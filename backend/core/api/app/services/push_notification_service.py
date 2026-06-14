# backend/core/api/app/services/push_notification_service.py
"""
Push Notification Service — VAPID Web Push and Apple APNs delivery.

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
import time
import base64
from typing import Optional

logger = logging.getLogger(__name__)

# Vault path where VAPID keys are stored
VAPID_VAULT_PATH = "kv/data/providers/vapid"

# VAPID contact email — identifies this server to push services.
# Use the VAPID_CONTACT env var (set in docker-compose); fall back to placeholder.
VAPID_CONTACT_EMAIL = os.getenv("VAPID_CONTACT_EMAIL", "admin@openmates.org")

APNS_CHAT_CATEGORY = "OPENMATES_CHAT_MESSAGE"
APNS_TIMEOUT_SECONDS = 10.0
APNS_CHAT_MESSAGE_TITLE = "OpenMates"
APNS_CHAT_MESSAGE_BODY = "New message received"
APNS_ENCRYPTION_VERSION = "x25519-aesgcm-v1"
APNS_ENCRYPTION_INFO = b"openmates-apns-notification-v1"


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
        chat_id: Optional[str] = None,
        category: str = APNS_CHAT_CATEGORY,
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
        try:
            subscription_info = json.loads(subscription_json)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"[PushNotificationService] Invalid subscription JSON: {e}")
            return False

        subscription_type = subscription_info.get("type")
        if subscription_type == "apns":
            return self._send_apns_notification(
                subscription_info=subscription_info,
                title=title,
                body=body,
                chat_id=chat_id,
                category=category,
                tag=tag,
            )

        if not self.is_ready():
            logger.error("[PushNotificationService] Cannot send Web Push — VAPID keys not initialized")
            return False

        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "icon": icon,
                "badge": badge,
                "tag": tag or "openmates-notification",
                "url": url or "/",
                "chat_id": chat_id,
                "category": category,
            }
        )

        try:
            from pywebpush import webpush  # type: ignore[import]

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

    def _send_apns_notification(
        self,
        subscription_info: dict,
        title: str,
        body: str,
        chat_id: Optional[str],
        category: str,
        tag: Optional[str],
    ) -> bool:
        """
        Send an APNs alert notification to a native Apple device token.

        Required environment:
        - APNS_TEAM_ID
        - APNS_KEY_ID
        - APNS_PRIVATE_KEY or APNS_PRIVATE_KEY_PATH
        - APNS_BUNDLE_ID (defaults to org.openmates.app)
        - APNS_USE_SANDBOX=true for development APNs
        """
        token = (subscription_info.get("token") or "").strip()
        if not token:
            logger.error("[PushNotificationService] APNs subscription missing token")
            return False

        team_id = os.getenv("APNS_TEAM_ID")
        key_id = os.getenv("APNS_KEY_ID")
        bundle_id = os.getenv("APNS_BUNDLE_ID", "org.openmates.app")
        private_key = os.getenv("APNS_PRIVATE_KEY")
        private_key_path = os.getenv("APNS_PRIVATE_KEY_PATH")

        if not private_key and private_key_path:
            try:
                with open(private_key_path, "r", encoding="utf-8") as key_file:
                    private_key = key_file.read()
            except OSError as exc:
                logger.error(f"[PushNotificationService] Could not read APNs key file: {exc}")
                return False

        if not team_id or not key_id or not private_key:
            logger.error("[PushNotificationService] APNs credentials are not configured")
            return False
        private_key = private_key.replace("\\n", "\n")

        host = "api.sandbox.push.apple.com" if os.getenv("APNS_USE_SANDBOX", "false").lower() == "true" else "api.push.apple.com"
        alert_title = APNS_CHAT_MESSAGE_TITLE if category == APNS_CHAT_CATEGORY else title
        alert_body = APNS_CHAT_MESSAGE_BODY if category == APNS_CHAT_CATEGORY else body
        payload = {
            "aps": {
                "alert": {"title": alert_title, "body": alert_body},
                "sound": "default",
                "category": category,
                "thread-id": chat_id or tag or "openmates-chat",
            },
            "chat_id": chat_id,
            "category": category,
        }
        encrypted_payload = self._build_encrypted_apns_payload(subscription_info, body)
        if category == APNS_CHAT_CATEGORY and encrypted_payload:
            payload["aps"]["mutable-content"] = 1
            payload["encrypted_notification"] = encrypted_payload

        try:
            import httpx

            jwt_token = self._build_apns_jwt(team_id=team_id, key_id=key_id, private_key_pem=private_key)
            headers = {
                "authorization": f"bearer {jwt_token}",
                "apns-topic": bundle_id,
                "apns-push-type": "alert",
                "apns-priority": "10",
            }
            if tag:
                headers["apns-collapse-id"] = tag[:64]

            with httpx.Client(http2=True, timeout=APNS_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"https://{host}/3/device/{token}",
                    json=payload,
                    headers=headers,
                )
            if 200 <= response.status_code < 300:
                logger.info("[PushNotificationService] APNs notification accepted")
                return True

            logger.error(
                "[PushNotificationService] APNs delivery failed "
                f"status={response.status_code} body={response.text[:500]}"
            )
            return False
        except Exception as exc:
            logger.error(f"[PushNotificationService] APNs delivery failed: {exc}", exc_info=True)
            return False

    def _build_encrypted_apns_payload(self, subscription_info: dict, preview_text: str) -> Optional[dict]:
        """Encrypt optional Apple notification preview text to the device public key."""
        public_key_b64 = (subscription_info.get("notification_public_key") or "").strip()
        encryption_version = (subscription_info.get("encryption_version") or APNS_ENCRYPTION_VERSION).strip()
        if not public_key_b64 or encryption_version != APNS_ENCRYPTION_VERSION or not preview_text:
            return None

        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import x25519
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF

            device_public_key = x25519.X25519PublicKey.from_public_bytes(
                _decode_base64url(public_key_b64)
            )
            ephemeral_private_key = x25519.X25519PrivateKey.generate()
            shared_secret = ephemeral_private_key.exchange(device_public_key)
            key = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=APNS_ENCRYPTION_INFO,
            ).derive(shared_secret)
            nonce = os.urandom(12)
            plaintext = json.dumps(
                {"preview": preview_text},
                separators=(",", ":"),
            ).encode("utf-8")
            ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
            ephemeral_public_key = ephemeral_private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            return {
                "version": APNS_ENCRYPTION_VERSION,
                "ephemeral_public_key": _encode_base64url(ephemeral_public_key),
                "nonce": _encode_base64url(nonce),
                "ciphertext": _encode_base64url(ciphertext),
            }
        except Exception as exc:
            logger.warning("[PushNotificationService] Could not encrypt APNs notification preview: %s", exc)
            return None

    def _build_apns_jwt(self, team_id: str, key_id: str, private_key_pem: str) -> str:
        """Build the ES256 provider token APNs expects without adding a PyJWT dependency."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

        header = {"alg": "ES256", "kid": key_id}
        claims = {"iss": team_id, "iat": int(time.time())}
        signing_input = (
            f"{b64url(json.dumps(header, separators=(',', ':')).encode())}."
            f"{b64url(json.dumps(claims, separators=(',', ':')).encode())}"
        ).encode("ascii")

        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        if not isinstance(private_key, ec.EllipticCurvePrivateKey):
            raise ValueError("APNs private key must be an EC private key")
        der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der_signature)
        raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"{signing_input.decode('ascii')}.{b64url(raw_signature)}"


# Singleton — imported by routes and tasks
push_notification_service = PushNotificationService()


def _encode_base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode_base64url(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
