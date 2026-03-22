"""
Account Recovery Email Task

Sends verification code emails for account recovery requests.
Uses the same pattern as verification_email_task but for recovery flow.
"""

import logging
import random
import asyncio

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app

# Import necessary services and utilities
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.recovery_email_task.send_account_recovery_email', bind=True)
def send_account_recovery_email(
    self,
    email: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Generate a recovery code, store it in cache, and send recovery email.
    
    The recovery code is stored with a longer TTL than verification codes
    since account recovery is a more critical process.
    """
    logger.info(f"Starting account recovery email task for {email[:2]}***")
    try:
        result = asyncio.run(
            _async_send_account_recovery_email(email, language, darkmode)
        )
        logger.info(f"Account recovery email task completed for {email[:2]}***")
        return result
    except Exception as e:
        logger.error(f"Failed to run account recovery email task for {email[:2]}***: {str(e)}", exc_info=True)
        return False


async def _async_send_account_recovery_email(
    email: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation of the account recovery email task.
    
    Generates a 6-digit code, stores it in cache, and sends the email.
    
    IMPORTANT: Uses try/finally to ensure SecretsManager's httpx client is
    properly closed before returning. This prevents "Event loop is closed" 
    errors when asyncio.run() closes the event loop in Celery tasks.
    """
    # Create services outside try block so they're available in finally
    secrets_manager = SecretsManager()
    
    try:
        # Create standalone services for this task
        cache_service = CacheService()
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

        # Generate a 6-digit recovery code
        recovery_code = ''.join(random.choices('0123456789', k=6))
        logger.info(f"Generated recovery code for {email[:2]}***")

        # Store the code in cache with 15 minute expiration
        # Cache key format: account_recovery:{email}
        cache_key = f"account_recovery:{email}"
        cache_result = await cache_service.set(cache_key, recovery_code, ttl=900)  # 15 minutes
        
        if not cache_result:
            logger.error(f"Failed to store recovery code in cache for {email[:2]}***")
            return False

        logger.info(f"Stored recovery code in cache for {email[:2]}***")

        # Prepare email context
        context = {
            "code": recovery_code,
            "darkmode": darkmode
        }

        # Send the email using the recovery template
        logger.info(f"Sending account recovery email to {email[:2]}*** - language: {language}")
        success = await email_template_service.send_email(
            template="account-recovery",
            recipient_email=email,
            context=context,
            lang=language
        )

        if not success:
            logger.error(f"Failed to send account recovery email to {email[:2]}***")
            return False

        logger.info(f"Account recovery email sent successfully to {email[:2]}***")
        return True

    except Exception as e:
        logger.error(f"Error in account recovery email task for {email[:2]}***: {str(e)}", exc_info=True)
        return False
    finally:
        # CRITICAL: Close the httpx client before asyncio.run() closes the event loop
        # This prevents "Event loop is closed" errors during httpx cleanup
        await secrets_manager.aclose()

