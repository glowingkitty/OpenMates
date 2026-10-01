"""Serialize writes to each user's push targets across API and Celery workers."""

from contextlib import asynccontextmanager


class PushSubscriptionLockUnavailable(RuntimeError):
    """A push write must fail closed if its shared lock cannot be held."""


@asynccontextmanager
async def push_subscription_write_lock(cache_service, user_id: str):
    client = await cache_service.client
    if client is None:
        raise PushSubscriptionLockUnavailable("Push subscription lock store unavailable")
    lock = client.lock(f"push:subscription:{user_id}", timeout=120)
    try:
        acquired = await lock.acquire(blocking=True, blocking_timeout=10)
    except Exception as exc:
        raise PushSubscriptionLockUnavailable("Could not acquire push subscription lock") from exc
    if not acquired:
        raise PushSubscriptionLockUnavailable("Push subscription lock busy")
    try:
        yield lock
    finally:
        try:
            await lock.release()
        except Exception:
            # Redis lock release checks the owner token; an expired lease must
            # never release another worker's replacement lock.
            pass


async def require_push_subscription_lock(lock) -> None:
    """Refresh and verify the lease immediately before the database write."""
    try:
        # Redis verifies the owner token while extending, avoiding a check
        # followed by a nearly expired lease during the Directus PATCH.
        if await lock.extend(120, replace_ttl=True):
            return
    except Exception as exc:
        raise PushSubscriptionLockUnavailable("Push subscription lock state unavailable") from exc
    raise PushSubscriptionLockUnavailable("Push subscription lock expired")
