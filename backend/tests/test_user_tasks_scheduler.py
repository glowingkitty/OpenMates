"""Tests for restart-safe user task scheduling.

The scheduler operates on durable Directus rows rather than in-memory timers so
AI-assigned due tasks recover after worker restarts or missed beat windows.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_task_methods import TaskLockBusyError, UserTaskMethods, hash_id
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


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_process_due_ai_tasks_starts_due_rows() -> None:
    directus = SimpleNamespace()
    directus.cache = FakeCache()
    task = {"id": "row-1", "task_id": "task-1", "hashed_user_id": hash_id("user-1"), "status": "todo", "assignee_type": "openmates", "assignee_identity": "openmates", "version": 2}
    directus.get_items = AsyncMock(side_effect=[[task], [], [], [task], []])
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


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_due_ai_query_uses_durable_filters() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    await UserTaskMethods(directus).list_due_ai_tasks(200)

    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[assignee_type][_eq]"] == "openmates"
    assert params["filter[due_at][_lte]"] == 200
    assert params["filter[status][_eq]"] == "todo"


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_stale_queued_query_only_selects_expired_dispatch_leases() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])

    await UserTaskMethods(directus).list_stale_queued_ai_tasks(200)

    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[assignee_type][_eq]"] == "openmates"
    assert params["filter[status][_eq]"] == "in_progress"
    assert params["filter[queue_state][_eq]"] == "active"
    assert params["filter[ai_execution_state][_eq]"] == "queued"
    assert params["filter[started_at][_lte]"] == 200
    assert params["sort"] == "started_at,task_id"


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_process_due_ai_tasks_skips_rows_without_version() -> None:
    directus = SimpleNamespace()
    directus.cache = FakeCache()
    task = {"id": "row-1", "task_id": "task-1", "hashed_user_id": hash_id("user-1")}
    directus.get_items = AsyncMock(side_effect=[[task], [], [], [task], []])
    directus.update_item_if_version = AsyncMock()

    result = await process_due_ai_tasks(UserTaskMethods(directus), now=200)

    assert result == {"checked": 1, "started": 0, "failed_task_ids": []}
    directus.update_item_if_version.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_scheduler_reconciles_waiting_todo_scope_without_due_task() -> None:
    task = {"id": "row-1", "task_id": "task-1", "hashed_user_id": hash_id("user-1"), "status": "todo", "assignee_type": "openmates", "assignee_identity": "openmates", "version": 2}
    directus = SimpleNamespace(cache=FakeCache())
    directus.get_items = AsyncMock(side_effect=[[], [task], [], [task], []])
    directus.update_item_if_version = AsyncMock(return_value={**task, "status": "in_progress", "version": 3})

    result = await process_due_ai_tasks(UserTaskMethods(directus), now=200)

    assert result == {"checked": 0, "started": 1, "failed_task_ids": []}
    assert directus.update_item_if_version.await_args.args[2]["ai_execution_state"] == "queued"


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_scheduler_fails_stale_queued_task_before_refill() -> None:
    stale = {
        "id": "row-1",
        "task_id": "task-1",
        "hashed_user_id": hash_id("user-1"),
        "status": "in_progress",
        "queue_state": "active",
        "ai_execution_state": "queued",
        "assignee_type": "openmates", "assignee_identity": "openmates",
        "started_at": 100,
        "version": 2,
    }
    released = {
        **stale,
        "status": "blocked",
        "queue_state": "waiting_for_user",
        "ai_execution_state": "failed",
        "blocked_reason_code": "ai_dispatch_timeout",
        "version": 3,
    }
    next_task = {
        "id": "row-2",
        "task_id": "task-2",
        "hashed_user_id": hash_id("user-1"),
        "status": "todo",
        "assignee_type": "openmates", "assignee_identity": "openmates",
        "version": 1,
    }
    directus = SimpleNamespace(cache=FakeCache())
    directus.get_items = AsyncMock(side_effect=[[], [], [stale], [released, next_task], []])
    directus.update_item_if_version = AsyncMock(
        side_effect=[released, {**next_task, "status": "in_progress", "queue_state": "active", "ai_execution_state": "queued", "version": 2}]
    )

    result = await process_due_ai_tasks(UserTaskMethods(directus), now=1_100)

    assert result == {"checked": 0, "started": 1, "failed_task_ids": []}
    recovery_update = directus.update_item_if_version.await_args_list[0].args[2]
    assert recovery_update == {
        "status": "blocked",
        "queue_state": "waiting_for_user",
        "ai_execution_state": "failed",
        "blocked_reason_code": "ai_dispatch_timeout",
        "updated_at": 1_100,
        "version": 3,
    }
    claim_update = directus.update_item_if_version.await_args_list[1].args[2]
    assert claim_update["started_at"] == 1_100


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_delayed_worker_claim_requires_task_to_still_be_queued() -> None:
    queued = {
        "id": "row-1",
        "task_id": "task-1",
        "hashed_user_id": hash_id("user-1"),
        "status": "in_progress",
        "queue_state": "active",
        "ai_execution_state": "queued",
        "version": 2,
    }
    directus = SimpleNamespace(cache=FakeCache())
    directus.get_items = AsyncMock(side_effect=[[queued], [{**queued, "status": "blocked", "ai_execution_state": "failed"}]])
    directus.update_item_if_version = AsyncMock(return_value={**queued, "ai_execution_state": "running", "version": 3})
    methods = UserTaskMethods(directus)

    claimed = await methods.claim_queued_ai_task_execution("task-1", "user-1", now=200)
    rejected = await methods.claim_queued_ai_task_execution("task-1", "user-1", now=201)

    assert claimed and claimed["ai_execution_state"] == "running"
    assert rejected is None
    assert directus.update_item_if_version.await_count == 1


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_stale_sweep_treats_worker_claim_lock_as_healthy_contention() -> None:
    stale = {
        "id": "row-1",
        "task_id": "task-1",
        "hashed_user_id": hash_id("user-1"),
        "status": "in_progress",
        "queue_state": "active",
        "ai_execution_state": "queued",
        "assignee_type": "openmates", "assignee_identity": "openmates",
        "started_at": 100,
        "version": 2,
    }
    methods = AsyncMock()
    methods.list_due_ai_tasks.return_value = []
    methods.list_waiting_ai_task_scopes_for_reconciliation.return_value = []
    methods.list_stale_queued_ai_tasks.return_value = [stale]
    methods.fail_stale_queued_ai_task.side_effect = TaskLockBusyError("Task is already being updated")

    result = await process_due_ai_tasks(methods, now=1_100)

    assert result == {"checked": 0, "started": 0, "failed_task_ids": []}
    methods.acquire_hashed_admission_lock.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
def test_ai_worker_exits_when_delayed_user_task_dispatch_loses_fence() -> None:
    source = (Path(__file__).resolve().parents[1] / "apps" / "ai" / "tasks" / "ask_skill_task.py").read_text()
    claim_block = source.split("user_task_claimed = await _update_user_task_execution_state(", maxsplit=1)[1]
    claim_block = claim_block.split("except Exception as e:", maxsplit=1)[0]

    assert 'ai_execution_state="running"' in claim_block
    assert "if request_data.user_task_id and not user_task_claimed:" in claim_block
    assert '"status": "stale_user_task_dispatch_ignored"' in claim_block


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped
def test_reconciliation_uses_dedicated_user_tasks_queue() -> None:
    source = (Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "tasks" / "celery_config.py").read_text()
    schedule = source.split("'process-due-ai-user-tasks':", maxsplit=1)[1].split("'archive-completed-user-tasks-daily':", maxsplit=1)[0]

    assert "'task': 'user_tasks.process_due_ai_tasks'" in schedule
    assert "'options': {'queue': 'user_tasks'}" in schedule
    assert "{'name': 'user_tasks', 'module': 'backend.core.api.app.tasks.user_task_scheduler'}" in source
    assert '"user_tasks.process_due_ai_tasks": {\'queue\': \'user_tasks\'}' in source
    assert '"user_tasks.archive_completed_tasks": {\'queue\': \'persistence\'}' in source
