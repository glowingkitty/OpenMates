"""
Regression tests for encrypted chat metadata WebSocket storage guards.

These tests exercise the backend boundary that accepts client-encrypted chat
messages and metadata. A stale client can generate ciphertext with the wrong
chat key; the server must fail closed before anything is persisted.
"""

import asyncio
from types import SimpleNamespace

from backend.core.api.app.routes.handlers.websocket_handlers import (
    encrypted_chat_metadata_handler,
)
from backend.core.api.app.routes.handlers.websocket_handlers.encrypted_chat_metadata_handler import (
    handle_encrypted_chat_metadata,
)


class FakeManager:
    def __init__(self) -> None:
        self.personal_messages: list[tuple[dict, str, str]] = []
        self.broadcasts: list[tuple[dict, str, str | None]] = []

    async def send_personal_message(
        self, message: dict, user_id: str, device_fingerprint_hash: str
    ) -> None:
        self.personal_messages.append((message, user_id, device_fingerprint_hash))

    async def broadcast_to_user(
        self, message: dict, user_id: str, exclude_device_hash: str | None = None
    ) -> None:
        self.broadcasts.append((message, user_id, exclude_device_hash))


class FakeCacheService:
    async def get_chat_list_item_data(self, user_id: str, chat_id: str):
        return None

    async def update_chat_list_item_field(
        self, user_id: str, chat_id: str, field: str, value: str
    ) -> bool:
        raise AssertionError("mismatched key payload must not update cache")


class FakeChatService:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return True

    async def get_chat_metadata(self, chat_id: str) -> dict:
        return {
            "encrypted_chat_key": "existing-key-a",
            "messages_v": 5,
        }


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatService()


def test_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch):
    asyncio.run(_run_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch))


async def _run_mismatched_chat_key_rejects_entire_encrypted_payload(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="unexpected-task")

    monkeypatch.setattr(
        encrypted_chat_metadata_handler.celery_app,
        "send_task",
        fake_send_task,
    )

    manager = FakeManager()
    payload = {
        "chat_id": "chat-123",
        "message_id": "message-123",
        "encrypted_content": "encrypted-with-key-b",
        "encrypted_sender_name": "sender",
        "encrypted_category": "message-category",
        "encrypted_title": "title-with-key-b",
        "encrypted_icon": "icon-with-key-b",
        "encrypted_chat_category": "category-with-key-b",
        "encrypted_chat_key": "incoming-key-b",
        "created_at": 1_778_686_000,
        "versions": {
            "messages_v": 6,
            "title_v": 6,
            "last_edited_overall_timestamp": 1_778_686_000,
        },
        "message_history": [
            {
                "message_id": "history-message-1",
                "encrypted_content": "history-content-with-key-b",
            }
        ],
    }

    await handle_encrypted_chat_metadata(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService(),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=payload,
    )

    assert queued_tasks == []
    assert manager.broadcasts == []
    assert len(manager.personal_messages) == 1

    message, user_id, device_hash = manager.personal_messages[0]
    assert user_id == "user-123"
    assert device_hash == "device-123"
    assert message == {
        "type": "chat_key_mismatch",
        "payload": {
            "chat_id": "chat-123",
            "message_id": "message-123",
            "code": "chat_key_mismatch",
            "message": "Chat encryption key mismatch. Reload the chat key and retry.",
        },
    }
