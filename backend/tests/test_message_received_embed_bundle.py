"""Encrypted upload bundles must be durable before message admission."""

# contract-test-file: infrastructure

import asyncio
import hashlib
import sys
import types
from unittest.mock import AsyncMock

import pytest


sys.modules.setdefault(
    "backend.core.api.app.services.cache", types.SimpleNamespace(CacheService=object),
)
sys.modules.setdefault(
    "backend.core.api.app.services.directus.directus",
    types.SimpleNamespace(DirectusService=object),
)


USER = "bundle-owner"
CHAT = "bundle-chat"
MESSAGE = "bundle-message"
EMBED = "bundle-embed"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bundle(*, chat=CHAT, owner=USER, embed_id=EMBED):
    embed_hash = digest(embed_id)
    return [{
        "embed_id": embed_id,
        "hashed_embed_id": embed_hash,
        "hashed_user_id": digest(owner),
        "hashed_chat_id": digest(chat),
        "hashed_message_id": digest(MESSAGE),
        "encrypted_type": "type-cipher",
        "encrypted_content": "content-cipher",
        "embed_keys": [
            {"hashed_embed_id": embed_hash, "hashed_user_id": digest(owner),
             "hashed_chat_id": None, "key_type": "master",
             "encrypted_embed_key": "master-cipher", "created_at": 1},
            {"hashed_embed_id": embed_hash, "hashed_user_id": digest(owner),
             "hashed_chat_id": digest(chat), "key_type": "chat",
             "encrypted_embed_key": "chat-cipher", "created_at": 1},
        ],
    }]


class Response:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self.data = data

    def json(self):
        return {"data": self.data} if self.status_code == 200 else {
            "error": {"code": "project_context_required"},
        }


class FakeEmbeds:
    def __init__(self, parent):
        self.parent = parent

    async def get_sync_embed_by_id(self, embed_id):
        if self.parent.fail_head_read:
            return None
        return self.parent.head if self.parent.head and self.parent.head["embed_id"] == embed_id else None


class FakeDirectus:
    base_url = "http://directus.test"

    def __init__(self):
        self.head = None
        self.wrappers = []
        self.head_writes = 0
        self.key_writes = 0
        self.fail_head = False
        self.fail_head_read = False
        self.fail_key = False
        self.fail_key_after = None
        self.project_linked = False
        self.embed = FakeEmbeds(self)

    async def _make_api_request(self, method, url, *, headers, json):
        assert method == "POST" and url.endswith("/embed-version-transaction/legacy-embed-write")
        assert "embed_keys" not in json["payload"]
        assert json["actor_user_hash"] == digest(USER)
        assert json["bundle_context"]["chat_id"] in {CHAT, "team-chat"}
        assert json["bundle_context"]["message_id"] == MESSAGE
        self.head_writes += 1
        if self.fail_head or self.project_linked:
            return Response(403)
        if self.fail_key or self.fail_key_after is not None:
            return Response(500)
        proposed = dict(json["payload"])
        if self.head and self.head != proposed:
            return Response(409)
        for wrapper in json["bundle_context"]["key_wrappers"]:
            existing = next((row for row in self.wrappers if row["key_type"] == wrapper["key_type"]), None)
            if existing and existing["encrypted_embed_key"] != wrapper["encrypted_embed_key"]:
                return Response(409)
        self.head = proposed
        for wrapper in json["bundle_context"]["key_wrappers"]:
            if not any(row["key_type"] == wrapper["key_type"] for row in self.wrappers):
                self.wrappers.append({"id": f"key-{len(self.wrappers)}", **wrapper})
                self.key_writes += 1
        return Response(data={"embed_id": json["embed_id"]})

    async def get_items(self, collection, params, *, no_cache, admin_required, raise_on_error):
        assert no_cache and admin_required and raise_on_error
        if collection == "embeds":
            if self.fail_head_read:
                return []
            return [self.head] if self.head else []
        if collection == "project_items":
            return [{"id": "project-link"}] if self.project_linked else []
        if collection == "embed_keys":
            predicate = params["filter"]
            chat_predicate = predicate["hashed_chat_id"]
            chat_hash = chat_predicate.get("_eq")
            return [row for row in self.wrappers
                    if row["hashed_embed_id"] == predicate["hashed_embed_id"]["_eq"]
                    and row["key_type"] == predicate["key_type"]["_eq"]
                    and row["hashed_chat_id"] == chat_hash]
        raise AssertionError(collection)


@pytest.fixture(autouse=True)
def transaction_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "unit-test-token")


