# backend/tests/test_embed_service_draft_events.py
#
# Regression tests for no-context draft embed WebSocket delivery.
# Draft uploads (for example PDFs in the composer before send) need a
# send_embed_data event so the browser can mark the draft card finished, but
# they must not be tracked as pending client persistence until a chat/message
# context exists.

import asyncio
import json

import pytest

try:
    from backend.core.api.app.services.embed_service import EmbedService
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


class _FakeRedisClient:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def get(self, _key: str):
        return None

    async def publish(self, channel: str, message: str):
        self.published.append((channel, json.loads(message)))
        return 1


class _FakeCacheService:
    def __init__(self):
        self._client = _FakeRedisClient()

    @property
    async def client(self):
        return self._client


def _run(coro):
    return asyncio.run(coro)


# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
def test_no_context_embed_event_publishes_without_pending_persistence(monkeypatch):
    cache = _FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=object())
    tracked: list[tuple[str, str]] = []

    async def fake_track_pending(user_id: str, embed_id: str, _log_prefix: str):
        tracked.append((user_id, embed_id))

    monkeypatch.setattr(service, "_track_pending_embed", fake_track_pending)

    ok = _run(service.send_embed_data_to_client(
        embed_id="embed-draft",
        embed_type="pdf",
        content_toon="type: pdf\nstatus: finished",
        chat_id="",
        message_id="",
        user_id="user-1",
        user_id_hash="user-hash",
        status="finished",
        check_cache_status=False,
    ))

    assert ok is True
    assert tracked == []
    assert cache._client.published[0][0] == "websocket:user:user-hash"
    assert cache._client.published[0][1]["payload"]["embed_id"] == "embed-draft"


# contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
def test_contextual_embed_event_still_tracks_pending_persistence(monkeypatch):
    cache = _FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=object())
    tracked: list[tuple[str, str]] = []

    async def fake_track_pending(user_id: str, embed_id: str, _log_prefix: str):
        tracked.append((user_id, embed_id))

    monkeypatch.setattr(service, "_track_pending_embed", fake_track_pending)

    ok = _run(service.send_embed_data_to_client(
        embed_id="embed-sent",
        embed_type="pdf",
        content_toon="type: pdf\nstatus: finished",
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="user-hash",
        status="finished",
        check_cache_status=False,
    ))

    assert ok is True
    assert tracked == [("user-1", "embed-sent")]


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,chats.rendering.assistant-document-convergence
def test_failed_skill_is_sealed_cached_encrypted_and_sent_for_client_persistence(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from toon_format import decode

    cache = _FakeCacheService()
    encryption = Mock(encrypt_with_user_key=AsyncMock(return_value=("vault-ciphertext", None)))
    service = EmbedService(cache, directus_service=object(), encryption_service=encryption)
    monkeypatch.setattr(service, "_get_cached_embed", AsyncMock(return_value={"query": "evening classes", "provider": "test"}))
    sealed = AsyncMock()
    retained = AsyncMock()
    tracked = AsyncMock()
    scheduled = Mock()
    monkeypatch.setattr(service, "_save_completed_embed_recovery", sealed)
    monkeypatch.setattr(service, "_cache_embed", retained)
    monkeypatch.setattr(service, "_track_pending_embed", tracked)
    monkeypatch.setattr(service, "_schedule_embed_persistence_fallback", scheduled)

    result = _run(service.update_embed_status_to_error(
        embed_id="failed-skill", app_id="fitness", skill_id="search_classes",
        error_message="", chat_id="chat-1", message_id="message-1",
        user_id="user-1", user_id_hash="user-hash", user_vault_key_id="vault-key",
    ))

    assert result == {"embed_id": "failed-skill", "child_embed_ids": [], "status": "error", "from_placeholder": True}
    payload = cache._client.published[0][1]["payload"]
    assert payload["status"] == "error"
    content = decode(payload["content"])
    assert content["status"] == "error"
    assert content["error"]
    assert content["query"] == "evening classes"
    assert content["result_count"] == 0
    sealed.assert_awaited_once()
    assert sealed.await_args.kwargs["producer_final_children"] == []
    retained.assert_awaited_once()
    cache_data = retained.await_args.args[1]
    assert cache_data["status"] == "error"
    assert cache_data["encrypted_content"] == "vault-ciphertext"
    assert "content" not in cache_data
    assert "query" not in cache_data
    tracked.assert_awaited_once_with("user-1", "failed-skill", "")
    scheduled.assert_called_once_with("failed-skill")


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,chats.rendering.assistant-document-convergence
def test_failed_skill_recovery_failure_prevents_publication(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from backend.core.api.app.services.embed_service import RequiredRecoveryOutputError

    cache = _FakeCacheService()
    service = EmbedService(cache, directus_service=object(), encryption_service=Mock(
        encrypt_with_user_key=AsyncMock(return_value=("vault-ciphertext", None)),
    ))
    monkeypatch.setattr(service, "_get_cached_embed", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_save_completed_embed_recovery", AsyncMock(side_effect=RequiredRecoveryOutputError("unavailable")))
    retained = AsyncMock()
    monkeypatch.setattr(service, "_cache_embed", retained)

    with pytest.raises(RequiredRecoveryOutputError):
        _run(service.update_embed_status_to_error(
            embed_id="failed-skill", app_id="web", skill_id="search", error_message="Request failed",
            chat_id="chat-1", message_id="message-1", user_id="user-1",
            user_id_hash="user-hash", user_vault_key_id="vault-key",
        ))

    assert cache._client.published == []
    retained.assert_not_awaited()
