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
from backend.core.api.app.utils.email_context_helpers import prepare_new_device_login_context

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.new_device_email_task.send_new_device_email', bind=True)
def send_new_device_email(
    self,
    email_address: str,
    user_agent_string: str,
    ip_address: str,
    latitude: Optional[float],
    longitude: Optional[float],
    location_name: str,
    is_localhost: bool,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Celery task wrapper to send a 'new device login' notification email.
    """
    logger.info(f"Starting new device login email task for email: {email_address[:2]}***")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_async_send_new_device_email(
            email_address=email_address,
            user_agent_string=user_agent_string,
            ip_address=ip_address,
            latitude=latitude,
            longitude=longitude,
            location_name=location_name,
            is_localhost=is_localhost,
            language=language,
            darkmode=darkmode
        ))
        logger.info(f"New device login email task completed for email: {email_address[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run new device login email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False
    finally:
        loop.close()

async def _async_send_new_device_email(
    email_address: str,
    user_agent_string: str,
    ip_address: str,
    latitude: Optional[float],
    longitude: Optional[float],
    location_name: str,
    is_localhost: bool,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation for sending the new device login email.
    """
    try:
        secrets_manager = SecretsManager() # Instantiate SecretsManager
        await secrets_manager.initialize() # Initialize SecretsManager
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager) # Pass SecretsManager

        # --- Prepare Context using Helper Function ---
        try:
            context = await prepare_new_device_login_context(
                user_agent_string=user_agent_string,
                ip_address=ip_address,
                account_email=email_address,
                language=language,
                darkmode=darkmode,
                translation_service=email_template_service.translation_service,
                latitude=latitude,
                longitude=longitude,
                location_name=location_name,
                is_localhost=is_localhost
            )
        except Exception as context_exc:
             logger.error(f"Error preparing email context for email {email_address[:2]}...: {context_exc}", exc_info=True)
             return False # Fail the task if context preparation fails

        # --- Send Email ---
        logger.info(f"Sending new device login email to {email_address[:2]}*** - lang: {language}")

        success = await email_template_service.send_email(
            template="new-device-login",
            recipient_email=email_address,
            context=context,
            lang=language
        )

        if not success:
            logger.error(f"Failed to send new device login email for email {email_address[:2]}...")
            return False

        logger.info(f"New device login email sent successfully for email {email_address[:2]}...")
        return True

    except Exception as e:
        logger.error(f"Error in _async_send_new_device_email task for email {email_address[:2]}...: {str(e)}", exc_info=True)
        return False