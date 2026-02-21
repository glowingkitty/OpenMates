from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

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


# ─── Storage Overview ─────────────────────────────────────────────────────────

class StorageCategoryBreakdown(BaseModel):
    """
    Storage usage broken down by a single file-type category.

    Each category maps to a group of MIME types so the frontend can display
    a per-app or per-type breakdown (e.g. Images, Videos, Audio, PDF, Code,
    Docs, Sheets, Archives, Other).
    """
    category: str = Field(description="Category name, e.g. 'images', 'videos', 'audio'")
    bytes_used: int = Field(default=0, description="Total bytes stored in this category")
    file_count: int = Field(default=0, description="Number of uploaded files in this category")


class StorageOverviewResponse(BaseModel):
    """
    Response model for GET /v1/settings/storage.

    Provides the current user's total storage usage, a per-category breakdown
    (for the Files app panel in account settings), the free tier, cost info,
    and the next scheduled billing date.

    Pricing model (mirrors storage_billing_tasks.py):
      - First 1 GB is always free.
      - 3 credits per GB per week above the free tier.
    """
    # ─── Totals ──────────────────────────────────────────────────────────────
    total_bytes: int = Field(default=0, description="Total bytes stored across all file types")
    total_files: int = Field(default=0, description="Total number of uploaded files")

    # ─── Free tier info ───────────────────────────────────────────────────────
    free_bytes: int = Field(
        default=1_073_741_824,
        description="Free storage allowance in bytes (always 1 GB = 1,073,741,824 bytes)"
    )

    # ─── Billing ─────────────────────────────────────────────────────────────
    billable_gb: int = Field(
        default=0,
        description="Number of GB above the free tier (ceiling). 0 if within free tier."
    )
    credits_per_gb_per_week: int = Field(
        default=3,
        description="Credits charged per billable GB per week"
    )
    weekly_cost_credits: int = Field(
        default=0,
        description="Total credits charged per week. 0 if within free tier."
    )
    next_billing_date: Optional[int] = Field(
        default=None,
        description="Unix timestamp of the next weekly billing date (next Sunday 03:00 UTC). "
                    "None if the user is within the free tier."
    )
    last_billed_at: Optional[int] = Field(
        default=None,
        description="Unix timestamp of the last successful billing run for this user."
    )

    # ─── Per-category breakdown ───────────────────────────────────────────────
    breakdown: List[StorageCategoryBreakdown] = Field(
        default_factory=list,
        description="Storage usage broken down by file-type category."
    )
