# backend/apps/ai/processing/task_tool_context.py
#
# Tasks V1 main-processor context resolution. This module keeps task mention
# lookup and chat-attached task discovery separate from the large main processor
# so backend tests can verify ownership and primary-chat semantics without a
# model call or live Directus instance.

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

TASK_MENTION_PATTERN = re.compile(r"(?<![\w-])@?(?P<task_id>TASK-[A-Za-z0-9_-]+)\b")
DEFAULT_ATTACHED_TASK_LIMIT = 50


@dataclass(slots=True)
class TaskToolContext:
    """Task context available to main-processing task tools for one chat turn."""

    user_id: str
    chat_id: str
    attached_tasks: list[dict[str, Any]] = field(default_factory=list)
    referenced_tasks: list[dict[str, Any]] = field(default_factory=list)
    missing_reference_ids: list[str] = field(default_factory=list)
    client_persisted_task_ids: set[str] = field(default_factory=set)

    @property
    def visible_tasks(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        visible: list[dict[str, Any]] = []
        for task in [*self.attached_tasks, *self.referenced_tasks]:
            task_id = str(task.get("task_id") or "")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            visible.append(task)
        return visible


def extract_task_mentions(message_text: str | None) -> list[str]:
    """Return ordered, de-duplicated task short IDs mentioned as @TASK-123."""
    if not message_text:
        return []

    mentions: list[str] = []
    seen: set[str] = set()
    for match in TASK_MENTION_PATTERN.finditer(message_text):
        task_id = match.group("task_id")
        if task_id in seen:
            continue
        seen.add(task_id)
        mentions.append(task_id)
    return mentions


async def resolve_task_tool_context(
    *,
    task_methods: Any,
    user_id: str,
    chat_id: str,
    message_text: str | None,
    attached_limit: int = DEFAULT_ATTACHED_TASK_LIMIT,
) -> TaskToolContext:
    """Resolve chat-attached tasks and explicitly mentioned owned tasks."""
    attached_tasks = await task_methods.list_tasks(user_id, chat_id=chat_id, limit=attached_limit)
    if not isinstance(attached_tasks, list):
        attached_tasks = []

    attached_ids = {
        str(identifier)
        for task in attached_tasks
        for identifier in (task.get("task_id"), task.get("short_id"))
        if identifier
    }
    referenced_tasks: list[dict[str, Any]] = []
    missing_reference_ids: list[str] = []

    for task_id in extract_task_mentions(message_text):
        if task_id in attached_ids:
            continue
        get_by_short_id = getattr(task_methods, "get_task_by_short_id", None)
        task = await get_by_short_id(task_id, user_id) if get_by_short_id else None
        if not task:
            task = await task_methods.get_task(task_id, user_id)
        if isinstance(task, dict) and task.get("task_id"):
            if task.get("primary_chat_id") == chat_id:
                attached_tasks.append(task)
                attached_ids.update(str(identifier) for identifier in (task.get("task_id"), task.get("short_id")) if identifier)
            else:
                referenced_tasks.append(task)
        else:
            missing_reference_ids.append(task_id)
            logger.info("Task mention was not visible to user; mention ignored")

    return TaskToolContext(
        user_id=user_id,
        chat_id=chat_id,
        attached_tasks=attached_tasks,
        referenced_tasks=referenced_tasks,
        missing_reference_ids=missing_reference_ids,
    )


def build_task_context_prompt(context: TaskToolContext) -> str:
    """Build minimal safe task context for the model without changing ownership."""
    if not context.visible_tasks:
        return ""

    lines = ["### Visible Tasks", "Use task tools for task changes; do not claim a task changed unless a tool call succeeds."]
    for task in context.visible_tasks:
        task_id = task.get("short_id") or task.get("task_id")
        status = task.get("status") or "unknown"
        primary_chat_id = task.get("primary_chat_id") or "none"
        version = task.get("version")
        scope = "attached" if primary_chat_id == context.chat_id else "referenced"
        lines.append(f"- {task_id}: status={status}, version={version}, scope={scope}, primary_chat_id={primary_chat_id}")
    lines.append("Mentioned referenced tasks are context only. Use task_move only when the user explicitly asks to move a task.")
    return "\n".join(lines)
