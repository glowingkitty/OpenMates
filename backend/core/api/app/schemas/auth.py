from pydantic import BaseModel, EmailStr
from typing import Optional

class InviteCodeRequest(BaseModel):
    invite_code: str
    
class InviteCodeResponse(BaseModel):
    valid: bool
    message: str
    is_admin: Optional[bool] = None
    gifted_credits: Optional[int] = None

# Updated model for email verification
class RequestEmailCodeRequest(BaseModel):
    email: EmailStr
    invite_code: Optional[str] = None  # Can come from cookie
    username: Optional[str] = None  # For account creation
    password: Optional[str] = None  # For account creation
    language: str = "en"  # Default to English if not provided
    darkmode: bool = False  # Default to light mode if not provided
    
class RequestEmailCodeResponse(BaseModel):
    success: bool
    message: str
    
class CheckEmailCodeRequest(BaseModel):
    email: Optional[EmailStr] = None  # Can come from cookie
    code: str
    invite_code: Optional[str] = None  # Can come from cookie
    
class CheckEmailCodeResponse(BaseModel):
    success: bool
    message: str
