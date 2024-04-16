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

from typing import List, Optional
from server.api.models.mates import MateUpdateOutput
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException


async def update_mate_processing(
        team_url: str,
        user_api_token: str,
        mate_username: str,
        new_name: Optional[str] = None,
        new_username: Optional[str] = None,
        new_description: Optional[str] = None,
        new_profile_picture_url: Optional[str] = None,
        new_default_systemprompt: Optional[str] = None,
        new_default_skills: Optional[List[int]] = None
    ) -> MateUpdateOutput:
    """
    Update a specific AI team mate on the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Update mate", state="start", color="yellow")
        add_to_log("Updating a specific AI team mate on the team ...")

        # TODO: implement processing

        return JSONResponse(status_code=200, content={"message": "AI team mate updated successfully."})
    
    except Exception:
        process_error("Failed to update the AI team mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to update the AI team mate.")