from server.cms.cms import make_strapi_request, get_nested
from typing import Dict, Union, Optional
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from typing import Literal
import logging

# Set up logger
logger = logging.getLogger(__name__)


async def get_skill(
        id: Optional[int] = None,
        app_slug: Optional[str] = None,
        skill_slug: Optional[str] = None,
        team_slug: Optional[str] = None,
        include_populated_data: bool = False,
        output_raw_data: bool = False,
        output_format: Literal["JSONResponse", "dict"] = "dict"
    ) -> Union[JSONResponse, dict, HTTPException]:
        """
        Get a specific skill
        """
        try:
            logger.debug("Getting a specific skill ...")

            if id is None and (app_slug is None or skill_slug is None):
                raise HTTPException(status_code=400, detail="Either id or app_slug and skill_slug must be provided")

            fields = [
                "name",
                "description",
                "slug",
                "processing",
                "free",
                "pricing",
                "is_llm_endpoint",
                "is_llm_endpoint_and_supports_tool_selection",
                "default_skill_settings"
            ]

            populate = []

            if include_populated_data:
                populate = [
                    "icon.file.url",
                    "app.name",
                    "app.slug",
                    "app.icon.file.url"
                ]

            filters = []

            if id is not None:
                filters.append({
                    "field": "id",
                    "operator": "$eq",
                    "value": id
                })

            if app_slug is not None and skill_slug is not None:
                filters.append({
                    "field": "app.slug",
                    "operator": "$eq",
                    "value": app_slug
                })
                filters.append({
                    "field": "slug",
                    "operator": "$eq",
                    "value": skill_slug
                })

            # TODO can't get this to work
            # if team_slug is not None:
            #     filters.append({
            #         "field": "not_allowed_in_teams.slug",
            #         "operator": "$notContains",
            #         "value": team_slug
            #     })

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

                    icon_url = get_nested(skill, 'icon.file.url')
                    app_icon_url = get_nested(skill, 'app.icon.file.url')

                    skill = {
                        "id": get_nested(skill, "id"),
                        "api_endpoint": f"/v1/{team_slug}/skills/{get_nested(skill, 'app.slug')}/{get_nested(skill, 'slug')}",
                        "name": get_nested(skill, "name"),
                        "description": get_nested(skill, "description"),
                        "slug": get_nested(skill, "slug"),
                        "icon_url": f"/v1/{team_slug}{icon_url}" if icon_url else None,
                        "app": {
                            "id": get_nested(skill, "app.id"),
                            "name": get_nested(skill, "app.name"),
                            "slug": get_nested(skill, "app.slug"),
                            "icon_url": f"/v1/{team_slug}{app_icon_url}" if app_icon_url else None,
                        },
                        "processing": ["cloud", "local"] if get_nested(skill, "processing") == "localORcloud" else [get_nested(skill, "processing")],
                        "free": get_nested(skill, "free"),
                        "pricing": get_nested(skill, "pricing"),
                        "is_llm_endpoint": get_nested(skill, "is_llm_endpoint"),
                        "is_llm_endpoint_and_supports_tool_selection": get_nested(skill, "is_llm_endpoint_and_supports_tool_selection"),
                        "default_skill_settings": get_nested(skill, "default_skill_settings")
                    }

                    json_response = skill


                    logger.debug("Successfully got the skill.")

            if status_code == 404:
                logger.error("Could not find the requested skill.")

            if output_format == "JSONResponse":
                return JSONResponse(status_code=status_code, content=json_response)
            else:
                return json_response

        except HTTPException:
            raise

        except Exception:
            logger.exception("Failed to get the requested skill.")
            raise HTTPException(status_code=500, detail="Failed to get the requested skill.")
