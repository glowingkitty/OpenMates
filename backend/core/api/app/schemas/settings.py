from pydantic import BaseModel
from typing import Optional

class LanguageUpdateRequest(BaseModel):
    language: str

    class Config:
        json_schema_extra = {
            "example": {
                "language": "fr"
            }
        }

class DarkModeUpdateRequest(BaseModel):
    darkmode: bool

    class Config:
        json_schema_extra = {
            "example": {
                "darkmode": True
            }
        }

class AutoTopUpLowBalanceRequest(BaseModel):
    enabled: bool
    threshold: int
    amount: int
    currency: str
    totp_code: str  # 2FA TOTP code for verification

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "threshold": 1000,
                "amount": 10000,
                "currency": "eur",
                "totp_code": "123456"
            }
        }

# --- Response model for user email ---
class UserEmailResponse(BaseModel):
    email: str

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com"
            }
        }