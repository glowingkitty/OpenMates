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

from typing import List, Optional
from server.api.models.mates.mates_update import MatesUpdateOutput
from server.cms.cms import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.security.validation.validate_permissions import validate_permissions
from server.api.security.validation.validate_mate_username import validate_mate_username
from server.api.security.validation.validate_skills import validate_skills
from server.api.endpoints.mates.get_mate import get_mate
from server.api.endpoints.mates.update_or_create_config import update_or_create_config
from server.api.endpoints.skills.get_skill import get_skill


async def update_mate(
        mate_username: str,
        new_name: Optional[str] = None,
        new_username: Optional[str] = None,
        new_description: Optional[str] = None,
        new_profile_image: Optional[str] = None,
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
            endpoint=f"/uploads/{new_profile_image.split('/')[-1]}",
            user_api_token=user_api_token,
            user_api_token_already_checked=True,
            team_slug=team_slug
        ) if new_profile_image!=None else None

        # Process new_default_skills to ensure they are all integers
        if new_default_skills != None:
            new_default_skills_ids = []
            for skill in new_default_skills:
                if isinstance(skill, int):
                    new_default_skills_ids.append(skill)
                elif isinstance(skill, str):
                    # Fetch skill ID based on the API endpoint
                    skill_data = await get_skill(skill_slug=skill.split('/')[-1], software_slug=skill.split('/')[-2])
                    if isinstance(skill_data, dict) and 'id' in skill_data:
                        new_default_skills_ids.append(skill_data['id'])
                    else:
                        raise HTTPException(status_code=400, detail=f"Skill not found for endpoint: {skill}")
            new_default_skills = new_default_skills_ids


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
        if new_default_llm_model != None:
            updated_mate["default_llm_model"] = new_default_llm_model
        if new_default_llm_endpoint is not None:
            endpoint_parts = new_default_llm_endpoint.split('/')

            if len(endpoint_parts) == 4:  # Format: /skills/{software_slug}/ask
                software_slug = endpoint_parts[2]
                skill_slug = endpoint_parts[3]
            elif len(endpoint_parts) >= 5 and endpoint_parts[1] == 'v1':  # Format: /v1/{team_slug}/skills/{software_slug}/ask
                software_slug = endpoint_parts[-2]
                skill_slug = endpoint_parts[-1]
            else:
                raise ValueError("Invalid default_llm_endpoint format")

            default_llm_endpoint_skill = await get_skill(
                software_slug=software_slug,
                skill_slug=skill_slug,
                output_raw_data=True
            )

            if not isinstance(default_llm_endpoint_skill, dict) or 'id' not in default_llm_endpoint_skill:
                add_to_log(f"Unexpected response from get_skill: {default_llm_endpoint_skill}", state="error")
                raise HTTPException(status_code=500, detail="Failed to retrieve LLM endpoint skill")

            updated_mate["default_llm_endpoint"] = {
                "id": default_llm_endpoint_skill["id"],
                "api_endpoint": new_default_llm_endpoint,
                "description": default_llm_endpoint_skill["attributes"]["description"]
            }
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
        if updated_mate=={}:
            raise HTTPException(status_code=400, detail="There are no fields to update.")

        status_code, json_response = await make_strapi_request(
            method='put',
            endpoint='mates/'+str(mate["id"]),
            data={"data":updated_mate}
        )

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
        add_to_log(state="error", message=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to update the AI team mate.")