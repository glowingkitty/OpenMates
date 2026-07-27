# backend/apps/ai/processing/task_queue_continuation.py
#
# Lightweight task queue continuation helpers for the AI main processor. This
# module stays free of model/provider imports so backend tests can verify queue
# semantics without loading the full streaming pipeline. Durable task content
# remains client-encrypted; helpers only inspect safe task metadata.

from __future__ import annotations

from typing import Any

from backend.core.api.app.services.user_task_queue_service import UserTaskQueueService


TASK_QUEUE_GUARD_MAX_RETRIES = 2
TASK_QUEUE_MODEL_RETRY_STATES = {"started_next_ai_task", "active_ai_task"}
TASK_QUEUE_BLOCKING_STATES = {"blocked_by_human_task", "blocked_by_ai_task"}
TASK_QUEUE_CONTINUATION_SYSTEM_PREFIX = "Task queue continuation:"
PLAN_APP_SKILL_PREFIX = "plans-"
TASK_ACTIVITY_EVENT_WORDS = {"blocked", "completed", "continuing", "created", "moved", "started", "unblocked", "updated"}


def task_context_blocks_plan_creation(task_tool_context: Any) -> bool:
    """Return whether chat-attached task state should suppress plan creation tools."""
    if task_tool_context is None:
        return False
    visible_tasks = getattr(task_tool_context, "visible_tasks", None)
    if visible_tasks is None:
        visible_tasks = getattr(task_tool_context, "attached_tasks", []) or []
    for task in visible_tasks:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "todo")
        queue_state = str(task.get("queue_state") or "")
        if status not in {"done", "backlog"} and queue_state != "skipped":
            return True
    return False


def filter_plan_skills_for_task_queue(
    preselected_skills: set[str] | None,
    task_tool_context: Any,
) -> tuple[set[str] | None, set[str]]:
    """Remove plan app skills while chat tasks still need work."""
    if not preselected_skills or not task_context_blocks_plan_creation(task_tool_context):
        return preselected_skills, set()
    removed = {skill for skill in preselected_skills if skill.startswith(PLAN_APP_SKILL_PREFIX)}
    if not removed:
        return preselected_skills, set()
    return preselected_skills - removed, removed


def is_task_queue_continuation_system_content(content: Any) -> bool:
    return isinstance(content, str) and content.strip().startswith(TASK_QUEUE_CONTINUATION_SYSTEM_PREFIX)


def _looks_like_task_system_label(value: str) -> bool:
    if value.startswith("TASK-") and value[5:].isdigit():
        return True
    compact_uuid = value.replace("-", "")
    return len(value) == 36 and value.count("-") == 4 and len(compact_uuid) == 32 and all(
        char in "0123456789abcdefABCDEF" for char in compact_uuid
    )


def is_task_activity_system_content(content: Any) -> bool:
    if not isinstance(content, str):
        return False
    task_label, separator, rest = content.strip().partition(" ")
    if not separator or not _looks_like_task_system_label(task_label):
        return False
    event_word = rest.split(maxsplit=1)[0].strip(":").lower()
    return event_word in TASK_ACTIVITY_EVENT_WORDS


def task_queue_llm_history_role(role: Any, content: Any) -> Any:
    if role == "system" and (
        is_task_queue_continuation_system_content(content) or is_task_activity_system_content(content)
    ):
        return "user"
    return role


def task_queue_continuation_event_type(queue_result: dict[str, Any]) -> str:
    return "started" if queue_result.get("state") == "started_next_ai_task" else "continuing"


def build_task_queue_continuation_event(
    queue_result: dict[str, Any],
    *,
    message_id: str,
    now: int,
) -> dict[str, Any] | None:
    task_id = str(queue_result.get("task_id") or "")
    chat_id = str(queue_result.get("chat_id") or "")
    state = str(queue_result.get("state") or "")
    if not task_id or not chat_id or not state:
        return None
    event_id = f"task-queue-continuation-{message_id}-{task_id}-{state}"
    event = {
        "event_id": event_id,
        "chat_id": chat_id,
        "task_id": task_id,
        "event_type": task_queue_continuation_event_type(queue_result),
        "status": "in_progress",
        "created_at": now,
        "message_id": message_id,
    }
    short_id = queue_result.get("short_id")
    if short_id:
        event["short_id"] = short_id
    return event


async def evaluate_task_queue_post_turn(
    *,
    task_tool_context: Any,
    directus_service: Any,
    user_id: str,
    chat_id: str,
    now: int,
) -> dict[str, Any] | None:
    if task_tool_context is None or directus_service is None:
        return None
    task_methods = getattr(directus_service, "user_task", None)
    if task_methods is None:
        return None
    queue_result = await UserTaskQueueService(task_methods).evaluate_chat_queue(user_id, chat_id, now=now)
    state = str(queue_result.get("state") or "")
    if state in {"no_chat", "no_work"}:
        return None
    return {
        **queue_result,
        "requires_model_retry": state in TASK_QUEUE_MODEL_RETRY_STATES,
        "task_queue_blocks_plan": state in TASK_QUEUE_MODEL_RETRY_STATES or state in TASK_QUEUE_BLOCKING_STATES,
    }


def task_queue_post_turn_prompt(queue_result: dict[str, Any]) -> str:
    task_id = queue_result.get("short_id") or queue_result.get("task_id") or "the current task"
    state = queue_result.get("state")
    if state == "started_next_ai_task":
        return (
            f"{TASK_QUEUE_CONTINUATION_SYSTEM_PREFIX} continue working on task {task_id}. "
            "Use explicit task tools for task changes. Do not switch to plan steps while chat tasks remain."
        )
    return (
        f"{TASK_QUEUE_CONTINUATION_SYSTEM_PREFIX} task {task_id} is still active. "
        "Use explicit task tools to complete it, block it with a safe reason, or update it. "
        "Do not treat the chat as finished while workable tasks remain."
    )
