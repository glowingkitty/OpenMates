from server.api.models.skills.business.skills_business_create_application import BusinessCreateApplicationOutput
from typing import List

async def create_application(
        requirements: str,
        recommendations: str
) -> BusinessCreateApplicationOutput:
    application = ""

    return BusinessCreateApplicationOutput(
        application=application
    )
