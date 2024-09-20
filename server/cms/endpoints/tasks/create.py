import logging
from server.cms.cms import make_strapi_request
from server.api.endpoints.tasks.get_task import Task
from fastapi import HTTPException
from datetime import datetime, timezone
import uuid

# Set up logger
logger = logging.getLogger(__name__)


async def create(
    team_slug: str,
    title: str,
    api_endpoint: str
) -> Task:
    """
    Create a task.
    """
    try:
        logger.debug(f"Creating task for team '{team_slug}' with title '{title}' and api endpoint '{api_endpoint}'")

        task_id = str(uuid.uuid4())
        current_time = datetime.now(timezone.utc)

        task = Task(
            id=task_id,
            team_slug=team_slug,
            url=f"/v1/{team_slug}/tasks/{task_id}",
            api_endpoint=api_endpoint,
            title=title,
            status="scheduled",
            progress=0,
            time_started=current_time.isoformat()
        )

        # Save to Strapi
        strapi_data = task.model_dump()
        strapi_data['task_id'] = strapi_data.pop('id')

        status_code, strapi_data = await make_strapi_request(
            method='post',
            endpoint='tasks',
            data={'data': strapi_data}
        )
        if status_code == 200:
            logger.debug(f"Successfully created task {task.id} in Strapi")
            return task
        else:
            raise HTTPException(status_code=500, detail="Failed to create task in Strapi")

    except Exception:
        logger.exception(f"Error creating task {task_id}.")
        raise HTTPException(status_code=500, detail="An error occurred while creating the task.")