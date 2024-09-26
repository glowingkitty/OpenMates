from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Union
from urllib.parse import quote
from server.api.models.mates.validators import validate_llm_model, validate_llm_endpoint
from pydantic import model_validator


# PATCH /mates/{mate_username} (update a mate)

class MatesUpdateInput(BaseModel):
    """This is the model for the incoming parameters for PATCH /mates/{mate_username}"""
    name: str = Field(None, description="Name of the AI team mate")
    username: str = Field(None, description="Username of the AI team mate", min_length=1, max_length=30, json_schema_extra={"unique": True})
    description: str = Field(None, description="Description of the AI team mate", min_length=1, max_length=150)
    profile_image: str = Field(None, description="URL of the profile picture of the AI team mate", pattern=r".*\.(jpg|jpeg|png)$")
    default_systemprompt: str = Field(None, description="Default system prompt of the AI team mate", min_length=1)
    default_skills: Optional[List[Union[int, str]]] = Field(None, description="Default list of skill IDs or skill API endpoints for the AI team mate")
    default_llm_endpoint: str = Field(None, description="Default API endpoint of the Large Language Model (LLM) which is used by the AI team mate.")
    default_llm_model: str = Field(None, description="Default LLM model which is used by the AI team mate.")
    systemprompt: str = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nCustom system prompt of the AI team mate.", min_length=1)
    skills: List[int] = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nCustom list of skills (IDs) AI team mate is allowed to use.")
    llm_endpoint: str = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nCustom API endpoint of the Large Language Model (LLM) which is used by the AI team mate.")
    llm_model: str = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nCustom LLM model which is used by the AI team mate.")
    allowed_to_access_user_name: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your name.")
    allowed_to_access_user_username: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your username.")
    allowed_to_access_user_projects: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your projects.")
    allowed_to_access_user_goals: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your goals.")
    allowed_to_access_user_todos: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access your To Do's.")
    allowed_to_access_user_recent_topics: bool = Field(None, description="**Only for your user, in the selected team. Does not apply to other teams or users.**  \nWhether the AI team mate is allowed to access the recent topics you asked AI team mates about.")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='after')
    def check_if_no_fields_to_update(self):
        if self.model_dump() == {}:
            raise ValueError("No fields to update.")
        return self

    @field_validator('username')
    @classmethod
    def username_must_be_url_compatible(cls, v):
        if quote(v) != v:
            raise ValueError('username must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('username must be all lowercase')
        return v

    @field_validator('profile_image')
    @classmethod
    def validate_profile_image(cls, v):
        pattern = r'^/v1/[a-z0-9-]+/uploads/[a-zA-Z0-9_.-]+\.(jpeg|jpg|png)$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid profile picture URL format: {v}")
        return v

    @field_validator('default_llm_endpoint', 'llm_endpoint')
    @classmethod
    def validate_llm_endpoint(cls, v):
        if v is not None:  # Check if the value is provided
            return validate_llm_endpoint(v)
        return v  # Return as is if None

    @field_validator('default_llm_model', 'llm_model')
    @classmethod
    def validate_llm_model(cls, v, info):
        if v is not None:  # Check if the value is provided
            endpoint_field = 'default_llm_endpoint' if info.field_name == 'default_llm_model' else 'llm_endpoint'
            endpoint = info.data.get(endpoint_field)
            if endpoint is None:
                raise ValueError(f"{endpoint_field} must be provided when specifying a model")
            return validate_llm_model(v, endpoint)
        return v  # Return as is if None


mates_update_input_example = {
    "description": "A software development expert, who can help you with all your coding needs."
}


class MatesUpdateOutput(BaseModel):
    """This is the model for the outgoing response for PATCH /mates/{mate_username}"""
    id: int = Field(..., description="ID of the AI team mate")
    username: str = Field(..., description="Username of the AI team mate")
    updated_fields: dict = Field(..., description="Dict with all updated fields")

mates_update_output_example = {
    "id": 1,
    "username": "sophia",
    "updated_fields": {
        "description": "A software development expert, who can help you with all your coding needs."
    }
}