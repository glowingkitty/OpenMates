"""
Account Recovery Schemas

Request and response models for the account reset flow.

This is a LAST RESORT for users who lost ALL login methods AND their recovery key.
Users who have their recovery key should use "Login with recovery key" instead.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


# ============================================================================
# Request Schemas
# ============================================================================

class RecoveryRequestRequest(BaseModel):
    """
    Request to initiate account reset.
    Sends a verification code to the provided email.
    """
    email: str = Field(..., description="Email address associated with the account")
    language: str = Field(default="en", description="Preferred language for email")
    darkmode: bool = Field(default=False, description="Darkmode preference for email template")


class RecoveryFullResetRequest(BaseModel):
    """
    Complete account reset with verification token.
    
    IMPORTANT: This permanently deletes all client-encrypted data:
    - All chats and messages
    - All app settings and memories
    - All embeds
    
    Server-encrypted data (credits, username, subscription) is preserved.
    
    User must explicitly acknowledge data loss AND provide the verification token
    obtained from the verify-code endpoint.
    """
    email: str = Field(..., description="Email address")
    verification_token: str = Field(..., description="Token from verify-code endpoint")
    acknowledge_data_loss: bool = Field(
        ..., 
        description="User must confirm they understand ALL data will be permanently deleted"
    )
    
    # New account setup (similar to signup)
    new_login_method: str = Field(..., description="'password' or 'passkey'")
    hashed_email: str = Field(..., description="SHA256(email) for lookup")
    encrypted_email: str = Field(..., description="Email encrypted with email_encryption_key")
    encrypted_email_with_master_key: str = Field(
        ..., 
        description="Email encrypted with master key (for passkey login)"
    )
    user_email_salt: str = Field(..., description="Salt for email encryption key derivation")
    lookup_hash: str = Field(..., description="Hash for authentication")
    encrypted_master_key: str = Field(..., description="Master key wrapped with credentials")
    salt: str = Field(..., description="Salt for key derivation")
    key_iv: str = Field(..., description="IV for AES-GCM encryption")
    
    # For passkey: additional fields (optional)
    passkey_credential: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Passkey credential data (for passkey login method)"
    )


# ============================================================================
# Response Schemas
# ============================================================================

class RecoveryVerifyRequest(BaseModel):
    """
    Verify the recovery code before showing login method selection.
    """
    email: str = Field(..., description="Email address associated with the account")
    code: str = Field(..., description="6-digit verification code from email")


class RecoveryRequestResponse(BaseModel):
    """Response after requesting account reset code."""
    success: bool
    message: str
    error_code: Optional[str] = None


class RecoveryVerifyResponse(BaseModel):
    """Response after verifying recovery code."""
    success: bool
    message: str
    verification_token: Optional[str] = Field(
        default=None,
        description="One-time token to use for the reset request (valid 10 minutes)"
    )
    error_code: Optional[str] = None


class PreservedDataInfo(BaseModel):
    """
    Information about what data will be preserved during reset.
    Shown to user before they confirm the reset.
    """
    username: Optional[str] = None
    credits: int = 0
    has_subscription: bool = False
    subscription_credits: Optional[int] = None
    has_2fa: bool = False
    has_profile_image: bool = False
    account_id: Optional[str] = None


class RecoveryCompleteResponse(BaseModel):
    """Response after completing account reset."""
    success: bool
    message: str
    
    # If successful, return user info for immediate login
    user_id: Optional[str] = None
    username: Optional[str] = None
    
    error_code: Optional[str] = None
