# backend/tests/test_task_main_processor_tools.py
#
# Red-phase contract tests for Tasks V1 main-processor tool injection. These
# tests define the small helper seam that main_processor.py will call before the
# LLM request is sent. They avoid live Directus and model calls so the tool
# contract can be verified deterministically.

from __future__ import annotations

from unittest.mock import AsyncMock
import pytest

from backend.apps.ai.processing.task_runtime_tools import (
    TASK_TOOL_BLOCK,
    TASK_TOOL_COMPLETE,
    TASK_TOOL_CREATE,
    TASK_TOOL_MOVE,
    TASK_TOOL_UNBLOCK,
    TASK_TOOL_UPDATE,
    build_task_runtime_tools,
    merge_task_runtime_tools,
)
from backend.apps.ai.processing.task_tool_executor import (
    _check_expected_version,
    is_task_tool_name,
    task_tool_name_variants,
)
from backend.apps.ai.processing.task_tool_context import resolve_task_tool_context
from backend.apps.ai.processing.task_tool_context import TaskToolContext
from backend.core.api.app.services.user_task_service import UserTaskConflictError


def _tool_names(tools: list[dict]) -> set[str]:
    return {str(tool["function"]["name"]) for tool in tools}


@pytest.mark.asyncio
async def test_create_only_task_tool_is_injected_when_chat_has_no_visible_tasks() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = []

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Please split this launch into tasks.",
    )
    tools = build_task_runtime_tools(context)

    assert _tool_names(tools) == {TASK_TOOL_CREATE}
    task_methods.list_tasks.assert_awaited_once_with("user-1", chat_id="chat-1", limit=50)


@pytest.mark.asyncio
async def test_attached_tasks_enable_update_reorder_block_complete_and_move_tools() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = [
        {
            "task_id": "TASK-101",
            "short_id": "TASK-101",
            "primary_chat_id": "chat-1",
            "status": "todo",
            "version": 4,
        }
    ]

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Update the task list.",
    )
    names = _tool_names(build_task_runtime_tools(context))

    assert {
        TASK_TOOL_CREATE,
        TASK_TOOL_UPDATE,
        TASK_TOOL_BLOCK,
        TASK_TOOL_COMPLETE,
        TASK_TOOL_MOVE,
    }.issubset(names)
    assert "task_reorder" not in names
    assert TASK_TOOL_UNBLOCK not in names


@pytest.mark.asyncio
async def test_blocked_attached_tasks_enable_unblock_tool() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = [
        {
            "task_id": "TASK-202",
            "short_id": "TASK-202",
            "primary_chat_id": "chat-1",
            "status": "blocked",
            "version": 2,
        }
    ]

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Unblock anything waiting on me.",
    )
    names = _tool_names(build_task_runtime_tools(context))

    assert TASK_TOOL_UNBLOCK in names
    assert TASK_TOOL_BLOCK not in names


def test_task_runtime_tools_merge_with_existing_main_processor_tools_without_duplicates() -> None:
    existing_tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": TASK_TOOL_CREATE,
                "description": "Existing duplicate should not be kept.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    task_tools = [
        {
            "type": "function",
            "function": {
                "name": TASK_TOOL_CREATE,
                "description": "Create a task.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
    ]

    merged = merge_task_runtime_tools(existing_tools, task_tools)

    assert [tool["function"]["name"] for tool in merged] == ["web_search", TASK_TOOL_CREATE]


def test_reorder_tool_is_not_advertised_until_atomic_persistence_exists() -> None:
    names = _tool_names(build_task_runtime_tools(TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[{"task_id": "TASK-1", "status": "todo", "version": 1}],
    )))

    assert "task_reorder" not in names


def test_task_tool_expected_version_is_required_before_mutation() -> None:
    with pytest.raises(UserTaskConflictError, match="version is required"):
        _check_expected_version({"task_id": "task-1", "version": 2}, None)


def test_task_tool_allow_list_preserves_provider_emitted_name() -> None:
    allowed_names = task_tool_name_variants(TASK_TOOL_CREATE)

    assert TASK_TOOL_CREATE in allowed_names
    assert "task-create" in allowed_names
    assert is_task_tool_name(TASK_TOOL_CREATE)
    assert is_task_tool_name("task-create")
