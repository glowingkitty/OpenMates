from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field

AI_MODEL_DEFAULT_FIELDS = (
    "default_ai_model_simple",
    "default_ai_model_complex",
    "default_ai_model_most_demanding",
)
AI_PREFERENCE_FIELDS = (
    *AI_MODEL_DEFAULT_FIELDS,
    "default_app_skill_models",
    "follow_up_suggestions_enabled",
    "recommendations_enabled",
)


class UserResponse(BaseModel):
    id: Optional[str] = None # User's primary key (UUID)
    account_id: Optional[str] = None # Public billing account identifier used on invoices and account recovery links
    username: str
    is_admin: bool
    credits: int
    profile_image_url: Optional[str] = None
    last_opened: Optional[str] = None
    tfa_app_name: Optional[str] = None
    tfa_enabled: bool
    consent_privacy_and_apps_default_settings: bool = False
    consent_mates_default_settings: bool = False
    language: Optional[str] = 'en' # User's preferred language
    darkmode: bool = False # User's dark mode preference
    ui_font: Optional[str] = 'lexend' # User's preferred web UI font
    invoice_counter: Optional[int] = None # Counter for invoice generation
    encrypted_key: Optional[str] = None # Master key encrypted with user's password
    encrypted_settings: Optional[str] = None # Opaque client-encrypted account preferences, including private bookmarks
    key_iv: Optional[str] = None # IV used for master key encryption (Web Crypto API)
    salt: Optional[str] = None # Salt used for password-based key derivation
    credential_version: Optional[int] = None # Password wrapper derivation version
    user_email_salt: Optional[str] = None # Salt used for client-side email encryption
    # Low balance auto top-up fields
    auto_topup_low_balance_enabled: bool = False # Enable automatic one-time top-up when balance low
    auto_topup_low_balance_threshold: Optional[int] = None # Credit threshold that triggers auto top-up (fixed at 100 credits)
    auto_topup_low_balance_amount: Optional[int] = None # Credits to purchase when threshold crossed
    auto_topup_low_balance_currency: Optional[str] = None # Currency for auto top-up purchases
    # Refund policy consent — True if user has consented to the limited refund / withdrawal waiver
    # (set at signup, updated on each purchase). Used by frontend to skip redundant consent screens.
    has_accepted_refund_policy: bool = False
    # Storage tracking fields (used for billing display and auto-delete UI)
    storage_used_bytes: int = 0 # Total S3 storage used in bytes
    # Auto-deletion settings (privacy)
    auto_delete_chats_after_days: Optional[int] = None # Days after which chats are auto-deleted (None = never)
    # Push notification fields (browser Web Push API)
    push_notification_enabled: bool = False # Whether push notifications are enabled for this user
    push_notification_subscription: Optional[str] = None # JSON string of browser PushSubscription
    push_notification_preferences: Optional[dict] = None # e.g. {"aiResponses": true}
    push_notification_banner_shown: bool = False # Whether the "Enable push?" banner has been dismissed
    has_free_testing_credits_grant: bool = False # Whether this account already received a Free testing grant
    # Server-side AI preferences. The server applies them on every request, so
    # clients must receive them to show the same state ("Auto" = None).
    default_ai_model_simple: Optional[str] = None
    default_ai_model_complex: Optional[str] = None
    default_ai_model_most_demanding: Optional[str] = None
    default_app_skill_models: dict[str, str] = Field(default_factory=dict)
    follow_up_suggestions_enabled: bool = True
    recommendations_enabled: bool = True
    # Furry Mode is disabled until any furry art is made by human artists.

    class Config:
        json_schema_extra = {
            "example": {
                "username": "johndoe",
                "is_admin": False,
                "credits": 100,
                "profile_image_url": "https://example.com/profile.jpg",
                "last_opened": "/signup/backup-codes",
                "tfa_app_name": "Google Authenticator",
                "tfa_enabled": True, # Added example value
                # Add examples for consent flags
                "consent_privacy_and_apps_default_settings": False,
                "consent_mates_default_settings": False,
                "language": "de", # Added example value
                "darkmode": True, # Added example value
                "ui_font": "figtree",
                "invoice_counter": 5, # Added example value
                "encrypted_key": "encrypted_master_key_example",
                "salt": "salt_example",
                "user_email_salt": "email_salt_example"
            }
        }


def ai_preference_fields(user_data: Mapping[str, Any]) -> dict[str, Any]:
    """Saved AI preferences for a full UserResponse, read from cached or Directus user data.

    Every login and session response must carry these: the server applies the
    stored values to each request, so a response without them makes clients
    show "Auto" while the server still routes to the saved model.
    """
    return {
        **{field: user_data.get(field) for field in AI_MODEL_DEFAULT_FIELDS},
        "default_app_skill_models": user_data.get("default_app_skill_models") or {},
        "follow_up_suggestions_enabled": user_data.get("follow_up_suggestions_enabled") is not False,
        "recommendations_enabled": user_data.get("recommendations_enabled") is not False,
    }
