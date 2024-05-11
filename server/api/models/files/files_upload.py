
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

from pydantic import BaseModel, Field, validator
from typing import List, Optional
from urllib.parse import quote


# POST /uploads (create a new mate)

class FileUploadOutput(BaseModel):
    """This is the model for the output of POST /uploads"""
    url: str = Field(..., description="URL of the uploaded file"),
    access_public: bool = Field(False, description="If set to True, the file can be accessed by anyone on the internet.")
    read_access_limited_to_team_slugs: List[str] = Field(None, description="List of team slugs with read access")
    write_access_limited_to_team_slugs: List[str] = Field(None, description="List of team slugs with write access")
    read_access_limited_to_user_usernames: List[str] = Field(None, description="List of user usernames with read access (even if outside of the teams with file access)")
    write_access_limited_to_user_usernames: List[str] = Field(None, description="List of user usernames with write access (even if outside of the teams with file access)")


file_upload_output_example = {
    "url": "/ai-sales-team/uploads/sophia_image.jpeg",
    "access_public": False,
    "read_access_limited_to_team_slugs": ["ai-sales-team"],
    "write_access_limited_to_team_slugs": ["ai-sales-team"],
    "read_access_limited_to_user_usernames": ["sophia"],
    "write_access_limited_to_user_usernames": ["sophia"]
}