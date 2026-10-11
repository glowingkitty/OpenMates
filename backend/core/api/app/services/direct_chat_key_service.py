"""Opaque, immutable account public keys for client-encrypted direct chats.

Validate canonical X25519 public keys and their SHA256 key identifiers.
The encrypted private key is treated as an opaque account-master ciphertext.
A unique hashed account ID in Directus fences simultaneous registrations.
On a duplicate insert, read the stored row and accept only an exact retry.
"""

import base64
import hashlib
import re
from typing import Any

from backend.core.api.app.services.directus.team_methods import hash_id

ALGORITHM = "x25519-xsalsa20poly1305"
VERSION = 1
KEY_ID_RE = re.compile(r"^[0-9a-f]{64}$")
PUBLIC_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class KeyConflictError(Exception):
    pass


class KeyStoreError(Exception):
    pass


def validate_public_key(public_key: str, key_id: str) -> None:
    if not PUBLIC_KEY_RE.fullmatch(public_key) or not KEY_ID_RE.fullmatch(key_id):
        raise ValueError("INVALID_CHAT_ENCRYPTION_KEY")
    try:
        public_bytes = base64.urlsafe_b64decode(public_key + "=")
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("INVALID_CHAT_ENCRYPTION_KEY") from exc
    if (len(public_bytes) != 32 or not any(public_bytes)
            or base64.urlsafe_b64encode(public_bytes).decode().rstrip("=") != public_key):
        raise ValueError("INVALID_CHAT_ENCRYPTION_KEY")
    if hashlib.sha256(public_bytes).hexdigest() != key_id:
        raise ValueError("CHAT_ENCRYPTION_KEY_ID_MISMATCH")


def public_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {"key_id": row["key_id"], "public_key": row["public_key"]}


def own_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {**public_projection(row), "encrypted_private_key": row["encrypted_private_key"],
            "algorithm": ALGORITHM, "version": VERSION}


async def get_account_key(directus: Any, user_id: str) -> dict[str, Any] | None:
    return await get_account_key_by_hash(directus, hash_id(user_id))


async def get_account_key_by_hash(directus: Any, user_hash: str) -> dict[str, Any] | None:
    if not KEY_ID_RE.fullmatch(user_hash):
        raise ValueError("INVALID_USER_HASH")
    rows = await directus.get_items(
        "account_chat_keys",
        params={"filter[hashed_user_id][_eq]": user_hash,
                "fields": "hashed_user_id,key_id,public_key,encrypted_private_key,algorithm,version", "limit": 1},
        no_cache=True, admin_required=True,
    )
    if not isinstance(rows, list):
        raise KeyStoreError("CHAT_ENCRYPTION_KEY_UNAVAILABLE")
    return rows[0] if rows else None


async def register_account_key(directus: Any, user_id: str, *, key_id: str,
                               public_key: str, encrypted_private_key: str) -> dict[str, Any]:
    validate_public_key(public_key, key_id)
    candidate = {"key_id": key_id, "public_key": public_key,
                 "encrypted_private_key": encrypted_private_key, "algorithm": ALGORITHM, "version": VERSION}
    existing = await get_account_key(directus, user_id)
    if existing:
        if own_projection(existing) != candidate:
            raise KeyConflictError("CHAT_ENCRYPTION_KEY_IMMUTABLE")
        return own_projection(existing)
    created, _ = await directus.create_item(
        "account_chat_keys", {"hashed_user_id": hash_id(user_id), **candidate},
        admin_required=True, expected_unique_conflict_field="hashed_user_id",
    )
    # Re-read after both a successful insert and a uniqueness race. Never trust
    # an insert failure as a conflict without observing the authoritative row.
    stored = await get_account_key(directus, user_id)
    if stored:
        if own_projection(stored) != candidate:
            raise KeyConflictError("CHAT_ENCRYPTION_KEY_IMMUTABLE")
        return own_projection(stored)
    raise KeyStoreError("CHAT_ENCRYPTION_KEY_UNAVAILABLE")
