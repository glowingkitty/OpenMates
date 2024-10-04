from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_add_device import (
    HomeAddDeviceInput,
    HomeAddDeviceOutput
)

logger = logging.getLogger(__name__)


async def add_device(
    team_slug: str,
    api_token: str,
    input: HomeAddDeviceInput
) -> HomeAddDeviceOutput:
    try:
        logger.debug("Adding device")

        # TODO add processing via MQTT

        logger.debug("Added device")
        return HomeAddDeviceOutput(success=True)
    except Exception:
        logger.exception("Error adding device")
        raise HTTPException(status_code=500, detail="An error occurred while adding device")
