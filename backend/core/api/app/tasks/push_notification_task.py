# backend/core/api/app/tasks/push_notification_task.py
"""
Celery task for sending browser push notifications to users.

Architecture:
- Called from websockets.py after an AI response completes and the user is offline.
- Sends a Web Push notification to the user's stored browser PushSubscription.
- If push delivery fails (e.g., subscription expired / 410 Gone), the user's
  push_notification_enabled flag is cleared in Directus so future messages fall back
  to email immediately.
- The push_notification_service singleton holds the VAPID keys initialised at startup.

See docs/architecture/notifications.md for the full notification flow.
"""

import logging
import asyncio
from typing import Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.push_notification_service import push_notification_service

logger = logging.getLogger(__name__)


@app.task(
    name='app.tasks.push_notification_task.send_push_notification',
    bind=True,
    max_retries=2,
    default_retry_delay=5,
)
def send_push_notification(
    self,
    subscription_json: str,
    title: str,
    body: str,
    url: Optional[str] = None,
    tag: Optional[str] = None,
    user_id: Optional[str] = None,
) -> bool:
    """
    Celery task to send a browser push notification.

    Args:
        subscription_json: Raw JSON string of the browser PushSubscription object.
        title: Notification title.
        body: Notification body text.
        url: URL to open on click (defaults to '/').
        tag: Deduplication tag; replaces previous notification with same tag.
        user_id: User ID (for logging / subscription cleanup on expiry).

    Returns:
        True if the push was accepted, False otherwise.
    """
    uid_prefix = (user_id or "unknown")[:6]
    log_prefix = f"[PushTask user={uid_prefix}]"

    if not push_notification_service.is_ready():
        logger.error(f"{log_prefix} Push service not initialised — skipping")
        return False

    success = push_notification_service.send_push_notification(
        subscription_json=subscription_json,
        title=title,
        body=body,
        url=url,
        tag=tag,
    )

    if not success:
        logger.warning(f"{log_prefix} Push delivery failed")
        # Attempt to clear the stale subscription so future notifications fall
        # back to email immediately (best-effort, non-blocking).
        if user_id:
            try:
                asyncio.run(_clear_stale_subscription(user_id))
            except Exception as e:
                logger.warning(f"{log_prefix} Could not clear stale subscription: {e}")

    return success


async def _clear_stale_subscription(user_id: str) -> None:
    """
    Remove a broken push subscription from Directus and invalidate the user cache
    so the next offline check sees push_notification_enabled=False and falls back
    to email without delay.
    """
    try:
        from backend.core.api.app.utils.secrets_manager import SecretsManager
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService

        secrets_manager = SecretsManager()
        await secrets_manager.initialize()

        try:
            directus = DirectusService(cache_service=None, encryption_service=None)
            updated = await directus.update_user(user_id, {
                "push_notification_enabled": False,
                "push_notification_subscription": None,
            })
            if updated:
                logger.info(f"[PushTask] Cleared stale push subscription for user {user_id[:6]}...")

            cache = CacheService()
            try:
                await cache.delete_user_cache(user_id)
            finally:
                await cache.close()
        finally:
            await secrets_manager.aclose()
    except Exception as e:
        logger.warning(f"[PushTask] _clear_stale_subscription failed for {user_id[:6]}...: {e}")
