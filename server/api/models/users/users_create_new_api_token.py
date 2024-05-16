
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


# PATCH /{team_slug}/users/{username}/api_token (Create a new API token)

class UsersCreateNewApiTokenInput(BaseModel):
    """This is the model for the incoming parameters for PATCH /{team_slug}/users/{username}/api_token"""
    email: str = Field(..., description="Email of the user", min_length=1, max_length=50)
    password: str = Field(..., description="Password of the user", min_length=8, max_length=100)

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


users_create_new_api_token_input_example = {
    "email": "sophiiisthebest93@gmail.com",
    "password": "-Q9U72vax684LxfPH6AoGDZ"
}



class UsersCreateNewApiTokenOutput(BaseModel):
    """This is the model for the outgoing parameters for PATCH /{team_slug}/users/{username}/api_token"""
    api_token: str = Field(..., description="New API token for the user")


users_create_new_api_token_output_example = {
    "api_token": "0jasdjj2i2ik83hdhD98kd"
}