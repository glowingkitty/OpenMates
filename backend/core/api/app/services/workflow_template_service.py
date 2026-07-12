# backend/core/api/app/services/workflow_template_service.py
#
# Persistent storage and import validation for opaque, client-encrypted Workflow
# template projections. Runtime workflow data remains authoritative and Vault
# encrypted; this service never decrypts projection ciphertext or template keys.
#
# Spec: docs/specs/workflows-v1/spec.yml (TASK-5, T-PYTEST-008)

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.api.app.services.workflow_models import WorkflowDetail, WorkflowGraph, WorkflowNodeType
from backend.core.api.app.services.workflow_service import WorkflowService


FORBIDDEN_TEMPLATE_FIELD_PARTS = {
    "token",
    "refreshtoken",
    "accesstoken",
    "authtoken",
    "bearertoken",
    "secret",
    "credential",
    "accountid",
    "connectionid",
    "connectedaccountid",
    "provideruserid",
    "webhooksecret",
    "apikey",
    "password",
    "vault",
    "grant",
    "runid",
    "versionid",
    "workflowid",
    "nextrunat",
    "claim",
    "wait",
    "output",
    "providerresponse",
    "sourcechatid",
    "encryptedgraphblobref",
    "encryptedcontentref",
    "fragmentkey",
    "shortkey",
    "templatekey",
}


class WorkflowTemplateProjectionError(ValueError):
    """Raised when an opaque template projection cannot be persisted."""


class WorkflowTemplateProjectionStaleError(WorkflowTemplateProjectionError):
    """Raised when a client snapshot predates the current runtime workflow."""


class WorkflowTemplateImportError(ValueError):
    """Raised when a client-decrypted template is not safe to import."""


