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

        # get the mate ID
        status_code, json_response = await make_strapi_request(
            method='get', 
            endpoint='mates', 
            filters=[{"field": "username", "operator": "$eq", "value": mate_username}]
        )
        if status_code == 200 and json_response["data"]:
            if len(json_response["data"]) == 1:
                mated_id = json_response["data"][0]["id"]
            elif len(json_response["data"]) > 1:
                raise HTTPException(status_code=400, detail="There are multiple mates with the same username.")
        else:
            raise HTTPException(status_code=404, detail="The AI team mate was not found.")

        if new_username:
            # check if the username is already taken
            await validate_mate_username(username=new_username)

        if new_profile_picture_url:
            new_profile_picture = await validate_file_access(
                filename=new_profile_picture_url.split("/")[-1],
                team_url=team_url,
                user_api_token=user_api_token,
                scope="uploads:read"
                )
        else:
            new_profile_picture = None

        if new_default_skills:
            new_default_skills_extended_data = await validate_skills(
                skills=new_default_skills,
                team_url=team_url
                )
        else:
            new_default_skills_extended_data = None
        
        if new_custom_skills:
            new_custom_skills_extended_data = await validate_skills(
                skills=new_custom_skills,
                team_url=team_url
                )
        else:
            new_custom_skills_extended_data = None


        # prepare to make the patch request to strapi
        updated_mate = {}

        if new_name:
            updated_mate["name"] = new_name
        if new_username:
            updated_mate["username"] = new_username
        if new_description:
            updated_mate["description"] = new_description
        if new_profile_picture:
            updated_mate["profile_picture"] = new_profile_picture["id"]
        if new_default_systemprompt:
            updated_mate["default_systemprompt"] = new_default_systemprompt
        if new_default_skills_extended_data:
            updated_mate["default_skills"] = new_default_skills
        if new_custom_systemprompt:
            updated_mate["custom_systemprompt"] = new_custom_systemprompt
        if new_custom_skills_extended_data:
            updated_mate["custom_skills"] = new_custom_skills

        # TODO make sure that if a field is not supported, it shows an error
        # TODO make sure that if default_skills field is set to empty, it will remove the default skills
        # TODO process updating custom systemprompt and custom skills via config

        # make the patch request
        status_code, json_response = await make_strapi_request(
            method='put', 
            endpoint='mates/'+str(mated_id), 
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