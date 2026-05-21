"""
Unit tests for chat ciphertext fingerprint validation helpers.

The backend cannot decrypt zero-knowledge chat content, but it can compare the
non-secret key fingerprint embedded in modern client ciphertext headers. These
tests keep that validation behavior explicit and independent from WebSocket
handler plumbing.
"""

import base64

from backend.shared.python_utils.chat_ciphertext_fingerprint import (
    authoritative_chat_fingerprint,
    extract_chat_ciphertext_fingerprint,
    validate_message_matches_authoritative_fingerprint,
)


def make_ciphertext(fingerprint: str) -> str:
    raw = b"OM" + bytes.fromhex(fingerprint) + (b"0" * 12) + b"ciphertext"
    return base64.b64encode(raw).decode("ascii")


def test_extract_chat_ciphertext_fingerprint_reads_om_header():
    assert extract_chat_ciphertext_fingerprint(make_ciphertext("1a5b3b7c")) == "1a5b3b7c"


def test_authoritative_chat_fingerprint_prefers_chat_metadata():
    fingerprint = authoritative_chat_fingerprint(
        {"encrypted_title": make_ciphertext("1a5b3b7c")},
        [{"encrypted_content": make_ciphertext("0f0165e4")}],
    )

    assert fingerprint == "1a5b3b7c"


def test_validate_message_rejects_mismatched_authoritative_fingerprint():
    result = validate_message_matches_authoritative_fingerprint(
        {"encrypted_content": make_ciphertext("0f0165e4")},
        "1a5b3b7c",
    )

    assert result.valid is False
    assert result.incoming_fingerprint == "0f0165e4"
    assert result.authoritative_fingerprint == "1a5b3b7c"
    assert result.reason == "incoming_fingerprint_does_not_match_chat"
