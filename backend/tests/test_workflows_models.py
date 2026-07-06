# backend/tests/test_workflows_models.py
#
# Contract tests for Workflows V1 graph validation, feature gating, ownership,
# and capability metadata.
#
# Spec: docs/specs/workflows-v1/spec.yml

import json
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.api.app.services.feature_availability_service import FeatureAvailabilityService, FeatureDefinition
from backend.core.api.app.services.workflow_models import (
    WorkflowGraph,
    WorkflowLifecycle,
    WorkflowMissingInputError,
    WorkflowTemplateSensitiveFieldError,
    build_workflow_template_share_payload,
)
from backend.core.api.app.services.workflow_service import (
    DirectusWorkflowRepository,
    InMemoryWorkflowRepository,
    VaultWorkflowPayloadCipher,
    WORKFLOW_PLATFORM_FEATURE,
    WORKFLOW_TEMPORARY_TTL_SECONDS,
    WorkflowFeatureDisabledError,
    WorkflowService,
)
from backend.tests.workflow_test_utils import workflow_service


class FakeDirectusResponse:
    def __init__(self, status_code: int, data: Any = None) -> None:
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data or {})

    def json(self) -> Any:
        return self._data

    def raise_for_status(self) -> None:
        raise AssertionError(f"Unexpected fake Directus status: {self.status_code}")


class FakeDirectusClient:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict[str, Any]]] = {}

    def request(self, method: str, url: str, **kwargs: Any) -> FakeDirectusResponse:
        collection, item_id = self._parse_url(url)
        rows = self.collections.setdefault(collection, {})
        if method == "GET":
            filters = json.loads(kwargs.get("params", {}).get("filter", "{}"))
            data = [row for row in rows.values() if self._matches(row, filters)]
            limit = int(kwargs.get("params", {}).get("limit", 100))
            return FakeDirectusResponse(200, {"data": data if limit == -1 else data[:limit]})
        if method == "POST":
            payload = dict(kwargs["json"])
            payload.setdefault("id", payload.get("ref") or f"fake-{len(rows) + 1}")
            rows[payload["id"]] = payload
            return FakeDirectusResponse(200, {"data": payload})
        if method == "PATCH" and item_id:
            rows[item_id].update(kwargs["json"])
            return FakeDirectusResponse(200, {"data": rows[item_id]})
        if method == "DELETE" and item_id:
            rows.pop(item_id, None)
            return FakeDirectusResponse(204, {})
        return FakeDirectusResponse(500, {"error": "unsupported fake request"})

    def post(self, url: str, **kwargs: Any) -> FakeDirectusResponse:
        return FakeDirectusResponse(200, {"data": {"access_token": "fake-token"}})

    def _parse_url(self, url: str) -> tuple[str, str | None]:
        path = url.split("/items/", 1)[1]
        parts = path.split("/", 1)
        return parts[0], parts[1] if len(parts) > 1 else None

    def _matches(self, row: dict[str, Any], filters: dict[str, Any]) -> bool:
        if "_and" in filters:
            return all(self._matches(row, item) for item in filters["_and"])
        for field, condition in filters.items():
            if condition.get("_eq") is not None and row.get(field) != condition["_eq"]:
                return False
            if condition.get("_neq") is not None and row.get(field) == condition["_neq"]:
                return False
        return True


class FakeVaultEncryptionService:
    def __init__(self) -> None:
        self.encrypted: dict[str, tuple[str, str]] = {}
        self.encrypt_calls: list[tuple[str, str]] = []
        self.decrypt_calls: list[tuple[str, str]] = []

    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> tuple[str, str]:
        ciphertext = f"vault:v1:{len(self.encrypted) + 1}"
        self.encrypted[ciphertext] = (plaintext, key_id)
        self.encrypt_calls.append((plaintext, key_id))
        return ciphertext, "1"

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str | None:
        self.decrypt_calls.append((ciphertext, key_id))
        stored = self.encrypted.get(ciphertext)
        if stored is None or stored[1] != key_id:
            return None
        return stored[0]


def rain_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {
                "id": "trigger",
                "type": "schedule_trigger",
                "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "Europe/Berlin"}},
            },
            {
                "id": "weather",
                "type": "app_skill_action",
                "config": {"app_id": "weather", "skill_id": "forecast", "input": {"location": "Berlin", "days": 1}},
            },
            {
                "id": "decision",
                "type": "decision",
                "config": {"predicate": {"left": "$nodes.weather.output.rain_probability", "op": "gte", "right": 60}},
            },
            {"id": "notify", "type": "send_notification", "config": {"title": "Rain today", "body": "Take an umbrella."}},
            {"id": "email", "type": "send_email_notification", "config": {"title": "Rain today", "body": "Take an umbrella."}},
        ],
        "edges": [
            {"from": "trigger", "to": "weather"},
            {"from": "weather", "to": "decision"},
            {"from": "decision", "to": "notify", "branch": "yes"},
            {"from": "notify", "to": "email"},
        ],
    }


