# backend/core/api/app/routes/auth_routes/auth_sessions.py
# Active Sessions management — list, register metadata, revoke sessions, logout-all-others.
# Architecture: docs/architecture/device-sessions.md
# Sensitive per-session metadata (device name, IP, city, country) is client-encrypted
# via master key; the server only stores opaque blobs after registration.

from fastapi import APIRouter, Depends, Request, Response, Cookie, HTTPException
import logging
import hashlib
import json
from typing import Optional, List
from pydantic import BaseModel

from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_current_user,
    get_compliance_service,
)


router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SessionInfo(BaseModel):
    """Public representation of an active session returned to the client."""
    session_id: str  # first 12 chars of token hash (opaque identifier)
    is_current: bool
    created_at: int
    stay_logged_in: bool
    # Plaintext fallbacks — present only if client hasn't registered encrypted meta yet
    device_name: Optional[str] = None
    ip_truncated: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    # Client-encrypted metadata blob (replaces plaintext fields after registration)
    encrypted_meta: Optional[str] = None


class SessionListResponse(BaseModel):
    sessions: List[SessionInfo]


class RegisterMetaRequest(BaseModel):
    encrypted_meta: str  # Base64-encoded IV + ciphertext blob from client-side AES-GCM encryption


class SessionActionResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_id_from_hash(token_hash: str) -> str:
    """Derive a public session_id (first 12 hex chars) from the full token hash."""
    return token_hash[:12]


def _find_token_hash_by_prefix(tokens_map: dict, prefix: str) -> Optional[str]:
    """Find the full token hash that starts with the given prefix."""
    for full_hash in tokens_map:
        if full_hash[:12] == prefix:
            return full_hash
    return None


async def _get_current_token_hash(
    refresh_token: Optional[str],
) -> Optional[str]:
    """Hash the current request's refresh token to match against user_tokens."""
    if not refresh_token:
        return None
    return hashlib.sha256(refresh_token.encode()).hexdigest()


