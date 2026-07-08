# backend/core/api/app/services/user_task_scheduler_service.py
#
# Pure scheduling logic for Tasks V1. Kept outside the Celery task package so
# focused tests can validate restart-safe due-task behavior without importing
# worker-only dependencies.

import logging
import time
from typing import Any

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods

logger = logging.getLogger(__name__)


async def process_due_ai_tasks(task_methods: UserTaskMethods, *, now: int | None = None, limit: int = 100) -> dict[str, Any]:
    current_time = now or int(time.time())
    due_tasks = await task_methods.list_due_ai_tasks(current_time, limit=limit)
    started = 0
    failed_task_ids: list[str] = []

    for task in due_tasks:
        try:
            updated = await task_methods.start_due_ai_task(task, current_time)
            if updated:
                started += 1
            else:
                failed_task_ids.append(str(task.get("task_id") or task.get("id") or "unknown"))
        except Exception:
            failed_task_ids.append(str(task.get("task_id") or task.get("id") or "unknown"))
            logger.exception("Failed to start due AI user task %s", task.get("task_id"))

    return {"checked": len(due_tasks), "started": started, "failed_task_ids": failed_task_ids}
