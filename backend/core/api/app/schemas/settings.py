from pydantic import BaseModel
from typing import Optional

class LanguageUpdateRequest(BaseModel):
    language: str

    class Config:
        json_schema_extra = {
            "example": {
                "language": "fr"
            }
        }

class DarkModeUpdateRequest(BaseModel):
    darkmode: bool

    class Config:
        json_schema_extra = {
            "example": {
                "darkmode": True
            }
        }

# --- Response model for user email ---
class UserEmailResponse(BaseModel):
    email: str

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com"
            }
        }