# backend/apps/ai/processing/task_runtime_tools.py
#
# Tasks V1 main-processor tool schemas. The helpers here only build and merge
# function definitions; runtime mutation and client-encrypted persistence are
# implemented in later task-job services so Directus never receives plaintext
# private task content from the backend.

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.apps.ai.processing.task_tool_context import TaskToolContext

TASK_TOOL_CREATE = "task_create"
TASK_TOOL_UPDATE = "task_update"
TASK_TOOL_REORDER = "task_reorder"
TASK_TOOL_BLOCK = "task_block"
TASK_TOOL_COMPLETE = "task_complete"
TASK_TOOL_UNBLOCK = "task_unblock"
TASK_TOOL_MOVE = "task_move"

TASK_TERMINAL_STATUSES = {"done"}
TASK_BLOCKED_STATUS = "blocked"


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _task_id_property(description: str = "Visible task ID, for example TASK-123.") -> dict[str, Any]:
    return {"type": "string", "description": description}


def _expected_version_property() -> dict[str, Any]:
    return {"type": "integer", "description": "Current visible task version used for conflict checks."}


def _create_tool() -> dict[str, Any]:
    return _tool(
        TASK_TOOL_CREATE,
        "Create a user-visible task in this chat. Private content will be staged for client encryption before durable persistence.",
        {
            "title": {"type": "string", "description": "Short user-visible task title."},
            "description": {"type": "string", "description": "Optional task details or acceptance criteria."},
            "assignee_type": {"type": "string", "enum": ["user", "ai"], "default": "user"},
            "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "blocked"], "default": "todo"},
        },
        ["title"],
    )


def _update_tool() -> dict[str, Any]:
    return _tool(
        TASK_TOOL_UPDATE,
        "Update a visible task title, description, status, or assignee without changing its primary chat.",
        {
            "task_id": _task_id_property(),
            "expected_version": _expected_version_property(),
            "title": {"type": "string", "description": "Replacement task title."},
            "description": {"type": "string", "description": "Replacement task details."},
            "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "blocked", "done"]},
            "assignee_type": {"type": "string", "enum": ["user", "ai"]},
        },
        ["task_id", "expected_version"],
    )


def _reorder_tool() -> dict[str, Any]:
    return _tool(
        TASK_TOOL_REORDER,
        "Reorder attached tasks in the current chat.",
        {
            "ordered_task_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Visible task IDs in their new order.",
            },
            "expected_versions": {
                "type": "object",
                "additionalProperties": {"type": "integer"},
                "description": "Map of each reordered task ID to its current visible version.",
            },
        },
        ["ordered_task_ids", "expected_versions"],
    )


def _block_tool() -> dict[str, Any]:
    return _tool(
        TASK_TOOL_BLOCK,
        "Block a visible task when progress requires user input or an external dependency.",
        {
            "task_id": _task_id_property(),
            "expected_version": _expected_version_property(),
            "blocked_reason_code": {
                "type": "string",
                "enum": ["needs_input", "external_dependency", "waiting_for_previous_task", "other"],
            },
        },
        ["task_id", "expected_version", "blocked_reason_code"],
    )


def _complete_tool() -> dict[str, Any]:
    return _tool(
        TASK_TOOL_COMPLETE,
        "Mark a visible task complete after the requested work is actually done.",
        {
            "task_id": _task_id_property(),
            "expected_version": _expected_version_property(),
            "completion_note": {"type": "string", "description": "Optional short completion summary."},
        },
        ["task_id", "expected_version"],
    )


def _unblock_tool() -> dict[str, Any]:
    return _tool(
        TASK_TOOL_UNBLOCK,
        "Unblock a visible blocked task after the blocker is resolved.",
        {
            "task_id": _task_id_property(),
            "expected_version": _expected_version_property(),
        },
        ["task_id", "expected_version"],
    )


def _move_tool() -> dict[str, Any]:
    return _tool(
        TASK_TOOL_MOVE,
        "Move a visible task to a different primary chat only when the user explicitly asks for the move.",
        {
            "task_id": _task_id_property(),
            "target_chat_id": {"type": "string", "description": "Destination chat ID that will become the task primary_chat_id."},
            "expected_version": _expected_version_property(),
        },
        ["task_id", "target_chat_id", "expected_version"],
    )


def build_task_runtime_tools(context: TaskToolContext) -> list[dict[str, Any]]:
    """Return task tools appropriate for the visible task context."""
    tools = [_create_tool()]
    if not context.attached_tasks:
        return tools

    attached_statuses = {str(task.get("status") or "") for task in context.attached_tasks}
    has_blocked = TASK_BLOCKED_STATUS in attached_statuses
    has_mutable = any(status not in TASK_TERMINAL_STATUSES for status in attached_statuses)

    if has_mutable:
        tools.extend([_update_tool(), _complete_tool(), _move_tool()])
    if any(status and status != TASK_BLOCKED_STATUS for status in attached_statuses):
        tools.append(_block_tool())
    if has_blocked:
        tools.append(_unblock_tool())

    return tools


def merge_task_runtime_tools(existing_tools: list[dict[str, Any]], task_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append task tools, replacing any same-named existing tool definitions."""
    task_names = {str(tool.get("function", {}).get("name")) for tool in task_tools}
    merged = [deepcopy(tool) for tool in existing_tools if str(tool.get("function", {}).get("name")) not in task_names]
    merged.extend(deepcopy(tool) for tool in task_tools)
    return merged
