import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone # Needed for mailto link generation

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


@app.task(name='app.tasks.email_tasks.backup_code_email_task.send_backup_code_used_email', bind=True)
def send_backup_code_used_email(
    self,
    email_address: str,
    anonymized_code: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Celery task wrapper to send a 'backup code used' notification email.
    """
    logger.info(f"Starting backup code used email task for email: {email_address[:2]}***")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_async_send_backup_code_used_email(
            email_address=email_address,
            anonymized_code=anonymized_code,
            language=language,
            darkmode=darkmode
        ))
        logger.info(f"Backup code used email task completed for email: {email_address[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run backup code used email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False
    finally:
        loop.close()

async def _async_send_backup_code_used_email(
    email_address: str,
    anonymized_code: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending the backup code used email.
    """
    try:
        secrets_manager = SecretsManager() # Instantiate SecretsManager
        await secrets_manager.initialize() # Initialize SecretsManager
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager) # Pass SecretsManager
        translation_service = email_template_service.translation_service # Get translation service instance

        # --- Prepare Mailto Link using Helper ---
        login_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z') # e.g., 2025-04-02 13:10:00 UTC

        report_details = {
            "login_time": login_time_str,
            "backup_code": anonymized_code # Pass the anonymized code to the helper
            # account_email is passed directly to the helper
        }

        logout_link = await generate_report_access_mailto_link(
            translation_service=translation_service,
            language=language,
            account_email=email_address,
            report_type='backup_code', # Specify the report type
            details=report_details
        )

        if not logout_link:
             logger.error(f"Failed to generate mailto link for backup code used email for {email_address[:2]}...")
             # Decide if task should fail or continue without link
             # For now, let's allow it to continue but log the error prominently
             logout_link = "" # Set to empty string to avoid template errors

        # --- Prepare Template Context ---
        # Context now only needs the code, darkmode, and the generated mailto link
        context = {
            "code": anonymized_code, # The anonymized code itself for display in the email
            "darkmode": darkmode,
            "logout_link": logout_link # The generated mailto link
        }
        logger.debug(f"Prepared template context for backup code used email: {context}")

        # --- Send Email ---
        logger.info(f"Sending backup code used email to {email_address[:2]}*** - lang: {language}")

        success = await email_template_service.send_email(
            template="backup-code-was-used", # Use the correct template name
            recipient_email=email_address,
            context=context,
            lang=language
        )

        if not success:
            logger.error(f"Failed to send backup code used email for email {email_address[:2]}...")
            return False

        logger.info(f"Backup code used email sent successfully for email {email_address[:2]}...")
        return True

    except Exception as e:
        logger.error(f"Error in _async_send_backup_code_used_email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False