from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_get_temperature import (
    HomeGetTemperatureInput,
    HomeGetTemperatureOutput
)

logger = logging.getLogger(__name__)


async def get_temperature(
    team_slug: str,
    api_token: str,
    input: HomeGetTemperatureInput
) -> HomeGetTemperatureOutput:
    try:
        logger.debug("Getting temperature(s)")

        # TODO add processing via MQTT

        temperatures =[]

        logger.debug("Got temperature(s)")
        return HomeGetTemperatureOutput(temperatures=temperatures)
    except Exception:
        logger.exception("Error getting temperature(s)")
        raise HTTPException(status_code=500, detail="An error occurred while getting temperature(s)")
