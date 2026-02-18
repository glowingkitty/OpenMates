# backend/core/api/app/tasks/email_tasks/usecase_submitted_email_task.py
"""
Celery task for sending use-case submission notification emails to the server admin.

This module handles sending a notification to the server admin whenever a user
anonymously submits a use-case summary via the 'share-usecase' skill during the
welcome/onboarding focus mode. No user identity is included — only the summary
text and language code are forwarded, preserving the anonymous nature of the
submission.
"""

import logging
import asyncio

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app

# Import necessary services and utilities
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(
    name='app.tasks.email_tasks.usecase_submitted_email_task.send_usecase_submitted_notification',
    bind=True,
)
def send_usecase_submitted_notification(
    self,
    admin_email: str,
    summary: str,
    language: str,
) -> bool:
    """
    Celery task to notify the server admin of a new anonymous use-case submission.

    This task is dispatched by ShareUsecaseSkill after a use-case summary has been
    successfully stored in the 'onboarding_usecases' Directus collection.

    PRIVACY: No user identifier is passed or included in the email. The submission
    is intentionally anonymous — only the summary text and language code are sent.

    Args:
        admin_email: Email address of the server admin (from SERVER_OWNER_EMAIL env var).
        summary: Anonymous use-case summary text (2-5 sentences from the user).
        language: ISO 639-1 language code of the conversation.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    logger.info(
        f"Starting use-case submission notification email task "
        f"(language={language}, summary_length={len(summary)}, recipient={admin_email})"
    )
    try:
        result = asyncio.run(
            _async_send_usecase_submitted_notification(admin_email, summary, language)
        )
        if result:
            logger.info(
                f"Use-case submission notification email task completed successfully "
                f"(recipient={admin_email})"
            )
        else:
            logger.error(
                f"Use-case submission notification email task failed "
                f"(recipient={admin_email}) — check logs above for details"
            )
        return result
    except Exception as e:
        logger.error(
            f"Failed to run use-case submission notification email task: {str(e)} "
            f"(recipient={admin_email})",
            exc_info=True,
        )
        return False


async def _async_send_usecase_submitted_notification(
    admin_email: str,
    summary: str,
    language: str,
) -> bool:
    """
    Async implementation for sending the use-case submission notification email.

    Uses try/finally to ensure SecretsManager's httpx client is properly closed
    before asyncio.run() closes the event loop in Celery tasks, preventing
    "Event loop is closed" errors during httpx cleanup.

    PRIVACY: Only summary and language are included. No user identity is passed.
    """
    secrets_manager = SecretsManager()

    try:
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

        # SECURITY: HTML-escape the summary to prevent XSS in the email template.
        # The summary comes from user-controlled LLM output and must be sanitized.
        from html import escape

        sanitized_summary = escape(summary) if summary else ""
        # Convert newlines to <br/> for readable display in the email body
        sanitized_summary = sanitized_summary.replace('\n', '<br/>')

        email_context = {
            "darkmode": True,   # Admin emails use dark mode by default
            "summary": sanitized_summary,
            "language": language,
        }

        logger.info(
            f"Attempting to send use-case submission notification email to {admin_email} "
            f"with template 'usecase_submitted' (language={language})"
        )

        email_success = await email_template_service.send_email(
            template="usecase_submitted",
            recipient_email=admin_email,
            context=email_context,
            lang="en",  # Admin emails are always in English
        )

        if not email_success:
            logger.error(
                f"Failed to send use-case submission notification email to {admin_email} — "
                f"send_email() returned False. Check email service configuration and logs."
            )
            return False

        logger.info(
            f"Successfully sent use-case submission notification email to {admin_email}"
        )
        event_logger.info(
            f"Use-case submission notification email sent to {admin_email} (language={language})"
        )
        return True

    except Exception as e:
        logger.error(
            f"Error sending use-case submission notification email: {str(e)}",
            exc_info=True,
        )
        return False
    finally:
        # CRITICAL: Close the httpx client before asyncio.run() closes the event loop.
        # Skipping this causes "Event loop is closed" errors during httpx cleanup.
        await secrets_manager.aclose()
