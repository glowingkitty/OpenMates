import logging
import asyncio
import aiohttp
import json
from typing import Optional, Union
from urllib.parse import quote

# Import the Celery app
from backend.core.api.app.tasks.celery_config import app

# Import necessary utilities
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.mailjet_contact_cleanup_task.cleanup_mailjet_contact', bind=True)
def cleanup_mailjet_contact(
    self,
    recipient_email: str
) -> bool:
    """
    Delayed cleanup task to remove a contact from Mailjet after email sending.

    This task is scheduled to run 30 seconds after email sending to allow
    Mailjet time to fully process the contact creation before deletion.

    Args:
        recipient_email: Email address of the contact to clean up

    Returns:
        True if cleanup succeeded or was not needed, False if cleanup failed
    """
    logger.info(f"Starting delayed Mailjet contact cleanup for {recipient_email[:3]}***")
    try:
        # Use asyncio.run() which handles loop creation and cleanup properly
        result = asyncio.run(_async_cleanup_mailjet_contact(recipient_email))
        logger.info(f"Mailjet contact cleanup completed for {recipient_email[:3]}*** - Success: {result}")
        return result
    except Exception as e:
        logger.error(f"Error in Mailjet contact cleanup task for {recipient_email[:3]}***: {str(e)}", exc_info=True)
        # Return True even on error since this is best-effort cleanup and shouldn't fail the overall process
        return True


async def _async_cleanup_mailjet_contact(recipient_email: str) -> bool:
    """
    Async implementation of Mailjet contact cleanup.

    Follows the same logic as EmailTemplateService._best_effort_delete_mailjet_contact
    but runs as a separate delayed task to avoid timing issues.
    """
    # Initialize SecretsManager outside try block so it's available in finally
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()

        # Fetch Mailjet API keys
        api_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/mailjet",
            secret_key="api_key"
        )
        api_secret = await secrets_manager.get_secret(
            secret_path="kv/data/providers/mailjet",
            secret_key="api_secret"
        )

        if not api_key or not api_secret:
            logger.warning("Mailjet contact cleanup skipped: API credentials not found")
            return True

        # Mailjet API endpoints
        contact_lookup_base_url = "https://api.mailjet.com/v3/REST/contact"
        gdpr_delete_base_url = "https://api.mailjet.com/v4/contacts"

        encoded_recipient = quote(recipient_email, safe="")
        lookup_url = f"{contact_lookup_base_url}/{encoded_recipient}"

        async with aiohttp.ClientSession() as session:
            auth = aiohttp.BasicAuth(api_key, api_secret)

            # Step 1: Lookup contact to get ID
            async with session.get(lookup_url, auth=auth) as lookup_response:
                if lookup_response.status == 404:
                    logger.info("Mailjet contact cleanup: contact not found (non-fatal).")
                    return True
                if lookup_response.status != 200:
                    body = await lookup_response.text()
                    logger.warning(
                        f"Mailjet contact lookup returned status {lookup_response.status} (non-fatal). "
                        f"Response: {body[:500]}"
                    )
                    return True

                body = await lookup_response.text()
                try:
                    lookup_data = json.loads(body)
                except json.JSONDecodeError:
                    logger.warning(
                        "Mailjet contact lookup returned non-JSON body (non-fatal). "
                        f"Response: {body[:500]}"
                    )
                    return True

                contact_id: Optional[Union[str, int]] = None
                data = lookup_data.get("Data") or []
                if data and isinstance(data, list) and isinstance(data[0], dict):
                    contact_id = data[0].get("ID")

                if not contact_id:
                    logger.warning(
                        f"Mailjet contact lookup did not return a contact ID for {recipient_email[:3]}*** (non-fatal). "
                        f"Response: {str(lookup_data)[:500]}"
                    )
                    return True

            # Step 2: Delete contact using GDPR endpoint
            delete_url = f"{gdpr_delete_base_url}/{contact_id}"
            async with session.delete(delete_url, auth=auth) as delete_response:
                # 200: anonymized, then removed after 30 days; 404: already missing; others warn.
                if delete_response.status in (200, 404):
                    logger.info("Mailjet contact cleanup completed successfully (non-fatal).")
                    return True
                body = await delete_response.text()
                logger.warning(
                    f"Mailjet contact cleanup returned status {delete_response.status} (non-fatal). "
                    f"Response: {body[:500]}"
                )
                return True

    except Exception as e:
        logger.warning(f"Mailjet contact cleanup failed (non-fatal): {e}")
        return True
    finally:
        # CRITICAL: Close async resources (like httpx clients) before the event loop closes
        # This prevents "Event loop is closed" errors during cleanup
        try:
            await secrets_manager.aclose()
            logger.debug("SecretsManager closed successfully for Mailjet contact cleanup task")
        except Exception as cleanup_error:
            logger.warning(f"Error closing SecretsManager during Mailjet cleanup: {cleanup_error}")