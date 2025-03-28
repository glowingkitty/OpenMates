from pydantic import BaseModel
from typing import Optional

class UserResponse(BaseModel):
    username: str
    is_admin: bool
    credits: int
    profile_image_url: Optional[str] = None
    last_opened: Optional[str] = None
    tfa_app_name: Optional[str] = None
    tfa_enabled: bool # Added field for 2FA status
    # Add boolean consent flags
    has_consent_privacy: bool = False
    has_consent_mates: bool = False
    
    class Config:
        json_schema_extra = {
            "example": {
                "username": "johndoe",
                "is_admin": False,
                "credits": 100,
                "profile_image_url": "https://example.com/profile.jpg",
                "last_opened": "/signup/step-3",
                "tfa_app_name": "Google Authenticator",
                "tfa_enabled": True, # Added example value
                # Add examples for consent flags
                "has_consent_privacy": True,
                "has_consent_mates": False
            }
        }
