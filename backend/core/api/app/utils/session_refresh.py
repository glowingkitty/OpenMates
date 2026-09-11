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


async def refresh_session_token(cache_service, directus_service, refresh_token: str):
    """Rotate once; concurrent HTTP/session requests receive the same cookies."""
    result_key, lock_key = _keys(refresh_token)
    deadline = time.monotonic() + ROTATION_WAIT_SECONDS
    try:
        redis = await cache_service.client
        if redis is None:
            raise SessionRefreshUnavailable()
        while time.monotonic() < deadline:
            encoded = await cache_service.get(result_key)
            if encoded:
                result = _decode(refresh_token, encoded)
                if result["expires_at"] <= time.time() or not result["success"]:
                    return False, None, "Invalid or expired token"
                if result.get("published"):
                    new_token_hash = result["new_token_hash"]
                    link = await cache_service.get(f"session:{new_token_hash}")
                    if not isinstance(link, dict) or link.get("user_id") != result["user_id"]:
                        # A completed rotation whose new session was removed is
                        # not an authentication fallback (e.g. explicit revoke).
                        return False, None, "Invalid or expired token"
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
                success, auth_data, message = await directus_service.refresh_token(refresh_token)
                saved = await cache_service.set(
                    result_key,
                    _encode(refresh_token, {"success": success, "auth_data": auth_data, "published": False, "expires_at": time.time() + ROTATION_GRACE_SECONDS}),
                    ttl=ROTATION_GRACE_SECONDS,
                )
                if not saved:
                    raise SessionRefreshUnavailable()
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
