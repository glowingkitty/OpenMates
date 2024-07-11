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

from server.cms.strapi_requests import make_strapi_request, get_nested
from typing import Dict, Union, Literal
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.api.security.crypto import verify_hash

async def get_mate(
        team_slug: str,
        mate_username: str,
        user_api_token: str = None,
        include_populated_data: bool = False,
        output_raw_data: bool = True,
        output_format: Literal["JSONResponse", "dict"] = "dict"
    ) -> Union[JSONResponse, dict, HTTPException]:
    """
    Get a specific AI team mate on the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mate", state="start", color="yellow", hide_variables=True)
        add_to_log("Getting a specific AI team mate on the team ...")

        fields = [
            "name",
            "username",
            "description",
            "default_systemprompt",
            "default_llm_model"
        ]
        populate = []

        if include_populated_data:
            populate = [
                "default_llm_endpoint.slug",
                "default_llm_endpoint.software.slug",
                "profile_picture.file.url",
                "default_skills.name",
                "default_skills.description",
                "default_skills.slug",
                "default_skills.software.name",
                "default_skills.software.slug",
                "configs.systemprompt",
                "configs.llm_endpoint.slug",
                "configs.llm_endpoint.software.slug",
                "configs.llm_model",
                "configs.user.api_token",
                "configs.team.slug",
                "configs.skills.name",
                "configs.skills.description",
                "configs.skills.slug",
                "configs.skills.software.name",
                "configs.skills.software.slug",
                "configs.allowed_to_access_user_name",
                "configs.allowed_to_access_user_username",
                "configs.allowed_to_access_user_projects",
                "configs.allowed_to_access_user_goals",
                "configs.allowed_to_access_user_todos",
                "configs.allowed_to_access_user_recent_topics",
                "configs.allowed_to_access_user_recent_emails",
                "configs.allowed_to_access_user_calendar",
                "configs.allowed_to_access_user_likes",
                "configs.allowed_to_access_user_dislikes"
            ]

        filters = [
            # The mate must be active on the team
            {
                "field": "teams.slug",
                "operator": "$eq",
                "value": team_slug
            },
            # The mate must have the requested mate username
            {
                "field": "username",
                "operator": "$eq",
                "value": mate_username
            }
        ]

        status_code, json_response = await make_strapi_request(
            method='get',
            endpoint='mates',
            fields=fields,
            populate=populate,
            filters=filters
            )

        if status_code == 200:
            # make sure there is only one mate with the requested username
            mate = {}
            mates = json_response["data"]
            if len(mates) == 0:
                status_code = 404
                json_response = {"detail": "Could not find the requested mate. Make sure the team URL is correct and the mate is active on the team."}
            elif len(mates) > 1:
                status_code = 404
                json_response = {"detail": "There are multiple mates with the requested username. Please contact the team owner."}
            else:
                mate = mates[0]

                # return the unprocessed json if requested
                if output_raw_data:
                    if output_format == "JSONResponse":
                        return JSONResponse(status_code=status_code, content=mate)
                    else:
                        return mate

                # check if a custom config exists
                if user_api_token and len(get_nested(mate, "configs"))>0:
                    matching_config = [config for config in get_nested(mate, "configs") if get_nested(config, "team.slug") == team_slug and verify_hash(get_nested(config, "user.api_token"),user_api_token[32:])]
                    if len(matching_config) == 1:
                        mate["attributes"]["config"] = matching_config[0]
                else:
                    mate["attributes"]["config"] = None

                llm_skill_slug = get_nested(mate, "config.llm_endpoint.slug") or get_nested(mate, "default_llm_endpoint.slug")
                llm_skill_software_slug = get_nested(mate, "config.llm_endpoint.software.slug") or get_nested(mate, "default_llm_endpoint.software.slug")

                mate = {
                        "id": get_nested(mate, "id"),
                        "name": get_nested(mate, "name"),
                        "username": get_nested(mate, "name").lower().replace(" ", "_"),
                        "description": get_nested(mate, "description"),
                        "profile_picture_url": f"/v1/{team_slug}{get_nested(mate, 'profile_picture.file.url')}" if get_nested(mate, "profile_picture") else None,
                        "llm_endpoint": f"/v1/{team_slug}/skills/{llm_skill_software_slug}/{llm_skill_slug}",
                        "llm_model": get_nested(mate, "config.llm_model") or get_nested(mate, "default_llm_model"),
                        "systemprompt": get_nested(mate, "config.systemprompt") or get_nested(mate, "default_systemprompt"),
                        "skills": [
                            {
                                "id": get_nested(skill, "id"),
                                "name": get_nested(skill, "name"),
                                "description": get_nested(skill, "description"),
                                "software":{
                                    "id": get_nested(skill, "software.id"),
                                    "name": get_nested(skill, "software.name"),
                                },
                                "api_endpoint": f"/v1/{team_slug}/skills/{get_nested(skill, 'software.slug')}/{get_nested(skill, 'slug')}",
                            } for skill in (get_nested(mate, "config.skills") or get_nested(mate, "default_skills"))
                        ],
                        "allowed_to_access_user_data":{
                            "name": True if get_nested(mate, "config.allowed_to_access_user_name") else False,
                            "username": True if get_nested(mate, "config.allowed_to_access_user_username") else False,
                            "projects": True if get_nested(mate, "config.allowed_to_access_user_projects") else False,
                            "goals": True if get_nested(mate, "config.allowed_to_access_user_goals") else False,
                            "todos": True if get_nested(mate, "config.allowed_to_access_user_todos") else False,
                            "recent_topics": True if get_nested(mate, "config.allowed_to_access_user_recent_topics") else False,
                            "recent_emails": True if get_nested(mate, "config.allowed_to_access_user_recent_emails") else False,
                            "calendar": True if get_nested(mate, "config.allowed_to_access_user_calendar") else False,
                            "likes": True if get_nested(mate, "config.allowed_to_access_user_likes") else False,
                            "dislikes": True if get_nested(mate, "config.allowed_to_access_user_dislikes") else False,
                        },
                        "custom_config_id": get_nested(mate, "config.id") if get_nested(mate, "config") else None,
                        "llm_endpoint_is_customized": True if get_nested(mate, "config.llm_endpoint") else False,
                        "llm_model_is_customized": True if get_nested(mate, "config.llm_model") else False,
                        "systemprompt_is_customized": True if get_nested(mate, "config.systemprompt") else False,
                        "skills_are_customized": True if get_nested(mate, "config.skills") else False
                    }

                json_response = mate


                add_to_log("Successfully got the mate.", state="success")

        if status_code == 404:
            add_to_log("Could not find the requested mate.", state="error")

        if output_format == "JSONResponse":
            return JSONResponse(status_code=status_code, content=json_response)
        else:
            return json_response

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to get the requested mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the requested mate.")