"""
Purpose: Sends the delayed post-purchase security setup reminder.
Architecture: Runs after a successful credit purchase so signup can stay short while
  still nudging users to create a recovery key and, for password accounts, OTP 2FA.
Architecture: See docs/architecture/app-skills.md for async task execution rationale.
Tests: Covered by signup purchase E2E specs and email delivery assertions.
"""

import asyncio
import hashlib
import logging

from backend.core.api.app.services.email_delivery_guard import send_email_once
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger(__name__)

RECOVERY_KEY_SETTINGS_PATH = "account/security/recovery-key"
TWOFA_SETTINGS_PATH = "account/security/2fa"


@app.task(
    name="app.tasks.email_tasks.post_purchase_security_setup_email_task.send_post_purchase_security_setup_reminder",
    base=BaseServiceTask,
    bind=True,
)
def send_post_purchase_security_setup_reminder(self, user_id: str, order_id: str) -> dict:
    """Send a post-credit-purchase reminder if security setup is incomplete."""
    return asyncio.run(_async_send_post_purchase_security_setup_reminder(self, user_id, order_id))


def _settings_url(path: str) -> str:
    return f"{get_frontend_base_url()}/#settings/{path}"


async def _async_send_post_purchase_security_setup_reminder(
    task: BaseServiceTask,
    user_id: str,
    order_id: str,
) -> dict:
    stats = {
        "user_id": user_id,
        "order_id": order_id,
        "sent_email": False,
        "sent_notification": False,
        "skipped": None,
    }

    try:
        await task.initialize_services()

        user_fields = await task.directus_service.get_user_fields_direct(
            user_id,
            [
                "encrypted_email_address",
                "encrypted_tfa_secret",
                "language",
                "darkmode",
                "vault_key_id",
            ],
        )
        if not user_fields:
            stats["skipped"] = "missing_user"
            return stats

        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        has_password = await task.directus_service.get_encryption_key(hashed_user_id, "password") is not None
        has_recovery_key = await task.directus_service.get_encryption_key(hashed_user_id, "recovery_key") is not None
        has_2fa = bool(user_fields.get("encrypted_tfa_secret"))

        needs_recovery_key = not has_recovery_key
        needs_2fa = has_password and not has_2fa
        if not needs_recovery_key and not needs_2fa:
            stats["skipped"] = "security_complete"
            return stats

        action_path = RECOVERY_KEY_SETTINGS_PATH if needs_recovery_key else TWOFA_SETTINGS_PATH
        action_label = "Set up recovery key" if needs_recovery_key else "Set up 2FA"
        message = (
            "Secure your OpenMates account: set up a recovery key so you do not lose access."
            if not needs_2fa
            else "Secure your OpenMates account: set up a recovery key, and add OTP 2FA plus backup codes for password login."
        )

        await task.cache_service.publish_event(
            channel=f"user_updates::{user_id}",
            event_data={
                "event_for_client": "user_notification",
                "user_id_uuid": user_id,
                "payload": {
                    "notification_type": "warning",
                    "message": message,
                    "action_label": action_label,
                    "action_deep_link": action_path,
                    "duration": 0,
                    "dedupe_key": f"post_purchase_security_setup:{order_id}",
                },
            },
        )
        stats["sent_notification"] = True

        encrypted_email = user_fields.get("encrypted_email_address")
        vault_key_id = user_fields.get("vault_key_id")
        if not encrypted_email or not vault_key_id:
            stats["skipped"] = "missing_email"
            return stats

        recipient_email = await task.encryption_service.decrypt_with_user_key(encrypted_email, vault_key_id)
        if not recipient_email:
            stats["skipped"] = "email_decrypt_failed"
            return stats

        context = {
            "darkmode": bool(user_fields.get("darkmode", False)),
            "needs_recovery_key": needs_recovery_key,
            "needs_2fa": needs_2fa,
            "recovery_key_settings_url": _settings_url(RECOVERY_KEY_SETTINGS_PATH),
            "twofa_settings_url": _settings_url(TWOFA_SETTINGS_PATH),
        }
        sent, delivery_status = await send_email_once(
            directus=task.directus_service,
            email_template_service=task.email_template_service,
            email_type="post_purchase_security_setup",
            campaign_key="post_purchase_security_setup_v1",
            recipient_kind="directus_user",
            recipient_id=user_id,
            stage=f"order-{order_id}",
            template="post-purchase-security-setup",
            recipient_email=recipient_email,
            context=context,
            lang=user_fields.get("language") or "en",
        )
        stats["sent_email"] = sent
        if not sent:
            stats["skipped"] = delivery_status

        return stats
    except Exception as exc:
        logger.error("Post-purchase security setup reminder failed: %s", exc, exc_info=True)
        stats["skipped"] = "error"
        return stats
    finally:
        await task.cleanup_services()
