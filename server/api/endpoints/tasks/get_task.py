from fastapi import HTTPException
from server.memory.memory import get_task_from_memory, save_task_to_memory
from server.cms.endpoints.tasks.get_task import get_task as get_task_from_cms
from server.api.models.tasks.tasks_create import Task
import logging

# Set up logger
logger = logging.getLogger(__name__)


async def get(task_id: str) -> Task:
    """
    Get a task by ID.
    """
    try:
        logger.debug(f"Getting task {task_id}")

        task: Task = get_task_from_memory(task_id)

        if task is None:
            task: Task = await get_task_from_cms(task_id)

            if task:
                # if task found in cms, save it to memory
                save_task_to_memory(task_id=task_id, task_data=task)

        logger.debug(f"Successfully loaded task {task_id}.")

        return task

    except Exception:
        logger.exception(f"Error getting task {task_id}.")
        raise HTTPException(status_code=500, detail="An error occurred while getting the task.")