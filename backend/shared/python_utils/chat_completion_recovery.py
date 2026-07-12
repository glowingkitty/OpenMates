"""
Cryptographic primitives for sealed cross-device chat completion recovery.

This module implements the versioned byte contract shared by backend and all
clients. The backend seals with public recovery keys only; raw chat keys and
derived recovery private keys remain client-side.
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct
import uuid
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


PROTOCOL_VERSION = 1
KEY_LENGTH = 32
NONCE_LENGTH = 12
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
RECOVERY_KEY_SALT = hashlib.sha256(b"openmates:chat-recovery:v1").digest()
ENVELOPE_KEY_SALT = hashlib.sha256(b"openmates:chat-recovery-envelope:v1").digest()
ENVELOPE_FIELDS = {"v", "epk", "nonce", "ciphertext"}


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str, field: str) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise ValueError(f"{field} must be non-empty unpadded base64url")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be valid unpadded base64url") from exc
    if _encode(decoded) != value:
        raise ValueError(f"{field} must use canonical unpadded base64url")
    return decoded


def _canonical_uuid(value: str, field: str) -> str:
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc
    if canonical != value:
        raise ValueError(f"{field} must use canonical lowercase UUID encoding")
    return value


def _key_version(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 0xFFFFFFFF:
        raise ValueError("key_version must be an unsigned 32-bit integer greater than zero")
    return value


def _length_prefixed(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def _associated_data(
    *,
    owner_id: str,
    chat_id: str,
    turn_id: str,
    job_id: str,
    assistant_message_id: str,
    key_version: int,
) -> bytes:
    identifiers = (
        _canonical_uuid(owner_id, "owner_id"),
        _canonical_uuid(chat_id, "chat_id"),
        _canonical_uuid(turn_id, "turn_id"),
        _canonical_uuid(job_id, "job_id"),
        _canonical_uuid(assistant_message_id, "assistant_message_id"),
    )
    return b"OMCR1" + b"".join(_length_prefixed(value) for value in identifiers) + struct.pack(">I", _key_version(key_version))


def build_recovery_associated_data(values: Mapping[str, Any]) -> str:
    return _encode(
        _associated_data(
            owner_id=values["owner_id"],
            chat_id=values["chat_id"],
            turn_id=values["turn_id"],
            job_id=values["job_id"],
            assistant_message_id=values["assistant_message_id"],
            key_version=values["key_version"],
        )
    )


def derive_recovery_keypair(chat_key: str, chat_id: str, key_version: int) -> tuple[str, str]:
    chat_key_bytes = _decode(chat_key, "chat_key")
    if len(chat_key_bytes) != KEY_LENGTH:
        raise ValueError("chat_key must contain exactly 32 bytes")
    private_bytes = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=RECOVERY_KEY_SALT,
        info=_length_prefixed(_canonical_uuid(chat_id, "chat_id")) + struct.pack(">I", _key_version(key_version)),
    ).derive(chat_key_bytes)
    private_key = x25519.X25519PrivateKey.from_private_bytes(private_bytes)
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return _encode(private_bytes), _encode(public_bytes)


def _envelope_key(private_key: x25519.X25519PrivateKey, public_key: bytes, associated_data: bytes) -> bytes:
    if len(public_key) != KEY_LENGTH:
        raise ValueError("X25519 public key must contain exactly 32 bytes")
    shared_secret = private_key.exchange(x25519.X25519PublicKey.from_public_bytes(public_key))
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=ENVELOPE_KEY_SALT,
        info=hashlib.sha256(associated_data).digest(),
    ).derive(shared_secret)


def seal_recovery_payload(
    payload: bytes,
    *,
    recovery_public_key: str,
    owner_id: str,
    chat_id: str,
    turn_id: str,
    job_id: str,
    assistant_message_id: str,
    key_version: int,
    ephemeral_private_key: str | None = None,
    nonce: str | None = None,
) -> dict[str, str | int]:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("recovery payload exceeds 16 MiB")
    ephemeral_bytes = _decode(ephemeral_private_key, "ephemeral_private_key") if ephemeral_private_key else os.urandom(KEY_LENGTH)
    nonce_bytes = _decode(nonce, "nonce") if nonce else os.urandom(NONCE_LENGTH)
    if len(ephemeral_bytes) != KEY_LENGTH or len(nonce_bytes) != NONCE_LENGTH:
        raise ValueError("invalid ephemeral key or nonce length")
    associated_data = _associated_data(
        owner_id=owner_id,
        chat_id=chat_id,
        turn_id=turn_id,
        job_id=job_id,
        assistant_message_id=assistant_message_id,
        key_version=key_version,
    )
    ephemeral = x25519.X25519PrivateKey.from_private_bytes(ephemeral_bytes)
    key = _envelope_key(ephemeral, _decode(recovery_public_key, "recovery_public_key"), associated_data)
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return {
        "v": PROTOCOL_VERSION,
        "epk": _encode(ephemeral_public),
        "nonce": _encode(nonce_bytes),
        "ciphertext": _encode(AESGCM(key).encrypt(nonce_bytes, payload, associated_data)),
    }


def open_recovery_envelope(
    envelope: Mapping[str, Any],
    *,
    recovery_private_key: str,
    owner_id: str,
    chat_id: str,
    turn_id: str,
    job_id: str,
    assistant_message_id: str,
    key_version: int,
) -> bytes:
    if set(envelope) != ENVELOPE_FIELDS or envelope.get("v") != PROTOCOL_VERSION:
        raise ValueError("unsupported recovery envelope")
    private_bytes = _decode(recovery_private_key, "recovery_private_key")
    ephemeral_public = _decode(envelope["epk"], "epk")
    nonce = _decode(envelope["nonce"], "nonce")
    ciphertext = _decode(envelope["ciphertext"], "ciphertext")
    if len(private_bytes) != KEY_LENGTH or len(nonce) != NONCE_LENGTH:
        raise ValueError("invalid recovery key or nonce length")
    if len(ciphertext) > MAX_PAYLOAD_BYTES + 16:
        raise ValueError("recovery payload exceeds 16 MiB")
    associated_data = _associated_data(
        owner_id=owner_id,
        chat_id=chat_id,
        turn_id=turn_id,
        job_id=job_id,
        assistant_message_id=assistant_message_id,
        key_version=key_version,
    )
    private_key = x25519.X25519PrivateKey.from_private_bytes(private_bytes)
    key = _envelope_key(private_key, ephemeral_public, associated_data)
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data)
