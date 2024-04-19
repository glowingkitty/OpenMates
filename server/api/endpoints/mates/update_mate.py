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
from server.api.validation.validate_file_access import validate_file_access


async def update_mate_processing(
        mate_username: str,
        new_name: Optional[str] = None,
        new_username: Optional[str] = None,
        new_description: Optional[str] = None,
        new_profile_picture_url: Optional[str] = None,
        new_default_systemprompt: Optional[str] = None,
        new_default_skills: Optional[List[int]] = None,
        new_custom_systemprompt: Optional[str] = None,
        new_custom_skills: Optional[List[int]] = None,
        team_url: Optional[str] = None,
        user_api_token: Optional[str] = None
    ) -> MateUpdateOutput:
    """
    Update a specific AI team mate on the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Update mate", state="start", color="yellow")
        add_to_log("Updating a specific AI team mate on the team ...")

        # TODO: implement processing

        if new_profile_picture_url:
            await validate_file_access(
                filename=new_profile_picture_url.split("/")[-1],
                team_url=team_url,
                user_api_token=user_api_token,
                scope="uploads:read"
                )

        return JSONResponse(status_code=200, content={"message": "AI team mate updated successfully."})
    
    except Exception:
        process_error("Failed to update the AI team mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to update the AI team mate.")