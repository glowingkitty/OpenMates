from pydantic import BaseModel
from typing import Optional

class UserResponse(BaseModel):
    username: str
    is_admin: bool
    credits: int
    profile_image_url: Optional[str] = None
    last_opened: Optional[str] = None
    tfa_app_name: Optional[str] = None
    tfa_enabled: bool
    consent_privacy_and_apps_default_settings: bool = False
    consent_mates_default_settings: bool = False
    language: Optional[str] = 'en' # User's preferred language
    darkmode: bool = False # User's dark mode preference

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
                "consent_privacy_and_apps_default_settings": True,
                "consent_mates_default_settings": False,
                "language": "de", # Added example value
                "darkmode": True # Added example value
            }
        }
