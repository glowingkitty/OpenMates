from fastapi import HTTPException
import logging
from server.api.models.apps.home.skills_home_set_device import (
    HomeSetDeviceInput,
    HomeSetDeviceOutput
)
from server.api.models.apps.home.skills_home_add_device import HomeAddDeviceInput, MQTTTopic, MQTT
logger = logging.getLogger(__name__)


async def set_device(
    team_slug: str,
    api_token: str,
    input: HomeSetDeviceInput
) -> HomeSetDeviceOutput:
    try:
        logger.debug("Setting device")

        # TODO find the device in the database

        # TODO check if the command is valid

        # TODO send the command to the MQTT broker

        logger.debug("Set device")
        return HomeSetDeviceOutput(success=True)
    except Exception:
        logger.exception("Error setting device")
        raise HTTPException(status_code=500, detail="An error occurred while setting device")
