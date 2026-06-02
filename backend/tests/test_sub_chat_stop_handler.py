# backend/tests/test_sub_chat_stop_handler.py
#
# Unit coverage for stopping sequential sub-chat queues from the websocket layer.
# The tests use fake cache, Directus, manager, and Celery control objects so no
# real Redis, Directus, Celery worker, or LLM provider is required.

from typing import Any

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import sub_chat_stop_handler


class FakeCache:
    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.cleared_active: list[str] = []

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.context

    async def set(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        self.context = value

    async def delete(self, key: str) -> None:
        self.context = {}

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        self.published.append((channel, payload))

    async def clear_active_ai_task(self, chat_id: str) -> bool:
        self.cleared_active.append(chat_id)
        return True


class FakeDirectusChat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return True


class FakeDirectus:
    def __init__(self) -> None:
        self.chat = FakeDirectusChat()


class FakeManager:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_personal_message(self, message: dict[str, Any], user_id: str, device_fingerprint_hash: str) -> None:
        self.messages.append(message)


def sequential_context() -> dict[str, Any]:
    return {
        "parent_task_id": "parent-task",
        "parent_request_data": {"user_id_hash": "hash-1"},
        "execution_mode": "sequential",
        "expected_sub_chat_ids": ["child-1", "child-2", "child-3"],
        "completed": {"child-1": {"summary": "done", "task_id": "task-1"}},
        "active_sub_chat_id": "child-2",
        "active_task_id": "task-2",
    }


@pytest.mark.asyncio
async def test_sub_chat_stop_revokes_active_child_and_cancels_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = FakeCache(sequential_context())
    manager = FakeManager()
    revoked: list[str] = []
    monkeypatch.setattr(sub_chat_stop_handler, "_revoke_child_task", lambda task_id: revoked.append(task_id))

    await sub_chat_stop_handler.handle_sub_chat_stop(
        manager=manager,  # type: ignore[arg-type]
        user_id="user-1",
        device_fingerprint_hash="device-1",
        payload={"chat_id": "parent-chat", "task_id": "parent-task"},
        cache_service=cache,  # type: ignore[arg-type]
        directus_service=FakeDirectus(),  # type: ignore[arg-type]
    )

    assert revoked == ["task-2"]
    assert cache.cleared_active == ["child-2"]
    assert cache.context["stop_requested"] is True
    assert cache.context["completed"]["child-3"]["cancelled"] is True
    assert cache.published[0][0] == "chat_stream::parent-chat"
    assert cache.published[0][1]["status"] == "stopping"
    assert manager.messages[0]["payload"]["status"] == "stopping"
