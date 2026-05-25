# backend/core/api/app/tasks/email_tasks/referral_reward_email_task.py
"""
Send referral reward notification emails.

The payment webhook queues this task only after a referral reward is durably
recorded and both promotional credit balances were updated. The email contains
no referred-user identity; it only tells the referrer that their code produced a
successful reward.
"""

import asyncio
import logging
from html import escape

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())


@app.task(name="app.tasks.email_tasks.referral_reward_email_task.send_referral_reward_email", bind=True)
def send_referral_reward_email(
    self,
    recipient_email: str,
    credits_awarded: int,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    """Send a referral reward email to the original referrer."""
    try:
        return asyncio.run(
            _async_send_referral_reward_email(
                recipient_email=recipient_email,
                credits_awarded=credits_awarded,
                language=language,
                darkmode=darkmode,
            )
        )
    except Exception as exc:
        logger.error("Failed to run referral reward email task: %s", exc, exc_info=True)
        return False


async def _async_send_referral_reward_email(
    recipient_email: str,
    credits_awarded: int,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        context = {
            "darkmode": darkmode,
            "credits_awarded": escape(str(credits_awarded)),
        }
        return await email_template_service.send_email(
            template="referral-reward",
            recipient_email=recipient_email,
            context=context,
            lang=language,
        )
    finally:
        await secrets_manager.aclose()
