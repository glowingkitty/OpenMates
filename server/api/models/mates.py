
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
from server.api.models.metadata import MetaData
from server.api.models.skills import Skill
from urllib.parse import quote

##################################
######### Mates ##################
##################################

## Base models

class Mate(BaseModel):
    """This is the model for an AI team mate"""
    id: int = Field(..., description="ID of the AI team mate")
    name: str = Field(..., description="name of the AI team mate")
    username: str = Field(..., description="username of the AI team mate")
    description: str = Field(..., description="Description of the AI team mate")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the AI team mate")
    systemprompt: str = Field(..., description="Currently used system prompt of the AI team mate for the user who makes the request to the API, in the context of the selected team.")
    systemprompt_is_customized: bool = Field(..., description="Indicates if the system prompt is customized or the default one.")
    skills: List[Skill] = Field(..., description="Skills of the AI team mate")
    skills_are_customized: bool = Field(..., description="Indicates if the skills are customized or the default ones.")



## Endpoint models

# POST /mates/ask (Send a message to an AI team mate and you receive the response)

class MatesAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /mates/ask"""
    mate_username: str = Field(..., description="Username of the AI team mate who the message is for.")
    message: str = Field(..., description="Message to send to the AI team mate.")
    
mates_ask_input_example = {
    "mate_username": "sophia",
    "message": "Write me some python code that prints 'Hello, AI!'"
}


class MatesAskOutput(BaseModel):
    """This is the model for outgoing message for POST /mates/ask"""
    message: str = Field(..., description="The content of the message")
    tokens_used_input: int = Field(..., description="The number of tokens used to process the input message")
    tokens_used_output: int = Field(..., description="The number of tokens used to generate the output message")
    total_costs_eur: float = Field(..., description="The total cost of processing the message, in EUR")
    
mates_ask_output_example = {
    "message": "Of course I can help you with that! Here is the python code you requested: print('Hello, AI!')\n\nI hope this helps you out. If you have any more questions, feel free to ask!",
    "tokens_used_input": 20,
    "tokens_used_output": 46,
    "total_costs_eur": 0.003
}


# GET /mates (get all mates)

class MateForGetAll(BaseModel):
    """This is the model for a single AI team mate, for the endpoint GET /mates"""
    id: int = Field(..., description="ID of the AI team mate")
    name: str = Field(..., description="name of the AI team mate")
    username: str = Field(..., description="username of the AI team mate")
    description: str = Field(..., description="Description of the AI team mate")
    profile_picture_url: str = Field(..., description="URL of the profile picture of the AI team mate")

class MatesGetAllOutput(BaseModel):
    data: List[MateForGetAll] = Field(..., description="List of all AI team mates for the team")
    meta: MetaData = Field(..., description="Metadata for the response")


mates_get_all_output_example = {
    "data": [
        {
            "id": 1,
            "name": "Burton",
            "username": "burton",
            "description": "Business development expert",
            "profile_picture_url": "/{team_url}/uploads/burton_image.jpeg"
        },
        {
            "id": 2,
            "name": "Sophia",
            "username": "sophia",
            "description": "Software development expert",
            "profile_picture_url": "/{team_url}/uploads/sophia_image.jpeg"
        }
    ],
    "meta": {
        "pagination": {
            "page": 1,
            "pageSize": 25,
            "pageCount": 1,
            "total": 1
        }
    }
}

# GET /mates/{mate_username} (get a mate)

class MatesGetOneInput(BaseModel):
    team_name: str = Field(...,
                    description="The name of your team.",
                    example="glowingkitties"
                    )
    

mates_get_one_output_example = {
    "id": 1,
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_picture_url": "/{team_url}/uploads/sophia_image.jpeg",
    "systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "systemprompt_is_customized": False,
    "skills": [
        {
            "id": 3,
            "name": "Write & test code",
            "description": "Writes and tests code based on the given requirements.",
            "software": {
                "id": 4,
                "name": "VS Code"
            },
            "api_endpoint": "/{team_url}/skills/vs_code/write_and_test_code"
        }
    ],
    "skills_are_customized": False
}


# POST /mates (create a new mate)

class MatesCreateInput(BaseModel):
    """This is the model for the incoming parameters for POST /mates"""
    name: str = Field(..., description="Name of the AI team mate", min_length=1, max_length=30)
    username: str = Field(..., description="Username of the AI team mate", min_length=1, max_length=30, unique=True)
    description: str = Field(..., description="Description of the AI team mate", min_length=1, max_length=150)
    profile_picture_url: str = Field(..., description="URL of the profile picture of the AI team mate", pattern=r".*\.(jpg|jpeg|png)$")
    default_systemprompt: str = Field(..., description="Default system prompt of the AI team mate", min_length=1)
    default_skills: Optional[List[int]] = Field(None, description="Default list of skill IDs for the AI team mate")
    
    # TODO improve validation later using LLMs

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
            raise ValueError('profile picture URL must be in the right format: /{team_url}/uploads/{filename}')
        return v
        


mates_create_input_example = {
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_picture_url": "/{team_url}/uploads/sophia_image.jpeg",
    "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "default_skills": [3]
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

mates_create_output_example = {
    "id": 2,
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_picture_url": "/{team_url}/uploads/sophia_image.jpeg",
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
            "api_endpoint": "/{team_url}/skills/vs_code/write_and_test_code"
        }
    ]
}


# PATCH /mates/{mate_username} (update a mate)

class MatesUpdateInput(BaseModel):
    """This is the model for the incoming parameters for PATCH /mates/{mate_username}"""
    name: Optional[str] = Field(None, description="Name of the AI team mate")
    username: Optional[str] = Field(None, description="Username of the AI team mate", min_length=1, max_length=30, unique=True)
    description: Optional[str] = Field(None, description="Description of the AI team mate", min_length=1, max_length=150)
    profile_picture_url: Optional[str] = Field(None, description="URL of the profile picture of the AI team mate", pattern=r".*\.(jpg|jpeg|png)$")
    default_systemprompt: Optional[str] = Field(None, description="Default system prompt of the AI team mate", min_length=1)
    default_skills: Optional[List[int]] = Field(None, description="Default list of skill IDs for the AI team mate")
    systemprompt: Optional[str] = Field(None, description="Custom system prompt of the AI team mate, specific for the user who makes the request to the API, in the context of the selected team.", min_length=1)
    skills: Optional[List[int]] = Field(None, description="Custom list of skill IDs for the AI team mate, specific for the user who makes the request to the API, in the context of the selected team.")

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
            raise ValueError('profile picture URL must be in the right format: /{team_url}/uploads/{filename}')
        return v

mates_update_input_example = {
    "description": "A software development expert, who can help you with all your coding needs."
}


class MateUpdateOutput(BaseModel):
    """This is the model for the outgoing response for POST /mates"""
    id: int = Field(..., description="ID of the AI team mate")
    updated_fields: List[dict] = Field(..., description="Dict with all updated fields")

mates_update_output_example = {
    "id": 1,
    "updated_fields": [
        {"description": "A software development expert, who can help you with all your coding needs."}
    ]
}