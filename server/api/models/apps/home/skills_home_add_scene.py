from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from skills_home_set_device import HomeSetDeviceInput


class HomeAddSceneInput(BaseModel):
    """
    The input of the home add scene skill.

    Attributes:
        id (str): The id of the scene.
        name (str): The name of the scene.
        description (str): The description of the scene.
        device_changes (List[HomeSetDeviceInput]): The list of devices that are part of the scene and what states should be set.
    """
    id: str = Field(..., description="The id of the scene")
    name: str = Field(..., description="The name of the scene")
    description: Optional[str] = Field(None, description="The description of the scene")
    device_changes: List[HomeSetDeviceInput] = Field(..., description="The list of devices that are part of the scene and what states should be set")

home_add_scene_input_example = {
    "id": "1",
    "name": "Watch a movie",
    "description": "Set the scene to watch a movie in the living room.",
    "device_changes": [
        {
            "id": "1234567890",
            "command": {
                "state": "power",
                "value": "on"
            }
        },
        {
            "id": "1234567894",
            "command": {
                "state": "brightness",
                "value": "50"
            }
        }
    ]
}

class HomeAddSceneOutput(BaseModel):
    """
    The output of the home add scene skill.

    Attributes:
        success (bool): Whether the scene was added successfully.
    """
    success: bool = Field(..., description="Whether the scene was added successfully")

home_add_scene_output_example = {
    "success": True
}