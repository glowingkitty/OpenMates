from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any, Union

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
    error_code: Optional[str] = None  # Add error code field
    
class CheckEmailCodeRequest(BaseModel):
    email: Optional[EmailStr] = None  # Can come from cookie
    code: str
    invite_code: Optional[str] = None  # Can come from cookie
    
class CheckEmailCodeResponse(BaseModel):
    success: bool
    message: str
    user: Optional[Dict[str, Any]] = None  # Include user data in the response

class LoginRequest(BaseModel):
    """Schema for login request"""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")
    
    class Config:
        schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "securePassword123!"
            }
        }

class LoginResponse(BaseModel):
    """Schema for login response"""
    success: bool = Field(..., description="Whether the login was successful")
    message: str = Field(..., description="Response message")
    user: Optional[Dict[str, Any]] = Field(None, description="User information if login successful")
    
    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Login successful",
                "user": {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "username": "johndoe",
                    "is_admin": False
                }
            }
        }

class LogoutResponse(BaseModel):
    """Schema for logout response"""
    success: bool = Field(..., description="Whether the logout was successful")
    message: str = Field(..., description="Response message")
    
    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Logged out successfully"
            }
        }

class SessionResponse(BaseModel):
    """Schema for current user session data"""
    authenticated: bool = False
    # Use empty string as default instead of None for string fields
    id: Optional[str] = ""  
    username: Optional[str] = ""
    is_admin: bool = False
    avatar_url: Optional[str] = None
