################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from fastapi import HTTPException
from server.cms.strapi_requests import make_strapi_request, get_nested
from server.api.security.crypto import verify_hash
from server.api.memory import get_user_from_memory, save_user_to_memory


async def validate_token(
    token: str,
    team_slug: str = None
    ):
    """
    Verify if the API token is valid for the requested team
    """
    try:
        add_to_log("Verifying the API token ...", module_name="OpenMates | API | Verify Token", color="yellow")

        # separate uid (first 32 characters) from api token (following 32 characters)
        uid = token[:32]
        api_token = token[32:]

        # Check Redis for the user
        user = get_user_from_memory(uid)
        if user:
            if verify_hash(get_nested(user, "api_token"), api_token):
                if team_slug is None or team_slug in [get_nested(team, "slug") for team in get_nested(user, "teams")]:
                    # Update the expiration time
                    save_user_to_memory(uid, user)
                    add_to_log("Token found in cache and is valid.", module_name="OpenMates | API | Verify Token", state="success")
                    return True

        # find the user with the token and check if the user is inside the team
        fields = [
            "api_token",
            "uid",
            "is_server_admin"
        ]
        populate = [
            "teams.slug"
        ]
        filters = [
            {
                "field": "uid",
                "operator": "$eq",
                "value": uid
            }
        ]

        add_to_log("Requesting user data from Strapi...", module_name="OpenMates | API | Verify Token", color="yellow")
        status_code, user_json_response = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            fields=fields,
            populate=populate,
            filters=filters
            )

        failure_message = "Your token is invalid. Make sure the token and team_slug are valid, you are part of the requested team and you have access to the requested API endpoint."

        users = user_json_response["data"]
        if status_code != 200:
            add_to_log("Got a status code of " + str(status_code) + " from strapi.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        if len(users) == 0:
            add_to_log("The user does not exist.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        if len(users) > 1:
            add_to_log("Found more than one user with the token.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=500, detail="Found more than one user with your token. Please contact the administrator.")

        if len(users) == 1:
            user = users[0]
            # check if the api token is valid
            if not verify_hash(get_nested(user, "api_token"), api_token):
                add_to_log("The user token is invalid.", module_name="OpenMates | API | Verify Token", state="error")
                raise HTTPException(status_code=403, detail=failure_message)

            # Store the valid user in Redis
            save_user_to_memory(uid, user)

            # check if the user is either a team admin or a member of the team
            if get_nested(user, "is_server_admin"):
                add_to_log("The user is a server admin.", module_name="OpenMates | API | Verify Token", state="success")
                return True
            if team_slug == None:
                return True
            if team_slug in [get_nested(team, "slug") for team in get_nested(user, "teams")]:
                add_to_log("The user is a member of the team.", module_name="OpenMates | API | Verify Token", state="success")
                return True

            add_to_log("The user token is invalid.", module_name="OpenMates | API | Verify Token", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        # all other checks (if the user is a team admin or not, if the user has access to the requested file, if the user has enough money left, etc.)
        # will be done in the respective endpoints

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=401, detail="The API key is invalid")