# backend/core/api/app/tasks/push_notification_task.py
"""
Celery task for sending browser or native push notifications to users.

Architecture:
- Called from websockets.py after an AI response completes and the user is offline.
- Sends Web Push and APNs notifications to the user's stored targets.
- A confirmed 410 Gone for a legacy single browser subscription clears that
  exact stored subscription, allowing email fallback. Other delivery failures
  preserve the user's push registrations and settings.
- The push_notification_service singleton holds process-local delivery credentials.

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
    chat_id: Optional[str] = None,
    category: str = "OPENMATES_CHAT_MESSAGE",
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
        chat_id: Native notification chat target for APNs actions.
        category: Native notification category identifier.
        user_id: User ID (for logging / subscription cleanup on expiry).

    Returns:
        True if the push was accepted, False otherwise.
    """
    uid_prefix = (user_id or "unknown")[:6]
    log_prefix = f"[PushTask user={uid_prefix}]"

    if not _can_dispatch_subscription(subscription_json):
        logger.error(f"{log_prefix} Push service not initialised — skipping")
        return False

    expired_web_target = False

    def mark_expired_web_target() -> None:
        nonlocal expired_web_target
        expired_web_target = True

    success = push_notification_service.send_push_notification(
        subscription_json=subscription_json,
        title=title,
        body=body,
        url=url,
        tag=tag,
        chat_id=chat_id,
        category=category,
        on_expired_web_target=mark_expired_web_target,
    )

    if not success:
        logger.warning(f"{log_prefix} Push delivery failed")
        # Only a known permanent failure of a sole browser target may clear
        # this user-wide setting. Other targets must remain registered.
        if user_id and expired_web_target and _should_clear_failed_subscription(subscription_json):
            try:
                asyncio.run(_clear_stale_subscription(user_id, subscription_json))
            except Exception as e:
                logger.warning(f"{log_prefix} Could not clear stale subscription: {e}")

    return success


def _should_clear_failed_subscription(subscription_json: str) -> bool:
    """Only one-browser records can be safely cleared as a whole."""
    try:
        from backend.core.api.app.services.push_subscription_targets import normalize_push_subscription_targets

        targets = normalize_push_subscription_targets(subscription_json)
    except Exception:
        return False
    return len(targets) == 1 and targets[0].get("type", "web") == "web" and bool(targets[0].get("endpoint"))


def _can_dispatch_subscription(subscription_json: str) -> bool:
    """VAPID gates browser delivery, while APNs can dispatch independently."""
    if push_notification_service.is_ready():
        return True
    if not push_notification_service.is_apns_ready():
        return False
    try:
        import json

        subscription = json.loads(subscription_json)
    except Exception:
        return False
    if not isinstance(subscription, dict):
        return False
    if subscription.get("type") == "apns":
        return True
    if subscription.get("type") == "multi":
        targets = subscription.get("targets")
        if not isinstance(targets, list):
            return False
        return any(
            isinstance(target, dict) and target.get("type") == "apns"
            for target in targets
        )
    return False


async def _clear_stale_subscription(user_id: str, failed_subscription_json: str) -> None:
    """
    Remove a broken push subscription from Directus and invalidate the user cache
    so the next offline check sees push_notification_enabled=False and falls back
    to email without delay.
    """
    try:
        from backend.core.api.app.utils.secrets_manager import SecretsManager
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.services.push_subscription_lock import (
            push_subscription_write_lock,
            require_push_subscription_lock,
        )

        secrets_manager = SecretsManager()
        await secrets_manager.initialize()

        try:
            directus = DirectusService(cache_service=None, encryption_service=None)
            cache = CacheService()
            try:
                async with push_subscription_write_lock(cache, user_id) as lock:
                    current_user = await directus.get_user_fields_direct(
                        user_id, ["push_notification_subscription"]
                    )
                    if not isinstance(current_user, dict) or current_user.get("push_notification_subscription") != failed_subscription_json:
                        logger.info("[PushTask] Subscription changed; preserving current push targets")
                        return
                    await require_push_subscription_lock(lock)
                    updated = await directus.update_user(user_id, {
                        "push_notification_enabled": False,
                        "push_notification_subscription": None,
                    })
                    if updated:
                        logger.info(f"[PushTask] Cleared stale push subscription for user {user_id[:6]}...")
                        await cache.delete_user_cache(user_id)
            finally:
                await cache.close()
        finally:
            await secrets_manager.aclose()
    except Exception as e:
        logger.warning(f"[PushTask] _clear_stale_subscription failed for {user_id[:6]}...: {e}")
