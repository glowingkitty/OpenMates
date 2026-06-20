"""
Existing Account Signup Email Task

Sends a transactional notice when someone starts signup with an email address
that already belongs to an OpenMates account. The API response remains generic
for anti-enumeration; only the mailbox owner receives account-specific guidance.
"""

import asyncio
import logging

from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.frontend_url import get_frontend_base_url

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)

SUPPORTED_TRANSLATED_LANGUAGES = {"en", "de"}


@app.task(name="app.tasks.email_tasks.existing_account_email_task.send_existing_account_email", bind=True)
def send_existing_account_email(
    self,
    email: str,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    """Send login guidance to a mailbox that already has an account."""
    logger.info("Starting existing-account signup email task for %s***", email[:2])
    try:
        return asyncio.run(
            _async_send_existing_account_email(
                email=email,
                language=language,
                darkmode=darkmode,
            )
        )
    except Exception as exc:
        logger.error(
            "Failed to run existing-account signup email task for %s***: %s",
            email[:2],
            exc,
            exc_info=True,
        )
        return False


async def _async_send_existing_account_email(
    email: str,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    """Async implementation for sending the existing-account signup notice."""
    secrets_manager = SecretsManager()

    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        frontend_base_url = get_frontend_base_url()
        template_language = language if language in SUPPORTED_TRANSLATED_LANGUAGES else "en"

        context = {
            "darkmode": darkmode,
            "login_url": frontend_base_url,
            "account_recovery_url": frontend_base_url,
        }

        logger.info("Sending existing-account signup email to %s*** - lang: %s", email[:2], template_language)
        success = await email_template_service.send_email(
            template="existing-account",
            recipient_email=email,
            context=context,
            lang=template_language,
        )

        if not success:
            logger.error("Failed to send existing-account signup email to %s***", email[:2])
            return False

        logger.info("Existing-account signup email sent successfully to %s***", email[:2])
        return True
    except Exception as exc:
        logger.error(
            "Error in _async_send_existing_account_email task for %s***: %s",
            email[:2],
            exc,
            exc_info=True,
        )
        return False
    finally:
        await secrets_manager.aclose()
