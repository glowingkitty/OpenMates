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
from server.api.validation.validate_mate_username import validate_mate_username
from server.api.validation.validate_skills import validate_skills
from server.api.endpoints.mates.get_mate import get_mate_processing
from server.api.endpoints.mates.update_or_create_config import update_or_create_config

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
        add_to_log(module_name="OpenMates | API | Update mate", state="start", color="yellow", hide_variables=True)
        add_to_log("Updating a specific AI team mate on the team ...")

        # validate the values
        if new_username != None:
            await validate_mate_username(username=new_username)

        new_profile_picture = await validate_file_access(
            filename=new_profile_picture_url.split("/")[-1],
            team_url=team_url,
            user_api_token=user_api_token,
            scope="uploads:read"
            ) if new_profile_picture_url!=None else None

        new_default_skills_extended_data = await validate_skills(
            skills=new_default_skills,
            team_url=team_url
            ) if new_default_skills!=None else None
        
        new_custom_skills_extended_data = await validate_skills(
            skills=new_custom_skills,
            team_url=team_url
            ) if new_custom_skills!=None else None
        
        # prepare to make the patch request to strapi
        updated_mate = {}

        if new_name != None:
            updated_mate["name"] = new_name
        if new_username != None:
            updated_mate["username"] = new_username
        if new_description != None:
            updated_mate["description"] = new_description
        if new_profile_picture != None:
            updated_mate["profile_picture"] = new_profile_picture["id"]
        if new_default_systemprompt != None:
            updated_mate["default_systemprompt"] = new_default_systemprompt
        if new_default_skills_extended_data != None:
            updated_mate["default_skills"] = new_default_skills_extended_data

        # get the mate
        mate = await get_mate_processing(
            team_url=team_url,
            mate_username=mate_username,
            user_api_token=user_api_token,
            output_raw_data=True,
            output_format="json"
        )

        # TODO process updating custom systemprompt and custom skills via config

        # if any of the custom fields are updated, find first the matching config database entry
        # for the combination of the user, team, and mate
        if new_custom_systemprompt != None or new_custom_skills_extended_data != None:
            await update_or_create_config(
                mate=mate,
                team_url=team_url, 
                user_api_token=user_api_token, 
                systemprompt=new_custom_systemprompt,
                skills=new_custom_skills
                )
            
            if new_custom_systemprompt != None:
                updated_mate["custom_systemprompt"] = new_custom_systemprompt
            if new_custom_skills_extended_data != None:
                updated_mate["custom_skills"] = new_custom_skills_extended_data

        # TODO make sure that config_id is inside the configs field of the mate, else add it and patch the mate
        # TODO make sure the config_id or configs are not included in the response

        # make the patch request
        status_code, json_response = await make_strapi_request(
            method='put', 
            endpoint='mates/'+str(mate["id"]), 
            data={"data":updated_mate}
        )

        # return updated fields
        if status_code == 200 and json_response["data"]:
            updated_response = {
                "id": json_response["data"]["id"],
                "username": json_response["data"]["attributes"]["username"],
                "updated_fields": updated_mate
            }
            return JSONResponse(status_code=200, content=updated_response)
        else:
            raise HTTPException(status_code=500, detail="Failed to update the AI team mate.")

    except HTTPException:
        raise
    
    except Exception:
        process_error("Failed to update the AI team mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to update the AI team mate.")