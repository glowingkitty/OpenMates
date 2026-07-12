# backend/tests/test_workflow_trigger_persistence.py
#
# Focused persistence contracts for Workflows V1 trigger rows. These tests keep
# recurrence and event configuration encrypted while asserting that only routing
# and scheduler metadata reaches the durable trigger record.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, InMemoryWorkflowRepository
from backend.tests.workflow_test_utils import workflow_service


def schedule_graph(time_value: str = "07:00") -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {
                "id": "trigger",
                "type": "schedule_trigger",
                "config": {"schedule": {"type": "daily", "time": time_value, "timezone": "Europe/Berlin"}},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "end"}],
    }


def event_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {
                "id": "trigger",
                "type": "event_trigger",
                "config": {
                    "event": {
                        "source": "terminal",
                        "event_type": "command.completed",
                        "scope": {"project_id": "project-private"},
                        "filters": {"command_text": {"op": "contains", "value": "deploy"}},
                        "rate_limit": {"max_per_hour": 1},
                    }
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"from": "trigger", "to": "end"}],
    }


def test_schedule_trigger_is_encrypted_and_replaced_when_its_graph_version_changes() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Daily deploy check", schedule_graph(), enabled=False)

    trigger = repository.get_trigger_for_workflow(workflow.id, "alice")
    assert trigger is not None
    assert trigger["workflow_id"] == workflow.id
    assert trigger["version_id"] == workflow.current_version_id
    assert trigger["owner_hash"] == repository.workflow_owner_hash("alice")
    assert trigger["trigger_type"] == "schedule"
    assert trigger["enabled"] is False
    assert trigger["next_run_at"] is None
    assert trigger["encrypted_schedule_config_ref"].startswith("vault://workflows/workflow_schedule_config/")
    assert trigger["encrypted_event_predicate_ref"] is None

    raw_trigger_rows = json.dumps(repository.triggers, sort_keys=True)
    raw_blob_rows = json.dumps(repository.encrypted_blobs, sort_keys=True)
    assert "Europe/Berlin" not in raw_trigger_rows
    assert "07:00" not in raw_trigger_rows
    assert "Europe/Berlin" not in raw_blob_rows
    assert "07:00" not in raw_blob_rows

    enabled = service.update_workflow(workflow.id, "alice", enabled=True)
    enabled_trigger = repository.get_trigger_for_workflow(workflow.id, "alice")
    assert enabled_trigger is not None
    assert enabled_trigger["trigger_id"] == trigger["trigger_id"]
    assert enabled_trigger["version_id"] == enabled.current_version_id
    assert enabled_trigger["encrypted_schedule_config_ref"] == trigger["encrypted_schedule_config_ref"]
    assert enabled_trigger["enabled"] is True
    assert isinstance(enabled_trigger["next_run_at"], int)

    old_ref = enabled_trigger["encrypted_schedule_config_ref"]
    updated = service.update_workflow(workflow.id, "alice", graph=schedule_graph("08:30"))
    updated_trigger = repository.get_trigger_for_workflow(workflow.id, "alice")

    assert updated_trigger is not None
    assert updated_trigger["trigger_id"] == trigger["trigger_id"]
    assert updated_trigger["version_id"] == updated.current_version_id
    assert updated_trigger["enabled"] is True
    assert isinstance(updated_trigger["next_run_at"], int)
    assert updated_trigger["encrypted_schedule_config_ref"] != old_ref
    assert repository.get_encrypted_blob(old_ref) is None
    assert service.decrypt_schedule_config("alice", updated_trigger["encrypted_schedule_config_ref"]) == {
        "schedule": {"type": "daily", "time": "08:30", "timezone": "Europe/Berlin"}
    }


