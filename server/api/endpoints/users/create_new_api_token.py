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

from typing import List, Optional, Union, Dict, Literal
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.models.users.users_create_new_api_token import UsersCreateNewApiTokenOutput


async def create_new_api_token_processing(
        username: str,
        email: str,
        password: str,
        team_slug: str
    ) -> UsersCreateNewApiTokenOutput:
    """
    Create a new API token for the user
    """

    # TODO generate new API token, save it to the database and return it

    return {
        "api_token": "0jasdjj2i2ik83hdhD98kd"
    }