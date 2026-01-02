from pydantic import BaseModel, Field
from typing import Optional


class ConfirmRecoveryKeyStoredRequest(BaseModel):
    """
    Request model for confirming that the recovery key has been stored by the user.
    Includes the lookup hash and wrapped master key for server storage.
    """
    confirmed: bool = Field(..., description="User confirmation that they have stored the recovery key")
    lookup_hash: str = Field(..., description="SHA-256 hash of email + recovery key for authentication")
    wrapped_master_key: str = Field(..., description="Master key encrypted with key derived from recovery key")
    key_iv: str = Field(..., description="IV used for master key encryption (Web Crypto API)")
    salt: str = Field(..., description="Salt used for key derivation")


class ConfirmRecoveryKeyStoredResponse(BaseModel):
    """
    Response model for confirming that the recovery key has been stored.
    """
    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Success or error message")


class RegenerateRecoveryKeyRequest(BaseModel):
    """
    Request model for regenerating a recovery key.
    This replaces the old recovery key with a new one.
    Requires authentication via passkey or password first.
    """
    # New recovery key data
    new_lookup_hash: str = Field(..., description="SHA-256 hash of email + new recovery key for authentication")
    new_wrapped_master_key: str = Field(..., description="Master key encrypted with key derived from new recovery key")
    new_key_iv: str = Field(..., description="IV used for master key encryption (Web Crypto API)")
    new_salt: str = Field(..., description="Salt used for key derivation")
    
    # Old recovery key lookup hash (to remove from lookup_hashes array)
    old_lookup_hash: Optional[str] = Field(None, description="The old lookup hash to remove (if known)")


class RegenerateRecoveryKeyResponse(BaseModel):
    """
    Response model for regenerating a recovery key.
    """
    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Success or error message")