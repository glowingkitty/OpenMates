
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

from server.api import *
################


from celery.result import AsyncResult
from fastapi import HTTPException
from server.api.models.tasks.tasks_cancel import TasksCancelOutput



async def cancel(task_id: str) -> TasksCancelOutput:
    task = AsyncResult(task_id)

    if task.state in ['PENDING', 'STARTED', 'RETRY']:
        task.revoke(terminate=True)
        return TasksCancelOutput()
    elif task.state in ['SUCCESS', 'FAILURE', 'REVOKED']:
        raise HTTPException(status_code=400, detail=f"Cannot cancel task {task_id}. It has already completed or been revoked.")
    else:
        raise HTTPException(status_code=500, detail=f"Unknown task state for task {task_id}")