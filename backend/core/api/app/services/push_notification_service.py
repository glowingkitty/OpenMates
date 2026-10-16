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
import re
import os
import time
import base64
from typing import Callable, Optional

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


APNS_MAX_PAYLOAD_BYTES = 4096


def notification_preview_text(content: str, lang: str = "en") -> str:
    """Project response protocol to human text; only allowlisted fields survive.

    This projection is intentionally not character bounded. APNs dispatch bounds
    the complete encrypted wire payload, including UTF-8 and base64 overhead.
    """
    from backend.core.api.app.services.translations import TranslationService

    translations = TranslationService()
    skills = []
    seen = set()

    def label(key: str, fallback: str) -> str:
        value = translations.get_nested_translation(key, lang=lang)
        return value if value != key else fallback

    def human(value) -> str:
        if not isinstance(value, str):
            return ""
        # Do not allow nested protocol, markup or internal IDs as display fields.
        if re.search(r"[{}<>]|embed:|embed_id|app_skill_use|[0-9a-f]{8}-[0-9a-f-]{27,}", value, re.I):
            return ""
        return re.sub(r"\s+", " ", value).strip()

    def project(data) -> str:
        if not isinstance(data, dict):
            return ""
        kind = data.get("type")
        if not isinstance(kind, str):
            return ""
        if kind == "app_skill_use":
            app, skill = data.get("app_id"), data.get("skill_id")
            if not isinstance(app, str) or not isinstance(skill, str):
                return ""
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", app) or not re.fullmatch(r"[a-z][a-z0-9_-]*", skill):
                return ""
            identity = data.get("embed_id")
            if not isinstance(identity, str):
                identity = (app, skill, human(data.get("query")))
            if identity not in seen:
                seen.add(identity)
                app_label = label(f"apps.{app}", "App")
                skill_label = label(f"app_skills.{app}.{skill}", "Action")
                details = human(data.get("query")) or human(data.get("location"))
                skills.append(f"{app_label} | {skill_label}" + (f": '{details}'" if details else ""))
            return ""
        markers = {"image": "Image", "image_result": "Image", "video": "Video", "audio": "Audio",
                   "document": "Document", "pdf": "Document", "table": "Table", "code": "Code",
                   "mermaid": "Diagram", "mindmap": "Mind map", "math_plot": "Plot"}
        return f"[{markers.get(kind, 'Attachment')}]" if kind else ""

    def fence(match) -> str:
        block = match.group(0)
        # Unfinished fences and non-protocol code never become preview text.
        if not block.endswith(("```", "~~~")):
            return " "
        body = re.sub(r"^(?:```|~~~)[^\n]*\n", "", block)[:-3].strip()
        try:
            return project(json.loads(body))
        except (ValueError, TypeError):
            return " "

    text = re.sub(r"(?s)```.*?(?:```|$)|~~~.*?(?:~~~|$)", fence, content or "")
    # References may also be embedded as unfenced JSON. Decode complete
    # objects, including nested metadata, rather than leaking their tail fields.
    decoder = json.JSONDecoder()
    cursor = 0
    pieces = []
    while True:
        start = text.find('{', cursor)
        if start < 0:
            pieces.append(text[cursor:])
            break
        pieces.append(text[cursor:start])
        try:
            value, end = decoder.raw_decode(text[start:])
            pieces.append(project(value))
            cursor = start + end
        except ValueError:
            if re.match(r'\{\s*"', text[start:]):
                end = text.find('\n', start)
                cursor = len(text) if end < 0 else end
            else:
                pieces.append('{')
                cursor = start + 1
    text = ''.join(pieces)
    def inline(match):
        display = human(match.group(1))
        counted = re.fullmatch(r"(\d+)\s+(Images?|Videos?|Documents?|Files?|Attachments?|Results?)", display, re.I)
        return f"[{display}]" if counted else "[Attachment]"
    text = re.sub(r"!?\[([^\]]*)\]\(embed:[^)]+\)", inline, text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[Image]", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[embed:[^\]]+\]|embed:[^\s)]+", "[Attachment]", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)(\*|_)(.+?)\1(?!\w)", r"\2", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "", text, flags=re.I)
    def image_group(match):
        count = match.group(0).count("[Image]")
        return f"[{count} Images]" if count > 1 else "[Image]"
    text = re.sub(r"\[Image\](?:\s*\[Image\])+", image_group, text)
    # Reapplying projection at transport must preserve an already formatted
    # skill prefix and its deliberate blank line.
    ready = not skills and re.match(r"^[^\n]+ \| [^\n]+\n\n", text)
    if ready:
        first, rest = text.split("\n\n", 1)
        prose = first.strip() + "\n\n" + re.sub(r"\s+", " ", rest).strip()
    else:
        prose = re.sub(r"\s+", " ", text).strip()
    if not skills:
        return prose
    prefix = skills[0]
    if len(skills) > 1:
        prefix += f" & {len(skills) - 1} other app skill" + ("s" if len(skills) > 2 else "")
    return prefix + ("\n\n" + prose if prose else "")


