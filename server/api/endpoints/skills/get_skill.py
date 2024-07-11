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
from typing import Dict, Union, Optional
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from typing import Literal


# TODO write test

async def get_skill(
        id: Optional[int] = None,
        endpoint: Optional[str] = None,
        team_slug: Optional[str] = None,
        include_populated_data: bool = False,
        output_raw_data: bool = False,
        output_format: Literal["JSONResponse", "dict"] = "dict"
    ) -> Union[JSONResponse, dict, HTTPException]:
        """
        Get a specific skill
        """
        try:
            add_to_log(module_name="OpenMates | API | Get skill", state="start", color="yellow", hide_variables=True)
            add_to_log("Getting a specific skill ...")

            if id is None and endpoint is None:
                raise HTTPException(status_code=400, detail="Either id or endpoint must be provided")

            fields = [
                "name",
                "description",
                "slug",
                "requires_cloud_to_run",
                "is_llm_endpoint",
                "is_llm_endpoint_and_supports_tool_selection"
            ]

            populate = []

            if include_populated_data:
                populate = [
                    "icon.file.url",
                    "software.name",
                    "software.slug",
                    "software.icon.file.url"
                ]

            filters = []

            if id is not None:
                filters.append({
                    "field": "id",
                    "operator": "eq",
                    "value": id
                })

            if endpoint is not None:
                filters.append({
                    "field": "endpoint",
                    "operator": "eq",
                    "value": endpoint
                })

            if team_slug is not None:
                filters.append({
                    "field": "team.slug",
                    "operator": "eq",
                    "value": team_slug
                })

            status_code, response = await make_strapi_request(
                method='get',
                endpoint='skills',
                fields=fields,
                populate=populate,
                filters=filters
            )

            if status_code == 200:
                # make sure there is only one skill
                skill = {}
                skills = response["data"]
                if len(skills) == 0:
                    status_code = 404
                    json_response = {"detail": "Could not find the requested skill. Make sure the team URL is correct and the skill is active on the team."}
                elif len(skills) > 1:
                    status_code = 404
                    json_response = {"detail": "There are multiple skills with the requested endpoint. Please contact the team owner."}
                else:
                    skill = skills[0]

                    # return the unprocessed json if requested
                    if output_raw_data:
                        if output_format == "JSONResponse":
                            return JSONResponse(status_code=status_code, content=skill)
                        else:
                            return skill

                    skill = {
                        "id": get_nested(skill, ["id"]),
                        "name": get_nested(skill, ["attributes", "name"]),
                        "description": get_nested(skill, ["attributes", "description"]),
                        "slug": get_nested(skill, ["attributes", "slug"]),
                        "requires_cloud_to_run": get_nested(skill, ["attributes", "requires_cloud_to_run"]),
                        "is_llm_endpoint": get_nested(skill, ["attributes", "is_llm_endpoint"]),
                        "is_llm_endpoint_and_supports_tool_selection": get_nested(skill, ["attributes", "is_llm_endpoint_and_supports_tool_selection"]),
                        "icon_url": get_nested(skill, ["attributes", "icon", "data", "attributes", "url"]),
                        "software": {
                            "name": get_nested(skill, ["attributes", "software", "name"]),
                            "slug": get_nested(skill, ["attributes", "software", "slug"]),
                            "icon_url": get_nested(skill, ["attributes", "software", "icon", "data", "attributes", "url"]),
                        }
                    }

                    json_response = skill


            add_to_log("Successfully got the skill.", state="success")
            if output_format == "JSONResponse":
                return JSONResponse(status_code=status_code, content=json_response)
            else:
                return json_response

        except HTTPException:
            raise

        except Exception:
            process_error("Failed to get the requested skill.", traceback=traceback.format_exc())
            raise HTTPException(status_code=500, detail="Failed to get the requested skill.")