def test_event_trigger_persists_only_hashed_routing_metadata_and_an_opaque_config_ref() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Deploy watcher", event_graph(), enabled=True)

    trigger = repository.get_trigger_for_workflow(workflow.id, "alice")
    assert trigger is not None
    assert trigger["workflow_id"] == workflow.id
    assert trigger["version_id"] == workflow.current_version_id
    assert trigger["owner_hash"] == repository.workflow_owner_hash("alice")
    assert trigger["trigger_type"] == "event"
    assert trigger["source"] == "terminal"
    assert trigger["event_type"] == "command.completed"
    assert trigger["hashed_project_id"] == hashlib.sha256(b"project-private").hexdigest()
    assert trigger["encrypted_event_predicate_ref"].startswith("vault://workflows/workflow_event_predicate/")
    assert trigger["encrypted_schedule_config_ref"] is None

    raw_trigger_rows = json.dumps(repository.triggers, sort_keys=True)
    raw_blob_rows = json.dumps(repository.encrypted_blobs, sort_keys=True)
    assert "project-private" not in raw_trigger_rows
    assert "deploy" not in raw_trigger_rows
    assert "project-private" not in raw_blob_rows
    assert "deploy" not in raw_blob_rows


def test_deleting_a_workflow_removes_its_trigger_and_trigger_config_blob() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Daily deploy check", schedule_graph(), enabled=True)
    trigger = repository.get_trigger_for_workflow(workflow.id, "alice")
    assert trigger is not None

    assert service.delete_workflow(workflow.id, "alice") is True
    assert repository.get_trigger_for_workflow(workflow.id, "alice") is None
    assert repository.get_encrypted_blob(trigger["encrypted_schedule_config_ref"]) is None


class FakeDirectusTriggerClient:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def request(self, method: str, url: str, **kwargs: Any) -> "FakeDirectusTriggerResponse":
        path = url.split("/items/", 1)[1]
        _, _, item_id = path.partition("/")
        if method == "GET":
            filters = json.loads(kwargs["params"]["filter"])
            rows = [row for row in self.rows.values() if row.get("trigger_id") == filters["trigger_id"]["_eq"]]
            return FakeDirectusTriggerResponse(200, {"data": rows})
        if method == "POST":
            payload = dict(kwargs["json"])
            payload["id"] = "directus-trigger-row"
            self.rows[payload["id"]] = payload
            return FakeDirectusTriggerResponse(200, {"data": payload})
        if method == "PATCH":
            self.rows[item_id].update(kwargs["json"])
            return FakeDirectusTriggerResponse(200, {"data": self.rows[item_id]})
        if method == "DELETE":
            self.rows.pop(item_id, None)
            return FakeDirectusTriggerResponse(204, {})
        raise AssertionError(f"Unexpected Directus method: {method}")


class FakeDirectusTriggerResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        raise AssertionError(f"Unexpected Directus status: {self.status_code}")


def test_directus_trigger_repository_upserts_by_public_trigger_id() -> None:
    repository = DirectusWorkflowRepository(base_url="http://directus.test", token="test-token")
    client = FakeDirectusTriggerClient()
    repository._client = client
    record = {
        "trigger_id": "trigger-1",
        "workflow_id": "workflow-1",
        "version_id": "version-1",
        "owner_hash": "user_sha256:owner",
        "hashed_project_id": None,
        "trigger_type": "schedule",
        "source": None,
        "event_type": None,
        "encrypted_schedule_config_ref": "vault://workflows/workflow_schedule_config/1",
        "encrypted_event_predicate_ref": None,
        "encrypted_webhook_config_ref": None,
        "encrypted_required_start_input_schema_ref": None,
        "enabled": True,
        "next_run_at": 1_800_000_000,
        "claim_status": None,
        "claim_token_hash": None,
        "claim_generation": 0,
        "claimed_at": None,
        "claim_expires_at": None,
        "created_at": 100,
        "updated_at": 100,
    }

    repository.save_trigger(record)
    record["version_id"] = "version-2"
    record["updated_at"] = 101
    repository.save_trigger(record)

    assert list(client.rows) == ["directus-trigger-row"]
    assert client.rows["directus-trigger-row"]["trigger_id"] == "trigger-1"
    assert client.rows["directus-trigger-row"]["version_id"] == "version-2"
    assert client.rows["directus-trigger-row"]["hashed_user_id"] == "user_sha256:owner"
