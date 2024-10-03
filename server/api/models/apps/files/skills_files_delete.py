from pydantic import BaseModel, Field


# POST /apps/files/delete

class FilesDeleteOutput(BaseModel):
    """Output for the files delete endpoint"""
    file_id: str = Field(..., description="The ID of the file that was deleted")
    success: bool = Field(..., description="Whether the file was successfully deleted")


files_delete_output_example = {
    "file_id": "291hs98229",
    "success": True
}