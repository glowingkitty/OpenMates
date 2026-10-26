"""Real authored materialization, cache, context, and publication contracts."""

import base64
import copy
import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from toon_format import decode, encode

from backend.apps.ai.utils.authored_result_fences import get_authoring_definitions
from backend.core.api.app.services.authored_result_service import authored_child_id, authored_children_for_context
from backend.core.api.app.services.embed_service import EmbedService
from backend.core.api.app.services.embed_version_transaction_service import is_hosted_project_embed_id
from backend.shared.python_utils.chat_recovery_context import (
    RecoveryOutputContext,
    RequiredRecoveryOutputError,
    active_recovery_output_context,
    active_verified_output_producer,
)
from backend.tests.test_authored_result_content import VALID_KIND_DETAILS, valid_authored_item


OWNER = "11111111-1111-4111-8111-111111111111"
CHAT = "22222222-2222-4222-8222-222222222222"
MESSAGE = "33333333-3333-4333-8333-333333333333"
OWNER_HASH = "a" * 64
VAULT = "test-vault"


class _OpaqueEncryption:
    """Make encryption boundaries observable without claiming real cryptography."""

    async def encrypt_with_user_key(self, content, vault_key_id):
        return "vault:v1:test:" + base64.b64encode(content.encode()).decode(), "test-version"

    async def decrypt_with_user_key(self, content, vault_key_id):
        assert content.startswith("vault:v1:test:")
        return base64.b64decode(content.removeprefix("vault:v1:test:")).decode()


class _Cache:
    def __init__(self):
        self.values = {}
        self.events = []
        self.order = []
        self.pending = []
        self.fail_publish = False

    @property
    async def client(self):
        return self

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **_kwargs):
        self.values[key] = value
        self.order.append(("refill", key))
        return True

    async def cache_required_ai_embed(self, owner, chat_id, embed_id, value, **_kwargs):
        self.values[f"embed:{embed_id}"] = value
        self.order.append(("cache", embed_id))
        return True

    async def publish(self, channel, value):
        if self.fail_publish:
            raise RuntimeError("publication unavailable")
        self.events.append((channel, json.loads(value)))
        self.order.append(("publish", self.events[-1][1]["payload"]["embed_id"]))
        return 1

    async def add_pending_embed(self, owner_id, embed_id):
        self.pending.append((owner_id, embed_id))
        return True

    async def mark_ai_context_pending_persistence(self, *_args):
        return True


@pytest.fixture
def authored_service(monkeypatch):
    cache = _Cache()
    service = EmbedService(cache, SimpleNamespace(), _OpaqueEncryption())
    scheduled = []
    monkeypatch.setattr(service, "_schedule_embed_persistence_fallback", scheduled.append)

    async def save_batch(payloads):
        cache.order.append(("recovery", [payload["payload"]["embed_id"] for payload in payloads]))

    async def save_one(payload, **_kwargs):
        cache.order.append(("recovery-one", payload["payload"]["embed_id"]))

    monkeypatch.setattr(service, "_save_completed_embed_recovery_batch", AsyncMock(side_effect=save_batch))
    monkeypatch.setattr(service, "_save_completed_embed_recovery", AsyncMock(side_effect=save_one))
    args = dict(chat_id=CHAT, user_id=OWNER, user_id_hash=OWNER_HASH, user_vault_key_id=VAULT)

    async def create():
        created = await service.create_json_content_embed_placeholder(
            source_language="openmates_embeds", message_id=MESSAGE,
            task_id="66666666-6666-4666-8666-666666666666", **args,
        )
        assert created is not None
        assert json.loads(created["embed_reference"]) == {
            "type": "authored_results", "embed_id": created["embed_id"],
        }
        cache.events.clear()
        cache.order.clear()
        return created["embed_id"]

    async def update(carrier, items=None, *, status="finished", raw=None, **overrides):
        source = raw if raw is not None else json.dumps({
            "schemaVersion": 1, "title": "Supplied private results", "items": items or [],
            "view": {"mode": "cards", "items": [item["id"] for item in items or []]},
        })
        return await service.update_json_content_embed_content(
            source_language="openmates_embeds", embed_id=carrier,
            source_json=source, status=status, **{**args, **overrides},
        )

    def record(embed_id):
        return json.loads(cache.values[f"embed:{embed_id}"])

    async def content(embed_id):
        return decode(await service._get_cached_embed_toon(embed_id, VAULT))

    async def put_reference(embed_id, body, *, owner_hash=OWNER_HASH, chat_id=CHAT, parent=None):
        encrypted, _ = await service.encryption_service.encrypt_with_user_key(encode(body), VAULT)
        row = {"embed_id": embed_id, "type": body["type"], "status": "finished",
               "chat_id": chat_id, "message_id": MESSAGE, "hashed_user_id": owner_hash,
               "encrypted_content": encrypted}
        if parent:
            row["parent_embed_id"] = parent
        cache.values[f"embed:{embed_id}"] = json.dumps(row)

    return SimpleNamespace(service=service, cache=cache, scheduled=scheduled,
                           create=create, update=update, record=record, content=content,
                           put_reference=put_reference)


