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

from typing import List
from server.cms.strapi_requests import make_strapi_request, get_nested
from fastapi.responses import JSONResponse


async def get_mates_processing(team_url: str, page: int = 1, pageSize: int = 25) -> List[dict]:
    """
    Get a list of all AI team mates on a team
    """
    try:
        add_to_log(module_name="OpenMates | API | Get mates", state="start", color="yellow")
        add_to_log("Getting a list of all AI team mates in a team ...")

        fields = [
            "name",
            "username",
            "description",
            "default_systemprompt"
        ]
        populate = [
            "profile_picture.url",
            "skills.name",
            "skills.description",
            "skills.slug",
            "skills.software.name",
            "skills.software.slug"
        ]
        filters = [
            {
                "field": "teams.slug",
                "operator": "$eq",
                "value": team_url
            }
        ]
        status_code, json_response = await make_strapi_request(
            method='get', 
            endpoint='mates', 
            fields=fields, 
            populate=populate, 
            filters=filters,
            page=page,
            pageSize=pageSize,
            )

        if status_code == 200:
            mates = [
                {
                    "id": get_nested(mate, ["id"]),
                    "name": get_nested(mate, ["attributes", "name"]),
                    "username": get_nested(mate, ["attributes", "username"]),
                    "description": get_nested(mate, ['attributes', 'description']),
                    "profile_picture_url": f"/{team_url}{get_nested(mate, ['attributes', 'profile_picture', 'data', 'attributes', 'url'])}" if get_nested(mate, ['attributes', 'profile_picture']) else None,
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
                        } for skill in get_nested(mate, ['attributes', 'skills', 'data']) or []]
                } for mate in json_response["data"]
            ]
            
            json_response["data"] = mates

        add_to_log("Successfully created a list of all mates in the requested team.", state="success")
        return JSONResponse(status_code=status_code, content=json_response)

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        add_to_log(traceback.format_exc())
        # process_error("Failed to get a list of all mates in the team.", traceback=traceback.format_exc())
        return []