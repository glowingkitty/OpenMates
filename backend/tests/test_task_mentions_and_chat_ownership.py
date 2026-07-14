# backend/tests/test_task_mentions_and_chat_ownership.py
#
# Red-phase contract tests for task mention context and chat ownership. Mentions
# such as @TASK-123 should provide temporary inference context for owned tasks,
# while keeping the durable primary_chat_id unchanged unless a task_move tool is
# called explicitly.

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing.task_runtime_tools import TASK_TOOL_MOVE, build_task_runtime_tools
from backend.apps.ai.processing.task_tool_context import extract_task_mentions, resolve_task_tool_context


def _tool_by_name(tools: list[dict], name: str) -> dict:
    return next(tool for tool in tools if tool["function"]["name"] == name)


def test_extract_task_mentions_preserves_order_and_deduplicates_short_ids() -> None:
    assert extract_task_mentions("Use @TASK-123, compare @TASK-456, then revisit @TASK-123.") == [
        "TASK-123",
        "TASK-456",
    ]


@pytest.mark.asyncio
async def test_task_mentions_expose_owned_context_without_changing_primary_chat() -> None:
    task_methods = AsyncMock()
    attached = {
        "task_id": "TASK-100",
        "short_id": "TASK-100",
        "primary_chat_id": "chat-1",
        "status": "todo",
        "version": 1,
    }
    mentioned = {
        "task_id": "TASK-123",
        "short_id": "TASK-123",
        "primary_chat_id": "chat-2",
        "status": "todo",
        "version": 3,
    }
    task_methods.list_tasks.return_value = [attached]
    task_methods.get_task_by_short_id.return_value = mentioned
    task_methods.get_task.return_value = None

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Use @TASK-123 as context while planning this chat.",
    )

    assert [task["task_id"] for task in context.attached_tasks] == ["TASK-100"]
    assert [task["task_id"] for task in context.referenced_tasks] == ["TASK-123"]
    assert context.referenced_tasks[0]["primary_chat_id"] == "chat-2"
    task_methods.get_task_by_short_id.assert_awaited_once_with("TASK-123", "user-1")
    task_methods.get_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_or_unowned_task_mentions_are_ignored() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = []
    task_methods.get_task_by_short_id.return_value = None
    task_methods.get_task.return_value = None

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Summarize @TASK-999.",
    )

    assert context.referenced_tasks == []
    task_methods.get_task_by_short_id.assert_awaited_once_with("TASK-999", "user-1")
    task_methods.get_task.assert_awaited_once_with("TASK-999", "user-1")


@pytest.mark.asyncio
async def test_move_tool_requires_explicit_target_chat_and_expected_version() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = [
        {
            "task_id": "TASK-123",
            "short_id": "TASK-123",
            "primary_chat_id": "chat-1",
            "status": "todo",
            "version": 7,
        }
    ]

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Move TASK-123 to the planning chat.",
    )
    move_tool = _tool_by_name(build_task_runtime_tools(context), TASK_TOOL_MOVE)
    parameters = move_tool["function"]["parameters"]

    assert set(parameters["required"]) == {"task_id", "target_chat_id", "expected_version"}
    assert parameters["properties"]["target_chat_id"]["type"] == "string"
    assert parameters["properties"]["expected_version"]["type"] == "integer"
