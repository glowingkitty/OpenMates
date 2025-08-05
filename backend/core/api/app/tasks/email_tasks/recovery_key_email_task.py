"""
Recovery Key Email Task

This module handles sending email notifications when a recovery key is used for login.
Recovery keys are standalone login credentials designed for emergency access when other
login methods are unavailable.
"""

import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app

# Import necessary services and utilities
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
# Import the email context helpers
from backend.core.api.app.utils.email_context_helpers import generate_report_access_mailto_link

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.recovery_key_email_task.send_recovery_key_used_email', bind=True)
def send_recovery_key_used_email(
    self,
    email_address: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Celery task wrapper to send a 'recovery key used' notification email.
    
    Args:
        email_address: The recipient's email address
        language: User's preferred language (default: "en")
        darkmode: User's darkmode preference (default: False)
        
    Returns:
        bool: True if email was sent successfully, False otherwise
        
    Note:
        For security reasons, we don't include any details about the recovery key itself.
        The email only notifies that a recovery key was used to access the account.
    """
    logger.info(f"Starting recovery key used email task for email: {email_address[:2]}***")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_async_send_recovery_key_used_email(
            email_address=email_address,
            language=language,
            darkmode=darkmode
        ))
        logger.info(f"Recovery key used email task completed for email: {email_address[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run recovery key used email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False
    finally:
        loop.close()

async def _async_send_recovery_key_used_email(
    email_address: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending the recovery key used email.
    
    Args:
        email_address: The recipient's email address
        language: User's preferred language
        darkmode: User's darkmode preference
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        translation_service = email_template_service.translation_service

        # --- Prepare Mailto Link using Helper ---
        login_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')

        report_details = {
            "login_time": login_time_str
            # No recovery key details included for security
        }

        logout_link = await generate_report_access_mailto_link(
            translation_service=translation_service,
            language=language,
            account_email=email_address,
            report_type='recovery_key',  # Specify the report type
            details=report_details
        )

        if not logout_link:
            logger.error(f"Failed to generate mailto link for recovery key used email for {email_address[:2]}...")
            # Allow it to continue but log the error prominently
            logout_link = ""  # Set to empty string to avoid template errors

        # --- Prepare Template Context ---
        # Context only needs darkmode and the generated mailto link
        context = {
            "darkmode": darkmode,
            "logout_link": logout_link  # The generated mailto link
        }
        logger.debug(f"Prepared template context for recovery key used email: {context}")

        # --- Send Email ---
        logger.info(f"Sending recovery key used email to {email_address[:2]}*** - lang: {language}")

        success = await email_template_service.send_email(
            template="recovery-key-was-used",  # Use the correct template name
            recipient_email=email_address,
            context=context,
            lang=language
        )

        if not success:
            logger.error(f"Failed to send recovery key used email for email {email_address[:2]}...")
            return False

        logger.info(f"Recovery key used email sent successfully for email {email_address[:2]}...")
        return True

    except Exception as e:
        logger.error(f"Error in _async_send_recovery_key_used_email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False