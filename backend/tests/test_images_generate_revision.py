# backend/tests/test_images_generate_revision.py
#
# Contract tests for images-generate revisions (feature.app-skill.images-generate,
# images-generate.revision.*; plan docs/plans/image-edit-as-embed-version).
# A change to a generated image of the same chat becomes version N+1 of that
# image embed, pinned by the changing message; every version is billed once.

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

import pytest
from toon_format import decode as toon_decode

from backend.apps.images.tasks import image_revision
from backend.apps.images.tasks.image_revision import (
    RevisionPreconditionFailed,
    RevisionTarget,
    billing_event_id,
    union_file_keys,
)
from backend.core.api.app.services.embed_revision_authority import RevisionRefused, verify_producer_revision
from backend.shared.python_utils import generated_media_graph
from backend.shared.python_utils.chat_recovery_context import (
    RequiredRecoveryOutputError,
    VerifiedOutputProducer,
    active_verified_output_producer,
)
from backend.shared.python_utils.team_skill_billing import skill_billing_request

USER_ID = "user-1"
CHAT_ID = "chat-1"
IMAGE_ID = "3e1733df-1aea-5245-a3d0-b9a7179d9b48"
PARENT_ID = "parent-embed-1"
NEW_PARENT_ID = "parent-embed-2"
NEW_MESSAGE_ID = "message-2"
UPLOAD_ID = "9f0c33c6-0d0c-4d7e-9a8e-6d5b2a6f7a10"
INTENT_ID = "44444444-4444-4444-8444-444444444444"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Directus:
    """Collections as lists of rows; ``get_items`` honours ``filter[field][_eq]``."""

    def __init__(self, collections: Dict[str, List[Dict[str, Any]]]) -> None:
        self.collections = collections

    async def get_items(self, collection: str, params: Dict[str, Any] | None = None, **_: Any) -> List[Dict[str, Any]]:
        filters = {key[len("filter["):-len("][_eq]")]: value for key, value in (params or {}).items()
                   if key.startswith("filter[")}
        rows = [row for row in self.collections.get(collection, [])
                if all(row.get(field) == value for field, value in filters.items())]
        return [dict(row) for row in rows[: int((params or {}).get("limit") or len(rows) or 1)]]


def _world(**overrides: Any) -> Directus:
    image = {
        "id": "row-image", "embed_id": IMAGE_ID, "hashed_user_id": _hash(USER_ID),
        "hashed_chat_id": _hash(CHAT_ID), "hashed_message_id": _hash("message-1"),
        "parent_embed_id": PARENT_ID, "version_number": 1, "app_id": "images", "skill_id": "generated_image",
        "s3_file_keys": json.dumps([{"bucket": "chatfiles", "key": "u/v1_original.png"}]),
    }
    upload = {
        "id": "row-upload", "embed_id": UPLOAD_ID, "hashed_user_id": _hash(USER_ID),
        "hashed_chat_id": _hash(CHAT_ID), "parent_embed_id": None, "version_number": 1,
    }
    image.update(overrides)
    return Directus({
        "embeds": [image, upload],
        "upload_files": [
            {"id": "index-image", "embed_id": IMAGE_ID, "user_id": USER_ID, "file_size_bytes": 1000,
             "ai_detection": {"source": "openmates_image_generate"}},
            {"id": "index-upload", "embed_id": UPLOAD_ID, "user_id": USER_ID,
             "ai_detection": {"source": "upload"}},
        ],
        "embed_diffs": [],
    })


@pytest.fixture
def registered_producer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(image_revision.REVISIONS_ENV, "1")
    producer = VerifiedOutputProducer(
        classification="registered_ai", intent_id=INTENT_ID,
        task_id="task-1", task_name="apps.images.tasks.skill_generate", kwargs_binding="b" * 64,
        primary_embed_id=NEW_PARENT_ID, primary_message_id=NEW_MESSAGE_ID,
        target_chat_id=CHAT_ID, owner_hash=_hash(USER_ID),
    )
    token = active_verified_output_producer.set(producer)
    yield producer
    active_verified_output_producer.reset(token)


async def _find(directus: Directus, references: List[str], **kwargs: Any):
    return await image_revision.find_revision_target(
        directus, reference_embed_ids=references, chat_id=kwargs.get("chat_id", CHAT_ID),
        user_id=USER_ID, external_request=False,
    )


