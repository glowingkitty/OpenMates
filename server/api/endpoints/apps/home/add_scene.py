from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_add_scene import (
    HomeAddSceneInput,
    HomeAddSceneOutput
)

logger = logging.getLogger(__name__)


async def add_scene(
    team_slug: str,
    api_token: str,
    input: HomeAddSceneInput
) -> HomeAddSceneOutput:
    try:
        logger.debug("Adding scene")

        # TODO add processing via MQTT

        logger.debug("Added scene")
        return HomeAddSceneOutput(success=True)
    except Exception:
        logger.exception("Error adding scene")
        raise HTTPException(status_code=500, detail="An error occurred while adding scene")
