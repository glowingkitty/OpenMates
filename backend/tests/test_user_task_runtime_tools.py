"""Tests for explicit Tasks V1 runtime queue transitions.

The assistant must commit task progress through task actions instead of prose.
These tests exercise queue-safe metadata transitions without a live Directus
instance so route, CLI, and future assistant tools share one deterministic
contract.
"""

from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.user_task_queue_service import UserTaskQueueService


@pytest.mark.asyncio
async def test_skip_marks_backlog_skipped_and_starts_next_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {
        "task_id": "task-1",
        "primary_chat_id": "chat-1",
        "version": 2,
    }
    methods.list_tasks.return_value = [
        {"task_id": "task-2", "assignee_type": "ai", "version": 1, "started_at": None},
    ]
    methods.update_task_if_version.side_effect = [
        {"task_id": "task-1", "status": "backlog", "queue_state": "skipped"},
        {"task_id": "task-2", "status": "in_progress", "queue_state": "active"},
    ]

    result = await UserTaskQueueService(methods).skip_task("task-1", "user-1", version=2, now=500)

    assert result["status"] == "backlog"
    assert result["queue_state"] == "skipped"
    assert result["next_task_id"] == "task-2"
    skipped_patch = methods.update_task_if_version.await_args_list[0].args[2]
    assert methods.update_task_if_version.await_args_list[0].args[3] == 2
    assert skipped_patch["status"] == "backlog"
    assert skipped_patch["queue_state"] == "skipped"
    assert skipped_patch["ai_execution_state"] == "skipped"
    next_patch = methods.update_task_if_version.await_args_list[1].args[2]
    assert methods.update_task_if_version.await_args_list[1].args[3] == 1
    assert next_patch["status"] == "in_progress"
    assert next_patch["queue_state"] == "active"
    assert next_patch["ai_execution_state"] == "queued"
    assert next_patch["started_at"] == 500


@pytest.mark.asyncio
async def test_block_pauses_queue_with_safe_reason() -> None:
    methods = AsyncMock()
    methods.update_task_if_version.return_value = {
        "task_id": "task-1",
        "status": "blocked",
        "queue_state": "waiting_for_user",
        "blocked_reason_code": "needs_input",
    }

    result = await UserTaskQueueService(methods).block_task(
        "task-1",
        "user-1",
        version=4,
        blocked_reason_code="needs_input",
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
        "blocked_reason_code": "needs_input",
        "ai_execution_state": "waiting_for_user",
        "updated_at": 700,
    }


@pytest.mark.asyncio
async def test_complete_starts_next_eligible_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 3}
    methods.list_tasks.return_value = [
        {"task_id": "task-user", "assignee_type": "user", "version": 1},
        {"task_id": "task-ai", "assignee_type": "ai", "version": 1},
    ]
    methods.update_task_if_version.side_effect = [
        {"task_id": "task-1", "status": "done", "queue_state": "none"},
        {"task_id": "task-ai", "status": "in_progress", "queue_state": "active"},
    ]

    result = await UserTaskQueueService(methods).complete_task("task-1", "user-1", version=3, now=900)

    assert result["status"] == "done"
    assert result["next_task_id"] == "task-ai"
    done_patch = methods.update_task_if_version.await_args_list[0].args[2]
    assert methods.update_task_if_version.await_args_list[0].args[3] == 3
    assert done_patch["status"] == "done"
    assert done_patch["queue_state"] == "none"
    next_patch = methods.update_task_if_version.await_args_list[1].args[2]
    assert methods.update_task_if_version.await_args_list[1].args[3] == 1
    assert next_patch["status"] == "in_progress"
    assert next_patch["queue_state"] == "active"


@pytest.mark.asyncio
async def test_complete_uses_ordered_chat_queue_for_next_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 5}
    methods.list_tasks.return_value = [
        {"task_id": "task-late", "assignee_type": "ai", "status": "todo", "version": 1, "position": 30, "created_at": 100},
        {"task_id": "task-early", "assignee_type": "ai", "status": "todo", "version": 2, "position": 20, "created_at": 200},
        {"task_id": "task-same-position", "assignee_type": "ai", "status": "todo", "version": 3, "position": 20, "created_at": 100},
    ]
    methods.update_task_if_version.side_effect = [
        {"task_id": "task-1", "status": "done", "queue_state": "none"},
        {"task_id": "task-same-position", "status": "in_progress", "queue_state": "active"},
    ]

    result = await UserTaskQueueService(methods).complete_task("task-1", "user-1", version=5, now=1200)

    assert result["next_task_id"] == "task-same-position"
    assert result["queue_result"] == {
        "state": "started_next_ai_task",
        "task_id": "task-same-position",
        "chat_id": "chat-1",
    }
    methods.list_tasks.assert_awaited_once_with("user-1", chat_id="chat-1", limit=500)
    next_call = methods.update_task_if_version.await_args_list[1]
    assert next_call.args[0] == "task-same-position"
    assert next_call.args[3] == 3


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
        {"task_id": "task-ai", "assignee_type": "ai", "status": "todo", "version": 2, "position": 30, "created_at": 100},
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


@pytest.mark.asyncio
async def test_complete_skips_independent_human_task_and_starts_later_ai_task() -> None:
    methods = AsyncMock()
    methods.get_task.return_value = {"task_id": "task-1", "primary_chat_id": "chat-1", "version": 5}
    methods.list_tasks.return_value = [
        {"task_id": "task-human", "assignee_type": "user", "status": "todo", "queue_state": "none", "position": 20, "created_at": 100},
        {"task_id": "task-ai", "assignee_type": "ai", "status": "todo", "version": 2, "position": 30, "created_at": 100},
    ]
    methods.update_task_if_version.side_effect = [
        {"task_id": "task-1", "status": "done", "queue_state": "none"},
        {"task_id": "task-ai", "status": "in_progress", "queue_state": "active"},
    ]

    result = await UserTaskQueueService(methods).complete_task("task-1", "user-1", version=5, now=1200)

    assert result["next_task_id"] == "task-ai"
    assert result["queue_result"] == {
        "state": "started_next_ai_task",
        "task_id": "task-ai",
        "chat_id": "chat-1",
    }
    next_call = methods.update_task_if_version.await_args_list[1]
    assert next_call.args[0] == "task-ai"
