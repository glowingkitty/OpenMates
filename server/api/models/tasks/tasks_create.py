
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

from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any, Literal


class Task(BaseModel):
    id: str = Field(..., description="ID of the task")
    team_slug: str = Field(..., description="Slug of the team that created the task")
    url: str = Field(..., description="URL of the task")
    api_endpoint: str = Field(..., description="API endpoint of the task")
    title: str = Field(..., description="Title of the task")
    status: Literal["scheduled", "in_progress", "completed", "failed", "cancelled"] = Field(..., description="Current status of the task")
    progress: float = Field(..., description="Progress of the task in percentage")
    time_scheduled_for: Optional[str] = Field(None, description="ISO 8601 datetime string of the scheduled start time")
    time_started: str = Field(..., description="ISO 8601 datetime string when the task started")
    time_estimated_completion: Optional[str] = Field(None, description="ISO 8601 datetime string of the estimated completion time")
    time_completion: Optional[str] = Field(None, description="ISO 8601 datetime string when the task completed")
    execution_time_seconds: Optional[float] = Field(None, description="Execution time of the task in seconds")
    total_credits_cost_estimated: Optional[int] = Field(None, description="Estimated total cost of the task in credits")
    total_credits_cost_real: Optional[int] = Field(None, description="Real total cost of the task in credits")
    output: Optional[Dict[str, Any]] = Field(None, description="Output of the task")

    @model_validator(mode='after')
    def validate_progress(self):
        if self.progress < 0 or self.progress > 100:
            raise ValueError("Progress must be between 0 and 100")
        return self

task_create_output_example = {
    "id": "153e0027-e34d-27i7-9a9c-14a6375b1c97",
    "team_slug": "openmatesdevs",
    "url": "/v1/openmatesdevs/tasks/153e0027-e34d-27i7-9a9c-14a6375b1c97",
    "api_endpoint": "/v1/openmatesdevs/skills/books/translate",
    "title": "Translate a book",
    "status": "scheduled",
    "progress": 0,
    "time_scheduled_for": None,
    "time_started": "2023-05-17T12:34:56.789Z",
    "time_estimated_completion": "2023-05-17T12:36:00.000Z",
    "time_completion": None,
    "execution_time_seconds": None,
    "total_credits_cost_estimated": 720,
    "total_credits_cost_real": None,
    "output": None
}