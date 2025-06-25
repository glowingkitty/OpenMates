from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any, Union
from backend.core.api.app.schemas.user import UserResponse

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
    code: str
    email: EmailStr
    username: str
    password: str
    invite_code: str
    language: str
    darkmode: bool
    encrypted_master_key: str
    salt: str
    
class CheckEmailCodeResponse(BaseModel):
    success: bool
    message: str
    user: Optional[Dict[str, Any]] = None  # Include user data in the response

class LoginRequest(BaseModel):
    """Schema for login request"""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")
    tfa_code: Optional[str] = Field(None, description="Optional 2FA code (OTP or backup) for verification step")
    code_type: Optional[str] = Field("otp", description="Type of code provided ('otp' or 'backup')")
    deviceSignals: Optional[Dict[str, Any]] = Field(None, description="Optional dictionary containing client-side device signals (hashes)")
    
    class Config:
        json_schema_extra = {
            "example_no_tfa": {
                "email": "user@example.com",
                "password": "securePassword123!"
            },
            "example_with_tfa": {
                "email": "user@example.com",
                "password": "securePassword123!",
                "tfa_code": "123456"
            }
        }

class LoginResponse(BaseModel):
    """Schema for login response"""
    success: bool = Field(..., description="Whether the login was successful")
    message: str = Field(..., description="Response message")
    user: Optional[UserResponse] = None
    tfa_required: bool = Field(False, description="Indicates if 2FA verification is required")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Login successful",
                "user": {
                    "username": "johndoe",
                    "is_admin": False,
                    "credits": 100,
                    "profile_image_url": None,
                    "tfa_app_name": "Google Authenticator", # Example if 2FA is setup
                    "last_opened": "/app/dashboard"
                },
                # Example when 2FA is required (first step)
                "example_tfa_required": {
                    "success": True,
                    "message": "2FA required",
                    "user": {
                        "username": None, 
                        "is_admin": None,
                        "credits": None,
                        "profile_image_url": None,
                        "tfa_app_name": "Google Authenticator",
                        "last_opened": None
                    },
                    "tfa_required": True
                }
            }
        }

class LogoutResponse(BaseModel):
    """Schema for logout response"""
    success: bool = Field(..., description="Whether the logout was successful")
    message: str = Field(..., description="Response message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Logged out successfully"
            }
        }
class SessionRequest(BaseModel):
    """Optional request body for session endpoint, containing client signals"""
    deviceSignals: Optional[Dict[str, Any]] = Field(None, description="Optional dictionary containing client-side device signals (hashes)")

class SessionResponse(BaseModel):
    """Response for session endpoint"""
    success: bool
    message: str
    user: Optional[UserResponse] = None
    token_refresh_needed: bool = False
    re_auth_required: Optional[str] = None # e.g., "2fa"
