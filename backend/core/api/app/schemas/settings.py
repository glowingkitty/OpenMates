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
    email: Optional[str] = None  # Decrypted email from client for server-side encryption

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "threshold": 200,
                "amount": 10000,
                "currency": "eur",
                "email": "user@example.com"
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

class InvoiceResponse(BaseModel):
    """Response model for invoice information in billing overview"""
    id: str
    order_id: str
    date: str
    amount: str  # Decrypted amount (stored as string in Directus)
    credits_purchased: int
    is_gift_card: bool
    refund_status: Optional[str] = None  # 'none', 'pending', 'completed', 'failed'
    download_url: Optional[str] = None  # URL to download the invoice PDF

class BillingOverviewResponse(BaseModel):
    """Response model for billing overview endpoint"""
    payment_tier: int
    auto_topup_enabled: bool
    auto_topup_threshold: int
    auto_topup_amount: int
    auto_topup_currency: str
    invoices: list[InvoiceResponse]
