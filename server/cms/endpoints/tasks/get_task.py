import logging
from server.cms.cms import make_strapi_request
from server.api.models.tasks.tasks_create import Task
from fastapi import HTTPException

# Set up logger
logger = logging.getLogger(__name__)


async def get_task(task_id: str) -> Task:
    """
    Get a task by ID.
    """
    try:
        logger.debug(f"Getting task {task_id}")

        status_code, strapi_data = await make_strapi_request(
            method='get',
            endpoint='tasks',
            filters=[{'field': 'task_id', 'operator': '$eq', 'value': task_id}]
        )
        if status_code == 200 and strapi_data['data']:
            task_data = strapi_data['data'][0]['attributes']
            task_data['id'] = task_data.pop('task_id')
        else:
            raise HTTPException(status_code=404, detail="Task not found")

        return Task(**task_data)

    except Exception:
        logger.exception(f"Error getting task {task_id}.")
        raise HTTPException(status_code=500, detail="An error occurred while getting the task.")