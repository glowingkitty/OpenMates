"""Deterministic admission reducer for host-owned disposable test runtimes.

The engineering coordinator persists one document per host and serializes every
transition with a database row lock. Only its trusted host broker supplies usage
observations; task callers cannot attest capacity, cleanup or enforcement.
Current usage is already reflected in host availability, so reservations cover
only unwritten/unconsumed growth. See the Codex runtime isolation Plan.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

GIB = 1024**3
DISK_FLOOR = 30 * GIB
CHARGED_STATES = frozenset(
    {"admitted", "provisioning", "ready", "testing", "releasing", "retained"}
)
REQUEST_FIELDS = frozenset(
    {"key", "owner", "memory_limit", "disk_limits", "source", "profile"}
)


def _bytes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Resource measurements must be non-negative integer bytes")
    return value


def _disks(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise ValueError("Filesystem measurements must be a non-empty mapping")
    if not all(isinstance(key, str) and key for key in value):
        raise ValueError("Filesystem identity is required")
    return {key: _bytes(size) for key, size in value.items()}


def empty_state() -> dict:
    return {"version": 1, "requests": []}


def _get(state: dict, key: str, owner: str | None = None) -> dict:
    row = next((row for row in state["requests"] if row["key"] == key), None)
    if row is None:
        raise ValueError("Unknown runtime request")
    if owner is not None and row["owner"] != owner:
        raise ValueError("Runtime request owner mismatch")
    return row


def enqueue(state: dict, request: dict) -> dict:
    """Idempotency binds all source/profile/budget inputs, including ownership."""
    if set(request) != REQUEST_FIELDS:
        raise ValueError("Invalid runtime request fields")
    for field in ("key", "owner", "source", "profile"):
        if (
            not isinstance(request[field], str)
            or not request[field]
            or len(request[field]) > 256
        ):
            raise ValueError("Invalid runtime request identity")
    if _bytes(request["memory_limit"]) == 0:
        raise ValueError("Memory limit must be positive")
    if not all(_disks(request["disk_limits"]).values()):
        raise ValueError("Disk limits must be positive")
    existing = next((r for r in state["requests"] if r["key"] == request["key"]), None)
    if existing:
        if any(existing[k] != request[k] for k in REQUEST_FIELDS):
            raise ValueError("Runtime request identity cannot change on retry")
        return deepcopy(existing)
    row = deepcopy(request)
    row.update(
        state="queued",
        reason="capacity_not_checked",
        memory_used=0,
        disk_used={key: 0 for key in request["disk_limits"]},
        live=False,
        observed=False,
        evidence_saved=False,
    )
    state["requests"].append(row)
    return deepcopy(row)


def outstanding(state: dict) -> dict:
    memory = 0
    disk: dict[str, int] = {}
    for row in state["requests"]:
        if row["state"] not in CHARGED_STATES:
            continue
        stopped = (
            row["observed"]
            and not row["live"]
            and row["state"] in {"retained", "releasing"}
        )
        if not stopped:
            memory += max(0, row["memory_limit"] - row["memory_used"])
        for filesystem, limit in row["disk_limits"].items():
            growth = 0 if stopped else max(0, limit - row["disk_used"][filesystem])
            disk[filesystem] = disk.get(filesystem, 0) + growth
    return {"memory": memory, "disk": disk}


def reconcile(state: dict, host: dict) -> dict:
    """Admit FIFO under the caller's host transaction; never reclaim live work."""
    available = _bytes(host["memory_available"])
    total = _bytes(host["memory_total"])
    floor = _bytes(host["memory_floor"]) + _bytes(host["build_memory"])
    disks = _disks(host["disk_available"])
    totals = _disks(host["disk_total"])
    builds = _disks(host["build_disk"])
    maximum = _bytes(host["max_environments"])
    if (
        maximum < 1
        or available > total
        or any(k not in totals or v > totals[k] for k, v in disks.items())
    ):
        raise ValueError("Invalid host capacity or concurrency configuration")
    if set(builds) != set(disks) or set(totals) != set(disks):
        raise ValueError(
            "All capacity filesystems must have build and total measurements"
        )
    enforcement = host.get("enforcement_verified") is True
    waiting_ahead = False
    for row in state["requests"]:
        if row["state"] != "queued":
            continue
        if not enforcement:
            row["reason"] = "enforcement_unverified"
            continue
        if row["memory_limit"] + floor > total:
            row.update(state="blocked", reason="profile_cannot_fit_memory")
            continue
        if any(
            k not in totals or size + builds.get(k, 0) + DISK_FLOOR > totals.get(k, 0)
            for k, size in row["disk_limits"].items()
        ):
            row.update(state="blocked", reason="profile_cannot_fit_disk")
            continue
        used = outstanding(state)
        active = sum(
            r["state"] in CHARGED_STATES and r["state"] != "retained"
            for r in state["requests"]
        )
        if waiting_ahead:
            reason = "earlier_request"
        elif active >= maximum:
            reason = "environment_slots"
        elif available - used["memory"] - row["memory_limit"] < floor:
            reason = "memory"
        elif any(
            disks[k] - used["disk"].get(k, 0) - row["disk_limits"].get(k, 0) - builds[k]
            < DISK_FLOOR
            for k in disks
        ):
            reason = "disk_reserve"
        else:
            row.update(state="admitted", reason="capacity_reserved")
            continue
        row["reason"] = reason
        waiting_ahead = True
    return deepcopy(state)


def observe(
    state: dict, key: str, *, memory_used: int, disk_used: dict, live: bool
) -> None:
    """Trusted broker observation; absence of a heartbeat is not an observation."""
    row = _get(state, key)
    if row["state"] not in CHARGED_STATES:
        raise ValueError("Cannot observe an unallocated request")
    memory = _bytes(memory_used)
    disks = _disks(disk_used)
    if set(disks) != set(row["disk_limits"]) or not isinstance(live, bool):
        raise ValueError("Incomplete runtime observation")
    if not live and memory:
        raise ValueError("Stopped runtime cannot report allocated memory")
    if memory > row["memory_limit"] or any(
        v > row["disk_limits"][k] for k, v in disks.items()
    ):
        raise ValueError("Enforced runtime budget exceeded; suspend host admission")
    row.update(memory_used=memory, disk_used=disks, live=live, observed=True)


def retain(state: dict, key: str, *, owner: str, evidence_saved: bool) -> None:
    row = _get(state, key, owner)
    if row["state"] not in CHARGED_STATES or not row["observed"] or row["live"]:
        raise ValueError("Cannot retain an unobserved or live runtime")
    if evidence_saved is not True:
        raise ValueError("Evidence must be saved before retention")
    row.update(state="retained", evidence_saved=True, reason="failure_data_retained")


def release(
    state: dict, key: str, *, owner: str, evidence_saved: bool, removed: bool
) -> None:
    row = _get(state, key, owner)
    if row["state"] == "released":
        return
    if row["state"] not in CHARGED_STATES or not row["observed"] or row["live"]:
        raise ValueError("Cannot release an unobserved or live runtime")
    if evidence_saved is not True or not isinstance(removed, bool):
        raise ValueError("Verified evidence and cleanup result required")
    row.update(
        state="released" if removed else "releasing",
        evidence_saved=True,
        reason="cleanup_verified" if removed else "cleanup_incomplete",
    )