async def _broadcast_force_logout(
    cache_service: CacheService,
    user_id: str,
    reason: str = "session_revoked",
    revoked_session_id: Optional[str] = None,
    exclude_connection_hash: Optional[str] = None,
):
    """
    Publish a force_logout event via Redis so the WebSocket listener
    in websockets.py can forward it to the affected user's connections.

    exclude_connection_hash: the connection_hash of the revoking device.
    The websockets.py listener reads this and passes it as exclude_device_hash
    to broadcast_to_user_specific_event so the revoking device never receives
    the force_logout event and does not log itself out.
    """
    await cache_service.publish_event(
        channel=f"user_updates::{user_id}",
        event_data={
            "event_for_client": "force_logout",
            "user_id_uuid": user_id,
            # exclude_connection_hash is a server-internal routing hint; it is NOT
            # forwarded to the client (stripped in the websockets.py listener).
            "exclude_connection_hash": exclude_connection_hash,
            "payload": {
                "reason": reason,
                "revoked_session_id": revoked_session_id,
            },
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    """
    List all active sessions for the authenticated user.
    Returns session metadata — encrypted blobs if registered, else plaintext fallback.
    """
    user_id = current_user.id
    current_hash = await _get_current_token_hash(refresh_token)

    user_tokens_key = f"user_tokens:{user_id}"
    tokens_map: dict = await cache_service.get(user_tokens_key) or {}

    sessions: List[SessionInfo] = []
    stale_hashes: List[str] = []

    for token_hash, meta in list(tokens_map.items()):
        # Validate the session still exists in cache
        session_cache_key = f"session:{token_hash}"
        session_data = await cache_service.get(session_cache_key)
        if not session_data:
            stale_hashes.append(token_hash)
            continue

        is_current = (token_hash == current_hash)

        # Handle both old format (bare int timestamp) and new format (dict)
        if isinstance(meta, (int, float)):
            # Legacy format — bare timestamp, no metadata
            sessions.append(SessionInfo(
                session_id=_session_id_from_hash(token_hash),
                is_current=is_current,
                created_at=int(meta),
                stay_logged_in=False,
            ))
        elif isinstance(meta, dict):
            has_encrypted = bool(meta.get("encrypted_meta"))
            sessions.append(SessionInfo(
                session_id=_session_id_from_hash(token_hash),
                is_current=is_current,
                created_at=meta.get("created_at", 0),
                stay_logged_in=meta.get("stay_logged_in", False),
                device_name=meta.get("device_name") if not has_encrypted else None,
                ip_truncated=meta.get("ip_truncated") if not has_encrypted else None,
                country_code=meta.get("country_code") if not has_encrypted else None,
                city=meta.get("city") if not has_encrypted else None,
                encrypted_meta=meta.get("encrypted_meta"),

            ))

    # Clean up stale tokens (session expired but still in token list)
    if stale_hashes:
        for sh in stale_hashes:
            tokens_map.pop(sh, None)
        if tokens_map:
            await cache_service.set(user_tokens_key, tokens_map, ttl=604800)
        else:
            await cache_service.delete(user_tokens_key)
        logger.info(f"Cleaned {len(stale_hashes)} stale session(s) from user_tokens for user {user_id[:6]}...")

    # Sort: current session first, then by created_at descending
    sessions.sort(key=lambda s: (not s.is_current, -s.created_at))

    return SessionListResponse(sessions=sessions)


@router.post("/sessions/register-meta", response_model=SessionActionResponse)
async def register_session_meta(
    request: Request,
    body: RegisterMetaRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    """
    Register client-encrypted metadata for the current session.
    The client encrypts {device_name, ip_truncated, city, country_code} with
    the master key and sends the blob here. Server stores it and clears
    the plaintext fallback fields.
    """
    user_id = current_user.id
    current_hash = await _get_current_token_hash(refresh_token)
    if not current_hash:
        raise HTTPException(status_code=401, detail="Missing auth token")

    user_tokens_key = f"user_tokens:{user_id}"
    tokens_map: dict = await cache_service.get(user_tokens_key) or {}

    if current_hash not in tokens_map:
        raise HTTPException(status_code=404, detail="Current session not found in token list")

    meta = tokens_map[current_hash]
    if isinstance(meta, (int, float)):
        # Legacy format — upgrade to dict
        meta = {"created_at": int(meta), "stay_logged_in": False}

    # Store encrypted blob, clear plaintext
    meta["encrypted_meta"] = body.encrypted_meta
    meta.pop("device_name", None)
    meta.pop("ip_truncated", None)
    meta.pop("country_code", None)
    meta.pop("city", None)

    tokens_map[current_hash] = meta
    await cache_service.set(user_tokens_key, tokens_map, ttl=604800)
    logger.info(f"Registered encrypted session meta for user {user_id[:6]}...")

    return SessionActionResponse(success=True, message="Session metadata registered")


@router.delete("/sessions/{session_id}", response_model=SessionActionResponse)
async def revoke_session(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    """
    Revoke a single session by its public session_id (first 12 chars of token hash).
    Cannot revoke the current session — use /logout for that.
    Broadcasts a force_logout event via Redis so the target device logs out in real-time.
    """
    user_id = current_user.id
    current_hash = await _get_current_token_hash(refresh_token)

    user_tokens_key = f"user_tokens:{user_id}"
    tokens_map: dict = await cache_service.get(user_tokens_key) or {}

    target_hash = _find_token_hash_by_prefix(tokens_map, session_id)
    if not target_hash:
        raise HTTPException(status_code=404, detail="Session not found")

    if target_hash == current_hash:
        raise HTTPException(status_code=400, detail="Cannot revoke the current session. Use logout instead.")

    # 1. Delete the session cache entry — makes the session immediately invalid
    await cache_service.delete(f"session:{target_hash}")

    # 2. Remove from user_tokens map
    del tokens_map[target_hash]
    if tokens_map:
        await cache_service.set(user_tokens_key, tokens_map, ttl=604800)
    else:
        await cache_service.delete(user_tokens_key)

    # 3. Broadcast force_logout so WebSocket pushes it to the target device.
    #    Pass the revoking session's connection_hash so the listener in
    #    websockets.py skips that WebSocket — the revoking device must NOT
    #    receive force_logout and must NOT log itself out.
    current_meta = tokens_map.get(current_hash, {}) if current_hash else {}
    current_connection_hash: Optional[str] = (
        current_meta.get("connection_hash") if isinstance(current_meta, dict) else None
    )
    await _broadcast_force_logout(
        cache_service,
        user_id,
        "session_revoked",
        session_id,
        exclude_connection_hash=current_connection_hash,
    )

    # 4. Compliance log
    compliance_service.log_auth_event_safe(
        event_type="session_revoked",
        user_id=user_id,
        device_fingerprint=session_id,
        location="",
        status="success",
        details={"revoked_session_prefix": session_id},
    )

    logger.info(f"Revoked session {session_id} for user {user_id[:6]}... ({len(tokens_map)} remaining)")
    return SessionActionResponse(success=True, message="Session revoked")


@router.post("/sessions/logout-others", response_model=SessionActionResponse)
async def logout_all_others(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    """
    Log out all sessions except the current one.
    Useful when user suspects compromise but wants to stay logged in.
    """
    user_id = current_user.id
    current_hash = await _get_current_token_hash(refresh_token)
    if not current_hash:
        raise HTTPException(status_code=401, detail="Missing auth token")

    user_tokens_key = f"user_tokens:{user_id}"
    tokens_map: dict = await cache_service.get(user_tokens_key) or {}

    revoked_count = 0
    for token_hash in list(tokens_map.keys()):
        if token_hash == current_hash:
            continue
        # Delete session cache for each other token
        await cache_service.delete(f"session:{token_hash}")
        del tokens_map[token_hash]
        revoked_count += 1

    # Update token list — only current session remains
    if tokens_map:
        await cache_service.set(user_tokens_key, tokens_map, ttl=604800)
    else:
        await cache_service.delete(user_tokens_key)

    # Broadcast force_logout to all connections, excluding the revoking device.
    # Without the exclusion the revoking device would receive the event and log
    # itself out — the same bug as single-session revocation.
    if revoked_count > 0:
        current_meta = tokens_map.get(current_hash, {}) if current_hash else {}
        current_connection_hash: Optional[str] = (
            current_meta.get("connection_hash") if isinstance(current_meta, dict) else None
        )
        await _broadcast_force_logout(
            cache_service,
            user_id,
            "all_other_sessions_revoked",
            exclude_connection_hash=current_connection_hash,
        )

    compliance_service.log_auth_event_safe(
        event_type="logout_all_others",
        user_id=user_id,
        device_fingerprint="all_other_devices",
        location="",
        status="success",
        details={"revoked_count": revoked_count},
    )

    logger.info(f"Revoked {revoked_count} other session(s) for user {user_id[:6]}...")
    return SessionActionResponse(success=True, message=f"Logged out {revoked_count} other session(s)")


@router.post("/sessions/logout-all-devices", response_model=SessionActionResponse)
async def logout_all_devices(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
):
    """
    Nuclear option: log out ALL sessions (including current) AND clear the
    connected_devices list so every future login is treated as a new device
    (triggers re-auth / 2FA).
    """
    user_id = current_user.id

    # 1. Broadcast force_logout to ALL connections before clearing cache
    await _broadcast_force_logout(cache_service, user_id, "all_devices_logout")

    # 2. Clear all user sessions from cache
    user_tokens_key = f"user_tokens:{user_id}"
    tokens_map: dict = await cache_service.get(user_tokens_key) or {}
    for token_hash in list(tokens_map.keys()):
        await cache_service.delete(f"session:{token_hash}")
    await cache_service.delete(user_tokens_key)

    # 3. Clear connected_devices in Directus so all devices are "new" on next login
    try:
        await directus_service.update_user(user_id, {"connected_devices": json.dumps([])})
        await cache_service.update_user(user_id, {"connected_devices": json.dumps([])})
        logger.info(f"Cleared connected_devices for user {user_id[:6]}...")
    except Exception as e:
        logger.error(f"Error clearing connected_devices for user {user_id[:6]}...: {e}", exc_info=True)

    # 4. Logout from Directus
    try:
        if refresh_token:
            await directus_service.logout_user(refresh_token)
    except Exception as e:
        logger.warning(f"Directus logout failed during logout-all-devices: {e}")

    # 5. Clear auth cookies
    for cookie in request.cookies:
        if cookie.startswith("auth_"):
            response.delete_cookie(key=cookie, httponly=True, secure=True)

    # 6. Compliance
    compliance_service.log_auth_event_safe(
        event_type="logout_all_devices",
        user_id=user_id,
        device_fingerprint="all_devices_cleared",
        location="",
        status="success",
        details={"sessions_cleared": len(tokens_map), "devices_cleared": True},
    )

    logger.info(f"Logged out all devices and cleared connected_devices for user {user_id[:6]}...")
    return SessionActionResponse(success=True, message="All sessions terminated and device list cleared")
