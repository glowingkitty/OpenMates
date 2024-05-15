
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
from typing import Optional


async def validate_invite_code(
    invite_code: str,
    team_slug: Optional[str] = None
    ):
    """
    Verify if the invite code is valid
    """
    try:
        # TODO
        add_to_log("Verifying the invite code ...", module_name="OpenMates | API | Validate Invite Code", color="yellow")

        # find the invite code and check if it is valid
        fields = [
            "id",
            "team_slug",
            "is_valid"
        ]
        filters = [
            {
                "field": "invite_code",
                "operator": "$eq",
                "value": invite_code
            }
        ]

        if team_slug:
            filters.append({
                "field": "team_slug",
                "operator": "$eq",
                "value": team_slug
            })

        status_code, invite_code_json_response = await make_strapi_request(
            method='get',
            endpoint='invite-codes',
            fields=fields,
            filters=filters
            )

        failure_message = "The invite code is invalid. Make sure the invite code and team_slug are valid."

        if status_code != 200:
            add_to_log("Got a status code of " + str(status_code) + " from strapi.", module_name="OpenMates | API | Validate Invite Code", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        if not invite_code_json_response:
            add_to_log("The invite code is invalid. Make sure the invite code and team_slug are valid.", module_name="OpenMates | API | Validate Invite Code", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        if not invite_code_json_response[0]['is_valid']:
            add_to_log("The invite code is invalid. Make sure the invite code and team_slug are valid.", module_name="OpenMates | API | Validate Invite Code", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        return invite_code_json_response

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to validate the invite code.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the invite code. Please contact the administrator.")