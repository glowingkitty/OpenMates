"""Read-only provider polling; all application writes are private hashed state."""
import asyncio
import logging
import os

from backend.core.api.app.services.email_delivery_feedback import (
    delivery_environment, reconcile_delivery_feedback,
)
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


async def poll_delivery_feedback() -> dict:
    # Isolated CI has no Brevo access; captured SMTP sends are not live mail.
    if os.getenv("OPENMATES_CI_MAIL_CAPTURE") == "1" or os.getenv("CI", "").lower() in {"true", "1"}:
        return {"status": "skipped", "reason": "ci_mail_capture"}
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    secrets = SecretsManager()
    directus = None
    try:
        await secrets.initialize()
        api_key = await secrets.get_secret(secret_path="kv/data/providers/brevo", secret_key="api_key")
        if not api_key:
            return {"status": "skipped", "reason": "brevo_secret_unavailable"}
        directus = DirectusService()
        return await reconcile_delivery_feedback(directus=directus, api_key=api_key, environment=delivery_environment())
    except Exception:
        # Raw provider text, exceptions and event identities are never logged.
        logger.error("Email delivery feedback polling failed")
        return {"status": "failed", "reason": "delivery_feedback_unavailable"}
    finally:
        try:
            if directus is not None:
                await directus.close()
        finally:
            await secrets.aclose()


@app.task(name="email_delivery.poll_feedback", soft_time_limit=240, time_limit=270)
def poll_feedback() -> dict:
    return asyncio.run(poll_delivery_feedback())