class WorkflowTemplateProjectionRecord(BaseModel):
    """Opaque persistent record used for owner cross-device and share flows."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=200)
    workflow_id: str = Field(min_length=1, max_length=200)
    owner_hash: str = Field(min_length=1)
    source_version: int = Field(ge=1)
    projection_schema_version: int = Field(ge=1)
    ciphertext: str = Field(min_length=1, max_length=100_000)
    ciphertext_checksum: str = Field(min_length=1, max_length=200)
    owner_wrapped_key: str = Field(min_length=1, max_length=100_000)
    created_at: int
    updated_at: int
    revoked_at: int | None = None


class WorkflowTemplateImportPayload(BaseModel):
    """Portable plaintext accepted only after client-side decryption."""

    model_config = ConfigDict(extra="forbid")

    template_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    trigger_template: dict[str, Any]
    node_templates: list[dict[str, Any]] = Field(default_factory=list)
    edge_templates: list[dict[str, Any]] = Field(default_factory=list)
    variables_schema: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list)
    binding_requirements: list[dict[str, Any]] = Field(default_factory=list)


class ImportedWorkflowTemplate(BaseModel):
    """Recipient-owned disabled runtime workflow and required local bindings."""

    workflow: WorkflowDetail
    binding_requirements: list[dict[str, Any]]


class WorkflowTemplateProjectionService:
    """Owns one-way client template projection persistence and recipient import."""

    def __init__(self, workflow_service: WorkflowService) -> None:
        self.workflow_service = workflow_service
        self.repository = workflow_service.repository

    def upsert_projection(
        self,
        workflow_id: str,
        user_id: str,
        *,
        template_id: str,
        source_version: int,
        ciphertext: str,
        ciphertext_checksum: str,
        owner_wrapped_key: str,
        projection_schema_version: int,
    ) -> WorkflowTemplateProjectionRecord:
        """Persist client ciphertext without changing the runtime workflow state."""
        self.workflow_service.ensure_enabled()
        workflow = self.workflow_service.get_workflow(workflow_id, user_id)
        if source_version < workflow.version:
            raise WorkflowTemplateProjectionStaleError("source_version is older than the current workflow version")
        if source_version != workflow.version:
            raise WorkflowTemplateProjectionError("source_version must match the current workflow version")

        existing = self.repository.get_template_projection_for_workflow(workflow_id, user_id)
        if existing and existing["template_id"] != template_id:
            raise WorkflowTemplateProjectionError("A workflow projection must keep its stable template_id")

        now = int(time.time())
        record = WorkflowTemplateProjectionRecord(
            template_id=template_id,
            workflow_id=workflow_id,
            owner_hash=existing["owner_hash"] if existing else self.repository.workflow_owner_hash(user_id),
            source_version=source_version,
            projection_schema_version=projection_schema_version,
            ciphertext=ciphertext,
            ciphertext_checksum=ciphertext_checksum,
            owner_wrapped_key=owner_wrapped_key,
            created_at=existing["created_at"] if existing else now,
            updated_at=now,
            revoked_at=existing.get("revoked_at") if existing else None,
        )
        return WorkflowTemplateProjectionRecord.model_validate(self.repository.save_template_projection(record.model_dump()))

    def import_template(self, user_id: str, payload: dict[str, Any] | WorkflowTemplateImportPayload) -> ImportedWorkflowTemplate:
        """Create a fresh recipient-owned disabled runtime workflow from a portable template."""
        self.workflow_service.ensure_enabled()
        try:
            template = payload if isinstance(payload, WorkflowTemplateImportPayload) else WorkflowTemplateImportPayload.model_validate(payload)
        except ValidationError as exc:
            raise WorkflowTemplateImportError(str(exc)) from exc

        template_data = template.model_dump(mode="json")
        _reject_forbidden_template_fields(template_data)
        graph = _graph_from_template(template)
        _validate_declared_capabilities(graph, template.required_capabilities)
        _validate_binding_requirements(graph, template.binding_requirements)

        imported_graph, binding_requirements = _with_recipient_runtime_node_ids(graph)
        workflow = self.workflow_service.create_workflow(
            user_id,
            template.title,
            imported_graph,
            enabled=False,
            source="import",
            description=template.description,
        )
        return ImportedWorkflowTemplate(workflow=workflow, binding_requirements=binding_requirements)


def _reject_forbidden_template_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            if any(forbidden in normalized_key for forbidden in FORBIDDEN_TEMPLATE_FIELD_PARTS):
                raise WorkflowTemplateImportError(f"Workflow template contains forbidden field at {path}.{key}")
            _reject_forbidden_template_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_template_fields(child, f"{path}[{index}]")


def _graph_from_template(template: WorkflowTemplateImportPayload) -> WorkflowGraph:
    try:
        return WorkflowGraph.model_validate(
            {
                "version": template.template_version,
                "trigger_node_id": template.trigger_template.get("id"),
                "nodes": [template.trigger_template, *template.node_templates],
                "edges": template.edge_templates,
                "variables": {"schema": template.variables_schema},
            }
        )
    except ValidationError as exc:
        raise WorkflowTemplateImportError(str(exc)) from exc


def _required_capabilities(graph: WorkflowGraph) -> set[str]:
    capabilities: set[str] = set()
    for node in graph.nodes:
        if node.type != WorkflowNodeType.APP_SKILL_ACTION:
            continue
        app_id = str(node.config.get("app_id") or "").strip()
        skill_id = str(node.config.get("skill_id") or "").strip()
        if app_id:
            capabilities.add(app_id)
        if app_id and skill_id:
            capabilities.add(f"{app_id}.{skill_id}")
    return capabilities


def _binding_requirements(graph: WorkflowGraph) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for node in graph.nodes:
        if node.type == WorkflowNodeType.SCHEDULE_TRIGGER:
            requirements.append({"type": "schedule", "node_id": node.id})
        elif node.type == WorkflowNodeType.APP_SKILL_ACTION:
            requirements.append(
                {
                    "type": "app_skill",
                    "node_id": node.id,
                    "app_id": node.config.get("app_id"),
                    "skill_id": node.config.get("skill_id"),
                }
            )
        elif node.type in {WorkflowNodeType.SEND_NOTIFICATION, WorkflowNodeType.SEND_EMAIL_NOTIFICATION}:
            requirements.append({"type": "notification_preferences", "node_id": node.id})
    return requirements


def _validate_declared_capabilities(graph: WorkflowGraph, declared_capabilities: list[str]) -> None:
    missing = _required_capabilities(graph).difference(declared_capabilities)
    if missing:
        raise WorkflowTemplateImportError(f"Workflow template is missing required capability declarations: {sorted(missing)}")


def _validate_binding_requirements(graph: WorkflowGraph, declared_requirements: list[dict[str, Any]]) -> None:
    expected = {(item["type"], item["node_id"]) for item in _binding_requirements(graph)}
    declared = {
        (str(item.get("type") or ""), str(item.get("node_id") or ""))
        for item in declared_requirements
        if isinstance(item, dict)
    }
    missing = expected.difference(declared)
    if missing:
        raise WorkflowTemplateImportError(f"Workflow template is missing binding requirements: {sorted(missing)}")


def _with_recipient_runtime_node_ids(graph: WorkflowGraph) -> tuple[WorkflowGraph, list[dict[str, Any]]]:
    node_id_map = {node.id: str(uuid.uuid4()) for node in graph.nodes}
    graph_data = graph.model_dump(mode="json", by_alias=True)
    graph_data["trigger_node_id"] = node_id_map[graph.trigger_node_id]
    for node in graph_data["nodes"]:
        node["id"] = node_id_map[node["id"]]
    for edge in graph_data["edges"]:
        edge["from"] = node_id_map[edge["from"]]
        edge["to"] = node_id_map[edge["to"]]
    imported_graph = WorkflowGraph.model_validate(graph_data)
    return imported_graph, _binding_requirements(imported_graph)