def _target(**overrides: Any) -> RevisionTarget:
    values = dict(
        embed_id=IMAGE_ID, parent_embed_id=PARENT_ID, current_version=1,
        s3_file_keys=({"bucket": "chatfiles", "key": "u/v1_original.png"},),
        upload_record_id="index-image", base_snapshot_required=True,
        hashed_message_id=_hash("message-1"), retained_size_bytes=1000,
        change_id=image_revision.change_identity(message_id=NEW_MESSAGE_ID, intent_id=INTENT_ID),
    )
    values.update(overrides)
    return RevisionTarget(**values)


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_a_generated_image_of_the_same_chat_is_revised_as_its_next_version(registered_producer) -> None:
    target = await _find(_world(), [IMAGE_ID])
    assert target is not None
    assert (target.embed_id, target.parent_embed_id) == (IMAGE_ID, PARENT_ID)
    assert (target.current_version, target.next_version) == (1, 2)
    assert target.base_snapshot_required is True
    assert target.upload_record_id == "index-image"
    assert (target.hashed_message_id, target.retained_size_bytes) == (_hash("message-1"), 1000)
    assert target.change_id == _target().change_id


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_uploads_other_chats_and_combinations_keep_making_a_new_image(registered_producer) -> None:
    assert await _find(_world(), [UPLOAD_ID]) is None
    assert await _find(_world(hashed_chat_id=_hash("other-chat")), [IMAGE_ID]) is None
    assert await _find(_world(), [IMAGE_ID], chat_id="other-chat") is None
    two = _world()
    two.collections["embeds"].append({**two.collections["embeds"][0], "id": "row-2", "embed_id": "second-image"})
    two.collections["upload_files"].append({**two.collections["upload_files"][0], "id": "i2", "embed_id": "second-image"})
    assert await _find(two, [IMAGE_ID, "second-image"]) is None
    # A pixel reference that is no generated image (no images-generate index) is no revision either.
    not_generated = _world()
    not_generated.collections["upload_files"][0]["ai_detection"] = {"source": "upload"}
    assert await _find(not_generated, [IMAGE_ID]) is None


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_no_revision_without_the_switch_or_a_registered_chat_producer(registered_producer, monkeypatch) -> None:
    monkeypatch.setenv(image_revision.REVISIONS_ENV, "0")
    assert await _find(_world(), [IMAGE_ID]) is None
    monkeypatch.setenv(image_revision.REVISIONS_ENV, "1")
    token = active_verified_output_producer.set(None)
    try:
        assert await _find(_world(), [IMAGE_ID]) is None
    finally:
        active_verified_output_producer.reset(token)


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_one_call_never_makes_two_next_versions_of_one_image(registered_producer) -> None:
    async def two_requests():
        return await _find(_world(), [IMAGE_ID]), await _find(_world(), [IMAGE_ID])

    first, second = await image_revision.run_with_batch_claims(two_requests())
    assert first is not None and second is None


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_existing_history_and_version_are_read_from_the_canonical_head(registered_producer) -> None:
    world = _world(version_number=3)
    world.collections["embed_diffs"].append({"embed_id": IMAGE_ID, "hashed_user_id": _hash(USER_ID),
                                              "version_number": 3, "id": "d3"})
    target = await _find(world, [IMAGE_ID])
    assert target is not None and target.next_version == 4 and target.base_snapshot_required is False


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version,images-generate.revision.each-version-billed-once
@pytest.mark.asyncio
async def test_a_change_that_lost_the_race_fails_before_any_charge() -> None:
    await image_revision.assert_current_version(_world(), _target(), user_id=USER_ID, chat_id=CHAT_ID)
    with pytest.raises(RevisionPreconditionFailed):
        await image_revision.assert_current_version(
            _world(version_number=2), _target(), user_id=USER_ID, chat_id=CHAT_ID,
        )
    with pytest.raises(RevisionPreconditionFailed):
        await image_revision.assert_current_version(
            _world(parent_embed_id="another-parent"), _target(), user_id=USER_ID, chat_id=CHAT_ID,
        )
    # The chat had not synced when version 1 was stored: no catalog marker, so the
    # extension would refuse the write. The change stops here, before any charge.
    for missing in ({"app_id": None, "skill_id": None}, {"skill_id": "generated_video"}):
        with pytest.raises(image_revision.RevisionNotSupported):
            await image_revision.assert_current_version(_world(**missing), _target(), user_id=USER_ID, chat_id=CHAT_ID)


def _revision_data(**overrides: Any) -> Dict[str, Any]:
    data = {"embed_id": IMAGE_ID, "parent_embed_id": PARENT_ID, "version_number": 2,
            "chat_id": CHAT_ID, "message_id": NEW_MESSAGE_ID}
    data.update(overrides)
    return data


