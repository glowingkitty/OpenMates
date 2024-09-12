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

from server.api import *
################

from fastapi import HTTPException
from server.cms.strapi_requests import make_strapi_request


async def validate_user_username(username:str) -> bool:
    """
    Validate if the user username is already taken
    """
    try:
        add_to_log(module_name="OpenMates | API | Validate Username", state="start", color="yellow", hide_variables=True)
        add_to_log("Validating if the user username is already taken ...")

        # try to get the user from strapi
        fields = [
            "username"
        ]
        filters = [
            {
                "field": "username",
                "operator": "$eq",
                "value": username
            }
        ]
        status_code, user_json_response = await make_strapi_request(
            method='get',
            endpoint='user-accounts',
            fields=fields,
            filters=filters
        )

        # check if the username is already taken
        if status_code == 200 and user_json_response:
            add_to_log("The username is already taken.")
            raise HTTPException(status_code=400, detail="The username is not available. Please choose another one.")
        else:
            add_to_log("The username is not taken.")
            return True

    except HTTPException:
        raise

    except Exception:
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the username.")