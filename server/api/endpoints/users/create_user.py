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
from server.api.validation.validate_user_data_access import validate_user_data_access
from server.api.models.users.users_create import UsersCreateOutput


async def create_user_processing(
        name: str,
        username: str,
        email: str,
        password: str,
        team_slug: str
    ) -> UsersCreateOutput:
    """
    Create a new user on the team
    """

    # TODO how to handle mate configs / default privacy settings?