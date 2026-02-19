from pydantic import BaseModel
from typing import Optional

class UserResponse(BaseModel):
    id: Optional[str] = None # User's primary key (UUID)
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
    invoice_counter: Optional[int] = None # Counter for invoice generation
    encrypted_key: Optional[str] = None # Master key encrypted with user's password
    key_iv: Optional[str] = None # IV used for master key encryption (Web Crypto API)
    salt: Optional[str] = None # Salt used for password-based key derivation
    user_email_salt: Optional[str] = None # Salt used for client-side email encryption
    # Low balance auto top-up fields
    auto_topup_low_balance_enabled: bool = False # Enable automatic one-time top-up when balance low
    auto_topup_low_balance_threshold: Optional[int] = None # Credit threshold that triggers auto top-up (fixed at 100 credits)
    auto_topup_low_balance_amount: Optional[int] = None # Credits to purchase when threshold crossed
    auto_topup_low_balance_currency: Optional[str] = None # Currency for auto top-up purchases
    # Storage tracking fields (used for billing display and auto-delete UI)
    storage_used_bytes: int = 0 # Total S3 storage used in bytes
    # Auto-deletion settings (privacy)
    auto_delete_chats_after_days: Optional[int] = None # Days after which chats are auto-deleted (None = never)

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
                "invoice_counter": 5, # Added example value
                "encrypted_key": "encrypted_master_key_example",
                "salt": "salt_example",
                "user_email_salt": "email_salt_example"
            }
        }
