from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any, Union
from app.schemas.user import UserResponse

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
    tfa_code: Optional[str] = Field(None, description="Optional 2FA code for verification step")
    
    class Config:
        schema_extra = {
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
    user: Optional[UserResponse] = None  # User data is returned only on full success (no 2FA needed or 2FA verified)
    tfa_required: bool = Field(False, description="Indicates if 2FA verification is required")
    # tfa_cache_key: Optional[str] = Field(None, description="Temporary key for linking 2FA verification step") # Removed as per revised plan
    
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
                    "user": { # Only include minimal info needed for 2FA step, like app name
                        "username": None, 
                        "is_admin": None,
                        "credits": None,
                        "profile_image_url": None,
                        "tfa_app_name": "Google Authenticator",
                        "last_opened": None
                    },
                    "tfa_required": True
                    # "tfa_cache_key": "login_tfa_pending:abc123xyz" # Removed as per revised plan
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
    """Response for session endpoint"""
    success: bool
    message: str
    user: Optional[UserResponse] = None
    token_refresh_needed: bool = False
