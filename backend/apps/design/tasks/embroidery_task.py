"""Celery entry point of design.embroidery on the shared media worker.

Every invocation is a registered generated-media batch: the parent
``app_skill_use`` embed is closed by ``run_generated_media_batch`` around the one
result child that ``run_embroidery`` publishes. The time limits cover the 180 s
sandbox run plus one model rework.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.apps.design.embroidery.pipeline import run_embroidery
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

TASK_NAME = "apps.design.tasks.skill_embroidery"


@app.task(
    bind=True,
    name=TASK_NAME,
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=420,
    time_limit=480,
)
def embroidery_task(self: BaseServiceTask, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the registered request batch; a payload without one is rejected explicitly."""
    from backend.shared.python_utils.generated_media_graph import run_generated_media_batch

    if not arguments.get("requests"):
        raise ValueError("design.embroidery requires a registered request batch")
    return asyncio.run(run_generated_media_batch(
        self, app_id=app_id, skill_id=skill_id, arguments=arguments, generate_one=run_embroidery,
    ))
