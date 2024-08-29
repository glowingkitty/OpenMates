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

from fastapi import HTTPException
from server.api.models.tasks.tasks_get_task import TasksGetTaskOutput
from server.celery_app import celery
from celery.result import AsyncResult

async def get_task(task_id: str) -> TasksGetTaskOutput:
    add_to_log(f"Getting task {task_id}")

    task_result = AsyncResult(task_id, app=celery)

    if not task_result:
        raise HTTPException(status_code=404, detail="Task not found")

    return task_result.result
