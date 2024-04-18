
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

from fastapi import Header, HTTPException
from server.api.load_valid_tokens import load_valid_tokens
from typing import Optional
from server.api.validate_file_access import validate_file_access



async def verify_token(
        team_url: str, 
        token: str, 
        scope: str,
        requested_file_name: Optional[str] = None
        ):
    """
    Verify the API token
    """
    try:
        add_to_log("Verifying the API token ...", module_name="OpenMates | API | Verify Token", color="yellow")
    
        # if requested_file_name, check if user has access to file (including public access without token)
        if requested_file_name:
            return await validate_file_access(
                filename = requested_file_name,
                team_url = team_url,
                user_api_token = token,
                scope = scope
                )

        return True


        # TODO implement the token verification logic

        # TODO: verify that the token is valid, valid for the team and has the necessary scope
        # TODO: implement strapi to save the users
        # TODO: also check if the user has still money left (if skill is not free)


        valid_tokens = load_valid_tokens()
        if team_name in valid_tokens and token in valid_tokens[team_name]:
            if scope in valid_tokens[team_name][token]:
                add_to_log("Success. The API token is valid.",module_name="OpenMates | API | Verify Token", state="success")
                return True
            else:
                add_to_log("The API token does not have the necessary scope.", module_name="OpenMates | API | Verify Token", state="success")
                raise HTTPException(status_code=403, detail="The API token does not have the necessary scope.")
        else:
            add_to_log("The API token is invalid. Make sure you use a valid key and that the key is valid for the requested team and scope.", module_name="OpenMates | API | Verify Token", state="success")
            raise HTTPException(status_code=401, detail="The API token is invalid. Make sure you use a valid key and that the key is valid for the requested team.")

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to verify token.", traceback=traceback.format_exc())
        raise HTTPException(status_code=401, detail="The API key is invalid")