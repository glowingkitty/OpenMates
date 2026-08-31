# backend/apps/audio/assistant_speech/delete_task.py
#
# Lifecycle cleanup for assistant-response speech. It removes each segment's
# private chatfiles object and upload_files record before deleting durable speech
# metadata; source text is never loaded or emitted during cleanup.

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.apps.audio.assistant_speech.persistence import cleanup_generated_speech_asset, delete_speech_assets
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.storage_availability import initialize_task_storage

logger = logging.getLogger(__name__)


@app.task(bind=True, name="apps.audio.tasks.assistant_speech_delete", base=BaseServiceTask, queue="app_music")
def assistant_speech_delete_task(self: BaseServiceTask, arguments: dict[str, Any]) -> None:
    """Delete all generated files and metadata for one owner-scoped response."""
    asyncio.run(_async_delete_assistant_speech(self, arguments))


async def _async_delete_assistant_speech(task: BaseServiceTask, arguments: dict[str, Any]) -> None:
    await task.initialize_core_services()
    s3 = await initialize_task_storage(task)

    async def delete_asset(segment: dict[str, object]) -> None:
        asset_id = segment.get("generated_asset_id") or segment.get("pending_generated_asset_id")
        if not asset_id:
            return
        await cleanup_generated_speech_asset(
            task._directus_service,
            str(asset_id),
            delete_file=lambda file_key: s3.delete_file(bucket_key="chatfiles", file_key=file_key),
        )

    try:
        await delete_speech_assets(
            task._directus_service,
            user_id=str(arguments["user_id"]),
            chat_id=str(arguments["chat_id"]),
            assistant_message_id=str(arguments["assistant_message_id"]),
            delete_asset=delete_asset,
        )
    finally:
        await task.cleanup_services()