# contract-test: supporting surface=cli assertions=projects.files.hosted-ciphertext-commit
def test_bundle_persists_personal_and_team_ciphertext_and_exact_retry():
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _store_client_encrypted_embeds,
    )

    for chat in (CHAT, "team-chat"):
        directus = FakeDirectus()
        data = bundle(chat=chat)
        asyncio.run(_store_client_encrypted_embeds(directus, data, USER, chat, MESSAGE))
        asyncio.run(_store_client_encrypted_embeds(directus, data, USER, chat, MESSAGE))
        assert directus.head_writes == 2
        assert directus.key_writes == 2
        assert len(directus.wrappers) == 2
        assert "embed_keys" not in directus.head


# contract-test: supporting surface=cli assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.parametrize("change", ["owner", "chat", "wrapper_owner", "wrapper_chat"])
def test_bundle_rejects_foreign_identity_before_any_write(change):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _store_client_encrypted_embeds,
    )

    directus = FakeDirectus()
    data = bundle()
    if change == "owner":
        data[0]["hashed_user_id"] = digest("foreign-user")
    elif change == "chat":
        data[0]["hashed_chat_id"] = digest("foreign-chat")
    elif change == "wrapper_owner":
        data[0]["embed_keys"][0]["hashed_user_id"] = digest("foreign-user")
    else:
        data[0]["embed_keys"][1]["hashed_chat_id"] = digest("foreign-chat")
    with pytest.raises(ValueError):
        asyncio.run(_store_client_encrypted_embeds(directus, data, USER, CHAT, MESSAGE))
    assert directus.head_writes == directus.key_writes == 0


# contract-test: supporting surface=cli assertions=teams.chat.encrypted-until-invoked
def test_bundle_requires_current_chat_wrapper_before_head_write():
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _store_client_encrypted_embeds,
    )

    directus = FakeDirectus()
    data = bundle()
    data[0]["embed_keys"].pop()
    with pytest.raises(ValueError):
        asyncio.run(_store_client_encrypted_embeds(directus, data, USER, CHAT, MESSAGE))
    assert directus.head_writes == directus.key_writes == 0


# contract-test: supporting surface=cli assertions=projects.files.hosted-ciphertext-commit
@pytest.mark.parametrize("failure", ["fail_head", "fail_head_read", "fail_key", "project_linked"])
def test_bundle_failure_never_counts_as_durable_and_retry_repairs_partial_write(failure):
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _store_client_encrypted_embeds,
    )

    directus = FakeDirectus()
    setattr(directus, failure, True)
    data = bundle()
    with pytest.raises((RuntimeError, ValueError)):
        asyncio.run(_store_client_encrypted_embeds(directus, data, USER, CHAT, MESSAGE))
    assert directus.key_writes == (2 if failure == "fail_head_read" else 0)
    setattr(directus, failure, False)
    asyncio.run(_store_client_encrypted_embeds(directus, data, USER, CHAT, MESSAGE))
    assert len(directus.wrappers) == 2
    assert directus.key_writes == 2


# contract-test: supporting surface=cli assertions=projects.files.hosted-ciphertext-commit
def test_bundle_retry_after_second_wrapper_transaction_failure():
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _store_client_encrypted_embeds,
    )

    directus = FakeDirectus()
    directus.fail_key_after = 1
    data = bundle()
    with pytest.raises(RuntimeError):
        asyncio.run(_store_client_encrypted_embeds(directus, data, USER, CHAT, MESSAGE))
    assert directus.head is None
    assert directus.key_writes == 0
    directus.fail_key_after = None
    asyncio.run(_store_client_encrypted_embeds(directus, data, USER, CHAT, MESSAGE))
    assert directus.head_writes == 2
    assert directus.key_writes == 2
    assert len(directus.wrappers) == 2


# contract-test: supporting surface=cli assertions=teams.chat.encrypted-until-invoked
def test_bundle_gate_precedes_preflight_broadcast_cache_and_confirmation():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] /
              "core/api/app/routes/handlers/websocket_handlers/message_received_handler.py").read_text()
    gate = source.index('encrypted_embeds_from_client = payload.get("encrypted_embeds", [])')
    assert source.index("chat_metadata_from_db = await directus_service.chat.get_chat_metadata") < gate
    assert gate < source.index("recovery_enqueue_result = await enqueue_chat_turn(")
    assert gate < source.index("await broadcast_team_event(")
    assert gate < source.index("version_update_result = await cache_service.save_chat_message_and_update_versions(")
    assert gate < source.index("admission = await cutover_controller.admit_legacy_inference(")
    assert gate < source.index("await _send_origin_chat_message_confirmed(", gate)


