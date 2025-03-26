from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any

class User(BaseModel):
    id: str
    username: str
    vault_key_id: str
    is_admin: bool = False
    credits: int = 0
    profile_image_url: Optional[str] = None
    last_opened: Optional[str] = None