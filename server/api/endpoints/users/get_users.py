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

from server import *
################

from server.cms.strapi_requests import make_strapi_request, get_nested
from server.api.models.users.users_get_all import UsersGetAllOutput
from fastapi import HTTPException
from server.api.validation.validate_permissions import validate_permissions


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

        fields = [
            "username",
            "id"
        ]
        filters = [
            {
                "field": "teams.slug",
                "operator": "$eq",
                "value": team_slug
            }
        ]

        if user_access == "basic_access_for_own_user_only":
            filters.append({
                "field": "uid",
                "operator": "$eq",
                "value": request_sender_api_token[:32]
            })

        # Get the users with pagination info
        status_code, json_response = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            fields=fields,
            filters=filters,
            page=page,
            pageSize=pageSize
        )

        if status_code == 200:
            users = [
                {
                    "id": get_nested(user, "id"),
                    "username": get_nested(user, "username")
                }
                for user in json_response.get("data", [])
            ]

            # Extract pagination info from the response
            pagination = json_response.get("meta", {}).get("pagination", {})
            total = pagination.get("total", 0)
            page_count = pagination.get("pageCount", 0)

            meta = {
                "pagination": {
                    "page": page,
                    "pageSize": pageSize,
                    "pageCount": page_count,
                    "total": total
                }
            }
            users_get_all_output = {
                "data": users,
                "meta": meta
            }
            add_to_log(module_name="OpenMates | API | Get users", state="end", color="green")
            return UsersGetAllOutput(**users_get_all_output)
        else:
            add_to_log(module_name="OpenMates | API | Get users", state="end", color="red")
            raise HTTPException(status_code=status_code, detail=json_response)

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get all users in the team.")