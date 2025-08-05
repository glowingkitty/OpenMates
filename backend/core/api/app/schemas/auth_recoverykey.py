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
    salt: str = Field(..., description="Salt used for key derivation")


class ConfirmRecoveryKeyStoredResponse(BaseModel):
    """
    Response model for confirming that the recovery key has been stored.
    """
    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Success or error message")