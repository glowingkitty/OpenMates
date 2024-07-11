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
            "slug",
            "requires_cloud_to_run",
            "is_llm_endpoint",
            "is_llm_endpoint_and_supports_tool_selection"
        ]
        populate = [
            "icon.file.url",
            "software.id",
            "software.name",
            "software.slug",
            "software.icon.file.url",
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
                skill_data["slug"] = skill_json_response["data"][0]["attributes"]["slug"]
                skill_data["requires_cloud_to_run"] = skill_json_response["data"][0]["attributes"]["requires_cloud_to_run"]
                skill_data["is_llm_endpoint"] = skill_json_response["data"][0]["attributes"]["is_llm_endpoint"]
                skill_data["is_llm_endpoint_and_supports_tool_selection"] = skill_json_response["data"][0]["attributes"]["is_llm_endpoint_and_supports_tool_selection"]
                skill_data["icon_url"] = f"/v1/{team_slug}{skill_json_response['data'][0]['attributes']['icon']['data']['attributes']['file']['data']['attributes']['url']}"
                skill_data["software"] = {}
                skill_data["software"]["id"] = skill_json_response["data"][0]["attributes"]["software"]["data"]["id"]
                skill_data["software"]["name"] = skill_json_response["data"][0]["attributes"]["software"]["data"]["attributes"]["name"]
                skill_data["software"]["icon_url"] = f"/v1/{team_slug}{skill_json_response['data'][0]['attributes']['software']['data']['attributes']['icon']['data']['attributes']['file']['data']['attributes']['url']}"
                skill_data["software"]["slug"] = skill_json_response["data"][0]["attributes"]["software"]["data"]["attributes"]["slug"]
                skill_data["api_endpoint"] = f"/v1/{team_slug}/skills/{skill_json_response['data'][0]['attributes']['software']['data']['attributes']['slug']}/{skill_json_response['data'][0]['attributes']['slug']}"

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