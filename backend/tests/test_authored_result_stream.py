"""Progressive authored cards: chunked streaming, early publication and later coordinates."""

import asyncio
import json
import random
from collections import OrderedDict
from types import SimpleNamespace

import pytest
from toon_format import decode

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.tasks import stream_consumer
from backend.apps.ai.utils.authored_result_fences import (
    get_authoring_definitions,
    normalize_authored_results_source,
)
from backend.apps.ai.utils.authored_result_stream import AuthoredResultsStreamParser, ProgressiveEnvelope
from backend.core.api.app.services import event_embed_enrichment
from backend.core.api.app.services.authored_result_progressive import drain_authored_result_background
from backend.core.api.app.services.authored_result_service import authored_child_id
from backend.shared.python_utils.chat_recovery_context import LegacyOutputContext, active_legacy_output_context
from backend.tests.test_authored_result_service import (  # noqa: F401 - pytest fixture import
    CHAT,
    MESSAGE,
    OWNER,
    OWNER_HASH,
    VAULT,
    authored_service,
)

INTRO = "Here are upcoming open source conferences in Europe.\n\n"
EXISTING_REF = "fosdem-2027-abc123"
EXISTING_ID = "44444444-4444-4444-8444-444444444444"
VENUE_COORDS = (50.8126, 4.3816)


def _event(local_id, title, **details):
    return {
        "id": local_id, "kind": "events.event", "title": title, "origin": "researched",
        "sources": [{"url": "https://example.org/events", "label": "Example events"}],
        "details": {"date_start": "2027-02-06", "date_end": "2027-02-07", **details},
    }


# Item 1 is invalid (unknown origin); later items must still publish.
# The title carries quote, backslash and unicode escapes for mid-escape splits.
ITEMS = [
    _event("first", 'Conf "One" \\ café', venue={"name": "ULB Solbosch", "city": "Brussels",
                                                       "lat": 1.0, "lon": 2.0}),
    {**_event("broken", "Broken"), "origin": "rumoured"},
    {"id": "again", "existing": EXISTING_REF},
    _event("online", "Online summit", online=True),
]
SOURCE = json.dumps({"schemaVersion": 1, "title": "Conferences", "items": ITEMS,
                     "view": {"mode": "auto"}}, indent=2, ensure_ascii=True)


def _split(text, seed, *, forced=()):
    """Split at random positions plus forced ones (inside escapes and strings)."""
    rng = random.Random(seed)
    cuts = set(rng.sample(range(1, len(text)), 25)) | {cut for cut in forced if 0 < cut < len(text)}
    bounds = [0, *sorted(cuts), len(text)]
    return [text[start:end] for start, end in zip(bounds, bounds[1:])]


def _escape_cuts(text):
    backslash = text.index("\\")
    return (backslash + 1, text.index("\\u00e9") + 3, text.index('"title"') + 3)


def _envelope():
    return ProgressiveEnvelope(source_byte_limit=1_000_000, item_limit=50)


# contract-test: direct surface=rest_api assertions=authored-results.streaming.progressive-cards
@pytest.mark.parametrize("seed", range(12))
def test_parser_yields_each_valid_entry_once_and_matches_the_closed_block(seed):
    envelope, seen, text = _envelope(), [], ""
    for chunk in _split(SOURCE, seed, forced=_escape_cuts(SOURCE)):
        text += chunk
        seen.extend(entry.local_id for entry in envelope.feed_source(text))
        if seen and len(seen) < 3:
            assert envelope.pending  # more entries can follow: placeholders stay
    one_shot = normalize_authored_results_source(SOURCE)
    assert not envelope.abandoned and not envelope.pending
    assert seen == one_shot.order == ["first", "again", "online"]
    assert envelope.warnings == one_shot.warnings == [{"code": "invalid_item", "path": "items[1]"}]
    assert envelope.parser.title == "Conferences"


# contract-test: direct surface=rest_api assertions=authored-results.streaming.progressive-cards
def test_entry_is_offered_only_once_its_json_value_is_complete():
    envelope = _envelope()
    first = json.dumps(ITEMS[0])
    prefix = '{"schemaVersion": 1, "items": [' + first[:-1]
    assert envelope.feed_source(prefix) == [] and envelope.pending
    assert [entry.local_id for entry in envelope.feed_source(prefix + "}")] == ["first"]


