
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


# GET /users (get all users for a team)

class UserForGetAll(BaseModel):
    """This is the model for a single user, for the endpoint GET /users"""
    id: int = Field(..., description="ID of the user")
    username: str = Field(..., description="Username of the user")

class UsersGetAllOutput(BaseModel):
    data: List[UserForGetAll] = Field(..., description="List of all users")
    meta: MetaData = Field(..., description="Metadata for the response")


users_get_all_output_example = {
    "data": [
        {
            "id": 1,
            "username": "johnd"
        },
        {
            "id": 2,
            "username": "janea"
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