@contextmanager
def _recovery_scope():
    context = RecoveryOutputContext(
        owner_id=OWNER, owner_hash=OWNER_HASH, root_chat_id=CHAT, target_chat_id=CHAT,
        turn_id=MESSAGE, preflight_id="77777777-7777-4777-8777-777777777777",
        inference_task_id="66666666-6666-4666-8666-666666666666",
        public_key="test-public-key-unused-by-fake-recovery", key_version=1,
    )
    token = active_recovery_output_context.set(context)
    try:
        yield
    finally:
        active_recovery_output_context.reset(token)


# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.groups.same-response-and-reuse
@pytest.mark.asyncio
async def test_retry_keeps_child_identity_and_does_not_republish_or_duplicate(authored_service):
    h = authored_service
    carrier = await h.create()
    items = [valid_authored_item("events.event", "event"), valid_authored_item("nutrition.recipe", "recipe")]
    assert await h.update(carrier, items)
    children = h.record(carrier)["embed_ids"]
    assert len(children) == len(set(children)) == 2
    assert all(uuid.UUID(child).version == 4 and not is_hosted_project_embed_id(child) for child in children)
    assert [event["payload"]["embed_id"] for _, event in h.cache.events] == [*children, carrier]
    before = copy.deepcopy((h.cache.values, h.cache.events, h.scheduled))
    assert await h.update(carrier, items)
    assert (h.cache.values, h.cache.events, h.scheduled) == before
    assert await h.update(carrier, status="error", raw="")
    assert h.record(carrier)["status"] == "finished"
    other_carrier = await h.create()
    assert await h.update(other_carrier, items)
    assert set(h.record(other_carrier)["embed_ids"]).isdisjoint(children)


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
def test_retry_stable_children_remain_ordinary_without_registered_project_identity():
    carrier, other_carrier = str(uuid.uuid4()), str(uuid.uuid4())
    first = authored_child_id(carrier, "first")
    assert authored_child_id(carrier, "first") == first
    ordinary = {first, authored_child_id(carrier, "second"), authored_child_id(other_carrier, "first")}
    assert len(ordinary) == 3
    assert all(uuid.UUID(embed).version == 4 and not is_hosted_project_embed_id(embed) for embed in ordinary)
    token = active_verified_output_producer.set(SimpleNamespace(
        classification="registered_ai", primary_embed_id=carrier, intent_id=str(uuid.uuid4()),
    ))
    try:
        registered = EmbedService._registered_child_embed_id(carrier, 0)
        assert uuid.UUID(registered).version == 5 and is_hosted_project_embed_id(registered)
        assert registered not in ordinary
        assert authored_child_id(carrier, "first") == first
    finally:
        active_verified_output_producer.reset(token)


