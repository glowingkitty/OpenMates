
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

from pydantic import BaseModel, Field, field_validator, ConfigDict
from urllib.parse import quote
from server.api.models.software.software_get_one import Software


# GET /skill/{endpoint} (get a skill)

class Skill(BaseModel):
    """This is the model for a skill"""
    id: int = Field(..., description="ID of the skill")
    name: str = Field(..., description="name of the skill")
    description: str = Field(..., description="Description of the skill")
    slug: str = Field(..., description="Slug of the skill")
    requires_cloud_to_run: bool = Field(..., description="Indicates if the skill requires the cloud to run")
    is_llm_endpoint: bool = Field(..., description="Indicates if the skill is an LLM endpoint")
    is_llm_endpoint_and_supports_tool_selection: bool = Field(..., description="Indicates if the skill is an LLM endpoint and supports tool selection")
    icon_url: str = Field(..., description="URL of the icon of the skill")
    api_endpoint: str = Field(..., description="API endpoint of the skill")
    software: Software = Field(..., description="Software of the skill")

    model_config = ConfigDict(extra="forbid")

    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if quote(v) != v:
            raise ValueError('slug must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('slug must be all lowercase')
        return v

    @field_validator('icon_url')
    @classmethod
    def validate_icon_url(cls, v: str) -> str:
        pattern = r'^/v1/[a-z0-9-]+/uploads/[a-zA-Z0-9_.-]+\.(jpeg|jpg|png|gif)$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid icon URL format: {v}")
        return v

    @field_validator('api_endpoint')
    @classmethod
    def validate_api_endpoint(cls, v: str) -> str:
        pattern = r'^/v1/[a-z0-9-]+/skills/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid API endpoint format: {v}")
        return v


skills_get_one_output_example = {
    "id": 1,
    "name": "Ask",
    "description": "Ask a question to Claude from Anthropic.",
    "slug": "ask",
    "requires_cloud_to_run": False,
    "is_llm_endpoint": True,
    "is_llm_endpoint_and_supports_tool_selection": True,
    "icon_url": "/v1/ai-sales-team/uploads/ask_icon.jpeg",
    "api_endpoint": "/v1/ai-sales-team/skills/claude/ask",
    "software": {
        "id": 1,
        "name": "Claude",
        "slug": "claude",
        "icon_url": "/v1/ai-sales-team/uploads/claude_icon.jpeg",
    }
}