# contract-test: direct surface=rest_api assertions=authored-results.streaming.progressive-cards
@pytest.mark.parametrize("source", [
    '{"schemaVersion": 2, "items": [' + json.dumps(ITEMS[0]) + "]}",
    '{"schemaVersion": 1, "extra": 1, "items": [' + json.dumps(ITEMS[0]) + "]}",
    '{"schemaVersion": 1, "items": [{"id": "x", "id": "y"}]}',
    '["schemaVersion", 1]',
])
def test_envelope_that_cannot_be_valid_offers_nothing(source):
    envelope = _envelope()
    assert envelope.feed_source(source) == []
    assert envelope.abandoned
    assert not normalize_authored_results_source(source).items


# contract-test: direct surface=rest_api assertions=authored-results.streaming.progressive-cards
def test_entries_wait_for_schema_version_and_repeated_labels_are_dropped():
    late = '{"items": [' + json.dumps(ITEMS[0]) + ", " + json.dumps(ITEMS[0]) + '], "schemaVersion": 1}'
    envelope = _envelope()
    assert envelope.feed_source(late[:late.index('"schemaVersion"')]) == []
    accepted = envelope.feed_source(late)
    assert [entry.local_id for entry in accepted] == ["first"]
    assert envelope.duplicated_labels == {"first"}
    assert normalize_authored_results_source(late).order == []


# contract-test: supporting surface=rest_api assertions=authored-results.streaming.progressive-cards
def test_parser_tolerates_any_split_of_strings_and_escapes():
    parser = AuthoredResultsStreamParser(source_byte_limit=1_000_000)
    entries = []
    for char in SOURCE:
        entries.extend(parser.feed(char))
    assert [json.loads(entry.raw)["id"] for entry in entries] == [item["id"] for item in ITEMS]
    assert parser.closed and not parser.abandoned


def _existing_card_body():
    definition = get_authoring_definitions()["events.event"]
    return {
        "type": definition["backend_type"], "app_id": definition["app_id"],
        "skill_id": definition["skill_id"], "title": "FOSDEM 2027", "status": "finished",
        "authoring": {"schema_version": 1, "kind": "events.event", "origin": "researched", "sources": []},
    }


@pytest.fixture
def streamed(request, monkeypatch):
    """Run the real stream consumer against the real authored-result service."""
    h = request.getfixturevalue("authored_service")
    timeline: list[tuple] = []
    geocode = {"released": None, "timed_out": False, "calls": 0}
    original_publish = h.cache.publish

    async def publish(channel, value):
        await original_publish(channel, value)
        payload = h.cache.events[-1][1]["payload"]
        timeline.append(("publish", payload["embed_id"], payload["status"], decode(payload["content"])))
        if payload["type"] == "authored_results" and payload["status"] == "finished":
            geocode["released"].set()

    async def geocode_address(*_args, **_kwargs):
        # Resolves only after the carrier finished: publication cannot wait for it.
        geocode["calls"] += 1
        try:
            await asyncio.wait_for(geocode["released"].wait(), timeout=5)
        except asyncio.TimeoutError:
            geocode["timed_out"] = True
            return None
        timeline.append(("geocoded",))
        return VENUE_COORDS

    monkeypatch.setattr(h.cache, "publish", publish)
    monkeypatch.setattr(event_embed_enrichment, "geocode_address", geocode_address)
    monkeypatch.setattr(event_embed_enrichment, "_cache", OrderedDict())
    from backend.core.api.app.services import embed_service as embed_service_module

    class _SharedService(embed_service_module.EmbedService):
        """Every stream-side ``EmbedService(...)`` is the fixture's real service.

        A subclass (not a lambda) keeps class-level helpers that embed_service.py
        reaches through the module name, e.g. ``EmbedService._slugify_direct_ref_base``.
        """

        def __new__(cls, *_args, **_kwargs):
            return h.service

    monkeypatch.setattr(embed_service_module, "EmbedService", _SharedService)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult",
                        lambda _: SimpleNamespace(state="STARTED"))

    def run(chunks, *, fail_after=False):
        async def main_stream(**_kwargs):
            for index, chunk in enumerate(chunks):
                timeline.append(("yield", index))
                yield chunk
            if fail_after:
                raise RuntimeError("provider failed")

        async def consume():
            geocode["released"] = asyncio.Event()
            await h.put_reference(EXISTING_ID, _existing_card_body(), parent="11111111-0000-4000-8000-000000000000")
            return await stream_consumer._consume_main_processing_stream(
                task_id="66666666-6666-4666-8666-666666666666", request_data=ask_request,
                preprocessing_result=PreprocessingResult(can_proceed=True), base_instructions={},
                directus_service=SimpleNamespace(), encryption_service=SimpleNamespace(),
                user_vault_key_id=VAULT, all_mates_configs=[], discovered_apps_metadata={},
                cache_service=None,
            )

        monkeypatch.setattr(stream_consumer, "handle_main_processing", main_stream)
        ask_request = AskSkillRequest(
            chat_id=CHAT, message_id=MESSAGE, user_id=OWNER, user_id_hash=OWNER_HASH,
            message_history=[], is_incognito=True, embed_file_path_index={EXISTING_REF: EXISTING_ID},
        )
        token = active_legacy_output_context.set(LegacyOutputContext(
            owner_id=OWNER, owner_hash=OWNER_HASH, legacy_task_identity="a" * 64,
            root_chat_id=CHAT, root_turn_id=None, root_user_message_id=MESSAGE, target_chat_id=CHAT,
        ))
        try:
            result = asyncio.run(consume())
        finally:
            active_legacy_output_context.reset(token)
        carrier = next(entry[1] for entry in timeline
                       if entry[0] == "publish" and entry[3].get("type") == "authored_results")
        return SimpleNamespace(result=result, timeline=timeline, carrier=carrier, geocode=geocode, h=h)

    return run