# contract-test: direct surface=rest_api assertions=authored-results.eligibility.all-suitable-results,authored-results.content.typed-and-useful,authored-results.groups.same-response-and-reuse
@pytest.mark.asyncio
async def test_all_admitted_kinds_materialize_as_ordered_existing_typed_children(authored_service):
    h = authored_service
    carrier = await h.create()
    items = [valid_authored_item(kind, f"item{index}") for index, kind in enumerate(VALID_KIND_DETAILS)]
    assert len(items) == len(get_authoring_definitions()) == 25
    assert {"tv.movie", "tv.series"}.issubset({item["kind"] for item in items})
    assert await h.update(carrier, items)
    parent = await h.content(carrier)
    assert parent["status"] == "finished" and parent["validation"]["status"] == "valid", parent["validation"]
    assert [item["kind"] for item in parent["items"]] == list(VALID_KIND_DETAILS)
    assert parent["view"] == {"mode": "cards", "embeds": h.record(carrier)["embed_ids"]}
    definitions = get_authoring_definitions()
    for supplied, member in zip(items, parent["items"], strict=True):
        row, body = h.record(member["embed_id"]), await h.content(member["embed_id"])
        definition = definitions[supplied["kind"]]
        assert body["type"] == row["type"] == definition["backend_type"]
        assert body["app_id"] == definition["app_id"] and body["skill_id"] == definition["skill_id"]
        assert row["parent_embed_id"] == carrier and "embed_ids" not in row
        assert body["authoring"]["kind"] == supplied["kind"]
        assert body["authoring"]["origin"] == "user_provided"
        for key, value in supplied["details"].items():
            if key != "title":
                assert body[key] == value
        assert body["title"] not in row["encrypted_content"]
    assert all(h.record(embed)["type"] != "app_skill_use" for embed in [carrier, *parent["embed_ids"]])


# contract-test: direct surface=rest_api assertions=authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_partial_invalid_items_keep_independent_children_and_view_order(authored_service):
    h = authored_service
    carrier = await h.create()
    good = [valid_authored_item("nutrition.recipe", "first"), valid_authored_item("events.event", "last")]
    bad = valid_authored_item("events.event", "bad")
    bad["details"]["date_start"] = "2027-02-30"
    raw = json.dumps({"schemaVersion": 1, "items": [good[0], bad, good[1]],
                      "view": {"mode": "map", "items": ["last", "bad", "first"]}})
    assert await h.update(carrier, raw=raw)
    parent = await h.content(carrier)
    assert parent["status"] == "finished" and parent["validation"]["status"] == "partial"
    assert [item["kind"] for item in parent["items"]] == [item["kind"] for item in good]
    assert parent["view"]["embeds"] == list(reversed(parent["embed_ids"]))
    assert len(parent["embed_ids"]) == 2 and parent["validation"]["warnings"]


@pytest.mark.parametrize("status,raw", [("finished", '{"schemaVersion":'), ("error", "")])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_invalid_and_interrupted_carriers_retain_encrypted_error_snapshot(authored_service, status, raw):
    h = authored_service
    carrier = await h.create()
    with _recovery_scope():
        assert await h.update(carrier, status=status, raw=raw)
    parent = await h.content(carrier)
    assert h.record(carrier)["status"] == parent["status"] == "error"
    assert parent["embed_ids"] == [] and parent["items"] == []
    assert parent["validation"]["status"] == "invalid_source"
    assert parent["validation"]["parse_error"]
    assert parent["source_json"] == ""
    assert h.cache.events[-1][1]["payload"]["status"] == "error"
    assert h.cache.pending == [(OWNER, carrier)]
    assert h.cache.order.index(("recovery-one", carrier)) < h.cache.order.index(("cache", carrier))


@pytest.mark.parametrize("override", [{"chat_id": "wrong-chat"}, {"user_id_hash": "b" * 64}])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_owner_and_chat_mismatch_cannot_update_carrier(authored_service, override):
    h = authored_service
    carrier = await h.create()
    before = dict(h.cache.values)
    assert not await h.update(carrier, [valid_authored_item()], **override)
    assert h.cache.values == before and h.cache.events == []


# contract-test: direct surface=rest_api assertions=authored-results.groups.same-response-and-reuse,authored-results.media.safe-and-attributed
@pytest.mark.asyncio
async def test_only_context_index_and_matching_owner_authorize_references(authored_service, monkeypatch):
    h = authored_service
    carrier = await h.create()
    known, foreign, guessed = [str(uuid.uuid4()) for _ in range(3)]
    await h.put_reference(known, {"type": "document", "title": "Authorized source"}, chat_id="other-authorized-chat")
    await h.put_reference(foreign, {"type": "document", "title": "Foreign private source"}, owner_hash="b" * 64)
    await h.put_reference(guessed, {"type": "document", "title": "Guessed private source"})
    h.service.authoring_reference_index = {"known.pdf": known, "foreign.pdf": foreign}
    lookup = AsyncMock(wraps=h.service._get_cached_embed)
    monkeypatch.setattr(h.service, "_get_cached_embed", lookup)
    item = valid_authored_item()
    item["sources"] = [{"embed_ref": ref} for ref in ["known.pdf", "foreign.pdf", guessed]]
    assert await h.update(carrier, [item])
    parent = await h.content(carrier)
    child = await h.content(parent["embed_ids"][0])
    assert child["authoring"]["sources"] == [{"embed_ref": "known.pdf"}]
    assert guessed not in [call.args[0] for call in lookup.await_args_list]
    assert sum(w["code"] == "unavailable_source_reference" for w in parent["validation"]["warnings"]) == 2
    assert "Foreign private source" not in json.dumps(child)


