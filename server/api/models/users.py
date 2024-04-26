
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
######### Users ##################
##################################

## Base models

class User(BaseModel):
    """This is the base model for a user"""
    id: int = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")
    # TODO add the rest of the fields