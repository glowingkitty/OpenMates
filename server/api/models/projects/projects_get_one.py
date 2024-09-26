
from pydantic import BaseModel, Field
from typing import List


# GET /projects/{project_name} (get a project)

class Project(BaseModel):
    """This is the base model for a project"""
    id: int = Field(..., description="ID of the project")
    name: str = Field(..., description="Name of the project")
    description: str = Field(..., description="Description of the project")


project_get_one_output_example = {
    "id": 1,
    "name": "Integrate AI into sales software",
    "description": "Integrate AI into the sales software to provide better insights and predictions. We use Python, Pandas, NumPy, and TensorFlow."
}