from fastapi import HTTPException
from celery.result import AsyncResult
from server.memory.memory import get_task_from_memory, save_task_to_memory
from server.cms.cms import make_strapi_request
from server.api.models.tasks.tasks_cancel import TasksCancelOutput
from server.api.models.tasks.tasks_create import Task

async def cancel(task_id: str) -> TasksCancelOutput:
    # Get the task from memory or Strapi
    task_data = get_task_from_memory(task_id)
    if task_data is None:
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

    task = Task(**task_data)

    # Cancel the Celery task
    celery_task = AsyncResult(task_id)
    if celery_task.state in ['PENDING', 'STARTED', 'RETRY']:
        celery_task.revoke(terminate=True)

    if task.status in ['scheduled', 'in_progress']:
        # Update task status to 'cancelled'
        task.status = 'cancelled'

        # Update in memory
        save_task_to_memory(task_id, task.model_dump())

        # Update in Strapi
        strapi_data = {k: v for k, v in task.model_dump().items() if k != 'progress'}
        strapi_data['task_id'] = strapi_data.pop('id')
        status_code, _ = await make_strapi_request(
            method='put',
            endpoint=f'tasks/{task_id}',
            data={'data': strapi_data}
        )
        if status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to update task status in Strapi")

        return TasksCancelOutput()
    elif task.status in ['completed', 'failed', 'cancelled']:
        raise HTTPException(status_code=400, detail=f"Cannot cancel task {task_id}. It has already {task.status}.")
    else:
        raise HTTPException(status_code=500, detail=f"Unknown task state for task {task_id}")