"""Durable, pair-only absolute deadlines for first-party refresh sessions."""
from __future__ import annotations

import hashlib
import time

from fastapi import HTTPException


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _membership_key(token_hash: str) -> str:
    return f"pair:membership:{token_hash}"


async def _record(directus, token_hash: str) -> dict | None:
    try:
        rows = await directus.get_items(
            "pair_session_deadlines",
            params={"filter": {"token_hash": {"_eq": token_hash}}, "fields": "id,token_hash,user_id,expires_at,pending_ack,relay_acknowledged,retired", "limit": 1},
            admin_required=True, raise_on_error=True,
        )
    except Exception as exc:
        raise HTTPException(503, "Session verification temporarily unavailable") from exc
    return rows[0] if rows else None


async def _mark_cache(cache, token_hash: str, user_id: str, deadline: int | None, pending: bool) -> None:
    key = f"session:{token_hash}"
    existing = await cache.get(key)
    if existing is not None and (not isinstance(existing, dict) or existing.get("user_id") != user_id):
        raise HTTPException(503, "Pair session identity conflict")
    remaining = deadline - int(time.time()) if deadline is not None else cache.SESSION_TTL
    if remaining <= 0:
        raise HTTPException(401, "Pair session expired")
    link = dict(existing or {})
    link.update(user_id=user_id, pair_expires_at=deadline, pair_pending_ack=pending)
    if not await cache.set(key, link, ttl=remaining):
        raise HTTPException(503, "Pair session cache unavailable")


async def register_pair_session(directus, cache, token: str, user_id: str, deadline: int | None) -> None:
    """Register before the newly minted cookie is returned to the receiver."""
    if deadline is not None and deadline <= int(time.time()):
        raise HTTPException(401, "Pair session expired")
    # Override any verified ordinary-session negative cache before the new
    # token can be returned. A missing/failed marker falls back to Directus.
    if not await cache.set(_membership_key(_hash(token)), "present", ttl=cache.SESSION_TTL):
        raise HTTPException(503, "Pair session membership unavailable")
    created, row = await directus.create_item(
        "pair_session_deadlines",
        {"token_hash": _hash(token), "user_id": user_id, "expires_at": deadline, "pending_ack": True, "relay_acknowledged": False, "retired": False},
        admin_required=True,
    )
    if not created:
        raise HTTPException(503, "Pair session expiry unavailable")
    await _mark_cache(cache, _hash(token), user_id, deadline, True)


async def activate_pair_session(directus, cache, token_hash: str, user_id: str) -> None:
    """Only an acknowledged receiver can activate its previously minted session."""
    row = await _record(directus, token_hash)
    if not row or row.get("user_id") != user_id:
        raise HTTPException(503, "Pair session marker unavailable")
    if row.get("retired"):
        raise HTTPException(401, "Pair session token retired")
    deadline = int(row["expires_at"]) if row.get("expires_at") is not None else None
    if deadline is not None and deadline <= int(time.time()):
        raise HTTPException(401, "Pair session expired")
    if row.get("pending_ack"):
        updated = await directus._update_item("pair_session_deadlines", row["id"], {"pending_ack": False}, admin_required=True)
        if not updated:
            raise HTTPException(503, "Pair session activation unavailable")
    # The relay ACK is a separate transition. Authentication still checks the
    # durable relay_acknowledged flag and denies this intermediate state.


async def confirm_pair_session(directus, cache, token_hash: str, user_id: str) -> None:
    row = await _record(directus, token_hash)
    if not row or row.get("user_id") != user_id or row.get("retired") or row.get("pending_ack"):
        raise HTTPException(503, "Pair session activation incomplete")
    deadline = int(row["expires_at"]) if row.get("expires_at") is not None else None
    if deadline is not None and deadline <= int(time.time()):
        raise HTTPException(401, "Pair session expired")
    if not row.get("relay_acknowledged"):
        updated = await directus._update_item("pair_session_deadlines", row["id"], {"relay_acknowledged": True}, admin_required=True)
        if not updated:
            raise HTTPException(503, "Pair session acknowledgement unavailable")
    await _mark_cache(cache, token_hash, user_id, deadline, False)