async def _image_reference(h, *, reference="venue.jpg", owner_hash=OWNER_HASH):
    embed_id = str(uuid.uuid4())
    key = base64.b64encode(b"k" * 32).decode()
    wrapped, _ = await h.service.encryption_service.encrypt_with_user_key(key, VAULT)
    body = {"type": "image", "app_id": "images", "skill_id": "upload", "filename": reference,
            "s3_base_url": "https://private-storage.example", "vault_wrapped_aes_key": wrapped,
            "aes_nonce": "selected-image-nonce", "files": {
                "preview": {"s3_key": "selected-preview", "aes_nonce": "preview-nonce"},
                "original": {"s3_key": "selected-original", "aes_nonce": "original-nonce"},
                "unselected": {"s3_key": "unselected-variant"},
            }}
    await h.put_reference(embed_id, body, owner_hash=owner_hash, parent="original-upload-parent")
    h.service.authoring_reference_index = {reference: embed_id}
    return embed_id, key


# contract-test: direct surface=rest_api assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_selected_uploaded_image_stays_in_intended_child_and_upload_is_unchanged(authored_service):
    h = authored_service
    carrier = await h.create()
    upload, key = await _image_reference(h)
    original_upload = h.cache.values[f"embed:{upload}"]
    illustrated = valid_authored_item("events.event", "illustrated")
    illustrated["images"] = [{"embed_ref": "venue.jpg", "caption": "Selected venue", "attribution": "User photographer"}]
    plain = valid_authored_item("nutrition.recipe", "plain")
    assert await h.update(carrier, [illustrated, plain])
    parent = await h.content(carrier)
    selected, other = [await h.content(child) for child in parent["embed_ids"]]
    media = selected["authored_media"]
    assert len(media) == 1 and media[0]["source_embed_id"] == upload
    assert media[0]["aes_key"] == key and media[0]["aes_nonce"] == "selected-image-nonce"
    assert set(media[0]["files"]) == {"preview", "original"}
    assert media[0]["caption"] == "Selected venue" and media[0]["attribution"] == "User photographer"
    assert "authored_media" not in parent and "authored_media" not in other
    assert key not in h.cache.values[f"embed:{parent['embed_ids'][0]}"]
    assert h.cache.values[f"embed:{upload}"] == original_upload
    assert upload not in parent["embed_ids"]
    assert all("embed_ids" not in h.record(child) for child in parent["embed_ids"])


@pytest.mark.parametrize("indexed", [False, True])
# contract-test: direct surface=rest_api assertions=authored-results.media.safe-and-attributed
@pytest.mark.asyncio
async def test_guessed_or_foreign_uploaded_image_cannot_supply_crypto(authored_service, indexed):
    h = authored_service
    carrier = await h.create()
    upload, key = await _image_reference(h, owner_hash="b" * 64 if indexed else OWNER_HASH)
    reference = "venue.jpg" if indexed else upload
    item = valid_authored_item()
    item["images"] = [{"embed_ref": reference}]
    assert await h.update(carrier, [item])
    parent = await h.content(carrier)
    child = await h.content(parent["embed_ids"][0])
    assert "authored_media" not in child and key not in json.dumps(child)
    assert any(w["code"] == "unavailable_image_reference" for w in parent["validation"]["warnings"])


