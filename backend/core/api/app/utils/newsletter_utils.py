"""
Utility functions for newsletter functionality.

This module provides shared helper functions for newsletter operations
to avoid circular imports.
"""

import hashlib
import base64
import logging
from typing import Literal
from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)

# Valid values for newsletter_subscribers.user_registration_status
NewsletterUserStatus = Literal["not_signed_up", "signup_incomplete", "signup_complete"]


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


async def update_newsletter_registration_status(
    hashed_email: str,
    status: NewsletterUserStatus,
    directus_service: DirectusService,
) -> bool:
    """
    Update user_registration_status on a newsletter_subscribers record identified by hashed_email.

    Called from two places:
    - newsletter.py confirm handler: sets status based on whether matching user exists at subscribe time
    - auth_password.py user creation: updates existing subscriber record when user signs up

    Args:
        hashed_email: SHA-256/base64 hash of the subscriber's email
        status: One of "not_signed_up", "signup_incomplete", "signup_complete"
        directus_service: DirectusService instance

    Returns:
        True if updated successfully (or record not found — not an error), False on unexpected error.
    """
    try:
        collection_url = f"{directus_service.base_url}/items/newsletter_subscribers"
        # Look up subscriber by hashed_email
        resp = await directus_service._make_api_request(
            "GET",
            collection_url,
            params={"filter[hashed_email][_eq]": hashed_email, "fields": "id", "limit": 1},
        )
        if resp.status_code != 200:
            logger.warning(
                f"newsletter status update: lookup failed (HTTP {resp.status_code}) for hash {hashed_email[:16]}..."
            )
            return False

        items = resp.json().get("data", [])
        if not items:
            # No subscriber record found — not an error (user may not be subscribed)
            return True

        subscriber_id = items[0]["id"]
        patch_resp = await directus_service._make_api_request(
            "PATCH",
            f"{collection_url}/{subscriber_id}",
            json={"user_registration_status": status},
        )
        if patch_resp.status_code >= 400:
            logger.error(
                f"newsletter status update: PATCH failed (HTTP {patch_resp.status_code}) "
                f"for subscriber {subscriber_id}: {patch_resp.text}"
            )
            return False

        logger.info(
            f"newsletter status update: set status='{status}' for subscriber {subscriber_id} "
            f"(hash {hashed_email[:16]}...)"
        )
        return True

    except Exception as e:
        logger.error(
            f"newsletter status update: unexpected error for hash {hashed_email[:16]}...: {e}",
            exc_info=True,
        )
        return False


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