def disabled_workflow_service():
    return workflow_service(
        feature_availability=FeatureAvailabilityService(
            definitions=[FeatureDefinition(id=WORKFLOW_PLATFORM_FEATURE, kind="platform", default_enabled=False)],
            config={},
        )
    )


def test_workflow_graph_requires_exactly_one_trigger() -> None:
    graph = rain_graph()
    graph["nodes"].append({"id": "manual", "type": "manual_trigger", "config": {}})

    with pytest.raises(ValidationError, match="exactly one trigger"):
        WorkflowGraph.model_validate(graph)


def test_decision_predicates_reject_arbitrary_code_operator() -> None:
    graph = rain_graph()
    graph["nodes"][2]["config"]["predicate"] = {"op": "eval", "left": "__import__('os')", "right": True}

    with pytest.raises(ValidationError, match="Unsupported decision operator"):
        WorkflowGraph.model_validate(graph)


def test_app_skill_actions_are_limited_to_v1_allowlist() -> None:
    graph = rain_graph()
    graph["nodes"][1]["config"] = {"app_id": "calendar", "skill_id": "list_events", "input": {}}

    with pytest.raises(ValidationError, match="not enabled"):
        WorkflowGraph.model_validate(graph)


def test_repeat_nodes_require_safety_bounds() -> None:
    graph = rain_graph()
    graph["nodes"].append({"id": "repeat", "type": "repeat", "config": {"max_iterations": 10}})
    graph["edges"].append({"from": "email", "to": "repeat"})

    with pytest.raises(ValidationError, match="max_duration_seconds"):
        WorkflowGraph.model_validate(graph)


def test_future_custom_code_node_is_not_executable_in_v1() -> None:
    graph = rain_graph()
    graph["nodes"].append({"id": "code", "type": "custom_code", "config": {"runtime": "python"}})

    with pytest.raises(ValidationError, match="future UI only"):
        WorkflowGraph.model_validate(graph)


def test_event_trigger_nodes_require_scoped_rate_limited_metadata() -> None:
    graph = rain_graph()
    graph["nodes"][0] = {"id": "trigger", "type": "event_trigger", "config": {}}

    with pytest.raises(ValidationError, match="event.source"):
        WorkflowGraph.model_validate(graph)

    graph["nodes"][0]["config"] = {"event": {"source": "chat_message", "scope": {}, "filters": {"phrase": "rain"}, "rate_limit": {"max_per_hour": 1}}}
    with pytest.raises(ValidationError, match="event.scope"):
        WorkflowGraph.model_validate(graph)

    graph["nodes"][0]["config"] = {"event": {"source": "chat_message", "scope": {"chat_id": "chat-1"}, "filters": {}, "rate_limit": {"max_per_hour": 1}}}
    with pytest.raises(ValidationError, match="event.filters"):
        WorkflowGraph.model_validate(graph)

    graph["nodes"][0]["config"] = {"event": {"source": "chat_message", "scope": {"chat_id": "chat-1"}, "filters": {"phrase": "rain"}, "rate_limit": {"max_per_hour": 0}}}
    with pytest.raises(ValidationError, match="event.rate_limit"):
        WorkflowGraph.model_validate(graph)

    graph["nodes"][0]["config"] = {
        "event": {
            "source": "chat_message",
            "scope": {"chat_id": "chat-1"},
            "filters": {"phrase": "rain"},
            "rate_limit": {"max_per_hour": 1},
        }
    }
    assert WorkflowGraph.model_validate(graph).nodes[0].type == "event_trigger"


def test_workflow_service_blocks_when_platform_feature_disabled() -> None:
    service = disabled_workflow_service()

    with pytest.raises(WorkflowFeatureDisabledError):
        service.create_workflow("alice", "Rain", rain_graph())


def test_workflow_service_enforces_owner_isolation() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Rain", rain_graph())

    assert service.get_workflow(workflow.id, "alice").id == workflow.id
    with pytest.raises(KeyError):
        service.get_workflow(workflow.id, "bob")


def test_workflow_definition_rows_store_sensitive_content_as_encrypted_blob_refs() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)

    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph())
    raw_workflow_rows = json.dumps(repository.workflows, sort_keys=True)
    raw_blob_rows = json.dumps(repository.encrypted_blobs, sort_keys=True)

    assert service.get_workflow(workflow.id, "alice").title == "Daily rain alert"
    assert "Daily rain alert" not in raw_workflow_rows
    assert "Berlin" not in raw_workflow_rows
    assert "weather" not in raw_workflow_rows
    assert "alice" not in raw_workflow_rows
    assert "encrypted_graph_ref" in raw_workflow_rows
    assert "Daily rain alert" not in raw_blob_rows
    assert "Berlin" not in raw_blob_rows
    assert "weather" not in raw_blob_rows
    assert "alice" not in raw_blob_rows


