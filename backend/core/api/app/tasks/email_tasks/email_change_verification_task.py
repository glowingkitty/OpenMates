"""
Email change verification task.

Generates the short-lived code used by Settings > Account > E-mail when a
signed-in user wants to move their login identity to a new address. The code is
scoped to the user id and target hashed email so signup verification codes and
email-change codes cannot be replayed across flows.
"""

import asyncio
import logging
import random

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())


@app.task(
    name="app.tasks.email_tasks.email_change_verification_task.generate_and_send_email_change_verification_email",
    bind=True,
)
def generate_and_send_email_change_verification_email(
    self,
    user_id: str,
    hashed_new_email: str,
    email: str,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    """Generate, cache, and send the new-email verification code."""
    try:
        return asyncio.run(
            _async_generate_and_send_email_change_verification_email(
                user_id=user_id,
                hashed_new_email=hashed_new_email,
                email=email,
                language=language,
                darkmode=darkmode,
            )
        )
    except Exception as exc:
        logger.error("Failed to run email change verification task: %s", exc, exc_info=True)
        return False


async def _async_generate_and_send_email_change_verification_email(
    user_id: str,
    hashed_new_email: str,
    email: str,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    secrets_manager = SecretsManager()
    cache_service = None

    try:
        cache_service = CacheService()
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

        verification_code = "".join(random.choices("0123456789", k=6))
        cache_key = f"email_change_code:{user_id}:{hashed_new_email}"
        cache_result = await cache_service.set(cache_key, verification_code, ttl=1200)
        if not cache_result:
            logger.error("Failed to store email change verification code")
            return False

        success = await email_template_service.send_email(
            template="confirm-email",
            recipient_email=email,
            context={"code": verification_code, "darkmode": darkmode},
            lang=language,
        )
        if not success:
            logger.error("Failed to send email change verification message")
            return False

        logger.info("Email change verification email sent")
        return True
    except Exception as exc:
        logger.error("Error in email change verification task: %s", exc, exc_info=True)
        return False
    finally:
        if cache_service:
            await cache_service.close()
        await secrets_manager.aclose()
