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
from server.cms.strapi_requests import make_strapi_request
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.validation.validate_file_access import validate_file_access
from server.api.validation.validate_mate_username import validate_mate_username
from server.api.validation.validate_skills import validate_skills


async def create_mate_processing(
        name: str,
        username: str,
        description: str,
        profile_picture_url: str,
        default_systemprompt: str,
        default_skills: List[int],
        team_url: Optional[str] = None,
        user_api_token: Optional[str] = None
    ) -> MatesCreateOutput:
    """
    Create a new AI team mate on the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Create mate", state="start", color="yellow", hide_variables=True)
        add_to_log("Creating a new AI team mate on the server and adding it to the team ...")

        # check if the username is already taken
        await validate_mate_username(username=username)

        # check if the profile picture exists and the user has access to it
        # TODO return file id
        profile_picture = await validate_file_access(
            filename=profile_picture_url.split("/")[-1],
            team_url=team_url,
            user_api_token=user_api_token,
            scope="uploads:read"
            )
        
        # check if the skills exist with their ID
        if default_skills:
            default_skills_extended_data = await validate_skills(
                skills=default_skills,
                team_url=team_url
                )

        # TODO: implement processing
        # TODO: profile picture file ID and team ID
        status_code, json_response = await make_strapi_request(
            method='post', 
            endpoint='mates', 
            data={
                "data":{
                    "name": name,
                    "username": username,
                    "description": description,
                    "profile_picture": profile_picture["id"],
                    "default_systemprompt": default_systemprompt,
                    "default_skills": default_skills,
                    "teams": [team_id],
                }
            }
        )

        add_to_log(json_response)

        if status_code == 201:
            add_to_log("Successfully created the AI team mate", state="success")


        return JSONResponse(status_code=201, content={"detail": "All good."})

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to create the AI team mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to create the AI team mate.")