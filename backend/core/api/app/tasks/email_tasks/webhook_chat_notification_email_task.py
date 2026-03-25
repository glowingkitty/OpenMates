# backend/core/api/app/tasks/email_tasks/webhook_chat_notification_email_task.py
"""
Celery task for sending email notifications when a webhook creates a new chat
while the user is offline (no active WebSocket connections).

Architecture:
- The webhook router (webhooks.py) checks if user is online via
  ConnectionManager.is_user_active() — if offline, this task is queued.
- Respects email_notifications_enabled + webhookChats preference.
- Decrypts notification email via vault (same pattern as
  ai_response_notification_email_task.py).

Related: ai_response_notification_email_task.py (same structure)
"""

import asyncio
import logging
import os
from typing import Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(
    name="app.tasks.email_tasks.webhook_chat_notification_email_task.send_webhook_chat_notification",
    bind=True,
)
def send_webhook_chat_notification(
    self,
    user_id: str,
    chat_id: str,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    """
    Celery task to send webhook chat notification email.

    Unlike ai_response_notification where the decrypted email is passed in,
    this task re-reads user data from cache/Directus and decrypts the
    notification email itself (safer — no plaintext email in Celery args).

    Args:
        user_id: User UUID (for looking up notification email)
        chat_id: The chat ID to link in the email
        language: User's preferred language code
        darkmode: User's dark mode preference

    Returns:
        True if email sent successfully, False otherwise
    """
    logger.info(
        f"[WEBHOOK_EMAIL] Sending webhook chat notification "
        f"(user_id={user_id[:8]}..., chat_id={chat_id})"
    )
    try:
        result = asyncio.run(
            _async_send_webhook_chat_notification(
                user_id=user_id,
                chat_id=chat_id,
                language=language,
                darkmode=darkmode,
            )
        )
        if result:
            logger.info(f"[WEBHOOK_EMAIL] Notification sent (user_id={user_id[:8]}...)")
        else:
            logger.error(f"[WEBHOOK_EMAIL] Notification failed (user_id={user_id[:8]}...)")
        return result
    except Exception as e:
        logger.error(f"[WEBHOOK_EMAIL] Task error: {e}", exc_info=True)
        return False


async def _async_send_webhook_chat_notification(
    user_id: str,
    chat_id: str,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    """
    Async implementation. Fetches user data, decrypts notification email,
    and sends via EmailTemplateService.
    """
    secrets_manager = SecretsManager()

    try:
        await secrets_manager.initialize()

        # --- Get user's notification email ---
        # Import here to avoid circular imports at module level
        from backend.core.api.app.utils.encryption import EncryptionService
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.services.directus import DirectusService

        encryption_service = EncryptionService()
        await encryption_service.initialize()

        cache_service = CacheService()
        await cache_service.initialize()

        # Try cache first, Directus fallback
        cached_user = await cache_service.get_user_by_id(user_id)
        encrypted_email = None
        vault_key_id = None

        if cached_user:
            encrypted_email = cached_user.get("encrypted_notification_email")
            vault_key_id = cached_user.get("vault_key_id")
        else:
            directus_service = DirectusService()
            await directus_service.initialize()
            try:
                success, profile, _ = await directus_service.get_user_profile(user_id)
                if success and profile:
                    encrypted_email = profile.get("encrypted_notification_email")
                    vault_key_id = profile.get("vault_key_id")
            finally:
                await directus_service.close()

        if not encrypted_email or not vault_key_id:
            logger.debug(f"[WEBHOOK_EMAIL] No notification email for user {user_id[:8]}...")
            return False

        # Decrypt email
        recipient_email = await encryption_service.decrypt_with_user_key(
            encrypted_email, vault_key_id
        )
        if not recipient_email:
            logger.warning(f"[WEBHOOK_EMAIL] Email decryption failed for user {user_id[:8]}...")
            return False

        # --- Build email ---
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

        base_url = os.getenv("FRONTEND_URL", "https://openmates.org")
        chat_url = f"{base_url}/chat/{chat_id}"

        email_context = {
            "darkmode": darkmode,
            "chat_url": chat_url,
        }

        email_success = await email_template_service.send_email(
            template="webhook-chat-notification",
            recipient_email=recipient_email,
            context=email_context,
            lang=language,
        )

        if not email_success:
            logger.error(f"[WEBHOOK_EMAIL] send_email returned False for user {user_id[:8]}...")
            return False

        return True

    except Exception as e:
        logger.error(f"[WEBHOOK_EMAIL] Error: {e}", exc_info=True)
        return False
    finally:
        await secrets_manager.aclose()
