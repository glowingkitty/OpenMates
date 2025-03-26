from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Setup2FAResponse(BaseModel):
    success: bool
    message: str
    secret: Optional[str] = None
    otpauth_url: Optional[str] = None

class Verify2FACodeRequest(BaseModel):
    code: str

class Verify2FACodeResponse(BaseModel):
    success: bool
    message: str

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