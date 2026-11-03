"""Authenticated embed replay retains explicit catalog identity, including cold recovery."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.request_embed_handler import handle_request_embed


CATALOGS = [{"app_id": "ai", "skill_id": "authored_results"},
            {"app_id": "tv", "skill_id": "search"}, {},
            {"app_id": None, "skill_id": None}]


# contract-test: supporting surface=cli assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.surfaces.shared-semantics
@pytest.mark.anyio
@pytest.mark.parametrize("catalog", CATALOGS)
@pytest.mark.parametrize("source", ["canonical", "canonical_stale_cache", "canonical_cache_miss", "cache"])
async def test_requested_embed_retains_only_explicit_authorized_catalog(source, catalog):
    owner_hash = hashlib.sha256(b"owner").hexdigest()
    chat_hash = hashlib.sha256(b"chat").hexdigest()
    record = {"embed_id": "record", "hashed_chat_id": chat_hash,
              "hashed_user_id": owner_hash, "status": "finished", **catalog}
    canonical = {**record, "encrypted_type": "type-cipher", "encrypted_content": "client-cipher",
                 "encryption_mode": "client"} if source != "cache" else None
    if source in {"canonical_stale_cache", "canonical_cache_miss"}:
        canonical.pop("encrypted_type")
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[{"id": "chat", "hashed_user_id": owner_hash}]),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=canonical),
            get_sync_embed_key_window_for_page=AsyncMock(return_value={"embed_keys": [],
                "has_more_after": False, "end_cursor": None, "oversized_key_id": None})))
    cached = {**record, "chat_id": "chat", "encrypted_content": "vault-cipher", "type": "authored_results"}
    if source == "canonical_stale_cache":
        cached["status"] = "processing"
    if source == "canonical_cache_miss":
        cached = None
    cache = SimpleNamespace(get=AsyncMock(return_value=cached),
        get_user_vault_key_id=AsyncMock(return_value="vault-key"))
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(
        return_value='{"app_id":"untrusted","skill_id":"content-only"}'))
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(None, manager, cache, directus, encryption, "owner", "device",
        {"embed_id": "record", "chat_id": "chat", "app_id": "untrusted-request", "skill_id": "fake"})
    frame = manager.send_personal_message.await_args.args[0]
    assert frame["type"] == "send_embed_data"
    assert {key: frame["payload"][key] for key in ("app_id", "skill_id") if key in frame["payload"]} == {
        key: value for key, value in catalog.items() if value is not None}
    assert frame["payload"]["content"] == ("client-cipher" if source != "cache"
        else '{"app_id":"untrusted","skill_id":"content-only"}')
    if source == "canonical":
        cache.get.assert_not_awaited()
    if source != "cache":
        encryption.decrypt_with_user_key.assert_not_awaited()


# contract-test: supporting surface=cli assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.surfaces.shared-semantics
@pytest.mark.anyio
@pytest.mark.parametrize("catalog", CATALOGS)
async def test_pending_embed_replay_preserves_explicit_catalog_without_content_inference(monkeypatch, catalog):
    from backend.core.api.app.routes import websockets
    monkeypatch.setattr(websockets.asyncio, "sleep", AsyncMock())
    record = {"embed_id": "record", "type": "authored_results", "status": "finished",
              "chat_id": "chat", "message_id": "message", "vault_key_id": "vault-key",
              "encrypted_content": "vault-cipher", **catalog}
    class Cache:
        get_pending_embed_ids = AsyncMock(return_value=["record"])
        remove_pending_embed = AsyncMock()
        @property
        def client(self):
            async def redis():
                return SimpleNamespace(get=AsyncMock(return_value=json.dumps(record)))
            return redis()
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(
        return_value='{"app_id":"untrusted-content","skill_id":"fake"}'))
    await websockets._deliver_pending_embeds(Cache(), encryption, manager, "owner", "owner-hash", "device")
    frame = manager.send_personal_message.await_args.kwargs["message"]["payload"]
    assert {key: frame[key] for key in ("app_id", "skill_id") if key in frame} == {
        key: value for key, value in catalog.items() if value is not None}
    assert (frame["embed_id"], frame["chat_id"], frame["message_id"]) == ("record", "chat", "message")
    encryption.decrypt_with_user_key.assert_awaited_once_with("vault-cipher", "vault-key")
