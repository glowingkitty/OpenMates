
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

from pydantic import BaseModel, Field, field_validator


# PATCH /api_token (Create a new API token)

class UsersCreateNewApiTokenInput(BaseModel):
    """This is the model for the incoming parameters for PATCH /{team_slug}/users/{username}/api_token"""
    username: str = Field(..., description="Your username")
    password: str = Field(..., description="Your password", min_length=8, max_length=100)

    @field_validator('password')
    @classmethod
    def password_must_be_strong(cls, v):
        if not re.match(r"^(?=.*[a-zA-Z])(?=.*\d)(?=.*[@$!%*?&#^+=()\[\]{}:;,.<>\/\\|~`]).{8,}$", v):
            raise ValueError('password must be at least 8 characters long and contain at least one letter, one number and one special character')
        return v


users_create_new_api_token_input_example = {
    "username": "sophiarocks21",
    "password": "-Q9U72vax684LxfPH6AoGDZ"
}



class UsersCreateNewApiTokenOutput(BaseModel):
    """This is the model for the outgoing parameters for PATCH /{team_slug}/users/{username}/api_token"""
    api_token: str = Field(..., description="New API token for the user")


users_create_new_api_token_output_example = {
    "api_token": "226af3d154b9eff1acb658fa3ba3973e856b06ac59b1"
}