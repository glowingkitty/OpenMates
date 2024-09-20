from server.memory.memory import save_task_to_memory
from server.cms.cms import make_strapi_request
from datetime import datetime, timezone
import uuid
from models.tasks.tasks_create import Task
from fastapi import HTTPException
from server.cms.endpoints.tasks.create import create as create_task_in_cms

import logging

# Set up logger
logger = logging.getLogger(__name__)


async def create(
    team_slug: str,
    title: str,
    api_endpoint: str
) -> Task:
    try:
        logger.debug(f"Creating task for team '{team_slug}' with title '{title}' and api endpoint '{api_endpoint}'")

        # Save to CMS
        task: Task = await create_task_in_cms(team_slug, title, api_endpoint)

        # Save to memory
        save_task_to_memory(task_id=task.id, task_data=task)

        logger.debug(f"Successfully created task {task.id} and saved to memory")

        return task

    except Exception:
        logger.exception("Unexpected error during task creation")
        raise HTTPException(status_code=500, detail="An error occurred while creating the task.")