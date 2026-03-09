# backend/core/api/app/tasks/email_tasks/new_api_key_device_email_task.py
#
# Celery task: send a security-alert email when a new IP/device uses a user's
# API key for the first time.
#
# This is a *security* email — it is always sent regardless of the user's
# email_notifications_enabled preference (which only governs chat-related
# notifications).
#
# Architecture: follows the same pattern as new_device_email_task.py.
# Triggered from api_key_auth.py after a new api_key_devices record is created.
#
# Related docs: docs/architecture/developer-settings.md

import logging
import asyncio
from datetime import datetime, timezone

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())


@app.task(
    name='app.tasks.email_tasks.new_api_key_device_email_task.send_new_api_key_device_email',
    bind=True,
)
def send_new_api_key_device_email(
    self,
    recipient_email: str,
    anonymized_ip: str,
    region: str,
    developer_settings_url: str,
    language: str = "en",
    darkmode: bool = False,
) -> bool:
    """
    Celery task: send a security alert email when a new device/IP uses an API key.

    Args:
        recipient_email: Decrypted notification email address of the user.
        anonymized_ip: Anonymized IP, e.g. "184.149.xxx".
        region: Human-readable region string, e.g. "California, US".
        developer_settings_url: Direct URL to the Developer Settings > Devices page.
        language: BCP-47 language code for template localisation.
        darkmode: Whether to render the dark-mode variant of the template.
    """
    logger.info(f"Starting new_api_key_device email task for {recipient_email[:2]}***")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            _async_send_new_api_key_device_email(
                recipient_email=recipient_email,
                anonymized_ip=anonymized_ip,
                region=region,
                developer_settings_url=developer_settings_url,
                language=language,
                darkmode=darkmode,
            )
        )
        logger.info(f"new_api_key_device email task done for {recipient_email[:2]}***")
        return result
    except Exception as e:
        logger.error(
            f"Failed new_api_key_device email task for {recipient_email[:2]}***: {e}",
            exc_info=True,
        )
        return False
    finally:
        loop.close()


async def _async_send_new_api_key_device_email(
    recipient_email: str,
    anonymized_ip: str,
    region: str,
    developer_settings_url: str,
    language: str,
    darkmode: bool,
) -> bool:
    """
    Async inner implementation.

    IMPORTANT: uses try/finally so SecretsManager's httpx client is closed
    before the event loop closes — prevents "Event loop is closed" errors.
    """
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        email_service = EmailTemplateService(secrets_manager=secrets_manager)

        now_utc = datetime.now(timezone.utc)
        year = now_utc.strftime("%Y")
        month = now_utc.strftime("%m")
        day = now_utc.strftime("%d")
        time_str = now_utc.strftime("%H:%M")
        timezone_name = "UTC"

        context = {
            "anonymized_ip": anonymized_ip,
            "region": region,
            "year": year,
            "month": month,
            "day": day,
            "time": time_str,
            "timezone_name": timezone_name,
            "developer_settings_url": developer_settings_url,
            "darkmode": darkmode,
        }

        success = await email_service.send_email(
            template="new-api-key-device",
            recipient_email=recipient_email,
            context=context,
            lang=language,
        )

        if not success:
            logger.error(f"Failed to send new_api_key_device email for {recipient_email[:2]}***")
            return False

        logger.info(f"new_api_key_device email sent to {recipient_email[:2]}***")
        return True

    except Exception as e:
        logger.error(
            f"Error in _async_send_new_api_key_device_email for {recipient_email[:2]}***: {e}",
            exc_info=True,
        )
        return False
    finally:
        await secrets_manager.aclose()
