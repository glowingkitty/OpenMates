"""Processor guard coverage for task queue auto-continuation.

These tests keep the expensive model loop out of scope and verify the deterministic
contract used by main_processor.py: task queues are evaluated before plan
continuation, and a no-tool assistant turn with remaining task work requests one
more tool-capable iteration instead of being treated as finished.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.task_queue_continuation import (
    build_task_queue_continuation_event,
    evaluate_task_queue_post_turn,
    filter_plan_skills_for_task_queue,
    is_task_activity_system_content,
    is_task_queue_continuation_system_content,
    task_context_blocks_plan_creation,
    task_queue_llm_history_role,
    task_queue_post_turn_prompt,
)
from backend.apps.ai.processing.task_tool_context import TaskToolContext, build_task_context_prompt, refresh_task_tool_context


# contract-test: direct surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.capacity-scoped,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_post_turn_guard_starts_next_task_before_plan_continuation() -> None:
    methods = AsyncMock()
    next_task = {"id": "row-ai", "task_id": "task-ai", "primary_chat_id": "chat-1", "hashed_user_id": "owner", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 2, "position": 20, "created_at": 100}
    methods.list_tasks.return_value = [next_task]
    methods.list_open_tasks_for_admission.return_value = [next_task]
    methods.acquire_admission_lock.return_value = "scope-lock"
    methods.admission_blockers.return_value = []
    methods.claim_ai_task.return_value = {**next_task, "status": "in_progress", "queue_state": "active"}
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
    methods.claim_ai_task.assert_awaited_once_with(next_task, 1500)


# contract-test: supporting surface=rest_api assertions=tasks.execution.order-preserved,tasks.lifecycle.visible
@pytest.mark.asyncio
async def test_post_turn_guard_retries_active_task_without_mutating_metadata() -> None:
    methods = AsyncMock()
    methods.list_tasks.return_value = [
        {"task_id": "task-active", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "in_progress", "version": 3, "position": 10, "created_at": 100},
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


# contract-test: supporting surface=rest_api assertions=tasks.execution.order-preserved,tasks.lifecycle.visible
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
        {"task_id": "task-ai-later", "assignee_type": "openmates", "assignee_identity": "openmates", "status": "todo", "version": 2, "position": 30, "created_at": 100},
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


# contract-test: supporting surface=rest_api assertions=tasks.execution.order-preserved
def test_task_context_blocks_plan_creation_for_open_chat_tasks() -> None:
    context = SimpleNamespace(
        visible_tasks=[
            {"task_id": "task-done", "status": "done", "queue_state": "none"},
            {"task_id": "task-open", "status": "todo", "queue_state": "none"},
        ]
    )

    assert task_context_blocks_plan_creation(context) is True

    filtered, removed = filter_plan_skills_for_task_queue(
        {"plans-create", "plans-search", "web-search"},
        context,
    )
    assert filtered == {"web-search"}
    assert removed == {"plans-create", "plans-search"}


# contract-test: supporting surface=rest_api assertions=tasks.execution.order-preserved
def test_task_context_allows_plan_creation_when_tasks_are_closed() -> None:
    context = SimpleNamespace(
        visible_tasks=[
            {"task_id": "task-done", "status": "done", "queue_state": "none"},
            {"task_id": "task-skipped", "status": "todo", "queue_state": "skipped"},
        ]
    )

    assert task_context_blocks_plan_creation(context) is False
    filtered, removed = filter_plan_skills_for_task_queue({"plans-create"}, context)
    assert filtered == {"plans-create"}
    assert removed == set()


# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible,tasks.content.client-encrypted
def test_task_queue_continuation_event_is_turn_scoped_and_safe() -> None:
    result = {
        "state": "started_next_ai_task",
        "task_id": "task-ai",
        "short_id": "TASK-42",
        "chat_id": "chat-1",
    }

    event = build_task_queue_continuation_event(result, message_id="message-1", now=1700)

    assert event == {
        "event_id": "task-queue-continuation-message-1-task-ai-started_next_ai_task",
        "chat_id": "chat-1",
        "task_id": "task-ai",
        "event_type": "started",
        "status": "in_progress",
        "created_at": 1700,
        "message_id": "message-1",
        "short_id": "TASK-42",
    }


# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
def test_task_queue_continuation_system_content_detects_synthetic_user_history() -> None:
    prompt = task_queue_post_turn_prompt({"state": "active_ai_task", "task_id": "TASK-42"})

    assert is_task_queue_continuation_system_content(prompt) is True
    assert is_task_queue_continuation_system_content("TASK-42 created") is False


# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
def test_task_activity_system_content_detects_client_persisted_task_events() -> None:
    assert is_task_activity_system_content("TASK-42 completed") is True
    assert is_task_activity_system_content("TASK-42 continuing (in_progress)") is True
    assert is_task_activity_system_content("TASK-42 started (in_progress)") is True
    assert is_task_activity_system_content("TASK-42 moved") is True
    assert is_task_activity_system_content("ae083c42-a81d-488b-ad25-95b2e7b2c6dc created \"Task\" (todo)") is True
    assert is_task_activity_system_content("Task queue continuation: TASK-42 started") is False
    assert is_task_activity_system_content("Something else completed") is False


# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
def test_llm_history_maps_persisted_task_queue_system_notice_to_user() -> None:
    prompt = task_queue_post_turn_prompt({"state": "active_ai_task", "task_id": "TASK-42"})

    assert task_queue_llm_history_role("system", prompt) == "user"
    assert task_queue_llm_history_role("system", "TASK-42 created") == "user"
    assert task_queue_llm_history_role("system", "TASK-42 continuing (in_progress)") == "user"
    assert task_queue_llm_history_role("system", "ae083c42-a81d-488b-ad25-95b2e7b2c6dc created \"Task\" (todo)") == "user"
    assert task_queue_llm_history_role("system", "Something else completed") == "system"


# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
def test_task_queue_post_turn_prompt_prefers_short_id() -> None:
    prompt = task_queue_post_turn_prompt({"state": "started_next_ai_task", "task_id": "uuid-task", "short_id": "TASK-42"})

    assert "TASK-42" in prompt
    assert "uuid-task" not in prompt


# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible,tasks.execution.order-preserved
@pytest.mark.asyncio
async def test_refresh_task_tool_context_reloads_tasks_and_preserves_turn_state() -> None:
    existing = TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[{"task_id": "task-next", "short_id": "TASK-42", "status": "todo", "version": 1}],
    )
    existing.client_persisted_task_ids.add("task-created")
    existing.client_persisted_create_titles["created task"] = "task-created"
    existing.created_task_sequence = 3
    methods = AsyncMock()
    methods.list_tasks.return_value = [
        {
            "task_id": "task-next",
            "short_id": "TASK-42",
            "primary_chat_id": "chat-1",
            "status": "in_progress",
            "queue_state": "active",
            "version": 2,
        },
    ]

    refreshed = await refresh_task_tool_context(
        existing_context=existing,
        task_methods=methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text=None,
    )

    assert refreshed.attached_tasks[0]["status"] == "in_progress"
    assert refreshed.attached_tasks[0]["version"] == 2
    assert refreshed.client_persisted_task_ids == {"task-created"}
    assert refreshed.client_persisted_create_titles == {"created task": "task-created"}
    assert refreshed.created_task_sequence == 3
    assert "TASK-42: status=in_progress, version=2" in build_task_context_prompt(refreshed)
