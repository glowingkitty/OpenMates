from pydantic import BaseModel, Field
from typing import Optional


class HomeSetSceneInput(BaseModel):
    id: Optional[str] = Field(None, description="The id of the scene which should be set")
    name: Optional[str] = Field(None, description="The name of the scene which should be set")


class HomeSetSceneOutput(BaseModel):
    success: bool

home_set_scene_input_example = {
    "name": "Watch a movie"
}

home_set_scene_output_example = {
    "success": True
}