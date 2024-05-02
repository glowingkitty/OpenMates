
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