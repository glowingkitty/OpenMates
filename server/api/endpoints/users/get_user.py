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
from server.api.security.validation.validate_permissions import validate_permissions
from server.api.security.crypto import verify_hash, decrypt
from server.cms.endpoints.users.get_user import get_user as get_user_from_cms

async def get_user(
        team_slug: Optional[str] = None,
        request_sender_api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_token: Optional[str] = None,
        output_raw_data: bool = False,
        output_format: Literal["JSONResponse", "dict"] = "JSONResponse",
        decrypt_data: bool = False
    ) -> Union[JSONResponse, Dict, HTTPException]:
    """
    Get a specific user.
    """
    try:
        add_to_log(module_name="OpenMates | API | Get user", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a specific user ...")

        # TODO clean up function, make it simpler and easier to read

        if not api_token and not (username and password):
            raise ValueError("You need to provide either an api token or username and password.")

        # check if the user is a server or team admin
        if request_sender_api_token or (username and password):
            # TODO this means the database is asked twice for the user data, inefficient...
            user_access = await validate_permissions(
                endpoint=f"/users/{username}",
                team_slug=team_slug,
                user_api_token=request_sender_api_token,
                user_username=username,
                user_password=password
            )
        else:
            user_access = "basic_access"

        return await get_user_from_cms(
            user_access=user_access,
            team_slug=team_slug,
            request_sender_api_token=request_sender_api_token,
            username=username,
            password=password,
            api_token=api_token,
            output_raw_data=output_raw_data,
            output_format=output_format,
            decrypt_data=decrypt_data
        )
    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the user.")