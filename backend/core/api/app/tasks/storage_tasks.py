# backend/core/api/app/tasks/storage_tasks.py
#
# Celery delivery adapters for durable regional replication and deletion work.
# Beat performs a bounded indexed scan; per-record task identities keep retries
# independent and inherit the repository-wide broker redelivery guard.

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from backend.core.api.app.services.cold_archive_service import (
    ColdArchiveService,
    dispatch_due_cold_chat_archives,
)
from backend.core.api.app.services.s3.job_processor import RegionalStorageJobProcessor
from backend.core.api.app.services.s3.replication import dispatch_due_storage_jobs
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


@app.task(name="storage.process_replication_job", base=BaseServiceTask, bind=True)
def process_storage_replication_job(
    self: BaseServiceTask,
    *,
    job_id: str,
    expected_version: int,
) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        try:
            await self.initialize_services()
            return await RegionalStorageJobProcessor(
                directus_service=self.directus_service,
                s3_service=self.s3_service,
            ).process_replication_job(job_id, expected_version)
        finally:
            await self.cleanup_services()

    return asyncio.run(run())


@app.task(name="storage.process_deletion_tombstone", base=BaseServiceTask, bind=True)
def process_storage_deletion_tombstone(
    self: BaseServiceTask,
    *,
    tombstone_id: str,
    expected_version: int,
) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        try:
            await self.initialize_services()
            return await RegionalStorageJobProcessor(
                directus_service=self.directus_service,
                s3_service=self.s3_service,
            ).process_deletion_tombstone(tombstone_id, expected_version)
        finally:
            await self.cleanup_services()

    return asyncio.run(run())


@app.task(name="storage.archive_cold_chat", base=BaseServiceTask, bind=True)
def archive_cold_chat(self: BaseServiceTask, *, chat_id: str) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        try:
            await self.initialize_services()
            if await self.cache_service.get_active_ai_task(chat_id):
                return {"chat_id_hash": hashlib.sha256(chat_id.encode()).hexdigest(), "state": "skipped_active"}
            return await ColdArchiveService(
                directus_service=self.directus_service,
                s3_service=self.s3_service,
            ).archive_chat(
                chat_id,
                processing_task_checker=self.cache_service.get_active_ai_task,
            )
        finally:
            await self.cleanup_services()

    return asyncio.run(run())


@app.task(name="storage.sweep_due_jobs", base=BaseServiceTask, bind=True)
def sweep_due_storage_jobs(self: BaseServiceTask) -> dict[str, int]:
    async def run() -> dict[str, int]:
        try:
            await self.initialize_services()
            result = await dispatch_due_storage_jobs(
                directus_service=self.directus_service,
                replication_dispatch=lambda job_id, version: process_storage_replication_job.apply_async(
                    kwargs={"job_id": job_id, "expected_version": version},
                    task_id=f"storage-replication:{job_id}:v{version}",
                    queue="persistence",
                ),
                tombstone_dispatch=lambda tombstone_id, version: process_storage_deletion_tombstone.apply_async(
                    kwargs={"tombstone_id": tombstone_id, "expected_version": version},
                    task_id=f"storage-tombstone:{tombstone_id}:v{version}",
                    queue="persistence",
                ),
            )
            result["cold_archives_dispatched"] = await dispatch_due_cold_chat_archives(
                directus_service=self.directus_service,
                cache_service=self.cache_service,
                dispatch=lambda chat_id: archive_cold_chat.apply_async(
                    kwargs={"chat_id": chat_id},
                    task_id=f"storage-cold-chat:{hashlib.sha256(chat_id.encode()).hexdigest()}",
                    queue="persistence",
                ),
            )
            return result
        finally:
            await self.cleanup_services()

    return asyncio.run(run())
