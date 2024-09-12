################
# Default Imports
################
import sys
import os
import re
import math

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################

from server.cms.cms import make_strapi_request, get_nested
from server.api.models.users.users_get_all import UsersGetAllOutput
from fastapi import HTTPException
from server.api.validation.validate_permissions import validate_permissions
from server.cms.endpoints.users.get_users import get_users as get_users_from_cms


async def get_users(
        team_slug: str,
        request_sender_api_token: str,
        page: int = 1,
        pageSize: int = 25
    ) -> UsersGetAllOutput:
    """
    Get a list of all users on a team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get users", state="start", color="yellow")
        add_to_log("Getting a list of all users in a team ...")

        user_access = await validate_permissions(
            endpoint="/users",
            user_api_token=request_sender_api_token,
            team_slug=team_slug
        )

        return await get_users_from_cms(
            user_access=user_access,
            team_slug=team_slug,
            request_sender_api_token=request_sender_api_token,
            page=page,
            pageSize=pageSize
        )

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get all users in the team.")