from server.api.models.skills.business.skills_business_plan_application import BusinessPlanApplicationOutput


async def plan_application(
        application_type: str,
        application_type_other_use_case: str
) -> BusinessPlanApplicationOutput:
    requirements = ""
    recommendations = ""

    return BusinessPlanApplicationOutput(
        requirements=requirements,
        recommendations=recommendations
    )
