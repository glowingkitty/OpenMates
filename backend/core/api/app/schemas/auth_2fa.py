from pydantic import BaseModel
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
    provider: str  # e.g., "Google Authenticator", "Microsoft Authenticator", etc.

class Setup2FAProviderResponse(BaseModel):
    success: bool
    message: str