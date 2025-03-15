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
    invite_code: str
    language: str = "en"  # Default to English if not provided
    darkmode: bool = False  # Default to light mode if not provided
    
class RequestEmailCodeResponse(BaseModel):
    success: bool
    message: str
    
class CheckEmailCodeRequest(BaseModel):
    email: EmailStr
    code: str
    
class CheckEmailCodeResponse(BaseModel):
    success: bool
    message: str
