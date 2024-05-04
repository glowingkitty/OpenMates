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
from server.cms.strapi_requests import make_strapi_request
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.validation.validate_user_data_access import validate_user_data_access


async def get_user_processing(
        request_sender_api_token: str,
        search_by_username: Optional[str] = None,
        search_by_user_api_token: Optional[str] = None,
        output_raw_data: bool = False,
        output_format: Literal["JSONResponse", "json"] = "JSONResponse"
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
            request_sender_api_token=request_sender_api_token
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

        if not json_response:
            add_to_log("User not found ...", color="red")
            raise HTTPException(status_code=404, detail="User not found. Either the username is wrong, or you don't have the permission to access this user.")

        if output_raw_data:
            if output_format == "JSONResponse":
                return JSONResponse(status_code=status_code, content=json_response)
            else:
                return json_response
        
        if output_format == "JSONResponse":
            return JSONResponse(status_code=status_code, content=json_response)
        else:
            return json_response
        
    except HTTPException:
        raise

    except Exception:
        process_error("Failed to get the user.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the user.")