"""Celery dispatcher for automatic interpretation of spawned-chat events (app_ai queue).

See backend/shared/python_utils/chat_orchestration_interpretation.py.
"""

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils import chat_orchestration_interpretation as interpretation
from backend.shared.python_utils.chat_orchestration_interpretation import run_dispatcher

logger = logging.getLogger(__name__)


@app.task(name=interpretation.TASK_NAME, max_retries=0)
def interpret_creator_events(user_id: str, chat_id: str, elapsed: float = 0):
    """Interpret buffered events once the debounce window ended and the chat is idle."""
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

    async def run():
        return await run_dispatcher(
            user_id, chat_id, elapsed, cache_service=CacheService(), directus_service=DirectusService(),
            encryption_service=EncryptionService(),
            reschedule=lambda countdown, new_elapsed: interpretation._schedule(user_id, chat_id, countdown, new_elapsed))

    return asyncio.run(run())
