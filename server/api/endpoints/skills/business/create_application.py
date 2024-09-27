from server.api.models.skills.business.skills_business_create_application import BusinessCreateApplicationOutput, BusinessCreateApplicationInput
from typing import List
import logging

logger = logging.getLogger(__name__)


async def create_application(
        application_input: BusinessCreateApplicationInput
) -> BusinessCreateApplicationOutput:
    logger.debug(f"Creating application")
    application = ""

    logger.debug(f"Application created")
    return BusinessCreateApplicationOutput(
        application=application
    )