REVISION = {"embed_id": IMAGE_ID, "parent_embed_id": PARENT_ID, "expected_version": 1,
            "base_snapshot_required": True, "hashed_message_id": _hash("message-1"),
            "s3_file_keys": [{"bucket": "chatfiles", "key": "u/v1_original.png"},
                             {"bucket": "chatfiles", "key": "u/v2_original.png"}]}


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_the_producer_seals_only_the_exact_next_version_of_the_canonical_child(registered_producer) -> None:
    await verify_producer_revision(_world(), producer=registered_producer, data=_revision_data(), revision=REVISION)
    for directus, data in [
        (_world(version_number=2), _revision_data()),
        (_world(), _revision_data(version_number=3)),
        (_world(), _revision_data(message_id="message-1")),
        (_world(), _revision_data(parent_embed_id=NEW_PARENT_ID)),
        (_world(hashed_chat_id=_hash("other-chat")), _revision_data()),
        (_world(app_id=None, skill_id=None), _revision_data()),
        (_world(hashed_message_id=_hash(NEW_MESSAGE_ID)), _revision_data()),
    ]:
        with pytest.raises(RevisionRefused):
            await verify_producer_revision(directus, producer=registered_producer, data=data, revision=REVISION)
    # The sealed copy may never carry fewer file keys than the head already has.
    with pytest.raises(RevisionRefused):
        await verify_producer_revision(_world(), producer=registered_producer, data=_revision_data(),
                                       revision={**REVISION, "s3_file_keys": REVISION["s3_file_keys"][1:]})
    assert issubclass(RevisionRefused, RequiredRecoveryOutputError)
    with pytest.raises(RequiredRecoveryOutputError):
        await verify_producer_revision(_world(), producer=registered_producer, data=_revision_data(),
                                       revision={**REVISION, "extra": 1})


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_the_file_index_keeps_the_files_of_every_version() -> None:
    old = [{"bucket": "chatfiles", "key": "u/v1_original.png"}, {"bucket": "chatfiles", "key": "u/v1_preview.webp"}]
    new = [{"bucket": "chatfiles", "key": "u/v2_original.png"}, {"bucket": "chatfiles", "key": "u/v1_preview.webp"}]
    assert union_file_keys(old, new) == [*old, new[0]]
    with pytest.raises(ValueError):
        union_file_keys(old, [{"bucket": "chatfiles"}])

    class Redis:
        def __init__(self) -> None:
            self.store: Dict[str, str] = {}

        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            self.store[key] = value

    redis = Redis()

    class Cache:
        @property
        async def client(self) -> Redis:
            return redis

    task = type("Task", (), {"_cache_service": Cache()})()
    union = await image_revision.cache_file_keys(task, target=_target(s3_file_keys=tuple(old)), new_keys=new)
    assert json.loads(redis.store[f"embed:{IMAGE_ID}:s3_file_keys"]) == union == [*old, new[0]]


# contract-test: direct surface=rest_api assertions=images-generate.revision.each-version-billed-once
def test_each_change_has_its_own_billing_identity_and_version_one_keeps_the_existing_one() -> None:
    change = image_revision.change_identity(message_id=NEW_MESSAGE_ID, intent_id=INTENT_ID)
    assert billing_event_id(IMAGE_ID, 1) == IMAGE_ID
    assert billing_event_id(IMAGE_ID, 1, change) == IMAGE_ID
    assert billing_event_id(IMAGE_ID, 2, change) == f"{IMAGE_ID}:v2:{change}"
    # A retry of the same task (same message, same producer intent) is the same charge.
    retry = image_revision.change_identity(message_id=NEW_MESSAGE_ID, intent_id=INTENT_ID)
    assert billing_event_id(IMAGE_ID, 2, retry) == billing_event_id(IMAGE_ID, 2, change)
    # Two changes that both saw version 1 (the head never advanced) are two charges.
    other_message = image_revision.change_identity(message_id="message-3", intent_id="55555555-5555-4555-8555-555555555555")
    other_intent = image_revision.change_identity(message_id=NEW_MESSAGE_ID, intent_id="66666666-6666-4666-8666-666666666666")
    ids = {billing_event_id(IMAGE_ID, 2, c) for c in (change, other_message, other_intent)}
    assert len(ids) == 3
    keys = {skill_billing_request({"user_id": USER_ID, "credits": 15}, None, event_id=i)[1]["idempotency_key"]
            for i in ids | {billing_event_id(IMAGE_ID, 1)}}
    assert len(keys) == 4 and f"app-skill:{IMAGE_ID}" in keys
    with pytest.raises(ValueError):
        billing_event_id(IMAGE_ID, 2)
    for invalid in (0, -1, True, "2"):
        with pytest.raises(ValueError):
            billing_event_id(IMAGE_ID, invalid, change)  # type: ignore[arg-type]  # the guard is the test subject


