"""Durable coordination semantics for parallel engineering sessions.

The in-memory implementation is a deterministic reference adapter for unit
tests. Production PostgreSQL operations must preserve the same atomic lease,
dispatch-idempotency, runtime-epoch, canary, and event-cursor invariants.
No product data or credentials are accepted by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from threading import RLock
from typing import Any, Iterable, Mapping


ACTIVE_DISPATCH_STATUSES = frozenset({"pending_canary", "queued", "running", "succeeded"})
FORBIDDEN_EVENT_FIELDS = frozenset(
    {
        "api_key",
        "content",
        "cookie",
        "credentials",
        "email",
        "password",
        "product_content",
        "secret",
        "token",
        "user_id",
    }
)


class LeaseConflict(RuntimeError):
    """Raised when requested resources overlap an active exclusive lease."""


class LeaseMode(StrEnum):
    """Compatibility mode for a resource lease."""

    SHARED = "shared"
    EXCLUSIVE = "exclusive"


class SessionEventType(StrEnum):
    """Allowlisted event kinds understood by coordination clients."""

    DISPATCH_CHANGED = "dispatch.changed"
    LEASE_CHANGED = "lease.changed"
    RUNTIME_CHANGED = "runtime.changed"
    TASK_CHANGED = "task.changed"


@dataclass(frozen=True, slots=True)
class DispatchSpec:
    repository: str
    commit: str
    tests: tuple[str, ...]
    profile: str
    account: str
    mocks: tuple[tuple[str, str], ...]
    required_services: tuple[str, ...]
    runtime_epoch: int

    @classmethod
    def create(
        cls,
        *,
        repository: str,
        commit: str,
        tests: Iterable[str],
        profile: str,
        account: str,
        mocks: Mapping[str, str],
        required_services: Iterable[str],
        runtime_epoch: int,
    ) -> DispatchSpec:
        """Normalize every execution-affecting input before fingerprinting."""
        if runtime_epoch < 0:
            raise ValueError("runtime_epoch must be non-negative")
        return cls(
            repository=repository.strip(),
            commit=commit.strip(),
            tests=tuple(sorted({value.strip() for value in tests if value.strip()})),
            profile=profile.strip(),
            account=account.strip(),
            mocks=tuple(sorted((str(key).strip(), str(value).strip()) for key, value in mocks.items())),
            required_services=tuple(sorted({value.strip() for value in required_services if value.strip()})),
            runtime_epoch=runtime_epoch,
        )

    @property
    def fingerprint(self) -> str:
        payload = {
            "account": self.account,
            "commit": self.commit,
            "mocks": self.mocks,
            "profile": self.profile,
            "repository": self.repository,
            "required_services": self.required_services,
            "runtime_epoch": self.runtime_epoch,
            "tests": self.tests,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class ResourceLease:
    lease_key: str
    owner: str
    resources: frozenset[str]
    expires_at: datetime
    mode: LeaseMode = LeaseMode.EXCLUSIVE
    status: str = "active"


@dataclass(slots=True)
class RuntimeOperation:
    operation_key: str
    requested_by: str
    resources: frozenset[str]
    requested_at: datetime
    status: str
    completed_at: datetime | None = None


@dataclass(slots=True)
class DispatchRequest:
    dispatch_key: str
    fingerprint: str
    spec: DispatchSpec
    requested_by: str
    requested_at: datetime
    status: str
    reason: str | None = None
    canaries: dict[str, bool] = field(default_factory=dict)


@dataclass(slots=True)
class SessionEvent:
    event_key: str
    cursor: int
    event_type: SessionEventType
    target_type: str
    target_key: str
    subject_key: str
    payload: dict[str, Any]
    created_at: datetime
    acknowledged_by: set[str] = field(default_factory=set)


def _validate_event_payload(payload: Mapping[str, Any]) -> None:
    pending: list[Mapping[str, Any]] = [payload]
    while pending:
        current = pending.pop()
        for key, value in current.items():
            if str(key).lower() in FORBIDDEN_EVENT_FIELDS:
                raise ValueError(f"forbidden event payload field: {key}")
            if isinstance(value, Mapping):
                pending.append(value)


class InMemoryCoordinationStore:
    """Thread-safe reference implementation of the coordination contract."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._leases: dict[str, ResourceLease] = {}
        self._operations: dict[str, RuntimeOperation] = {}
        self._dispatches: dict[str, DispatchRequest] = {}
        self._events: dict[str, SessionEvent] = {}
        self._cursor = 0
        self._runtime_epoch = 0

    @property
    def runtime_epoch(self) -> int:
        with self._lock:
            return self._runtime_epoch

    def advance_runtime_epoch(self) -> int:
        with self._lock:
            self._runtime_epoch += 1
            return self._runtime_epoch

    def acquire_lease(
        self,
        *,
        lease_key: str,
        owner: str,
        resources: set[str],
        expires_at: datetime,
        now: datetime,
        mode: LeaseMode = LeaseMode.EXCLUSIVE,
    ) -> ResourceLease:
        if not resources:
            raise ValueError("resources must not be empty")
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")
        normalized = frozenset(resources)
        with self._lock:
            self._expire_leases(now)
            existing = self._leases.get(lease_key)
            if existing and existing.status == "active":
                if existing.owner == owner and existing.resources == normalized and existing.mode == mode:
                    existing.expires_at = expires_at
                    return existing
                raise LeaseConflict(f"lease key already active: {lease_key}")
            for lease in self._leases.values():
                if (
                    lease.status == "active"
                    and lease.resources & normalized
                    and (lease.mode == LeaseMode.EXCLUSIVE or mode == LeaseMode.EXCLUSIVE)
                ):
                    overlap = ",".join(sorted(lease.resources & normalized))
                    raise LeaseConflict(f"resources already leased: {overlap}")
            lease = ResourceLease(lease_key, owner, normalized, expires_at, mode)
            self._leases[lease_key] = lease
            return lease

    def release_lease(self, lease_key: str, *, now: datetime) -> bool:
        with self._lock:
            lease = self._leases.get(lease_key)
            if lease is None or lease.status != "active":
                return False
            lease.status = "released"
            self._admit_queued_operations(now)
            return True

    def request_runtime_operation(
        self,
        *,
        operation_key: str,
        requested_by: str,
        resources: set[str],
        now: datetime,
    ) -> RuntimeOperation:
        if not resources:
            raise ValueError("resources must not be empty")
        with self._lock:
            existing = self._operations.get(operation_key)
            if existing is not None:
                return existing
            self._expire_leases(now)
            normalized = frozenset(resources)
            blocked_by_lease = any(
                lease.status == "active" and bool(lease.resources & normalized) for lease in self._leases.values()
            )
            blocked_by_operation = any(
                operation.status in {"queued", "admitted", "draining_tests", "restarting", "verifying"}
                and bool(operation.resources & normalized)
                for operation in self._operations.values()
            )
            operation = RuntimeOperation(
                operation_key=operation_key,
                requested_by=requested_by,
                resources=normalized,
                requested_at=now,
                status="queued" if blocked_by_lease or blocked_by_operation else "admitted",
            )
            self._operations[operation_key] = operation
            return operation

    def get_runtime_operation(self, operation_key: str) -> RuntimeOperation:
        with self._lock:
            return self._operations[operation_key]

    def poll_runtime_operation(self, operation_key: str, *, now: datetime) -> RuntimeOperation:
        """Reconcile expiry and queue admission while a client waits."""
        with self._lock:
            self._admit_queued_operations(now)
            return self._operations[operation_key]

    def runtime_operation_blockers(self, operation_key: str, *, now: datetime) -> dict[str, list[object]]:
        with self._lock:
            self._admit_queued_operations(now)
            operation = self._operations[operation_key]
            leases = [
                lease
                for lease in self._leases.values()
                if lease.status == "active" and bool(lease.resources & operation.resources)
            ]
            operations = [
                other
                for other in self._operations.values()
                if other.operation_key != operation.operation_key
                and bool(other.resources & operation.resources)
                and (
                    other.status in {"admitted", "draining_tests", "restarting", "verifying"}
                    or (
                        other.status == "queued"
                        and (other.requested_at, other.operation_key) < (operation.requested_at, operation.operation_key)
                    )
                )
            ]
            return {"leases": leases, "operations": operations}

    def complete_runtime_operation(self, operation_key: str, *, now: datetime) -> RuntimeOperation:
        with self._lock:
            operation = self._operations[operation_key]
            if operation.status != "admitted":
                raise RuntimeError(f"operation is not admitted: {operation_key}")
            operation.status = "completed"
            operation.completed_at = now
            self._runtime_epoch += 1
            self._admit_queued_operations(now)
            return operation

    def request_dispatch(
        self,
        spec: DispatchSpec,
        *,
        requested_by: str,
        now: datetime,
    ) -> tuple[DispatchRequest, bool]:
        with self._lock:
            matches = [
                request
                for request in self._dispatches.values()
                if request.fingerprint == spec.fingerprint and request.status in ACTIVE_DISPATCH_STATUSES
            ]
            if matches:
                return min(matches, key=lambda item: item.requested_at), True
            attempt = 1 + sum(request.fingerprint == spec.fingerprint for request in self._dispatches.values())
            dispatch_key = f"{spec.fingerprint[:24]}-{attempt}"
            status = "pending_canary" if spec.required_services else "queued"
            request = DispatchRequest(
                dispatch_key=dispatch_key,
                fingerprint=spec.fingerprint,
                spec=spec,
                requested_by=requested_by,
                requested_at=now,
                status=status,
            )
            self._dispatches[dispatch_key] = request
            return request, False

    def get_dispatch(self, dispatch_key: str) -> DispatchRequest:
        with self._lock:
            return self._dispatches[dispatch_key]

    def record_canary(self, dispatch_key: str, service: str, *, healthy: bool, now: datetime) -> DispatchRequest:
        del now
        with self._lock:
            request = self._dispatches[dispatch_key]
            if service not in request.spec.required_services:
                raise ValueError(f"undeclared required service: {service}")
            if request.status not in {"pending_canary", "prevented"}:
                return request
            request.canaries[service] = healthy
            if not healthy:
                request.status = "prevented"
                request.reason = f"required_service_unhealthy:{service}"
            elif all(request.canaries.get(item) is True for item in request.spec.required_services):
                request.status = "queued"
                request.reason = None
            return request

    def complete_dispatch(self, dispatch_key: str, *, succeeded: bool, now: datetime) -> DispatchRequest:
        del now
        with self._lock:
            request = self._dispatches[dispatch_key]
            if request.status not in {"queued", "running"}:
                raise RuntimeError(f"dispatch cannot complete from {request.status}")
            request.status = "succeeded" if succeeded else "failed"
            return request

    def publish_event(
        self,
        *,
        event_type: SessionEventType,
        target_type: str,
        target_key: str,
        subject_key: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> SessionEvent:
        _validate_event_payload(payload)
        if target_type not in {"session", "task", "dispatch", "lease", "runtime_operation"}:
            raise ValueError(f"unsupported event target type: {target_type}")
        with self._lock:
            self._cursor += 1
            event = SessionEvent(
                event_key=f"event-{self._cursor}",
                cursor=self._cursor,
                event_type=event_type,
                target_type=target_type,
                target_key=target_key,
                subject_key=subject_key,
                payload=dict(payload),
                created_at=now,
            )
            self._events[event.event_key] = event
            return event

    def read_events(self, target_type: str, target_key: str, *, after_cursor: int = 0) -> list[SessionEvent]:
        with self._lock:
            return [
                event
                for event in self._events.values()
                if event.cursor > after_cursor and event.target_type == target_type and event.target_key == target_key
            ]

    def acknowledge_event(self, event_key: str, *, recipient: str, now: datetime) -> bool:
        del now
        with self._lock:
            event = self._events[event_key]
            if recipient in event.acknowledged_by:
                return False
            event.acknowledged_by.add(recipient)
            return True

    def _expire_leases(self, now: datetime) -> None:
        for lease in self._leases.values():
            if lease.status == "active" and lease.expires_at <= now:
                lease.status = "expired"

    def _admit_queued_operations(self, now: datetime) -> None:
        self._expire_leases(now)
        for operation in sorted(self._operations.values(), key=lambda item: (item.requested_at, item.operation_key)):
            if operation.status != "queued":
                continue
            blocked_by_lease = any(
                lease.status == "active" and bool(lease.resources & operation.resources)
                for lease in self._leases.values()
            )
            blocked_by_operation = any(
                other.operation_key != operation.operation_key
                and other.status in {"queued", "admitted", "draining_tests", "restarting", "verifying"}
                and bool(other.resources & operation.resources)
                and (other.status != "queued" or (other.requested_at, other.operation_key) < (operation.requested_at, operation.operation_key))
                for other in self._operations.values()
            )
            if not blocked_by_lease and not blocked_by_operation:
                operation.status = "admitted"
