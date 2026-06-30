# backend/core/api/app/tasks/user_task_scheduler.py
#
# Restart-safe Tasks V1 scheduler. Due AI-assigned tasks are selected from
# durable Directus rows and atomically moved back into the normal AI execution
# queue state, so missed worker windows are recovered by the next sweep.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.core.api.app.services.user_task_scheduler_service import process_due_ai_tasks
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


@app.task(name="user_tasks.process_due_ai_tasks", base=BaseServiceTask, bind=True)
def process_due_ai_tasks_task(self: BaseServiceTask, now: int | None = None, limit: int = 100) -> dict[str, Any]:
    try:
        async def run() -> dict[str, Any]:
            await self.initialize_services()
            return await process_due_ai_tasks(self.directus_service.user_task, now=now, limit=limit)

        return asyncio.run(run())
    except Exception as exc:
        logger.error("Due AI user task scheduler failed: %s", exc, exc_info=True)
        raise
