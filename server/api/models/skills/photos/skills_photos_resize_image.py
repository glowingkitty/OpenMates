
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

from server.api import *
################

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


# POST /{team_slug}/skills/photos/resize (resize an image)

class ImageEditorResizeImageInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/skills/photos/resize"""
    image_data: bytes = Field(..., title="Image Data", description="The image data to resize")
    target_resolution_width: int = Field(..., title="Target Resolution Width", description="The target resolution width")
    target_resolution_height: int = Field(..., title="Target Resolution Height", description="The target resolution height")
    max_length: int = Field(..., title="Max Length", description="The maximum length of the image")
    method: Literal["scale", "crop"] = Field("scale", description="The method to use for resizing.")
    use_ai_upscaling_if_needed: bool = Field(False, title="Use AI Upscaling If Needed", description="Use AI upscaling if needed")
    output_square: bool = Field(False, title="Output Square", description="Output a square image")

    model_config = ConfigDict(extra="forbid")

    @field_validator('image_data')
    @classmethod
    def validate_file_size(cls, v):
        if not v:
            raise ValueError("Image data is empty")
        file_size = len(v)
        max_size = 3 * 1024 * 1024  # 3MB in bytes
        if file_size > max_size:
            raise ValueError(f"File size ({file_size} bytes) exceeds 3MB limit ({max_size} bytes)")
        return v


photos_resize_output_example = {
    "image/jpeg": "data:image/jpeg;base64..."
}