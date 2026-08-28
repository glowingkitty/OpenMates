"""Pure regional replication job and health-state policies.

Directus and Celery adapters persist and deliver these values; this module owns
deterministic generation identity, bounded retry timing, circuit transitions,
and failback fencing without performing network or database operations.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from typing import Any, Callable

from backend.shared.python_utils.object_storage_regions import (
    RETRYABLE_STORAGE_ERROR_CODES,
    is_retryable_storage_error,
)


MAX_RETRY_DELAY = timedelta(hours=1)
BASE_RETRY_DELAY = timedelta(seconds=30)
RETRYABLE_ERROR_CODES = set(RETRYABLE_STORAGE_ERROR_CODES)
MISSING_OBJECT_CODES = {"404", "NoSuchBucket", "NoSuchKey"}
DEFAULT_STORAGE_SWEEP_LIMIT = 100
_DUE_STATES = ("pending", "retry_scheduled")
DEFAULT_REGION_FAILURE_THRESHOLD = 3
DEFAULT_REGION_COOLDOWN = timedelta(minutes=5)


def _job_identity(logical_bucket: str, object_key: str, generation: int) -> str:
    value = f"{logical_bucket}\0{object_key}\0{generation}".encode()
    return hashlib.sha256(value).hexdigest()


def build_replication_job(
    *,
    logical_bucket: str,
    object_key: str,
    generation: int,
    checksum: str,
    active_region: str,
    configured_regions: tuple[str, ...],
    now: datetime,
) -> dict:
    """Build one idempotent desired-generation job after active write success."""
    if generation <= 0:
        raise ValueError("Object generation must be a positive integer")
    if active_region not in configured_regions:
        raise ValueError("Active region must be configured")
    return {
        "idempotency_key": _job_identity(logical_bucket, object_key, generation),
        "logical_bucket": logical_bucket,
        "object_key": object_key,
        "generation": generation,
        "checksum": checksum,
        "active_region": active_region,
        "desired_regions": list(configured_regions),
        "region_states": {
            region: "verified" if region == active_region else "pending"
            for region in configured_regions
        },
        "state": "pending" if len(configured_regions) > 1 else "verified",
        "version": 1,
        "attempts": 0,
        "next_attempt_at": now,
        "created_at": now,
        "updated_at": now,
    }


async def persist_replication_job(*, directus_service: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Insert one durable generation, returning the existing row on redelivery."""
    payload = dict(job)
    for field in ("created_at", "updated_at", "next_attempt_at"):
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = value.isoformat()
    success, created = await directus_service.create_item(
        "storage_replication_jobs",
        payload,
        admin_required=True,
    )
    if success and created:
        return dict(created)

    rows = await directus_service.get_items(
        "storage_replication_jobs",
        params={
            "filter": {"idempotency_key": {"_eq": str(job["idempotency_key"])}},
            "fields": "*",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if rows:
        existing = dict(rows[0])
        if existing.get("checksum") != job.get("checksum"):
            raise RuntimeError("Immutable storage key already has a different checksum")
        return existing
    raise RuntimeError("Failed to persist regional replication job")


async def record_persisted_region_error(
    *,
    directus_service: Any,
    region: str,
    error_code: str,
    now: datetime,
) -> None:
    """Persist retryable circuit state; missing-object data remains health-neutral."""
    if error_code in MISSING_OBJECT_CODES or not is_retryable_storage_error(error_code, error_code):
        return
    rows = await directus_service.get_items(
        "storage_region_health",
        params={"filter": {"region": {"_eq": region}}, "fields": "*", "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    existing = dict(rows[0]) if rows else {}
    circuit = RegionCircuitBreaker(
        failure_threshold=DEFAULT_REGION_FAILURE_THRESHOLD,
        cooldown=DEFAULT_REGION_COOLDOWN,
    )
    state = circuit._state(region)
    state["failures"] = int(existing.get("failure_count", 0))
    open_until = existing.get("open_until")
    if isinstance(open_until, str):
        open_until = datetime.fromisoformat(open_until.replace("Z", "+00:00"))
    state["open_until"] = open_until
    state["probe_succeeded"] = bool(existing.get("probe_succeeded", False))
    state["reconciled"] = bool(existing.get("reconciled", False))
    circuit.record_error(region, error_code=error_code, now=now)
    payload = {
        "region": region,
        "failure_count": state["failures"],
        "open_until": state["open_until"].isoformat() if state["open_until"] else None,
        "probe_succeeded": state["probe_succeeded"],
        "reconciled": state["reconciled"],
        "last_error_code": error_code,
        "updated_at": now.isoformat(),
    }
    if existing.get("id"):
        updated = await directus_service.update_item_if_version(
            "storage_region_health",
            existing["id"],
            payload,
            existing.get("updated_at"),
            version_field="updated_at",
            admin_required=True,
        )
        if not updated:
            return
        return
    success, created = await directus_service.create_item(
        "storage_region_health",
        payload,
        admin_required=True,
    )
    if not success or not created:
        raise RuntimeError("Failed to create regional storage health")


async def record_persisted_region_probe_success(
    *,
    directus_service: Any,
    region: str,
    now: datetime,
) -> bool:
    """Persist a successful recovery probe after the circuit cooldown expires."""
    rows = await directus_service.get_items(
        "storage_region_health",
        params={"filter": {"region": {"_eq": region}}, "fields": "*", "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    existing = dict(rows[0]) if rows else {}
    open_until = existing.get("open_until")
    if isinstance(open_until, str):
        open_until = datetime.fromisoformat(open_until.replace("Z", "+00:00"))
    if isinstance(open_until, datetime) and now < open_until:
        return False
    payload = {
        "region": region,
        "failure_count": 0,
        "open_until": None,
        "probe_succeeded": True,
        "reconciled": bool(existing.get("reconciled", False)),
        "last_error_code": None,
        "updated_at": now.isoformat(),
    }
    if existing.get("id"):
        updated = await directus_service.update_item_if_version(
            "storage_region_health",
            existing["id"],
            payload,
            existing.get("updated_at"),
            version_field="updated_at",
            admin_required=True,
        )
        if not updated:
            return False
        return True
    success, created = await directus_service.create_item(
        "storage_region_health",
        payload,
        admin_required=True,
    )
    if not success or not created:
        raise RuntimeError("Failed to create regional storage recovery probe")
    return True


def record_replica_failure(job: dict, *, region: str, now: datetime) -> dict:
    """Persist pending replica state with deterministic bounded backoff."""
    if region not in job["region_states"]:
        raise ValueError("Replica region is not part of the desired generation")
    updated = deepcopy(job)
    updated["attempts"] = int(updated.get("attempts", 0)) + 1
    multiplier = 2 ** min(updated["attempts"] - 1, 16)
    delay = min(BASE_RETRY_DELAY * multiplier, MAX_RETRY_DELAY)
    updated["region_states"][region] = "pending"
    updated["state"] = "pending"
    updated["next_attempt_at"] = now + delay
    return updated


async def dispatch_due_storage_jobs(
    *,
    directus_service: Any,
    replication_dispatch: Callable[[str, int], Any],
    tombstone_dispatch: Callable[[str, int], Any],
    limit: int = DEFAULT_STORAGE_SWEEP_LIMIT,
) -> dict[str, int]:
    """Dispatch bounded durable work; database identities fence duplicate delivery."""
    if limit <= 0 or limit > DEFAULT_STORAGE_SWEEP_LIMIT:
        raise ValueError(f"Storage sweep limit must be between 1 and {DEFAULT_STORAGE_SWEEP_LIMIT}")

    async def due_rows(collection: str) -> list[dict[str, Any]]:
        rows = await directus_service.get_items(
            collection,
            params={
                "filter": {
                    "state": {"_in": list(_DUE_STATES)},
                    "_or": [
                        {"next_attempt_at": {"_null": True}},
                        {"next_attempt_at": {"_lte": "$NOW"}},
                    ],
                },
                "fields": "id,version",
                "sort": "created_at",
                "limit": limit,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        return rows or []

    replication_rows = await due_rows("storage_replication_jobs")
    tombstone_rows = await due_rows("storage_deletion_tombstones")
    for row in replication_rows:
        replication_dispatch(str(row["id"]), int(row["version"]))
    for row in tombstone_rows:
        tombstone_dispatch(str(row["id"]), int(row["version"]))
    return {
        "replication_dispatched": len(replication_rows),
        "tombstones_dispatched": len(tombstone_rows),
    }


class RegionCircuitBreaker:
    """Track retryable regional failures and reconciliation-gated failback."""

    def __init__(self, *, failure_threshold: int, cooldown: timedelta) -> None:
        if failure_threshold <= 0 or cooldown <= timedelta(0):
            raise ValueError("Circuit threshold and cooldown must be positive")
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._states: dict[str, dict] = {}

    def _state(self, region: str) -> dict:
        return self._states.setdefault(
            region,
            {"failures": 0, "open_until": None, "probe_succeeded": False, "reconciled": False},
        )

    def record_error(self, region: str, *, error_code: str, now: datetime) -> None:
        if error_code in MISSING_OBJECT_CODES or not is_retryable_storage_error(error_code, error_code):
            return
        state = self._state(region)
        state["failures"] += 1
        state["probe_succeeded"] = False
        state["reconciled"] = False
        if state["failures"] >= self.failure_threshold:
            state["open_until"] = now + self.cooldown

    def is_available(self, region: str, *, now: datetime) -> bool:
        open_until = self._state(region)["open_until"]
        return open_until is None or now >= open_until

    def record_probe_success(self, region: str, *, now: datetime) -> None:
        state = self._state(region)
        if state["open_until"] is not None and now >= state["open_until"]:
            state["probe_succeeded"] = True

    def mark_reconciled(self, region: str) -> None:
        self._state(region)["reconciled"] = True

    def can_fail_back(self, region: str, *, now: datetime) -> bool:
        state = self._state(region)
        return bool(
            self.is_available(region, now=now)
            and state["probe_succeeded"]
            and state["reconciled"]
        )
