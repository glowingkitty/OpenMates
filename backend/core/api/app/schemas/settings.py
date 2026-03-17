from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

class UsernameUpdateRequest(BaseModel):
    """Request model for updating the user's username."""
    username: str  # New plain-text username (3–20 chars, letters/numbers/dots/underscores)

    class Config:
        json_schema_extra = {
            "example": {
                "username": "jane.doe"
            }
        }


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


# ─── Valid period strings for auto-deletion (chats and files) ────────────────
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

# ─── Valid period strings for usage data auto-deletion ────────────────────────
# Usage data has a longer minimum retention (90 days) than chats.
# The platform default is 3 years (1095 days) when the user has not configured a period.
# "never" = null = apply platform default (1095 days); users cannot set truly unlimited retention
# as usage data must eventually be purged for GDPR compliance.
USAGE_DEFAULT_RETENTION_DAYS: int = 1095  # 3 years — platform default when field is null

_USAGE_PERIOD_TO_DAYS: dict[str, Optional[int]] = {
    '90d':   90,
    '6m':    180,
    '1y':    365,
    '2y':    730,
    '3y':    1095,
    '5y':    1825,
    'never': None,  # null → platform default (USAGE_DEFAULT_RETENTION_DAYS)
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


class AutoDeleteUsageRequest(BaseModel):
    """
    Request body for POST /v1/settings/auto-delete-usage.

    Accepts a period string (e.g. "1y", "3y", "never").  "never" stores null,
    which tells the auto-delete task to apply the platform default retention of
    3 years (USAGE_DEFAULT_RETENTION_DAYS = 1095 days).

    Minimum: 90d.  Available options mirror the frontend PERIOD_OPTIONS_LONG list.
    """
    period: str  # One of: "90d", "6m", "1y", "2y", "3y", "5y", "never"

    @field_validator('period')
    @classmethod
    def validate_period(cls, v: str) -> str:
        """Reject unknown period strings immediately."""
        if v not in _USAGE_PERIOD_TO_DAYS:
            allowed = ', '.join(sorted(_USAGE_PERIOD_TO_DAYS.keys()))
            raise ValueError(f"Invalid usage period '{v}'. Must be one of: {allowed}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "period": "3y"
            }
        }


def period_to_days(period: str) -> Optional[int]:
    """Convert a chat/files UI period string to an integer day count (None for 'never')."""
    return _PERIOD_TO_DAYS.get(period)


def usage_period_to_days(period: str) -> Optional[int]:
    """Convert a usage-data UI period string to an integer day count (None for 'never')."""
    return _USAGE_PERIOD_TO_DAYS.get(period)


# ─── AI Model Defaults ────────────────────────────────────────────────────────

class AiModelDefaultsRequest(BaseModel):
    """
    Request body for POST /v1/settings/ai-model-defaults.

    Allows the user to set a preferred default model for simple and complex AI
    requests, which overrides auto-selection for all their future messages.
    Setting a field to None resets it to auto-select.

    Model ID format: "provider/model_id" (e.g., "anthropic/claude-haiku-4-5-20251001").
    """
    default_ai_model_simple: Optional[str] = Field(
        default=None,
        description="Default model for simple requests. Null = auto-select. Format: 'provider/model_id'."
    )
    default_ai_model_complex: Optional[str] = Field(
        default=None,
        description="Default model for complex requests. Null = auto-select. Format: 'provider/model_id'."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "default_ai_model_simple": "anthropic/claude-haiku-4-5-20251001",
                "default_ai_model_complex": "anthropic/claude-opus-4-6"
            }
        }


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


# ─── Storage File Listing ──────────────────────────────────────────────────────

class StorageFileItem(BaseModel):
    """
    A single uploaded file record as returned by GET /v1/settings/storage/files.

    Represents one row in the upload_files Directus collection, enriched with
    the category name derived from its MIME type.
    """
    id: str = Field(description="Directus UUID of the upload_files record (used for deletion)")
    embed_id: str = Field(description="Embed UUID — used to construct the view URL (/v1/settings/storage/files/{embed_id}/view)")
    original_filename: str = Field(description="Original filename as provided by the browser at upload time")
    content_type: str = Field(description="Detected MIME type (e.g. 'image/jpeg', 'application/pdf')")
    category: str = Field(description="Classified category: images, videos, audio, pdf, code, docs, sheets, archives, other")
    file_size_bytes: int = Field(default=0, description="Pre-encryption file size in bytes")
    variant_count: int = Field(default=1, description="Number of S3 variants stored (1 for PDF/audio, 3 for images)")
    created_at: Optional[int] = Field(default=None, description="Unix timestamp (seconds) when the file was uploaded")


class StorageFilesListResponse(BaseModel):
    """Response for GET /v1/settings/storage/files."""
    files: List[StorageFileItem] = Field(default_factory=list)
    total_count: int = Field(default=0, description="Total number of files in the response (after category filter)")
    total_bytes: int = Field(default=0, description="Total bytes for the files in the response")


# ─── Storage File Deletion ─────────────────────────────────────────────────────

class StorageDeleteFilesRequest(BaseModel):
    """
    Request body for DELETE /v1/settings/storage/files.

    Three mutually-exclusive scopes:
      - single:   Delete one file by its upload_files Directus ID.
      - category: Delete all files matching a category name (images, pdf, etc.).
      - all:      Delete every upload_files record for the current user.
    """
    scope: str = Field(description="Deletion scope: 'single', 'category', or 'all'")
    file_id: Optional[str] = Field(default=None, description="Directus ID of the upload_files record (required when scope='single')")
    category: Optional[str] = Field(default=None, description="Category name to delete (required when scope='category')")


class StorageDeleteFilesResponse(BaseModel):
    """Response for DELETE /v1/settings/storage/files."""
    deleted_count: int = Field(default=0, description="Number of upload_files records deleted")
    bytes_freed: int = Field(default=0, description="Total bytes freed (sum of file_size_bytes for deleted records)")
