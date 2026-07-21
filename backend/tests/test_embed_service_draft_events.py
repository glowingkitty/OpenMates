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
