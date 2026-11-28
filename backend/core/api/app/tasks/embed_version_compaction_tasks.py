"""Daily metadata-only compaction of old unnamed session versions of embeds."""

from __future__ import annotations

import asyncio

from backend.core.api.app.services.embed_version_compaction_service import compact_session_versions
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


@app.task(name="storage.compact_embed_session_versions", base=BaseServiceTask, bind=True)
def compact_embed_session_versions(self: BaseServiceTask) -> dict:
    async def run() -> dict:
        try:
            await self.initialize_services()
            return await compact_session_versions(self.directus_service)
        finally:
            await self.cleanup_services()

    return asyncio.run(run())
