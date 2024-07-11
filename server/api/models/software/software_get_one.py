
################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from pydantic import BaseModel, Field, field_validator, ConfigDict
from urllib.parse import quote


# GET /software/{slug} (get a software)

class Software(BaseModel):
    """This is the model for a software"""
    id: int = Field(..., description="ID of the software")
    name: str = Field(..., description="name of the software")
    slug: str = Field(..., description="Slug of the software")
    icon_url: str = Field(..., description="URL of the icon of the software")

    model_config = ConfigDict(extra="forbid")

    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if quote(v) != v:
            raise ValueError('slug must only contain URL-safe characters')
        if not v.islower():
            raise ValueError('slug must be all lowercase')
        return v

    @field_validator('icon_url')
    @classmethod
    def validate_icon_url(cls, v: str) -> str:
        pattern = r'^/v1/[a-z0-9-]+/uploads/[a-zA-Z0-9_.-]+\.(jpeg|jpg|png|gif)$'
        if not re.match(pattern, v):
            raise ValueError(f"Invalid icon URL format: {v}")
        return v


software_get_one_output_example = {
    "id": 1,
    "name": "Claude",
    "slug": "claude",
    "icon_url": "/v1/ai-sales-team/uploads/claude_icon.jpeg",
}