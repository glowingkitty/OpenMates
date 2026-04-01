# backend/core/api/app/services/push_notification_service.py
"""
Web Push Notification Service — VAPID key management and push delivery.

Architecture:
- VAPID keys are generated once at startup and persisted to Vault at
  kv/data/providers/vapid (public_key + private_key fields).
- The public key is exposed to the frontend via GET /v1/push/vapid-public-key
  so the browser can create a PushSubscription tied to this server.
- When a push is needed, pywebpush sends a Web Push Protocol request directly
  to the browser vendor's push service (FCM for Chrome, Mozilla Push for Firefox, etc.).
- No third-party push provider is used — pure VAPID server-to-browser protocol.

See docs/architecture/notifications.md for the full notification flow.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Vault path where VAPID keys are stored
VAPID_VAULT_PATH = "kv/data/providers/vapid"

# VAPID contact email — identifies this server to push services.
# Use the VAPID_CONTACT env var (set in docker-compose); fall back to placeholder.
VAPID_CONTACT_EMAIL = os.getenv("VAPID_CONTACT_EMAIL", "admin@openmates.org")


class PushNotificationService:
    """
    Manages VAPID key lifecycle and dispatches Web Push notifications.

    Lifecycle:
      1. On API startup call initialize(secrets_manager) to load or generate VAPID keys.
      2. Use get_vapid_public_key() to serve the public key to the frontend.
      3. Use send_push_notification() to send a push to a stored subscription JSON.
    """

    def __init__(self) -> None:
        self._vapid_private_key: Optional[str] = None
        self._vapid_public_key: Optional[str] = None
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Startup initialisation
    # ------------------------------------------------------------------

    async def initialize(self, secrets_manager) -> None:
        """
        Load VAPID keys from Vault, or generate new ones if absent.
        Must be called once at API startup before handling requests.
        """
        if self._initialized:
            return

        try:
            secret = await secrets_manager.get_secrets_from_path(VAPID_VAULT_PATH)
            if secret and secret.get("public_key") and secret.get("private_key"):
                self._vapid_public_key = secret["public_key"]
                self._vapid_private_key = secret["private_key"]
                logger.info("[PushNotificationService] Loaded VAPID keys from Vault")
            else:
                logger.info("[PushNotificationService] No VAPID keys in Vault — generating new pair")
                await self._generate_and_store_keys(secrets_manager)
        except Exception as e:
            logger.error(
                f"[PushNotificationService] Failed to load/generate VAPID keys: {e}",
                exc_info=True,
            )
            # Non-fatal: push notifications will simply be skipped until the next restart
            return

        self._initialized = True

    async def _generate_and_store_keys(self, secrets_manager) -> None:
        """Generate a fresh VAPID EC key pair and persist to Vault."""
        try:
            import base64
            from py_vapid import Vapid  # type: ignore[import]
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PublicFormat,
            )

            vapid = Vapid()
            vapid.generate_keys()

            # pywebpush >=2.0 removed the convenience urlsafe_base64 properties.
            # Extract the raw EC public key as uncompressed point, and private
            # key as raw 32-byte scalar, then URL-safe base64-encode them.
            pub_bytes = vapid.public_key.public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )
            public_key_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

            priv_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
            private_key_b64 = base64.urlsafe_b64encode(priv_raw).decode().rstrip("=")

            await secrets_manager.store_secrets_at_path(
                VAPID_VAULT_PATH,
                {"public_key": public_key_b64, "private_key": private_key_b64},
            )

            self._vapid_public_key = public_key_b64
            self._vapid_private_key = private_key_b64
            logger.info("[PushNotificationService] Generated and stored new VAPID key pair")
        except Exception as e:
            logger.error(
                f"[PushNotificationService] VAPID key generation failed: {e}",
                exc_info=True,
            )
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_vapid_public_key(self) -> Optional[str]:
        """Return the VAPID public key (URL-safe base64) for the frontend."""
        return self._vapid_public_key

    def is_ready(self) -> bool:
        """True if VAPID keys are loaded and push can be sent."""
        return self._initialized and bool(self._vapid_private_key) and bool(self._vapid_public_key)

    def send_push_notification(
        self,
        subscription_json: str,
        title: str,
        body: str,
        url: Optional[str] = None,
        tag: Optional[str] = None,
        icon: str = "/icons/icon-192x192.png",
        badge: str = "/icons/badge-72x72.png",
    ) -> bool:
        """
        Send a Web Push notification to a stored subscription.

        This is a *synchronous* method — call it from a Celery task.

        Args:
            subscription_json: JSON string of the browser PushSubscription object
                               (endpoint, keys.p256dh, keys.auth).
            title: Notification title shown to the user.
            body: Notification body text.
            url: URL to open when the notification is clicked (defaults to '/').
            tag: Deduplication tag — if sent again with same tag, replaces the previous.
            icon: URL of the notification icon.
            badge: URL of the monochrome badge icon (Android).

        Returns:
            True if the push was accepted by the push service, False otherwise.
        """
        if not self.is_ready():
            logger.error("[PushNotificationService] Cannot send push — VAPID keys not initialized")
            return False

        try:
            subscription_info = json.loads(subscription_json)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"[PushNotificationService] Invalid subscription JSON: {e}")
            return False

        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "icon": icon,
                "badge": badge,
                "tag": tag or "openmates-notification",
                "url": url or "/",
            }
        )

        try:
            from pywebpush import webpush, WebPushException  # type: ignore[import]

            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=self._vapid_private_key,
                vapid_claims={
                    "sub": f"mailto:{VAPID_CONTACT_EMAIL}",
                },
            )
            logger.info(
                f"[PushNotificationService] Push sent to endpoint "
                f"{subscription_info.get('endpoint', '')[:60]}..."
            )
            return True

        except Exception as exc:  # WebPushException and others
            # 410 Gone means the subscription is expired/unregistered
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 410:
                logger.info(
                    f"[PushNotificationService] Subscription expired (410) — "
                    f"endpoint: {subscription_info.get('endpoint', '')[:60]}"
                )
            else:
                logger.error(
                    f"[PushNotificationService] Push delivery failed "
                    f"(status={status_code}): {exc}",
                    exc_info=True,
                )
            return False


# Singleton — imported by routes and tasks
push_notification_service = PushNotificationService()
