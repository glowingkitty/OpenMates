"""Retry signed archive migration eligibility without operator intervention.

The scan remains bounded and does not restore databases. Existing storage tasks
perform copies and per-unit transitions after the durable rollout gates advance.
"""

import asyncio

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from scripts.storage_rollout import automatic_tick


async def run_automatic_migration(task: BaseServiceTask) -> dict:
    try:
        await task.initialize_services()
        return await automatic_tick(task.directus_service, cache_service=task.cache_service)
    finally:
        await task.cleanup_services()


@app.task(name="storage.advance_automatic_migration", base=BaseServiceTask, bind=True)
def advance_automatic_migration(self: BaseServiceTask) -> dict:
    return asyncio.run(run_automatic_migration(self))
