# backend/core/api/app/services/user_task_scheduler_service.py
#
# Pure scheduling logic for Tasks V1. Kept outside the Celery task package so
# focused tests can validate restart-safe due-task behavior without importing
# worker-only dependencies.

import logging
import time
from typing import Any, Awaitable, Callable

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods
from backend.core.api.app.services.user_task_admission_service import TaskAdmissionService

logger = logging.getLogger(__name__)


async def process_due_ai_tasks(
    task_methods: UserTaskMethods,
    *,
    now: int | None = None,
    limit: int = 100,
    on_admitted: Callable[[dict[str, Any], int], Awaitable[bool]] | None = None,
) -> dict[str, Any]:
    current_time = now or int(time.time())
    due_tasks = await task_methods.list_due_ai_tasks(current_time, limit=limit)
    waiting_tasks = await task_methods.list_waiting_ai_task_scopes_for_reconciliation(limit=limit)
    started = 0
    failed_task_ids: list[str] = []
    admission_service = TaskAdmissionService(task_methods, on_admitted=on_admitted)
    scopes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for task in [*due_tasks, *waiting_tasks]:
        team_hash = str(task.get("hashed_team_id") or "")
        user_hash = str(task.get("hashed_user_id") or "")
        scope = "team" if team_hash else "personal"
        owner_hash = team_hash or user_hash
        if not owner_hash:
            failed_task_ids.append(str(task.get("task_id") or task.get("id") or "unknown"))
            continue
        scopes.setdefault((scope, owner_hash), []).append(task)

    for (scope, owner_hash), scope_tasks in scopes.items():
        try:
            result = await admission_service.admit_hashed_scope(scope, owner_hash, now=current_time)
            started += len(result.get("admitted_task_ids", []))
        except Exception:
            failed_task_ids.extend(str(task.get("task_id") or task.get("id") or "unknown") for task in scope_tasks)
            logger.exception("Failed to reconcile due AI user Task scope %s", scope)

    return {"checked": len(due_tasks), "started": started, "failed_task_ids": failed_task_ids}
