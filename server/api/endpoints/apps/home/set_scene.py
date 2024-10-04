from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_set_scene import (
    HomeSetSceneInput,
    HomeSetSceneOutput
)

logger = logging.getLogger(__name__)


async def set_scene(
    team_slug: str,
    api_token: str,
    input: HomeSetSceneInput
) -> HomeSetSceneOutput:
    try:
        logger.debug("Setting scene")

        # TODO add processing via MQTT

        logger.debug("Set scene")
        return HomeSetSceneOutput(success=True)
    except Exception:
        logger.exception("Error setting scene")
        raise HTTPException(status_code=500, detail="An error occurred while setting scene")
