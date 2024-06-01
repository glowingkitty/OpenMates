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
from typing import Union, Literal
from server.api.security.crypto import hashing_sha256


async def validate_user_data_access(
        request_team_slug: str,
        request_sender_api_token: str,
        username: str = None,
        request_endpoint: Literal["get_one_user", "get_all_users"] = "get_one_user"
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
            populate=["teams_where_user_is_admin.slug"],
            filters=[{
                "field": "api_token",
                "operator": "$eq",
                "value": hashing_sha256(request_sender_api_token)
            }]
        )
        if status_code != 200 or not json_response:
            add_to_log("User not found.", state="error")
            raise HTTPException(status_code=404, detail="User not found.")

        # check if the user has the righ to acces the
        if request_endpoint == "get_one_user":
            add_to_log("Checking if the user has the permission to access a specific user ...")

            # check if the found user has the same username as in username
            if username and json_response[0]["username"] == username:
                # if so that means a user tries to get its own data and we can proceed with 'full data' access
                add_to_log("User is trying to access its own data.")
                return "full_access"

            # else we check if the user is marked as a server admin, if so, we can proceed 'basic data' access
            if json_response[0]["is_server_admin"]:
                add_to_log("User is a server admin and has the permission to access all basic user data.")
                return "basic_access"

            # else we check if the user is a team admin, if so, we can proceed with 'basic data' access
            for team in json_response[0]["teams_where_user_is_admin"]:
                if team["slug"] == request_team_slug:
                    # user is team admin and therefore is allowed to access the 'basic data' of all users on the team
                    add_to_log("User is a team admin and has the permission to access all basic user data on the team.")
                    return "basic_access"

            # else, the user is not allowed to access the data
            add_to_log("User does not have the permission to access the user data.")
            raise HTTPException(status_code=404, detail="User not found. Either the username is wrong, the team slug is wrong or the user is not part of the team or you don't have the permission to access this user.")


        if request_endpoint == "get_all_users":
            add_to_log("Checking if the user has the permission to access all users ...")
            # check if the found user is a server admin, if so, we can proceed with 'basic data' access
            if json_response[0]["is_server_admin"]:
                add_to_log("User is a server admin and has the permission to access all basic user data.")
                return "basic_access_for_all_users_on_server"

            # check if user is a team admin, if so, we can proceed with 'basic data' access
            for team in json_response[0]["teams_where_user_is_admin"]:
                if team["slug"] == request_team_slug:
                    # user is team admin and therefore is allowed to access the 'basic data' of all users on the team
                    add_to_log("User is a team admin and has the permission to access all basic user data on the team.")
                    return "basic_access_for_all_users_on_team"

            # else the user is only allowed to access the 'basic data' of the user itself
            add_to_log("User is only allowed to access its own data.")
            return "basic_access_for_own_user_only"



    except HTTPException:
        raise

    except Exception:
        process_error("Failed to validate the user data access.",traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the user data access.")