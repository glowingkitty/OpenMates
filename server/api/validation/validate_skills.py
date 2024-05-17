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

from fastapi import HTTPException
from server.cms.strapi_requests import make_strapi_request
from typing import List, Optional


async def validate_skills(
        skills: List[int],
        team_slug: Optional[str] = None
        ) -> List[dict]:
    """
    Validate if the skills exist with their ID
    """
    try:
        add_to_log(module_name="OpenMates | API | Validate skills", state="start", color="yellow", hide_variables=True)
        add_to_log("Validating if the skills exist with their ID ...")

        # check if the skills exist with their ID
        # return the skills from the strapi request, so they can be included with their details later in the API response
        fields = [
            "id",
            "name",
            "description",
            "slug"
        ]
        populate = [
            "software.id",
            "software.name",
            "software.slug"
        ]

        output_skills = []

        for skill in skills:
            add_to_log(f"Validating skill with ID {skill} ...")
            skill_data = {
                "id": skill,
            }
            filters = [
                {
                    "field": "id",
                    "operator": "$eq",
                    "value": skill
                }
            ]

            status_code, skill_json_response = await make_strapi_request(
                method='get',
                endpoint='skills',
                fields=fields,
                populate=populate,
                filters=filters
            )

            if status_code == 200 and len(skill_json_response["data"])>0:
                add_to_log(f"Skill with ID {skill} exists.")

                skill_data["name"] = skill_json_response["data"][0]["attributes"]["name"]
                skill_data["description"] = skill_json_response["data"][0]["attributes"]["description"]
                skill_data["software"] = {}
                skill_data["software"]["id"] = skill_json_response["data"][0]["attributes"]["software"]["data"]["id"]
                skill_data["software"]["name"] = skill_json_response["data"][0]["attributes"]["software"]["data"]["attributes"]["name"]
                skill_data["api_endpoint"] = f"/{team_slug}/skills/{skill_json_response['data'][0]['attributes']['software']['data']['attributes']['slug']}/{skill_json_response['data'][0]['attributes']['slug']}"

                output_skills.append(skill_data)

            if status_code != 200 or len(skill_json_response["data"])==0:
                add_to_log(f"Skill with ID {skill} does not exist.")
                raise HTTPException(status_code=400, detail=f"Skill with ID {skill} does not exist.")

        return output_skills

    except HTTPException:
        raise

    except Exception:
        process_error("Failed to validate the skills.", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to validate the skills.")