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
    session_id: Optional[str] = Field(None, description="Browser session ID for device fingerprint uniqueness (UUID from sessionStorage). Required for login, optional for signup.")
    tfa_code: Optional[str] = Field(None, description="Optional 2FA code (OTP or backup) for verification step")
    code_type: Optional[str] = Field("otp", description="Type of code provided ('otp' or 'backup')")
    email_encryption_key: Optional[str] = Field(None, description="Client-derived key for email decryption (SHA256(email + user_email_salt))")
    login_method: Optional[str] = Field(None, description="Login method used ('password', 'passkey', 'security_key', 'recovery_key')")
    stay_logged_in: bool = Field(False, description="Whether to keep user logged in for extended period (30 days vs 24 hours)")
    
    class Config:
        json_schema_extra = {
            "example_no_tfa": {
                "hashed_email": "base64_encoded_hashed_email",
                "lookup_hash": "base64_encoded_lookup_hash"
            },
            "example_with_tfa": {
                "hashed_email": "base64_encoded_hashed_email",
                "lookup_hash": "base64_encoded_lookup_hash",
                "tfa_code": "123456",
                "email_encryption_key": "base64_encoded_email_encryption_key"
            }
        }

class LoginResponse(BaseModel):
    """Schema for login response"""
    success: bool = Field(..., description="Whether the login was successful")
    message: str = Field(..., description="Response message")
    user: Optional[UserResponse] = None
    tfa_required: bool = Field(False, description="Indicates if 2FA verification is required")
    ws_token: Optional[str] = None  # WebSocket authentication token (for Safari iOS compatibility)
    
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
    ws_token: Optional[str] = None  # WebSocket authentication token (for Safari iOS compatibility)

class SetupPasswordRequest(BaseModel):
    """Request for setting up password and creating user account"""
    hashed_email: str = Field(..., description="Hashed email for lookup")
    encrypted_email: str = Field(..., description="Client-side encrypted email")
    user_email_salt: str = Field(..., description="Salt used for email encryption (base64)")
    username: str = Field(..., description="User's username")
    invite_code: str = Field(..., description="Invite code")
    encrypted_master_key: str = Field(..., description="Encrypted master key")
    key_iv: str = Field(..., description="IV used for master key encryption (base64)")
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
    stay_logged_in: bool = Field(False, description="Whether to keep user logged in for extended period (30 days vs 24 hours)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "hashed_email": "base64_encoded_hashed_email",
                "stay_logged_in": False
            }
        }

class UserLookupResponse(BaseModel):
    """Schema for user lookup response"""
    login_method: str = Field(..., description="Preferred login method (password, passkey, security_key, recovery_key)")
    available_login_methods: list[str] = Field(..., description="List of available login methods")
    tfa_app_name: Optional[str] = Field(None, description="Name of the 2FA app if user has 2FA enabled")
    user_email_salt: str = Field(..., description="Salt for generating lookup hash (real for existing users, random for non-existing users)")
    tfa_enabled: bool = Field(False, description="Whether 2FA is enabled for this user")
    stay_logged_in: bool = Field(False, description="Echo back the stay_logged_in preference from request")
    
    class Config:
        json_schema_extra = {
            "example": {
                "login_method": "password",
                "available_login_methods": ["password", "recovery_key"],
                "tfa_app_name": "Google Authenticator",
                "user_email_salt": "base64_encoded_salt",
                "tfa_enabled": True
            }
        }

# Passkey Registration Schemas
class PasskeyRegistrationInitiateRequest(BaseModel):
    """Request to initiate passkey registration"""
    hashed_email: str = Field(..., description="Hashed email for user lookup")
    user_id: Optional[str] = Field(None, description="User ID if user already exists (for adding passkey to existing account)")

class PasskeyRegistrationInitiateResponse(BaseModel):
    """Response with WebAuthn challenge and options for passkey registration"""
    success: bool = Field(..., description="Whether the initiation was successful")
    challenge: str = Field(..., description="Base64-encoded challenge for WebAuthn")
    rp: Dict[str, str] = Field(..., description="Relying Party information (id, name)")
    user: Dict[str, Any] = Field(..., description="User information for WebAuthn (id, name, displayName)")
    pubKeyCredParams: list[Dict[str, Any]] = Field(..., description="Public key credential parameters")
    timeout: Optional[int] = Field(60000, description="Timeout in milliseconds")
    attestation: str = Field("direct", description="Attestation conveyance preference")
    authenticatorSelection: Dict[str, Any] = Field(..., description="Authenticator selection criteria")
    message: Optional[str] = Field(None, description="Optional message")

