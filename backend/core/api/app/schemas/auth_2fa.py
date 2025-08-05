from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Setup2FAInitiateRequest(BaseModel):
    """Request to initiate 2FA setup with email encryption key"""
    email_encryption_key: Optional[str] = None  # Client-derived key for email decryption

class Setup2FAResponse(BaseModel):
    success: bool
    message: str
    secret: Optional[str] = None
    otpauth_url: Optional[str] = None

# Renamed for clarity: Used during initial 2FA setup/signup
class VerifySignup2FARequest(BaseModel):
    code: str

# Renamed for clarity: Used during initial 2FA setup/signup
class VerifySignup2FAResponse(BaseModel):
    success: bool
    message: str

# New models for verifying 2FA due to device mismatch
class VerifyDevice2FARequest(BaseModel):
    tfa_code: str = Field(..., description="The 6-digit code from the user's authenticator app")

class VerifyDevice2FAResponse(BaseModel):
    success: bool = Field(..., description="Whether the device verification was successful")
    message: str = Field(..., description="Response message")

class BackupCodesResponse(BaseModel):
    success: bool
    message: str
    backup_codes: List[str] = []

class ConfirmCodesStoredRequest(BaseModel):
    confirmed: bool

class ConfirmCodesStoredResponse(BaseModel):
    success: bool
    message: str

class Setup2FAProviderRequest(BaseModel):
    provider: str = Field(
        ...,  # Ellipsis indicates the field is required
        min_length=3, 
        max_length=40, 
        description="Name of the 2FA app used, e.g., 'Google Authenticator'"
    )

class Setup2FAProviderResponse(BaseModel):
    success: bool
    message: str