class EmbedService:
    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    async def send_embed_data_to_client(self, **kwargs: Any) -> bool:
        self.sent.append(kwargs)
        return True


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
@pytest.mark.asyncio
async def test_the_next_version_is_published_under_the_original_parent_with_its_snapshot_row() -> None:
    service = EmbedService()
    target = _target()
    ref = await image_revision.publish_revision(
        service, target=target, content={"app_id": "images", "status": "finished", "prompt": "red"},
        s3_file_keys=REVISION["s3_file_keys"], chat_id=CHAT_ID, message_id=NEW_MESSAGE_ID, user_id=USER_ID, user_id_hash=_hash(USER_ID),
        created_at=100, log_prefix="t",
    )
    sent = service.sent[0]
    assert ref == generated_media_graph.generated_media_embed_ref("images", IMAGE_ID)
    assert (sent["embed_id"], sent["parent_embed_id"], sent["version_number"]) == (IMAGE_ID, PARENT_ID, 2)
    assert sent["message_id"] == NEW_MESSAGE_ID and sent["embed_type"] == "generated_image"
    assert sent["version_history_rows"] == [{
        "embed_id": IMAGE_ID, "version_number": 2, "snapshot": sent["content_toon"], "created_at": 100,
    }]
    assert toon_decode(sent["content_toon"])["embed_ref"] == ref
    assert sent["producer_revision"] == REVISION


# contract-test: direct surface=rest_api assertions=images-generate.revision.message-shows-its-version
@pytest.mark.asyncio
async def test_the_changing_message_pins_the_version_it_made_instead_of_adopting_the_child() -> None:
    target = _target()
    revision_result = {"status": "finished", "embed_id": IMAGE_ID, "input_embed_ids": [IMAGE_ID],
                       **image_revision.revision_result_fields(target)}
    service = EmbedService()
    await generated_media_graph.finalize_generated_media_parent(
        service, parent_embed_id=NEW_PARENT_ID, app_id="images", skill_id="generate",
        children=[{"request_index": 0, "child_embed_id": IMAGE_ID, "embed_ref": target.embed_ref,
                   "result": revision_result, "revision": True}],
        failures=[], chat_id=CHAT_ID, message_id=NEW_MESSAGE_ID, user_id=USER_ID,
        user_id_hash=_hash(USER_ID), created_at=100, log_prefix="t",
    )
    sent = service.sent[0]
    content = toon_decode(sent["content_toon"])
    assert sent["embed_ids"] == [] and content["embed_ids"] == []
    assert content["status"] == "finished"
    assert content["pinned_embeds"] == [{"embed_id": IMAGE_ID, "version": 2, "embed_ref": target.embed_ref,
                                          "previous_version": 1}]
    assert sent["producer_final_children"] == [
        {"subject_id": IMAGE_ID, "output_kind": "embed", "output_version": 2},
        {"subject_id": IMAGE_ID, "output_kind": "diff", "output_version": 2},
    ]


# contract-test: direct surface=rest_api assertions=images-generate.revision.message-shows-its-version
@pytest.mark.asyncio
async def test_the_chat_model_is_told_the_image_got_a_new_version() -> None:
    target = _target()

    async def generate_one(task: Any, app_id: str, skill_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "finished", "embed_id": IMAGE_ID, "prompt": "red",
                **image_revision.revision_result_fields(target)}

    task = type("Task", (), {"request": type("R", (), {"id": "task-1"})()})()
    result = await generated_media_graph.run_generated_media_batch(
        task, app_id="images", skill_id="generate",
        arguments={"embed_id": NEW_PARENT_ID, "user_id": USER_ID, "requests": [{"prompt": "red"}]},
        generate_one=generate_one,
    )
    row = result["completed_results"][0]
    assert row["child_embed_id"] == IMAGE_ID and row["revision"] is True
    assert result["child_embed_ids"] == []
    completion = generated_media_graph.media_completion_result(row["result"])
    assert (completion["version"], completion["previous_version"]) == (2, 1)
    assert target.embed_ref in completion["revision_note"] and "version 2" in completion["revision_note"]


