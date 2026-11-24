# backend/core/api/app/services/task_sub_chat_link_service.py
#
# Task -> sub-chat links for Tasks that are still being persisted.
# The AI creates Tasks as staged jobs that a client encrypts and stores a few
# seconds later, so a sub-chat started for such a Task in the same turn finds
# no Task row yet. The link is then kept as a short-lived pending record and
# written as user_tasks.linked_sub_chat_id when the client stores the Task
# (feature.plans: one sub-chat per Task, linked back to its Task).
# Tests: backend/tests/test_sub_chat_orchestration.py.

from __future__ import annotations

import logging
from typing import Any

from backend.apps.ai.processing.task_tool_executor import TASK_TOOL_JOB_CACHE_PREFIX
from backend.core.api.app.services.directus.user_task_methods import hash_id
from backend.core.api.app.services.user_task_update_job_service import DEFAULT_TASK_UPDATE_JOB_TTL_SECONDS

logger = logging.getLogger(__name__)

PENDING_LINK_PREFIX = "user_task_pending_sub_chat_link:"


def _pending_key(user_id: str, task_id: str) -> str:
    return f"{PENDING_LINK_PREFIX}{hash_id(user_id)}:{task_id}"


async def has_staged_task_create(cache_service: Any, user_id: str, task_id: str) -> bool:
    """True when this user has a live, not yet finished create job for task_id."""
    owner_hash = hash_id(user_id)
    for key in await cache_service.get_keys_by_pattern(f"{TASK_TOOL_JOB_CACHE_PREFIX}*"):
        job = await cache_service.get(key)
        if (
            isinstance(job, dict)
            and job.get("owner_hash") == owner_hash
            and str(job.get("task_id") or "") == task_id
            and job.get("operation") == "create"
            and job.get("state") != "TERMINAL"
        ):
            return True
    return False


async def record_pending_link(
    cache_service: Any, *, user_id: str, task_id: str, plan_id: str, child_chat_id: str,
) -> None:
    stored = await cache_service.set(
        _pending_key(user_id, task_id),
        {"plan_id": plan_id, "child_chat_id": child_chat_id},
        ttl=DEFAULT_TASK_UPDATE_JOB_TTL_SECONDS,
    )
    if stored is False:
        raise RuntimeError("Failed to store pending Task sub-chat link")


async def apply_pending_link(
    cache_service: Any, directus_service: Any, *, user_id: str, task: dict[str, Any],
) -> str | None:
    """Write a pending link onto a stored Task; returns the linked child chat id."""
    task_id = str(task.get("task_id") or "")
    if not task_id:
        return None
    key = _pending_key(user_id, task_id)
    pending = await cache_service.get(key)
    if not isinstance(pending, dict) or not pending.get("child_chat_id"):
        return None
    if task.get("plan_id") != pending.get("plan_id"):
        await cache_service.delete(key)
        logger.warning("Pending Task sub-chat link refused: Task belongs to another Plan")
        return None
    child_chat_id = str(pending["child_chat_id"])
    await directus_service.update_item(
        "user_tasks", task["id"], {"linked_sub_chat_id": child_chat_id}, admin_required=True,
    )
    await cache_service.delete(key)
    return child_chat_id
