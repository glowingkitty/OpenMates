# backend/shared/python_utils/encrypted_slug_metadata.py
#
# Shared validation for privacy-preserving object slugs. The backend stores only
# client ciphertext plus a keyed blind lookup hash; plaintext private slugs must
# never become durable Directus metadata. Directus helpers use this module before
# writing workflow, project, plan, task, or chat slug metadata.

from __future__ import annotations

import re
from typing import Any


SLUG_METADATA_FIELDS = ("encrypted_slug", "slug_lookup_hash")
PLAINTEXT_SLUG_FIELDS = ("slug", "plaintext_slug")
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
UNIQUE_ERROR_MARKERS = (
    "record_not_unique",
    "duplicate key",
    "has to be unique",
    "violates unique constraint",
    "unique constraint",
)
SLUG_UNIQUE_ERROR_MARKERS = ("slug", "slug_lookup_hash", "slug_hash")


class DuplicateObjectSlugError(ValueError):
    """Raised when a private slug lookup hash already exists in its scope."""


def is_sha256_hex(value: str | None) -> bool:
    return bool(value and SHA256_HEX_RE.fullmatch(value))


def is_unique_violation(value: Any) -> bool:
    """Return True when a Directus/Postgres error reports a unique conflict."""

    text = _error_text(value)
    return any(marker in text for marker in UNIQUE_ERROR_MARKERS)


def is_slug_unique_violation(value: Any) -> bool:
    """Return True when a Directus/Postgres unique conflict targets slug indexes."""

    text = _error_text(value)
    return (
        any(marker in text for marker in UNIQUE_ERROR_MARKERS)
        and any(marker in text for marker in SLUG_UNIQUE_ERROR_MARKERS)
    )


def _error_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict):
        text = " ".join(str(item) for item in value.values())
    else:
        text = str(value)
    return text.lower()


def validate_encrypted_slug_metadata(payload: dict[str, Any], *, record_label: str) -> None:
    """Validate encrypted slug metadata without accepting plaintext slugs."""

    for field in PLAINTEXT_SLUG_FIELDS:
        if field in payload and payload.get(field) is not None:
            raise ValueError(f"{record_label} plaintext slug is not allowed")

    encrypted_slug_present = "encrypted_slug" in payload and payload.get("encrypted_slug") is not None
    slug_hash_present = "slug_lookup_hash" in payload and payload.get("slug_lookup_hash") is not None
    if encrypted_slug_present != slug_hash_present:
        raise ValueError(f"{record_label} encrypted_slug and slug_lookup_hash must be provided together")

    encrypted_slug = payload.get("encrypted_slug")
    if encrypted_slug_present and (not isinstance(encrypted_slug, str) or not encrypted_slug):
        raise ValueError(f"{record_label} encrypted_slug must be non-empty client ciphertext")

    slug_lookup_hash = payload.get("slug_lookup_hash")
    if slug_hash_present and (not isinstance(slug_lookup_hash, str) or not is_sha256_hex(slug_lookup_hash)):
        raise ValueError(f"{record_label} slug_lookup_hash must be lowercase SHA-256 hex")
