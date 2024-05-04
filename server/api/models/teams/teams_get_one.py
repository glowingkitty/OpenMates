
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


# GET /teams/{slug} (get a team)

class Team(BaseModel):
    id: int = Field(..., description="ID of the team")
    name: str = Field(..., description="Name of the team")
    slug: str = Field(..., description="Slug of the team")