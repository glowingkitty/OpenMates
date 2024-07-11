
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
from typing import List, Optional
from server.api.models.projects.projects_get_one import Project
from server.api.models.teams.teams_get_one import Team



# POST /users (create a new user)

class UsersCreateInput(BaseModel):
    """This is the model for the incoming parameters for POST /users"""
    invite_code: str = Field(..., description="Invite code for creating a new user.", min_length=19, max_length=19)
    name: str = Field(..., description="Name of the user", min_length=1, max_length=30)
    username: str = Field(..., description="Username of the user", min_length=1, max_length=30, json_schema_extra={"unique": True})
    email: str = Field(..., description="Email of the user", min_length=1, max_length=50)
    password: str = Field(..., description="Password of the user", min_length=8, max_length=100)

    # TODO improve validation later using LLMs

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")

    @field_validator('username')
    @classmethod
    def username_must_be_url_compatible(cls, v):
        if quote(v) != v:
            raise ValueError('username must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('username must be all lowercase')
        return v

    @field_validator('email')
    @classmethod
    def email_must_be_valid(cls, v):
        if not re.match(r"[^@]+@[^@]+\.[^@]+", v):
            raise ValueError('email must be in the right format')
        return v

    @field_validator('password')
    @classmethod
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


users_create_output_example = {
    "id": 2,
    "name": "Sophia",
    "username": "sophia93",
    "email": "sophiiisthebest93@gmail.com",
    "api_token": "976be9fb2150404e9f7e3105a",
    "teams": [
        {
            "id": 1,
            "name": "AI Sales Team",
            "slug": "ai-sales-team"
        }
    ]
}