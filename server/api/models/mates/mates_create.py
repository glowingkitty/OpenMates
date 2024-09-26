from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Union
from server.api.models.skills.skills_get_one import SkillMini
from urllib.parse import quote
from server.api.models.mates.validators import validate_llm_endpoint, validate_llm_model


# POST /mates (create a new mate)

class MatesCreateInput(BaseModel):
    """This is the model for the incoming parameters for POST /mates"""
    name: str = Field(..., description="Name of the AI team mate", min_length=1, max_length=30)
    username: str = Field(..., description="Username of the AI team mate", min_length=1, max_length=30, json_schema_extra={"unique": True})
    description: str = Field(..., description="Description of the AI team mate", min_length=1, max_length=150)
    profile_image: str = Field(..., description="URL of the profile picture of the AI team mate", pattern=r".*\.(jpg|jpeg|png)$")
    default_systemprompt: str = Field(..., description="Default system prompt of the AI team mate", min_length=1)
    default_skills: Optional[List[Union[int, str]]] = Field(None, description="Default list of skill IDs or skill API endpoints for the AI team mate")
    default_llm_endpoint: str = Field(..., description="Default LLM endpoint of the AI team mate")
    default_llm_model: str = Field(..., description="Default LLM model of the AI team mate")

    # TODO improve validation later using LLMs

    # prevent extra fields from being passed to API
    model_config = ConfigDict(extra="forbid")

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        if quote(v) != v:
            raise ValueError('username must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('username must be all lowercase')
        return v

    @field_validator('profile_image')
    @classmethod
    def validate_profile_image(cls, v):
        pattern = r'^/v1/[a-z0-9-]+/uploads/[a-zA-Z0-9_.-]+\.(jpeg|jpg|png|gif)$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid profile picture URL format: {v}")
        return v

    @field_validator('default_llm_endpoint')
    @classmethod
    def validate_llm_endpoint(cls, v):
        return validate_llm_endpoint(v)

    @field_validator('default_llm_model')
    @classmethod
    def validate_llm_model(cls, v, values):
        endpoint = values.data.get('default_llm_endpoint')
        return validate_llm_model(v, endpoint)


mates_create_input_example = {
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_image": "/v1/ai-sales-team/uploads/sophia_image.jpeg",
    "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "default_skills": ['/v1/ai-sales-team/skills/vs_code/write_and_test_code'],
    "default_llm_endpoint": "/v1/ai-sales-team/skills/claude/ask",
    "default_llm_model": "claude-3.5-sonnet"
}



class MatesCreateOutput(MatesCreateInput):
    """This is the model for the outgoing response for POST /mates"""
    id: int = Field(..., description="ID of the AI team mate")
    default_skills: List[SkillMini] = Field(..., description="Default list of skills for the AI team mate")


mates_create_output_example = {
    "id": 2,
    "name": "Sophia",
    "username": "sophia",
    "description": "Software development expert",
    "profile_image": "/v1/ai-sales-team/uploads/sophia_image.jpeg",
    "default_systemprompt": "You are a software development expert. Keep your answers clear and concise.",
    "default_skills": [
        {
            "id": 3,
            "api_endpoint": "/v1/ai-sales-team/skills/vs_code/write_and_test_code",
            "description": "Writes and tests code based on the given requirements."
        }
    ],
    "default_llm_endpoint": "/v1/ai-sales-team/skills/claude/ask",
    "default_llm_model": "claude-3.5-sonnet"
}