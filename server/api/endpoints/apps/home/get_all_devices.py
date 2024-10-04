from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_get_all_devices import (
    HomeGetAllDevicesInput,
    HomeGetAllDevicesOutput
)

logger = logging.getLogger(__name__)


async def get_all_devices(
    team_slug: str,
    api_token: str,
    input: HomeGetAllDevicesInput
) -> HomeGetAllDevicesOutput:
    try:
        logger.debug("Getting all devices")

        # TODO add processing via MQTT

        devices =[]

        logger.debug("Got all devices")
        return HomeGetAllDevicesOutput(devices=devices)
    except Exception:
        logger.exception("Error getting all devices")
        raise HTTPException(status_code=500, detail="An error occurred while getting all devices")
