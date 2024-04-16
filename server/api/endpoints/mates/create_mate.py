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
from server.api.models.mates import MatesCreateOutput
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException


async def create_mate_processing(
        name: str,
        username: str,
        description: str,
        profile_picture_url: str,
        default_systemprompt: str,
        default_skills: List[int],
        team_url: Optional[str] = None,
    ) -> MatesCreateOutput:
    """
    Create a new AI team mate on the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Create mate", state="start", color="yellow")
        add_to_log("Creating a new AI team mate on the server and adding it to the team ...")

        # TODO: implement processing


        return JSONResponse(status_code=201, content={"message": "AI team mate created successfully."})

    except Exception:
        process_error("Failed to create the AI team mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to create the AI team mate.")