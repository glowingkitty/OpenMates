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

from fastapi import HTTPException
from server.cms.strapi_requests import make_strapi_request
from typing import Union


async def validate_user_data_access(
        request_sender_api_token: str,
        search_by_username: str
    ) -> Union[dict, str, HTTPException]:
    """
    Validate if the user has access to the user data
    """
    try:
        add_to_log(module_name="OpenMates | API | Validate user data Access", state="start", color="yellow", hide_variables=True)
        add_to_log("Validating if the user has access to the user data ...")

        # get the userdata for the user who makes the request, based on the request_sender_api_token
        status_code, json_response = await make_strapi_request(
            method='get', 
            endpoint='users',
            fields=["is_server_admin","username"],
            filters=[{
                "field": "api_token",
                "operator": "$eq",
                "value": request_sender_api_token
            }]
        )
        if status_code != 200 or not json_response:
            raise HTTPException(status_code=404, detail="User not found.")

        # check if the found user has the same username as in search_by_username
        if json_response[0]["username"] == search_by_username:
            # if so that means a user tries to get its own data and we can proceed with 'full data' access
            return "full_access"

        # else we check if the user is marked as a server admin, if so, we can proceed 'basic data' access
        if json_response[0]["is_server_admin"]:
            return "basic_access"
        
        # else, the user is not allowed to access the data
        add_to_log("User does not have the permission to access the user data.")
        raise HTTPException(status_code=404, detail="User not found. Either the username is wrong, or you don't have the permission to access this user.")
        

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to validate the user data access.",traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the user data access.")