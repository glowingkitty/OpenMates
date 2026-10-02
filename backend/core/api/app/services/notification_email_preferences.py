"""Durable eligibility and verified address lookup for optional notification email."""

from __future__ import annotations

import json
from typing import Any

from backend.core.api.app.utils.newsletter_utils import hash_email


NOTIFICATION_USER_FIELDS = [
    "id", "status", "hashed_email", "vault_key_id", "encrypted_notification_email",
    "email_notifications_enabled", "email_notification_preferences",
    "email_notification_preference_choices", "backup_reminder_interval_days", "language", "darkmode",
]
DEFAULT_NOTIFICATION_PREFERENCES = {
    "aiResponses": True,
    "workflowRuns": True,
    "includeContent": False,
    "backupReminder": False,
    "webhookChats": False,
}
NOTIFICATION_CATEGORIES = frozenset(("aiResponses", "workflowRuns"))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def notification_category_enabled(user: dict[str, Any] | None, category: str) -> bool:
    """Require master permission and a category choice; legacy workflow mail stays off."""
    if category not in NOTIFICATION_CATEGORIES or not isinstance(user, dict):
        return False
    if user.get("email_notifications_enabled") is not True:
        return False
    choices = _json_object(user.get("email_notification_preference_choices"))
    master_choice = choices.get("enabled")
    category_choice = choices.get(category)
    if isinstance(master_choice, dict) and master_choice.get("source") == "user" and master_choice.get("value") is False:
        return False
    if isinstance(category_choice, dict) and category_choice.get("source") == "user" and category_choice.get("value") is False:
        return False
    preferences = _json_object(user.get("email_notification_preferences"))
    return preferences.get(category, category == "aiResponses") is True


def preview_enabled(user: dict[str, Any] | None) -> bool:
    """Content is never included just because notification email is enabled."""
    if not isinstance(user, dict) or user.get("email_notifications_enabled") is not True:
        return False
    choices = _json_object(user.get("email_notification_preference_choices"))
    master_choice = choices.get("enabled")
    if isinstance(master_choice, dict) and master_choice.get("source") == "user" and master_choice.get("value") is False:
        return False
    choice = choices.get("includeContent")
    return (
        _json_object(user.get("email_notification_preferences")).get("includeContent") is True
        and isinstance(choice, dict)
        and choice.get("value") is True
        and choice.get("source") == "user"
    )


async def load_notification_user(directus: Any, user_id: str) -> dict[str, Any] | None:
    """Read from Directus, bypassing potentially stale or missing user cache."""
    if not user_id:
        return None
    user = await directus.get_user_fields_direct(user_id, NOTIFICATION_USER_FIELDS, no_cache=True)
    if not isinstance(user, dict) or user.get("id") != user_id:
        return None
    return user


async def resolve_notification_email(directus: Any, encryption: Any, user: dict[str, Any]) -> str | None:
    """Use only the verified account address; never trust a caller-supplied address."""
    user_id = user.get("id")
    hashed_email = user.get("hashed_email")
    if not user_id or not hashed_email:
        return None
    rows = await directus.get_items(
        "account_contact_emails",
        params={
            "filter": {"user_id": {"_eq": user_id}, "hashed_email": {"_eq": hashed_email},
                       "purpose": {"_eq": "account_lifecycle"}, "verified_at": {"_nnull": True}},
            "fields": "user_id,hashed_email,purpose,verified_at,encrypted_email_address",
            "limit": 1,
        },
        admin_required=True,
        raise_on_error=True,
        no_cache=True,
    )
    row = rows[0] if rows else None
    if not isinstance(row, dict) or row.get("user_id") != user_id or row.get("hashed_email") != hashed_email:
        return None
    if row.get("purpose") != "account_lifecycle" or not row.get("verified_at"):
        return None
    ciphertext = row.get("encrypted_email_address")
    if not ciphertext:
        return None
    email = await encryption.decrypt_account_contact_email(ciphertext)
    if not isinstance(email, str) or not email.strip():
        return None
    email = email.strip()
    # The global block endpoint hashes lowercased, trimmed email. Account
    # hashed_email can reflect the original signup casing, so derive it anew.
    ignored = await directus.get_items(
        "ignored_emails",
        params={"filter": {"hashed_email": {"_eq": hash_email(email.lower())}},
                "fields": "id", "limit": 1},
        admin_required=True,
        raise_on_error=True,
        no_cache=True,
    )
    return None if ignored else email
