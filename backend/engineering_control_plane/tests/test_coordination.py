"""Coordination contract tests for the private engineering control plane.

These tests define the atomic lease, runtime-operation, dispatch, and event
semantics shared by sessions, test runners, and product lifecycle commands.
They use an in-memory reference store so the contract stays deterministic.
"""

# contract-test-file: infrastructure

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.engineering_control_plane.coordination import (
    DispatchSpec,
    InMemoryCoordinationStore,
    LeaseConflict,
    LeaseMode,
    SessionEventType,
)
from backend.engineering_control_plane.coordination_repository import _validate_runtime_operation_transition


def test_shared_leases_coexist_but_exclusive_lease_waits() -> None:
    store = InMemoryCoordinationStore()
    for lease_key in ("reader-a", "reader-b"):
        store.acquire_lease(
            lease_key=lease_key,
            owner=lease_key,
            resources={"product-runtime"},
            expires_at=NOW + timedelta(minutes=10),
            now=NOW,
            mode=LeaseMode.SHARED,
        )

    with pytest.raises(LeaseConflict):
        store.acquire_lease(
            lease_key="writer",
            owner="restart",
            resources={"product-runtime"},
            expires_at=NOW + timedelta(minutes=10),
            now=NOW,
            mode=LeaseMode.EXCLUSIVE,
        )


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def test_overlapping_resource_leases_are_atomic() -> None:
    store = InMemoryCoordinationStore()

    def acquire(lease_key: str) -> str:
        try:
            store.acquire_lease(
                lease_key=lease_key,
                owner=lease_key,
                resources={"product-runtime"},
                expires_at=NOW + timedelta(minutes=10),
                now=NOW,
            )
        except LeaseConflict:
            return "conflict"
        return "acquired"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(acquire, ("lease-a", "lease-b")))

    assert sorted(outcomes) == ["acquired", "conflict"]
    store.acquire_lease(
        lease_key="lease-c",
        owner="chat-c",
        resources={"apple-runner"},
        expires_at=NOW + timedelta(minutes=10),
        now=NOW,
    )


def test_runtime_operation_waits_for_conflicting_lease() -> None:
    store = InMemoryCoordinationStore()
    store.acquire_lease(
        lease_key="test-run",
        owner="chat-a",
        resources={"product-runtime"},
        expires_at=NOW + timedelta(minutes=10),
        now=NOW,
    )

    operation = store.request_runtime_operation(
        operation_key="restart-1",
        requested_by="chat-b",
        resources={"product-runtime"},
        now=NOW,
    )
    assert operation.status == "queued"

    store.release_lease("test-run", now=NOW + timedelta(seconds=1))
    assert store.get_runtime_operation("restart-1").status == "admitted"

    store.complete_runtime_operation("restart-1", now=NOW + timedelta(seconds=2))
    assert store.runtime_epoch == 1


def test_runtime_operation_poll_reconciles_expired_lease_without_release_signal() -> None:
    store = InMemoryCoordinationStore()
    store.acquire_lease(
        lease_key="test-run",
        owner="chat-a",
        resources={"product-runtime"},
        expires_at=NOW + timedelta(seconds=5),
        now=NOW,
    )
    store.request_runtime_operation(
        operation_key="restart-1",
        requested_by="chat-b",
        resources={"product-runtime"},
        now=NOW,
    )

    operation = store.poll_runtime_operation("restart-1", now=NOW + timedelta(seconds=6))

    assert operation.status == "admitted"
    assert store.runtime_operation_blockers("restart-1", now=NOW + timedelta(seconds=6)) == {
        "leases": [],
        "operations": [],
    }


def test_runtime_operation_blockers_include_earlier_operation_and_active_lease() -> None:
    store = InMemoryCoordinationStore()
    store.acquire_lease(
        lease_key="apple-test",
        owner="chat-a",
        resources={"apple-runner"},
        expires_at=NOW + timedelta(minutes=5),
        now=NOW,
    )
    first = store.request_runtime_operation(
        operation_key="restart-1",
        requested_by="chat-b",
        resources={"product-runtime"},
        now=NOW,
    )
    queued = store.request_runtime_operation(
        operation_key="restart-2",
        requested_by="chat-c",
        resources={"product-runtime", "apple-runner"},
        now=NOW + timedelta(seconds=1),
    )

    blockers = store.runtime_operation_blockers("restart-2", now=NOW + timedelta(seconds=2))

    assert queued.status == "queued"
    assert [lease.lease_key for lease in blockers["leases"]] == ["apple-test"]
    assert [operation.operation_key for operation in blockers["operations"]] == [first.operation_key]


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_terminal_runtime_operation_cannot_be_resurrected(terminal: str) -> None:
    with pytest.raises(ValueError, match="cannot transition from terminal status"):
        _validate_runtime_operation_transition(terminal, "restarting", "restart-1")

    _validate_runtime_operation_transition(terminal, terminal, "restart-1")


