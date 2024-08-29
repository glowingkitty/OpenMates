
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

from pydantic import BaseModel, Field
from typing import List, Optional


class TasksGetTaskOutput(BaseModel):
    id: str = Field(..., description="ID of the task")
    title: str = Field(..., description="Title of the task")
    status: str = Field(..., description="Current status of the task (e.g., 'scheduled', 'in_progress', 'completed', 'failed')")
    scheduled_at: Optional[str] = Field(None, description="Scheduled date and time of the task in ISO 8601 format")
    priority: Optional[int] = Field(None, description="Priority of the task (e.g., 1 for high, 2 for medium, 3 for low)")
    assigned_to_user_id: Optional[int] = Field(None, description="ID of the user this task is assigned to")
    execution_time_seconds: Optional[float] = Field(None, description="Execution time of the task in seconds")
    output: Optional[dict] = Field(None, description="Output of the task")
    error: Optional[str] = Field(None, description="Error of the task")


tasks_get_task_output_example = {
    "id": 31412313,
    "title": "/openmatesdevs/mates/ask",
    "status": "completed",
    "scheduled_at": None,
    "priority": 1,
    "assigned_to_user_id": 392,
    "execution_time_seconds": 3.14,
    "output": {
        "answer": "The capital city of France is Paris and there are about 2.1 million people living there.",
        "request_cost_credits": 1
    },
    "error": None
}