@pytest.mark.parametrize("access", ["authorized", "guessed", "foreign"])
# contract-test: direct surface=rest_api assertions=authored-results.media.safe-and-attributed,authored-results.eligibility.all-suitable-results
@pytest.mark.asyncio
async def test_resource_only_image_reference_requires_an_authorized_real_asset(authored_service, access):
    h = authored_service
    carrier = await h.create()
    upload, key = await _image_reference(h, owner_hash="b" * 64 if access == "foreign" else OWNER_HASH)
    original_upload = h.cache.values[f"embed:{upload}"]
    item = valid_authored_item("images.image_result")
    item["details"] = {"embed_ref": upload if access == "guessed" else "venue.jpg"}
    assert await h.update(carrier, [item])
    parent = await h.content(carrier)
    if access == "authorized":
        assert parent["status"] == "finished" and len(parent["embed_ids"]) == 1
        child = await h.content(parent["embed_ids"][0])
        assert child["authored_media"][0]["source_embed_id"] == upload
        assert child["authored_media"][0]["aes_key"] == key
    else:
        assert parent["status"] == "error" and parent["embed_ids"] == []
        assert any(w["code"] == "unavailable_resource" for w in parent["validation"]["warnings"])
    assert h.cache.values[f"embed:{upload}"] == original_upload


# contract-test: direct surface=rest_api assertions=authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_context_expands_real_child_refs_without_source_crypto_or_uuids(authored_service):
    h = authored_service
    carrier = await h.create()
    upload, key = await _image_reference(h)
    item = valid_authored_item()
    item["images"] = [{"embed_ref": "venue.jpg"}]
    assert await h.update(carrier, [item])
    child_id = h.record(carrier)["embed_ids"][0]
    child = await h.content(child_id)
    message = f'Before\n```json\n{json.dumps({"type": "authored_results", "embed_id": carrier})}\n```\nAfter'
    expanded, index = await h.service.resolve_embed_references_in_content(message, VAULT)
    assert index == {child["embed_ref"]: child_id}
    assert child["title"] in expanded and child["embed_ref"] in expanded
    assert "Before" in expanded and "After" in expanded
    for secret in [carrier, child_id, upload, key, "source_json", "schemaVersion", "authored_media",
                   "selected-preview", "selected-original", "vault_wrapped_aes_key"]:
        assert secret not in expanded


@pytest.mark.parametrize("invalid", ["owner", "chat", "parent", "processing", "kind", "app", "skill"])
# contract-test: direct surface=rest_api assertions=authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_context_skips_children_with_invalid_membership_or_identity(authored_service, invalid):
    h = authored_service
    carrier = await h.create()
    assert await h.update(carrier, [valid_authored_item()])
    child_id = h.record(carrier)["embed_ids"][0]
    row = h.record(child_id)
    if invalid in {"owner", "chat", "parent", "processing"}:
        field, value = {"owner": ("hashed_user_id", "b" * 64), "chat": ("chat_id", "wrong"),
                        "parent": ("parent_embed_id", "wrong"), "processing": ("status", "processing")}[invalid]
        row[field] = value
    if invalid in {"processing", "kind", "app", "skill"}:
        body = await h.content(child_id)
        if invalid == "kind":
            body["authoring"]["kind"] = "not_admitted.fake"
        elif invalid == "app":
            body["app_id"] = "other-app"
        elif invalid == "skill":
            body["skill_id"] = "other-skill"
        else:
            body["status"] = "processing"
        row["encrypted_content"], _ = await h.service.encryption_service.encrypt_with_user_key(encode(body), VAULT)
    h.cache.values[f"embed:{child_id}"] = json.dumps(row)
    assert await authored_children_for_context(h.service, carrier, user_vault_key_id=VAULT) == []


# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.groups.same-response-and-reuse
@pytest.mark.asyncio
async def test_recovery_defers_all_children_and_carrier_before_ordered_publication(authored_service):
    h = authored_service
    carrier = await h.create()
    with _recovery_scope():
        assert await h.update(carrier, [valid_authored_item(local_id="one"), valid_authored_item("nutrition.recipe", "two")])
    children = h.record(carrier)["embed_ids"]
    assert h.cache.order[0] == ("recovery", [*children, carrier])
    assert h.cache.order[1:] == [operation for embed in [*children, carrier]
                               for operation in [("cache", embed), ("publish", embed)]]
    prepared = h.service._save_completed_embed_recovery_batch.await_args.args[0]
    assert [payload["payload"]["embed_id"] for payload in prepared] == [*children, carrier]
    assert [payload["payload"].get("parent_embed_id") for payload in prepared[:-1]] == [carrier] * 2


