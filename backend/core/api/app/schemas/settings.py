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

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "threshold": 200,
                "amount": 10000,
                "currency": "eur"
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