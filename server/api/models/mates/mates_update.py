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
from urllib.parse import quote


# PATCH /mates/{mate_username} (update a mate)

class MatesUpdateInput(BaseModel):
    """This is the model for the incoming parameters for PATCH /mates/{mate_username}"""
    name: str = Field(None, description="Name of the AI team mate")
    username: str = Field(None, description="Username of the AI team mate", min_length=1, max_length=30, unique=True)
    description: str = Field(None, description="Description of the AI team mate", min_length=1, max_length=150)
    profile_picture_url: str = Field(None, description="URL of the profile picture of the AI team mate", pattern=r".*\.(jpg|jpeg|png)$")
    default_systemprompt: str = Field(None, description="Default system prompt of the AI team mate", min_length=1)
    default_skills: List[int] = Field(None, description="Default list of skill IDs for the AI team mate")
    systemprompt: str = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nCustom system prompt of the AI team mate.", min_length=1)
    skills: List[int] = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nCustom list of skills (IDs) AI team mate is allowed to use.")
    allowed_to_access_user_name: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your name.")
    allowed_to_access_user_username: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your username.")
    allowed_to_access_user_projects: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your projects.")
    allowed_to_access_user_goals: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your goals.")
    allowed_to_access_user_todos: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your To Do's.")
    allowed_to_access_user_recent_topics: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access the recent topics you asked AI team mates about.")

    class Config:
        extra = "forbid"

    @validator('username')
    def username_must_be_url_compatible(cls, v):
        if quote(v) != v:
            raise ValueError('username must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('username must be all lowercase')
        return v

    @validator('profile_picture_url')
    def profile_picture_url_must_in_right_format(cls, v):
        if not re.match(r"/[a-z0-9_]+/uploads/.+\.(jpg|jpeg|png)$", v):
            raise ValueError('profile picture URL must be in the right format: /{team_slug}/uploads/{filename}')
        return v

mates_update_input_example = {
    "description": "A software development expert, who can help you with all your coding needs."
}


class MateUpdateOutput(BaseModel):
    """This is the model for the outgoing response for POST /mates"""
    id: int = Field(..., description="ID of the AI team mate")
    username: str = Field(..., description="Username of the AI team mate")
    updated_fields: List[dict] = Field(..., description="Dict with all updated fields")

mates_update_output_example = {
    "id": 1,
    "username": "sophia",
    "updated_fields": [
        {"description": "A software development expert, who can help you with all your coding needs."}
    ]
}