# backend/core/api/app/tasks/push_worker_service.py
"""Initialize the process-local push service for Celery delivery workers.

This module stays independent from Celery's broad bootstrap imports so the
credential lifecycle can be tested without loading unrelated worker services.
"""

import logging

from backend.core.api.app.services.push_notification_service import (
    push_notification_service,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager


logger = logging.getLogger(__name__)


async def initialize_push_services(worker_queues: set[str]) -> None:
    """Initialize push credentials before a push worker accepts delivery tasks."""
    if "push" not in worker_queues:
        logger.info("Skipping push service initialization - not a push worker")
        return

    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        await push_notification_service.initialize(secrets_manager)
        if not push_notification_service.is_ready():
            raise RuntimeError("Push notification service failed to initialize")
        logger.info("Push notification service initialized for worker process")
    finally:
        await secrets_manager.aclose()
