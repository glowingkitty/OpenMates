# backend/tests/test_sub_chat_confirmation_handler.py
#
# Unit coverage for the WebSocket sub-chat confirmation handler.
# Uses fakes for cache, Directus ownership, and the connection manager so the
# tests validate behavior without creating real child chats or dispatching
# Celery tasks.

import sys
import types
from typing import Any

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.sub_chat_confirmation_handler import (
    handle_sub_chat_confirmation,
)


class FakeCache:
    def __init__(self, context: dict[str, Any] | None) -> None:
        self.context = context
        self.deleted: list[str] = []
        self.values: dict[str, Any] = {}
        self.active_tasks: dict[str, str] = {}
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.context

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.context = None

    async def set(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        self.values[key] = value

    async def set_active_ai_task(self, chat_id: str, task_id: str) -> None:
        self.active_tasks[chat_id] = task_id

    async def publish_event(self, channel: str, payload: dict[str, Any]) -> None:
        self.published.append((channel, payload))


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
async def test_sub_chat_confirmation_revalidates_parallel_capacity_on_approval() -> None:
    cache = FakeCache(pending_context(21))
    manager = FakeManager()

    await handle_sub_chat_confirmation(
        manager=manager,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chat_id": "parent-chat", "task_id": "task-1", "action": "approve"},
        cache_service=cache,  # type: ignore[arg-type]
        directus_service=FakeDirectus(existing_sub_chats=0),  # type: ignore[arg-type]
    )

    assert manager.messages[0]["type"] == "sub_chat_confirmation_resolved"
    assert manager.messages[0]["payload"]["status"] == "limit_exceeded"


@pytest.mark.asyncio
async def test_sub_chat_confirmation_allows_large_sequential_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FakeCache({**pending_context(25), "execution_mode": "sequential"})
    manager = FakeManager()
    calls: dict[str, Any] = {}

    class FakeAskSkillRequest:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

        def model_dump(self, mode: str = "json") -> dict[str, Any]:
            return dict(self.__dict__)

    async def fake_create_sub_chat_records(**kwargs: Any) -> None:
        calls["created"] = len(kwargs["spawned_sub_chats"])

    async def fake_dispatch_sub_chat_task(**kwargs: Any) -> str:
        calls["dispatched"] = kwargs["sub_chat"]["id"]
        return "active-task"

    monkeypatch.setattr(
        "backend.core.api.app.routes.handlers.websocket_handlers.sub_chat_confirmation_handler.create_sub_chat_records",
        fake_create_sub_chat_records,
    )
    monkeypatch.setattr(
        "backend.core.api.app.routes.handlers.websocket_handlers.sub_chat_confirmation_handler.dispatch_sub_chat_task",
        fake_dispatch_sub_chat_task,
    )
    fake_ask_skill_module = types.SimpleNamespace(AskSkillRequest=FakeAskSkillRequest)
    monkeypatch.setitem(sys.modules, "backend.apps.ai.skills.ask_skill", fake_ask_skill_module)
    fake_stream_consumer_module = types.SimpleNamespace(_store_sub_chat_pending_context=lambda **_: None)
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.stream_consumer", fake_stream_consumer_module)

    await handle_sub_chat_confirmation(
        manager=manager,
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chat_id": "parent-chat", "task_id": "task-1", "action": "approve"},
        cache_service=cache,  # type: ignore[arg-type]
        directus_service=FakeDirectus(existing_sub_chats=200),  # type: ignore[arg-type]
    )

    assert calls["created"] == 25
    assert calls["dispatched"] == "child-0"
    assert manager.messages[-1]["type"] == "sub_chat_confirmation_resolved"
    assert manager.messages[-1]["payload"]["status"] == "approved"
    assert manager.messages[-1]["payload"]["approved_count"] == 25
