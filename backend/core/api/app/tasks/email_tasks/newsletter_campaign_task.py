"""Celery tasks for scheduled newsletter campaigns.

The task only sends Directus campaigns that were previewed to an admin and then
explicitly approved. Recipient-level idempotency is handled by email_deliveries
inside the existing newsletter sender.
"""

from __future__ import annotations

import asyncio
import logging

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.newsletter_campaign_service import NewsletterCampaignService
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


@app.task(name="app.tasks.email_tasks.newsletter_campaign_task.process_due_newsletter_campaigns", bind=True)
def process_due_newsletter_campaigns(self) -> dict:
    try:
        return asyncio.run(_process_due_newsletter_campaigns())
    except Exception as exc:
        logger.error("Scheduled newsletter campaign processing failed: %s", exc, exc_info=True)
        return {"processed": 0, "error": str(exc)}


async def _process_due_newsletter_campaigns() -> dict:
    directus = DirectusService()
    try:
        return await NewsletterCampaignService(directus).process_due_campaigns()
    finally:
        await directus.close()
