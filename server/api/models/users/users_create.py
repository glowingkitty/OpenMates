
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
from fastapi import UploadFile

# POST /users (create a new user)

class UsersCreateInput(BaseModel):
    """This is the model for the incoming parameters for POST /users"""
    name: str = Field(..., description="Name of the user", min_length=1, max_length=30)
    username: str = Field(..., description="Username of the user", min_length=1, max_length=30, unique=True)
    email: str = Field(..., description="Email of the user", min_length=1, max_length=50)
    password: str = Field(..., description="Password of the user", min_length=8, max_length=100)
    team_slug: str = Field(..., description="Slug (URL friendly name) of the team the user will join", min_length=1, max_length=30)
    profile_picture: UploadFile = Field(..., description="Profile picture of the user", max_length=1000000)

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
        if not re.match(r"^(?=.*[a-zA-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$", v):
            raise ValueError('password must be at least 8 characters long and contain at least one letter, one number and one special character')
        return v


users_create_input_example = {
    "name": "Sophia",
    "username": "sophia93",
    "email": "sophiiisthebest93@gmail.com",
    "password": "-Q9U72vax684LxfPH6AoGDZ",
    "team_slug": "ai-sales-team",
    "profile_picture_url": "/ai-sales-team/uploads/sophia_image.jpeg"
}



class UsersCreateOutput(BaseModel):
    """This is the model for a user that was just created successfully."""
    id: int = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")
    email: str = Field(..., description="Email address of the user")
    api_token: str = Field(..., description="API token of the user. This token is used for authenticating the user in the API. It will only be shown once, so make sure to store it securely.")
    teams: List[Team] = Field(..., description="Teams the user is a member of")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the user")
    balance_in_EUR: float = Field(..., description="Balance of the user in EUR. This balance can be used for using paid skills.")
    software_settings: dict = Field(..., description="Software settings, such as privacy settings, which cloud accounts are connected, default settings and more.")
    other_settings: dict = Field(..., description="Other settings, such as notification settings, etc.")
    projects: List[Project] = Field(..., description="Projects of the user")
    goals: List[dict] = Field(..., description="Goals and priorities of the user, related to projects, learning, finances etc.")
    todos: List[str] = Field(..., description="List of current To Do's of the user")
    recent_topics: List[str] = Field(..., description="Recent topics the user asked the AI team mates about.")


users_create_output_example = {
    "id": 2,
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
    "profile_picture_url": "/ai-sales-team/uploads/sophia_image.jpeg",
    "balance_in_EUR": 0.0,
    "software_settings": {},
    "other_settings": {},
    "projects": [],
    "goals": [],
    "todos": [],
    "recent_topics": []
}