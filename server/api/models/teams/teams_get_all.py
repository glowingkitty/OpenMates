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

# GET /teams (get all teams)

class TeamMini(BaseModel):
    """This is the model for a single team, for the endpoint GET /teams"""
    id: int = Field(..., description="The unique identifier for the team")
    name: str = Field(..., description="The name of the team")
    slug: str = Field(..., description="The URL-friendly name of the team")
    number_of_members: int = Field(..., description="The number of members in the team")

class TeamsGetAllOutput(BaseModel):
    data: List[TeamMini] = Field(..., description="List of all teams on the server")
    meta: MetaData = Field(..., description="Metadata for the response")

teams_get_all_output_example = {
    "data": [
        {
            "id": 1,
            "name": "OpenMates Enthusiasts",
            "slug": "openmates_enthusiasts",
            "number_of_members": 10
        },
        {
            "id": 2,
            "name": "AI Research Team",
            "slug": "ai_research_team",
            "number_of_members": 5
        }
    ],
    "meta": {
        "pagination": {
            "page": 1,
            "pageSize": 25,
            "pageCount": 1,
            "total": 2
        }
    }
}