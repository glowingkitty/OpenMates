
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

from pydantic import BaseModel, Field, validator


# PATCH /{team_slug}/users/{username}/profile_picture (Replace the profile picture of a user)

class UsersReplaceProfilePictureOutput(BaseModel):
    """This is the model for the output of PATCH /{team_slug}/users/{username}/profile_picture"""
    profile_picture_url: str = Field(..., description="URL of the new profile picture")


users_replace_profile_picture_output_example = {
    "profile_picture_url": "/v1/ai-sales-team/uploads/johnd_new_image.jpeg"
}