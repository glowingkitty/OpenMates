"""Durable regional object replication and deletion job execution.

The processor loads safe routing state from product Directus and performs S3
network calls in a worker thread. Immutable keys make copy and purge retries
idempotent; every copied ciphertext object is SHA-256 verified at both ends.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
from tempfile import SpooledTemporaryFile
from typing import Any

from botocore.exceptions import ClientError

from backend.core.api.app.services.s3.config import get_bucket_config, get_bucket_name
from backend.core.api.app.services.s3.reconciliation import record_purge_result
from backend.core.api.app.services.s3.replication import (
    record_persisted_region_error,
    record_replica_failure,
)
from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name


COPY_CHUNK_SIZE = 1024 * 1024
COPY_MEMORY_LIMIT = 8 * COPY_CHUNK_SIZE
MISSING_SOURCE_CODES = {"404", "NoSuchBucket", "NoSuchKey"}


class ReplicaChecksumMismatchError(RuntimeError):
    """Raised when source or copied ciphertext differs from the desired hash."""


class RegionalObjectOperationError(RuntimeError):
    """Retain which regional client failed without exposing the object key."""

    def __init__(self, *, region: str, error: Exception) -> None:
        super().__init__(type(error).__name__)
        self.region = region
        self.error = error


def _checksum_hex(value: str) -> str:
    checksum = value.removeprefix("sha256:").lower()
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        raise ValueError("Replication job checksum must be a SHA-256 hex digest")
    return checksum


def _stream_checksum(stream: Any) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(COPY_CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


def _error_code(error: Exception) -> str:
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code")
        if code:
            return str(code)[:64]
    return type(error).__name__[:64]


def _as_directus_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class RegionalStorageJobProcessor:
    """Execute durable jobs using Directus state and initialized regional clients."""

    def __init__(self, *, directus_service: Any, s3_service: Any) -> None:
        self.directus_service = directus_service
        self.s3_service = s3_service

    async def _load(self, collection: str, item_id: str) -> dict[str, Any]:
        rows = await self.directus_service.get_items(
            collection,
            params={"filter": {"id": {"_eq": item_id}}, "fields": "*", "limit": 1},
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        if not rows:
            raise RuntimeError(f"Durable storage job not found in {collection}")
        return dict(rows[0])

    async def _update(
        self,
        collection: str,
        item_id: str,
        patch: dict[str, Any],
        expected_version: int,
    ) -> None:
        updated = await self.directus_service.update_item_if_version(
            collection,
            item_id,
            {**patch, "version": expected_version + 1},
            expected_version,
            admin_required=True,
        )
        if not updated:
            raise RuntimeError(f"Durable storage job changed concurrently in {collection}")

    def _copy_immutable_object(self, job: dict[str, Any], target_region: str) -> None:
        source_region = str(job["active_region"])
        logical_bucket = str(job["logical_bucket"])
        object_key = str(job["object_key"])
        expected_checksum = _checksum_hex(str(job["checksum"]))
        legacy_bucket = get_bucket_name(logical_bucket, self.s3_service.environment)
        source_bucket = resolve_regional_bucket_name(legacy_bucket, source_region)
        target_bucket = resolve_regional_bucket_name(legacy_bucket, target_region)
        source_client = self.s3_service.region_clients[source_region]
        target_read_client = self.s3_service.region_clients[target_region]
        target_upload_client = self.s3_service.upload_region_clients[target_region]

        try:
            source_head = source_client.head_object(Bucket=source_bucket, Key=object_key)
            source_file = SpooledTemporaryFile(max_size=COPY_MEMORY_LIMIT)
            source_client.download_fileobj(source_bucket, object_key, source_file)
        except Exception as error:
            raise RegionalObjectOperationError(region=source_region, error=error) from error

        with source_file:
            source_file.seek(0)
            source_checksum = _stream_checksum(source_file)
            if not hmac.compare_digest(source_checksum, expected_checksum):
                raise ReplicaChecksumMismatchError("Active-region object checksum mismatch")

            metadata = dict(source_head.get("Metadata") or {})
            metadata["openmates-sha256"] = expected_checksum
            extra_args: dict[str, Any] = {
                "ACL": "private" if get_bucket_config(logical_bucket)["access"] == "private" else "public-read",
                "ContentType": source_head.get("ContentType") or "application/octet-stream",
                "Metadata": metadata,
            }
            if source_head.get("CacheControl"):
                extra_args["CacheControl"] = source_head["CacheControl"]
            source_file.seek(0)
            try:
                target_upload_client.upload_fileobj(
                    source_file,
                    target_bucket,
                    object_key,
                    ExtraArgs=extra_args,
                )
            except Exception as error:
                raise RegionalObjectOperationError(region=target_region, error=error) from error

        try:
            response = target_read_client.get_object(Bucket=target_bucket, Key=object_key)
        except Exception as error:
            raise RegionalObjectOperationError(region=target_region, error=error) from error
        body = response["Body"]
        try:
            target_checksum = _stream_checksum(body)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if not hmac.compare_digest(target_checksum, expected_checksum):
            raise ReplicaChecksumMismatchError("Copied object checksum mismatch")

    async def process_replication_job(self, job_id: str, expected_version: int) -> dict[str, Any]:
        job = await self._load("storage_replication_jobs", job_id)
        if int(job.get("version", 0)) != expected_version:
            return {"job_id": job_id, "state": str(job["state"]), "processed": 0}
        if job.get("state") in {"verified", "completed"}:
            return {"job_id": job_id, "state": str(job["state"]), "processed": 0}

        now = datetime.now(timezone.utc)
        processed = 0
        last_error_code: str | None = None
        for region, state in tuple(dict(job["region_states"]).items()):
            if state == "verified":
                continue
            if await self._find_deletion_tombstone(job):
                job["state"] = "cancelled"
                job["next_attempt_at"] = None
                break
            try:
                await asyncio.to_thread(self._copy_immutable_object, job, region)
                if await self._find_deletion_tombstone(job):
                    await asyncio.to_thread(
                        self._delete_immutable_object,
                        str(job["logical_bucket"]),
                        str(job["object_key"]),
                        region,
                    )
                    job["state"] = "cancelled"
                    job["next_attempt_at"] = None
                    break
                job["region_states"][region] = "verified"
                processed += 1
            except ReplicaChecksumMismatchError as error:
                last_error_code = _error_code(error)
                job["state"] = "failed"
                job["next_attempt_at"] = None
                break
            except Exception as error:
                health_region = error.region if isinstance(error, RegionalObjectOperationError) else region
                root_error = error.error if isinstance(error, RegionalObjectOperationError) else error
                last_error_code = _error_code(root_error)
                if health_region == str(job["active_region"]) and last_error_code in MISSING_SOURCE_CODES:
                    job["state"] = "source_missing"
                    job["next_attempt_at"] = None
                    break
                job = record_replica_failure(job, region=region, now=now)
                await record_persisted_region_error(
                    directus_service=self.directus_service,
                    region=health_region,
                    error_code=last_error_code,
                    now=now,
                )

        all_verified = all(state == "verified" for state in job["region_states"].values())
        if all_verified:
            job["state"] = "verified"
            job["next_attempt_at"] = None
        elif job.get("state") not in {"failed", "cancelled", "source_missing"}:
            job["state"] = "retry_scheduled"

        await self._update(
            "storage_replication_jobs",
            job_id,
            {
                "region_states": job["region_states"],
                "state": job["state"],
                "attempts": int(job.get("attempts", 0)),
                "last_error_code": last_error_code,
                "next_attempt_at": _as_directus_datetime(job.get("next_attempt_at")),
                "updated_at": now.isoformat(),
                "completed_at": now.isoformat() if all_verified else None,
            },
            expected_version,
        )
        return {"job_id": job_id, "state": str(job["state"]), "processed": processed}

    async def _find_deletion_tombstone(self, job: dict[str, Any]) -> dict[str, Any] | None:
        from backend.core.api.app.services.s3.reconciliation import find_deletion_tombstone

        return await find_deletion_tombstone(
            directus_service=self.directus_service,
            logical_bucket=str(job["logical_bucket"]),
            object_key=str(job["object_key"]),
        )

    def _delete_immutable_object(self, logical_bucket: str, object_key: str, region: str) -> None:
        legacy_bucket = get_bucket_name(logical_bucket, self.s3_service.environment)
        bucket = resolve_regional_bucket_name(legacy_bucket, region)
        self.s3_service.region_clients[region].delete_object(Bucket=bucket, Key=object_key)

    async def process_deletion_tombstone(
        self,
        tombstone_id: str,
        expected_version: int,
    ) -> dict[str, Any]:
        tombstone = await self._load("storage_deletion_tombstones", tombstone_id)
        if int(tombstone.get("version", 0)) != expected_version:
            return {"tombstone_id": tombstone_id, "state": str(tombstone["state"]), "processed": 0}
        if tombstone.get("state") == "completed":
            return {"tombstone_id": tombstone_id, "state": "completed", "processed": 0}
        if tombstone.get("state") not in {"pending", "retry_scheduled"}:
            return {"tombstone_id": tombstone_id, "state": str(tombstone["state"]), "processed": 0}

        now = datetime.now(timezone.utc)
        processed = 0
        last_error_code: str | None = None
        generation_keys = dict(tombstone["generation_keys"])
        for generation, region_states in tuple(dict(tombstone["purge_states"]).items()):
            object_key = str(generation_keys[generation])
            for region, state in tuple(dict(region_states).items()):
                if state == "purged":
                    continue
                try:
                    await asyncio.to_thread(
                        self._delete_immutable_object,
                        str(tombstone["logical_bucket"]),
                        object_key,
                        region,
                    )
                    tombstone = record_purge_result(
                        tombstone,
                        generation=generation,
                        region=region,
                        success=True,
                        now=now,
                    )
                    processed += 1
                except Exception as error:
                    last_error_code = _error_code(error)
                    already_missing = last_error_code in MISSING_SOURCE_CODES
                    tombstone = record_purge_result(
                        tombstone,
                        generation=generation,
                        region=region,
                        success=already_missing,
                        now=now,
                    )
                    if already_missing:
                        processed += 1

        completed = tombstone["state"] == "completed"
        if not completed:
            tombstone["state"] = "retry_scheduled"
        await self._update(
            "storage_deletion_tombstones",
            tombstone_id,
            {
                "purge_states": tombstone["purge_states"],
                "state": tombstone["state"],
                "attempts": int(tombstone.get("attempts", 0)),
                "last_error_code": last_error_code,
                "next_attempt_at": None if completed else _as_directus_datetime(tombstone.get("next_attempt_at")),
                "updated_at": now.isoformat(),
                "completed_at": now.isoformat() if completed else None,
            },
            expected_version,
        )
        return {
            "tombstone_id": tombstone_id,
            "state": str(tombstone["state"]),
            "processed": processed,
        }