def _chunks(seed):
    return [INTRO, "```openmates_embeds\n", *_split(SOURCE + "\n", seed, forced=_escape_cuts(SOURCE)),
            "```\n\nAll dates are from the official sites."]


def _first(timeline, predicate):
    return next(index for index, entry in enumerate(timeline) if predicate(entry))


def _published(timeline, embed_id, status="finished"):
    return [index for index, entry in enumerate(timeline)
            if entry[0] == "publish" and entry[1] == embed_id and entry[2] == status]


# contract-test: direct surface=rest_api assertions=authored-results.streaming.progressive-cards,authored-results.maps.source-faithful-geometry
@pytest.mark.parametrize("seed", [3, 11])
def test_stream_publishes_intro_then_each_card_before_the_fence_closes(streamed, seed):
    chunks = _chunks(seed)
    run = streamed(chunks)
    text, timeline, carrier = run.result[0], run.timeline, run.carrier
    first, online = authored_child_id(carrier, "first"), authored_child_id(carrier, "online")
    broken = authored_child_id(carrier, "broken")
    closing = _first(timeline, lambda entry: entry == ("yield", len(chunks) - 1))

    # The intro is streamed text ahead of the block's single carrier reference.
    assert text.startswith(INTRO.strip())
    assert text.index(INTRO.strip()) < text.index(carrier) and "schemaVersion" not in text
    assert _first(timeline, lambda entry: entry == ("yield", 1)) < _first(
        timeline, lambda entry: entry[0] == "publish")

    # Each valid card is published finished before the closing fence is read.
    assert _published(timeline, first)[0] < closing
    assert _published(timeline, online)[0] < closing
    assert _published(timeline, broken) == []
    processing = [entry[3] for entry in timeline[:closing]
                  if entry[0] == "publish" and entry[1] == carrier and entry[2] == "processing"]
    assert any(content.get("pending_count") == 1 for content in processing)
    # processing[0] is the empty placeholder, created before any member exists.
    assert processing[0]["embed_ids"] == [] and "member_ids" not in processing[0]
    assert any(content.get("member_ids") == [first] for content in processing)
    assert processing[-1]["member_ids"] == [first, EXISTING_ID, online]

    # The finished carrier lists members in source order with no pending placeholders.
    final = _published(timeline, carrier)[-1]
    content = timeline[final][3]
    assert content["member_ids"] == [first, EXISTING_ID, online]
    assert content["embed_ids"] == [first, online]
    assert "pending_count" not in content
    assert content["validation"]["warnings"] == [{"code": "invalid_item", "path": "items[1]"}]

    # Published first without coordinates (model-written ones are dropped),
    # then the same card again with the server lookup's coordinates.
    first_publications = _published(timeline, first)
    assert "lat" not in timeline[first_publications[0]][3]["venue"]
    assert first_publications[0] < final < _first(timeline, lambda entry: entry == ("geocoded",))
    assert len(first_publications) == 2 and first_publications[-1] > final
    venue = timeline[first_publications[-1]][3]["venue"]
    assert (venue["lat"], venue["lon"]) == VENUE_COORDS
    assert run.geocode == {"released": run.geocode["released"], "timed_out": False, "calls": 1}
    # The online event never gets a lookup or a map pin.
    assert all("lat" not in timeline[index][3].get("venue", {}) for index in _published(timeline, online))


