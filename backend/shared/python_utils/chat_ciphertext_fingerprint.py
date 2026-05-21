"""
Utilities for validating client-side chat ciphertext key fingerprints.

OpenMates message encryption prefixes new ciphertext with an `OM` header and a
short non-secret key fingerprint. Backend services cannot decrypt chat content,
but they can compare these fingerprints to reject mixed-key writes before they
are persisted. This keeps zero-knowledge storage intact while preventing
cross-device stale-key races from corrupting a chat.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


CHAT_CIPHERTEXT_MAGIC = b"OM"
CHAT_CIPHERTEXT_HEADER_LENGTH = 6

CHAT_METADATA_FINGERPRINT_FIELDS = (
    "encrypted_title",
    "encrypted_category",
    "encrypted_icon",
    "encrypted_chat_summary",
    "encrypted_chat_tags",
    "encrypted_follow_up_request_suggestions",
    "encrypted_top_recommended_apps_for_chat",
    "encrypted_active_focus_id",
)

MESSAGE_FINGERPRINT_FIELDS = (
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
)


@dataclass(frozen=True)
class FingerprintValidationResult:
    valid: bool
    incoming_fingerprint: str | None
    authoritative_fingerprint: str | None
    reason: str | None = None


def extract_chat_ciphertext_fingerprint(ciphertext: Any) -> str | None:
    """Return the 4-byte `OM` header fingerprint as lowercase hex, if present."""
    if not isinstance(ciphertext, str) or not ciphertext:
        return None

    try:
        decoded = base64.b64decode(ciphertext, validate=True)
    except Exception:
        return None

    if len(decoded) < CHAT_CIPHERTEXT_HEADER_LENGTH:
        return None
    if not decoded.startswith(CHAT_CIPHERTEXT_MAGIC):
        return None

    return decoded[2:CHAT_CIPHERTEXT_HEADER_LENGTH].hex()


def collect_message_fingerprints(message: dict[str, Any]) -> set[str]:
    """Collect all known ciphertext fingerprints from a message-like object."""
    fingerprints: set[str] = set()
    for field in MESSAGE_FINGERPRINT_FIELDS:
        fingerprint = extract_chat_ciphertext_fingerprint(message.get(field))
        if fingerprint:
            fingerprints.add(fingerprint)
    return fingerprints


def authoritative_chat_fingerprint(
    chat_metadata: dict[str, Any] | None,
    existing_messages: Iterable[dict[str, Any] | str] = (),
) -> str | None:
    """
    Pick the authoritative fingerprint for an existing chat.

    Chat metadata is preferred over messages because it is written alongside the
    chat's canonical encrypted key. If metadata lacks a modern `OM` header, fall
    back to the oldest stored message with a fingerprint.
    """
    for field in CHAT_METADATA_FINGERPRINT_FIELDS:
        fingerprint = extract_chat_ciphertext_fingerprint(
            (chat_metadata or {}).get(field),
        )
        if fingerprint:
            return fingerprint

    for raw_message in existing_messages:
        message = _normalize_message(raw_message)
        if not message:
            continue
        fingerprints = collect_message_fingerprints(message)
        if fingerprints:
            return sorted(fingerprints)[0]

    return None


def validate_message_matches_authoritative_fingerprint(
    message: dict[str, Any],
    authoritative_fingerprint_value: str | None,
) -> FingerprintValidationResult:
    """Fail closed when an incoming encrypted message uses a different key."""
    incoming_fingerprints = collect_message_fingerprints(message)
    if len(incoming_fingerprints) > 1:
        return FingerprintValidationResult(
            valid=False,
            incoming_fingerprint=",".join(sorted(incoming_fingerprints)),
            authoritative_fingerprint=authoritative_fingerprint_value,
            reason="incoming_encrypted_fields_use_multiple_keys",
        )

    incoming_fingerprint = next(iter(incoming_fingerprints), None)
    if not incoming_fingerprint or not authoritative_fingerprint_value:
        return FingerprintValidationResult(
            valid=True,
            incoming_fingerprint=incoming_fingerprint,
            authoritative_fingerprint=authoritative_fingerprint_value,
        )

    if incoming_fingerprint != authoritative_fingerprint_value:
        return FingerprintValidationResult(
            valid=False,
            incoming_fingerprint=incoming_fingerprint,
            authoritative_fingerprint=authoritative_fingerprint_value,
            reason="incoming_fingerprint_does_not_match_chat",
        )

    return FingerprintValidationResult(
        valid=True,
        incoming_fingerprint=incoming_fingerprint,
        authoritative_fingerprint=authoritative_fingerprint_value,
    )


def _normalize_message(raw_message: dict[str, Any] | str) -> dict[str, Any] | None:
    if isinstance(raw_message, dict):
        return raw_message
    if isinstance(raw_message, str):
        try:
            parsed = json.loads(raw_message)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
