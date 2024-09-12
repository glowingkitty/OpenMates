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

from server.api import *
################

from typing import List, Optional, Union, Dict, Literal
from server.cms.cms import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.models.users.users_create_new_api_token import UsersCreateNewApiTokenOutput
from server.api.endpoints.users.get_user import get_user
from server.api.validation.validate_token import validate_token
import secrets


async def create_new_api_token(
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> UsersCreateNewApiTokenOutput:
    """
    Create a new API token for the user
    """
    add_to_log("Creating a new API token ...", module_name="OpenMates | API | Create New API Token", color="yellow")
    # create a new uid
    uid = secrets.token_hex(16)

    # create a new API token
    api_token = secrets.token_hex(16)

    # make sure the new uid and API token don't already exist
    try:
        while await validate_token(token=uid+api_token):
            uid = secrets.token_hex(16)
            api_token = secrets.token_hex(16)
    except HTTPException as e:
        if e.status_code == 403:
            add_to_log("The token does not exist yet. Continuing ...", module_name="OpenMates | API | Create New API Token", color="green")
        else:
            raise e

    # try to find the user in the database, if it already exists, replace the existing API token
    # else, only create a new API token (but don't update any user data)
    if username and password:
        user = await get_user(
            username=username,
            password=password,
            output_format="dict",
            output_raw_data=True
        )

        if user and "id" in user:
            add_to_log("User found. Replacing the existing uid and api_token ...", module_name="OpenMates | API | Create New API Token", color="green")
            # TODO create update_user function
            update_user(id=user["id"], uid=uid, api_token=api_token)

        else:
            raise HTTPException(status_code=404, detail="Could not find the requested user.")


    return {
        "api_token": uid+api_token
    }