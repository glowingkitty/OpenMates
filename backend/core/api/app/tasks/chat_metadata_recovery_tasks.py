"""Retry only sealed metadata persistence; never re-run paid inference."""
from __future__ import annotations

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError, ChatRecoveryService

logger = logging.getLogger(__name__)
RETRY_DELAYS = (1, 3, 10, 30, 60)


async def persist_pending_metadata(data: dict) -> dict:
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.cache import CacheService

    directus = DirectusService()
    try:
        result = await ChatRecoveryService(directus).execute("create_metadata_job", data)
    finally:
        await directus.close()
    cache = CacheService()
    try:
        await cache.publish_event(f"ai_typing_indicator_events::{data['hashed_user_id']}", {
            "type": "chat_metadata_recovery_available", "user_id_hash": data["hashed_user_id"],
            "metadata_recovery_job": result,
        })
    finally:
        await cache.close()
    return result


@celery_app.task(bind=True, name="app.tasks.persistence_tasks.persist_chat_metadata_recovery", max_retries=5)
def persist_chat_metadata_recovery(self, data: dict) -> dict:
    try:
        return asyncio.run(persist_pending_metadata(data))
    except ChatRecoveryProtocolError as exc:
        if exc.status_code in {400, 404, 409, 410}:
            # Deletion, changed ownership/key, or malformed state cannot be retried.
            logger.warning("Sealed metadata retry rejected code=%s", exc.code)
            return {"state": "REJECTED"}
        raise self.retry(exc=RuntimeError("Sealed metadata persistence unavailable"),
                         countdown=RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)])
    except Exception:
        raise self.retry(exc=RuntimeError("Sealed metadata persistence unavailable"),
                         countdown=RETRY_DELAYS[min(self.request.retries, len(RETRY_DELAYS) - 1)])
