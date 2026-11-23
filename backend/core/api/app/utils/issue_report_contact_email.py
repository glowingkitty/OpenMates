"""
Issue-report contact email helpers.

Authenticated issue reports need a reliable server-side contact email even when
the browser submits before its decrypted account email has loaded. This module
keeps that resolution separate from the large settings route so unit tests can
exercise the behavior without importing the full FastAPI/Celery route graph.
"""

from __future__ import annotations

import logging
import re
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


# AI test-user accounts sign up as `omtestuser-<16 hex>@inboxkitten.com` (production, and dev when the
# server admits that domain) or with that prefix at a Mailosaur test inbox (dev); see
# scripts/ai_test_users_accounts.py. Mailosaur inboxes only ever belong to test accounts.
AI_TEST_USER_LOCAL_PART = re.compile(r"^omtestuser-[0-9a-f]{16}$")
AI_TEST_USER_DOMAINS = ("inboxkitten.com",)
TEST_INBOX_DOMAIN = "mailosaur.net"


def is_ai_test_user_email(email: Optional[str]) -> bool:
    """True for a contact address of an AI test-user account (or any Mailosaur test inbox)."""
    local, _, domain = (email or "").strip().lower().rpartition("@")
    if not local or not domain:
        return False
    if domain == TEST_INBOX_DOMAIN or domain.endswith("." + TEST_INBOX_DOMAIN):
        return True
    return domain in AI_TEST_USER_DOMAINS and bool(AI_TEST_USER_LOCAL_PART.match(local))


async def reporter_is_test_account(
    directus_service: Any, user_id: Optional[str], contact_email: Optional[str] = None
) -> bool:
    """True when the report comes from an AI test-user account.

    Owner, 20 Nov 2026: test accounts never send issue emails (admin notice and reporter
    confirmation); their reports are still stored and readable. Owner, 23 Nov 2026: only real
    users' reports email Marco, so two independent signals count: the `users.is_test_account`
    label, and the AI test-user contact address (which also covers accounts whose label is
    missing, e.g. a gift card created without `marks_test_account`). A failed label lookup
    falls back to the address check alone.
    """
    if is_ai_test_user_email(contact_email):
        return True
    if not user_id:
        return False
    fields = await directus_service.get_user_fields_direct(user_id, ["is_test_account"])
    if fields is None:
        logger.warning("Test-account label unreadable for issue report user %s; sending emails", user_id[:8])
        return False
    return fields.get("is_test_account") is True
