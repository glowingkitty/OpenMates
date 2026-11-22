"""Periodic reaper for hosted Project sandboxes (past their hard maximum, or without a cache record)."""

import asyncio

from backend.core.api.app.services.project_sandbox_service import reap_project_sandboxes
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


async def run_reaper(task: BaseServiceTask) -> dict:
    try:
        await task.initialize_services()
        return await reap_project_sandboxes(task.cache_service, secrets_manager=getattr(task, "secrets_manager", None))
    finally:
        await task.cleanup_services()


@app.task(name="project_sandbox.reap", base=BaseServiceTask, bind=True)
def reap(self: BaseServiceTask) -> dict:
    return asyncio.run(run_reaper(self))
