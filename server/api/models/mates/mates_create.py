
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

from pydantic import BaseModel, Field, validator
from typing import List, Optional
from server.api.models.skills.skills_old import Skill
from urllib.parse import quote


# POST /mates (create a new mate)

class MatesCreateInput(BaseModel):
    """This is the model for the incoming parameters for POST /mates"""
    name: str = Field(..., description="Name of the AI team mate", min_length=1, max_length=30)
    username: str = Field(..., description="Username of the AI team mate", min_length=1, max_length=30, unique=True)
    description: str = Field(..., description="Description of the AI team mate", min_length=1, max_length=150)
    profile_picture_url: str = Field(..., description="URL of the profile picture of the AI team mate", pattern=r".*\.(jpg|jpeg|png)$")
    default_systemprompt: str = Field(..., description="Default system prompt of the AI team mate", min_length=1)
    default_skills: List[int] = Field(None, description="Default list of skill IDs for the AI team mate")
    default_llm_endpoint: str = Field(..., description="Default LLM endpoint of the AI team mate")
    default_llm_model: str = Field(..., description="Default LLM model of the AI team mate")

    # TODO improve validation later using LLMs

    # prevent extra fields from being passed to API
    class Config:
        extra = "forbid"

    @validator('username')
    def validate_username(cls, v):
        if quote(v) != v:
            raise ValueError('username must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('username must be all lowercase')
        return v

    @validator('profile_picture_url')
    def validate_profile_picture_url(cls, v):
        pattern = r'^/v1/[a-z0-9-]+/uploads/[a-zA-Z0-9_.-]+\.(jpeg|jpg|png|gif)$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid profile picture URL format: {v}")
        return v

    @validator('default_llm_endpoint')
    def validate_llm_endpoint(cls, v):
        pattern = r'^/skills/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid LLM endpoint format: {v}")
        return v

    @validator('default_llm_model')
    def validate_llm_model(cls, v):
        pattern = r'^[a-z0-9_.-]+$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid LLM model format: {v}")
        return v


mates_create_input_example = {
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_picture_url": "/v1/ai-sales-team/uploads/sophia_image.jpeg",
    "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "default_skills": [3],
    "default_llm_endpoint": "/v1/ai-sales-team/skills/chatgpt/ask",
    "default_llm_model": "gpt-3.5-turbo"
}



class MatesCreateOutput(BaseModel):
    """This is the model for the outgoing response for POST /mates"""
    id: int = Field(..., description="ID of the AI team mate")
    name: str = Field(..., description="Name of the AI team mate")
    username: str = Field(..., description="Username of the AI team mate")
    description: str = Field(..., description="Description of the AI team mate")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the AI team mate")
    default_systemprompt: str = Field(..., description="Default system prompt of the AI team mate")
    default_skills: List[Skill] = Field(..., description="Default list of skills for the AI team mate")
    default_llm_endpoint: str = Field(..., description="Default LLM endpoint of the AI team mate")
    default_llm_model: str = Field(..., description="Default LLM model of the AI team mate")


mates_create_output_example = {
    "id": 2,
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_picture_url": "/v1/ai-sales-team/uploads/sophia_image.jpeg",
    "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "default_skills": [
        {
            "id": 3,
            "name": "Write & test code",
            "description": "Writes and tests code based on the given requirements.",
            "software": {
                "id": 4,
                "name": "VS Code"
            },
            "api_endpoint": "/v1/ai-sales-team/skills/vs_code/write_and_test_code"
        }
    ],
    "default_llm_endpoint": "/v1/ai-sales-team/skills/chatgpt/ask",
    "default_llm_model": "gpt-3.5-turbo"
}