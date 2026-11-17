"""
Scheduled jobs for safety reviews (existing Celery beat, persistence queue).

- 48-hour reminder to the admin for undecided reviews (hourly check)
- automatic restore of unclear cases with no appeal after 14 days (daily)
- retention cleanup: strike records 90 days after closing, appeals 6 months after the decision (daily)
"""

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


async def _run(job: str):
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.shared.python_utils.image_safety import safety_review
    from backend.shared.python_utils.image_safety.account_suspension import alert_admin

    cache_service = CacheService()
    directus_service = DirectusService()
    try:
        if job == "remind":
            return await safety_review.remind_stale_reviews(directus_service, alert_admin)
        if job == "restore":
            return await safety_review.auto_restore_unappealed(directus_service, cache_service)
        return await safety_review.purge_closed_cases(directus_service)
    finally:
        await cache_service.close()
        await directus_service.close()


@app.task(name="safety.remind_stale_reviews")
def remind_stale_reviews() -> int:
    """Remind the admin of reviews undecided for 48 hours."""
    return asyncio.run(_run("remind"))


@app.task(name="safety.auto_restore_unappealed")
def auto_restore_unappealed() -> int:
    """Restore unclear cases that were not appealed within 14 days."""
    return asyncio.run(_run("restore"))


@app.task(name="safety.purge_closed_cases")
def purge_closed_cases() -> dict:
    """Delete closed strike records (90 days) and decided appeals (6 months)."""
    return asyncio.run(_run("purge"))
