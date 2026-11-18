"""
Emails of the safety review: suspension notice and admin question.

The recipient is the server-decryptable account contact email. The mails carry
the category-level reason only, never request or image detail.
"""

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

SUSPENSION_TEMPLATE = "safety-account-suspended"
MORE_INFO_TEMPLATE = "safety-more-information"


@app.task(
    name="app.tasks.email_tasks.safety_review_email_task.send_safety_suspension_email",
    bind=True,
)
def send_safety_suspension_email(self, user_id: str, state: str, until: str | None) -> bool:
    """Tell the user about the suspension: reason, end date or review note, appeal link."""
    return asyncio.run(_send(user_id, SUSPENSION_TEMPLATE, {"state": state, "until": until}))


@app.task(
    name="app.tasks.email_tasks.safety_review_email_task.send_safety_more_information_email",
    bind=True,
)
def send_safety_more_information_email(self, user_id: str, question: str) -> bool:
    """Send the admin's question for more information."""
    return asyncio.run(_send(user_id, MORE_INFO_TEMPLATE, {"question": question}))


def appeal_url(webapp_base_url: str) -> str:
    """Link to the app, where the suspended-account screen offers the appeal."""
    return f"{webapp_base_url.rstrip('/')}/#login"


async def _send(user_id: str, template: str, extra: dict) -> bool:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.tasks.email_tasks.newsletter_email_task import _resolve_webapp_base_url
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.issue_report_contact_email import resolve_account_contact_email
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.python_utils.image_safety.account_suspension import STATE_PENDING_REVIEW, _translate

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    cache_service = CacheService()
    directus_service = DirectusService()
    try:
        encryption_service = EncryptionService(secrets_manager)
        email = await resolve_account_contact_email(directus_service, encryption_service, user_id)
        if not email:
            logger.error(f"[SafetyStrikes] No contact email for user {user_id[:8]}; {template} email not sent")
            return False
        user = await cache_service.get_user_by_id(user_id) or {}
        language = user.get("language") or "en"
        context = {"darkmode": bool(user.get("darkmode", False)), "appeal_url": appeal_url(_resolve_webapp_base_url()), **extra}
        if template == SUSPENSION_TEMPLATE:
            category = user.get("safety_suspension_category") or "unknown"
            context["category"] = category
            if extra["state"] == STATE_PENDING_REVIEW:
                context["detail"] = _translate("suspended_pending_review", language)
            else:
                context["detail"] = _translate("suspended_until", language).replace("{date}", (extra["until"] or "")[:10])
        service = EmailTemplateService(secrets_manager)
        return await service.send_email(template=template, recipient_email=email, context=context, lang=language)
    finally:
        await cache_service.close()
        await directus_service.close()
