################
# Default Imports
################
import sys
import os
import re
from datetime import datetime

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from fastapi import HTTPException
from server.api.models.tasks.tasks_get_task import TasksGetTaskOutput
from server.api.endpoints.tasks.celery import celery
from celery.result import AsyncResult

async def get_task(task_id: str) -> TasksGetTaskOutput:
    add_to_log(f"Getting task {task_id}")

    task_result = AsyncResult(task_id, app=celery)

    if not task_result:
        raise HTTPException(status_code=404, detail="Task not found")

    # handle error
    if task_result.state == 'FAILURE':
        return TasksGetTaskOutput(
            id=task_id,
            title='Unknown',
            status='failed',
            error="An error occurred while processing the task"
        )

    return TasksGetTaskOutput(
        id=task_id,
        title=task_result.result.get('title', 'Unknown'),
        status=task_result.state.lower(),
        output=task_result.result.get('output', {}),
        execution_time_seconds=task_result.result.get('execution_time', 0)
    )

