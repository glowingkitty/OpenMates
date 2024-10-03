from typing import List, Optional, Union
from server.api.models.mates.mates_create import MatesCreateOutput
from server.cms.cms import make_strapi_request
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.endpoints.apps.get_skill import get_skill
from server.api.security.validation.validate_permissions import validate_permissions
from server.api.security.validation.validate_mate_username import validate_mate_username
from server.api.security.validation.validate_skills import validate_skills

import logging

logger = logging.getLogger(__name__)


async def create_mate(
        name: str,
        username: str,
        description: str,
        profile_image: str,
        default_systemprompt: str,
        default_llm_endpoint: str,
        default_llm_model: str,
        default_skills: List[Union[int, str]],
        team_slug: Optional[str] = None,
        user_api_token: Optional[str] = None
    ) -> MatesCreateOutput:
    """
    Create a new AI team mate on the team
    """
    try:
        logger.debug("Creating a new AI team mate on the server and adding it to the team ...")

        # check if the username is already taken
        await validate_mate_username(username=username)

        # check if the profile picture exists and the user has access to it
        profile_picture = await validate_permissions(
            endpoint=f"/uploads/{profile_image.split('/')[-1]}",
            user_api_token=user_api_token,
            user_api_token_already_checked=True,
            team_slug=team_slug
        )

        # check if the skills exist with their ID
        if default_skills:
            # Process default_skills to ensure they are all integers
            default_skills_ids = []
            for skill in default_skills:
                if isinstance(skill, int):
                    default_skills_ids.append(skill)
                elif isinstance(skill, str):
                    # Fetch skill ID based on the API endpoint
                    skill_data = await get_skill(skill_slug=skill.split('/')[-1], app_slug=skill.split('/')[-2])
                    if isinstance(skill_data, dict) and 'id' in skill_data:
                        default_skills_ids.append(skill_data['id'])
                    else:
                        raise HTTPException(status_code=400, detail=f"Skill not found for endpoint: {skill}")
            default_skills = default_skills_ids
            default_skills_extended_data = await validate_skills(
                skills=default_skills,
                team_slug=team_slug
                )

        # get the team and its ID
        status_code, json_response = await make_strapi_request(
            method='get',
            endpoint='teams',
            filters=[{"field": "slug", "operator": "$eq", "value": team_slug}]
        )
        if status_code == 200 and json_response["data"]:
            if len(json_response["data"])==1:
                team = json_response["data"][0]
            elif len(json_response["data"])>1:
                logger.error("More than one team found with the same URL.")
                raise HTTPException(status_code=500, detail="More than one team found with the same URL.")

        else:
            logger.error("No team found with the given URL.")
            raise HTTPException(status_code=404, detail="No team found with the given URL.")

        # add default_llm_endpoint as linked skill
        # Split the endpoint to handle both formats
        endpoint_parts = default_llm_endpoint.split('/')

        # Determine the app_slug and skill_slug based on the format
        if len(endpoint_parts) == 4:  # Format: /apps/{app_slug}/ask
            app_slug = endpoint_parts[2]
            skill_slug = endpoint_parts[3]
        elif len(endpoint_parts) >= 5 and endpoint_parts[1] == 'v1':  # Format: /v1/{team_slug}/apps/{app_slug}/ask
            app_slug = endpoint_parts[-2]  # second last part
            skill_slug = endpoint_parts[-1]      # last part
        else:
            raise ValueError("Invalid default_llm_endpoint format")

        default_llm_endpoint_skill = await get_skill(
            app_slug=app_slug,
            skill_slug=skill_slug,
            output_raw_data=True
        )

        if not isinstance(default_llm_endpoint_skill, dict) or 'id' not in default_llm_endpoint_skill:
            logger.error(f"Unexpected response from get_skill: {default_llm_endpoint_skill}")
            raise HTTPException(status_code=500, detail="Failed to retrieve LLM endpoint skill")

        # add default_llm_endpoint skill to default_llm_endpoint
        default_llm_endpoint_id = default_llm_endpoint_skill["id"]

        # create the AI team mate
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
                    "default_llm_endpoint": default_llm_endpoint_id,
                    "default_llm_model": default_llm_model,
                    "teams": [team["id"]],
                }
            }
        )

        # return the created mate and the details
        created_mate = {
            "id": json_response["data"]["id"],
            "name": name,
            "username": username,
            "description": description,
            "profile_image": profile_image,
            "default_systemprompt": default_systemprompt,
            "default_skills": default_skills_extended_data,
            "default_llm_endpoint": default_llm_endpoint,
            "default_llm_model": default_llm_model,
        }

        if status_code == 200:
            logger.debug("Successfully created the AI team mate")
            return JSONResponse(status_code=201, content=created_mate)
        else:
            logger.error("Failed to create the AI team mate.")
            raise HTTPException(status_code=500, detail="Failed to create the AI team mate.")

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to create the AI team mate.")
        raise HTTPException(status_code=500, detail="Failed to create the AI team mate.")