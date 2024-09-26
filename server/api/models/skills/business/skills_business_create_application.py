from pydantic import BaseModel, Field
from typing import Literal, List, Optional

# POST /{team_slug}/skills/business/create_application

class BusinessCreateApplicationInput(BaseModel):
    requirements: str = Field(..., description="The detailed requirements for the application")
    recommendations: str = Field(..., description="Specific recommendations for improving the application")

# TODO: add fields

class BusinessCreateApplicationOutput(BaseModel):
    application: str = Field(..., description="The application for the project or company")

business_create_application_input_example = {
}

business_create_application_output_example = {

}
