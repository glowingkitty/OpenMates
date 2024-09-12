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

from typing import Optional
from fastapi import HTTPException
from server.cms.strapi_requests import make_strapi_request
from server.api.validation.validate_token import validate_token
from server.api.validation.validate_user_data_access import validate_user_data_access
from server.api.validation.validate_file_access import validate_file_access



# TODO add tests

async def validate_permissions(
    endpoint: str,
    user_api_token: str,
    team_slug: Optional[str] = None,
    user_username: Optional[str] = None,
    user_password: Optional[str] = None,
    user_api_token_already_checked: Optional[bool] = False,
    required_permissions: Optional[list] = None
) -> dict:
    try:
        add_to_log(module_name="OpenMates | API | Validate Permissions", state="start", color="yellow", hide_variables=True)
        add_to_log(f"Validating permissions for endpoint '{endpoint}'...")

        # TODO handle different endpoint usecases

        # TODO if username and password instead of token are given, handle that

        # /uploads/...
        if endpoint.startswith("/uploads/"):
            access = await validate_file_access(
                user_api_token=user_api_token,
                filename=endpoint.split("/")[-1],
                team_slug=team_slug
            )
            return access

        # /users
        if endpoint == "/users":
            access = await validate_user_data_access(
                token=user_api_token,
                request_team_slug=team_slug,
                username=user_username,
                password=user_password,
                request_endpoint="get_all_users"
            )
            return access

        # else just check the token
        if not user_api_token_already_checked:
            await validate_token(
                token=user_api_token,
                team_slug=team_slug
            )

        # TODO handle check for access to create, delete or update mate

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="An error occurred while validating permissions")