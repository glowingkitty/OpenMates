from server.memory.memory import save_task_to_memory
from server.api.endpoints.tasks.get_task import get as get_task
from server.cms.endpoints.tasks.update import update_task as update_task_in_cms
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from server.api.models.tasks.tasks_create import Task

import logging

# Set up logger
logger = logging.getLogger(__name__)


async def update(
    task_id: str,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    time_estimated_completion: Optional[float] = None,
    total_credits_cost_estimated: Optional[int] = None,
    total_credits_cost_real: Optional[int] = None,
    output: Optional[Dict[str, Any]] = None,
    api_endpoint: Optional[str] = None,
    error: Optional[str] = None
) -> Task:
    try:
        logger.debug(f"Updating task {task_id}")

        # Get the existing task
        task: Task = await get_task(task_id)

        current_time: datetime = datetime.now(timezone.utc)

        # Update the task
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = progress
        if time_estimated_completion is not None:
            task.time_estimated_completion = time_estimated_completion
        if total_credits_cost_estimated is not None:
            task.total_credits_cost_estimated = total_credits_cost_estimated
        if total_credits_cost_real is not None:
            task.total_credits_cost_real = total_credits_cost_real
        if output is not None:
            task.output = output
        if api_endpoint is not None:
            task.api_endpoint = api_endpoint
        if error is not None:
            task.error = error

        # Set the time started if it's not already set
        if not task.time_started:
            task.time_started = current_time.isoformat()

        # Set the time completion if the status is completed or failed
        if status in ['completed', 'failed']:
            task.time_completion = current_time.isoformat()
            if task.time_started:
                start_time = datetime.fromisoformat(task.time_started)
                task.execution_time_seconds = (current_time - start_time).total_seconds()

        # Save to memory
        save_task_to_memory(task_id=task_id, task_data=task)

        if status in ['in_progress', 'completed', 'failed']:
            await update_task_in_cms(task_id=task_id, task=task)

        return task

    except Exception:
        logger.exception(f"Error updating task {task_id}.")
        raise HTTPException(status_code=500, detail="An error occurred while updating the task.")