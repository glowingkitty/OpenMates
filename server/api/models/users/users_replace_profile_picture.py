
from pydantic import BaseModel, Field, validator


# PATCH /{team_slug}/users/{username}/profile_picture (Replace the profile picture of a user)

class UsersReplaceProfilePictureOutput(BaseModel):
    """This is the model for the output of PATCH /{team_slug}/users/{username}/profile_picture"""
    profile_image: str = Field(..., description="URL of the new profile picture")


users_replace_profile_picture_output_example = {
    "profile_image": "/v1/ai-sales-team/uploads/johnd_new_image.jpeg"
}