"""Backend media encryption reader compatibility contracts.

Frozen legacy fixtures must remain readable without metadata mutation. R1 also
adds read support for the explicit nonce-prefixed v2 marker while every writer
remains on the legacy format through the rollout manifest.
"""

from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.shared.python_utils.media_encryption import (
    MEDIA_ENCRYPTION_V2,
    decrypt_media_payload,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures/encryption_compatibility/legacy_layouts.json"


def test_frozen_legacy_media_uses_unchanged_top_level_nonce_fallback() -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    legacy_media = fixtures["legacy_media"]
    original = deepcopy(legacy_media)

    for media in legacy_media:
        key = base64.b64decode(media["aes_key_b64"])
        for variant in media["variants"].values():
            plaintext = decrypt_media_payload(
                encrypted_data=base64.b64decode(variant["ciphertext_b64"]),
                aes_key=key,
                variant=variant,
                legacy_nonce_b64=media["aes_nonce"],
            )
            assert plaintext.decode("utf-8") == variant["plaintext"]

    assert legacy_media == original


def test_explicit_v2_marker_reads_nonce_prefixed_payload() -> None:
    key = bytes(range(32))
    nonce = bytes(range(12))
    plaintext = b"generated_image:v2-preview"
    encrypted_data = nonce + AESGCM(key).encrypt(nonce, plaintext, None)

    assert decrypt_media_payload(
        encrypted_data=encrypted_data,
        aes_key=key,
        variant={"encryption": MEDIA_ENCRYPTION_V2},
        legacy_nonce_b64=None,
    ) == plaintext


def test_unknown_media_encryption_marker_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported media encryption"):
        decrypt_media_payload(
            encrypted_data=b"not-decrypted",
            aes_key=bytes(range(32)),
            variant={"encryption": "unknown-version"},
            legacy_nonce_b64=None,
        )


@pytest.mark.parametrize("key", [b"short", b"long" * 9])
def test_invalid_media_key_size_fails_before_decryption(key: bytes) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        decrypt_media_payload(
            encrypted_data=b"not-decrypted",
            aes_key=key,
            variant={},
            legacy_nonce_b64=base64.b64encode(bytes(range(12))).decode("ascii"),
        )
