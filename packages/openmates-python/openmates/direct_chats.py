"""Authenticated OMDM1 Team direct-chat key envelopes shared with web and CLI.

Each envelope uses a fresh ephemeral X25519 key and XSalsa20-Poly1305 nonce.
The boxed payload binds Team, chat, recipient hash, and recipient key ID, so a
wrapper from another conversation or participant cannot be reused. All wire
bytes use canonical base64url and strict bounds matching pairing-crypto's
browser/Node implementation. Team wrapping keys never enter this module.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from collections.abc import Mapping

from nacl.bindings import crypto_scalarmult
from nacl.exceptions import CryptoError
from nacl.public import Box, PrivateKey, PublicKey
from nacl.utils import random as nacl_random

_PREFIX = "OMDM1."
_MAX_ENVELOPE_LENGTH = 2048
_MAX_PAYLOAD_BYTES = 768
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z")
_KEY_ID = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class DirectChatIdentity:
    """Authenticated recipient binding carried inside a direct-chat envelope."""

    team_id: str
    chat_id: str
    recipient_hash: str
    key_id: str


@dataclass(frozen=True, slots=True)
class DirectChatKeyPair:
    """Canonical base64url X25519 keys and SHA-256 public-key identifier."""

    public_key: str
    private_key: str
    key_id: str


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(value: str, *, field: str, length: int | None = None,
            max_length: int | None = None) -> bytes:
    limit = length if max_length is None and length is not None else max_length or _MAX_PAYLOAD_BYTES
    if (not isinstance(value, str) or not value or not _BASE64URL.fullmatch(value)
            or len(value) > (limit * 4 + 2) // 3 + 2):
        raise ValueError(f"Invalid direct-chat {field}")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError(f"Invalid direct-chat {field}") from error
    if (length is not None and len(raw) != length) or len(raw) > limit or _encode(raw) != value:
        raise ValueError(f"Invalid direct-chat {field}")
    return raw


def _nonzero_key(value: bytes, field: str) -> bytes:
    if len(value) != 32 or value == bytes(32):
        raise ValueError(f"Invalid direct-chat {field}")
    return value


def _public_key_bytes(value: str) -> bytes:
    public = _nonzero_key(_decode(value, field="public key", length=32), "public key")
    # X25519 libraries may otherwise accept a small-order peer point. Probe it
    # before boxing, exactly as the shared browser/Node helper does.
    try:
        shared = crypto_scalarmult(bytes([7]) * 32, public)
    except (CryptoError, RuntimeError, ValueError) as error:
        raise ValueError("Invalid direct-chat public key") from error
    if shared == bytes(32):
        raise ValueError("Invalid direct-chat public key")
    return public


def direct_chat_key_id(public_key: str) -> str:
    """Return the lower-case SHA-256 hex ID of a valid X25519 public key."""

    return hashlib.sha256(_public_key_bytes(public_key)).hexdigest()


def validate_public_chat_key(record: Mapping[str, object]) -> dict[str, str]:
    """Validate a directory record and return only its public key and ID."""

    if not isinstance(record, Mapping):
        raise ValueError("Invalid member chat encryption key")
    key_id = record.get("key_id")
    public_key = record.get("public_key")
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ValueError("Invalid member chat encryption key ID")
    if not isinstance(public_key, str) or not hmac.compare_digest(direct_chat_key_id(public_key), key_id):
        raise ValueError("Member chat encryption key ID mismatch")
    return {"key_id": key_id, "public_key": public_key}


def generate_identity() -> DirectChatKeyPair:
    """Create a fresh account X25519 identity for encrypted backup by the SDK."""

    private = PrivateKey.generate()
    public_key = _encode(bytes(private.public_key))
    return DirectChatKeyPair(public_key, _encode(bytes(private)), direct_chat_key_id(public_key))


def recover_identity(public_key: str, key_id: str, private_key: str) -> DirectChatKeyPair:
    """Verify a decrypted account backup against its published public record."""

    validate_public_chat_key({"public_key": public_key, "key_id": key_id})
    secret = _nonzero_key(_decode(private_key, field="private key", length=32), "private key")
    derived = bytes(PrivateKey(secret).public_key)
    if not hmac.compare_digest(derived, _public_key_bytes(public_key)):
        raise ValueError("Account chat key pair mismatch")
    return DirectChatKeyPair(public_key, private_key, key_id)


def _validate_identity(identity: DirectChatIdentity) -> None:
    if not isinstance(identity, DirectChatIdentity):
        raise ValueError("Invalid direct-chat identity")
    for value in (identity.team_id, identity.chat_id, identity.recipient_hash):
        if not isinstance(value, str) or not 1 <= len(value) <= 128 or not _BASE64URL.fullmatch(value):
            raise ValueError("Invalid direct-chat identity")
    if not isinstance(identity.key_id, str) or not _KEY_ID.fullmatch(identity.key_id):
        raise ValueError("Invalid direct-chat key ID")


def _parse_object(value: bytes, field: str) -> dict[str, object]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid direct-chat {field}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid direct-chat {field}")
    return parsed


def seal_direct_chat_key(raw_key: bytes, identity: DirectChatIdentity,
                         recipient_public_key: str) -> str:
    """Seal a nonzero 32-byte chat key to one verified recipient identity."""

    _validate_identity(identity)
    if not isinstance(raw_key, (bytes, bytearray, memoryview)):
        raise ValueError("Invalid direct-chat chat key")
    chat_key = _nonzero_key(bytes(raw_key), "chat key")
    recipient = _public_key_bytes(recipient_public_key)
    if not hmac.compare_digest(identity.key_id, hashlib.sha256(recipient).hexdigest()):
        raise ValueError("Direct-chat recipient key ID mismatch")
    ephemeral = PrivateKey.generate()
    nonce = nacl_random(24)
    payload = json.dumps({
        "v": 1, "team_id": identity.team_id, "chat_id": identity.chat_id,
        "recipient_hash": identity.recipient_hash, "key_id": identity.key_id,
        "key": _encode(chat_key),
    }, separators=(",", ":")).encode("utf-8")
    ciphertext = Box(ephemeral, PublicKey(recipient)).encrypt(payload, nonce).ciphertext
    envelope = _PREFIX + _encode(json.dumps({
        "v": 1, "ephemeral_public_key": _encode(bytes(ephemeral.public_key)),
        "nonce": _encode(nonce), "ciphertext": _encode(ciphertext),
    }, separators=(",", ":")).encode("utf-8"))
    if len(envelope) > _MAX_ENVELOPE_LENGTH:
        raise ValueError("Direct-chat envelope too large")
    return envelope


def open_direct_chat_key(envelope: str, expected: DirectChatIdentity,
                         private_key: str) -> bytes:
    """Authenticate and unwrap one envelope only for its exact participant."""

    _validate_identity(expected)
    if not isinstance(envelope, str) or not envelope.startswith(_PREFIX) or len(envelope) > _MAX_ENVELOPE_LENGTH:
        raise ValueError("Invalid direct-chat envelope")
    outer = _parse_object(_decode(envelope[len(_PREFIX):], field="envelope"), "envelope")
    if set(outer) != {"v", "ephemeral_public_key", "nonce", "ciphertext"} or type(outer["v"]) is not int or outer["v"] != 1:
        raise ValueError("Invalid direct-chat envelope version or fields")
    sender = _public_key_bytes(outer["ephemeral_public_key"])
    nonce = _decode(outer["nonce"], field="nonce", length=24)
    ciphertext = _decode(outer["ciphertext"], field="ciphertext", max_length=512)
    if len(ciphertext) < 17:
        raise ValueError("Invalid direct-chat ciphertext")
    secret = _nonzero_key(_decode(private_key, field="private key", length=32), "private key")
    own_public = _encode(bytes(PrivateKey(secret).public_key))
    if not hmac.compare_digest(direct_chat_key_id(own_public), expected.key_id):
        raise ValueError("Direct-chat private key ID mismatch")
    try:
        plaintext = Box(PrivateKey(secret), PublicKey(sender)).decrypt(ciphertext, nonce)
    except CryptoError as error:
        raise ValueError("Direct-chat key authentication failed") from error
    payload = _parse_object(plaintext, "key payload")
    if (set(payload) != {"v", "team_id", "chat_id", "recipient_hash", "key_id", "key"}
            or type(payload["v"]) is not int or payload["v"] != 1
            or payload["team_id"] != expected.team_id or payload["chat_id"] != expected.chat_id
            or payload["recipient_hash"] != expected.recipient_hash
            or payload["key_id"] != expected.key_id):
        raise ValueError("Direct-chat key binding mismatch")
    return _nonzero_key(_decode(payload["key"], field="chat key", length=32), "chat key")
