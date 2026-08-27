"""Bounded recovery-aware regional S3 backfill policy.

The recovered source region is the only byte authority for historical repair.
This module verifies its object stream before persisting normal replication
outbox rows, so existing workers also reconcile incident-era secondary writes.
It intentionally exposes aggregate progress only and owns no route or worker.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import hmac
import logging
from typing import Any

from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.s3.reconciliation import find_deletion_tombstone
from backend.core.api.app.services.s3.replication import build_replication_job, persist_replication_job
from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name


SHA256_METADATA_KEY = "openmates-sha256"
COPY_CHUNK_SIZE = 1024 * 1024
ACTIVE_REPLICATION_STATES = ("pending", "retry_scheduled", "failed", "source_missing")
PENDING_TOMBSTONE_STATES = ("pending", "retry_scheduled")
READINESS_PAGE_SIZE = 100
logger = logging.getLogger(__name__)


def _provider_error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return None
    provider_error = response.get("Error")
    if not isinstance(provider_error, dict):
        return None
    code = provider_error.get("Code")
    return str(code) if code is not None else None


def sha256_hex(value: bytes) -> str:
    """Return the canonical digest used by regional replication jobs."""
    return hashlib.sha256(value).hexdigest()


def _normalise_checksum(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    checksum = value.removeprefix("sha256:").lower()
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        return None
    return checksum


def _stream_sha256(body: Any) -> str:
    digest = hashlib.sha256()
    try:
        while chunk := body.read(COPY_CHUNK_SIZE):
            digest.update(chunk)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    return digest.hexdigest()


def _read_source_checksum(client: Any, bucket: str, object_key: str) -> tuple[str, str | None]:
    head = client.head_object(Bucket=bucket, Key=object_key)
    metadata = dict(head.get("Metadata") or {})
    metadata_checksum = _normalise_checksum(metadata.get(SHA256_METADATA_KEY))
    if metadata_checksum:
        return metadata_checksum, metadata_checksum
    response = client.get_object(Bucket=bucket, Key=object_key)
    computed = _stream_sha256(response["Body"])
    return computed, metadata_checksum


def _target_matches(client: Any, bucket: str, object_key: str, checksum: str) -> bool:
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
        actual = _stream_sha256(response["Body"])
    except Exception as error:
        if _provider_error_code(error) in {"404", "NoSuchKey"}:
            return False
        raise
    return hmac.compare_digest(actual, checksum)


async def _classify_existing_authority(
    directus_service: Any,
    reference: dict[str, Any],
) -> str:
    rows = await directus_service.get_items(
        "storage_replication_jobs",
        params={
            "filter": {
                "logical_bucket": {"_eq": str(reference["logical_bucket"])},
                "object_key": {"_eq": str(reference["object_key"])},
            },
            "fields": "generation,checksum,active_region",
            "limit": 100,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    generation = int(reference["generation"])
    expected = _normalise_checksum(reference.get("checksum"))
    matching_generation_exists = False
    for row in rows or []:
        existing_generation = int(row.get("generation", 0))
        existing_checksum = _normalise_checksum(row.get("checksum"))
        if existing_generation > generation:
            return "blocked"
        if existing_generation == generation and expected and existing_checksum and existing_checksum != expected:
            return "blocked"
        if existing_generation == generation and expected and existing_checksum == expected:
            matching_generation_exists = True
    return "matching" if matching_generation_exists else "clear"


async def backfill_recovered_page(
    *,
    references: list[dict[str, Any]],
    source_region: str,
    configured_regions: tuple[str, ...],
    s3_clients: dict[str, Any],
    directus_service: Any,
    environment: str,
    now: datetime,
    next_cursor: str | None = None,
) -> dict[str, int | str | bool | None]:
    """Schedule repairs for one authoritative reference page after source recovery."""
    if not references:
        return {
            "processed": 0,
            "scheduled": 0,
            "skipped_tombstoned": 0,
            "skipped_unavailable_source": 0,
            "skipped_source_checksum_mismatch": 0,
            "skipped_newer_authority": 0,
            "cursor": None,
            "complete": True,
        }
    if source_region not in configured_regions or source_region not in s3_clients:
        raise ValueError("Recovered source region must be configured and available")

    counts: dict[str, int] = {
        "processed": 0,
        "scheduled": 0,
        "skipped_tombstoned": 0,
        "skipped_unavailable_source": 0,
        "skipped_source_checksum_mismatch": 0,
        "skipped_newer_authority": 0,
    }
    source_client = s3_clients[source_region]
    for reference in references:
        counts["processed"] += 1
        logical_bucket = str(reference["logical_bucket"])
        object_key = str(reference["object_key"])
        generation = int(reference["generation"])
        if generation <= 0:
            raise ValueError("Backfill generation must be positive")
        if await find_deletion_tombstone(
            directus_service=directus_service,
            logical_bucket=logical_bucket,
            object_key=object_key,
        ):
            counts["skipped_tombstoned"] += 1
            continue
        authority_state = await _classify_existing_authority(directus_service, reference)
        if authority_state == "blocked":
            counts["skipped_newer_authority"] += 1
            continue
        if authority_state == "matching":
            counts["scheduled"] += 1
            continue

        legacy_bucket = get_bucket_name(logical_bucket, environment)
        source_bucket = resolve_regional_bucket_name(legacy_bucket, source_region)
        try:
            computed_checksum, metadata_checksum = await asyncio.to_thread(
                _read_source_checksum, source_client, source_bucket, object_key
            )
        except Exception as error:
            logger.warning(
                "Recovered source object could not be verified: region=%s logical_bucket=%s error=%s",
                source_region,
                logical_bucket,
                type(error).__name__,
            )
            counts["skipped_unavailable_source"] += 1
            continue
        expected_checksum = _normalise_checksum(reference.get("checksum")) or computed_checksum
        if not hmac.compare_digest(computed_checksum, expected_checksum) or (
            metadata_checksum is not None and not hmac.compare_digest(metadata_checksum, expected_checksum)
        ):
            counts["skipped_source_checksum_mismatch"] += 1
            continue

        job = build_replication_job(
            logical_bucket=logical_bucket,
            object_key=object_key,
            generation=generation,
            checksum=expected_checksum,
            active_region=source_region,
            configured_regions=configured_regions,
            now=now,
        )
        for region in configured_regions:
            if region == source_region:
                continue
            target_bucket = resolve_regional_bucket_name(legacy_bucket, region)
            if await asyncio.to_thread(
                _target_matches, s3_clients[region], target_bucket, object_key, expected_checksum
            ):
                job["region_states"][region] = "verified"
        if all(state == "verified" for state in job["region_states"].values()):
            continue
        await persist_replication_job(directus_service=directus_service, job=job)
        counts["scheduled"] += 1

    return {**counts, "cursor": next_cursor, "complete": next_cursor is None}


async def is_region_failback_ready(
    *,
    directus_service: Any,
    region: str,
    historical_backfill_complete: bool,
) -> bool:
    """Require healthy recovery and no remaining durable reconciliation fences."""
    if not historical_backfill_complete:
        return False
    health_rows = await directus_service.get_items(
        "storage_region_health",
        params={"filter": {"region": {"_eq": region}}, "fields": "probe_succeeded", "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not health_rows or not bool(health_rows[0].get("probe_succeeded")):
        return False
    cursor: str | None = None
    while True:
        filters: dict[str, Any] = {"state": {"_in": list(ACTIVE_REPLICATION_STATES)}}
        if cursor:
            filters["id"] = {"_gt": cursor}
        jobs = await directus_service.get_items(
            "storage_replication_jobs",
            params={
                "filter": filters,
                "fields": "id,state,desired_regions,region_states,next_attempt_at",
                "sort": "id",
                "limit": READINESS_PAGE_SIZE,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        ) or []
        if any(
            region in row.get("desired_regions", [])
            and dict(row.get("region_states") or {}).get(region) != "verified"
            for row in jobs
        ):
            return False
        if len(jobs) < READINESS_PAGE_SIZE:
            break
        cursor = str(jobs[-1].get("id") or "")
        if not cursor:
            raise RuntimeError("Cannot paginate regional replication readiness")

    cursor = None
    while True:
        filters = {"state": {"_in": list(PENDING_TOMBSTONE_STATES)}}
        if cursor:
            filters["id"] = {"_gt": cursor}
        tombstones = await directus_service.get_items(
            "storage_deletion_tombstones",
            params={
                "filter": filters,
                "fields": "id,state,purge_states",
                "sort": "id",
                "limit": READINESS_PAGE_SIZE,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        ) or []
        if any(
            state != "purged"
            for tombstone in tombstones
            for states in dict(tombstone.get("purge_states") or {}).values()
            for target, state in dict(states).items()
            if target == region
        ):
            return False
        if len(tombstones) < READINESS_PAGE_SIZE:
            return True
        cursor = str(tombstones[-1].get("id") or "")
        if not cursor:
            raise RuntimeError("Cannot paginate regional deletion readiness")


async def persist_region_reconciliation_state(
    *,
    directus_service: Any,
    region: str,
    historical_backfill_complete: bool,
    now: datetime,
) -> bool:
    """Persist the failback fence after evaluating all durable recovery work."""
    ready = await is_region_failback_ready(
        directus_service=directus_service,
        region=region,
        historical_backfill_complete=historical_backfill_complete,
    )
    rows = await directus_service.get_items(
        "storage_region_health",
        params={"filter": {"region": {"_eq": region}}, "fields": "id,reconciled", "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if not rows:
        return False
    row = rows[0]
    if bool(row.get("reconciled")) == ready:
        return ready
    updated = await directus_service.update_item(
        "storage_region_health",
        str(row["id"]),
        {"reconciled": ready, "updated_at": now.isoformat()},
        admin_required=True,
    )
    if not updated:
        raise RuntimeError("Failed to persist regional reconciliation state")
    return ready
