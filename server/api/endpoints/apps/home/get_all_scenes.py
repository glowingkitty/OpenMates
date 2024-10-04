from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_get_all_scenes import (
    HomeGetAllScenesInput,
    HomeGetAllScenesOutput
)

logger = logging.getLogger(__name__)


async def get_all_scenes(
    team_slug: str,
    api_token: str,
    input: HomeGetAllScenesInput
) -> HomeGetAllScenesOutput:
    try:
        logger.debug("Getting all scenes")

        # TODO add processing via MQTT

        scenes =[]

        logger.debug("Got all scenes")
        return HomeGetAllScenesOutput(scenes=scenes)
    except Exception:
        logger.exception("Error getting all scenes")
        raise HTTPException(status_code=500, detail="An error occurred while getting all scenes")
