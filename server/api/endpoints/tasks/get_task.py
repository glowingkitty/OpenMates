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

from fastapi import HTTPException
from server.memory.memory import get_task_from_memory
from server.cms.cms import make_strapi_request
from server.api.models.tasks.tasks_create import Task

async def get(task_id: str) -> Task:
    task_data = get_task_from_memory(task_id)
    if task_data is None:
        add_to_log("Loading task from disk")
        # If not in Redis, fetch from Strapi
        status_code, strapi_data = await make_strapi_request(
            method='get',
            endpoint='tasks',
            filters=[{'field': 'task_id', 'operator': 'eq', 'value': task_id}]
        )
        if status_code == 200 and strapi_data['data']:
            task_data = strapi_data['data'][0]['attributes']
            task_data['id'] = task_data.pop('task_id')
        else:
            raise HTTPException(status_code=404, detail="Task not found")

    return Task(**task_data)