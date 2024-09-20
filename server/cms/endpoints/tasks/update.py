import logging
import asyncio
from server.cms.cms import make_strapi_request
from server.api.endpoints.tasks.get_task import Task
from fastapi import HTTPException

# Set up logger
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

async def update_task(task_id: str, task: Task) -> bool:
    """
    Update a task by ID.
    """
    try:
        logger.debug(f"Updating task {task_id}")

        # Step 1: Get the Strapi entry
        for attempt in range(MAX_RETRIES):
            status_code, response = await make_strapi_request(
                method='get',
                endpoint='tasks',
                filters=[{'field': 'task_id', 'operator': '$eq', 'value': task_id}],
                pageSize=1
            )
            if status_code == 200 and response.get('data'):
                strapi_id = response['data'][0]['id']
                break
            elif attempt < MAX_RETRIES - 1:
                logger.warning(f"Attempt {attempt + 1} failed to get task {task_id}. Retrying in {RETRY_DELAY} seconds...")
                await asyncio.sleep(RETRY_DELAY)
            else:
                logger.error(f"Task with task_id {task_id} not found in Strapi after {MAX_RETRIES} attempts")
                raise HTTPException(status_code=500, detail="An error occurred while updating the task.")

        # Step 2: Update the Strapi entry
        for attempt in range(MAX_RETRIES):
            status_code, response = await make_strapi_request(
                method='put',
                endpoint=f'tasks/{strapi_id}',
                data={'data': task.model_dump()}
            )
            if status_code == 200:
                logger.debug(f"Successfully updated task {task_id} in Strapi")
                return True
            elif attempt < MAX_RETRIES - 1:
                logger.warning(f"Attempt {attempt + 1} failed to update task {task_id}. Retrying in {RETRY_DELAY} seconds...")
                await asyncio.sleep(RETRY_DELAY)
            else:
                logger.exception(f"Failed to update task {task_id} in Strapi after {MAX_RETRIES} attempts")
                raise HTTPException(status_code=500, detail="An error occurred while updating the task.")

    except Exception:
        logger.exception(f"Error updating task {task_id}.")
        raise HTTPException(status_code=500, detail="An error occurred while updating the task.")