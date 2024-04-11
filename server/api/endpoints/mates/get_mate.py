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

async def get_mate_processing(team_url: str, mate_username: str) -> Mate:
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
            },
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
            mates = [
                {
                    "id": get_nested(mate, ["id"]),
                    "name": get_nested(mate, ["attributes", "name"]),
                    "username": get_nested(mate, ["attributes", "name"]).lower().replace(" ", "_"),
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

            if len(mates) == 0:
                add_to_log("The requested mate does not exist.", state="error")
                status_code = 404
                json_response = {"detail": "The requested mate does not exist or is not active on the team."}
            else:
                json_response = mates[0] 

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