from pydantic import BaseModel, Field
from typing import Optional


class HomeSetSceneInput(BaseModel):
    """
    The input of the home set scene skill.

    Attributes:
        id (Optional[str]): The id of the scene which should be set.
        name (Optional[str]): The name of the scene which should be set.
    """
    id: Optional[str] = Field(None, description="The id of the scene which should be set")
    name: Optional[str] = Field(None, description="The name of the scene which should be set")


class HomeSetSceneOutput(BaseModel):
    """
    The output of the home set scene skill.

    Attributes:
        success (bool): Whether the scene was set successfully.
    """
    success: bool = Field(..., description="Was the request sent successfully?")

home_set_scene_input_example = {
    "name": "Watch a movie"
}

home_set_scene_output_example = {
    "success": True
}