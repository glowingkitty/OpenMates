"""Deterministic tests of public, bounded and strictly grounded Mercury clues."""
# contract-test-file: supporting surface=rest_api assertions=home-search.location.precision,home-search.output.safe-and-truthful

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.home import location_clues as clues
from backend.shared.providers.inception import InceptionError, InceptionUsage


def clue(**overrides):
    return {"anchor_name": "Alexanderplatz", "anchor_type": "station", "relation": "distance",
            "quantity": 500, "unit": "m", "evidence_quote": "500 m from Alexanderplatz",
            "locality": "Berlin", **overrides}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.delenv("HOME_LOCATION_REFINEMENT_ENABLED", raising=False)
    resolve = AsyncMock(return_value="private-key")
    complete = AsyncMock()
    factory = SimpleNamespace(options=None)

    def client(key, **options):
        assert key == "private-key"
        factory.options = options
        return SimpleNamespace(complete=complete)

    monkeypatch.setattr(clues, "resolve_api_key", resolve)
    monkeypatch.setattr(clues, "InceptionClient", client)

    def response(items=None, *, content=None, finish="stop"):
        complete.return_value = SimpleNamespace(
            choices=[{"finish_reason": finish, "message": {"content": content if content is not None else json.dumps({"clues": items or []})}}],
            usage=InceptionUsage(prompt_tokens=60, completion_tokens=30, total_tokens=90,
                                prompt_tokens_details={"cached_tokens": 12}),
        )

    response([clue()])
    return SimpleNamespace(resolve=resolve, complete=complete, factory=factory, response=response)


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_one_structured_bounded_call_with_usage_and_public_data_only(provider):
    result = await clues.extract_location_clues({
        "city": "Berlin", "description": "500 m from Alexanderplatz. mail me at agent@example.org or +49 30 12345678 https://private.example/x",
        "contact": "Private Agent", "chat_history": "private-chat", "user_id": "private-user",
    }, secrets_manager=None)
    assert result["status"] == "ok"
    assert result["clues"] == [clue()]
    assert result["usage"]["prompt_tokens_details"]["cached_tokens"] == 12
    provider.complete.assert_awaited_once()
    request = provider.complete.call_args.args[0]
    assert request.model == "mercury-3"
    assert request.reasoning_effort == "instant"
    assert request.max_completion_tokens == 600
    assert request.response_format["json_schema"]["strict"] is True
    assert request.tools is None
    assert provider.factory.options == {"timeout": 1.5, "max_retries": 0}
    public = request.messages[1]["content"]
    for private in ("agent@example.org", "12345678", "private.example", "Private Agent", "private-chat", "private-user"):
        assert private not in public


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_input_bound_preserves_advertised_locality(provider):
    provider.response([])
    await clues.extract_location_clues({"city": "Berlin", "district": "Mitte", "description": "x" * 20000}, secrets_manager=None)
    source = provider.complete.call_args.args[0].messages[1]["content"]
    assert len(source) <= 6000
    assert source.startswith("city: Berlin\ndistrict: Mitte")


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"anchor_name": "Potsdamer Platz"}, {"evidence_quote": "10 m from Alexanderplatz"},
    {"quantity": 50}, {"quantity": True}, {"quantity": float("nan")},
    {"unit": "km"}, {"locality": "Paris"}, {"anchor_type": "coordinates"},
    {"relation": "walk_time", "quantity": 500, "unit": "minutes"},
    {"relation": "near"}, {"latitude": 52.5},
    {"evidence_quote": "500 M FROM ALEXANDERPLATZ"},
])
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.output.safe-and-truthful
async def test_ungrounded_or_invented_fields_are_invalid(provider, override):
    provider.response([clue(**override)])
    result = await clues.extract_location_clues({"city": "Berlin", "description": "500 m from Alexanderplatz"}, secrets_manager=None)
    assert result["status"] == "invalid"
    assert result["clues"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("description,evidence", [
    ("Not 500 m from Alexanderplatz", "500 m from Alexanderplatz"),
    ("Unser Maklerbüro ist 500 m from Alexanderplatz", "500 m from Alexanderplatz"),
    ("Our office is 500 m from Alexanderplatz", "500 m from Alexanderplatz"),
    ("Drive 500 m from Alexanderplatz", "500 m from Alexanderplatz"),
    ("By train 500 m from Alexanderplatz", "500 m from Alexanderplatz"),
    ("At least 500 m from Alexanderplatz", "At least 500 m from Alexanderplatz"),
])
# contract-test: supporting surface=rest_api assertions=home-search.location.precision,home-search.output.safe-and-truthful
async def test_cropped_quotes_cannot_hide_unsafe_context(provider, description, evidence):
    provider.response([clue(evidence_quote=evidence)])
    result = await clues.extract_location_clues({"city": "Berlin", "description": description}, secrets_manager=None)
    assert result["status"] == "invalid"
    assert result["usage"]["total_tokens"] == 90


@pytest.mark.asyncio
@pytest.mark.parametrize("description,overrides", [
    ("5 Minuten zu Fuß zum Alexanderplatz", {"relation": "walk_time", "quantity": 5, "unit": "minutes"}),
    ("0,5 km vom Alexanderplatz", {"quantity": 0.5, "unit": "km"}),
    ("Near Alexanderplatz", {"relation": "near", "quantity": None, "unit": None}),
    ("In Alexanderplatz", {"relation": "inside", "quantity": None, "unit": None}),
])
# contract-test: supporting surface=rest_api assertions=home-search.location.precision
async def test_explicit_supported_relationships(provider, description, overrides):
    provider.response([clue(evidence_quote=description, **overrides)])
    result = await clues.extract_location_clues({"city": "Berlin", "description": description}, secrets_manager=None)
    assert result["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("content,finish", [("not JSON", "stop"), ('{"clues":[]}', "length"), ('{"clues":[],"latitude":52}', "stop")])
# contract-test: supporting surface=rest_api assertions=home-search.output.safe-and-truthful
async def test_invalid_or_truncated_completion_is_not_no_clues(provider, content, finish):
    provider.response(content=content, finish=finish)
    result = await clues.extract_location_clues({"city": "Berlin"}, secrets_manager=None)
    assert result["status"] == "invalid"


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_positive_and_negative_cache_ttl_usage_and_text_invalidation(provider):
    values = {}
    cache = SimpleNamespace(get=AsyncMock(side_effect=lambda key: values.get(key)))

    async def save(key, value, ttl):
        values[key] = value

    cache.set = AsyncMock(side_effect=save)
    listing = {"id": "123", "city": "Berlin", "description": "500 m from Alexanderplatz"}
    first = await clues.extract_location_clues(listing, secrets_manager=None, cache_service=cache)
    second = await clues.extract_location_clues(listing, secrets_manager=None, cache_service=cache)
    assert first["status"] == second["status"] == "ok"
    assert "usage" in first and "usage" not in second
    assert cache.set.call_args.kwargs["ttl"] == 86400
    provider.complete.assert_awaited_once()
    provider.response([])
    third = await clues.extract_location_clues({**listing, "description": "No useful clue"}, secrets_manager=None, cache_service=cache)
    assert third["status"] == "no_clues"
    assert cache.set.call_args.kwargs["ttl"] == 3600
    assert provider.complete.await_count == 2
    assert len(values) == 2


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_disabled_empty_and_provider_outage_do_not_cache(provider):
    cache = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    provider.complete.side_effect = InceptionError("private provider details")
    assert (await clues.extract_location_clues({}, secrets_manager=None))["status"] == "no_clues"
    assert (await clues.extract_location_clues({"city": "Berlin"}, secrets_manager=None, cache_service=cache))["status"] == "unavailable"
    cache.set.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_disabled_switch_performs_no_credential_or_cache_calls(provider, monkeypatch):
    monkeypatch.setenv("HOME_LOCATION_REFINEMENT_ENABLED", "false")
    cache = SimpleNamespace(get=AsyncMock(), set=AsyncMock())
    assert (await clues.extract_location_clues({"city": "Berlin"}, secrets_manager=None, cache_service=cache))["status"] == "disabled"
    provider.resolve.assert_not_awaited()
    cache.get.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_deadline_includes_key_lookup(provider, monkeypatch):
    monkeypatch.setattr(clues, "EXTRACTION_TIMEOUT_SECONDS", 0.01)

    async def slow_key(_manager):
        await asyncio.sleep(10)

    provider.resolve.side_effect = slow_key
    assert (await clues.extract_location_clues({"city": "Berlin"}, secrets_manager=None))["status"] == "unavailable"
    provider.complete.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_inflight_dedup_and_cancellation_preserve_other_waiter(provider):
    started, release = asyncio.Event(), asyncio.Event()
    original = provider.complete.return_value

    async def complete(_request):
        started.set()
        await release.wait()
        return original

    provider.complete.side_effect = complete
    listing = {"city": "Berlin", "description": "500 m from Alexanderplatz"}
    first = asyncio.create_task(clues.extract_location_clues(listing, secrets_manager=None))
    await started.wait()
    second = asyncio.create_task(clues.extract_location_clues(listing, secrets_manager=None))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert (await second)["status"] == "ok"
    provider.complete.assert_awaited_once()
    assert not clues._INFLIGHT


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_inflight_usage_is_counted_once(provider):
    listing = {"city": "Berlin", "description": "500 m from Alexanderplatz"}
    results = await asyncio.gather(*(clues.extract_location_clues(listing, secrets_manager=None) for _ in range(3)))
    assert all(result["status"] == "ok" for result in results)
    assert sum("usage" in result for result in results) == 1
    provider.complete.assert_awaited_once()


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_cache_failure_still_attempts_provider_and_does_not_leak_details(provider, caplog):
    cache = SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("private-cache-data")),
                            set=AsyncMock(side_effect=RuntimeError("private-cache-data")))
    result = await clues.extract_location_clues({"city": "Berlin", "description": "500 m from Alexanderplatz"},
                                              secrets_manager=None, cache_service=cache)
    assert result["status"] == "ok"
    assert "private-cache-data" not in caplog.text
    provider.complete.assert_awaited_once()


@pytest.mark.asyncio
# contract-test: infrastructure
# Retained helper mechanics; no live discovery or historical rendering proof is claimed.
async def test_last_waiter_cancellation_cancels_provider(provider):
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def complete(_request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    provider.complete.side_effect = complete
    task = asyncio.create_task(clues.extract_location_clues({"city": "Berlin"}, secrets_manager=None))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(cancelled.wait(), 1)
    assert not clues._INFLIGHT