@pytest.mark.parametrize("phase", ["seal", "publish"])
# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_required_recovery_failure_propagates_without_unsealed_publication(authored_service, phase):
    h = authored_service
    carrier = await h.create()
    if phase == "seal":
        h.service._save_completed_embed_recovery_batch.side_effect = RequiredRecoveryOutputError("seal unavailable")
    else:
        h.cache.fail_publish = True
    with _recovery_scope(), pytest.raises(RequiredRecoveryOutputError):
        await h.update(carrier, [valid_authored_item()])
    assert h.cache.events == [] and h.scheduled == []
    assert h.record(carrier)["status"] == "processing"
    if phase == "seal":
        assert list(h.cache.values) == [f"embed:{carrier}"]
    else:
        assert h.cache.order[0][0] == "recovery"
    assert h.service.send_embed_data_to_client.__globals__["_pending_finished_embed_batch"].get() is None


# contract-test: direct surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_error_carrier_cache_rejection_is_required_failure_before_publication(authored_service, monkeypatch):
    h = authored_service
    carrier = await h.create()
    monkeypatch.setattr(h.cache, "cache_required_ai_embed", AsyncMock(return_value=False))
    with _recovery_scope(), pytest.raises(RequiredRecoveryOutputError):
        await h.update(carrier, status="error", raw="")
    assert h.cache.events == []
    assert h.record(carrier)["status"] == "processing"
    assert h.cache.order == [("recovery-one", carrier)]


# contract-test: direct surface=rest_api assertions=authored-results.groups.same-response-and-reuse,authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_cache_miss_restores_vault_carrier_and_children_from_durable_records(authored_service):
    h = authored_service
    carrier = await h.create()
    assert await h.update(carrier, [valid_authored_item()])
    child_id = h.record(carrier)["embed_ids"][0]
    durable = {embed: h.record(embed) for embed in [carrier, child_id]}
    h.service.directus_service.embed = SimpleNamespace(
        get_embed_by_id=AsyncMock(side_effect=lambda embed: copy.deepcopy(durable.get(embed))),
    )
    h.cache.values.clear()
    h.cache.events.clear()
    children = await authored_children_for_context(h.service, carrier, user_vault_key_id=VAULT)
    assert [embed for embed, _ in children] == [child_id]
    assert decode(children[0][1])["authoring"]["kind"] == "events.event"
    assert h.record(carrier) == durable[carrier] and h.record(child_id) == durable[child_id]
    assert [call.args[0] for call in h.service.directus_service.embed.get_embed_by_id.await_args_list] == [carrier, child_id]
    assert h.cache.events == []


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_client_ciphertext_from_durable_fallback_is_never_vault_decrypted(authored_service, monkeypatch):
    h = authored_service
    embed_id = str(uuid.uuid4())
    durable = {"embed_id": embed_id, "type": "authored_results", "chat_id": CHAT,
               "hashed_user_id": OWNER_HASH, "encrypted_content": "client-only-ciphertext"}
    h.service.directus_service.embed = SimpleNamespace(get_embed_by_id=AsyncMock(return_value=durable))
    decrypt = AsyncMock(side_effect=AssertionError("client ciphertext crossed Vault boundary"))
    monkeypatch.setattr(h.service.encryption_service, "decrypt_with_user_key", decrypt)
    assert await h.service._get_cached_embed_toon(embed_id, VAULT) is None
    assert await h.service._get_cached_embed(embed_id, VAULT) == durable
    decrypt.assert_not_awaited()
    h.service.directus_service.embed.get_embed_by_id.assert_awaited_once_with(embed_id)


# contract-test: supporting surface=rest_api assertions=authored-results.lifecycle.encrypted-and-stable
@pytest.mark.asyncio
async def test_decrypted_payload_cannot_override_outer_owner_chat_or_parent_authority(authored_service):
    h = authored_service
    embed_id = str(uuid.uuid4())
    await h.put_reference(embed_id, {"type": "authored_results", "title": "Content title",
                                   "hashed_user_id": OWNER_HASH, "chat_id": CHAT,
                                   "parent_embed_id": "claimed-parent", "status": "processing"},
                          owner_hash="foreign-owner", chat_id="foreign-chat", parent="real-parent")
    row = await h.service._get_cached_embed(embed_id, VAULT)
    assert row["title"] == "Content title"
    assert row["hashed_user_id"] == "foreign-owner" and row["chat_id"] == "foreign-chat"
    assert row["parent_embed_id"] == "real-parent" and row["status"] == "finished"
