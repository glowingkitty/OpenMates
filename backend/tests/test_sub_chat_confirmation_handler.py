# backend/tests/test_sub_chat_confirmation_handler.py
#
# Unit coverage for the WebSocket sub-chat confirmation handler.
# Uses fakes for cache, Directus ownership, and the connection manager so the
# tests validate behavior without creating real child chats or dispatching
# Celery tasks.

from typing import Any

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.sub_chat_confirmation_handler import (
    handle_sub_chat_confirmation,
)


class FakeCache:
    def __init__(self, context: dict[str, Any] | None) -> None:
        self.context = context
        self.deleted: list[str] = []

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.context

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.context = None


class FakeDirectusChat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return True


class FakeDirectus:
    def __init__(self, existing_sub_chats: int = 0) -> None:
        self.chat = FakeDirectusChat()
        self.existing_sub_chats = existing_sub_chats

    async def get_items(self, collection: str, params: dict[str, Any], admin_required: bool = False) -> list[dict[str, str]]:
        assert collection == "chats"
        return [{"id": f"existing-{index}"} for index in range(self.existing_sub_chats)]


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_personal_message(self, message: dict[str, Any], user_id: str, device_fingerprint_hash: str) -> None:
        self.messages.append(message)


def pending_context(sub_chat_count: int) -> dict[str, Any]:
    return {
        "parent_request_data": {
            "chat_id": "parent-chat",
            "message_id": "parent-message",
            "user_id": "user-1",
            "user_id_hash": "hash-1",
            "message_history": [],
            "chat_has_title": True,
        },
        "skill_config_dict": {},
        "sub_chats": [
            {
                "id": f"child-{index}",
                "user_message_id": f"child-message-{index}",
                "prompt": f"Task {index}",
                "wait_for_completion": True,
            }
            for index in range(sub_chat_count)
        ],
        "report_trigger": "all",
    }


@pytest.mark.asyncio
async def test_sub_chat_confirmation_cancel_consumes_pending_context() -> None:
    cache = FakeCache(pending_context(4))
    manager = FakeManager()

    await handle_sub_chat_confirmation(
        manager=manager,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chat_id": "parent-chat", "task_id": "task-1", "action": "cancel"},
        cache_service=cache,  # type: ignore[arg-type]
        directus_service=FakeDirectus(),  # type: ignore[arg-type]
    )

    assert cache.deleted
    assert manager.messages == [
        {
            "type": "sub_chat_confirmation_resolved",
            "payload": {"chat_id": "parent-chat", "task_id": "task-1", "status": "cancelled"},
        }
    ]


@pytest.mark.asyncio
async def test_sub_chat_confirmation_revalidates_capacity_on_approval() -> None:
    cache = FakeCache(pending_context(2))
    manager = FakeManager()

    await handle_sub_chat_confirmation(
        manager=manager,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chat_id": "parent-chat", "task_id": "task-1", "action": "approve"},
        cache_service=cache,  # type: ignore[arg-type]
        directus_service=FakeDirectus(existing_sub_chats=19),  # type: ignore[arg-type]
    )

    assert manager.messages[0]["type"] == "sub_chat_confirmation_resolved"
    assert manager.messages[0]["payload"]["status"] == "limit_exceeded"
