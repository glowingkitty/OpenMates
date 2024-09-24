from fastapi import HTTPException
from server.cms.cms import make_strapi_request, get_nested
from typing import List, Optional
import logging

# Set up logger
logger = logging.getLogger(__name__)


async def validate_skills(
        skills: List[int],
        team_slug: Optional[str] = None
        ) -> List[dict]:
    """
    Validate if the skills exist with their ID
    """
    try:
        logger.debug("Validating if the skills exist with their ID ...")

        # check if the skills exist with their ID
        # return the skills from the strapi request, so they can be included with their details later in the API response
        fields = [
            "id",
            "description",
            "slug"
        ]
        populate = [
            "software.slug"
        ]

        output_skills = []

        for skill in skills:
            logger.debug(f"Validating skill with ID {skill} ...")
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
                logger.debug(f"Skill with ID {skill} exists.")

                skill_data["description"] = get_nested(skill_json_response, "description")
                skill_data["api_endpoint"] = f"/v1/{team_slug}/skills/{get_nested(skill_json_response, 'software.slug')}/{get_nested(skill_json_response, 'slug')}"

                output_skills.append(skill_data)

            if status_code != 200 or len(skill_json_response["data"])==0:
                logger.debug(f"Skill with ID {skill} does not exist.")
                raise HTTPException(status_code=400, detail=f"Skill with ID {skill} does not exist.")

        return output_skills

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to validate the skills.")
        raise HTTPException(status_code=500, detail="Failed to validate the skills.")