# contract-test: direct surface=rest_api assertions=images-generate.revision.each-version-billed-once
@pytest.mark.asyncio
async def test_a_new_version_keeps_counting_every_earlier_versions_bytes() -> None:
    from backend.shared.python_utils.generated_assets.service import index_generated_asset

    class Directus:
        def __init__(self) -> None:
            self.updated: Dict[str, Any] = {}
            self.storage = 5000

        async def update_item(self, collection: str, item_id: str, record: Dict[str, Any], **_: Any) -> Dict[str, Any]:
            self.updated = {"collection": collection, "id": item_id, **record}
            return {"id": item_id}

        async def get_user_fields_direct(self, user_id: str, fields: List[str]) -> Dict[str, Any]:
            return {"storage_used_bytes": self.storage}

        async def update_user(self, user_id: str, data: Dict[str, Any]) -> None:
            self.storage = data["storage_used_bytes"]

    directus = Directus()
    task = type("Task", (), {"_directus_service": directus})()
    stored = await index_generated_asset(
        task, user_id=USER_ID, embed_id=IMAGE_ID, media_type="image",
        files_metadata={"original": {"s3_key": "u/v2_original.png", "size_bytes": 300}},
        s3_base_url="https://bucket", aes_key_b64="k", nonce_b64="n", vault_wrapped_aes_key="w",
        created_at=1, content_hash_source=b"x", original_filename="a.png", content_type="image/png",
        log_prefix="t", existing_record_id="index-image", retained_size_bytes=1000,
    )
    assert stored is True
    # Deleting the embed frees file_size_bytes: it must cover version 1 and version 2.
    assert directus.updated["id"] == "index-image" and directus.updated["file_size_bytes"] == 1300
    assert directus.storage == 5300
    with pytest.raises(ValueError):
        await index_generated_asset(
            task, user_id=USER_ID, embed_id=IMAGE_ID, media_type="image", files_metadata={},
            s3_base_url="", aes_key_b64="", nonce_b64="", vault_wrapped_aes_key="", created_at=1,
            content_hash_source=b"", original_filename="", content_type="", log_prefix="t", retained_size_bytes=1,
        )


# contract-test: direct surface=rest_api assertions=images-generate.revision.same-embed-new-version
@pytest.mark.asyncio
async def test_the_sealed_copy_of_a_revision_carries_every_versions_file_keys(monkeypatch) -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    service = EmbedService.__new__(EmbedService)
    saved: Dict[str, Any] = {}

    async def allow(*_: Any, **__: Any) -> None:
        return None

    async def save(payload: Dict[str, Any], **kwargs: Any) -> None:
        saved.update(kwargs, payload=payload)

    async def publish(*_: Any, **__: Any) -> bool:
        return True

    monkeypatch.setattr(service, "_require_finished_publication_authority", allow, raising=False)
    monkeypatch.setattr(service, "_finished_recovery_required", lambda: True, raising=False)
    monkeypatch.setattr(service, "_volatile_incognito_publication_required", lambda: False, raising=False)
    monkeypatch.setattr(service, "_save_completed_embed_recovery", save, raising=False)
    monkeypatch.setattr(service, "_publish_prepared_embed", publish, raising=False)
    await service.send_embed_data_to_client(
        embed_id=IMAGE_ID, embed_type="generated_image", content_toon="x", chat_id=CHAT_ID,
        message_id=NEW_MESSAGE_ID, user_id=USER_ID, user_id_hash=_hash(USER_ID), status="finished",
        parent_embed_id=PARENT_ID, version_number=2, check_cache_status=False, producer_revision=REVISION,
    )
    assert saved["s3_file_keys"] == REVISION["s3_file_keys"]
    assert saved["producer_revision"]["hashed_message_id"] == _hash("message-1")
    assert saved["payload"]["payload"]["revision"] == {"base_version": 1, "base_snapshot_required": True}


# contract-test: direct surface=rest_api assertions=images-generate.revision.each-version-billed-once
@pytest.mark.asyncio
async def test_a_refused_revision_gives_a_personal_charge_back_once(monkeypatch) -> None:
    import httpx

    posts: List[Dict[str, Any]] = []

    class Client:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def post(self, url: str, json: Dict[str, Any], headers: Dict[str, str]) -> httpx.Response:
            posts.append({"url": url, **json})
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    event = billing_event_id(IMAGE_ID, 2, _target().change_id)
    common = dict(user_id=USER_ID, user_id_hash=_hash(USER_ID), app_id="images", skill_id="generate",
                  event_id=event, log_prefix="t")
    await image_revision.refund_refused_revision(credits=15, team_id=None, **common)
    assert posts[0]["url"].endswith("/internal/billing/refund")
    assert posts[0]["credits"] == 15 and posts[0]["idempotency_key"] == f"app-skill:{event}:refund"
    # Nothing charged, nothing refunded; Team billing has no refund route (logged gap).
    await image_revision.refund_refused_revision(credits=0, team_id=None, **common)
    await image_revision.refund_refused_revision(credits=15, team_id="team-1", **common)
    assert len(posts) == 1
