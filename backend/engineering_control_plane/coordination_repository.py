"""Transactional PostgreSQL repository for shared runtime coordination.

Resource-scoped advisory locks serialize lease and operation admission. The
database remains authoritative across client/process restarts, while explicit
expiry, operation states, and runtime epochs make interruption recoverable.
"""

# test-file: backend/engineering_control_plane/tests/test_coordination.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import uuid4

from backend.engineering_control_plane.coordination import DispatchSpec, SessionEventType, _validate_event_payload
from backend.engineering_control_plane.database import connect


OPERATION_ACTIVE_STATUSES = ("queued", "admitted", "draining_tests", "restarting", "verifying")
OPERATION_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class CoordinationConflict(RuntimeError):
    """Raised when an active lease or operation owns a requested resource."""


def _validate_runtime_operation_transition(current_status: str, requested_status: str, operation_key: str) -> None:
    """Reject transitions that can resurrect a completed/failed operation."""
    if current_status in OPERATION_TERMINAL_STATUSES and requested_status != current_status:
        raise ValueError(
            f"runtime operation cannot transition from terminal status {current_status} "
            f"to {requested_status}: {operation_key}"
        )
    if current_status == "queued" and requested_status not in {"queued", "failed", "cancelled"}:
        raise ValueError(f"runtime operation is queued and not admitted: {operation_key}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresCoordinationRepository:
    """Persistent leases and runtime-operation queue."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def acquire_lease(
        self,
        *,
        lease_key: str,
        owner_key: str,
        resources: Iterable[str],
        ttl_seconds: int,
        mode: str = "exclusive",
    ) -> dict[str, Any]:
        normalized = sorted({resource.strip() for resource in resources if resource.strip()})
        if not normalized:
            raise ValueError("resources must not be empty")
        if mode not in {"shared", "exclusive"}:
            raise ValueError(f"unsupported lease mode: {mode}")
        now = _utc_now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        with connect(self.database_url) as connection:
            self._lock_resources(connection, normalized)
            self._expire_leases(connection, now)
            existing = connection.execute(
                "SELECT owner_key, status, mode FROM control_plane_resource_leases WHERE lease_key = %s FOR UPDATE",
                (lease_key,),
            ).fetchone()
            if existing is not None:
                if existing[0] != owner_key or existing[1] != "active":
                    raise CoordinationConflict(f"lease key is unavailable: {lease_key}")
                existing_resources = {
                    row[0]
                    for row in connection.execute(
                        "SELECT resource_key FROM control_plane_resource_lease_items WHERE lease_key = %s",
                        (lease_key,),
                    ).fetchall()
                }
                if existing_resources != set(normalized):
                    raise CoordinationConflict(f"lease resources cannot change during renewal: {lease_key}")
                if existing[2] != mode:
                    raise CoordinationConflict(f"lease mode cannot change during renewal: {lease_key}")
                connection.execute(
                    "UPDATE control_plane_resource_leases SET expires_at = %s WHERE lease_key = %s",
                    (expires_at, lease_key),
                )
                connection.execute(
                    "UPDATE control_plane_resource_lease_items SET active_window = tstzrange(lower(active_window), %s, '[)') WHERE lease_key = %s",
                    (expires_at, lease_key),
                )
                return self._lease_row(connection, lease_key)
            operation = connection.execute(
                """
                SELECT operation.operation_key
                FROM control_plane_runtime_operations operation
                JOIN control_plane_runtime_operation_resources resource
                  ON resource.operation_key = operation.operation_key
                WHERE operation.status = ANY(%s) AND resource.resource_key = ANY(%s)
                ORDER BY operation.requested_at, operation.operation_key
                LIMIT 1
                """,
                (list(OPERATION_ACTIVE_STATUSES), normalized),
            ).fetchone()
            if operation is not None:
                raise CoordinationConflict(f"runtime operation owns requested resources: {operation[0]}")
            conflicting_lease = connection.execute(
                """
                SELECT lease.lease_key
                FROM control_plane_resource_leases lease
                JOIN control_plane_resource_lease_items item ON item.lease_key = lease.lease_key
                WHERE lease.status = 'active'
                  AND item.status = 'active'
                  AND item.resource_key = ANY(%s)
                  AND (lease.mode = 'exclusive' OR %s = 'exclusive')
                ORDER BY lease.acquired_at, lease.lease_key
                LIMIT 1
                """,
                (normalized, mode),
            ).fetchone()
            if conflicting_lease is not None:
                raise CoordinationConflict(f"requested resources are already leased: {conflicting_lease[0]}")
            try:
                connection.execute(
                    """
                    INSERT INTO control_plane_resource_leases
                        (lease_key, owner_key, status, acquired_at, expires_at, mode)
                    VALUES (%s, %s, 'active', %s, %s, %s)
                    """,
                    (lease_key, owner_key, now, expires_at, mode),
                )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO control_plane_resource_lease_items
                            (lease_key, resource_key, active_window, status)
                        VALUES (%s, %s, tstzrange(%s, %s, '[)'), 'active')
                        """,
                        [(lease_key, resource, now, expires_at) for resource in normalized],
                    )
            except Exception as exc:
                if exc.__class__.__name__ in {"ExclusionViolation", "UniqueViolation"}:
                    raise CoordinationConflict("requested resources are already leased") from exc
                raise
            return self._lease_row(connection, lease_key)

    def get_lease(self, lease_key: str) -> dict[str, Any] | None:
        with connect(self.database_url) as connection:
            self._expire_leases(connection, _utc_now())
            row = connection.execute(
                "SELECT lease_key FROM control_plane_resource_leases WHERE lease_key = %s",
                (lease_key,),
            ).fetchone()
            return self._lease_row(connection, lease_key) if row is not None else None

    def release_lease(self, lease_key: str) -> bool:
        now = _utc_now()
        with connect(self.database_url) as connection:
            lease = connection.execute(
                "SELECT lease_key FROM control_plane_resource_leases WHERE lease_key = %s AND status = 'active' FOR UPDATE",
                (lease_key,),
            ).fetchone()
            if lease is None:
                return False
            connection.execute(
                "UPDATE control_plane_resource_lease_items SET status = 'released' WHERE lease_key = %s",
                (lease_key,),
            )
            connection.execute(
                "UPDATE control_plane_resource_leases SET status = 'released', released_at = %s WHERE lease_key = %s",
                (now, lease_key),
            )
            self._admit_queued_operations(connection, now)
            return True

    def transfer_lease(self, lease_key: str, *, expected_owner_key: str, new_owner_key: str) -> dict[str, Any]:
        with connect(self.database_url) as connection:
            updated = connection.execute(
                """
                UPDATE control_plane_resource_leases
                SET owner_key = %s
                WHERE lease_key = %s AND owner_key = %s AND status = 'active'
                RETURNING lease_key
                """,
                (new_owner_key, lease_key, expected_owner_key),
            ).fetchone()
            if updated is None:
                raise CoordinationConflict(f"lease is not owned by expected owner: {lease_key}")
            return self._lease_row(connection, lease_key)

    def lease_owned_by(self, lease_key: str, owner_key: str) -> bool:
        with connect(self.database_url) as connection:
            self._expire_leases(connection, _utc_now())
            row = connection.execute(
                "SELECT 1 FROM control_plane_resource_leases WHERE lease_key = %s AND owner_key = %s AND status = 'active'",
                (lease_key, owner_key),
            ).fetchone()
        return row is not None

    def request_runtime_operation(
        self,
        *,
        operation_key: str,
        requested_by: str,
        operation_type: str,
        resources: Iterable[str],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = sorted({resource.strip() for resource in resources if resource.strip()})
        if not normalized:
            raise ValueError("resources must not be empty")
        now = _utc_now()
        with connect(self.database_url) as connection:
            self._lock_resources(connection, normalized)
            self._expire_leases(connection, now)
            existing = connection.execute(
                "SELECT operation_key FROM control_plane_runtime_operations WHERE operation_key = %s",
                (operation_key,),
            ).fetchone()
            if existing is not None:
                return self._operation_row(connection, operation_key)
            metadata_session_id = str(metadata.get("session_id") or "")
            metadata_services = metadata.get("services") if isinstance(metadata.get("services"), list) else []
            if metadata_session_id:
                reusable = connection.execute(
                    """
                    SELECT operation.operation_key
                    FROM control_plane_runtime_operations operation
                    WHERE operation.operation_type = %s
                      AND operation.status = ANY(%s)
                      AND operation.metadata->>'session_id' = %s
                      AND operation.metadata->'services' = %s::jsonb
                      AND NOT EXISTS (
                          SELECT resource_key
                          FROM control_plane_runtime_operation_resources
                          WHERE operation_key = operation.operation_key
                          EXCEPT
                          SELECT unnest(%s::text[])
                      )
                      AND NOT EXISTS (
                          SELECT unnest(%s::text[])
                          EXCEPT
                          SELECT resource_key
                          FROM control_plane_runtime_operation_resources
                          WHERE operation_key = operation.operation_key
                      )
                    ORDER BY operation.requested_at, operation.operation_key
                    LIMIT 1
                    """,
                    (
                        operation_type,
                        list(OPERATION_ACTIVE_STATUSES),
                        metadata_session_id,
                        self._jsonb(metadata_services),
                        normalized,
                        normalized,
                    ),
                ).fetchone()
                if reusable is not None:
                    return self._operation_row(connection, reusable[0])
            other_operation = connection.execute(
                """
                SELECT 1
                FROM control_plane_runtime_operations operation
                JOIN control_plane_runtime_operation_resources resource
                  ON resource.operation_key = operation.operation_key
                WHERE operation.status = ANY(%s) AND resource.resource_key = ANY(%s)
                LIMIT 1
                """,
                (list(OPERATION_ACTIVE_STATUSES), normalized),
            ).fetchone()
            blocked_by_lease = connection.execute(
                """
                SELECT 1 FROM control_plane_resource_lease_items
                WHERE status = 'active' AND resource_key = ANY(%s)
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
            epoch = connection.execute(
                "SELECT runtime_epoch FROM control_plane_runtime_state WHERE singleton = true"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO control_plane_runtime_operations
                    (operation_key, requested_by, operation_type, status, requested_at, admitted_at, admitted_runtime_epoch, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    operation_key,
                    requested_by,
                    operation_type,
                    "queued" if other_operation is not None or blocked_by_lease is not None else "admitted",
                    now,
                    None if other_operation is not None or blocked_by_lease is not None else now,
                    None if other_operation is not None or blocked_by_lease is not None else epoch,
                    self._jsonb(metadata),
                ),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO control_plane_runtime_operation_resources (operation_key, resource_key) VALUES (%s, %s)",
                    [(operation_key, resource) for resource in normalized],
                )
            return self._operation_row(connection, operation_key)

    def update_runtime_operation(
        self,
        operation_key: str,
        *,
        status: str,
        metadata_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in OPERATION_ACTIVE_STATUSES + OPERATION_TERMINAL_STATUSES:
            raise ValueError(f"unsupported runtime operation status: {status}")
        now = _utc_now()
        with connect(self.database_url) as connection:
            resources = [
                row[0]
                for row in connection.execute(
                    "SELECT resource_key FROM control_plane_runtime_operation_resources WHERE operation_key = %s",
                    (operation_key,),
                ).fetchall()
            ]
            if not resources:
                exists = connection.execute(
                    "SELECT 1 FROM control_plane_runtime_operations WHERE operation_key = %s",
                    (operation_key,),
                ).fetchone()
                if exists is None:
                    raise KeyError(operation_key)
            self._lock_resources(connection, resources)
            if status == "queued":
                # Reconcile before locking this operation row. Admission locks
                # the FIFO queue in a single order; taking one row first could
                # deadlock with an unrelated waiter doing the same thing.
                self._expire_leases(connection, now)
                self._admit_queued_operations(connection, now)
            current = connection.execute(
                "SELECT status FROM control_plane_runtime_operations WHERE operation_key = %s FOR UPDATE",
                (operation_key,),
            ).fetchone()
            if current is None:
                raise KeyError(operation_key)
            current_status = str(current[0])
            # A queued waiter heartbeat is a recovery point. Admission normally
            # happens on release, but polling must heal a missed release signal.
            _validate_runtime_operation_transition(current_status, status, operation_key)
            effective_status = current_status if status == "queued" and current_status != "queued" else status
            completed_epoch = None
            if effective_status == "completed" and current_status != "completed":
                completed_epoch = connection.execute(
                    """
                    UPDATE control_plane_runtime_state
                    SET runtime_epoch = runtime_epoch + 1, updated_at = %s
                    WHERE singleton = true
                    RETURNING runtime_epoch
                    """,
                    (now,),
                ).fetchone()[0]
            connection.execute(
                """
                UPDATE control_plane_runtime_operations
                SET status = %s,
                    admitted_at = CASE WHEN %s = 'admitted' AND admitted_at IS NULL THEN %s ELSE admitted_at END,
                    completed_at = CASE WHEN %s = ANY(%s) THEN %s ELSE completed_at END,
                    completed_runtime_epoch = COALESCE(%s, completed_runtime_epoch),
                    metadata = CASE
                        WHEN %s = 'completed' THEN (metadata || %s) - 'error'
                        ELSE metadata || %s
                    END
                WHERE operation_key = %s
                """,
                (
                    effective_status,
                    effective_status,
                    now,
                    effective_status,
                    list(OPERATION_TERMINAL_STATUSES),
                    now,
                    completed_epoch,
                    effective_status,
                    self._jsonb(metadata_updates or {}),
                    self._jsonb(metadata_updates or {}),
                    operation_key,
                ),
            )
            if effective_status in OPERATION_TERMINAL_STATUSES:
                self._admit_queued_operations(connection, now)
            return self._operation_row(connection, operation_key)

    def list_runtime_operations(
        self,
        *,
        operation_type: str | None = None,
        statuses: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        normalized_statuses = [status for status in (statuses or []) if status]
        safe_limit = max(1, min(int(limit), 100))
        clauses = []
        parameters: list[Any] = []
        if operation_type:
            clauses.append("operation_type = %s")
            parameters.append(operation_type)
        if normalized_statuses:
            clauses.append("status = ANY(%s)")
            parameters.append(normalized_statuses)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect(self.database_url) as connection:
            rows = connection.execute(
                f"""
                SELECT operation_key
                FROM control_plane_runtime_operations
                {where}
                ORDER BY requested_at DESC, operation_key DESC
                LIMIT %s
                """,
                (*parameters, safe_limit),
            ).fetchall()
            return [self._operation_row(connection, row[0]) for row in rows]

    def blocking_leases(self, operation_key: str) -> list[dict[str, Any]]:
        return self.runtime_operation_blockers(operation_key)["leases"]

    def runtime_operation_blockers(self, operation_key: str) -> dict[str, list[dict[str, Any]]]:
        with connect(self.database_url) as connection:
            now = _utc_now()
            operation = connection.execute(
                "SELECT requested_at FROM control_plane_runtime_operations WHERE operation_key = %s",
                (operation_key,),
            ).fetchone()
            if operation is None:
                raise KeyError(operation_key)
            self._expire_leases(connection, now)
            self._admit_queued_operations(connection, now)
            from psycopg.rows import dict_row

            connection.row_factory = dict_row
            rows = connection.execute(
                """
                SELECT DISTINCT lease.*
                FROM control_plane_resource_leases lease
                JOIN control_plane_resource_lease_items lease_resource ON lease_resource.lease_key = lease.lease_key
                JOIN control_plane_runtime_operation_resources operation_resource
                  ON operation_resource.resource_key = lease_resource.resource_key
                WHERE operation_resource.operation_key = %s
                  AND lease.status = 'active'
                  AND lease_resource.status = 'active'
                ORDER BY lease.acquired_at, lease.lease_key
                """,
                (operation_key,),
            ).fetchall()
            leases = [self._normalize_lease(dict(row), connection) for row in rows]
            operation_rows = connection.execute(
                """
                SELECT DISTINCT other_operation.operation_key
                FROM control_plane_runtime_operations current_operation
                JOIN control_plane_runtime_operation_resources current_resource
                  ON current_resource.operation_key = current_operation.operation_key
                JOIN control_plane_runtime_operation_resources other_resource
                  ON other_resource.resource_key = current_resource.resource_key
                JOIN control_plane_runtime_operations other_operation
                  ON other_operation.operation_key = other_resource.operation_key
                WHERE current_operation.operation_key = %s
                  AND other_operation.operation_key <> current_operation.operation_key
                  AND (
                    other_operation.status = ANY(%s)
                    OR (
                      other_operation.status = 'queued'
                      AND (other_operation.requested_at, other_operation.operation_key)
                          < (current_operation.requested_at, current_operation.operation_key)
                    )
                  )
                ORDER BY other_operation.operation_key
                """,
                (operation_key, ["admitted", "draining_tests", "restarting", "verifying"]),
            ).fetchall()
            operations = [self._operation_row(connection, row["operation_key"]) for row in operation_rows]
            return {"leases": leases, "operations": operations}

    def runtime_epoch(self) -> int:
        with connect(self.database_url) as connection:
            return int(
                connection.execute(
                    "SELECT runtime_epoch FROM control_plane_runtime_state WHERE singleton = true"
                ).fetchone()[0]
            )

    def request_dispatch(
        self,
        spec: DispatchSpec,
        *,
        requested_by: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create a dispatch or reuse the canonical equivalent active result."""
        now = _utc_now()
        with connect(self.database_url) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (spec.fingerprint,))
            existing = connection.execute(
                """
                SELECT dispatch_key FROM control_plane_dispatch_requests
                WHERE fingerprint_sha256 = %s
                  AND status IN ('pending_canary', 'queued', 'running', 'succeeded')
                ORDER BY requested_at, dispatch_key
                LIMIT 1
                FOR UPDATE
                """,
                (spec.fingerprint,),
            ).fetchone()
            if existing is not None:
                return self._dispatch_row(connection, existing[0]), True
            attempt = connection.execute(
                "SELECT count(*) FROM control_plane_dispatch_requests WHERE fingerprint_sha256 = %s",
                (spec.fingerprint,),
            ).fetchone()[0] + 1
            dispatch_key = f"{spec.fingerprint[:24]}-{attempt}"
            connection.execute(
                """
                INSERT INTO control_plane_dispatch_requests
                    (dispatch_key, fingerprint_sha256, repository, subject_commit, test_selection,
                     profile, account_key, mocks, required_services, runtime_epoch, requested_by,
                     status, requested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    dispatch_key,
                    spec.fingerprint,
                    spec.repository,
                    spec.commit,
                    self._jsonb(list(spec.tests)),
                    spec.profile,
                    spec.account,
                    self._jsonb(dict(spec.mocks)),
                    self._jsonb(list(spec.required_services)),
                    spec.runtime_epoch,
                    requested_by,
                    "pending_canary" if spec.required_services else "queued",
                    now,
                ),
            )
            return self._dispatch_row(connection, dispatch_key), False

    def record_canary(
        self,
        dispatch_key: str,
        service: str,
        *,
        healthy: bool,
        failure_class: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT required_services, status FROM control_plane_dispatch_requests WHERE dispatch_key = %s FOR UPDATE",
                (dispatch_key,),
            ).fetchone()
            if row is None:
                raise KeyError(dispatch_key)
            required_services = set(row[0])
            if service not in required_services:
                raise ValueError(f"undeclared required service: {service}")
            if row[1] not in {"pending_canary", "prevented"}:
                return self._dispatch_row(connection, dispatch_key)
            connection.execute(
                """
                INSERT INTO control_plane_dispatch_canaries
                    (dispatch_key, service_key, healthy, checked_at, failure_class)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (dispatch_key, service_key) DO UPDATE SET
                    healthy = EXCLUDED.healthy,
                    checked_at = EXCLUDED.checked_at,
                    failure_class = EXCLUDED.failure_class
                """,
                (dispatch_key, service, healthy, now, failure_class),
            )
            if not healthy:
                connection.execute(
                    "UPDATE control_plane_dispatch_requests SET status = 'prevented', reason = %s WHERE dispatch_key = %s",
                    (f"required_service_unhealthy:{service}", dispatch_key),
                )
            else:
                remaining = connection.execute(
                    """
                    SELECT count(*) FROM jsonb_array_elements_text(%s::jsonb) required(service_key)
                    WHERE NOT EXISTS (
                        SELECT 1 FROM control_plane_dispatch_canaries canary
                        WHERE canary.dispatch_key = %s
                          AND canary.service_key = required.service_key
                          AND canary.healthy = true
                    )
                    """,
                    (self._jsonb(sorted(required_services)), dispatch_key),
                ).fetchone()[0]
                if remaining == 0:
                    connection.execute(
                        "UPDATE control_plane_dispatch_requests SET status = 'queued', reason = NULL WHERE dispatch_key = %s",
                        (dispatch_key,),
                    )
            return self._dispatch_row(connection, dispatch_key)

    def update_dispatch(self, dispatch_key: str, *, status: str, reason: str | None = None) -> dict[str, Any]:
        if status not in {"running", "succeeded", "failed", "cancelled", "environment_interrupted"}:
            raise ValueError(f"unsupported dispatch status: {status}")
        now = _utc_now()
        with connect(self.database_url) as connection:
            current = connection.execute(
                "SELECT status FROM control_plane_dispatch_requests WHERE dispatch_key = %s FOR UPDATE",
                (dispatch_key,),
            ).fetchone()
            if current is None:
                raise KeyError(dispatch_key)
            if status == "running" and current[0] != "queued":
                raise CoordinationConflict(f"dispatch cannot start from {current[0]}")
            if status != "running" and current[0] not in {"queued", "running"}:
                raise CoordinationConflict(f"dispatch cannot complete from {current[0]}")
            connection.execute(
                """
                UPDATE control_plane_dispatch_requests
                SET status = %s, reason = %s,
                    started_at = CASE WHEN %s = 'running' THEN COALESCE(started_at, %s) ELSE started_at END,
                    completed_at = CASE WHEN %s <> 'running' THEN %s ELSE completed_at END
                WHERE dispatch_key = %s
                """,
                (status, reason, status, now, status, now, dispatch_key),
            )
            return self._dispatch_row(connection, dispatch_key)

    def publish_event(
        self,
        *,
        event_type: SessionEventType,
        target_type: str,
        target_key: str,
        subject_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _validate_event_payload(payload)
        if target_type not in {"session", "task", "dispatch", "lease", "runtime_operation"}:
            raise ValueError(f"unsupported event target type: {target_type}")
        event_key = f"event-{uuid4().hex}"
        with connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO control_plane_session_events
                    (event_key, event_type, target_type, target_key, subject_key, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (event_key, event_type.value, target_type, target_key, subject_key, self._jsonb(payload)),
            )
            return self._event_row(connection, event_key)

    def read_events(self, target_type: str, target_key: str, *, after_cursor: int = 0) -> list[dict[str, Any]]:
        with connect(self.database_url) as connection:
            from psycopg.rows import dict_row

            connection.row_factory = dict_row
            rows = connection.execute(
                """
                SELECT * FROM control_plane_session_events
                WHERE target_type = %s AND target_key = %s AND cursor > %s AND retain_until > now()
                ORDER BY cursor
                """,
                (target_type, target_key, after_cursor),
            ).fetchall()
            return [dict(row) for row in rows]

    def acknowledge_event(self, event_key: str, *, recipient: str) -> bool:
        with connect(self.database_url) as connection:
            if connection.execute(
                "SELECT 1 FROM control_plane_session_events WHERE event_key = %s",
                (event_key,),
            ).fetchone() is None:
                raise KeyError(event_key)
            inserted = connection.execute(
                """
                INSERT INTO control_plane_session_event_acknowledgements
                    (event_key, recipient_key, acknowledged_at)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING event_key
                """,
                (event_key, recipient, _utc_now()),
            ).fetchone()
            return inserted is not None

    def _lock_resources(self, connection: Any, resources: Iterable[str]) -> None:
        for resource in sorted(resources):
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (resource,))

    def _expire_leases(self, connection: Any, now: datetime) -> None:
        expired = [
            row[0]
            for row in connection.execute(
                "SELECT lease_key FROM control_plane_resource_leases WHERE status = 'active' AND expires_at <= %s FOR UPDATE",
                (now,),
            ).fetchall()
        ]
        if not expired:
            return
        connection.execute(
            "UPDATE control_plane_resource_lease_items SET status = 'expired' WHERE lease_key = ANY(%s)",
            (expired,),
        )
        connection.execute(
            "UPDATE control_plane_resource_leases SET status = 'expired' WHERE lease_key = ANY(%s)",
            (expired,),
        )
        self._admit_queued_operations(connection, now)

    def _admit_queued_operations(self, connection: Any, now: datetime) -> None:
        queued = connection.execute(
            "SELECT operation_key, requested_at FROM control_plane_runtime_operations WHERE status = 'queued' ORDER BY requested_at, operation_key FOR UPDATE"
        ).fetchall()
        for operation_key, requested_at in queued:
            blocked_by_lease = connection.execute(
                """
                SELECT 1
                FROM control_plane_runtime_operation_resources operation_resource
                JOIN control_plane_resource_lease_items lease_resource
                  ON lease_resource.resource_key = operation_resource.resource_key
                WHERE operation_resource.operation_key = %s AND lease_resource.status = 'active'
                LIMIT 1
                """,
                (operation_key,),
            ).fetchone()
            blocked_by_operation = connection.execute(
                """
                SELECT 1
                FROM control_plane_runtime_operation_resources current_resource
                JOIN control_plane_runtime_operation_resources other_resource
                  ON other_resource.resource_key = current_resource.resource_key
                JOIN control_plane_runtime_operations other_operation
                  ON other_operation.operation_key = other_resource.operation_key
                WHERE current_resource.operation_key = %s
                  AND other_operation.operation_key <> %s
                  AND (
                    other_operation.status = ANY(%s)
                    OR (
                      other_operation.status = 'queued'
                      AND (other_operation.requested_at, other_operation.operation_key) < (%s, %s)
                    )
                  )
                LIMIT 1
                """,
                (
                    operation_key,
                    operation_key,
                    ["admitted", "draining_tests", "restarting", "verifying"],
                    requested_at,
                    operation_key,
                ),
            ).fetchone()
            if blocked_by_lease is None and blocked_by_operation is None:
                epoch = connection.execute(
                    "SELECT runtime_epoch FROM control_plane_runtime_state WHERE singleton = true"
                ).fetchone()[0]
                connection.execute(
                    """
                    UPDATE control_plane_runtime_operations
                    SET status = 'admitted', admitted_at = %s, admitted_runtime_epoch = %s
                    WHERE operation_key = %s
                    """,
                    (now, epoch, operation_key),
                )

    def _lease_row(self, connection: Any, lease_key: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        connection.row_factory = dict_row
        row = connection.execute(
            "SELECT * FROM control_plane_resource_leases WHERE lease_key = %s",
            (lease_key,),
        ).fetchone()
        return self._normalize_lease(dict(row), connection)

    def _normalize_lease(self, row: dict[str, Any], connection: Any) -> dict[str, Any]:
        resources = connection.execute(
            "SELECT resource_key FROM control_plane_resource_lease_items WHERE lease_key = %s ORDER BY resource_key",
            (row["lease_key"],),
        ).fetchall()
        row["resources"] = [item[0] if not isinstance(item, dict) else item["resource_key"] for item in resources]
        return row

    def _operation_row(self, connection: Any, operation_key: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        connection.row_factory = dict_row
        row = connection.execute(
            "SELECT * FROM control_plane_runtime_operations WHERE operation_key = %s",
            (operation_key,),
        ).fetchone()
        resources = connection.execute(
            "SELECT resource_key FROM control_plane_runtime_operation_resources WHERE operation_key = %s ORDER BY resource_key",
            (operation_key,),
        ).fetchall()
        result = dict(row)
        result["resources"] = [item["resource_key"] for item in resources]
        return result

    def _dispatch_row(self, connection: Any, dispatch_key: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        connection.row_factory = dict_row
        row = connection.execute(
            "SELECT * FROM control_plane_dispatch_requests WHERE dispatch_key = %s",
            (dispatch_key,),
        ).fetchone()
        canaries = connection.execute(
            "SELECT service_key, healthy FROM control_plane_dispatch_canaries WHERE dispatch_key = %s ORDER BY service_key",
            (dispatch_key,),
        ).fetchall()
        result = dict(row)
        result["canaries"] = {item["service_key"]: item["healthy"] for item in canaries}
        return result

    def _event_row(self, connection: Any, event_key: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        connection.row_factory = dict_row
        row = connection.execute(
            "SELECT * FROM control_plane_session_events WHERE event_key = %s",
            (event_key,),
        ).fetchone()
        return dict(row)

    def _jsonb(self, value: dict[str, Any]):
        from psycopg.types.json import Jsonb

        return Jsonb(value)
