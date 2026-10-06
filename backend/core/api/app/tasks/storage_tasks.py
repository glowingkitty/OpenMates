# backend/core/api/app/tasks/storage_tasks.py
#
# Celery delivery adapters for durable regional replication and deletion work.
# Beat performs a bounded indexed scan; per-record task identities keep retries
# independent and inherit the repository-wide broker redelivery guard.

from __future__ import annotations

import asyncio
import os
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
import uuid

from backend.core.api.app.services.s3.job_processor import RegionalStorageJobProcessor
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.s3.probe import probe_region_data_plane
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.s3.replication import (
    dispatch_due_storage_jobs,
    record_persisted_region_error,
    record_persisted_region_probe_success,
)
from backend.core.api.app.services.storage_reference_service import reconcile_prepared_storage_tombstones
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.storage_archive_rollout_config import (
    archive_feature_enabled, archive_advancement_allowed,
)
from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name

logger = logging.getLogger(__name__)


class StorageServiceTask(BaseServiceTask):
    """Initialize storage maintenance without billing or template dependencies."""

    async def initialize_services(self) -> None:
        await self.initialize_core_services()
        if self._s3_service is None:
            self._s3_service = S3UploadService(
                secrets_manager=self._secrets_manager,
                directus_service=self._directus_service,
            )
            # API startup owns bucket and policy reconciliation; workers only
            # initialize clients, including when no billing provider is configured.
            await self._s3_service.initialize(configure_buckets=False)


async def enqueue_warm_archive_check(*, cache_service: Any, chat_id: str) -> bool:
    """Coalesce canonical writes; the durable SQL sweep recovers lost deliveries."""
    if not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_COPY_ENABLED"):
        return False
    client = await cache_service.client
    if not client:
        return False
    key = "storage:warm_archive_admission:" + hashlib.sha256(chat_id.encode()).hexdigest()
    if not await client.set(key, "1", nx=True, ex=60):
        return False
    try:
        archive_cold_chat.apply_async(kwargs={"chat_id": chat_id}, queue="persistence", countdown=5)
    except Exception:
        await client.delete(key)
        raise
    return True