# contract-test: supporting surface=cli assertions=teams.chat.encrypted-until-invoked
@pytest.mark.parametrize("team_chat", [False, True])
def test_failed_bundle_does_not_ack_or_admit_dependent_turn(monkeypatch, team_chat):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    errors = []

    class Manager:
        async def send_personal_message(self, message, *_args):
            errors.append(message)

    class WebSocket:
        def __init__(self):
            self.sent = []

        async def send_json(self, message):
            self.sent.append(message)

    class Cutover:
        get_epoch = AsyncMock(return_value=1)

    preflight = AsyncMock()
    cache_write = AsyncMock()
    team_broadcast = AsyncMock()
    bundle_write = AsyncMock(side_effect=RuntimeError("key write failed"))
    monkeypatch.setattr(handler, "ChatRecoveryCutoverController", lambda *_args: Cutover())
    monkeypatch.setattr(handler, "_store_client_encrypted_embeds", bundle_write)
    monkeypatch.setattr(handler, "enqueue_chat_turn", preflight)
    monkeypatch.setattr(handler, "broadcast_team_event", team_broadcast)
    if team_chat:
        team_hash = digest("team-1")
        monkeypatch.setattr(handler, "extract_team_ai_context", lambda *_args: {
            "team_id": "team-1", "team_id_hash": team_hash,
        })
        inference_message = types.SimpleNamespace(
            content="@openmates help", model_dump=lambda **_kwargs: {"content": "@openmates help"},
        )
        monkeypatch.setattr(handler, "parse_team_message_transport", lambda *_args: types.SimpleNamespace(
            should_trigger_ai=True, inference_history=[inference_message],
            encrypted_content="team-cipher", mentioned_user_ids=[],
        ))
    else:
        team_hash = None
    directus = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value={"hashed_team_id": team_hash} if team_chat else None),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        team=types.SimpleNamespace(require_team_role=AsyncMock(return_value={"role": "member"})),
    )
    cache = types.SimpleNamespace(
        get_active_ai_task=AsyncMock(return_value=None),
        save_chat_message_and_update_versions=cache_write,
    )
    payload = {
        "chat_id": CHAT,
        "protocol_version": 1,
        "preflight_id": "preflight-1",
        "encrypted_embeds": bundle(),
        "message": {"message_id": MESSAGE, "role": "user", "content": "@openmates help",
                    "encrypted_content": "team-cipher", "created_at": 1_700_000_000},
    }
    websocket = WebSocket()
    asyncio.run(handler.handle_message_received(
        websocket=websocket, manager=Manager(), cache_service=cache,
        directus_service=directus, encryption_service=object(),
        user_id=USER, device_fingerprint_hash="device-1", payload=payload,
    ))
    bundle_write.assert_awaited_once()
    preflight.assert_not_awaited()
    team_broadcast.assert_not_awaited()
    cache_write.assert_not_awaited()
    assert errors[-1]["payload"]["code"] == "encrypted_embed_persistence_failed"
    assert not any(message["type"] == "chat_message_confirmed" for message in websocket.sent + errors)


# contract-test: supporting surface=cli assertions=projects.files.concurrent-chat-safety
def test_rejected_protocol_never_writes_bundle(monkeypatch):
    from backend.core.api.app.routes.handlers.websocket_handlers import message_received_handler as handler

    messages = []
    manager = types.SimpleNamespace(send_personal_message=AsyncMock(side_effect=lambda message, *_: messages.append(message)))
    directus = types.SimpleNamespace(chat=types.SimpleNamespace(get_chat_metadata=AsyncMock(return_value=None)))
    cache = types.SimpleNamespace(get_active_ai_task=AsyncMock(return_value=None))
    bundle_write = AsyncMock()
    monkeypatch.setattr(handler, "ChatRecoveryCutoverController", lambda *_: types.SimpleNamespace(
        get_epoch=AsyncMock(return_value=1),
    ))
    monkeypatch.setattr(handler, "_store_client_encrypted_embeds", bundle_write)
    asyncio.run(handler.handle_message_received(
        websocket=types.SimpleNamespace(), manager=manager, cache_service=cache,
        directus_service=directus, encryption_service=object(),
        user_id=USER, device_fingerprint_hash="device-1",
        payload={"chat_id": CHAT, "encrypted_embeds": bundle(),
                 "message": {"message_id": MESSAGE, "role": "user", "content": "hello",
                             "created_at": 1_700_000_000}},
    ))
    bundle_write.assert_not_awaited()
    assert messages[-1]["payload"]["code"] == "client_update_required"
