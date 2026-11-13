"""API-key SDK key helpers mirroring the Rust `crypto` primitives.

Pure functions: no network, no CLI state, no environment. Keys are 32 raw bytes.
Writes use the canonical browser `OM` + FNV-1a32 header; reads also accept the
authenticated legacy IV-prefixed layouts.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os

from . import sdk as _sdk

KEY_LENGTH = 32


class KeyManagementError(ValueError):
    """Typed refusal for malformed keys or ciphertext; never carries key material."""


def _require_key(key: bytes) -> bytes:
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_LENGTH:
        raise KeyManagementError("A 32-byte key is required.")
    return bytes(key)


def random_key() -> bytes:
    return os.urandom(KEY_LENGTH)


def encode_key(key: bytes) -> str:
    return base64.b64encode(_require_key(key)).decode("ascii")


def decode_key(value: str) -> bytes:
    """Standard or unpadded URL-safe base64 of exactly 32 bytes."""
    if not isinstance(value, str):
        raise KeyManagementError("A base64 key string is required.")
    for decoder, text in (
        (base64.b64decode, value),
        (base64.urlsafe_b64decode, value + "=" * (-len(value) % 4)),
    ):
        try:
            raw = decoder(text)
        except (binascii.Error, ValueError):
            continue
        if len(raw) == KEY_LENGTH:
            return raw
        break
    raise KeyManagementError("A 32-byte key is required.")


def key_fingerprint(key: bytes) -> bytes:
    return _sdk._key_fingerprint(_require_key(key))


def hash_email(email: str) -> str:
    return base64.b64encode(hashlib.sha256(email.encode("utf-8")).digest()).decode("ascii")


def hash_key(password: str, salt: bytes) -> str:
    digest = hashlib.sha256(password.encode("utf-8") + bytes(salt)).digest()
    return base64.b64encode(digest).decode("ascii")


def encrypt_combined(text: str, key: bytes) -> str:
    return _sdk._encrypt_aes_gcm_text(text, _require_key(key))


def decrypt_combined(ciphertext: str, key: bytes) -> str:
    plaintext = _sdk._decrypt_aes_gcm_text(ciphertext, _require_key(key))
    if plaintext is None:
        raise KeyManagementError("Decryption failed.")
    return plaintext
