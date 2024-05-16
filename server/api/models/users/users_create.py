
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
from urllib.parse import quote
from typing import List, Optional
from server.api.models.projects.projects_get_one import Project
from server.api.models.teams.teams_get_one import Team


class DefaultPrivacySettings(BaseModel):
    allowed_to_access_name: bool = Field(..., description="Whether the AI team mates are by default allowed to access the name of the user.")
    allowed_to_access_username: bool = Field(..., description="Whether the AI team mates are by default allowed to access the username of the user.")
    allowed_to_access_projects: bool = Field(..., description="Whether the AI team mates are by default allowed to access the projects of the user.")
    allowed_to_access_goals: bool = Field(..., description="Whether the AI team mates are by default allowed to access the goals of the user.")
    allowed_to_access_todos: bool = Field(..., description="Whether the AI team mates are by default allowed to access the To Do's of the user.")
    allowed_to_access_recent_topics: bool = Field(..., description="Whether the AI team mates are by default allowed to access the recent topics the user asked AI team mates about.")

class Skill(BaseModel):
    id: int = Field(..., description="ID of the skill")
    name: str = Field(..., description="Name of the skill")
    software: str = Field(..., description="Software related to the skill")
    api_endpoint: str = Field(..., description="API endpoint for the skill")

class MateConfig(BaseModel):
    mate_username: str = Field(..., description="Username of the AI team mate this config is for.")
    team_slug: str = Field(..., description="Slug of the team this config is for.")
    systemprompt: str = Field(..., description="Custom system prompt for the AI team mate.")
    skills: list[Skill] = Field(..., description="Custom selection of skills the AI team mate can use")
    allowed_to_access_user_name: bool = Field(..., description="Whether the AI team mate is allowed to access the name of the user.")
    allowed_to_access_user_username: bool = Field(..., description="Whether the AI team mate is allowed to access the username of the user.")
    allowed_to_access_user_projects: bool = Field(..., description="Whether the AI team mate is allowed to access the projects of the user.")
    allowed_to_access_user_goals: bool = Field(..., description="Whether the AI team mate is allowed to access the goals of the user.")
    allowed_to_access_user_todos: bool = Field(..., description="Whether the AI team mate is allowed to access the To Do's of the user.")
    allowed_to_access_user_recent_topics: bool = Field(..., description="Whether the AI team mate is allowed to access the recent topics the user asked AI team mates about.")


# POST /users (create a new user)

class UsersCreateInput(BaseModel):
    """This is the model for the incoming parameters for POST /users"""
    invite_code: str = Field(..., description="Invite code for creating a new user.", min_length=19, max_length=19)
    name: str = Field(..., description="Name of the user", min_length=1, max_length=30)
    username: str = Field(..., description="Username of the user", min_length=1, max_length=30, unique=True)
    email: str = Field(..., description="Email of the user", min_length=1, max_length=50)
    password: str = Field(..., description="Password of the user", min_length=8, max_length=100)
    mates_default_privacy_settings: DefaultPrivacySettings = Field(None, description="The default privacy settings for the AI team mates, which the user communicates with.")

    # TODO improve validation later using LLMs

    # prevent extra fields from being passed to API
    class Config:
        extra = "forbid"

    @validator('username')
    def username_must_be_url_compatible(cls, v):
        if quote(v) != v:
            raise ValueError('username must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('username must be all lowercase')
        return v

    @validator('email')
    def email_must_be_valid(cls, v):
        if not re.match(r"[^@]+@[^@]+\.[^@]+", v):
            raise ValueError('email must be in the right format')
        return v

    @validator('password')
    def password_must_be_strong(cls, v):
        if not re.match(r"^(?=.*[a-zA-Z])(?=.*\d)(?=.*[@$!%*?&#^+=()\[\]{}:;,.<>\/\\|~`]).{8,}$", v):
            raise ValueError('password must be at least 8 characters long and contain at least one letter, one number and one special character')
        return v


users_create_input_example = {
    "invite_code": "XJDO-DJDJ-B3A3-3JJD",
    "name": "Sophia",
    "username": "sophia93",
    "email": "sophiiisthebest93@gmail.com",
    "password": "-Q9U72vax684LxfPH6AoGDZ"
}



class UsersCreateOutput(BaseModel):
    """This is the model for a user that was just created successfully."""
    id: int = Field(..., description="ID of the user")
    name: str = Field(..., description="Name of the user")
    username: str = Field(..., description="Username of the user")
    email: str = Field(..., description="Email address of the user")
    api_token: str = Field(..., description="API token of the user. This token is used for authenticating the user in the API. It will only be shown once, so make sure to store it securely.")
    teams: List[Team] = Field(..., description="Teams the user is a member of")
    balance_in_EUR: float = Field(..., description="Balance of the user in EUR. This balance can be used for using paid skills.")
    mates_default_privacy_settings: DefaultPrivacySettings = Field(..., description="The default privacy settings for the AI team mates, which the user communicates with.")
    mates_custom_settings: list[MateConfig] = Field(..., description="Custom settings for the AI team mates, such as system prompt, privacy settings, etc.")
    software_settings: dict = Field(..., description="Software settings, such as privacy settings, which cloud accounts are connected, default settings and more.")
    other_settings: dict = Field(..., description="Other settings, such as notification settings, etc.")
    projects: List[Project] = Field(..., description="Projects of the user")
    goals: List[dict] = Field(..., description="Goals and priorities of the user, related to projects, learning, finances etc.")
    todos: List[str] = Field(..., description="List of current To Do's of the user")
    recent_topics: List[str] = Field(..., description="Recent topics the user asked the AI team mates about.")


users_create_output_example = {
    "id": 2,
    "name": "Sophia",
    "username": "sophia93",
    "email": "sophiiisthebest93@gmail.com",
    "api_token": "0jasdjj2i2ik83hdhD98kd",
    "teams": [
        {
            "id": 1,
            "name": "AI Sales Team",
            "slug": "ai-sales-team"
        }
    ],
    "balance_in_EUR": 0.0,
    "mates_default_privacy_settings":{
        "allowed_to_access_name": True,
        "allowed_to_access_username": True,
        "allowed_to_access_projects": True,
        "allowed_to_access_goals": True,
        "allowed_to_access_todos": True,
        "allowed_to_access_recent_topics": True
    },
    "mates_custom_settings":{},
    "software_settings": {},
    "other_settings": {},
    "projects": [],
    "goals": [],
    "todos": [],
    "recent_topics": []
}