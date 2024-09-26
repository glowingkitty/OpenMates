
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List
from server.api.models.metadata import MetaData


# GET /mates (get all mates)

class MateMini(BaseModel):
    """This is the model for a single AI team mate, for the endpoint GET /mates"""
    id: int = Field(..., description="ID of the AI team mate")
    name: str = Field(..., description="name of the AI team mate")
    username: str = Field(..., description="username of the AI team mate")
    description: str = Field(..., description="Description of the AI team mate")
    profile_image: str = Field(..., description="URL of the profile picture of the AI team mate")

    model_config = ConfigDict(extra="forbid")

    @field_validator('profile_image')
    @classmethod
    def validate_profile_image(cls, v):
        pattern = r'^/v1/[a-z0-9-]+/uploads/[a-zA-Z0-9_.-]+\.(jpeg|jpg|png|gif)$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid profile picture URL format: {v}")
        return v

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        if not v.islower():
            raise ValueError(f"Username must be in lower case: {v}")
        return v


class MatesGetAllOutput(BaseModel):
    data: List[MateMini] = Field(..., description="List of all AI team mates for the team")
    meta: MetaData = Field(..., description="Metadata for the response")

    model_config = ConfigDict(extra="forbid")


mates_get_all_output_example = {
    "data": [
        {
            "id": 1,
            "name": "Burton",
            "username": "burton",
            "description": "Business development expert",
            "profile_image": "/v1/ai-sales-team/uploads/burton_image.jpeg"
        },
        {
            "id": 2,
            "name": "Sophia",
            "username": "sophia",
            "description": "Software development expert",
            "profile_image": "/v1/ai-sales-team/uploads/sophia_image.jpeg"
        }
    ],
    "meta": {
        "pagination": {
            "page": 1,
            "pageSize": 25,
            "pageCount": 1,
            "total": 2
        }
    }
}