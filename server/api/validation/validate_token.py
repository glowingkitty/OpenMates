
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
from server.cms.strapi_requests import make_strapi_request


async def validate_token(
    team_slug: str,
    token: str
    ):
    """
    Verify if the API token is valid for the requested team
    """
    try:
        add_to_log("Verifying the API token ...", module_name="OpenMates | API | Verify Token", color="yellow")

        # find the user with the token and check if the user is inside the team
        fields = [
            "api_token",
            "is_server_admin"
        ]
        populate = [
            "teams.slug"
        ]
        filters = [
            {
                "field": "api_token",
                "operator": "$eq",
                "value": token
            }
        ]

        status_code, user_json_response = await make_strapi_request(
            method='get',
            endpoint='users',
            fields=fields,
            populate=populate,
            filters=filters
            )

        failure_message = "Your token is invalid. Make sure the token and team_slug are valid, you are part of the requested team and you have access to the requested API endpoint."

        if status_code != 200:
            add_to_log("Got a status code of " + str(status_code) + " from strapi.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        if len(user_json_response) == 0:
            add_to_log("The user does not exist.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        if len(user_json_response) > 1:
            add_to_log("Found more than one user with the token.", module_name="OpenMates | API | Validate file Access", state="error")
            raise HTTPException(status_code=500, detail="Found more than one user with your token. Please contact the administrator.")

        if len(user_json_response) == 1:
            # check if the user is either a team admin or a member of the team
            user = user_json_response[0]
            if user["is_server_admin"]:
                add_to_log("The user is a server admin.", module_name="OpenMates | API | Verify Token", state="success")
                return True
            if team_slug in [team["slug"] for team in user["teams"]]:
                add_to_log("The user is a member of the team.", module_name="OpenMates | API | Verify Token", state="success")
                return True

            add_to_log("The user token is invalid.", module_name="OpenMates | API | Verify Token", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        # all other checks (if the user is a team admin or not, if the user has access to the requested file, if the user has enough money left, etc.)
        # will be done in the respective endpoints

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to verify token.", traceback=traceback.format_exc())
        raise HTTPException(status_code=401, detail="The API key is invalid")