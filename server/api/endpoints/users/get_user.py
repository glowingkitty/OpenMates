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


async def get_user_processing(
        team_slug: str,
        request_sender_api_token: str,
        search_by_username: Optional[str] = None,
        search_by_user_api_token: Optional[str] = None,
        output_raw_data: bool = False,
        output_format: Literal["JSONResponse", "dict"] = "JSONResponse"
    ) -> Union[JSONResponse, Dict, HTTPException]:
    """
    Get a specific user.
    """
    try:
        add_to_log(module_name="OpenMates | API | Get user", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a specific user ...")

        if not search_by_username and not search_by_user_api_token:
            raise ValueError("Username or user API token must be provided.")

        user_access = await validate_user_data_access(
            search_by_username=search_by_username,
            request_team_slug=team_slug,
            request_sender_api_token=request_sender_api_token,
            request_endpoint="get_one_user"
        )

        fields = {
            "full_access":[
                "username",
                "api_token",
                "email",
                "balance",
                "software_settings",
                "other_settings",
                "goals",
                "todos",
                "recent_topics"
            ],
            "basic_access":[
                "username"
            ]
        }
        populate = {
            "full_access":[
                "profile_image.file.url",
                "teams.slug",
                "projects.name"
            ],
            "basic_access":[]
        }
        filters = []
        if search_by_username:
            filters.append({
                "field": "username",
                "operator": "$eq",
                "value": search_by_username
            })
        if search_by_user_api_token:
            filters.append({
                "field": "api_token",
                "operator": "$eq",
                "value": search_by_user_api_token
            })

        status_code, json_response = await make_strapi_request(
            method="get",
            endpoint="users",
            filters=filters,
            fields=fields[user_access],
            populate=populate[user_access]
        )

        if status_code == 200:
            # make sure there is only one user with the requested username
            user = {}
            users = json_response
            if len(users) == 0:
                status_code = 404
                json_response = {"detail": "Could not find the requested user."}
            elif len(users) > 1:
                status_code = 404
                json_response = {"detail": "There are multiple users with the requested username."}
            else:
                user = users[0]

                # return the unprocessed json if requested
                if output_raw_data:
                    if output_format == "JSONResponse":
                        return JSONResponse(status_code=status_code, content=user)
                    else:
                        return user

                user = {
                    "id": user["id"],
                    "username": user["username"],
                    "email": user["email"],
                    "teams": [
                        {
                            "id": team["id"],
                            "name": team["name"],
                            "slug": team["slug"]
                        } for team in user["teams"]
                    ],
                    "profile_picture_url":  f"/{team_slug}{get_nested(user, ['profile_image', 'file','url'])}" if get_nested(user, ['profile_image']) else None,
                    "balance_eur": user["balance"],
                    "software_settings": user["software_settings"],
                    "other_settings": user["other_settings"],
                    "projects": [
                        {
                            "id": project["id"],
                            "name": project["name"],
                            "description": project["description"]
                        } for project in user["projects"]
                    ],
                    "goals": user["goals"],
                    "todos": user["todos"],
                    "recent_topics": user["recent_topics"]
                } if user_access == "full_access" else {
                    "id": user["id"],
                    "username": user["username"]
                }

                json_response = user


        add_to_log("Successfully got the user.", state="success")

        if output_format == "JSONResponse":
            return JSONResponse(status_code=status_code, content=json_response)
        else:
            return json_response

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to get the user.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the user.")