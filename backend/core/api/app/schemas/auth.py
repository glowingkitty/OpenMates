from pydantic import BaseModel, EmailStr
from typing import Optional

class InviteCodeRequest(BaseModel):
    invite_code: str
    
class InviteCodeResponse(BaseModel):
    valid: bool
    message: str
    is_admin: Optional[bool] = None
    gifted_credits: Optional[int] = None

# New models for email verification
class RequestEmailCodeRequest(BaseModel):
    email: EmailStr
    username: str
    invite_code: str
    
class RequestEmailCodeResponse(BaseModel):
    success: bool
    message: str
    
class CheckEmailCodeRequest(BaseModel):
    email: EmailStr
    code: str
    
class CheckEmailCodeResponse(BaseModel):
    success: bool
    message: str
