from pydantic import BaseModel, Field, model_validator
from typing import List, Optional

class Home(BaseModel):
    id: Optional[str] = Field(None, description="The id of the home")
    name: Optional[str] = Field(None, description="The name of the home")

    @model_validator(mode='before')
    def validate_home(cls, data):
        if not data.get('id') and not data.get('name'):
            raise ValueError("Home must have either an id or name")
        return data

class HomeGetAllScenesInput(BaseModel):
    home: Home = Field(..., description="The home to get the scenes for")

home_get_all_scenes_input_example = {
    "home": {
        "name": "My Smart Home"
    }
}


class Scene(BaseModel):
    id: str = Field(..., description="The id of the scene")
    name: str = Field(..., description="The name of the scene")
    description: Optional[str] = Field(None, description="The description of the scene")

class HomeGetAllScenesOutput(BaseModel):
    scenes: List[Scene] = Field(..., description="The list of scenes in the home")



home_get_all_scenes_output_example = {
    "scenes": [
        {
            "id": "1",
            "name": "Watch a movie",
            "description": "Set the scene to watch a movie in the living room."
        },
        {
            "id": "2",
            "name": "Party mode",
            "description": "Set the scene to party mode in the living room."
        },
        {
            "id": "3",
            "name": "Sleep mode",
            "description": "Set the scene to sleep mode in the bedroom."
        }
    ]
}