# backend/core/api/app/tasks/email_tasks/team_member_mention_email_task.py
"""Send content-free Team member mention email notifications.

The worker resolves the recipient's encrypted notification address server-side;
Celery arguments contain only routing identifiers. No Team message content,
sender text, or decrypted Team metadata enters the task or template context.
"""

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


@app.task(name="app.tasks.email_tasks.team_member_mention_email_task.send_team_member_mention_email", bind=True)
def send_team_member_mention_email(self, user_id: str, team_id: str, chat_id: str) -> bool:
    try:
        result = asyncio.run(_send_team_member_mention_email(user_id=user_id, team_id=team_id, chat_id=chat_id))
    except Exception as exc:
        logger.error("Team member mention email failed for user %s: %s", user_id[:8], exc, exc_info=True)
        raise self.retry(exc=exc, countdown=30, max_retries=3)
    if result is False:
        raise self.retry(exc=RuntimeError("Team member mention email delivery failed"), countdown=30, max_retries=3)
    return True


async def _send_team_member_mention_email(*, user_id: str, team_id: str, chat_id: str) -> bool | None:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.python_utils.frontend_url import get_frontend_base_url

    secrets_manager = SecretsManager()
    cache_service = CacheService()
    encryption_service = EncryptionService()
    await secrets_manager.initialize()
    await cache_service.initialize()
    await encryption_service.initialize()
    try:
        user = await cache_service.get_user_by_id(user_id)
        if not user:
            directus_service = DirectusService()
            await directus_service.initialize()
            try:
                success, user, _ = await directus_service.get_user_profile(user_id)
                if not success:
                    user = None
            finally:
                await directus_service.close()
        if not user or not user.get("encrypted_notification_email") or not user.get("vault_key_id"):
            return None
        recipient_email = await encryption_service.decrypt_with_user_key(
            user["encrypted_notification_email"], user["vault_key_id"]
        )
        if not recipient_email:
            return None
        return await EmailTemplateService(secrets_manager=secrets_manager).send_email(
            template="team-member-mention-notification",
            recipient_email=recipient_email,
            context={"chat_url": f"{get_frontend_base_url()}/chat/{chat_id}", "team_id": team_id},
            lang=str(user.get("language") or "en"),
        )
    finally:
        await cache_service.close()
        if hasattr(encryption_service, "close"):
            await encryption_service.close()
        await secrets_manager.aclose()
