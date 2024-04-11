
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
from enum import Enum

##################################
######### Software ###############
##################################

## Base models

class Software(BaseModel):
    id: int = Field(..., description="ID of the software")
    name: str = Field(..., description="Name of the software")