async def is_pair_session_confirmed(directus, token_hash: str, user_id: str) -> bool:
    """Only durable ACK completion may become a terminal pairing success."""
    row = await _record(directus, token_hash)
    if not row or row.get("user_id") != user_id:
        return False
    deadline = int(row["expires_at"]) if row.get("expires_at") is not None else None
    return bool(not row.get("pending_ack") and row.get("relay_acknowledged")
                and not row.get("retired") and (deadline is None or deadline > int(time.time())))


async def get_pair_deadline(directus, cache, token: str) -> tuple[int | None, str] | None:
    """Read the current token's hard deadline, including after a Redis miss."""
    # Always consult the ledger. A warm cache link can survive issuer rotation
    # or a failed cache write and must not override retirement/ACK state.
    token_hash = _hash(token)
    membership = await cache.get(_membership_key(token_hash))
    if membership == "absent":
        return None
    row = await _record(directus, token_hash)
    if not row:
        await cache.set(_membership_key(token_hash), "absent", ttl=300)
        return None
    if row.get("retired"):
        raise HTTPException(401, "Pair session token retired")
    if row.get("pending_ack") or not row.get("relay_acknowledged"):
        raise HTTPException(401, "Pair session awaiting acknowledgement")
    deadline = int(row["expires_at"]) if row.get("expires_at") is not None else None
    user_id = row["user_id"]
    if deadline is not None and deadline <= int(time.time()):
        raise HTTPException(401, "Pair session expired")
    return deadline, user_id


async def transfer_pair_deadline(directus, cache, old_token: str, new_token: str, deadline: int | None, user_id: str) -> None:
    """Move the durable marker before a rotated cookie is published."""
    if deadline is not None and deadline <= int(time.time()):
        raise HTTPException(401, "Pair session expired")
    row = await _record(directus, _hash(old_token))
    row_deadline = int(row["expires_at"]) if row and row.get("expires_at") is not None else None
    if not row or row.get("user_id") != user_id or row.get("pending_ack") or row.get("retired") or row_deadline != deadline:
        raise HTTPException(503, "Pair session deadline missing during rotation")
    if old_token != new_token:
        if not await cache.set(_membership_key(_hash(new_token)), "present", ttl=cache.SESSION_TTL):
            raise HTTPException(503, "Pair session membership unavailable")
        created, _ = await directus.create_item(
            "pair_session_deadlines",
            {"token_hash": _hash(new_token), "user_id": user_id, "expires_at": deadline,
             "pending_ack": False, "relay_acknowledged": True, "retired": False},
            admin_required=True,
        )
        if not created:
            raise HTTPException(503, "Pair session deadline rotation unavailable")
        retired = await directus._update_item("pair_session_deadlines", row["id"], {"retired": True}, admin_required=True)
        if not retired:
            # Both hashes still remain pair-marked. Fail closed before cookie publication.
            raise HTTPException(503, "Pair session retirement unavailable")
    await _mark_cache(cache, _hash(new_token), user_id, deadline, False)


async def enforce_pair_deadline(directus, cache, token: str) -> None:
    await get_pair_deadline(directus, cache, token)


async def get_pair_deadline_hash(directus, cache, token_hash: str) -> int | None:
    """Resolve a WS token's pair deadline without ever needing the raw token."""
    membership = await cache.get(_membership_key(token_hash))
    if membership == "absent":
        return None
    row = await _record(directus, token_hash)
    if not row:
        await cache.set(_membership_key(token_hash), "absent", ttl=300)
        return None
    if row.get("retired"):
        raise HTTPException(401, "Pair session token retired")
    if row.get("pending_ack") or not row.get("relay_acknowledged"):
        raise HTTPException(401, "Pair session awaiting acknowledgement")
    deadline = int(row["expires_at"]) if row.get("expires_at") is not None else None
    if deadline is None:
        return None
    if deadline <= int(time.time()):
        raise HTTPException(401, "Pair session expired")
    return deadline
