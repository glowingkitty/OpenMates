from pydantic import BaseModel, Field
from typing import List
from enum import Enum

##################################
######### Uploads ##################
##################################

## Endpoint models

# GET /upload/{file_name} (Get a file from the Strapi uploads)

class UploadsGetFileInput(BaseModel):
    """This is the model for the incoming parameters for GET /upload/{file_name}"""
    team_name: str = Field(...,
                    description="The name of your team.",
                    example="glowingkitties"
                    )