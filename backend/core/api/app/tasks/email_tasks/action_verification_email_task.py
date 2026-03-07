"""
Purpose: Celery task to generate and send action verification OTP codes via email.
Used for sensitive actions (account deletion, etc.) for users who only have password
auth (no 2FA/passkey). Stores the code in cache and sends the email.

Architecture: Reuses the EmailTemplateService and CacheService pattern from
  verification_email_task.py. Uses the 'action-verification' email template.
  See docs/architecture/app-skills.md for async task context.
Tests: N/A (tested via E2E signup-skip-2fa-flow.spec.ts)
"""
import logging
import random
import asyncio

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# TTL for action verification codes: 10 minutes
ACTION_VERIFICATION_CODE_TTL = 600

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(
    name='app.tasks.email_tasks.action_verification_email_task.generate_and_send_action_verification_email',
    bind=True
)
def generate_and_send_action_verification_email(
    self,
    user_id: str,
    email: str,
    action: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Generate an action verification OTP code, store it in cache, and send email.

    Args:
        user_id: The user's ID (used for cache key scoping).
        email: The user's email address to send the code to.
        action: The action being verified (e.g. 'delete_account').
        language: Language code for the email template.
        darkmode: Whether to render the email in dark mode.
    """
    logger.info(f"Starting action verification email task for user {user_id}, action={action}")
    try:
        result = asyncio.run(
            _async_generate_and_send_action_verification_email(
                user_id, email, action, language, darkmode
            )
        )
        logger.info(f"Action verification email task completed for user {user_id}, action={action}")
        return result
    except Exception as e:
        logger.error(
            f"Failed to run action verification email task "
            f"for user {user_id}, action={action}: {e}",
            exc_info=True
        )
        return False


async def _async_generate_and_send_action_verification_email(
    user_id: str,
    email: str,
    action: str,
    language: str = "en",
    darkmode: bool = False
) -> bool:
    """
    Async implementation: generates 6-digit code, caches it, sends email.
    Cache key pattern: action_verification:{user_id}:{action}
    """
    secrets_manager = SecretsManager()

    try:
        cache_service = CacheService()
        await secrets_manager.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)

        # Generate a 6-digit code
        verification_code = ''.join(random.choices('0123456789', k=6))
        logger.info(f"Generated action verification code for user {user_id}, action={action}")

        # Store the code in cache with TTL
        cache_key = f"action_verification:{user_id}:{action}"
        cache_result = await cache_service.set(
            cache_key, verification_code, ttl=ACTION_VERIFICATION_CODE_TTL
        )
        if not cache_result:
            logger.error(
                f"Failed to store action verification code in cache "
                f"for user {user_id}, action={action}"
            )
            return False

        logger.info(f"Stored action verification code in cache for user {user_id}, action={action}")

        # Send the email using the action-verification template
        context = {
            "code": verification_code,
            "darkmode": darkmode,
        }

        logger.info(
            f"Sending action verification email to user {user_id}, "
            f"action={action}, language={language}"
        )
        success = await email_template_service.send_email(
            template="action-verification",
            recipient_email=email,
            context=context,
            lang=language
        )

        if not success:
            logger.error(f"Failed to send action verification email to user {user_id}")
            return False

        logger.info(f"Action verification email sent successfully to user {user_id}")
        return True

    except Exception as e:
        logger.error(
            f"Error in action verification email task "
            f"for user {user_id}, action={action}: {e}",
            exc_info=True
        )
        return False
    finally:
        await secrets_manager.aclose()
