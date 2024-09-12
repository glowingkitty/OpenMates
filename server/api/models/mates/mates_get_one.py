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

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List
from urllib.parse import quote
from typing import Optional
from server.api.models.skills.skills_get_one import SkillMini
from server.api.models.mates.validators import validate_llm_model, validate_llm_endpoint

# GET /mates/{mate_username} (get a mate)

class Mate(BaseModel):
    """This is the model for an AI team mate"""
    id: int = Field(..., description="ID of the AI team mate")
    name: str = Field(..., description="name of the AI team mate")
    username: str = Field(..., description="username of the AI team mate")
    description: str = Field(..., description="Description of the AI team mate")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the AI team mate")
    llm_endpoint: str = Field(..., description="The API endpoint of the Large Language Model (LLM) which is used by the AI team mate.")
    llm_model: str = Field(..., description="The LLM model which is used by the AI team mate.")
    systemprompt: str = Field(..., description="Currently used system prompt of the AI team mate for the user who makes the request to the API, in the context of the selected team.")
    skills: List[SkillMini] = Field(..., description="Skills of the AI team mate")
    allowed_to_access_user_data: dict = Field(..., description="Overview of which user data the AI team mate is allowed to access for the user who makes the request to the API, in the context of the selected team.")
    custom_config_id: Optional[int] = Field(..., description="If you customized your AI team mate for the requested team: ID of the config.")
    llm_endpoint_is_customized: bool = Field(..., description="Indicates if the Large Language Model provider is customized or the default one.")
    llm_model_is_customized: bool = Field(..., description="Indicates if the specific Large Language Model is customized or the default one.")
    systemprompt_is_customized: bool = Field(..., description="Indicates if the system prompt is customized or the default one.")
    skills_are_customized: bool = Field(..., description="Indicates if the skills are customized or the default ones.")

    model_config = ConfigDict(extra="forbid")

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        if quote(v) != v:
            raise ValueError('username must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('username must be all lowercase')
        return v

    @field_validator('profile_picture_url')
    @classmethod
    def validate_profile_picture_url(cls, v: str) -> str:
        pattern = r'^/v1/[a-z0-9-]+/uploads/[a-zA-Z0-9_.-]+\.(jpeg|jpg|png|gif)$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid profile picture URL format: {v}")
        return v

    @field_validator('llm_endpoint')
    @classmethod
    def validate_llm_endpoint(cls, v: str) -> str:
        return validate_llm_endpoint(v)

    @field_validator('llm_model')
    @classmethod
    def validate_llm_model(cls, v: str, values) -> str:
        endpoint = values.data.get('llm_endpoint')
        return validate_llm_model(v, endpoint)

    @field_validator('allowed_to_access_user_data')
    @classmethod
    def validate_allowed_to_access_user_data(cls, v: dict) -> dict:
        fields = ["name", "username", "projects", "goals", "todos", "recent_topics", "recent_emails", "calendar", "likes", "dislikes"]
        for field in fields:
            if field not in v:
                raise ValueError(f"allowed_to_access_user_data must contain all fields: {fields}")
        return v

    # TODO add endpoint to reset systemprompt and skills to default (for the user who makes the request, in the context of the selected team)

mates_get_one_output_example = {
    "id": 1,
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_picture_url": "/v1/ai-sales-team/uploads/sophia_image.jpeg",
    "llm_endpoint": "/v1/ai-sales-team/skills/chatgpt/ask",
    "llm_model":"gpt-4o",
    "systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "skills": [
        {
            "id": 3,
            "api_endpoint": "/v1/ai-sales-team/skills/vs_code/write_and_test_code",
            "description": "Writes and tests code based on the given requirements."
        }
    ],
    "allowed_to_access_user_data": {
        "name": True,
        "username": True,
        "projects": True,
        "goals": True,
        "todos": True,
        "recent_topics": True,
        "recent_emails": True,
        "calendar": True,
        "likes": True,
        "dislikes": True
    },
    "custom_config_id": 2,
    "llm_endpoint_is_customized": True,
    "llm_model_is_customized": True,
    "systemprompt_is_customized": True,
    "skills_are_customized": True
}