class PasskeyRegistrationCompleteRequest(BaseModel):
    """Request to complete passkey registration"""
    credential_id: str = Field(..., description="Base64-encoded credential ID")
    attestation_response: Dict[str, Any] = Field(..., description="WebAuthn attestation response")
    client_data_json: str = Field(..., description="Base64-encoded client data JSON")
    authenticator_data: str = Field(..., description="Base64-encoded authenticator data")
    hashed_email: str = Field(..., description="Hashed email for user lookup")
    username: str = Field(..., description="User's username")
    invite_code: str = Field(..., description="Invite code for signup")
    encrypted_email: str = Field(..., description="Client-side encrypted email")
    user_email_salt: str = Field(..., description="Salt used for email encryption (base64)")
    encrypted_master_key: str = Field(..., description="Encrypted master key wrapped with PRF-derived key")
    key_iv: str = Field(..., description="IV used for master key encryption (base64)")
    salt: str = Field(..., description="Salt used for key derivation (user_email_salt)")
    lookup_hash: str = Field(..., description="Hash of PRF signature + salt for authentication")
    language: str = Field("en", description="User's preferred language")
    darkmode: bool = Field(False, description="User's dark mode preference")
    prf_enabled: bool = Field(..., description="Whether PRF extension was enabled in the credential")

class PasskeyRegistrationCompleteResponse(BaseModel):
    """Response for passkey registration completion"""
    success: bool = Field(..., description="Whether the registration was successful")
    message: str = Field(..., description="Response message")
    user: Optional[Dict[str, Any]] = Field(None, description="User data if account was created")

# Passkey Assertion (Login) Schemas
class PasskeyAssertionInitiateRequest(BaseModel):
    """Request to initiate passkey assertion (login)"""
    hashed_email: Optional[str] = Field(None, description="Hashed email for user lookup (optional for resident credentials)")

class PasskeyAssertionInitiateResponse(BaseModel):
    """Response with WebAuthn challenge and options for passkey assertion"""
    success: bool = Field(..., description="Whether the initiation was successful")
    challenge: str = Field(..., description="Base64-encoded challenge for WebAuthn")
    rp: Dict[str, str] = Field(..., description="Relying Party information (id, name)")
    timeout: Optional[int] = Field(60000, description="Timeout in milliseconds")
    allowCredentials: list[Dict[str, Any]] = Field(..., description="List of allowed credentials (empty for resident credentials)")
    userVerification: str = Field("preferred", description="User verification requirement")
    message: Optional[str] = Field(None, description="Optional message")

class PasskeyAssertionVerifyRequest(BaseModel):
    """Request to verify passkey assertion (login)"""
    credential_id: str = Field(..., description="Base64-encoded credential ID")
    assertion_response: Dict[str, Any] = Field(..., description="WebAuthn assertion response")
    client_data_json: str = Field(..., description="Base64-encoded client data JSON")
    authenticator_data: str = Field(..., description="Base64-encoded authenticator data")
    hashed_email: Optional[str] = Field(None, description="Hashed email (optional if using resident credential)")
    email_encryption_key: Optional[str] = Field(None, description="Client-derived key for email decryption (SHA256(email + user_email_salt))")
    stay_logged_in: bool = Field(False, description="Whether to keep user logged in for extended period")
    session_id: Optional[str] = Field(None, description="Browser session ID for device fingerprint")

class PasskeyAssertionVerifyResponse(BaseModel):
    """Response for passkey assertion verification"""
    success: bool = Field(..., description="Whether the assertion was successful")
    message: str = Field(..., description="Response message")
    user_id: Optional[str] = Field(None, description="User ID if authentication succeeded")
    hashed_email: Optional[str] = Field(None, description="Hashed email if authentication succeeded")
    encrypted_email: Optional[str] = Field(None, description="Encrypted email for client decryption")
    encrypted_master_key: Optional[str] = Field(None, description="Encrypted master key")
    key_iv: Optional[str] = Field(None, description="IV for master key decryption")
    salt: Optional[str] = Field(None, description="Salt for key derivation")
    user_email_salt: Optional[str] = Field(None, description="User email salt")
    auth_session: Optional[Dict[str, Any]] = Field(None, description="Session data for login finalization")
