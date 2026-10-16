"""Durable, per-session security authority for first-party refresh tokens.

Authorization reads use the durable ledger because Redis entries cannot be
atomically invalidated with a Directus revocation. A missing session link can
be rebuilt from an issuer refresh only if this ledger permits it; a durable
tombstone is never interpreted as a cache miss.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid

import pyotp
from fastapi import HTTPException

COLLECTION = "session_security_states"
STRONG_PROOF_SECONDS = 300


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _row(directus, digest: str) -> dict | None:
    try:
        rows = await directus.get_items(
            COLLECTION,
            params={"filter": {"token_hash": {"_eq": digest}},
                    "fields": "id,token_hash,user_id,logical_session_id,expires_at,revoked,retired,strong_verified_at,proof_method,risk_pending,verified_login_method,verified_credential_version,verified_lookup_digest,login_verified_at",
                    "limit": 1},
            admin_required=True,
            no_cache=True,
            raise_on_error=True,
        )
    except Exception as exc:
        raise HTTPException(503, "Session verification temporarily unavailable") from exc
    return rows[0] if rows else None


def _check(row: dict, user_id: str | None = None, *, allow_risk: bool = True) -> dict:
    if user_id is not None and row.get("user_id") != user_id:
        raise HTTPException(401, "Invalid session")
    try:
        expires_at = int(row["expires_at"])
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Session security state invalid") from exc
    if row.get("revoked") or row.get("retired") or expires_at <= int(time.time()):
        raise HTTPException(401, "Session expired or revoked")
    if not allow_risk and row.get("risk_pending"):
        raise HTTPException(401, "Session verification required")
    return row


async def get_rotation_source_state(directus, digest: str, *, allow_risk: bool = True) -> dict | None:
    """Inspect rotation lineage without authorizing a retired credential.

    Only the encrypted, published successor resolver may use this read. Expiry,
    revocation and risk still apply to the source; ordinary reads reject retired.
    """
    row = await _row(directus, digest)
    if row:
        _check({**row, "retired": False}, allow_risk=allow_risk)
    return row


async def get_session_state(directus, digest: str, *, user_id: str | None = None,
                            allow_risk: bool = True) -> dict | None:
    row = await _row(directus, digest)
    return _check(row, user_id, allow_risk=allow_risk) if row else None


async def get_session_state_cached(directus, cache, digest: str, *,
                                   user_id: str | None = None,
                                   allow_risk: bool = True) -> dict | None:
    """Read durable authority for every authorization, including legacy absence.

    Redis cannot atomically publish a Directus revocation with an in-flight cache
    fill. Both an old active row and an old ``absent`` result could otherwise be
    written after revocation; the latter would permit the legacy-session path.
    Ignore existing cache entries during rollout and never republish either kind.
    """
    row = await _row(directus, digest)
    return _check(row, user_id, allow_risk=allow_risk) if row else None


async def register_session_state(directus, cache, token: str, user_id: str,
                                 *, ttl_seconds: int, strong_proof: bool = False,
                                 verified_login_method: str | None = None,
                                 verified_credential_version: int | None = None,
                                 verified_lookup_digest: str | None = None) -> dict:
    """Persist authority before publishing a new login credential."""
    digest = token_hash(token)
    return await _register_session_hash_state(
        directus, cache, digest, user_id,
        ttl_seconds=ttl_seconds, strong_proof=strong_proof,
        verified_login_method=verified_login_method,
        verified_credential_version=verified_credential_version,
        verified_lookup_digest=verified_lookup_digest,
    )


async def _register_session_hash_state(directus, cache, digest: str, user_id: str,
                                       *, ttl_seconds: int, strong_proof: bool = False,
                                       verified_login_method: str | None = None,
                                       verified_credential_version: int | None = None,
                                       verified_lookup_digest: str | None = None) -> dict:
    existing = await _row(directus, digest)
    if existing:
        # Never replace a tombstone or extend a previously fixed deadline.
        return _check(existing, user_id)
    if verified_login_method is None:
        if verified_credential_version is not None or verified_lookup_digest is not None:
            raise ValueError("Login provenance requires a verified method")
    elif verified_login_method not in {"password", "legacy_account_secret", "passkey", "totp", "recovery_key"}:
        raise ValueError("Unsupported verified login method")
    if verified_credential_version is not None and (
        type(verified_credential_version) is not int or verified_credential_version not in (1, 2)
    ):
        raise ValueError("Unsupported credential version")
    if verified_lookup_digest is not None and not re.fullmatch(r"[0-9a-f]{64}", verified_lookup_digest):
        raise ValueError("Verified lookup digest must be SHA256 hex")
    now = int(time.time())
    payload = {
        "token_hash": digest, "user_id": user_id,
        "logical_session_id": str(uuid.uuid4()),
        "expires_at": now + int(ttl_seconds),
        "revoked": False, "retired": False,
        "strong_verified_at": now if strong_proof else None,
        "proof_method": "verified_login" if strong_proof else None,
        "risk_pending": False,
        "verified_login_method": verified_login_method,
        "verified_credential_version": verified_credential_version,
        "verified_lookup_digest": verified_lookup_digest,
        "login_verified_at": now if verified_login_method is not None else None,
    }
    try:
        created, row = await directus.create_item(COLLECTION, payload, admin_required=True)
    except Exception as exc:
        raise HTTPException(503, "Session security state unavailable") from exc
    if not created or not row:
        # Concurrent first-use migration may have won the unique token-hash
        # insert. Accept only the same account's already-fixed state.
        row = await _row(directus, digest)
        if row is None:
            raise HTTPException(503, "Session security state unavailable")
        _check(row, user_id)
    await cache.delete(f"auth:session-state:{digest}")
    return row


async def ensure_legacy_session_state(directus, cache, token: str, user_id: str) -> dict:
    """Migrate a valid pre-ledger session once without resetting its new deadline."""
    return await ensure_legacy_session_hash_state(directus, cache, token_hash(token), user_id)


async def ensure_legacy_session_hash_state(directus, cache, digest: str, user_id: str) -> dict:
    """Migrate an already authenticated cached session known only by its digest."""
    state = await get_session_state_cached(directus, cache, digest, user_id=user_id)
    if state is not None:
        return state
    token_map = await cache.get(f"user_tokens:{user_id}") or {}
    meta = token_map.get(digest) if isinstance(token_map, dict) else None
    stay_logged_in = bool(meta.get("stay_logged_in")) if isinstance(meta, dict) else False
    ttl = 30 * 86400 if stay_logged_in else cache.SESSION_TTL
    return await _register_session_hash_state(
        directus, cache, digest, user_id, ttl_seconds=ttl,
    )


async def transfer_session_state(directus, cache, old_token: str, new_token: str) -> dict | None:
    """Carry an unchanged deadline and assurance across issuer rotation."""
    old_digest = token_hash(old_token)
    old = await get_session_state(directus, old_digest)
    if old is None or old_token == new_token:
        return old  # Legacy sessions have no ledger row; issuer still validates them.
    new_digest = token_hash(new_token)
    new = await _row(directus, new_digest)
    if new:
        if (new.get("logical_session_id") != old.get("logical_session_id")
                or new.get("user_id") != old.get("user_id")):
            raise HTTPException(503, "Session rotation identity conflict")
        _check(new, old["user_id"])
    else:
        payload = {key: old.get(key) for key in (
            "user_id", "logical_session_id", "expires_at", "revoked",
            "strong_verified_at", "proof_method", "risk_pending",
            "verified_login_method", "verified_credential_version",
            "verified_lookup_digest", "login_verified_at")}
        payload.update(token_hash=new_digest, retired=False)
        try:
            created, new = await directus.create_item(COLLECTION, payload, admin_required=True)
        except Exception as exc:
            raise HTTPException(503, "Session rotation unavailable") from exc
        if not created or not new:
            raise HTTPException(503, "Session rotation unavailable")
    try:
        retired = await directus._update_item(COLLECTION, old["id"], {"retired": True}, admin_required=True)
    except Exception as exc:
        raise HTTPException(503, "Session retirement unavailable") from exc
    if not retired:
        raise HTTPException(503, "Session retirement unavailable")
    await cache.delete(f"auth:session-state:{old_digest}")
    await cache.delete(f"auth:session-state:{new_digest}")
    return new


async def revoke_session_state(directus, cache, digest: str, user_id: str | None = None) -> None:
    row = await _row(directus, digest)
    if row is None:
        # Legacy session: create an immutable tombstone, including when its
        # Redis link is all we know. A later cache miss must never revive it.
        if user_id is None:
            raise HTTPException(503, "Session owner unavailable")
        payload = {"token_hash": digest, "user_id": user_id,
                   "logical_session_id": str(uuid.uuid4()),
                   "expires_at": int(time.time()), "revoked": True,
                   "retired": False, "strong_verified_at": None, "proof_method": None,
                   "risk_pending": False}
        try:
            created, _ = await directus.create_item(COLLECTION, payload, admin_required=True)
        except Exception as exc:
            raise HTTPException(503, "Session revocation unavailable") from exc
        if not created:
            raise HTTPException(503, "Session revocation unavailable")
        await cache.delete(f"auth:session-state:{digest}")
        return
    if user_id is not None and row.get("user_id") != user_id:
        raise HTTPException(401, "Invalid session")
    try:
        updated = await directus._update_item(COLLECTION, row["id"], {"revoked": True}, admin_required=True)
    except Exception as exc:
        raise HTTPException(503, "Session revocation unavailable") from exc
    if not updated:
        raise HTTPException(503, "Session revocation unavailable")
    await cache.delete(f"auth:session-state:{digest}")


async def revoke_logical_session(directus, cache, digest: str, user_id: str) -> set[str]:
    """Revoke a rotation chain without touching the account's sibling sessions."""
    current = await _row(directus, digest)
    if current is None:
        await revoke_session_state(directus, cache, digest, user_id)
        await cache.delete(f"session:{digest}")
        return {digest}
    if current.get("user_id") != user_id or not current.get("logical_session_id"):
        raise HTTPException(401, "Invalid session")
    try:
        rows = await directus.get_items(
            COLLECTION,
            params={"filter": {"user_id": {"_eq": user_id},
                               "logical_session_id": {"_eq": current["logical_session_id"]}},
                    "fields": "token_hash,user_id,logical_session_id", "limit": -1},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
    except Exception as exc:
        raise HTTPException(503, "Session revocation unavailable") from exc
    digests = {row["token_hash"] for row in rows
               if row.get("user_id") == user_id
               and row.get("logical_session_id") == current["logical_session_id"]
               and row.get("token_hash")}
    # Revoke the active successor first: every retired source grace check then
    # fails even if a later lineage tombstone write is unavailable.
    for session_digest in [digest, *sorted(digests - {digest})]:
        await revoke_session_state(directus, cache, session_digest, user_id)
        await cache.delete(f"session:{session_digest}")
    return digests | {digest}


async def revoke_all_user_sessions(directus, cache, user_id: str) -> int:
    """Tombstone every known session before destructive account cleanup."""
    try:
        rows = await directus.get_items(
            COLLECTION,
            params={"filter": {"user_id": {"_eq": user_id}},
                    "fields": "id,token_hash,user_id", "limit": -1},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
    except Exception as exc:
        raise HTTPException(503, "Session revocation unavailable") from exc
    token_map = await cache.get(f"user_tokens:{user_id}") or {}
    digests = {row["token_hash"] for row in rows if isinstance(row, dict) and row.get("token_hash")}
    if isinstance(token_map, dict):
        digests.update(token_map)
    for digest in digests:
        await revoke_session_state(directus, cache, digest, user_id)
        await cache.delete(f"session:{digest}")
    return len(digests)


async def set_session_risk_pending(directus, cache, token: str, user_id: str,
                                   pending: bool) -> None:
    """Persist a session-local risk challenge; stale assurance is cleared."""
    digest = token_hash(token)
    row = await get_session_state_cached(directus, cache, digest, user_id=user_id)
    if row is None:
        row = await ensure_legacy_session_state(directus, cache, token, user_id)
    changes = {"risk_pending": bool(pending)}
    if pending:
        changes.update(strong_verified_at=None, proof_method=None)
    try:
        updated = await directus._update_item(COLLECTION, row["id"], changes, admin_required=True)
    except Exception as exc:
        raise HTTPException(503, "Session risk state unavailable") from exc
    if not updated:
        raise HTTPException(503, "Session risk state unavailable")
    await cache.delete(f"auth:session-state:{digest}")


async def mark_recent_strong_proof(directus, cache, token: str, user_id: str,
                                   *, method: str = "verified_method",
                                   clear_risk: bool = False) -> None:
    """Call only after the server has verified an enrolled method and factors."""
    row = await get_session_state(directus, token_hash(token), user_id=user_id,
                                  allow_risk=clear_risk)
    if row is None:
        raise HTTPException(401, "New login required for sensitive action")
    if method not in {"verified_method", "passkey", "password_totp", "totp",
                      "typed_password_email", "password_v2_email",
                      "legacy_account_secret_email"}:
        raise ValueError("Unsupported proof method")
    changes = {"strong_verified_at": int(time.time()), "proof_method": method}
    if clear_risk:
        changes["risk_pending"] = False
    updated = await directus._update_item(
        COLLECTION, row["id"], changes, admin_required=True)
    if not updated:
        raise HTTPException(503, "Verification state unavailable")
    await cache.delete(f"auth:session-state:{token_hash(token)}")


async def require_recent_strong_proof(directus, cache, token: str, user_id: str) -> None:
    row = await get_session_state_cached(directus, cache, token_hash(token), user_id=user_id, allow_risk=False)
    if row is None:
        raise HTTPException(401, "New login required for sensitive action")
    try:
        verified_at = int(row.get("strong_verified_at") or 0)
    except (TypeError, ValueError):
        verified_at = 0
    now = int(time.time())
    if verified_at > now or now - verified_at >= STRONG_PROOF_SECONDS:
        raise HTTPException(401, "Recent verification required")


async def claim_totp_step(cache, user_id: str, secret: str, code: str) -> bool:
    """Consume one account-wide TOTP time step across all action routes."""
    if not isinstance(secret, str) or not secret or not isinstance(code, str):
        return False
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    matched_step = None
    for offset in (-1, 0, 1):
        step_time = now + offset * totp.interval
        if hmac.compare_digest(totp.at(step_time), code):
            matched_step = step_time // totp.interval
            break
    if matched_step is None:
        return False
    client = await cache.client
    if client is None:
        raise HTTPException(503, "Verification temporarily unavailable")
    key = f"auth:sensitive-totp-used:{user_id}:{matched_step}"
    return bool(await client.set(key, "used", nx=True, ex=120))
