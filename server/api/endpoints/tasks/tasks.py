################
# Default Imports
################
import sys
import os
import re
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from server.api.endpoints.tasks.celery import celery
from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing
from server.api.models.tasks.tasks_get_task import TasksGetTaskOutput

@celery.task(bind=True)
def ask_mate_task(self, team_slug, message, mate_username, task_info):
    # Add start time
    task_info['start_time'] = datetime.now()
    self.update_state(state='PROGRESS', meta={
        'meta': {
            'title': task_info['title'],
            'start_time': task_info['start_time']
        }
    })

    try:
        # Run the async function in an event loop
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(ask_mate_processing(
            team_slug=team_slug,
            message=message,
            mate_username=mate_username
        ))
        response = response.model_dump()

        # Add end time and title
        task_info['end_time'] = datetime.now()
        task_info['title'] = task_info.get('title', 'Unknown')
        execution_time = (task_info['end_time'] - task_info['start_time']).total_seconds()
        self.update_state(state='SUCCESS', meta={
            'title': task_info['title'],
            'start_time': task_info['start_time'],
            'end_time': task_info['end_time'],
            'execution_time': round(execution_time, 3),
            'output': response
        })
    except Exception as e:
        task_info['end_time'] = datetime.now()
        task_info['title'] = task_info.get('title', 'Unknown')
        execution_time = (task_info['end_time'] - task_info['start_time']).total_seconds()
        self.update_state(state='FAILURE', meta={
            'title': task_info['title'],
            'start_time': task_info['start_time'],
            'end_time': task_info['end_time'],
            'execution_time': round(execution_time, 3),
            'exc_type': type(e).__name__,
            'exc_message': traceback.format_exc().split('\n')
        })

        # TODO: cannot access meta data here
        # TODO: implement task data storage in strapi (might be also a workaround)
        raise