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
from server.api.models.mates.mates_update import MatesUpdateOutput
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.validation.validate_permissions import validate_permissions
from server.api.validation.validate_mate_username import validate_mate_username
from server.api.validation.validate_skills import validate_skills
from server.api.endpoints.mates.get_mate import get_mate
from server.api.endpoints.mates.update_or_create_config import update_or_create_config


async def update_mate(
        mate_username: str,
        new_name: Optional[str] = None,
        new_username: Optional[str] = None,
        new_description: Optional[str] = None,
        new_profile_picture_url: Optional[str] = None,
        new_default_systemprompt: Optional[str] = None,
        new_default_llm_endpoint: Optional[str] = None,
        new_default_llm_model: Optional[str] = None,
        new_default_skills: Optional[List[int]] = None,
        new_custom_systemprompt: Optional[str] = None,
        new_custom_llm_endpoint: Optional[str] = None,
        new_custom_llm_model: Optional[str] = None,
        new_custom_skills: Optional[List[int]] = None,
        team_slug: Optional[str] = None,
        user_api_token: Optional[str] = None,
        allowed_to_access_user_name: Optional[bool] = None,
        allowed_to_access_user_username: Optional[bool] = None,
        allowed_to_access_user_projects: Optional[bool] = None,
        allowed_to_access_user_goals: Optional[bool] = None,
        allowed_to_access_user_todos: Optional[bool] = None,
        allowed_to_access_user_recent_topics: Optional[bool] = None
    ) -> MatesUpdateOutput:
    """
    Update a specific AI team mate on the team
    """
    # TODO add llm endpoint and model
    # TODO update docs
    try:
        add_to_log(module_name="OpenMates | API | Update mate", state="start", color="yellow", hide_variables=True)
        add_to_log("Updating a specific AI team mate on the team ...")

        # validate the values
        if new_username != None:
            await validate_mate_username(username=new_username)

        new_profile_picture = await validate_permissions(
            endpoint=f"/uploads/{new_profile_picture_url.split('/')[-1]}",
            user_api_token=user_api_token,
            user_api_token_already_checked=True,
            team_slug=team_slug
        ) if new_profile_picture_url!=None else None

        new_default_skills_extended_data = await validate_skills(
            skills=new_default_skills,
            team_slug=team_slug
            ) if new_default_skills!=None else None

        new_custom_skills_extended_data = await validate_skills(
            skills=new_custom_skills,
            team_slug=team_slug
            ) if new_custom_skills!=None else None

        # TODO: later on, implement that server and team admins can prohibit certain LLM endpoints and models

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
        if new_default_llm_endpoint != None:
            updated_mate["default_llm_endpoint"] = new_default_llm_endpoint
        if new_default_llm_model != None:
            updated_mate["default_llm_model"] = new_default_llm_model

        # get the mate
        mate = await get_mate(
            team_slug=team_slug,
            mate_username=mate_username,
            user_api_token=user_api_token,
            include_populated_data=True
        )

        # if any of the custom fields are updated, find first the matching config database entry
        # for the combination of the user, team, and mate
        if new_custom_systemprompt != None \
            or new_custom_llm_endpoint != None \
            or new_custom_llm_model != None \
            or new_custom_skills_extended_data != None \
            or allowed_to_access_user_name != None \
            or allowed_to_access_user_username != None \
            or allowed_to_access_user_projects != None \
            or allowed_to_access_user_goals != None \
            or allowed_to_access_user_todos != None \
            or allowed_to_access_user_recent_topics != None:
            await update_or_create_config(
                mate=mate,
                team_slug=team_slug,
                user_api_token=user_api_token,
                systemprompt=new_custom_systemprompt,
                llm_endpoint=new_custom_llm_endpoint,
                llm_model=new_custom_llm_model,
                skills=new_custom_skills,
                allowed_to_access_user_name=allowed_to_access_user_name,
                allowed_to_access_user_username=allowed_to_access_user_username,
                allowed_to_access_user_projects=allowed_to_access_user_projects,
                allowed_to_access_user_goals=allowed_to_access_user_goals,
                allowed_to_access_user_todos=allowed_to_access_user_todos,
                allowed_to_access_user_recent_topics=allowed_to_access_user_recent_topics
                )

        # make the patch request
        status_code, json_response = await make_strapi_request(
            method='put',
            endpoint='mates/'+str(mate["id"]),
            data={"data":updated_mate}
        )

        if new_custom_systemprompt != None:
            updated_mate["custom_systemprompt"] = new_custom_systemprompt
        if new_custom_llm_endpoint != None:
            updated_mate["custom_llm_endpoint"] = new_custom_llm_endpoint
        if new_custom_llm_model != None:
            updated_mate["custom_llm_model"] = new_custom_llm_model
        if new_custom_skills_extended_data != None:
            updated_mate["custom_skills"] = new_custom_skills_extended_data
        if allowed_to_access_user_name != None:
            updated_mate["allowed_to_access_user_name"] = allowed_to_access_user_name
        if allowed_to_access_user_username != None:
            updated_mate["allowed_to_access_user_username"] = allowed_to_access_user_username
        if allowed_to_access_user_projects != None:
            updated_mate["allowed_to_access_user_projects"] = allowed_to_access_user_projects
        if allowed_to_access_user_goals != None:
            updated_mate["allowed_to_access_user_goals"] = allowed_to_access_user_goals
        if allowed_to_access_user_todos != None:
            updated_mate["allowed_to_access_user_todos"] = allowed_to_access_user_todos
        if allowed_to_access_user_recent_topics != None:
            updated_mate["allowed_to_access_user_recent_topics"] = allowed_to_access_user_recent_topics

        # return updated fields
        if status_code == 200 and json_response["data"]:
            updated_response = {
                "id": get_nested(json_response, "id"),
                "username": get_nested(json_response, "username"),
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