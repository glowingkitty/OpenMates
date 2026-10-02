"""A finished AI answer must not manufacture a Task's Done transition."""
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.utils.user_task_turn_finalization import finalize_user_task_turn


def task(**changes):
    return {"status": "in_progress", "primary_chat_id": "chat-a", "assignee_type": "openmates",
            "ai_execution_state": "running", "version": 7, **changes}


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_reply_completion_preserves_unfinished_task_and_uses_version_fence():
    methods = AsyncMock()
    methods.get_task.return_value = task()
    await finalize_user_task_turn(methods, task_id="task-a", user_id="owner", chat_id="chat-a", team_id="team-a", now=123)
    methods.get_task.assert_awaited_once_with("task-a", "owner", "team-a")
    methods.update_task_if_version.assert_awaited_once_with(
        "task-a", "owner", {"version": 7, "ai_execution_state": "awaiting_resume", "updated_at": 123}, 7, team_id="team-a")
    methods.complete_task.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.order-preserved
@pytest.mark.asyncio
@pytest.mark.parametrize("current", [None, task(status="done"), task(status="blocked"),
    task(primary_chat_id="other-chat"), task(assignee_type="user"), task(ai_execution_state="cancelled"), task(version=None)])
async def test_explicit_transitions_reassignment_and_moves_are_preserved(current):
    methods = AsyncMock()
    methods.get_task.return_value = current
    await finalize_user_task_turn(methods, task_id="task-a", user_id="owner", chat_id="chat-a", team_id=None, now=123)
    methods.update_task_if_version.assert_not_awaited()
    methods.complete_task.assert_not_awaited()
