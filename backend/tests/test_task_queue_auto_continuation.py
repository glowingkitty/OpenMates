"""Processor guard coverage for task queue auto-continuation.

These tests keep the expensive model loop out of scope and verify the deterministic
contract used by main_processor.py: task queues are evaluated before plan
continuation, and a no-tool assistant turn with remaining task work requests one
more tool-capable iteration instead of being treated as finished.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.task_queue_continuation import evaluate_task_queue_post_turn, task_queue_post_turn_prompt


@pytest.mark.asyncio
async def test_post_turn_guard_starts_next_task_before_plan_continuation() -> None:
    methods = AsyncMock()
    methods.list_tasks.return_value = [
        {"task_id": "task-ai", "assignee_type": "ai", "status": "todo", "version": 2, "position": 20, "created_at": 100},
    ]
    methods.update_task_if_version.return_value = {"task_id": "task-ai", "status": "in_progress", "queue_state": "active"}
    directus = SimpleNamespace(user_task=methods)

    result = await evaluate_task_queue_post_turn(
        task_tool_context=object(),
        directus_service=directus,
        user_id="user-1",
        chat_id="chat-1",
        now=1500,
    )

    assert result == {
        "state": "started_next_ai_task",
        "task_id": "task-ai",
        "chat_id": "chat-1",
        "requires_model_retry": True,
        "task_queue_blocks_plan": True,
    }
    patch = methods.update_task_if_version.await_args.args[2]
    assert patch["status"] == "in_progress"
    assert patch["ai_execution_state"] == "queued"


@pytest.mark.asyncio
async def test_post_turn_guard_retries_active_task_without_mutating_metadata() -> None:
    methods = AsyncMock()
    methods.list_tasks.return_value = [
        {"task_id": "task-active", "assignee_type": "ai", "status": "in_progress", "version": 3, "position": 10, "created_at": 100},
    ]
    directus = SimpleNamespace(user_task=methods)

    result = await evaluate_task_queue_post_turn(
        task_tool_context=object(),
        directus_service=directus,
        user_id="user-1",
        chat_id="chat-1",
        now=1500,
    )

    assert result == {
        "state": "active_ai_task",
        "task_id": "task-active",
        "chat_id": "chat-1",
        "requires_model_retry": True,
        "task_queue_blocks_plan": True,
    }
    methods.update_task_if_version.assert_not_awaited()
    assert "Use explicit task tools" in task_queue_post_turn_prompt(result)


@pytest.mark.asyncio
async def test_post_turn_guard_blocks_plan_on_human_gate_without_retry() -> None:
    methods = AsyncMock()
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
        {"task_id": "task-ai-later", "assignee_type": "ai", "status": "todo", "version": 2, "position": 30, "created_at": 100},
    ]
    directus = SimpleNamespace(user_task=methods)

    result = await evaluate_task_queue_post_turn(
        task_tool_context=object(),
        directus_service=directus,
        user_id="user-1",
        chat_id="chat-1",
        now=1500,
    )

    assert result == {
        "state": "blocked_by_human_task",
        "task_id": "task-human-blocker",
        "chat_id": "chat-1",
        "blocked_reason_code": "needs_user_input",
        "requires_model_retry": False,
        "task_queue_blocks_plan": True,
    }
    methods.update_task_if_version.assert_not_awaited()
