from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


# POST /skills/files/upload

class FilesUploadOutput(BaseModel):
    """Output for the files upload endpoint"""
    name: str = Field(..., description="The name of the file")
    url: str = Field(..., description="The URL of the file")
    expiration_datetime: Optional[str] = Field(None, description="The expiration date and time of the file")
    access_public: bool = Field(False, description="If set to True, the file will be publicly accessible")
    read_access_limited_to_teams: Optional[List[str]] = Field(None, description="List of teams with read access")
    read_access_limited_to_users: Optional[List[str]] = Field(None, description="List of users with read access")
    write_access_limited_to_teams: Optional[List[str]] = Field(None, description="List of teams with write access")
    write_access_limited_to_users: Optional[List[str]] = Field(None, description="List of users with write access")

    @field_validator('expiration_datetime')
    @classmethod
    def validate_expiration_datetime(cls, value):
        if value is not None:
            try:
                datetime.fromisoformat(value)
            except ValueError:
                raise ValueError('expiration_datetime must be a valid ISO 8601 datetime string')
        return value


files_upload_output_example = {
    "name": "project_proposal.docx",
    "url": "/v1/openmatesdevs/skills/files/dropbox/projects/rest_api/project_proposal.docx",
    "expiration_datetime": "2024-01-01T00:00:00Z",
    "access_public": False,
    "read_access_limited_to_teams": ["openmatesdevs"],
    "read_access_limited_to_users": None,
    "write_access_limited_to_teams": ["openmatesdevs"],
    "write_access_limited_to_users": None
}