def test_runtime_operations_queue_fifo_for_the_same_resource() -> None:
    store = InMemoryCoordinationStore()

    first = store.request_runtime_operation(
        operation_key="restart-1",
        requested_by="chat-a",
        resources={"product-runtime"},
        now=NOW,
    )
    second = store.request_runtime_operation(
        operation_key="restart-2",
        requested_by="chat-b",
        resources={"product-runtime"},
        now=NOW + timedelta(seconds=1),
    )
    unrelated = store.request_runtime_operation(
        operation_key="apple-1",
        requested_by="chat-c",
        resources={"apple-runner"},
        now=NOW + timedelta(seconds=2),
    )

    assert first.status == "admitted"
    assert second.status == "queued"
    assert unrelated.status == "admitted"

    store.complete_runtime_operation("restart-1", now=NOW + timedelta(seconds=3))

    assert store.get_runtime_operation("restart-2").status == "admitted"


def test_equivalent_dispatch_is_reused_until_runtime_epoch_changes() -> None:
    store = InMemoryCoordinationStore()
    spec = DispatchSpec.create(
        repository="openmates/OpenMates",
        commit="abc123",
        tests=["pytest::b", "pytest::a", "pytest::a"],
        profile="full",
        account="shared-1",
        mocks={"stripe": "fake", "llm": "recorded"},
        required_services=["api", "cms"],
        runtime_epoch=store.runtime_epoch,
    )

    first, first_reused = store.request_dispatch(spec, requested_by="chat-a", now=NOW)
    second, second_reused = store.request_dispatch(spec, requested_by="chat-b", now=NOW)
    assert first.dispatch_key == second.dispatch_key
    assert first_reused is False
    assert second_reused is True

    store.record_canary(first.dispatch_key, "api", healthy=True, now=NOW)
    store.record_canary(first.dispatch_key, "cms", healthy=True, now=NOW)
    store.complete_dispatch(first.dispatch_key, succeeded=True, now=NOW)
    successful, successful_reused = store.request_dispatch(spec, requested_by="chat-c", now=NOW)
    assert successful.dispatch_key == first.dispatch_key
    assert successful_reused is True

    store.advance_runtime_epoch()
    after_restart = DispatchSpec.create(
        repository=spec.repository,
        commit=spec.commit,
        tests=spec.tests,
        profile=spec.profile,
        account=spec.account,
        mocks=dict(spec.mocks),
        required_services=spec.required_services,
        runtime_epoch=store.runtime_epoch,
    )
    replacement, replacement_reused = store.request_dispatch(after_restart, requested_by="chat-c", now=NOW)
    assert replacement.dispatch_key != first.dispatch_key
    assert replacement_reused is False


def test_failed_canary_prevents_dispatch_with_stable_reason() -> None:
    store = InMemoryCoordinationStore()
    spec = DispatchSpec.create(
        repository="openmates/OpenMates",
        commit="abc123",
        tests=["playwright::login"],
        profile="browser",
        account="shared-2",
        mocks={},
        required_services=["api"],
        runtime_epoch=0,
    )
    dispatch, _ = store.request_dispatch(spec, requested_by="chat-a", now=NOW)

    store.record_canary(dispatch.dispatch_key, "api", healthy=False, now=NOW)

    dispatch = store.get_dispatch(dispatch.dispatch_key)
    assert dispatch.status == "prevented"
    assert dispatch.reason == "required_service_unhealthy:api"


def test_targeted_events_use_monotonic_cursors_and_idempotent_ack() -> None:
    store = InMemoryCoordinationStore()
    first = store.publish_event(
        event_type=SessionEventType.DISPATCH_CHANGED,
        target_type="session",
        target_key="chat-a",
        subject_key="dispatch-1",
        payload={"status": "running"},
        now=NOW,
    )
    second = store.publish_event(
        event_type=SessionEventType.RUNTIME_CHANGED,
        target_type="session",
        target_key="chat-a",
        subject_key="restart-1",
        payload={"status": "completed", "runtime_epoch": 1},
        now=NOW,
    )
    store.publish_event(
        event_type=SessionEventType.LEASE_CHANGED,
        target_type="session",
        target_key="chat-b",
        subject_key="lease-1",
        payload={"status": "released"},
        now=NOW,
    )

    assert [event.event_key for event in store.read_events("session", "chat-a", after_cursor=first.cursor)] == [
        second.event_key
    ]
    assert store.acknowledge_event(second.event_key, recipient="chat-a", now=NOW) is True
    assert store.acknowledge_event(second.event_key, recipient="chat-a", now=NOW) is False

    with pytest.raises(ValueError, match="forbidden event payload field"):
        store.publish_event(
            event_type=SessionEventType.DISPATCH_CHANGED,
            target_type="session",
            target_key="chat-a",
            subject_key="dispatch-1",
            payload={"credentials": "secret"},
            now=NOW,
        )
