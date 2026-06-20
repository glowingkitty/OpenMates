"""
Utilities for public issue-report references.

The Directus issue UUID remains the durable internal identifier. New report
submissions also receive a short, non-ambiguous alias that users can read aloud
or paste into support conversations. These helpers keep route filters and ID
generation consistent across settings and admin/debug endpoints.
"""

from __future__ import annotations

import re
import secrets


SHORT_ISSUE_ID_LENGTH = 5
SHORT_ISSUE_ID_MAX_ATTEMPTS = 12
SHORT_ISSUE_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SHORT_ISSUE_ID_RE = re.compile(rf"^[{SHORT_ISSUE_ID_ALPHABET}]{{{SHORT_ISSUE_ID_LENGTH}}}$")


def generate_short_issue_id() -> str:
    """Return a random 5-character public issue reference."""
    return "".join(secrets.choice(SHORT_ISSUE_ID_ALPHABET) for _ in range(SHORT_ISSUE_ID_LENGTH))


def normalize_issue_identifier(identifier: str) -> str:
    """Normalize a user-provided UUID or short issue reference."""
    cleaned = identifier.strip()
    return cleaned.upper() if is_short_issue_id(cleaned) else cleaned


def is_uuid_issue_id(identifier: str) -> bool:
    """Return True when the identifier is a UUID-shaped internal issue ID."""
    return bool(_UUID_RE.fullmatch(identifier.strip()))


def is_short_issue_id(identifier: str) -> bool:
    """Return True when the identifier is a valid public short issue ID."""
    return bool(_SHORT_ISSUE_ID_RE.fullmatch(identifier.strip().upper()))


def issue_identifier_filter(identifier: str) -> dict[str, dict[str, str]]:
    """Build a Directus filter for either the UUID or short issue ID field."""
    normalized = normalize_issue_identifier(identifier)
    if is_short_issue_id(normalized):
        return {"short_issue_id": {"_eq": normalized}}
    return {"id": {"_eq": normalized}}


def issue_identifier_query_params(identifier: str) -> dict[str, str | int]:
    """Build legacy bracket-style Directus query params for scripts/services."""
    normalized = normalize_issue_identifier(identifier)
    field = "short_issue_id" if is_short_issue_id(normalized) else "id"
    return {f"filter[{field}][_eq]": normalized, "limit": 1}


def is_short_issue_id_conflict_error(error_text: str) -> bool:
    """Return True when a Directus create failure appears to be a short-ID collision."""
    lowered = error_text.lower()
    return "short_issue_id" in lowered and any(
        token in lowered for token in ("unique", "duplicate", "already exists", "constraint")
    )


async def create_issue_record_with_short_id(directus_service, issue_data: dict) -> dict:
    """Create an issue record with a unique public short issue ID."""
    last_error = ""
    for _attempt in range(SHORT_ISSUE_ID_MAX_ATTEMPTS):
        short_issue_id = generate_short_issue_id()
        existing = await directus_service.get_items(
            "issues",
            {"filter": {"short_issue_id": {"_eq": short_issue_id}}, "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        if existing:
            last_error = f"short issue ID collision: {short_issue_id}"
            continue

        success, issue_record = await directus_service.create_item(
            "issues",
            {**issue_data, "short_issue_id": short_issue_id},
            admin_required=True,
        )
        if success and issue_record:
            issue_record.setdefault("short_issue_id", short_issue_id)
            return issue_record

        error_text = issue_record.get("text", str(issue_record)) if isinstance(issue_record, dict) else str(issue_record)
        last_error = error_text or "unknown Directus create error"
        if not is_short_issue_id_conflict_error(last_error):
            raise ValueError(f"Directus create_item failed: {last_error}")

    raise ValueError(f"Could not create issue record with a unique short issue ID: {last_error}")
