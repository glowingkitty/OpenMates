from server.api.models.skills.business.skills_business_plan_application import BusinessPlanApplicationOutput
import logging

logger = logging.getLogger(__name__)


async def plan_application(
        application_type: str,
        application_type_other_use_case: str
) -> BusinessPlanApplicationOutput:
    logger.debug(f"Planning application")
    requirements = ""
    recommendations = ""

    # generate the system prompt for the LLM
    system = """
    You are an expert in planning applications for funding programs.
    Based on the information provided, you will then output the following:
    - A detailed list of requirements of how the application should be written to be successful
    - A detailed list of recommendations for the application to be successful
    - A list of questions that the user needs to answer, so that an LLM can use the requirements,
    recommendations and the answer to the questions to create an amazing application in the next step.
    """


    logger.debug(f"Application planned")
    return BusinessPlanApplicationOutput(
        requirements=requirements,
        recommendations=recommendations
    )
