"""Shared media ciphertext reader compatibility.

Legacy media stores one external AES-GCM nonce at the record level. Media v2
uses an explicit marker and prefixes each ciphertext with its own 12-byte nonce.
Readers support both formats while unknown markers fail closed.
"""

from __future__ import annotations

import base64
from typing import Any, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


AES_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
AES_GCM_TAG_BYTES = 16
MEDIA_ENCRYPTION_V2 = "aes-gcm-nonce-prefixed-v1"


def decrypt_media_payload(
    *,
    encrypted_data: bytes,
    aes_key: bytes,
    variant: Mapping[str, Any],
    legacy_nonce_b64: str | None,
) -> bytes:
    """Decrypt one legacy or explicitly marked v2 media payload."""
    if len(aes_key) != AES_KEY_BYTES:
        raise ValueError("media AES key must be 32 bytes")

    marker = variant.get("encryption")
    if marker == MEDIA_ENCRYPTION_V2:
        if len(encrypted_data) < AES_GCM_NONCE_BYTES + AES_GCM_TAG_BYTES:
            raise ValueError("nonce-prefixed media ciphertext is too short")
        nonce = encrypted_data[:AES_GCM_NONCE_BYTES]
        ciphertext = encrypted_data[AES_GCM_NONCE_BYTES:]
    elif marker in (None, ""):
        nonce_b64 = variant.get("aes_nonce") or legacy_nonce_b64
        if not isinstance(nonce_b64, str) or not nonce_b64:
            raise ValueError("legacy media nonce is missing")
        try:
            nonce = base64.b64decode(nonce_b64, validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("legacy media nonce is invalid") from exc
        if len(nonce) != AES_GCM_NONCE_BYTES:
            raise ValueError("legacy media nonce must be 12 bytes")
        ciphertext = encrypted_data
    else:
        raise ValueError(f"unsupported media encryption marker: {marker}")

    return AESGCM(aes_key).decrypt(nonce, ciphertext, None)