def test_directus_workflow_repository_persists_workflow_records_without_plaintext() -> None:
    repository = DirectusWorkflowRepository(base_url="http://directus.test", token="test-token")
    fake_client = FakeDirectusClient()
    setattr(repository, "_client", fake_client)
    service = workflow_service(repository=repository)

    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph(), enabled=True)
    loaded = service.get_workflow(workflow.id, "alice")
    raw_workflow_rows = json.dumps(fake_client.collections["workflows"], sort_keys=True)
    raw_blob_rows = json.dumps(fake_client.collections["workflow_encrypted_blobs"], sort_keys=True)

    assert loaded.id == workflow.id
    assert service.list_workflows("alice")[0].title == "Daily rain alert"
    assert "Daily rain alert" not in raw_workflow_rows
    assert "Berlin" not in raw_workflow_rows
    assert "Daily rain alert" not in raw_blob_rows
    assert "Berlin" not in raw_blob_rows


def test_workflow_cipher_uses_existing_vault_encryption_service() -> None:
    repository = InMemoryWorkflowRepository()
    encryption = FakeVaultEncryptionService()
    service = WorkflowService(
        repository=repository,
        payload_cipher=VaultWorkflowPayloadCipher(encryption),
    )

    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph(), vault_key_id="vault-key-alice")
    loaded = service.get_workflow(workflow.id, "alice", vault_key_id="vault-key-alice")
    raw_workflow_rows = json.dumps(repository.workflows, sort_keys=True)
    raw_blob_rows = json.dumps(repository.encrypted_blobs, sort_keys=True)

    assert loaded.title == "Daily rain alert"
    assert encryption.encrypt_calls
    assert encryption.decrypt_calls
    assert {call[1] for call in encryption.encrypt_calls} == {"vault-key-alice"}
    assert "Daily rain alert" not in raw_workflow_rows
    assert "Berlin" not in raw_workflow_rows
    assert "Daily rain alert" not in raw_blob_rows
    assert "Berlin" not in raw_blob_rows
    assert all(blob["ciphertext"].startswith("vault:v1:") for blob in repository.encrypted_blobs.values())


def test_workflow_vault_cipher_fails_closed_without_vault_key_id() -> None:
    service = WorkflowService(
        repository=InMemoryWorkflowRepository(),
        payload_cipher=VaultWorkflowPayloadCipher(FakeVaultEncryptionService()),
    )

    with pytest.raises(RuntimeError, match="Vault key id"):
        service.create_workflow("alice", "Daily rain alert", rain_graph())


def test_workflow_run_content_retention_defaults_updates_and_rejects_unknown_values() -> None:
    service = workflow_service()
    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph())

    assert workflow.run_content_retention == "last_5"
    assert service.update_workflow(workflow.id, "alice", run_content_retention="none").run_content_retention == "none"
    with pytest.raises(ValueError, match="not_a_mode"):
        service.update_workflow(workflow.id, "alice", run_content_retention="not_a_mode")


def test_graph_completes_without_explicit_end_node() -> None:
    graph = WorkflowGraph.model_validate(rain_graph())

    assert {node.id for node in graph.nodes} == {"trigger", "weather", "decision", "notify", "email"}


def test_workflow_template_export_excludes_runtime_context_and_imports_disabled() -> None:
    service = workflow_service()
    workflow = service.create_workflow(
        "alice",
        "Daily rain alert",
        rain_graph(),
        enabled=True,
        source="chat",
        source_chat_id="chat-1",
    )

    payload = build_workflow_template_share_payload(workflow)
    serialized = json.dumps(payload.model_dump(mode="json"), sort_keys=True)

    assert payload.title == "Daily rain alert"
    assert payload.import_enabled is False
    assert payload.binding_requirements
    assert "weather" in payload.required_app_capabilities
    assert "source_chat_id" not in serialized
    assert "next_run_at" not in serialized
    assert "workflow_run" not in serialized
    assert "connected_account" not in serialized
    assert "access_token" not in serialized


def test_workflow_template_export_excludes_notification_destinations() -> None:
    graph = rain_graph()
    graph["nodes"][3]["config"].update({"recipient": "alice@example.com", "channel": "push-device-1"})
    workflow = workflow_service().create_workflow("alice", "Notify me", graph)

    payload = build_workflow_template_share_payload(workflow)
    serialized = json.dumps(payload.model_dump(mode="json"), sort_keys=True)

    assert "alice@example.com" not in serialized
    assert "push-device-1" not in serialized
    assert "recipient" not in serialized
    assert "channel" not in serialized


