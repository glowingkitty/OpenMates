
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
from typing import List
from server.api.models.skills.skills_old import Skill


# GET /mates/{mate_username} (get a mate)

class Mate(BaseModel):
    """This is the model for an AI team mate"""
    id: int = Field(..., description="ID of the AI team mate")
    name: str = Field(..., description="name of the AI team mate")
    username: str = Field(..., description="username of the AI team mate")
    description: str = Field(..., description="Description of the AI team mate")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the AI team mate")
    llm_endpoint: str = Field(..., description="The API endpoint of the Large Language Model (LLM) which is used by the AI team mate.")
    llm_endpoint_is_customized: bool = Field(..., description="Indicates if the Large Language Model provider is customized or the default one.")
    llm_model: str = Field(..., description="The LLM model which is used by the AI team mate.")
    llm_model_is_customized: bool = Field(..., description="Indicates if the specific Large Language Model is customized or the default one.")
    systemprompt: str = Field(..., description="Currently used system prompt of the AI team mate for the user who makes the request to the API, in the context of the selected team.")
    systemprompt_is_customized: bool = Field(..., description="Indicates if the system prompt is customized or the default one.")
    skills: List[Skill] = Field(..., description="Skills of the AI team mate")
    skills_are_customized: bool = Field(..., description="Indicates if the skills are customized or the default ones.")

    # TODO add endpoint to reset systemprompt and skills to default (for the user who makes the request, in the context of the selected team)

mates_get_one_output_example = {
    "id": 1,
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_picture_url": "/v1/ai-sales-team/uploads/sophia_image.jpeg",
    "llm_endpoint": "/v1/ai-sales-team/skills/chatgpt/ask",
    "llm_endpoint_is_customized": False,
    "llm_model":"gpt-4o",
    "llm_model_is_customized": False,
    "systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "systemprompt_is_customized": False,
    "skills": [
        {
            "id": 3,
            "name": "Write & test code",
            "description": "Writes and tests code based on the given requirements.",
            "software": {
                "id": 4,
                "name": "VS Code"
            },
            "api_endpoint": "/ai-sales-team/skills/vs_code/write_and_test_code"
        }
    ],
    "skills_are_customized": False
}