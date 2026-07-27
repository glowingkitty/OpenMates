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
    task_id = queue_result.get("task_id") or "the current task"
    state = queue_result.get("state")
    if state == "started_next_ai_task":
        return (
            f"Task queue continuation: continue working on task {task_id}. "
            "Use explicit task tools for task changes. Do not switch to plan steps while chat tasks remain."
        )
    return (
        f"Task queue continuation: task {task_id} is still active. "
        "Use explicit task tools to complete it, block it with a safe reason, or update it. "
        "Do not treat the chat as finished while workable tasks remain."
    )
