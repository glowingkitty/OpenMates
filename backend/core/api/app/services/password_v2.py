"""Versioned password authentication without a reusable database lookup hash.

The client performs Argon2id and HKDF locally. Vault seals the resulting auth
subkey at enrollment; subsequent logins prove possession against a one-use
challenge and never send the static subkey again.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping

from fastapi import HTTPException

KDF_ID = "argon2id-hkdf-sha256-v1"
CHALLENGE_TTL_SECONDS = 120
SENSITIVE_CHALLENGE_TTL_SECONDS = 600
_B64URL_32 = re.compile(r"^[A-Za-z0-9_-]{43}$")
_PURPOSE = re.compile(r"^(login|migration|sensitive:[a-z_]{3,40})$")
_DOMAIN = b"openmates/password-v2/proof\x00"


def decode_key(value: str) -> bytes:
    """Require canonical unpadded base64url for a 32-byte key or proof."""
    if not isinstance(value, str) or not _B64URL_32.fullmatch(value):
        raise ValueError("Invalid password v2 key encoding")
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except Exception as exc:
        raise ValueError("Invalid password v2 key encoding") from exc
    if len(raw) != 32 or encode_key(raw) != value:
        raise ValueError("Invalid password v2 key encoding")
    return raw


def encode_key(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def proof_message(purpose: str, nonce: bytes) -> bytes:
    if not _PURPOSE.fullmatch(purpose) or len(nonce) != 32:
        raise ValueError("Invalid password v2 challenge")
    return _DOMAIN + purpose.encode("utf-8") + b"\x00" + nonce


def password_v2_record(typed: object) -> dict | None:
    if isinstance(typed, str):
        try:
            typed = json.loads(typed)
        except ValueError:
            return None
    if not isinstance(typed, Mapping):
        return None
    record = typed.get("password")
    if not isinstance(record, Mapping) or record.get("version") != 2 or record.get("kdf") != KDF_ID:
        return None
    sealed = record.get("sealed_auth_key")
    wrapper = record.get("wrapper_method")
    if not isinstance(sealed, str) or not sealed.startswith("vault:"):
        return None
    if not isinstance(wrapper, str) or not wrapper.startswith("password_v2_"):
        return None
    pending_hash = record.get("pending_v1_lookup_hash")
    pending_wrapper = record.get("pending_v1_wrapper_method")
    if (pending_hash is None) != (pending_wrapper is None):
        return None
    if pending_hash is not None and (
        not isinstance(pending_hash, str) or not pending_hash
        or not isinstance(pending_wrapper, str) or not pending_wrapper
    ):
        return None
    if "legacy_password_retained" in record and not isinstance(record["legacy_password_retained"], bool):
        return None
    return dict(record)


def has_password_v2_record(typed: object) -> bool:
    """Fail closed on any claimed v2 password record, including malformed ones."""
    if isinstance(typed, str):
        try:
            typed = json.loads(typed)
        except ValueError:
            return False
    return isinstance(typed, Mapping) and isinstance(typed.get("password"), Mapping) and typed["password"].get("version") == 2


def _challenge_key(challenge_id: str) -> str:
    if not isinstance(challenge_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", challenge_id):
        raise ValueError("Invalid password v2 challenge")
    return f"auth:password-v2:challenge:{challenge_id}"


async def issue_challenge(cache, *, hashed_email: str, session_id: str, purpose: str,
                          binding: str | None = None) -> dict:
    """Issue a uniform challenge without looking up the account."""
    if not isinstance(hashed_email, str) or not hashed_email or not isinstance(session_id, str) or len(session_id) < 8:
        raise HTTPException(400, "Invalid password v2 challenge request")
    if not _PURPOSE.fullmatch(purpose):
        raise HTTPException(400, "Invalid password v2 purpose")
    challenge_id = secrets.token_urlsafe(32)
    nonce = secrets.token_bytes(32)
    value = {"hashed_email": hashed_email, "session_id": session_id,
             "purpose": purpose, "nonce": encode_key(nonce), "binding": binding}
    ttl = SENSITIVE_CHALLENGE_TTL_SECONDS if purpose.startswith("sensitive:") else CHALLENGE_TTL_SECONDS
    if not await cache.set(_challenge_key(challenge_id), value, ttl=ttl):
        raise HTTPException(503, "Password verification temporarily unavailable")
    return {"challenge_id": challenge_id, "nonce": value["nonce"],
            "expires_in": ttl}


async def verify_challenge_proof(
    cache, encryption_service, *, challenge_id: str, password_proof: str,
    hashed_email: str, session_id: str, purpose: str, record: object,
    vault_key_id: str, binding: str | None = None,
) -> bool:
    """Atomically consume a challenge, then verify a Vault-sealed auth subkey."""
    try:
        key = _challenge_key(challenge_id)
    except ValueError:
        return False
    challenge = await cache.get_and_delete(key)
    try:
        submitted = decode_key(password_proof)
    except ValueError:
        return False
    if not isinstance(challenge, Mapping) or any((
        challenge.get("hashed_email") != hashed_email,
        challenge.get("session_id") != session_id,
        challenge.get("purpose") != purpose,
        challenge.get("binding") != binding,
    )):
        return False
    v2 = password_v2_record(record)
    if not v2 or not vault_key_id:
        return False
    try:
        nonce = decode_key(challenge["nonce"])
        auth_key_b64 = await encryption_service.decrypt_with_user_key(
            v2["sealed_auth_key"], vault_key_id)
        auth_key = decode_key(auth_key_b64)
        expected = hmac.new(auth_key, proof_message(purpose, nonce), hashlib.sha256).digest()
        return hmac.compare_digest(submitted, expected)
    except Exception:
        return False


async def seal_auth_key(encryption_service, *, password_auth_key: str, vault_key_id: str) -> str:
    decode_key(password_auth_key)
    if not vault_key_id:
        raise ValueError("Vault key required")
    sealed, _version = await encryption_service.encrypt_with_user_key(
        password_auth_key, vault_key_id)
    if not isinstance(sealed, str) or not sealed.startswith("vault:"):
        raise RuntimeError("Vault password verifier sealing failed")
    return sealed
