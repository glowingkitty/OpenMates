"""
Regression tests for assistant-response ciphertext key validation.

The assistant completion path persists client-encrypted ciphertext after the AI
stream finishes. It must enforce the same key consistency guarantees as user
message metadata storage, otherwise a stale secondary device can win the
first-writer race and make only the follow-up assistant message undecryptable.
"""

import asyncio
import base64
from types import SimpleNamespace

from backend.core.api.app.routes.handlers.websocket_handlers import (
    ai_response_completed_handler,
)
from backend.core.api.app.routes.handlers.websocket_handlers.ai_response_completed_handler import (
    handle_ai_response_completed,
)


class FakeManager:
    def __init__(self) -> None:
        self.personal_messages: list[tuple[dict, str, str]] = []

    async def send_personal_message(
        self, message: dict, user_id: str, device_fingerprint_hash: str
    ) -> None:
        self.personal_messages.append((message, user_id, device_fingerprint_hash))


class FakeCacheService:
    async def get(self, key: str):
        return None


class FakeChatService:
    def __init__(self, authoritative_fingerprint: str) -> None:
        self.authoritative_fingerprint = authoritative_fingerprint

    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return True

    async def get_chat_metadata(self, chat_id: str) -> dict:
        return {
            "id": chat_id,
            "hashed_user_id": "user-hash-123",
            "encrypted_title": make_ciphertext(self.authoritative_fingerprint),
            "messages_v": 3,
        }

    async def get_messages_for_chats(self, chat_ids: list[str]) -> dict[str, list[str]]:
        return {
            chat_ids[0]: [
                {
                    "message_id": "existing-message-1",
                    "encrypted_content": make_ciphertext(self.authoritative_fingerprint),
                }
            ]
        }


class FakeDirectusService:
    def __init__(self, authoritative_fingerprint: str) -> None:
        self.chat = FakeChatService(authoritative_fingerprint)


def make_ciphertext(fingerprint: str) -> str:
    raw = b"OM" + bytes.fromhex(fingerprint) + (b"0" * 12) + b"ciphertext"
    return base64.b64encode(raw).decode("ascii")


def make_payload(fingerprint: str) -> dict:
    return {
        "chat_id": "chat-123",
        "message": {
            "message_id": "assistant-123",
            "chat_id": "chat-123",
            "role": "assistant",
            "encrypted_content": make_ciphertext(fingerprint),
            "encrypted_category": make_ciphertext(fingerprint),
            "encrypted_model_name": make_ciphertext(fingerprint),
            "created_at": 1_779_399_620,
        },
        "versions": {"messages_v": 4},
    }


def test_ai_response_completed_rejects_mismatched_ciphertext_fingerprint(monkeypatch):
    asyncio.run(_run_rejects_mismatched_ciphertext_fingerprint(monkeypatch))


async def _run_rejects_mismatched_ciphertext_fingerprint(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="unexpected-task")

    monkeypatch.setattr(
        ai_response_completed_handler.celery_app,
        "send_task",
        fake_send_task,
    )

    manager = FakeManager()
    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("0f0165e4"),
    )

    assert queued_tasks == []
    assert manager.personal_messages == [
        (
            {
                "type": "chat_key_mismatch",
                "payload": {
                    "chat_id": "chat-123",
                    "message_id": "assistant-123",
                    "code": "chat_key_mismatch",
                    "message": "Chat encryption key mismatch. Reload the chat key and retry.",
                },
            },
            "user-123",
            "device-123",
        )
    ]


def test_ai_response_completed_accepts_matching_ciphertext_fingerprint(monkeypatch):
    asyncio.run(_run_accepts_matching_ciphertext_fingerprint(monkeypatch))


async def _run_accepts_matching_ciphertext_fingerprint(monkeypatch):
    queued_tasks: list[tuple[str, list, str | None]] = []

    def fake_send_task(name: str, args: list | None = None, queue: str | None = None):
        queued_tasks.append((name, args or [], queue))
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr(
        ai_response_completed_handler.celery_app,
        "send_task",
        fake_send_task,
    )

    manager = FakeManager()
    await handle_ai_response_completed(
        websocket=None,
        manager=manager,
        cache_service=FakeCacheService(),
        directus_service=FakeDirectusService("1a5b3b7c"),
        encryption_service=None,
        user_id="user-123",
        user_id_hash="user-hash-123",
        device_fingerprint_hash="device-123",
        payload=make_payload("1a5b3b7c"),
    )

    assert len(queued_tasks) == 1
    assert queued_tasks[0][0] == "app.tasks.persistence_tasks.persist_ai_response_to_directus"
    assert queued_tasks[0][2] == "persistence"
    assert manager.personal_messages == [
        (
            {
                "type": "ai_response_storage_confirmed",
                "payload": {
                    "message_id": "assistant-123",
                    "chat_id": "chat-123",
                    "task_id": "task-123",
                },
            },
            "user-123",
            "device-123",
        )
    ]
