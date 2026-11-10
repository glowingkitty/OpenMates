"""Celery entry point of images.modify on the shared media worker (queue app_images).

Every invocation is a registered generated-media batch: the parent
``app_skill_use`` embed is closed by ``run_generated_media_batch`` around the one
result child that ``run_modify`` publishes. The limits cover three author and
review rounds per model plus model fallback, each sandbox run being stopped
after 60 seconds.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.apps.images.tasks.modify_pipeline import run_modify
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

TASK_NAME = "apps.images.tasks.skill_modify"


@app.task(
    bind=True,
    name=TASK_NAME,
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=660,
    time_limit=720,
)
def modify_image_task(self: BaseServiceTask, app_id: str, skill_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the registered request batch; a payload without one is rejected explicitly."""
    from backend.shared.python_utils.generated_media_graph import run_generated_media_batch

    if not arguments.get("requests"):
        raise ValueError("images.modify requires a registered request batch")
    return asyncio.run(run_generated_media_batch(
        self, app_id=app_id, skill_id=skill_id, arguments=arguments, generate_one=run_modify,
    ))
