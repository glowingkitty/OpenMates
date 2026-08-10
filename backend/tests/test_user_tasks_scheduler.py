"""Tests for restart-safe user task scheduling.

The scheduler operates on durable Directus rows rather than in-memory timers so
AI-assigned due tasks recover after worker restarts or missed beat windows.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, hash_id
from backend.core.api.app.services.user_task_scheduler_service import process_due_ai_tasks


class FakeLockClient:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class FakeCache:
    def __init__(self):
        self.client_value = FakeLockClient()

    @property
    def client(self):
        return self._client()

    async def _client(self):
        return self.client_value


@pytest.mark.asyncio
async def test_process_due_ai_tasks_starts_due_rows() -> None:
    directus = SimpleNamespace()
    directus.cache = FakeCache()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "task_id": "task-1", "hashed_user_id": hash_id("user-1"), "version": 2}])
    directus.update_item_if_version = AsyncMock(return_value={"id": "row-1", "status": "in_progress"})

    result = await process_due_ai_tasks(UserTaskMethods(directus), now=200)

    assert result == {"checked": 1, "started": 1, "failed_task_ids": []}
    collection, row_id, update, expected_version = directus.update_item_if_version.await_args.args
    assert collection == "user_tasks"
    assert row_id == "row-1"
    assert expected_version == 2
    assert directus.update_item_if_version.await_args.kwargs["owner_hash"] == hash_id("user-1")
    assert update["status"] == "in_progress"
    assert update["ai_execution_state"] == "queued"
    assert update["started_at"] == 200
    assert update["version"] == 3


@pytest.mark.asyncio
async def test_due_ai_query_uses_durable_filters() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    await UserTaskMethods(directus).list_due_ai_tasks(200)

    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[assignee_type][_eq]"] == "ai"
    assert params["filter[due_at][_lte]"] == 200
    assert params["filter[status][_in]"] == ["backlog", "todo"]


@pytest.mark.asyncio
async def test_process_due_ai_tasks_skips_rows_without_version() -> None:
    directus = SimpleNamespace()
    directus.cache = FakeCache()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "task_id": "task-1", "hashed_user_id": hash_id("user-1")}])
    directus.update_item_if_version = AsyncMock()

    result = await process_due_ai_tasks(UserTaskMethods(directus), now=200)

    assert result == {"checked": 1, "started": 0, "failed_task_ids": []}
    directus.update_item_if_version.assert_not_awaited()
