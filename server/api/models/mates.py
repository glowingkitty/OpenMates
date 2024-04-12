
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

from pydantic import BaseModel, Field
from typing import List
from server.api.models.metadata import MetaData
from server.api.models.skills import Skill

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
    default_systemprompt: str = Field(..., description="Default system prompt of the AI team mate")
    skills: List[Skill] = Field(..., description="Skills of the AI team mate")



## Endpoint models

# POST /mates/ask (Send a message to an AI team mate and you receive the response)

class MatesAskInput(BaseModel):
    """This is the model for the incoming parameters for POST /mates/ask"""
    mate_username: str = Field(...,
                    description="Username of the AI team mate who the message is for.",
                    example="sophia"
                    )
    message: str = Field(..., 
                    description="Message to send to the AI team mate.", 
                    example="Write me some python code that prints 'Hello, AI!'"
                    )


class MatesAskOutput(BaseModel):
    """This is the model for outgoing message for POST /mates/ask"""
    message: str = Field(..., 
                    description="The content of the message", 
                    example="Of course I can help you with that! Here is the python code you requested: print('Hello, AI!')\n\nI hope this helps you out. If you have any more questions, feel free to ask!"
                    )
    tokens_used_input: int = Field(...,
                    description="The number of tokens used to process the input message",
                    example=20
                    )
    tokens_used_output: int = Field(...,
                    description="The number of tokens used to generate the output message",
                    example=46
                    )
    total_costs_eur: float = Field(...,
                    description="The total cost of processing the message, in EUR",
                    example=0.003
                    )


# GET /mates (get all mates)

class MatesGetAllOutput(BaseModel):
    data: List[Mate] = Field(..., description="List of all AI team mates for the team")
    meta: MetaData = Field(..., description="Metadata for the response")


mates_get_all_output_example = {
    "data": [
        {
            "id": 1,
            "name": "Burton",
            "username": "burton",
            "description": "Business development expert",
            "profile_picture_url": "/{team_url}/uploads/burton_image.jpeg",
            "default_systemprompt": "You are an expert in business development. Keep your answers concise.",
            "skills": [
                {
                    "id": 1,
                    "name": "Create",
                    "description": "Create a new page in Notion.",
                    "software": {
                        "id": 1,
                        "name": "Notion"
                    },
                    "api_endpoint": "/{team_url}/skills/notion/create"
                },
                {
                    "id": 2,
                    "name": "Search",
                    "description": "Search & filter for videos on YouTube.",
                    "software": {
                        "id": 2,
                        "name": "YouTube"
                    },
                    "api_endpoint": "/{team_url}/skills/youtube/search"
                }
            ]
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