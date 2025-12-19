"""
Utility functions for newsletter functionality.

This module provides shared helper functions for newsletter operations
to avoid circular imports.
"""

import hashlib
import base64
import logging
from typing import Optional
from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)


def hash_email(email: str) -> str:
    """
    Hash email address using SHA-256 for lookup purposes.
    
    Args:
        email: Plaintext email address
        
    Returns:
        Base64-encoded SHA-256 hash of the email
    """
    email_bytes = email.encode('utf-8')
    hashed_email_buffer = hashlib.sha256(email_bytes).digest()
    return base64.b64encode(hashed_email_buffer).decode('utf-8')


async def check_ignored_email(hashed_email: str, directus_service: DirectusService) -> bool:
    """
    Check if an email hash is in the ignored_emails list.
    
    Args:
        hashed_email: SHA-256 hash of the email address (base64-encoded)
        directus_service: DirectusService instance
        
    Returns:
        True if email is ignored, False otherwise
    """
    try:
        collection_name = "ignored_emails"
        url = f"{directus_service.base_url}/items/{collection_name}"
        params = {"filter[hashed_email][_eq]": hashed_email}
        
        response = await directus_service._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            return len(items) > 0
        
        return False
    except Exception as e:
        logger.error(f"Error checking ignored email: {str(e)}", exc_info=True)
        return False
