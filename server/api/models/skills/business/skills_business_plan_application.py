from pydantic import BaseModel, Field
from typing import Literal, List, Optional

# POST /{team_slug}/skills/business/plan_application

class BusinessPlanApplicationInput(BaseModel):
    name: str = Field(..., description="What is the name of the project or company?")
    # TODO: add fields


class BusinessPlanApplicationOutput(BaseModel):
    requirements: str = Field(..., description="The detailed requirements for the application")
    recommendations: str = Field(..., description="Specific recommendations for improving the business plan")

business_plan_application_input_example = {
    "name": "GreenThumb",
}

business_plan_application_output_example = {
    "requirements": "The requirements for the application",
    "recommendations": "The recommendations for improving the business plan"
}
