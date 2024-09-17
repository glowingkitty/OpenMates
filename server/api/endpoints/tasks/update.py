################
# Default Imports
################
import sys
import os
import re
from datetime import datetime, timedelta, timezone

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from server.memory.memory import save_task_to_memory
from server.api.endpoints.tasks.get_task import get as get_task
from server.cms.cms import make_strapi_request
import time
from typing import Optional, Dict, Any
from models.tasks.tasks_create import Task


async def update(
    task_id: str,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    time_estimated_completion: Optional[float] = None,
    total_credits_cost_estimated: Optional[int] = None,
    total_credits_cost_real: Optional[int] = None,
    output: Optional[Dict[str, Any]] = None,
    api_endpoint: Optional[str] = None
) -> Task:
    task_data = await get_task(task_id)

    current_time = datetime.now(timezone.utc)

    if status is not None:
        task_data.status = status
    if progress is not None:
        task_data.progress = progress
    if time_estimated_completion is not None:
        task_data.time_estimated_completion = (current_time + timedelta(seconds=time_estimated_completion)).isoformat()
    if total_credits_cost_estimated is not None:
        task_data.total_credits_cost_estimated = total_credits_cost_estimated
    if total_credits_cost_real is not None:
        task_data.total_credits_cost_real = total_credits_cost_real
    if output is not None:
        task_data.output = output
    if api_endpoint is not None:
        task_data.api_endpoint = api_endpoint

    if 'time_started' not in task_data:
        task_data.time_started = current_time.isoformat()

    if status in ['completed', 'failed']:
        task_data.time_completion = current_time.isoformat()
        if 'time_started' in task_data:
            start_time = datetime.fromisoformat(task_data.time_started)
            task_data.execution_time_seconds = (current_time - start_time).total_seconds()

    save_task_to_memory(task_id, task_data.model_dump())

    if status in ['in_progress', 'completed', 'failed']:
        # Step 1: Get the Strapi entry
        status_code, response = await make_strapi_request(
            method='get',
            endpoint='tasks',
            filters=[{'field': 'task_id', 'operator': '$eq', 'value': task_id}],
            pageSize=1  # We only need one result
        )

        if status_code == 200 and response.get('data'):
            strapi_id = response['data'][0]['id']

            # Step 2: Update the Strapi entry
            await make_strapi_request(
                method='put',
                endpoint=f'tasks/{strapi_id}',
                data={'data': task_data.model_dump()}
            )
        else:
            # Handle the case where the task is not found in Strapi
            print(f"Task with task_id {task_id} not found in Strapi")
            # You might want to log this or handle it differently

    return task_data