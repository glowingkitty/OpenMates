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

async def get_mate(
        team_slug: str,
        mate_username: str,
        user_api_token: str = None,
        include_populated_data: bool = False,
        output_raw_data: bool = True,
        output_format: Literal["JSONResponse", "dict"] = "dict"
    ) -> Union[JSONResponse, Dict, HTTPException]:
    """
    Get a specific AI team mate on the team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mate", state="start", color="yellow")
        add_to_log("Getting a specific AI team mate on the team ...")

        fields = [
            "name",
            "username",
            "description",
            "default_systemprompt"
        ]
        populate = []

        if include_populated_data:
            populate = [
                "profile_picture.file.url",
                "default_skills.name",
                "default_skills.description",
                "default_skills.slug",
                "default_skills.software.name",
                "default_skills.software.slug",
                "configs.systemprompt",
                "configs.user.api_token",
                "configs.team.slug",
                "configs.skills.name",
                "configs.skills.description",
                "configs.skills.slug",
                "configs.skills.software.name",
                "configs.skills.software.slug"
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
                if user_api_token and len(mate["attributes"]["configs"]["data"])>0:
                    matching_config = [config for config in get_nested(mate, ["attributes", "configs"])["data"] if get_nested(config, ["attributes", "team", "data", "attributes", "slug"]) == team_slug and get_nested(config, ["attributes", "user", "data", "attributes", "api_token"]) == user_api_token]
                    if len(matching_config) == 1:
                        mate["attributes"]["config"] = matching_config[0]
                else:
                    mate["attributes"]["config"] = None

                mate = {
                        "id": get_nested(mate, ["id"]),
                        "name": get_nested(mate, ["attributes", "name"]),
                        "username": get_nested(mate, ["attributes", "name"]).lower().replace(" ", "_"),
                        "description": get_nested(mate, ['attributes', 'description']),
                        "profile_picture_url": f"/{team_slug}{get_nested(mate, ['attributes', 'profile_picture', 'data', 'attributes', 'file','data','attributes','url'])}" if get_nested(mate, ['attributes', 'profile_picture']) else None,
                        "systemprompt": get_nested(mate, ['attributes', 'config','attributes', 'systemprompt']) or get_nested(mate, ['attributes', 'default_systemprompt']),
                        "systemprompt_is_customized": True if get_nested(mate, ['attributes', 'config','attributes', 'systemprompt']) else False,
                        "skills": [
                            {
                                "id": get_nested(skill, ['id']),
                                "name": get_nested(skill, ['attributes', 'name']),
                                "description": get_nested(skill, ['attributes', 'description']),
                                "software":{
                                    "id": get_nested(skill, ['attributes', 'software', 'data', 'id']),
                                    "name": get_nested(skill, ['attributes', 'software', 'data', 'attributes', 'name']),
                                },
                                "api_endpoint": f"/{team_slug}/skills/{get_nested(skill, ['attributes', 'software', 'data', 'attributes', 'slug'])}/{get_nested(skill, ['attributes', 'slug'])}",
                            } for skill in (get_nested(mate, ['attributes','config', 'attributes','skills', 'data']) or get_nested(mate, ['attributes', 'default_skills', 'data']))
                        ],
                        "skills_are_customized": True if get_nested(mate, ['attributes','config', 'attributes','skills', 'data']) else False
                    }

                json_response = mate


        add_to_log("Successfully got the mate.", state="success")
        if output_format == "JSONResponse":
            return JSONResponse(status_code=status_code, content=json_response)
        else:
            return json_response

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to get the requested mate.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get the requested mate.")