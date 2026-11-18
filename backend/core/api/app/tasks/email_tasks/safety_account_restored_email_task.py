"""
Apology email after an admin restores a safety-suspended account.

The recipient is the server-decryptable account contact email. The mail carries
no category, request or image detail: it says the suspension was lifted, the
strikes were cleared and apologises for the interruption.
"""

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

TEMPLATE = "safety-account-restored"

@app.task(
    name="app.tasks.email_tasks.safety_account_restored_email_task.send_safety_account_restored_email",
    bind=True,
)
def send_safety_account_restored_email(self, user_id: str) -> bool:
    """Send the apology email for a restored account."""
    return asyncio.run(_send(user_id))

async def _send(user_id: str) -> bool:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.issue_report_contact_email import resolve_account_contact_email
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    cache_service = CacheService()
    directus_service = DirectusService()
    try:
        encryption_service = EncryptionService(secrets_manager)
        email = await resolve_account_contact_email(directus_service, encryption_service, user_id)
        if not email:
            logger.error(f"[SafetyStrikes] No contact email for user {user_id[:8]}; apology email not sent")
            return False
        user = await cache_service.get_user_by_id(user_id) or {}
        language = user.get("language") or "en"
        service = EmailTemplateService(secrets_manager)
        return await service.send_email(
            template=TEMPLATE,
            recipient_email=email,
            context={"darkmode": bool(user.get("darkmode", False))},
            lang=language,
        )
    finally:
        await cache_service.close()
        await directus_service.close()
