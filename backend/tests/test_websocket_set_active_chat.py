# backend/tests/test_websocket_set_active_chat.py
#
# Regression coverage for WebSocket active-chat selection ordering.
# New-chat sends issue set_active_chat and chat_message_added back-to-back on
# the same socket. The active-chat ack must not wait for slow last_opened
# persistence, otherwise the receive loop can stall before the AI send event.

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from backend.core.api.app.routes.connection_manager import ConnectionManager


class FakeManager:
    def __init__(self):
        self.calls = []

    def set_active_chat(self, user_id, device_fingerprint_hash, chat_id):
        self.calls.append(("set_active_chat", user_id, device_fingerprint_hash, chat_id))

    async def send_personal_message(self, message, user_id, device_fingerprint_hash):
        self.calls.append(("send_personal_message", message["type"], user_id, device_fingerprint_hash))


def import_active_chat_handler():
    tracing_config_stub = ModuleType("backend.shared.python_utils.tracing.config")
    tracing_config_stub.setup_tracing = lambda *args, **kwargs: None
    sys.modules.setdefault("backend.shared.python_utils.tracing.config", tracing_config_stub)

    from backend.core.api.app.routes.handlers.websocket_handlers import active_chat_handler

    return active_chat_handler


def test_set_active_chat_ack_is_sent_before_persistence_task(monkeypatch):
    active_chat_handler = import_active_chat_handler()

    manager = FakeManager()
    cache_service = SimpleNamespace(update_user=AsyncMock())
    directus_service = SimpleNamespace(update_user=AsyncMock())
    created_coroutines = []

    def fake_create_task(coroutine):
        created_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(active_chat_handler.asyncio, "create_task", fake_create_task)

    asyncio.run(
        active_chat_handler.handle_set_active_chat(
            manager=manager,
            cache_service=cache_service,
            directus_service=directus_service,
            user_id="user-123",
            device_fingerprint_hash="device-123",
            active_chat_id="353bfac8-b5aa-45f1-8ae2-76b3a9257719",
        )
    )

    assert manager.calls == [
        ("set_active_chat", "user-123", "device-123", "353bfac8-b5aa-45f1-8ae2-76b3a9257719"),
        ("send_personal_message", "active_chat_set_ack", "user-123", "device-123"),
    ]
    assert len(created_coroutines) == 1
    cache_service.update_user.assert_not_awaited()
    directus_service.update_user.assert_not_awaited()


def test_set_active_chat_skips_persistence_for_client_only_chats(monkeypatch):
    active_chat_handler = import_active_chat_handler()

    manager = FakeManager()
    cache_service = SimpleNamespace(update_user=AsyncMock())
    directus_service = SimpleNamespace(update_user=AsyncMock())
    created_coroutines = []

    monkeypatch.setattr(
        active_chat_handler.asyncio,
        "create_task",
        lambda coroutine: created_coroutines.append(coroutine),
    )

    asyncio.run(
        active_chat_handler.handle_set_active_chat(
            manager=manager,
            cache_service=cache_service,
            directus_service=directus_service,
            user_id="user-123",
            device_fingerprint_hash="device-123",
            active_chat_id="demo-for-everyone",
        )
    )

    assert manager.calls == [
        ("set_active_chat", "user-123", "device-123", "demo-for-everyone"),
        ("send_personal_message", "active_chat_set_ack", "user-123", "device-123"),
    ]
    assert created_coroutines == []


def test_set_active_chat_replays_inflight_ai_stream_snapshot(monkeypatch):
    active_chat_handler = import_active_chat_handler()

    manager = FakeManager()
    cache_service = SimpleNamespace(
        get=AsyncMock(return_value={
            "type": "ai_message_chunk",
            "chat_id": "353bfac8-b5aa-45f1-8ae2-76b3a9257719",
            "user_id_uuid": "user-123",
            "user_id_hash": "user-hash",
            "message_id": "assistant-1",
            "full_content_so_far": "Partial answer",
            "is_final_chunk": False,
        }),
        update_user=AsyncMock(),
    )
    directus_service = SimpleNamespace(update_user=AsyncMock())
    created_coroutines = []

    def fake_create_task(coroutine):
        created_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(active_chat_handler.asyncio, "create_task", fake_create_task)

    asyncio.run(
        active_chat_handler.handle_set_active_chat(
            manager=manager,
            cache_service=cache_service,
            directus_service=directus_service,
            user_id="user-123",
            device_fingerprint_hash="device-123",
            active_chat_id="353bfac8-b5aa-45f1-8ae2-76b3a9257719",
        )
    )

    assert manager.calls == [
        ("set_active_chat", "user-123", "device-123", "353bfac8-b5aa-45f1-8ae2-76b3a9257719"),
        ("send_personal_message", "active_chat_set_ack", "user-123", "device-123"),
        ("send_personal_message", "ai_message_update", "user-123", "device-123"),
    ]
    cache_service.get.assert_awaited_once_with(
        active_chat_handler.ai_stream_snapshot_cache_key("353bfac8-b5aa-45f1-8ae2-76b3a9257719")
    )
    assert len(created_coroutines) == 1


def test_native_background_connection_is_not_completion_capable():
    manager = ConnectionManager()
    user_id = "user-123"
    device_hash = "device-123"
    connection_key = (user_id, device_hash)

    manager.active_connections[user_id] = {device_hash: object()}
    manager.active_chat_per_connection[connection_key] = "chat-123"

    assert manager.is_user_active(user_id) is True
    assert manager.is_user_completion_capable_active(user_id) is True

    manager.set_connection_foreground(user_id, device_hash, is_foreground=False)

    assert manager.is_user_active(user_id) is True
    assert manager.is_user_completion_capable_active(user_id) is False
    assert manager.get_active_chat(user_id, device_hash) is None

    manager.set_connection_foreground(user_id, device_hash, is_foreground=True)
    manager.set_active_chat(user_id, device_hash, "chat-123")

    assert manager.is_user_completion_capable_active(user_id) is True
    assert manager.get_active_chat(user_id, device_hash) == "chat-123"


def test_native_background_grace_period_is_not_completion_capable():
    manager = ConnectionManager()
    user_id = "user-123"
    device_hash = "device-123"
    connection_key = (user_id, device_hash)

    manager.grace_period_tasks[connection_key] = SimpleNamespace(done=lambda: False)
    manager.active_chat_per_connection[connection_key] = "chat-123"

    assert manager.is_user_active(user_id) is True
    assert manager.is_user_completion_capable_active(user_id) is True

    manager.set_connection_foreground(user_id, device_hash, is_foreground=False)

    assert manager.is_user_active(user_id) is True
    assert manager.is_user_completion_capable_active(user_id) is False
    assert manager.get_active_chat(user_id, device_hash) is None

    manager.set_connection_foreground(user_id, device_hash, is_foreground=True)
    manager.set_active_chat(user_id, device_hash, "chat-123")

    assert manager.is_user_completion_capable_active(user_id) is True
    assert manager.get_active_chat(user_id, device_hash) == "chat-123"
