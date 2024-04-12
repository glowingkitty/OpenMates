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

from server.api.models.mates import Mate
from typing import List
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse
from fastapi import HTTPException

async def get_mate_processing(team_url: str, mate_username: str, user_api_token: str) -> Mate:
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
        populate = [
            "profile_picture.url",
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
                "value": team_url
            },
            # The mate must have the requested mate username
            {
                "field": "username",
                "operator": "$eq",
                "value": mate_username
            },
            # The config of the mate must belong to the user who made the request
            {
                "field": "configs.user.api_token",
                "operator": "$eq",
                "value": user_api_token
            },
            # The config of the mate must belong to the team that was used in the request
            {
                "field": "configs.team.slug",
                "operator": "$eq",
                "value": team_url
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
                json_response = {"detail": "The requested mate does not exist or is not active on the team."}
            elif len(mates) > 1:
                status_code = 404
                json_response = {"detail": "There are multiple mates with the requested username. Please contact the team owner."}
            else:
                mate = mates[0]

            # matching_config = get_nested(mate, ["attributes", "configs"])
            matching_config = [config for config in get_nested(mate, ["attributes", "configs"])["data"] if get_nested(config, ["attributes", "team", "data", "attributes", "slug"]) == team_url and get_nested(config, ["attributes", "user", "data", "attributes", "api_token"]) == user_api_token]
            if len(matching_config) == 1:
                mate["attributes"]["config"] = matching_config[0]

            mate = {
                    "id": get_nested(mate, ["id"]),
                    "name": get_nested(mate, ["attributes", "name"]),
                    "username": get_nested(mate, ["attributes", "name"]).lower().replace(" ", "_"),
                    "description": get_nested(mate, ['attributes', 'description']),
                    "profile_picture_url": f"/{team_url}{get_nested(mate, ['attributes', 'profile_picture', 'data', 'attributes', 'url'])}" if get_nested(mate, ['attributes', 'profile_picture']) else None,
                    "systemprompt": get_nested(mate, ['attributes', 'config','attributes', 'systemprompt']),
                    "default_systemprompt": get_nested(mate, ['attributes', 'default_systemprompt']),
                    "skills": [{
                        "id": get_nested(skill, ['id']),
                        "name": get_nested(skill, ['attributes', 'name']),
                        "description": get_nested(skill, ['attributes', 'description']),
                        "software":{
                            "id": get_nested(skill, ['attributes', 'software', 'data', 'id']),
                            "name": get_nested(skill, ['attributes', 'software', 'data', 'attributes', 'name']),
                        },
                        "api_endpoint": f"/{team_url}/skills/{get_nested(skill, ['attributes', 'software', 'data', 'attributes', 'slug'])}/{get_nested(skill, ['attributes', 'slug'])}",
                        } for skill in get_nested(mate, ['attributes','config', 'attributes','skills', 'data']) or []]
                }

            json_response = mate


        add_to_log("Successfully created a list of all mates in the requested team.", state="success")
        return JSONResponse(status_code=status_code, content=json_response)

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get the requested mate.", traceback=traceback.format_exc())
        return []
    
if __name__ == "__main__":
    response = get_mate_processing()
    print(response)