def _shape(h, carrier):
    """Carrier and card state with carrier-specific ids replaced by local labels."""
    labels = {authored_child_id(carrier, label): label for label in ("first", "broken", "again", "online")}
    labels[EXISTING_ID] = "existing"
    record = h.record(carrier)
    content = decode(asyncio.run(h.service._get_cached_embed_toon(carrier, VAULT)))
    cards = {}
    for child in content["embed_ids"]:
        card = decode(asyncio.run(h.service._get_cached_embed_toon(child, VAULT)))
        cards[labels[child]] = {key: value for key, value in card.items() if key != "embed_ref"}
    return {
        "status": record["status"], "title": content["title"], "source_json": content["source_json"],
        "member_ids": [labels[value] for value in content["member_ids"]],
        "embed_ids": [labels[value] for value in content["embed_ids"]],
        "view": {"mode": content["view"]["mode"], "embeds": [labels[v] for v in content["view"]["embeds"]]},
        "items": [(labels[item["embed_id"]], item["kind"], item["title"]) for item in content["items"]],
        "validation": content["validation"], "pending": content.get("pending_count"), "cards": cards,
    }


# contract-test: direct surface=rest_api assertions=authored-results.streaming.progressive-cards
def test_progressive_final_state_equals_the_one_shot_path(streamed):
    run = streamed(_chunks(5))
    h = run.h
    progressive = _shape(h, run.carrier)

    async def one_shot():
        carrier = await h.create()
        token = active_legacy_output_context.set(LegacyOutputContext(
            owner_id=OWNER, owner_hash=OWNER_HASH, legacy_task_identity="a" * 64,
            root_chat_id=CHAT, root_turn_id=None, root_user_message_id=MESSAGE, target_chat_id=CHAT,
        ))
        try:
            h.service.authoring_reference_index = {EXISTING_REF: EXISTING_ID}
            assert await h.service.update_json_content_embed_content(
                source_language="openmates_embeds", embed_id=carrier, source_json=SOURCE,
                status="finished", chat_id=CHAT, user_id=OWNER, user_id_hash=OWNER_HASH,
                user_vault_key_id=VAULT,
            )
            await drain_authored_result_background(MESSAGE)
        finally:
            active_legacy_output_context.reset(token)
        return carrier

    carrier = asyncio.run(one_shot())
    assert _shape(h, carrier) == progressive
    assert progressive["member_ids"] == ["first", "existing", "online"]
    assert progressive["cards"]["first"]["venue"]["lat"] == VENUE_COORDS[0]


# contract-test: direct surface=rest_api assertions=authored-results.streaming.progressive-cards
def test_cancellation_mid_item_never_finishes_the_partial_card(streamed):
    cut = SOURCE.index('"id": "online"') + 8
    chunks = [INTRO, "```openmates_embeds\n", *_split(SOURCE[:cut] + "\n", 2), '"private-partial": "x\n']
    run = streamed(chunks, fail_after=True)
    timeline, carrier = run.timeline, run.carrier
    first, online = authored_child_id(carrier, "first"), authored_child_id(carrier, "online")
    assert "private-partial" not in run.result[0]
    assert _published(timeline, online) == [] and _published(timeline, online, "processing") == []
    final = timeline[_published(timeline, carrier)[-1]][3]
    # Cards completed before the interruption stay; the cut-off one never appears.
    assert final["status"] == "finished" and "pending_count" not in final
    assert final["member_ids"] == [first, EXISTING_ID]
    assert final["validation"]["warnings"] == [{"code": "interrupted", "path": "items"}]
    assert run.h.record(carrier)["embed_ids"] == [first]


# contract-test: supporting surface=rest_api assertions=authored-results.maps.source-faithful-geometry
def test_failed_venue_lookup_leaves_the_published_card_without_coordinates(streamed, monkeypatch):
    async def no_result(*_args, **_kwargs):
        return None

    monkeypatch.setattr(event_embed_enrichment, "geocode_address", no_result)
    run = streamed(_chunks(7))
    first = authored_child_id(run.carrier, "first")
    publications = _published(run.timeline, first)
    assert len(publications) == 1
    assert "lat" not in run.timeline[publications[0]][3]["venue"]
    assert "lat" not in decode(asyncio.run(run.h.service._get_cached_embed_toon(first, VAULT)))["venue"]

