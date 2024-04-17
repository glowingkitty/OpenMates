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

async def validate_file_access(
        filename: str,
        team_url: str,
        user_api_token: str
    ) -> bool:
    """
    Validate if the user has access to the file (and if its uploaded)
    """
    try:
        add_to_log(module_name="OpenMates | API | Validate Profile Picture URL Access", state="start", color="yellow")
        add_to_log("Validating if the user has access to the file ...")

        # TODO: check if the image is uploaded to the server in the team of the user

    except Exception:
        process_error("Failed to validate the profile picture URL access.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the profile picture URL access.")