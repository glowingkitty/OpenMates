
################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################


from celery.result import AsyncResult
from fastapi import HTTPException
from server.api.models.tasks.tasks_get_task import TasksGetTaskOutput


async def get_task(task_id: str) -> TasksGetTaskOutput:
    task_result = AsyncResult(task_id)

    if task_result.ready():
        if task_result.successful():
            return TasksGetTaskOutput(
                status="completed",
                output=task_result.result
            )
        else:
            return TasksGetTaskOutput(
                status="failed",
                error=str(task_result.result)
            )
    elif task_result.state == 'PENDING':
        return TasksGetTaskOutput(status="pending")
    elif task_result.state == 'PROGRESS':
        return TasksGetTaskOutput(
            status="in_progress",
            progress=task_result.info
        )
    else:
        raise HTTPException(status_code=500, detail="Unknown task state")