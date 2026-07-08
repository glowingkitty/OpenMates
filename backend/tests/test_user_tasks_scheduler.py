"""Tests for restart-safe user task scheduling.

The scheduler operates on durable Directus rows rather than in-memory timers so
AI-assigned due tasks recover after worker restarts or missed beat windows.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods
from backend.core.api.app.services.user_task_scheduler_service import process_due_ai_tasks


@pytest.mark.asyncio
async def test_process_due_ai_tasks_starts_due_rows() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "row-1", "task_id": "task-1", "version": 2}])
    directus.update_item = AsyncMock(return_value={"id": "row-1", "status": "in_progress"})

    result = await process_due_ai_tasks(UserTaskMethods(directus), now=200)

    assert result == {"checked": 1, "started": 1, "failed_task_ids": []}
    collection, row_id, update = directus.update_item.await_args.args
    assert collection == "user_tasks"
    assert row_id == "row-1"
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
