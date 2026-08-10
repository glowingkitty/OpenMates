# backend/core/api/app/tasks/user_task_archive_task.py
#
# Daily Tasks V1 hot/cold retention job. Completed tasks older than the hot
# retention window are bundled, user-key encrypted, written to S3, then removed
# from Directus hot tables.
# Spec: docs/specs/tasks-v1/spec.yml.

from __future__ import annotations

import asyncio
import logging

from backend.core.api.app.services.user_task_archive_service import (
    DEFAULT_TASK_ARCHIVE_LIMIT,
    DEFAULT_TASK_ARCHIVE_RETENTION_DAYS,
    UserTaskArchiveService,
)
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


@app.task(name="user_tasks.archive_completed_tasks", base=BaseServiceTask, bind=True)
def archive_completed_user_tasks(
    self: BaseServiceTask,
    retention_days: int = DEFAULT_TASK_ARCHIVE_RETENTION_DAYS,
    limit: int = DEFAULT_TASK_ARCHIVE_LIMIT,
) -> dict:
    return asyncio.run(_archive_completed_user_tasks(self, retention_days=retention_days, limit=limit))


async def _archive_completed_user_tasks(task: BaseServiceTask, *, retention_days: int, limit: int) -> dict:
    try:
        await task.initialize_services()
        service = UserTaskArchiveService(
            directus_service=task.directus_service,
            s3_service=task.s3_service,
            encryption_service=task.encryption_service,
        )
        return await service.archive_completed_tasks(retention_days=retention_days, limit=limit)
    except Exception as exc:
        logger.error("Completed user task archive failed: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}
    finally:
        await task.cleanup_services()