def apns_topic_for_platform(platform: str) -> str:
    """Select the APNs topic on the server; client topic hints are never trusted."""
    if platform == "watchos":
        return "org.openmates.app.watch"
    if platform not in {"apns", "ios", "macos"}:
        raise ValueError("Unsupported native push platform")
    topic = os.getenv("APNS_BUNDLE_ID", "org.openmates.app")
    if topic != "org.openmates.app":
        raise ValueError("Unsupported APNs application topic")
    return topic


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

    def is_apns_ready(self) -> bool:
        """APNs delivery uses process credentials and does not require VAPID."""
        key_path = os.getenv("APNS_PRIVATE_KEY_PATH")
        return bool(
            os.getenv("APNS_TEAM_ID")
            and os.getenv("APNS_KEY_ID")
            and (os.getenv("APNS_PRIVATE_KEY") or (key_path and os.path.isfile(key_path)))
        )

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
        on_expired_web_target: Optional[Callable[[], None]] = None,
        workflow_routing: Optional[dict] = None,
        encrypted_title: Optional[str] = None,
        on_apns_result: Optional[Callable[[str], None]] = None,
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
        if subscription_type == "multi":
            return self._send_multi_target_notification(
                subscription_info=subscription_info,
                title=title,
                body=body,
                url=url,
                tag=tag,
                chat_id=chat_id,
                category=category,
                icon=icon,
                badge=badge,
                on_expired_web_target=on_expired_web_target,
                workflow_routing=workflow_routing,
                encrypted_title=encrypted_title,
                on_apns_result=on_apns_result,
            )
        if subscription_type == "apns":
            return self._send_apns_notification(
                subscription_info=subscription_info,
                title=title,
                body=body,
                chat_id=chat_id,
                category=category,
                tag=tag,
                workflow_routing=workflow_routing,
                encrypted_title=encrypted_title,
                on_apns_result=on_apns_result,
            )

        if not self.is_ready():
            logger.error("[PushNotificationService] Cannot send Web Push — VAPID keys not initialized")
            return False

        web_subscription_info = dict(subscription_info)
        web_subscription_info.pop("type", None)

        payload = json.dumps(
            {
                "title": title,
                "body": body[:200] if category == APNS_CHAT_CATEGORY else body,
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
                subscription_info=web_subscription_info,
                data=payload,
                vapid_private_key=self._vapid_private_key,
                vapid_claims={
                    "sub": f"mailto:{VAPID_CONTACT_EMAIL}",
                },
            )
            logger.info("[PushNotificationService] Web Push accepted")
            return True

        except Exception as exc:  # WebPushException and others
            # 410 Gone means the subscription is expired/unregistered
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 410:
                if on_expired_web_target is not None:
                    on_expired_web_target()
                logger.info("[PushNotificationService] Web Push subscription expired (410)")
            else:
                logger.error(
                    "[PushNotificationService] Web Push delivery failed "
                    "(status=%s, exception=%s)",
                    status_code,
                    type(exc).__name__,
                )
            return False

    def _send_multi_target_notification(
        self,
        subscription_info: dict,
        title: str,
        body: str,
        url: Optional[str],
        tag: Optional[str],
        chat_id: Optional[str],
        category: str,
        icon: str,
        badge: str,
        on_expired_web_target: Optional[Callable[[], None]],
        workflow_routing: Optional[dict] = None,
        encrypted_title: Optional[str] = None,
        on_apns_result: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Fan out one notification to all stored browser/APNs targets."""
        targets = subscription_info.get("targets")
        if not isinstance(targets, list):
            logger.error("[PushNotificationService] Multi-target subscription missing targets")
            return False

        any_success = False
        for target in targets:
            if not isinstance(target, dict):
                continue
            try:
                target_success = self.send_push_notification(
                    subscription_json=json.dumps(target),
                    title=title,
                    body=body,
                    url=url,
                    tag=tag,
                    chat_id=chat_id,
                    category=category,
                    icon=icon,
                    badge=badge,
                    on_expired_web_target=on_expired_web_target,
                    workflow_routing=workflow_routing,
                    encrypted_title=encrypted_title,
                    on_apns_result=on_apns_result,
                )
                any_success = any_success or target_success
            except Exception as exc:
                logger.error("[PushNotificationService] Multi-target dispatch failed: %s", exc, exc_info=True)
        return any_success

    def _send_apns_notification(
        self,
        subscription_info: dict,
        title: str,
        body: str,
        chat_id: Optional[str],
        category: str,
        tag: Optional[str],
        workflow_routing: Optional[dict] = None,
        encrypted_title: Optional[str] = None,
        on_apns_result: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Send an APNs alert notification to a native Apple device token.

        Required environment:
        - APNS_TEAM_ID
        - APNS_KEY_ID
        - APNS_PRIVATE_KEY or APNS_PRIVATE_KEY_PATH
        - APNS_BUNDLE_ID (defaults to org.openmates.app)
        - APNS_USE_SANDBOX=true as a fallback for legacy registrations without
          a stored per-device environment
        """
        token = (subscription_info.get("token") or "").strip()
        if not token:
            logger.error("[PushNotificationService] APNs subscription missing token")
            if on_apns_result:
                on_apns_result("permanent_reject")
            return False

        team_id = os.getenv("APNS_TEAM_ID")
        key_id = os.getenv("APNS_KEY_ID")
        platform = str(subscription_info.get("platform") or "apns").strip().lower()
        try:
            bundle_id = apns_topic_for_platform(platform)
        except ValueError:
            logger.error("[PushNotificationService] Unsupported APNs target topic")
            if on_apns_result:
                on_apns_result("permanent_reject")
            return False
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
            if on_apns_result:
                on_apns_result("retryable_reject")
            return False
        private_key = private_key.replace("\\n", "\n")

        environment = str(subscription_info.get("environment") or "").strip().lower()
        use_sandbox = (
            environment == "sandbox"
            if environment in {"sandbox", "production"}
            else os.getenv("APNS_USE_SANDBOX", "false").lower() == "true"
        )
        host = "api.sandbox.push.apple.com" if use_sandbox else "api.push.apple.com"
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
        if workflow_routing:
            payload.update({key: value for key, value in workflow_routing.items()
                            if key in {"workflow_id", "run_id", "notification_id", "chat_id", "message_id", "delivery_id"}
                            and isinstance(value, str) and value})
            payload["type"] = "workflow.run_completed"
        # Watch has no notification service extension; always retain generic text.
        if category == "OPENMATES_WORKFLOW_COMPLETED" and encrypted_title and platform != "watchos":
            encrypted_payload = self._build_encrypted_apns_payload(
                subscription_info, body, title=encrypted_title,
            )
        else:
            encrypted_payload = None if platform == "watchos" else self._build_encrypted_apns_payload(subscription_info, body)
        if (category == APNS_CHAT_CATEGORY or category == "OPENMATES_WORKFLOW_COMPLETED") and encrypted_payload:
            payload["aps"]["mutable-content"] = 1
            payload["encrypted_notification"] = encrypted_payload
            # Apple caps the entire UTF-8 JSON payload at 4096 bytes. Ciphertext
            # grows by the AES-GCM tag and base64; measure the real wire format.
            if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > APNS_MAX_PAYLOAD_BYTES:
                clean = notification_preview_text(body)
                low, high = 0, len(clean)
                best = None
                while low <= high:
                    middle = (low + high) // 2
                    candidate = self._build_encrypted_apns_payload(
                        subscription_info, clean[:middle] + ("…" if middle < len(clean) else ""),
                        title=encrypted_title if category == "OPENMATES_WORKFLOW_COMPLETED" else None,
                    )
                    payload["encrypted_notification"] = candidate
                    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                    if candidate and size <= APNS_MAX_PAYLOAD_BYTES:
                        best = candidate
                        low = middle + 1
                    else:
                        high = middle - 1
                if best is None:
                    payload.pop("encrypted_notification", None)
                    payload["aps"].pop("mutable-content", None)
                else:
                    payload["encrypted_notification"] = best
        if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > APNS_MAX_PAYLOAD_BYTES:
            logger.error("[PushNotificationService] APNs routing payload exceeds byte limit")
            if on_apns_result:
                on_apns_result("permanent_reject")
            return False

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
                if on_apns_result:
                    on_apns_result("accepted")
                return True

            logger.error(
                "[PushNotificationService] APNs delivery failed "
                f"status={response.status_code} body={response.text[:500]}"
            )
            if on_apns_result:
                on_apns_result("retryable_reject" if response.status_code == 429 or response.status_code >= 500 else "permanent_reject")
            return False
        except Exception as exc:
            logger.error(f"[PushNotificationService] APNs delivery failed: {exc}", exc_info=True)
            if on_apns_result:
                on_apns_result("uncertain")
            return False

    def _build_encrypted_apns_payload(self, subscription_info: dict, preview_text: str, *, title: str | None = None) -> Optional[dict]:
        """Encrypt optional Apple notification preview text to the device public key."""
        preview_text = notification_preview_text(preview_text)
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
                {"title": title[:200], "body": preview_text} if title else {"preview": preview_text},
                separators=(",", ":"), ensure_ascii=False,
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