@app.task(name="storage.copy_chat_checkpoint_archive", base=StorageServiceTask, bind=True)
def copy_chat_checkpoint_archive(self: StorageServiceTask, *, chat_id: str, checkpoint_id: str) -> dict[str, Any]:
    """Copy an acknowledged checkpoint prefix; payload removal is separate."""
    if not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_COPY_ENABLED"):
        return {"state": "archive_copy_disabled"}
    async def run() -> dict[str, Any]:
        from backend.core.api.app.services.chat_message_archive_service import ArchiveIntegrityError, ChatMessageArchiveService
        try:
            await self.initialize_services()
            rows = await self.directus_service.get_items("chat_compression_checkpoints", params={
                "filter": {"id": {"_eq": checkpoint_id}, "chat_id": {"_eq": chat_id}}, "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            if not rows or not rows[0].get("compressed_up_to_message_id"):
                return {"state": "legacy_boundary_requires_client_update"}
            checkpoint = rows[0]
            service = ChatMessageArchiveService(directus_service=self.directus_service, s3_service=self.s3_service)
            try:
                segment = await service.copy_segment(
                    chat_id=chat_id, checkpoint_id=checkpoint_id,
                    end=(int(checkpoint["compressed_up_to_timestamp"]), checkpoint["compressed_up_to_message_id"]),
                )
            except ArchiveIntegrityError as exc:
                if str(exc) in {"canonical_checkpoint_sources_not_ready", "archive_copy_in_progress",
                                "previous_archive_copy_incomplete", "checkpoint_does_not_advance",
                                "chat_unavailable", "exact_checkpoint_manifest_required"}:
                    return {"state": "deferred", "reason": str(exc)}
                raise
            if os.getenv("OPENMATES_STORAGE_CAPACITY_FIXTURES") == "true":
                segment = await service.activate_isolated_capacity_segment(segment)
            return segment
        finally:
            await self.cleanup_services()
    return asyncio.run(run())

def _provider_error_code(error: Exception) -> str:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)[:64]
    return type(error).__name__[:64]


async def probe_configured_storage_regions(
    *,
    directus_service: Any,
    s3_service: Any,
    now: datetime,
) -> dict[str, int]:
    """Run bounded managed-bucket probes and persist sanitized recovery state."""
    legacy_bucket = get_bucket_name("chatfiles", s3_service.environment)
    passed = 0
    failed = 0
    for region, client in s3_service.region_clients.items():
        bucket = resolve_regional_bucket_name(legacy_bucket, region)
        object_key = f".openmates-region-probe/{uuid.uuid4().hex}"
        try:
            await asyncio.to_thread(probe_region_data_plane, client, bucket, object_key)
        except Exception as error:
            failed += 1
            await record_persisted_region_error(
                directus_service=directus_service,
                region=region,
                error_code=_provider_error_code(error),
                now=now,
            )
            continue
        persisted = await record_persisted_region_probe_success(
            directus_service=directus_service,
            region=region,
            now=now,
        )
        passed += int(persisted)
    return {"region_probes_passed": passed, "region_probes_failed": failed}


@app.task(name="storage.process_replication_job", base=StorageServiceTask, bind=True)
def process_storage_replication_job(
    self: StorageServiceTask,
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


@app.task(name="storage.process_deletion_tombstone", base=StorageServiceTask, bind=True)
def process_storage_deletion_tombstone(
    self: StorageServiceTask,
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


@app.task(name="storage.archive_cold_chat", base=StorageServiceTask, bind=True)
def archive_cold_chat(self: StorageServiceTask, *, chat_id: str) -> dict[str, Any]:
    """Copy one policy-eligible bounded prefix, without whole-graph deletion."""
    if not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_COPY_ENABLED"):
        return {"state": "archive_copy_disabled"}
    async def run() -> dict[str, Any]:
        from backend.core.api.app.services.chat_message_archive_service import (
            ArchiveIntegrityError, ChatMessageArchiveService,
        )
        try:
            await self.initialize_services()
            if await self.cache_service.get_active_ai_task(chat_id):
                return {"chat_id_hash": hashlib.sha256(chat_id.encode()).hexdigest(), "state": "skipped_active"}
            try:
                return await ChatMessageArchiveService(
                    directus_service=self.directus_service,
                    s3_service=self.s3_service,
                ).copy_segment(chat_id=chat_id)
            except ArchiveIntegrityError as exc:
                reason = str(exc)
                if reason in {
                    "within_warm_limits", "no_new_prefix", "no_bounded_canonical_messages",
                    "active_preflight", "pending_recovery", "pending_recovery_output",
                    "child_durability_or_synthesis_pending", "chat_unavailable",
                    "unsupported_or_incomplete_newest_window", "unsupported_canonical_ciphertext",
                    "archive_copy_in_progress", "previous_archive_copy_incomplete",
                }:
                    return {"chat_id_hash": hashlib.sha256(chat_id.encode()).hexdigest(),
                            "state": "deferred", "reason": reason}
                raise
        finally:
            await self.cleanup_services()

    return asyncio.run(run())


async def dispatch_due_warm_chat_archives(
    *, directus_service: Any, cache_service: Any, dispatch: Any,
    now_timestamp: int, batch_limit: int = 1000,
) -> int:
    """Sweep likely SQL candidates by stable chat ID without loading histories."""
    from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService

    cursor_key = "storage:warm_archive_sweep_cursor:v1"
    cursor = await cache_service.get(cursor_key)
    if cursor is not None and not isinstance(cursor, str):
        raise RuntimeError("WARM_ARCHIVE_SWEEP_CURSOR_INVALID")
    if not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_COPY_ENABLED"):
        return 0
    service = ChatMessageArchiveService(directus_service=directus_service, s3_service=None)
    candidates = await service.transaction("policy_candidates", {
        "after_chat_id": cursor, "limit": min(max(int(batch_limit), 1), 1000), "now": now_timestamp,
    })
    chat_ids = candidates.get("chat_ids")
    next_cursor = candidates.get("next_cursor")
    if not isinstance(chat_ids, list) or (next_cursor is not None and not isinstance(next_cursor, str)):
        raise RuntimeError("WARM_ARCHIVE_SWEEP_RESPONSE_INVALID")
    if next_cursor:
        if not await cache_service.set(cursor_key, next_cursor, ttl=7 * 86400):
            raise RuntimeError("WARM_ARCHIVE_SWEEP_CURSOR_SAVE_FAILED")
    else:
        await cache_service.delete(cursor_key)
    for candidate_id in chat_ids:
        dispatch(str(candidate_id))
    return len(chat_ids)


@app.task(name="storage.advance_chat_archive", base=StorageServiceTask, bind=True)
def advance_chat_archive(self: StorageServiceTask, *, segment_id: str) -> dict[str, Any]:
    """Restart expired copies or advance one read/prune batch; all flags default off."""
    if not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_COPY_ENABLED"):
        return {"state": "archive_copy_disabled"}
    async def run() -> dict[str, Any]:
        from backend.core.api.app.services.chat_message_archive_service import (
            ArchiveIntegrityError, ChatMessageArchiveService, SEGMENTS,
        )
        try:
            await self.initialize_services()
            rows = await self.directus_service.get_items(SEGMENTS, params={
                "filter": {"id": {"_eq": segment_id}}, "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            if not rows:
                return {"state": "archive_no_longer_referenced"}
            segment = rows[0]
            service = ChatMessageArchiveService(directus_service=self.directus_service, s3_service=self.s3_service)
            try:
                if segment["state"] == "copying":
                    if int(segment["lease_until"]) > int(datetime.now(timezone.utc).timestamp()):
                        return {"state": "archive_copy_in_progress"}
                    segment = await service.copy_segment(chat_id=segment["chat_id"], resume_segment_id=segment_id)
                if segment["state"] in {"verified", "reader_active"}:
                    phase = "read" if segment["state"] == "verified" else "prune"
                    if not await archive_advancement_allowed(self.directus_service, phase=phase):
                        return {"state": "deferred", "reason": "release_or_client_gate_pending"}
                return await service.advance_segment(segment)
            except ArchiveIntegrityError as exc:
                reason = str(exc)
                if reason in {
                    "archive_copy_in_progress", "archive_generation_changed", "chat_unavailable",
                    "archive_segment_missing", "archive_read_rollout_not_verified",
                    "archive_prune_gates_not_verified", "archive_rollback_buffer_active",
                    "canonical_recovery_acknowledgement_required", "archive_not_verified",
                    "archive_reader_not_active",
                }:
                    return {"state": "deferred", "reason": reason}
                await service.pause_rollout(failure_code=reason)
                logger.error("Chat archive lifecycle paused: %s", reason)
                raise
        finally:
            await self.cleanup_services()
    return asyncio.run(run())


async def dispatch_chat_archive_progress(*, directus_service: Any, cache_service: Any,
                                       segment_dispatch: Any, checkpoint_dispatch: Any,
                                       now_timestamp: int) -> dict[str, int]:
    """Durable SQL intent is authoritative; Redis stores disposable scan cursors."""
    from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService
    if not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_COPY_ENABLED"):
        return {"archive_segments_dispatched": 0, "archive_checkpoints_dispatched": 0}
    service = ChatMessageArchiveService(directus_service=directus_service, s3_service=None)
    checkpoint_key = "storage:checkpoint_archive_cursor:v1"
    checkpoints = await service.transaction("checkpoint_candidates", {
        "after_id": await cache_service.get(checkpoint_key), "limit": 1000,
    })
    if checkpoints.get("next_cursor"):
        if not await cache_service.set(checkpoint_key, checkpoints["next_cursor"], ttl=7 * 86400):
            raise RuntimeError("CHECKPOINT_ARCHIVE_CURSOR_SAVE_FAILED")
    else:
        await cache_service.delete(checkpoint_key)
    for row in checkpoints["checkpoints"]:
        checkpoint_dispatch(row["chat_id"], row["id"])
    cursor_key = "storage:archive_progress_cursor:v1"
    # Directus rejects ordered filters on UUID fields. Keep the stable cursor
    # comparison in the internal SQL transaction, where UUID ordering is valid.
    candidates = await service.transaction("progress_candidates", {
        "after_id": await cache_service.get(cursor_key), "limit": 25,
        "now": now_timestamp,
        "reads_enabled": archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_READS_ENABLED"),
        "prune_enabled": archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED"),
    })
    segments = candidates.get("segments")
    if not isinstance(segments, list):
        raise RuntimeError("ARCHIVE_PROGRESS_INDEX_UNAVAILABLE")
    if segments:
        if not await cache_service.set(cursor_key, segments[-1]["id"], ttl=7 * 86400):
            raise RuntimeError("ARCHIVE_PROGRESS_CURSOR_SAVE_FAILED")
    else:
        await cache_service.delete(cursor_key)
    for row in segments:
        segment_dispatch(row["id"])
    return {"archive_segments_dispatched": len(segments), "archive_checkpoints_dispatched": len(checkpoints["checkpoints"])}


@app.task(name="storage.sweep_due_jobs", base=StorageServiceTask, bind=True)
def sweep_due_storage_jobs(self: StorageServiceTask) -> dict[str, int]:
    async def run() -> dict[str, int]:
        try:
            await self.initialize_services()
            prepared = await reconcile_prepared_storage_tombstones(
                directus_service=self.directus_service,
                encryption_service=self.encryption_service,
                now=datetime.now(timezone.utc),
            )
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
            result.update(prepared)
            result.update(await probe_configured_storage_regions(
                directus_service=self.directus_service,
                s3_service=self.s3_service,
                now=datetime.now(timezone.utc),
            ))
            now_timestamp = int(datetime.now(timezone.utc).timestamp())
            result.update(await dispatch_chat_archive_progress(
                directus_service=self.directus_service, cache_service=self.cache_service, now_timestamp=now_timestamp,
                segment_dispatch=lambda segment_id: advance_chat_archive.apply_async(
                    kwargs={"segment_id": segment_id}, queue="persistence",
                ),
                checkpoint_dispatch=lambda chat_id, checkpoint_id: copy_chat_checkpoint_archive.apply_async(
                    kwargs={"chat_id": chat_id, "checkpoint_id": checkpoint_id}, queue="persistence",
                ),
            ))
            result["cold_archives_dispatched"] = await dispatch_due_warm_chat_archives(
                directus_service=self.directus_service,
                cache_service=self.cache_service,
                now_timestamp=now_timestamp,
                dispatch=lambda chat_id: archive_cold_chat.apply_async(
                    kwargs={"chat_id": chat_id},
                    task_id=f"storage-warm-chat:{hashlib.sha256(chat_id.encode()).hexdigest()}:{now_timestamp // 300}",
                    queue="persistence",
                ),
            )
            return result
        finally:
            await self.cleanup_services()

    return asyncio.run(run())
