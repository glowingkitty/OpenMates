from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any

class User(BaseModel):
    id: str
    username: str
    email: EmailStr
    is_admin: bool = False
    credits: int = 0
    profile_image_url: Optional[str] = None
    last_opened: Optional[str] = None
    role: Optional[Dict[str, Any]] = None
