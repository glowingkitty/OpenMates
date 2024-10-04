from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_set_device import (
    HomeSetDeviceInput,
    HomeSetDeviceOutput
)

logger = logging.getLogger(__name__)


async def set_device(
    team_slug: str,
    api_token: str,
    input: HomeSetDeviceInput
) -> HomeSetDeviceOutput:
    try:
        logger.debug("Setting device")

        # TODO add processing via MQTT

        logger.debug("Set device")
        return HomeSetDeviceOutput(success=True)
    except Exception:
        logger.exception("Error setting device")
        raise HTTPException(status_code=500, detail="An error occurred while setting device")
