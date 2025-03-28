from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any

class User(BaseModel):
    id: str
    username: str
    vault_key_id: str
    is_admin: bool = False
    credits: int = 0
    profile_image_url: Optional[str] = None
    tfa_app_name: Optional[str] = None
    last_opened: Optional[str] = None
    # Consent fields (store timestamp as string)
    consent_privacy_and_apps_default_settings: Optional[str] = None
    consent_mates_default_settings: Optional[str] = None