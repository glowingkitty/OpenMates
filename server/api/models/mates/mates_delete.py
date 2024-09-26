from pydantic import BaseModel, Field


# DELETE /mates/{mate_username} (delete a mate)

class MatesDeleteOutput(BaseModel):
    """This is the model for the outgoing response for DELETE /mates/{mate_username}"""
    deleted_user: str = Field(..., description="Username of the AI team mate that was deleted")

mates_delete_output_example = {
    "deleted_user": "sophia"
}