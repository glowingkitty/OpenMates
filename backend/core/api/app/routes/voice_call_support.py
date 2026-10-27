"""First-party paid voice admission, lease and settlement helpers.

No provider-specific request or pricing code belongs in this module.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)
LOCK_TTL_SECONDS = 90
LOCK_RENEW_SECONDS = 30

def _decode_media(value: Any, *, max_bytes: int, jpeg: bool = False) -> bytes:
    if not isinstance(value, str) or len(value) > max_bytes * 4 // 3 + 8:
        raise ValueError("Media chunk size is invalid")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("Media encoding is invalid") from exc
    if not data or len(data) > max_bytes or (jpeg and not (data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"))):
        raise ValueError("Media chunk is invalid")
    return data


async def _authoritative_credits(websocket: WebSocket, user_id: str) -> int:
    """Cache projection with encrypted Directus fallback; fail admission closed."""
    cache = websocket.app.state.cache_service
    projection = await cache.get_billing_projection(user_id)
    if projection is not None and isinstance(projection.get("credits"), int):
        return projection["credits"]
    rows = await websocket.app.state.directus_service.get_items(
        "directus_users",
        params={"filter[id][_eq]": user_id, "fields": "id,vault_key_id,encrypted_credit_balance", "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Billing balance unavailable")
    key_id = rows[0].get("vault_key_id")
    encrypted = rows[0].get("encrypted_credit_balance")
    if not isinstance(key_id, str) or not isinstance(encrypted, str):
        raise RuntimeError("Billing balance unavailable")
    plaintext = await websocket.app.state.encryption_service.decrypt_with_user_key(encrypted, key_id)
    if plaintext is None:
        raise RuntimeError("Billing balance unavailable")
    credits = int(plaintext)
    await cache.set_billing_projection(
        user_id, credits=credits, encrypted_balance=encrypted, vault_key_id=key_id,
    )
    return credits


async def _session_still_valid(websocket: WebSocket, auth_data: dict[str, Any]) -> bool:
    """Recheck the durable session authority during an open paid connection."""
    from backend.core.api.app.services.pair_session_deadline import get_pair_deadline_hash
    from backend.core.api.app.services.session_security_state import get_session_state_cached

    now = int(time.time())
    for deadline in (auth_data.get("session_expires_at"), auth_data.get("pair_expires_at")):
        if deadline is not None:
            try:
                if int(deadline) <= now:
                    return False
            except (TypeError, ValueError):
                return False
    digest = auth_data.get("session_hash")
    if not isinstance(digest, str) or not digest:
        return False
    try:
        state = await get_session_state_cached(
            websocket.app.state.directus_service,
            websocket.app.state.cache_service,
            digest,
            user_id=auth_data["user_id"],
            allow_risk=False,
        )
        if not state:
            return False
        if auth_data.get("pair_expires_at") is not None:
            pair_deadline = await get_pair_deadline_hash(
                websocket.app.state.directus_service,
                websocket.app.state.cache_service,
                digest,
            )
            if pair_deadline is None or pair_deadline <= now:
                return False
        return True
    except Exception:
        return False


async def _acquire_lock(websocket: WebSocket, user_hash: str) -> tuple[Any, str, str]:
    key = f"voice:call:active:{user_hash}"
    token = uuid.uuid4().hex
    client = await websocket.app.state.cache_service.client
    if not client or not await client.set(key, token, nx=True, ex=LOCK_TTL_SECONDS):
        raise RuntimeError("A call is already active or admission is unavailable")
    return client, key, token


async def _release_lock(client: Any, key: str, token: str) -> None:
    try:
        await client.eval(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end",
            1, key, token,
        )
    except Exception:
        logger.warning("Voice-call lock release failed", exc_info=True)


async def _renew_lock(client: Any, key: str, token: str) -> None:
    """Refresh only this call's lease; loss of ownership stops paid work."""
    while True:
        await asyncio.sleep(LOCK_RENEW_SECONDS)
        renewed = await client.eval(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('EXPIRE', KEYS[1], ARGV[2]) else return 0 end",
            1, key, token, LOCK_TTL_SECONDS,
        )
        if renewed != 1:
            raise RuntimeError("Voice-call lease lost")


async def _finish_accepted_job(task: asyncio.Task[None]) -> None:
    """Preserve an accepted job's settlement through request cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            asyncio.current_task().uncancel()
    await task
    if cancelled:
        raise asyncio.CancelledError


def _billing(websocket: WebSocket) -> Any:
    # BillingService imports the wider task graph; defer it for route import.
    from backend.core.api.app.services.billing_service import BillingService

    return BillingService(
        websocket.app.state.cache_service,
        websocket.app.state.directus_service,
        websocket.app.state.encryption_service,
        websocket.app.state.server_stats_service,
    )
