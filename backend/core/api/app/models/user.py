from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any

class User(BaseModel):
    id: str
    username: str
    vault_key_id: str
    is_admin: bool = False
    credits: int = 0
    profile_image_url: Optional[str] = None
    tfa_app_name: Optional[str] = None
    last_opened: Optional[str] = None
    last_online_timestamp: Optional[int] = None # Timestamp of last login/session activity
    # Consent fields (store timestamp as string)
    consent_privacy_and_apps_default_settings: Optional[str] = None
    consent_mates_default_settings: Optional[str] = None
    language: Optional[str] = 'en' # User's preferred language, default 'en'
    darkmode: bool = False # User's dark mode preference, default false
    gifted_credits_for_signup: Optional[int] = None # Gifted credits from signup invite
    encrypted_email_address: Optional[str] = None
    invoice_counter: Optional[int] = None # Counter for invoice generation
    encrypted_key: Optional[str] = None # Encrypted key for email decryption
    salt: Optional[str] = None # Salt for email encryption key derivation
    user_email_salt: Optional[str] = None # Salt used for client-side email encryption (base64)
    lookup_hashes: Optional[list] = None # List of lookup hashes for authentication
    account_id: Optional[str] = None # Account ID for invoice numbering