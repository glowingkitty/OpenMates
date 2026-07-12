# backend/tests/test_workflow_template_projection.py
#
# Focused contract coverage for the persistent client-encrypted Workflow template
# projection. The service receives opaque client ciphertext only; template
# plaintext is validated locally at import before a new runtime workflow exists.
#
# Spec: docs/specs/workflows-v1/spec.yml (T-PYTEST-008, TASK-5)

from __future__ import annotations

import copy
import json

import pytest

from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.core.api.app.services.workflow_template_service import (
    WorkflowTemplateImportError,
    WorkflowTemplateProjectionService,
    WorkflowTemplateProjectionStaleError,
)
from backend.tests.test_workflows_models import rain_graph
from backend.tests.workflow_test_utils import workflow_service


def template_payload() -> dict[str, object]:
    graph = rain_graph()
    return {
        "template_version": 1,
        "title": "Daily rain alert",
        "description": "Notify me when rain is likely.",
        "trigger_template": graph["nodes"][0],
        "node_templates": graph["nodes"][1:],
        "edge_templates": graph["edges"],
        "variables_schema": {},
        "required_capabilities": ["weather", "weather.forecast"],
        "binding_requirements": [
            {"type": "schedule", "node_id": "trigger"},
            {"type": "app_skill", "node_id": "weather", "app_id": "weather", "skill_id": "forecast"},
            {"type": "notification_preferences", "node_id": "notify"},
            {"type": "notification_preferences", "node_id": "email"},
        ],
    }


def projection_service() -> tuple[WorkflowTemplateProjectionService, object]:
    repository = InMemoryWorkflowRepository()
    runtime_service = workflow_service(repository=repository)
    return WorkflowTemplateProjectionService(runtime_service), runtime_service


def test_projection_persists_opaque_client_ciphertext_and_rejects_stale_snapshots() -> None:
    service, runtime_service = projection_service()
    workflow = runtime_service.create_workflow("alice", "Daily rain alert", rain_graph(), enabled=True)
    runtime_before = copy.deepcopy(runtime_service.repository.workflows[workflow.id])

    projection = service.upsert_projection(
        workflow.id,
        "alice",
        template_id="template-rain-v1",
        source_version=workflow.version,
        ciphertext="client:aes-gcm:ciphertext",
        ciphertext_checksum="sha256:opaque-ciphertext",
        owner_wrapped_key="owner:wrapped-template-key",
        projection_schema_version=1,
    )

    assert projection.template_id == "template-rain-v1"
    assert projection.source_version == workflow.version
    assert projection.ciphertext == "client:aes-gcm:ciphertext"
    assert projection.owner_wrapped_key == "owner:wrapped-template-key"
    assert runtime_service.repository.workflows[workflow.id] == runtime_before
    assert "Daily rain alert" not in json.dumps(runtime_service.repository.template_projections, sort_keys=True)

    runtime_service.update_workflow(workflow.id, "alice", title="Updated rain alert")
    with pytest.raises(WorkflowTemplateProjectionStaleError):
        service.upsert_projection(
            workflow.id,
            "alice",
            template_id="template-rain-v1",
            source_version=workflow.version,
            ciphertext="client:aes-gcm:new-ciphertext",
            ciphertext_checksum="sha256:new-opaque-ciphertext",
            owner_wrapped_key="owner:new-wrapped-template-key",
            projection_schema_version=1,
        )


def test_template_import_rejects_runtime_fields_and_creates_disabled_recipient_workflow() -> None:
    service, runtime_service = projection_service()
    unsafe_payload = template_payload()
    unsafe_payload["node_templates"][0]["config"]["connected_account_id"] = "sender-account"

    with pytest.raises(WorkflowTemplateImportError, match="connected_account_id"):
        service.import_template("bob", unsafe_payload)

    imported = service.import_template("bob", template_payload())

    assert imported.workflow.id != "template-rain-v1"
    assert imported.workflow.enabled is False
    assert imported.workflow.status.value == "disabled"
    assert imported.workflow.source == "import"
    assert imported.workflow.title == "Daily rain alert"
    assert {requirement["type"] for requirement in imported.binding_requirements} == {
        "schedule",
        "app_skill",
        "notification_preferences",
    }
    assert runtime_service.list_workflows("alice") == []
    assert runtime_service.list_workflows("bob")[0].id == imported.workflow.id
    assert imported.workflow.graph.trigger_node_id != "trigger"


@pytest.mark.parametrize(
    "field_name",
    ["workflow_id", "version_id", "next_run_at", "claim_token", "wait_id", "output", "provider_response", "grant"],
)
def test_template_import_rejects_recursive_runtime_and_sensitive_fields(field_name: str) -> None:
    service, _runtime_service = projection_service()
    payload = template_payload()
    payload["node_templates"][0]["config"][field_name] = "forbidden"

    with pytest.raises(WorkflowTemplateImportError, match=field_name):
        service.import_template("bob", payload)
