################
# Default Imports
################
import sys
import os
import re
import asyncio
from datetime import datetime, timezone

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from server.celery_app import celery
from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing
from server.api.models.tasks.tasks_get_task import TasksGetTaskOutput

@celery.task(bind=True)
def ask_mate_task(self, team_slug, message, mate_username, task_info):
    # Add start time
    task_info['start_time'] = datetime.now(timezone.utc)

    # Run the async function in an event loop
    loop = asyncio.get_event_loop()
    response = loop.run_until_complete(ask_mate_processing(
        team_slug=team_slug,
        message=message,
        mate_username=mate_username
    ))

    # Add end time and title
    task_info['end_time'] = datetime.now(timezone.utc)
    task_info['title'] = task_info.get('title', 'Unknown')

    return response.model_dump()