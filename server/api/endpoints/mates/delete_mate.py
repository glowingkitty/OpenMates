from typing import Optional
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from server.cms.cms import make_strapi_request
from server.api.endpoints.mates.get_mate import get_mate

import logging

logger = logging.getLogger(__name__)


async def delete_mate(
        mate_username: str,
        team_slug: Optional[str] = None,
        user_api_token: Optional[str] = None
    ) -> JSONResponse:
    """
    Delete a specific AI team mate from the team
    """
    try:
        logger.debug("Deleting a specific AI team mate from the team ...")

        # Get the mate to be deleted
        mate = await get_mate(
            team_slug=team_slug,
            mate_username=mate_username,
            user_api_token=user_api_token
        )

        # Delete the mate
        status_code, json_response = await make_strapi_request(
            method='delete',
            endpoint=f'mates/{mate["id"]}'
        )

        delete_mate = {
            "deleted_user": mate_username
        }

        if status_code == 200:
            logger.debug("Successfully deleted the AI team mate")
            return JSONResponse(status_code=200, content=delete_mate)
        else:
            logger.error("Failed to delete the AI team mate.")
            raise HTTPException(status_code=500, detail="Failed to delete the AI team mate.")

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to delete the AI team mate.")
        raise HTTPException(status_code=500, detail="Failed to delete the AI team mate.")