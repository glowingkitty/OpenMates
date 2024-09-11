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
from server.cms.strapi_requests import make_strapi_request, get_nested
from typing import Union, Literal
from server.api.security.crypto import verify_hash
from server.api.memory import get_user_from_memory, save_user_to_memory

def check_user_access(user, request_team_slug, request_endpoint, username):
    if request_endpoint == "get_one_user":
        if username and get_nested(user, "username") == username:
            add_to_log("User is trying to access its own data.")
            return "full_access"
        if get_nested(user, "is_server_admin"):
            add_to_log("User is a server admin and has the permission to access all basic user data.")
            return "basic_access"
        if request_team_slug and get_nested(user, "teams_where_user_is_admin"):
            for team in get_nested(user, "teams_where_user_is_admin"):
                if get_nested(team, "slug") == request_team_slug:
                    add_to_log("User is a team admin and has the permission to access all basic user data on the team.")
                    return "basic_access"
        add_to_log("User does not have the permission to access the user data.")
        raise HTTPException(status_code=404, detail="User not found. Either the username is wrong, the team slug is wrong or the user is not part of the team or you don't have the permission to access this user.")
    elif request_endpoint == "get_all_users":
        if get_nested(user, "is_server_admin"):
            add_to_log("User is a server admin and has the permission to access all basic user data.")
            return "basic_access_for_all_users_on_server"
        if request_team_slug and get_nested(user, "teams_where_user_is_admin"):
            for team in get_nested(user, "teams_where_user_is_admin"):
                if get_nested(team, "slug") == request_team_slug:
                    add_to_log("User is a team admin and has the permission to access all basic user data on the team.")
                    return "basic_access_for_all_users_on_team"
        add_to_log("User is only allowed to access its own data.")
        return "basic_access_for_own_user_only"


async def validate_user_data_access(
        request_team_slug: str,
        token: str = None,
        username: str = None,
        password: str = None,
        request_endpoint: Literal["get_one_user", "get_all_users"] = "get_one_user"
    ) -> Union[dict, str, HTTPException]:
    """
    Validate if the user has access to the user data
    """
    try:
        add_to_log(module_name="OpenMates | API | Validate user data Access", state="start", color="yellow", hide_variables=True)
        add_to_log("Validating if the user has access to the user data ...")

        filters = []

        if token:
            uid = token[:32]
            api_token = token[32:]

            user = get_user_from_memory(uid)
            if user:
                if verify_hash(get_nested(user, "api_token"), api_token):
                    return check_user_access(user, request_team_slug, request_endpoint, username)

            filters.append({
                "field": "uid",
                "operator": "$eq",
                "value": uid
            })
        elif username:
            filters.append({
                "field": "username",
                "operator": "$eq",
                "value": username
            })

        status_code, json_response = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            fields=["is_server_admin","username","api_token","uid","password"],
            populate=["teams_where_user_is_admin.slug"],
            filters=filters
        )
        if status_code != 200 or not json_response or len(json_response["data"]) == 0:
            add_to_log("User not found.", state="error")
            raise HTTPException(status_code=404, detail="User not found.")

        user = json_response["data"][0]
        save_user_to_memory(uid, json_response)

        if token and not verify_hash(get_nested(user, "api_token"), api_token):
            add_to_log("The user token is invalid.", module_name="OpenMates | API | Validate user data Access", state="error")
            raise HTTPException(status_code=403, detail="The user token is invalid")

        if password and not verify_hash(get_nested(user, "password"), password):
            add_to_log("The password invalid.", module_name="OpenMates | API | Validate user data Access", state="error")
            raise HTTPException(status_code=403, detail="The password is invalid")

        return check_user_access(user, request_team_slug, request_endpoint, username)

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the user data access.")