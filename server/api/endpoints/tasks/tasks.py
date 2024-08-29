################
# Default Imports
################
import sys
import os
import re
import asyncio

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from server.celery_app import celery
from server.api.endpoints.mates.ask_mate import ask_mate as ask_mate_processing
from server.api.models.tasks.tasks_get_task import TasksGetTaskOutput

@celery.task
def ask_mate_task(team_slug, message, mate_username, task_info):
    # Run the async function in an event loop
    loop = asyncio.get_event_loop()
    response = loop.run_until_complete(ask_mate_processing(team_slug, message, mate_username))
    add_to_log(f"Response: {response}")
    add_to_log(f"Response type: {type(response)}")
    response_dict = response.model_dump()
    # Return the task output
    return TasksGetTaskOutput(
        id="9999999",
        title="some title",
        status="completed",
        output=response_dict,
        error=None
    ).model_dump()