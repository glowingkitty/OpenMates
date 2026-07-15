"""
Regression coverage for metadata sync dispatch in the WebSocket endpoint.

Cold accounts can have hundreds of older chats to sync after the initial
phased sync. That metadata response is useful but not latency-sensitive.
The receive loop must remain free to process chat-turn preflight messages,
otherwise a send can time out before its durable ACK is emitted.
"""

from types import SimpleNamespace

from backend.core.api.app.routes import websockets


def test_sync_metadata_chats_is_scheduled_without_awaiting(monkeypatch):
    created_coroutines = []
    handler_awaited = False

    async def fake_handle_sync_metadata_chats(**kwargs):
        nonlocal handler_awaited
        handler_awaited = True

    def fake_create_task(coroutine):
        created_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(websockets, "handle_sync_metadata_chats", fake_handle_sync_metadata_chats)
    monkeypatch.setattr(websockets.asyncio, "create_task", fake_create_task)

    task = websockets._schedule_sync_metadata_chats_background(
        websocket=object(),
        manager=object(),
        cache_service=object(),
        directus_service=object(),
        encryption_service=object(),
        user_id="user-123",
        device_fingerprint_hash="device-123",
        payload={"existing_chat_ids": []},
        user_otel_attrs={"is_admin": False, "debug_opted_in": False},
    )

    assert task.done() is False
    assert len(created_coroutines) == 1
    assert handler_awaited is False
