
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
from typing import List, Optional


# GET /skill/{endpoint} (get a skill)

class SkillMini(BaseModel):
    """This is the minified model for a skill"""
    id: int = Field(..., description="ID of the skill")
    api_endpoint: str = Field(..., description="API endpoint of the skill")
    description: str = Field(..., description="Description of the skill")

    @field_validator('api_endpoint')
    @classmethod
    def validate_api_endpoint(cls, v: str) -> str:
        pattern = r'^/v1/[a-z0-9-]+/skills/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid API endpoint format: {v}")
        return v


class Skill(BaseModel):
    """This is the model for a skill"""
    id: int = Field(..., description="ID of the skill")
    api_endpoint: str = Field(..., description="API endpoint of the skill")
    name: str = Field(..., description="name of the skill")
    description: str = Field(..., description="Description of the skill")
    slug: str = Field(..., description="Slug of the skill")
    icon_url: str = Field(..., description="URL of the icon of the skill")
    software: Software = Field(..., description="Software of the skill")
    processing: List[str] = Field(..., description="List of environments where the skill can be processed: 'cloud' and/or 'local'")
    free: bool = Field(..., description="Indicates if the skill can be used free of charge")
    pricing: dict = Field(..., description="If not free to use: Pricing details of the skill")
    is_llm_endpoint: bool = Field(..., description="Indicates if the skill is an LLM endpoint")
    is_llm_endpoint_and_supports_tool_selection: bool = Field(..., description="Indicates if the skill is an LLM endpoint and supports tool selection")
    default_skill_settings: Optional[dict] = Field(..., description="Default settings for the skill")

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

    @field_validator('processing')
    @classmethod
    def validate_processing(cls, v: List[str]) -> List[str]:
        valid_values = ['cloud', 'local']
        for item in v:
            if item not in valid_values:
                raise ValueError(f"Invalid processing value. Each item must be one of: {', '.join(valid_values)}")
        if len(v) == 0:
            raise ValueError("Processing list must not be empty")
        if len(v) != len(set(v)):
            raise ValueError("Processing list must not contain duplicates")
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
    "api_endpoint": "/v1/ai-sales-team/skills/claude/ask",
    "name": "Ask",
    "description": "Ask a question to Claude from Anthropic.",
    "slug": "ask",
    "icon_url": "/v1/ai-sales-team/uploads/ask_icon.jpeg",
    "software": {
        "id": 1,
        "name": "Claude",
        "slug": "claude",
        "icon_url": "/v1/ai-sales-team/uploads/claude_icon.jpeg",
    },
    "processing": ["cloud"],
    "free": False,
    "pricing": {
        "claude-3.5-sonnet": {
            "price": 15.00,
            "currency": "USD",
            "per": "1 Million tokens input+output",
            "description": "1000 tokens equals arround 800-900 words. Example: 300 tokens input + 100 tokens output = 400 tokens = 0.006 USD."
        },
        "claude-3-haiku": {
            "price": 1.25,
            "currency": "USD",
            "per": "1 Million tokens input+output",
            "description": "1000 tokens equals arround 800-900 words. Example: 300 tokens input + 100 tokens output = 400 tokens = 0.0005 USD"
        }
    },
    "is_llm_endpoint": True,
    "is_llm_endpoint_and_supports_tool_selection": True,
    "default_skill_settings": {
        "default_model": "claude-3.5-sonnet"
    }
}