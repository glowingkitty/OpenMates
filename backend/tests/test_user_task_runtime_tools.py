"""Tests for explicit Tasks V1 runtime queue transitions.

The assistant must commit task progress through task actions instead of prose.
These tests exercise queue-safe metadata transitions without a live Directus
instance so route, CLI, and future assistant tools share one deterministic
contract.
"""

from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.user_task_queue_service import UserTaskQueueService


def _configure_admission(methods, tasks, claimed):
    methods.list_open_tasks_for_admission.return_value = tasks
    methods.admission_blockers.return_value = []
    methods.acquire_admission_lock.return_value = "scope-lock"
    methods.claim_ai_task.return_value = claimed


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_skip_marks_backlog_skipped_and_starts_next_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {
        "task_id": "task-1",
        "primary_chat_id": "chat-1",
        "version": 2,
    }
    next_task = {"id": "row-2", "task_id": "task-2", "primary_chat_id": "chat-1", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 1, "started_at": None, "hashed_user_id": "owner"}
    methods.list_tasks.return_value = [next_task]
    methods.update_task_if_version.return_value = {"task_id": "task-1", "status": "backlog", "queue_state": "skipped"}
    _configure_admission(methods, [next_task], {**next_task, "status": "in_progress", "queue_state": "active", "ai_execution_state": "queued"})

    result = await UserTaskQueueService(methods).skip_task("task-1", "user-1", version=2, now=500)

    assert result["status"] == "backlog"
    assert result["queue_state"] == "skipped"
    assert result["next_task_id"] == "task-2"
    skipped_patch = methods.update_task_if_version.await_args_list[0].args[2]
    assert methods.update_task_if_version.await_args_list[0].args[3] == 2
    assert skipped_patch["status"] == "backlog"
    assert skipped_patch["queue_state"] == "skipped"
    assert skipped_patch["ai_execution_state"] == "skipped"
    methods.claim_ai_task.assert_awaited_once_with(next_task, 500)


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.capacity-scoped,tasks.blocking.encrypted-reason
@pytest.mark.asyncio
async def test_block_pauses_queue_with_safe_code_and_encrypted_reason() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 4}
    methods.update_task_if_version.return_value = {
        "task_id": "task-1",
        "status": "blocked",
        "queue_state": "waiting_for_user",
        "blocked_reason_code": "missing_credentials",
        "encrypted_blocked_reason": "cipher-blocked-reason",
    }

    result = await UserTaskQueueService(methods).block_task(
        "task-1",
        "user-1",
        version=4,
        blocked_reason_code="missing_credentials",
        encrypted_blocked_reason="cipher-blocked-reason",
        now=700,
    )

    assert result["status"] == "blocked"
    assert result["queue_state"] == "waiting_for_user"
    patch = methods.update_task_if_version.await_args.args[2]
    assert methods.update_task_if_version.await_args.args[3] == 4
    assert patch == {
        "version": 4,
        "status": "blocked",
        "queue_state": "waiting_for_user",
        "blocked_reason_code": "missing_credentials",
        "encrypted_blocked_reason": "cipher-blocked-reason",
        "ai_execution_state": "waiting_for_user",
        "updated_at": 700,
    }


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.capacity-scoped
@pytest.mark.asyncio
async def test_complete_starts_next_eligible_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 3}
    next_task = {"id": "row-ai", "task_id": "task-ai", "primary_chat_id": "chat-1", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 1, "hashed_user_id": "owner"}
    methods.list_tasks.return_value = [next_task]
    methods.update_task_if_version.return_value = {"task_id": "task-1", "status": "done", "queue_state": "none"}
    _configure_admission(methods, [next_task], {**next_task, "status": "in_progress", "queue_state": "active"})

    result = await UserTaskQueueService(methods).complete_task("task-1", "user-1", version=3, now=900)

    assert result["status"] == "done"
    assert result["next_task_id"] == "task-ai"
    done_patch = methods.update_task_if_version.await_args_list[0].args[2]
    assert methods.update_task_if_version.await_args_list[0].args[3] == 3
    assert done_patch["status"] == "done"
    assert done_patch["queue_state"] == "none"
    methods.claim_ai_task.assert_awaited_once_with(next_task, 900)


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_complete_uses_ordered_chat_queue_for_next_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 5}
    queued = [
        {"id": "row-late", "task_id": "task-late", "primary_chat_id": "chat-1", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 1, "position": 30, "created_at": 100, "hashed_user_id": "owner"},
        {"id": "row-early", "task_id": "task-early", "primary_chat_id": "chat-1", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 2, "position": 20, "created_at": 200, "hashed_user_id": "owner"},
        {"id": "row-first", "task_id": "task-same-position", "primary_chat_id": "chat-1", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 3, "position": 20, "created_at": 100, "hashed_user_id": "owner"},
    ]
    methods.list_tasks.return_value = queued
    methods.update_task_if_version.return_value = {"task_id": "task-1", "status": "done", "queue_state": "none"}
    _configure_admission(methods, queued, {**queued[2], "status": "in_progress", "queue_state": "active"})

    result = await UserTaskQueueService(methods).complete_task("task-1", "user-1", version=5, now=1200)

    assert result["next_task_id"] == "task-same-position"
    assert result["queue_result"] == {
        "state": "started_next_ai_task",
        "task_id": "task-same-position",
        "chat_id": "chat-1",
    }
    methods.list_tasks.assert_awaited_once_with("user-1", chat_id="chat-1", team_id=None, limit=500)
    methods.claim_ai_task.assert_awaited_once_with(queued[2], 1200)


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_complete_pauses_on_blocking_human_task_before_later_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 5}
    methods.list_tasks.return_value = [
        {
            "task_id": "task-human-blocker",
            "assignee_type": "user",
            "status": "blocked",
            "queue_state": "waiting_for_user",
            "blocked_reason_code": "needs_user_input",
            "position": 20,
            "created_at": 100,
        },
        {"task_id": "task-ai", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 2, "position": 30, "created_at": 100},
    ]
    methods.update_task_if_version.return_value = {"task_id": "task-1", "status": "done", "queue_state": "none"}

    result = await UserTaskQueueService(methods).complete_task("task-1", "user-1", version=5, now=1200)

    assert "next_task_id" not in result
    assert result["queue_result"] == {
        "state": "blocked_by_human_task",
        "task_id": "task-human-blocker",
        "chat_id": "chat-1",
        "blocked_reason_code": "needs_user_input",
    }
    assert methods.update_task_if_version.await_count == 1


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_complete_waits_for_user_ordered_human_task_before_later_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 5}
    methods.list_tasks.return_value = [
        {"task_id": "task-human", "assignee_type": "user", "status": "todo", "queue_state": "none", "position": 20, "created_at": 100},
        {"task_id": "task-ai", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 2, "position": 30, "created_at": 100},
    ]
    methods.update_task_if_version.return_value = {"task_id": "task-1", "status": "done", "queue_state": "none"}

    result = await UserTaskQueueService(methods).complete_task("task-1", "user-1", version=5, now=1200)

    assert "next_task_id" not in result
    assert result["queue_result"] == {
        "state": "blocked_by_human_task",
        "task_id": "task-human",
        "chat_id": "chat-1",
        "blocked_reason_code": "waiting_for_previous_task",
    }
    methods.claim_ai_task.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_complete_refills_scope_capacity_even_when_source_chat_is_blocked() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 5}
    methods.list_tasks.return_value = [
        {"task_id": "human-blocker", "assignee_type": "user", "status": "blocked", "position": 10},
    ]
    methods.update_task_if_version.return_value = {"task_id": "task-1", "status": "done", "queue_state": "none"}
    admission = AsyncMock()
    admission.admit_available.return_value = {
        "admitted_task_ids": ["other-chat-task"],
        "admitted_tasks": [
            {"task_id": "other-chat-task", "primary_chat_id": "chat-2", "status": "in_progress"},
        ],
    }

    result = await UserTaskQueueService(methods, admission_service=admission).complete_task(
        "task-1",
        "user-1",
        version=5,
        now=1200,
    )

    assert result["queue_result"]["state"] == "blocked_by_human_task"
    admission.admit_available.assert_awaited_once_with(
        "user-1",
        team_id=None,
        now=1200,
        preferred_chat_id="chat-1",
    )


# contract-test: direct surface=rest_api assertions=tasks.execution.capacity-scoped,tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_team_completion_updates_team_row_and_refills_team_pool() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "team-task", "primary_chat_id": "chat-1", "version": 2}
    methods.update_task_if_version.return_value = {"task_id": "team-task", "status": "done", "version": 3}
    methods.list_tasks.return_value = []
    admission = AsyncMock()
    admission.admit_available.return_value = {"admitted_task_ids": [], "admitted_tasks": []}

    result = await UserTaskQueueService(methods, admission_service=admission).complete_task(
        "team-task",
        "actor-1",
        version=2,
        team_id="team-1",
        now=1300,
    )

    assert result["status"] == "done"
    methods.get_task.assert_awaited_once_with("team-task", "actor-1", "team-1")
    assert methods.update_task_if_version.await_args.kwargs["team_id"] == "team-1"
    admission.admit_available.assert_awaited_once_with(
        "actor-1",
        team_id="team-1",
        now=1300,
        preferred_chat_id="chat-1",
    )
