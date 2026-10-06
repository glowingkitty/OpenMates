"""Notify the affected account after a Team role change or removal.

Only routing ids and the event type enter Celery. The worker decrypts the
notification address and never receives a Team display name.
"""

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


@app.task(name="app.tasks.email_tasks.team_membership_change_email_task.send_team_membership_change_email", bind=True)
def send_team_membership_change_email(self, user_id: str, team_id: str, change: str) -> bool:
    if change not in {"role_changed", "removed"}:
        return False
    try:
        result = asyncio.run(_send_team_membership_change_email(user_id=user_id, team_id=team_id, change=change))
    except Exception as exc:
        logger.error("Team membership notification failed for user %s: %s", user_id[:8], exc, exc_info=True)
        raise self.retry(exc=exc, countdown=30, max_retries=3)
    if result is False:
        raise self.retry(exc=RuntimeError("Team membership notification delivery failed"), countdown=30, max_retries=3)
    return True


async def _send_team_membership_change_email(*, user_id: str, team_id: str, change: str) -> bool | None:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.python_utils.frontend_url import get_frontend_base_url

    if change not in {"role_changed", "removed"}:
        return False
    secrets_manager = SecretsManager()
    cache_service = CacheService()
    encryption_service = EncryptionService()
    await secrets_manager.initialize()
    await encryption_service.initialize()
    try:
        user = await cache_service.get_user_by_id(user_id)
        if not user or not user.get("vault_key_id") or not (user.get("encrypted_notification_email") or user.get("encrypted_email_address")):
            directus_service = DirectusService()
            await directus_service.initialize()
            try:
                success, user, _ = await directus_service.get_user_profile(user_id)
                if not success:
                    user = None
            finally:
                await directus_service.close()
        if not user or not user.get("vault_key_id"):
            return None
        encrypted_address = user.get("encrypted_notification_email") or user.get("encrypted_email_address")
        if not encrypted_address:
            return None
        recipient_email = await encryption_service.decrypt_with_user_key(encrypted_address, user["vault_key_id"])
        if not recipient_email:
            return None
        lang = str(user.get("language")) if user.get("language") in {"en", "de"} else "en"
        email_service = EmailTemplateService(secrets_manager=secrets_manager)
        subject_key = "email.team_role_changed_notification.subject" if change == "role_changed" else "email.team_removed_notification.subject"
        subject = email_service.translation_service.get_nested_translation(subject_key, lang, {})
        return await email_service.send_email(
            template="team-role-changed-notification" if change == "role_changed" else "team-removed-notification",
            recipient_email=recipient_email,
            context={"open_url": get_frontend_base_url(), "team_id": team_id},
            lang=lang,
            subject=subject,
        )
    finally:
        await cache_service.close()
        if hasattr(encryption_service, "close"):
            await encryption_service.close()
        await secrets_manager.aclose()