def test_workflow_template_export_rejects_sensitive_recursive_keys() -> None:
    graph = rain_graph()
    graph["nodes"][1]["config"]["input"]["access_token"] = "secret-token"
    workflow = workflow_service().create_workflow("alice", "Unsafe", graph)

    with pytest.raises(WorkflowTemplateSensitiveFieldError, match="access_token"):
        build_workflow_template_share_payload(workflow)


@pytest.mark.parametrize("field_name", ["authToken", "bearer_token", "account_id", "connection_id", "provider_user_id"])
def test_workflow_template_export_rejects_sensitive_key_variants(field_name: str) -> None:
    graph = rain_graph()
    graph["nodes"][1]["config"]["input"][field_name] = "private-runtime-value"
    workflow = workflow_service().create_workflow("alice", "Unsafe", graph)

    with pytest.raises(WorkflowTemplateSensitiveFieldError, match=field_name):
        build_workflow_template_share_payload(workflow)


def test_temporary_workflow_lifecycle_can_be_kept_and_cleaned_up() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow(
        "alice",
        "Temporary rain reminder",
        rain_graph(),
        lifecycle=WorkflowLifecycle.TEMPORARY,
        source="chat",
        source_chat_id="chat-1",
        created_by_assistant=True,
    )

    assert workflow.lifecycle == WorkflowLifecycle.TEMPORARY
    assert workflow.auto_delete_at is not None
    assert workflow.auto_delete_at - workflow.created_at >= WORKFLOW_TEMPORARY_TTL_SECONDS
    assert service.list_workflows("alice") == []
    assert service.list_temporary_workflows("alice")[0].id == workflow.id

    with pytest.raises(ValueError, match="no sooner than seven days"):
        service.create_workflow(
            "alice",
            "Too short",
            rain_graph(),
            lifecycle=WorkflowLifecycle.TEMPORARY,
            auto_delete_at=workflow.created_at + WORKFLOW_TEMPORARY_TTL_SECONDS - 1,
        )

    kept = service.keep_temporary_workflow(workflow.id, "alice")

    assert kept.lifecycle == WorkflowLifecycle.PERSISTED
    assert kept.auto_delete_at is None
    assert kept.kept_at is not None
    assert service.list_workflows("alice")[0].id == workflow.id


def test_expired_temporary_workflows_are_deleted_by_cleanup_not_by_run() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow(
        "alice",
        "Expired temporary workflow",
        rain_graph(),
        lifecycle="temporary",
    )
    assert workflow.auto_delete_at is not None

    assert service.get_workflow(workflow.id, "alice").id == workflow.id
    assert service.cleanup_expired_temporary_workflows("alice", now=workflow.auto_delete_at - 1) == 0
    assert service.get_workflow(workflow.id, "alice").id == workflow.id

    assert service.cleanup_expired_temporary_workflows("alice", now=workflow.auto_delete_at + 1) == 1
    with pytest.raises(KeyError):
        service.get_workflow(workflow.id, "alice")


def test_manual_runs_validate_required_start_input_schema() -> None:
    graph = rain_graph()
    graph["nodes"][0] = {
        "id": "trigger",
        "type": "manual_trigger",
        "config": {
            "required_start_input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            }
        },
    }
    service = workflow_service()
    workflow = service.create_workflow("alice", "Manual city workflow", graph)

    with pytest.raises(WorkflowMissingInputError, match="city"):
        service.validate_manual_run_input(workflow, {})

    service.validate_manual_run_input(workflow, {"city": "Berlin"})


def test_capabilities_include_safe_v1_app_skills_and_disabled_custom_code() -> None:
    service = workflow_service()
    capabilities = {item.id: item for item in service.capabilities()}

    assert capabilities["weather:forecast"].enabled is True
    assert capabilities["news:search"].enabled is True
    assert capabilities["custom_code"].enabled is False


def test_capabilities_include_owner_scoped_persisted_workflows_only() -> None:
    service = workflow_service()
    persisted = service.create_workflow("alice", "Weekly AI news", rain_graph())
    service.create_workflow("alice", "Temporary chat workflow", rain_graph(), lifecycle="temporary")
    service.create_workflow("bob", "Bob workflow", rain_graph())

    capabilities = {item.id: item for item in service.capabilities(user_id="alice")}

    assert f"workflow:{persisted.id}" in capabilities
    assert capabilities[f"workflow:{persisted.id}"].title == "Weekly AI news"
    assert all(item.title != "Temporary chat workflow" for item in capabilities.values())
    assert all(item.title != "Bob workflow" for item in capabilities.values())
