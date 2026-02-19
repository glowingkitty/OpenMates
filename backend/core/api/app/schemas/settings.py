from pydantic import BaseModel, field_validator
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

class TimezoneUpdateRequest(BaseModel):
    """Request model for updating user's timezone setting."""
    timezone: str  # IANA timezone format, e.g., 'Europe/Berlin', 'America/New_York'

    class Config:
        json_schema_extra = {
            "example": {
                "timezone": "Europe/Berlin"
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


# ─── Valid period strings for auto-deletion ───────────────────────────────────
# Maps UI period key → number of days. "never" maps to None (no deletion).
_PERIOD_TO_DAYS: dict[str, Optional[int]] = {
    '30d':   30,
    '60d':   60,
    '90d':   90,
    '6m':    180,
    '1y':    365,
    '2y':    730,
    '5y':    1825,
    'never': None,
}


class AutoDeleteChatsRequest(BaseModel):
    """
    Request body for POST /v1/settings/auto-delete-chats.

    The ``period`` field accepts the same string keys used in the frontend UI
    (e.g. "90d", "1y", "never"). The endpoint converts them to an integer day
    count (or null for "never") before persisting to Directus.
    """
    period: str  # One of: "30d", "60d", "90d", "6m", "1y", "2y", "5y", "never"

    @field_validator('period')
    @classmethod
    def validate_period(cls, v: str) -> str:
        """Reject unknown period strings immediately."""
        if v not in _PERIOD_TO_DAYS:
            allowed = ', '.join(sorted(_PERIOD_TO_DAYS.keys()))
            raise ValueError(f"Invalid period '{v}'. Must be one of: {allowed}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "period": "90d"
            }
        }


def period_to_days(period: str) -> Optional[int]:
    """Convert a UI period string to an integer day count (None for 'never')."""
    return _PERIOD_TO_DAYS.get(period)
