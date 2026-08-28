"""Authenticated API tests for the independent test-control records.

The suite uses a fake repository to isolate transport, identity, scope, and
allowlist behavior. PostgreSQL transaction behavior is verified separately by
the dedicated integration suite against the real compose database.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from backend.engineering_control_plane.api import get_coordination_repository, get_repository
from backend.engineering_control_plane.auth import token_digest
from backend.engineering_control_plane.main import app


class FakeRepository:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, dict[str, Any]]] = {}

    def list_records(self, collection, *, filters=None, sort=None, limit=-1):
        del filters, sort, limit
        return list(self.records.get(collection, {}).values())

    def upsert_record(self, collection, record):
        key_field = {
            "test_claims": "claim_key",
            "test_catalog": "test_key",
        }[collection]
        stored = dict(record)
        self.records.setdefault(collection, {})[stored[key_field]] = stored
        return stored

    def import_records(self, collections, *, replace_current_state=False):
        del replace_current_state
        return {collection: len(records) for collection, records in collections.items()}


class FakeCoordinationRepository:
    def __init__(self) -> None:
        self.dispatches: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.acquired_leases: list[dict[str, Any]] = []

    def acquire_lease(self, **values):
        self.acquired_leases.append(values)
        return {**values, "status": "active"}

    def runtime_epoch(self):
        return 7

    def get_lease(self, lease_key):
        if lease_key == "missing":
            return None
        return {
            "lease_key": lease_key,
            "owner_key": "dev-server:1234",
            "resources": ["dev-stack"],
            "status": "active",
            "mode": "shared",
        }

    def runtime_operation_blockers(self, operation_key):
        if operation_key == "missing":
            raise KeyError(operation_key)
        return {
            "leases": [],
            "operations": [{"operation_key": "restart-first", "status": "restarting"}],
        }

    def request_dispatch(self, spec, *, requested_by):
        existing = self.dispatches.get(spec.fingerprint)
        if existing:
            return existing, True
        dispatch = {
            "dispatch_key": f"dispatch-{len(self.dispatches) + 1}",
            "fingerprint_sha256": spec.fingerprint,
            "requested_by": requested_by,
            "runtime_epoch": spec.runtime_epoch,
            "status": "queued",
        }
        self.dispatches[spec.fingerprint] = dispatch
        return dispatch, False

    def publish_event(self, *, event_type, target_type, target_key, subject_key, payload):
        from backend.engineering_control_plane.coordination import _validate_event_payload

        _validate_event_payload(payload)
        event = {
            "event_key": f"event-{len(self.events) + 1}",
            "cursor": len(self.events) + 1,
            "event_type": event_type.value,
            "target_type": target_type,
            "target_key": target_key,
            "subject_key": subject_key,
            "payload": payload,
        }
        self.events.append(event)
        return event

    def read_events(self, target_type, target_key, *, after_cursor=0):
        return [
            event
            for event in self.events
            if event["target_type"] == target_type
            and event["target_key"] == target_key
            and event["cursor"] > after_cursor
        ]


def _client(monkeypatch, scopes: list[str]) -> tuple[TestClient, FakeRepository, dict[str, str]]:
    token = "test-control-token"
    identities = {
        "test-client": {
            "token_sha256": token_digest(token),
            "scopes": scopes,
        }
    }
    monkeypatch.setenv("ENGINEERING_CONTROL_PLANE_DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("ENGINEERING_CONTROL_PLANE_IDENTITIES_JSON", json.dumps(identities))
    repository = FakeRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    return TestClient(app), repository, {"Authorization": f"Bearer {token}"}


def test_records_require_a_valid_scoped_identity(monkeypatch) -> None:
    client, _, headers = _client(monkeypatch, ["read"])

    assert client.get("/v1/records/test_catalog").status_code == 401
    assert client.get("/v1/records/test_catalog", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/records/test_catalog", headers=headers).status_code == 200
    response = client.put(
        "/v1/records/test_catalog",
        headers=headers,
        json={"record": {"test_key": "pytest::one"}},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "control_plane_scope_required:ingest"
    app.dependency_overrides.clear()


def test_ingest_and_coordinate_scopes_are_separate(monkeypatch) -> None:
    client, repository, headers = _client(monkeypatch, ["read", "ingest"])

    response = client.put(
        "/v1/records/test_catalog",
        headers=headers,
        json={"record": {"test_key": "pytest::one", "suite": "pytest"}},
    )
    assert response.status_code == 200
    assert repository.records["test_catalog"]["pytest::one"]["suite"] == "pytest"

    claim = client.put(
        "/v1/records/test_claims",
        headers=headers,
        json={"record": {"claim_key": "lease-1", "status": "active"}},
    )
    assert claim.status_code == 403
    assert claim.json()["detail"] == "control_plane_scope_required:coordinate"
    app.dependency_overrides.clear()


def test_bulk_import_rejects_unknown_collections(monkeypatch) -> None:
    client, _, headers = _client(monkeypatch, ["admin"])

    response = client.post(
        "/v1/import",
        headers=headers,
        json={"collections": {"product_users": [{"id": "forbidden"}]}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported record type: product_users"
    app.dependency_overrides.clear()


def test_dispatch_fingerprint_is_server_epoch_bound_and_reused(monkeypatch) -> None:
    client, _, headers = _client(monkeypatch, ["read", "coordinate"])
    coordination = FakeCoordinationRepository()
    app.dependency_overrides[get_coordination_repository] = lambda: coordination
    payload = {
        "repository": "OpenMates",
        "commit": "abc123",
        "tests": ["pytest::second", "pytest::first"],
        "profile": "full",
        "account": "test-account",
        "mocks": {"mail": "fake"},
        "required_services": [],
    }

    first = client.post("/v1/coordination/dispatches", headers=headers, json=payload)
    second = client.post("/v1/coordination/dispatches", headers=headers, json=payload)

    assert first.status_code == 200
    assert first.json()["reused"] is False
    assert first.json()["dispatch"]["runtime_epoch"] == 7
    assert second.json()["reused"] is True
    assert second.json()["dispatch"]["dispatch_key"] == first.json()["dispatch"]["dispatch_key"]
    app.dependency_overrides.clear()


def test_runtime_operation_blockers_report_operations_and_missing_keys(monkeypatch) -> None:
    client, _, headers = _client(monkeypatch, ["read", "coordinate"])
    coordination = FakeCoordinationRepository()
    app.dependency_overrides[get_coordination_repository] = lambda: coordination

    response = client.get("/v1/coordination/runtime-operations/restart-next/blocking-leases", headers=headers)
    missing = client.get("/v1/coordination/runtime-operations/missing/blocking-leases", headers=headers)

    assert response.status_code == 200
    assert response.json()["operations"][0]["operation_key"] == "restart-first"
    assert missing.status_code == 404
    app.dependency_overrides.clear()


def test_coordinate_scope_can_inspect_one_lease_for_dead_owner_recovery(monkeypatch) -> None:
    client, _, headers = _client(monkeypatch, ["read", "coordinate"])
    coordination = FakeCoordinationRepository()
    app.dependency_overrides[get_coordination_repository] = lambda: coordination

    response = client.get("/v1/coordination/leases/test-run", headers=headers)
    missing = client.get("/v1/coordination/leases/missing", headers=headers)

    assert response.status_code == 200
    assert response.json()["lease"]["owner_key"] == "dev-server:1234"
    assert missing.status_code == 404
    app.dependency_overrides.clear()


def test_lease_api_caps_unrenewed_lifetime_without_rejecting_old_clients(monkeypatch) -> None:
    client, _, headers = _client(monkeypatch, ["read", "coordinate"])
    coordination = FakeCoordinationRepository()
    app.dependency_overrides[get_coordination_repository] = lambda: coordination

    response = client.post(
        "/v1/coordination/leases",
        headers=headers,
        json={
            "lease_key": "old-client-run",
            "owner_key": "dev-server:1234",
            "resources": ["dev-stack"],
            "ttl_seconds": 12 * 60 * 60,
            "mode": "shared",
        },
    )

    assert response.status_code == 200
    assert coordination.acquired_leases[0]["ttl_seconds"] == 30 * 60
    app.dependency_overrides.clear()


def test_events_use_cursor_handoffs_and_reject_secret_fields(monkeypatch) -> None:
    client, _, headers = _client(monkeypatch, ["read", "coordinate"])
    coordination = FakeCoordinationRepository()
    app.dependency_overrides[get_coordination_repository] = lambda: coordination
    payload = {
        "event_type": "task.changed",
        "target_type": "session",
        "target_key": "session-b",
        "subject_key": "task-1",
        "payload": {"state": "ready"},
    }

    published = client.post("/v1/coordination/events", headers=headers, json=payload)
    read = client.get(
        "/v1/coordination/events",
        headers=headers,
        params={"target_type": "session", "target_key": "session-b", "after_cursor": 0},
    )
    forbidden = client.post(
        "/v1/coordination/events",
        headers=headers,
        json={**payload, "payload": {"nested": {"token": "must-not-cross"}}},
    )

    assert published.status_code == 200
    assert [event["event_key"] for event in read.json()["events"]] == ["event-1"]
    assert forbidden.status_code == 400
    assert forbidden.json()["detail"] == "forbidden event payload field: token"
    app.dependency_overrides.clear()
