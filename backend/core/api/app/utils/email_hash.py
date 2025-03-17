import hashlib
import hmac
import os
from typing import Optional

# This key should be stored securely and consistently for all hashes
# In production, fetch this from Vault
EMAIL_HASH_KEY = os.environ.get("EMAIL_HASH_KEY", "temporary_email_hash_key")

def hash_email(email: str) -> str:
    """
    Creates a consistent HMAC-SHA256 hash of an email address.
    This is used for username/login lookup without storing plaintext emails.
    """
    if not email:
        return ""
        
    # Normalize email to lowercase
    normalized_email = email.strip().lower()
    
    # Create the HMAC hash
    hash_obj = hmac.new(
        key=EMAIL_HASH_KEY.encode('utf-8'),
        msg=normalized_email.encode('utf-8'),
        digestmod=hashlib.sha256
    )
    
    # Return hex digest
    return hash_obj.hexdigest()

def verify_email_hash(email: str, stored_hash: str) -> bool:
    """
    Verifies if a plaintext email matches a stored hash.
    """
    return hmac.compare_digest(hash_email(email), stored_hash)
