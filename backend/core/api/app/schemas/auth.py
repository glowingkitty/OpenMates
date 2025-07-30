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
    hashed_email: str = Field(..., description="Hashed email (SHA256) for lookup and uniqueness check")
    invite_code: Optional[str] = None  # Can come from cookie
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
    invite_code: str
    language: str
    darkmode: bool
    
class CheckEmailCodeResponse(BaseModel):
    success: bool
    message: str
    user: Optional[Dict[str, Any]] = None  # Include user data in the response

class LoginRequest(BaseModel):
    """Schema for login request"""
    hashed_email: str = Field(..., description="Hashed email for lookup")
    lookup_hash: str = Field(..., description="Hash of email + password for authentication")
    tfa_code: Optional[str] = Field(None, description="Optional 2FA code (OTP or backup) for verification step")
    code_type: Optional[str] = Field("otp", description="Type of code provided ('otp' or 'backup')")
    
    class Config:
        json_schema_extra = {
            "example_no_tfa": {
                "hashed_email": "base64_encoded_hashed_email",
                "lookup_hash": "base64_encoded_lookup_hash"
            },
            "example_with_tfa": {
                "hashed_email": "base64_encoded_hashed_email",
                "lookup_hash": "base64_encoded_lookup_hash",
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

class SessionResponse(BaseModel):
    """Response for session endpoint"""
    success: bool
    message: str
    user: Optional[UserResponse] = None
    token_refresh_needed: bool = False
    re_auth_required: Optional[str] = None # e.g., "2fa"
    require_invite_code: bool = True  # Default to True for backward compatibility

class SetupPasswordRequest(BaseModel):
    """Request for setting up password and creating user account"""
    hashed_email: str = Field(..., description="Hashed email for lookup")
    encrypted_email: str = Field(..., description="Client-side encrypted email")
    user_email_salt: str = Field(..., description="Salt used for email encryption (base64)")
    username: str = Field(..., description="User's username")
    invite_code: str = Field(..., description="Invite code")
    encrypted_master_key: str = Field(..., description="Encrypted master key")
    salt: str = Field(..., description="Salt used for key derivation")
    lookup_hash: str = Field(..., description="Hash of email + password for authentication")
    language: str = Field("en", description="User's preferred language")
    darkmode: bool = Field(False, description="User's dark mode preference")

class SetupPasswordResponse(BaseModel):
    """Response for password setup endpoint"""
    success: bool = Field(..., description="Whether the password setup was successful")
    message: str = Field(..., description="Response message")
    user: Optional[Dict[str, Any]] = None

class UserLookupRequest(BaseModel):
    """Schema for user lookup request (email-only first step)"""
    hashed_email: str = Field(..., description="Hashed email for lookup")
    
    class Config:
        json_schema_extra = {
            "example": {
                "hashed_email": "base64_encoded_hashed_email"
            }
        }

class UserLookupResponse(BaseModel):
    """Schema for user lookup response"""
    login_method: str = Field(..., description="Preferred login method (password, passkey, security_key, recovery_key)")
    available_login_methods: list[str] = Field(..., description="List of available login methods")
    tfa_app_name: Optional[str] = Field(None, description="Name of the 2FA app if user has 2FA enabled")
    
    class Config:
        json_schema_extra = {
            "example": {
                "login_method": "password",
                "available_login_methods": ["password", "recovery_key"],
                "tfa_app_name": "Google Authenticator"
            }
        }
