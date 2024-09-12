
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

from pydantic import BaseModel, Field
from typing import List, Optional


class TasksCreateTaskOutput(BaseModel):
    task_url: str = Field(..., description="URL of the task")
    task_id: str = Field(..., description="ID of the task")


tasks_create_task_output_example = {
    "task_url": "/v1/openmatesdevs/tasks/153e0027-e34d-27i7-9a9c-14a6375b1c97",
    "task_id": "153e0027-e34d-27i7-9a9c-14a6375b1c97"
}