"""Pure regional replica reconciliation and deletion-tombstone policies.

The planner emits bounded repair actions from verified checksums and treats
tombstones and ambiguity as hard safety fences. Persistence and S3 adapters are
implemented separately so this policy remains deterministic and testable.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from typing import Any


PURGE_RETRY_DELAY = timedelta(minutes=5)


def plan_replica_reconciliation(
    *,
    desired: dict[int, dict],
    observed: dict[tuple[int, str], str],
    tombstoned_generations: set[int],
    ambiguous_generations: set[int],
) -> dict:
    """Classify desired generations and copy only from checksum-verified sources."""
    classifications: Counter[str] = Counter()
    copy_actions = []

    for generation, policy in sorted(desired.items()):
        if generation in tombstoned_generations:
            classifications["pending_delete"] += 1
            continue
        if generation in ambiguous_generations:
            classifications["ambiguous"] += 1
            continue

        checksum = str(policy["checksum"])
        regions = tuple(policy["regions"])
        verified_sources = [
            region for region in regions
            if observed.get((generation, region)) == checksum
        ]
        for region in regions:
            current = observed.get((generation, region))
            if current is None:
                classifications["missing"] += 1
                if verified_sources:
                    copy_actions.append({
                        "generation": generation,
                        "source_region": verified_sources[0],
                        "target_region": region,
                    })
            elif current != checksum:
                classifications["mismatched"] += 1

    return {
        "classifications": dict(classifications),
        "copy_actions": copy_actions,
        "delete_actions": [],
    }


def build_deletion_tombstone(
    *,
    logical_bucket: str,
    object_key: str,
    generations: tuple[int, ...],
    generation_keys: dict[int, str],
    regions: tuple[str, ...],
    surviving_reference_count: int,
    now: datetime,
) -> dict:
    """Create an authoritative immediate read fence and regional purge plan."""
    if surviving_reference_count:
        raise ValueError("Cannot purge storage object with surviving references")
    if not generations or not regions:
        raise ValueError("Tombstone requires generations and regions")
    if set(generation_keys) != set(generations) or not all(generation_keys.values()):
        raise ValueError("Tombstone requires one immutable object key per generation")
    identity = hashlib.sha256(f"{logical_bucket}\0{object_key}".encode()).hexdigest()
    return {
        "idempotency_key": identity,
        "logical_bucket": logical_bucket,
        "object_key": object_key,
        "generations": tuple(generations),
        "generation_keys": dict(generation_keys),
        "purge_states": {
            generation: {region: "pending" for region in regions}
            for generation in generations
        },
        "state": "pending",
        "version": 1,
        "attempts": 0,
        "next_attempt_at": now,
        "created_at": now,
        "updated_at": now,
    }


async def persist_deletion_tombstone(
    *,
    directus_service: Any,
    tombstone: dict[str, Any],
) -> dict[str, Any]:
    """Insert one authoritative tombstone, returning it on duplicate delivery."""
    payload = dict(tombstone)
    payload["generations"] = list(payload["generations"])
    for field in ("created_at", "updated_at", "next_attempt_at"):
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = value.isoformat()
    success, created = await directus_service.create_item(
        "storage_deletion_tombstones",
        payload,
        admin_required=True,
    )
    if success and created:
        return dict(created)
    rows = await directus_service.get_items(
        "storage_deletion_tombstones",
        params={
            "filter": {"idempotency_key": {"_eq": str(tombstone["idempotency_key"])}},
            "fields": "*",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if rows:
        return dict(rows[0])
    raise RuntimeError("Failed to persist regional deletion tombstone")


async def find_deletion_tombstone(
    *,
    directus_service: Any,
    logical_bucket: str,
    object_key: str,
) -> dict[str, Any] | None:
    """Return durable deletion authority for one logical object, if present."""
    rows = await directus_service.get_items(
        "storage_deletion_tombstones",
        params={
            "filter": {
                "logical_bucket": {"_eq": logical_bucket},
                "object_key": {"_eq": object_key},
                "state": {"_neq": "cancelled"},
            },
            "fields": "id,state,version",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    return dict(rows[0]) if rows else None


def can_read_generation(tombstone: dict, generation: int) -> bool:
    return generation not in tombstone["generations"]


def should_repair_generation(tombstone: dict, generation: int) -> bool:
    return generation not in tombstone["generations"]


def record_purge_result(
    tombstone: dict,
    *,
    generation: int,
    region: str,
    success: bool,
    now: datetime,
) -> dict:
    """Record one regional purge result while retaining failed work."""
    updated = deepcopy(tombstone)
    states = updated["purge_states"].get(generation)
    if states is None or region not in states:
        raise ValueError("Unknown tombstone generation or region")
    states[region] = "purged" if success else "pending"
    if not success:
        updated["attempts"] = int(updated.get("attempts", 0)) + 1
        updated["next_attempt_at"] = now + PURGE_RETRY_DELAY
    if all(value == "purged" for generation_states in updated["purge_states"].values() for value in generation_states.values()):
        updated["state"] = "completed"
    return updated
