"""Coordinate first-party refresh rotation across API workers.

Only an overlapping request holding the same old credential can decrypt the
short-lived result. Reuse also requires the new cache session to remain active,
so logout/revocation never becomes a successful refresh through this grace path.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from backend.core.api.app.services.pair_session_deadline import get_pair_deadline, transfer_pair_deadline, enforce_pair_rotation_lineage
from backend.core.api.app.services.session_security_state import (
    get_session_state_cached, get_rotation_source_state, transfer_session_state,
)
from backend.core.api.app.utils.directus_cookies import extract_directus_refresh_token

ROTATION_GRACE_SECONDS = 15
ROTATION_WAIT_SECONDS = 8
_LOCK_RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"


class SessionRefreshUnavailable(HTTPException):
    def __init__(self):
        super().__init__(status_code=503, detail="Session verification temporarily unavailable")


def _keys(token: str) -> tuple[str, str]:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"auth:refresh-result:{digest}", f"auth:refresh-lock:{digest}"


def _cipher(token: str) -> AESGCM:
    # Domain separation is essential: the result cache key must not reveal the
    # encryption key. No raw refresh/access token is stored in Redis or logged.
    return AESGCM(hashlib.sha256(b"openmates-refresh-result\0" + token.encode()).digest())


def _encode(token: str, value: dict) -> str:
    nonce = os.urandom(12)
    payload = json.dumps(value).encode()
    return base64.b64encode(nonce + _cipher(token).encrypt(nonce, payload, None)).decode()


def _decode(token: str, value: str) -> dict:
    payload = base64.b64decode(value)
    return json.loads(_cipher(token).decrypt(payload[:12], payload[12:], None))


async def _published_successor(cache_service, directus_service, refresh_token: str, result: dict, *, allow_risk: bool = True) -> str:
    """Resolve only the bounded result published by the completed rotation."""
    if not result.get("success") or result["expires_at"] <= time.time():
        raise HTTPException(401, "Invalid or expired token")
    source = await get_rotation_source_state(
        directus_service, hashlib.sha256(refresh_token.encode()).hexdigest(), allow_risk=allow_risk,
    )
    if not result.get("published"):
        # The rotation owner is still validating/caching the successor. Deny
        # protected work without turning a bounded publication gap into logout.
        raise SessionRefreshUnavailable()
    new_token = extract_directus_refresh_token((result.get("auth_data") or {}).get("cookies", {}))
    if not new_token or source is None:
        raise HTTPException(401, "Invalid session rotation")
    new_hash = hashlib.sha256(new_token.encode()).hexdigest()
    user_id = result.get("user_id")
    link = await cache_service.get(f"session:{new_hash}")
    if (new_hash != result.get("new_token_hash") or not user_id
            or source.get("user_id") != user_id or not isinstance(link, dict)
            or link.get("user_id") != user_id):
        raise HTTPException(401, "Invalid session rotation")
    successor = await get_session_state_cached(
        directus_service, cache_service, new_hash, user_id=user_id, allow_risk=allow_risk,
    )
    if (successor is None or not source.get("logical_session_id")
            or successor.get("logical_session_id") != source["logical_session_id"]
            or successor.get("expires_at") != source.get("expires_at")):
        raise HTTPException(401, "Invalid session rotation")
    await enforce_pair_rotation_lineage(directus_service, cache_service, refresh_token, new_token, user_id)
    return new_token


async def resolve_session_credential(cache_service, directus_service, refresh_token: str, *, allow_risk: bool = True) -> str:
    """Authorize an active credential or its published 15-second successor.

    Retirement is never a cache-miss fallback. The encrypted result proves the
    caller held the source secret; durable lineage and successor authority are
    checked again before any protected operation can run.
    """
    source = await get_rotation_source_state(
        directus_service, hashlib.sha256(refresh_token.encode()).hexdigest(), allow_risk=allow_risk,
    )
    encoded = await cache_service.get(_keys(refresh_token)[0])
    if encoded:
        try:
            result = _decode(refresh_token, encoded)
        except Exception as exc:
            raise SessionRefreshUnavailable() from exc
        if (source is None or source.get("retired") or result.get("success") or result.get("published")):
            return await _published_successor(
                cache_service, directus_service, refresh_token, result, allow_risk=allow_risk,
            )
    if source and source.get("retired"):
        raise HTTPException(401, "Session expired or revoked")
    await get_pair_deadline(directus_service, cache_service, refresh_token)
    return refresh_token


async def refresh_session_token(cache_service, directus_service, refresh_token: str):
    """Rotate once; concurrent HTTP/session requests receive the same cookies."""
    result_key, lock_key = _keys(refresh_token)
    deadline = time.monotonic() + ROTATION_WAIT_SECONDS
    try:
        redis = await cache_service.client
        if redis is None:
            raise SessionRefreshUnavailable()
        # Validate source expiry/revocation before considering the encrypted
        # result, but defer retirement to its published successor check.
        await get_rotation_source_state(
            directus_service, hashlib.sha256(refresh_token.encode()).hexdigest(),
        )
        while time.monotonic() < deadline:
            encoded = await cache_service.get(result_key)
            if encoded:
                result = _decode(refresh_token, encoded)
                if result["expires_at"] <= time.time() or not result["success"]:
                    return False, None, "Invalid or expired token"
                if result.get("published"):
                    try:
                        await _published_successor(cache_service, directus_service, refresh_token, result)
                    except HTTPException as exc:
                        if exc.status_code == 401:
                            return False, None, "Invalid or expired token"
                        raise
                    return True, result["auth_data"], "Token refreshed"
                await asyncio.sleep(0.05)
                continue

            owner = secrets.token_hex(16)
            if not await redis.set(lock_key, owner, nx=True, ex=ROTATION_GRACE_SECONDS):
                await asyncio.sleep(0.05)
                continue
            try:
                # Another worker may have published between our GET and SET NX.
                if await cache_service.get(result_key):
                    continue
                # A retired source without a published result cannot rotate
                # again or become an issuer-validation fallback.
                await get_session_state_cached(
                    directus_service, cache_service, hashlib.sha256(refresh_token.encode()).hexdigest(),
                )
                paired = await get_pair_deadline(directus_service, cache_service, refresh_token)
                success, auth_data, message = await directus_service.refresh_token(refresh_token)
                if success:
                    new_token = extract_directus_refresh_token((auth_data or {}).get("cookies", {}))
                    if not new_token:
                        raise SessionRefreshUnavailable()
                # Fence the issuer result before any durable source retirement.
                # Overlapping guards may see an unavailable unpublished result,
                # but can never see a retired source with no result in this window.
                saved = await cache_service.set(
                    result_key,
                    _encode(refresh_token, {"success": success, "auth_data": auth_data, "published": False, "expires_at": time.time() + ROTATION_GRACE_SECONDS}),
                    ttl=ROTATION_GRACE_SECONDS,
                )
                if not saved:
                    raise SessionRefreshUnavailable()
                if success:
                    await transfer_session_state(
                        directus_service, cache_service, refresh_token, new_token,
                    )
                if success and paired:
                    await transfer_pair_deadline(
                        directus_service, cache_service, refresh_token, new_token,
                        paired[0], paired[1],
                    )
                return success, auth_data, message
            finally:
                await redis.eval(_LOCK_RELEASE, 1, lock_key, owner)
        raise SessionRefreshUnavailable()
    except HTTPException:
        raise
    except Exception as error:
        raise SessionRefreshUnavailable() from error


async def complete_refresh_rotation(
    cache_service, *, old_refresh_token: str, new_refresh_token: str, user_id: str,
) -> None:
    """Publish only after the new session is cached; retire the old cache link."""
    result_key, _ = _keys(old_refresh_token)
    try:
        encoded = await cache_service.get(result_key)
        if not encoded:
            raise SessionRefreshUnavailable()
        result = _decode(old_refresh_token, encoded)
        remaining = math.ceil(result["expires_at"] - time.time())
        new_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()
        link = await cache_service.get(f"session:{new_hash}")
        if remaining <= 0 or not isinstance(link, dict) or link.get("user_id") != user_id:
            raise SessionRefreshUnavailable()
        result.update(
            published=True,
            user_id=user_id,
            new_token_hash=new_hash,
        )
        if not await cache_service.set(result_key, _encode(old_refresh_token, result), ttl=remaining):
            raise SessionRefreshUnavailable()
        if old_refresh_token != new_refresh_token:
            await cache_service.delete(
                f"session:{hashlib.sha256(old_refresh_token.encode()).hexdigest()}"
            )
    except HTTPException:
        raise
    except Exception as error:
        raise SessionRefreshUnavailable() from error
