"""
Issue-report contact email helpers.

Authenticated issue reports need a reliable server-side contact email even when
the browser submits before its decrypted account email has loaded. This module
keeps that resolution separate from the large settings route so unit tests can
exercise the behavior without importing the full FastAPI/Celery route graph.
"""

from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)

ACCOUNT_CONTACT_EMAIL_COLLECTION = "account_contact_emails"


async def resolve_account_contact_email(
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
) -> Optional[str]:
    """Return the server-decryptable account contact email for an authenticated user."""
    try:
        contact_rows = await directus_service.get_items(
            ACCOUNT_CONTACT_EMAIL_COLLECTION,
            {
                "filter": {"user_id": {"_eq": user_id}},
                "fields": "encrypted_email_address",
                "limit": 1,
            },
            admin_required=True,
        )
        if not contact_rows:
            logger.warning("No account contact email found for authenticated issue report user %s", user_id[:8])
            return None

        encrypted_email = (contact_rows[0] or {}).get("encrypted_email_address")
        if not encrypted_email:
            logger.warning("Account contact email row has no encrypted email for user %s", user_id[:8])
            return None

        contact_email = await encryption_service.decrypt_account_contact_email(encrypted_email)
        return contact_email.strip() if contact_email and contact_email.strip() else None
    except Exception as exc:
        logger.error(
            "Failed to resolve account contact email for authenticated issue report user %s: %s",
            user_id[:8],
            exc,
            exc_info=True,
        )
        return None
