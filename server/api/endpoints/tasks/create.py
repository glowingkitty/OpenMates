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

from server.memory.memory import save_task_to_memory
from server.cms.cms import make_strapi_request
from datetime import datetime, timezone
import uuid
from typing import Optional
from models.tasks.tasks_create import Task
from fastapi import HTTPException



async def create(
    team_slug: str,
    title: str,
    api_endpoint: str
) -> Task:
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
    status_code, json_response = await make_strapi_request(
        method='post',
        endpoint='tasks',
        data={'data': strapi_data}
    )
    if status_code == 200:
        # Save to Redis
        save_task_to_memory(task_id, task.model_dump())
        return task
    else:
        raise HTTPException(status_code=500, detail="Failed to create task in Strapi")