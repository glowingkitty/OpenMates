"""Short-lived, metadata-only human presence for chat email decisions.

Leases live in the shared cache so WebSocket and Celery processes see the same
state. A missing cache or expired lease never claims that a human is present.
"""

import hashlib
import json
import os
import time
from collections.abc import Mapping


LEASE_SECONDS = 75
MESSAGE_VIEW_SECONDS = 7 * 24 * 60 * 60


def classify_lifecycle_client(payload: dict, headers: Mapping[str, str]) -> tuple[str, bool]:
    """Use authenticated socket headers only for legacy Apple frames with no type."""
    if "client_type" in payload:
        explicit = payload["client_type"]
        return (explicit, False) if isinstance(explicit, str) and explicit in {"web", "apple", "cli"} else ("automation", False)

    user_agent = headers.get("user-agent", "")
    client = headers.get("x-openmates-client", "").strip().lower()
    bundle_id = headers.get("x-openmates-bundle-id", "").strip()
    expected_ios_bundle = os.getenv("OPENMATES_IOS_BUNDLE_ID", "").strip()
    if (
        user_agent.startswith("OpenMates-Apple/")
        and len(user_agent) > len("OpenMates-Apple/")
        and client in {"ios", "macos", "watchos"}
        and bundle_id
        and (client != "ios" or not expected_ios_bundle or bundle_id == expected_ios_bundle)
    ):
        return "apple", True
    return "automation", False


async def refresh_legacy_apple_presence_on_message(
    cache, user_id: str, connection_id: str, foreground: bool,
    chat_id: str | None = None, now: float | None = None,
) -> None:
    """Extend a declared Apple lease on an application message; background clears it."""
    await report_presence(cache, user_id, connection_id, "apple", foreground, chat_id=chat_id, now=now)


def _connection_key(user_id: str, connection_id: str) -> str:
    digest = hashlib.sha256(connection_id.encode()).hexdigest()
    return f"notification_presence:{user_id}:connection:{digest}"


def _connections_key(user_id: str) -> str:
    return f"notification_presence:{user_id}:connections"


def _view_key(user_id: str, chat_id: str, message_id: str) -> str:
    digest = hashlib.sha256(f"{chat_id}:{message_id}".encode()).hexdigest()
    return f"notification_viewed:{user_id}:{digest}"


async def report_presence(
    cache, user_id: str, connection_id: str, client_type: str,
    foreground: bool, interactive: bool = False, chat_id: str | None = None,
    now: float | None = None,
) -> None:
    """Refresh one authenticated connection's human presence lease."""
    client = await cache.client
    if client is None:
        return
    key = _connection_key(user_id, connection_id)
    index = _connections_key(user_id)
    if not foreground or client_type not in {"web", "apple", "cli"} or (client_type == "cli" and not interactive):
        await client.delete(key)
        await client.zrem(index, key)
        return
    timestamp = time.time() if now is None else now
    payload = {"client_type": client_type, "interactive": bool(interactive), "chat_id": chat_id,
               "expires_at": timestamp + LEASE_SECONDS}
    async with client.pipeline(transaction=True) as pipe:
        pipe.set(key, json.dumps(payload), ex=LEASE_SECONDS)
        pipe.zadd(index, {key: timestamp + LEASE_SECONDS})
        pipe.expire(index, LEASE_SECONDS)
        await pipe.execute()


async def clear_presence(cache, user_id: str, connection_id: str) -> None:
    client = await cache.client
    if client is None:
        return
    key = _connection_key(user_id, connection_id)
    await client.delete(key)
    await client.zrem(_connections_key(user_id), key)


async def has_active_human(cache, user_id: str, chat_id: str, now: float | None = None) -> bool:
    """Web/Apple foreground activity covers all chats; interactive CLI covers one."""
    client = await cache.client
    if client is None:
        return False
    timestamp = time.time() if now is None else now
    index = _connections_key(user_id)
    await client.zremrangebyscore(index, "-inf", timestamp)
    keys = await client.zrangebyscore(index, f"({timestamp}", "+inf")
    if not keys:
        return False
    values = await client.mget(keys)
    for value in values:
        if not value:
            continue
        try:
            lease = json.loads(value)
        except (TypeError, ValueError):
            continue
        if lease.get("expires_at", 0) <= timestamp:
            continue
        if lease.get("client_type") in {"web", "apple"}:
            return True
        if lease.get("client_type") == "cli" and lease.get("interactive") is True and lease.get("chat_id") == chat_id:
            return True
    return False


async def mark_message_viewed(cache, user_id: str, chat_id: str, message_id: str, now: float | None = None) -> bool:
    """Record only an opaque message identity; caller verifies chat ownership."""
    client = await cache.client
    if client is not None:
        await client.set(_view_key(user_id, chat_id, message_id), "1", ex=MESSAGE_VIEW_SECONDS)
        return True
    return False


async def is_message_viewed(cache, user_id: str, chat_id: str, message_id: str) -> bool:
    client = await cache.client
    return bool(client and await client.exists(_view_key(user_id, chat_id, message_id)))
