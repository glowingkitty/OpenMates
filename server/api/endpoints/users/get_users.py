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

from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from server.api.models.users.users_get_all import UsersGetAllOutput
from fastapi import HTTPException
from server.api.validation.validate_user_data_access import validate_user_data_access


async def get_users_processing(
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

        user_access = await validate_user_data_access(
            request_team_slug=team_slug,
            request_sender_api_token=request_sender_api_token,
            request_endpoint="get_all_users"
        )

        fields = [
            "username"
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
                "field": "api_token",
                "operator": "$eq",
                "value": request_sender_api_token
            })

        status_code, json_response = await make_strapi_request(
            method='get', 
            endpoint='users', 
            fields=fields, 
            filters=filters,
            page=page,
            pageSize=pageSize,
            )

        if status_code == 200:
            users = [
                {
                    "id": user.get("id"),
                    "username": user.get("username")
                }
                for user in json_response
            ]
            meta = {
                "pagination": {
                    "page": page,
                    "pageSize": pageSize,
                    "pageCount": 1,
                    "total": len(users)
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
        process_error("Failed to get all users in the team.",traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get all users in the team.")