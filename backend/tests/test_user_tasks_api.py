"""Tests for privacy-preserving user task backend helpers.

User-facing tasks are distinct from Celery task polling. These tests focus on
the Directus/service contract so they run without a live CMS or FastAPI app.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, hash_id
from backend.core.api.app.services.user_task_service import UserTaskConflictError, UserTaskService


def task_payload(**overrides):
    base = {
        "task_id": "task-1",
        "encrypted_task_key": "cipher-task-key",
        "encrypted_title": "cipher-title",
        "encrypted_description": "cipher-description",
        "encrypted_tags": "cipher-tags",
        "status": "todo",
        "assignee_type": "user",
        "assignee_hash": hash_id("user-1"),
        "primary_chat_id": "chat-1",
        "linked_project_ids": ["project-1"],
        "due_at": None,
        "priority": 0,
        "position": 10,
        "created_at": 100,
        "updated_at": 100,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_create_task_hashes_owner_and_projects_without_plaintext_content() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1", **task_payload()}))

    methods = UserTaskMethods(directus)
    created = await methods.create_task("user-1", task_payload())

    assert created is not None
    collection, record = directus.create_item.await_args.args
    assert collection == "user_tasks"
    assert record["hashed_user_id"] == hash_id("user-1")
    assert record["hashed_primary_chat_id"] == hash_id("chat-1")
    assert record["linked_project_ids"] == [hash_id("project-1")]
    assert record["encrypted_title"] == "cipher-title"
    assert record["encrypted_task_key"] == "cipher-task-key"
    assert "title" not in record
    assert "description" not in record


@pytest.mark.asyncio
async def test_list_tasks_filters_by_chat_and_project_hashes() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    methods = UserTaskMethods(directus)
    await methods.list_tasks("user-1", chat_id="chat-1", project_id="project-1", status="todo")

    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_user_id][_eq]"] == hash_id("user-1")
    assert params["filter[hashed_primary_chat_id][_eq]"] == hash_id("chat-1")
    assert params["filter[linked_project_ids][_contains]"] == hash_id("project-1")
    assert params["filter[status][_eq]"] == "todo"


@pytest.mark.asyncio
async def test_update_rejects_stale_version() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "version": 3, "task_id": "task-1"}])
    directus.update_item = AsyncMock()

    service = UserTaskService(UserTaskMethods(directus))

    with pytest.raises(UserTaskConflictError):
        await service.update_task("task-1", "user-1", {"status": "done", "version": 2})

    directus.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_task_without_due_date_starts_immediately() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=lambda _collection, record: (True, record))

    service = UserTaskService(UserTaskMethods(directus))
    created = await service.create_task("user-1", task_payload(assignee_type="ai", due_at=None))

    assert created["status"] == "in_progress"
    assert created["ai_execution_state"] == "queued"
    assert created["started_at"] == 100


@pytest.mark.asyncio
async def test_product_task_helpers_do_not_use_celery_tasks_collection() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    methods = UserTaskMethods(directus)
    await methods.list_tasks("user-1")

    collection = directus.get_items.await_args.args[0]
    assert collection == "user_tasks"
    assert collection != "tasks"


@pytest.mark.asyncio
async def test_start_ai_dispatches_transient_plaintext_without_persisting() -> None:
    existing = {"id": "row-1", "version": 2, **task_payload()}
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[existing])
    directus.update_item = AsyncMock(side_effect=lambda _collection, _row_id, patch: {**existing, **patch})
    cache = SimpleNamespace(set_active_ai_task=AsyncMock())
    dispatched: dict[str, object] = {}

    async def fake_dispatcher(app_id: str, skill_id: str, payload: dict[str, object]) -> dict[str, str]:
        dispatched.update({"app_id": app_id, "skill_id": skill_id, "payload": payload})
        return {"task_id": "ai-task-1"}

    service = UserTaskService(
        UserTaskMethods(directus),
        cache_service=cache,
        ai_dispatcher=fake_dispatcher,
    )

    updated = await service.start_ai(
        "task-1",
        "user-1",
        {
            "version": 2,
            "primary_chat_id": "chat-1",
            "plaintext_title": "Draft the launch plan",
            "plaintext_description": "Use the current project context.",
            "updated_at": 200,
        },
    )

    persisted_patch = directus.update_item.await_args_list[0].args[2]
    assert updated["ai_execution_state"] == "queued"
    assert persisted_patch["status"] == "in_progress"
    assert "plaintext_title" not in persisted_patch
    assert "plaintext_description" not in persisted_patch

    payload = dispatched["payload"]
    assert dispatched["app_id"] == "ai"
    assert dispatched["skill_id"] == "ask"
    assert isinstance(payload, dict)
    assert payload["user_task_id"] == "task-1"
    assert payload["chat_id"] == "chat-1"
    assert "Draft the launch plan" in str(payload["current_user_content"])
    assert "Use the current project context." in str(payload["current_user_content"])
    cache.set_active_ai_task.assert_awaited_once_with("chat-1", "ai-task-1")
