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

from server.api import *
################

from fastapi import HTTPException
from server.cms.strapi_requests import make_strapi_request, get_nested
from typing import Optional
from datetime import datetime


async def validate_invite_code(
    invite_code: str,
    team_slug: Optional[str] = None
    ):
    """
    Verify if the invite code is valid
    """
    try:
        add_to_log("Verifying the invite code ...", module_name="OpenMates | API | Validate Invite Code", color="yellow")

        # find the invite code and check if it is valid
        fields = [
            "code",
            "expire_date",
            "can_be_used_once",
            "can_be_used_x_more_times"
        ]
        populate = [
            "valid_to_access_team.slug"
        ]
        filters = [
            {
                "field": "code",
                "operator": "$eq",
                "value": invite_code
            }
        ]

        status_code, invite_code_json_response = await make_strapi_request(
            method='get',
            endpoint='invitecodes',
            fields=fields,
            populate=populate,
            filters=filters
            )

        invite_codes = invite_code_json_response["data"]

        if invite_codes:
            # only leave invite codes which to not have any team resistrictions or have the team_slug in the valid_to_access_team.slug
            invite_codes = [invite_code for invite_code in invite_codes if not get_nested(invite_code, "valid_to_access_team") or get_nested(invite_code, "valid_to_access_team.slug") == team_slug]

            # filter out invite codes which are expired (if date is set)
            invite_codes = [invite_code for invite_code in invite_codes if not get_nested(invite_code, "expire_date") or datetime.strptime(get_nested(invite_code, "expire_date"), '%Y-%m-%dT%H:%M:%S.%fZ') > datetime.now()]

        failure_message = "The invite code is invalid. This can be for various reasons. Maybe the code doesn't exist, or its for a specific team, or it expired."

        if status_code != 200:
            add_to_log("Got a status code of " + str(status_code) + " from strapi.", module_name="OpenMates | API | Validate Invite Code", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        if not invite_codes:
            add_to_log(failure_message, module_name="OpenMates | API | Validate Invite Code", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        # mark the invite code as used (and if it can only be used once, delete it)
        add_to_log("The invite code is valid. Now marking it as used.", module_name="OpenMates | API | Validate Invite Code", state="success")
        invite_code = invite_codes[0]
        # if the invite code can be used x more times, decrement the counter
        if get_nested(invite_code, "can_be_used_x_more_times") != None:
            if get_nested(invite_code, "can_be_used_x_more_times") > 0:
                invite_code["attributes"]["can_be_used_x_more_times"] -= 1
                status_code, invite_code_json_response = await make_strapi_request(
                    method='put',
                    endpoint='invitecodes/' + str(invite_code["id"]),
                    data={
                        "data": {
                            "can_be_used_x_more_times": get_nested(invite_code, "can_be_used_x_more_times")
                        }
                    }
                )

            # if the counter is 0, delete the invite code
            if get_nested(invite_code, "can_be_used_x_more_times") == 0:
                status_code, invite_code_json_response = await make_strapi_request(
                    method='delete',
                    endpoint='invitecodes/' + str(invite_code["id"])
                )

        # if the invite code can only be used once, delete the invite code
        if get_nested(invite_code, "can_be_used_once") == True:
            status_code, invite_code_json_response = await make_strapi_request(
                method='delete',
                endpoint='invitecodes/' + str(invite_code["id"])
            )

        if status_code != 200:
            add_to_log("Got a status code of " + str(status_code) + " from strapi.", module_name="OpenMates | API | Validate Invite Code", state="error")
            raise HTTPException(status_code=403, detail=failure_message)

        return True

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the invite code. Please contact the administrator.")