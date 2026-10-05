"""Automatic artifact history copy, reader activation and pruning scans.

Each delivery scans at most 25 PostgreSQL metadata rows. Pruning is disabled
until current signed eligibility, client enforcement and durable gates pass.
"""

from __future__ import annotations

import asyncio

from backend.core.api.app.services.embed_version_archive_service import (
    copy_archive_batch, transition_archive_batch,
)
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.storage_archive_rollout_config import (
    archive_feature_enabled, archive_advancement_allowed,
)


@app.task(name="storage.copy_embed_version_payloads", base=BaseServiceTask, bind=True)
def copy_embed_version_payloads(self: BaseServiceTask, cursor: str | None = None) -> dict:
    if not archive_feature_enabled("EMBED_VERSION_ARCHIVE_COPY_ENABLED"):
        return {"status": "disabled", "copied": 0}

    async def run() -> dict:
        try:
            await self.initialize_services()
            return await copy_archive_batch(
                directus_service=self.directus_service,
                s3_service=self.s3_service,
                cursor=cursor,
            )
        finally:
            await self.cleanup_services()

    result = asyncio.run(run())
    if result.get("next_cursor"):
        copy_embed_version_payloads.apply_async(
            kwargs={"cursor": result["next_cursor"]},
            queue="persistence", countdown=10,
        )
    return result


@app.task(name="storage.activate_embed_version_readers", base=BaseServiceTask, bind=True)
def activate_embed_version_readers(self: BaseServiceTask, cursor: str | None = None) -> dict:
    if (not archive_feature_enabled("EMBED_VERSION_ARCHIVE_COPY_ENABLED")
            or not archive_feature_enabled("EMBED_VERSION_ARCHIVE_READ_ENABLED")):
        return {"status": "disabled", "advanced": 0}

    async def run() -> dict:
        try:
            await self.initialize_services()
            if not await archive_advancement_allowed(self.directus_service, phase="read"):
                return {"status": "paused", "advanced": 0, "reason": "release_or_client_gate_pending"}
            return await transition_archive_batch(
                directus_service=self.directus_service, s3_service=self.s3_service,
                operation="activate", cursor=cursor,
            )
        finally:
            await self.cleanup_services()

    result = asyncio.run(run())
    if result.get("next_cursor"):
        activate_embed_version_readers.apply_async(
            kwargs={"cursor": result["next_cursor"]}, queue="persistence", countdown=10,
        )
    return result


@app.task(name="storage.prune_embed_version_payloads", base=BaseServiceTask, bind=True)
def prune_embed_version_payloads(self: BaseServiceTask, cursor: str | None = None) -> dict:
    if (not archive_feature_enabled("EMBED_VERSION_ARCHIVE_COPY_ENABLED")
            or not archive_feature_enabled("EMBED_VERSION_ARCHIVE_READ_ENABLED")
            or not archive_feature_enabled("EMBED_VERSION_ARCHIVE_PRUNE_ENABLED")):
        return {"status": "disabled", "advanced": 0}

    async def run() -> dict:
        try:
            await self.initialize_services()
            if not await archive_advancement_allowed(self.directus_service, phase="prune"):
                return {"status": "paused", "advanced": 0, "reason": "release_or_client_gate_pending"}
            return await transition_archive_batch(
                directus_service=self.directus_service, s3_service=self.s3_service,
                operation="prune", cursor=cursor,
            )
        finally:
            await self.cleanup_services()

    result = asyncio.run(run())
    if result.get("next_cursor"):
        prune_embed_version_payloads.apply_async(
            kwargs={"cursor": result["next_cursor"]}, queue="persistence", countdown=10,
        )
    return result
