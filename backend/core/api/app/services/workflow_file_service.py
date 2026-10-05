"""Validate and import the portable, client-parsed Workflow file document."""

from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.api.app.services.workflow_models import (
    WorkflowDetail,
    WorkflowGraph,
    WorkflowNodeType,
    WorkflowRunContentRetention,
    validate_workflow_composition_refs,
)
from backend.core.api.app.services.workflow_service import WorkflowService


class WorkflowFileImportError(ValueError):
    """The file is unsupported or contains unsafe/invalid authoring data."""


class WorkflowFileTooLargeError(WorkflowFileImportError):
    """The parsed document exceeds the bounded import envelope."""


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkflowFileDefinition(_FileModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    run_content_retention: Literal["last_5", "none"]
    graph: dict[str, Any]


class WorkflowFileDocument(_FileModel):
    format: Literal["openmates-workflow"]
    format_version: Literal[1]
    workflow: WorkflowFileDefinition
    binding_requirements: list[dict[str, Any]]


_FORBIDDEN_FIELDS = {
    "token", "accesstoken", "refreshtoken", "authtoken", "bearertoken",
    "secret", "credential", "credentials", "password", "apikey", "privatekey",
    "vaultkey", "masterkey", "encryptionkey", "authorization", "grant",
    "grantid", "accountid", "connectedaccountid", "connectionid", "provideruserid",
    "userid", "ownerid", "ownerhash", "projectid", "teamid", "workflowid",
    "versionid", "runid", "chatid", "sourcechatid", "sessionid",
    "sessioncookie", "cookie", "vault", "claimtoken", "deliveryid", "deliveryhistory",
    "encryptedgraphref", "encryptedgraphblobref", "encryptedcontentref", "encryptedpayload",
    "encryptedkey", "ciphertext", "fragmentkey", "shortkey", "templatekey",
    "nextrunat", "lastrunat", "providerresponse", "runhistory",
}
_CREDENTIAL_SUFFIXES = (
    "accesstoken", "refreshtoken", "authtoken", "bearertoken", "sessiontoken",
    "apikey", "privatekey", "clientsecret", "secret", "password", "credential",
    "credentials", "authorization", "vaultkey", "masterkey", "encryptionkey",
)
_GRAPH_FIELDS = {"version", "trigger_node_id", "nodes", "edges", "variables", "limits", "ui_layout"}
_NODE_FIELDS = {"id", "type", "title", "config", "input_mapping", "ui"}
_EDGE_FIELDS = {"from", "to", "branch"}
_STRUCTURED_REF = re.compile(r"\$nodes\.([A-Za-z0-9_-]+)(?=\.|\b)")
_INLINE_REF = re.compile(r"(\{\{\s*steps\.)([A-Za-z0-9_-]+)(?=\.|\s*\}\})")
WORKFLOW_FILE_MAX_BYTES = 1_048_576
_MAX_DOCUMENT_DEPTH = 64
_MAX_DOCUMENT_ITEMS = 50_000


def _bounded_document(payload: dict[str, Any] | WorkflowFileDocument) -> None:
    """Bound untrusted nested JSON before recursive scanning or graph remapping."""
    if isinstance(payload, WorkflowFileDocument):
        definition = payload.workflow
        value: Any = {
            "format": payload.format, "format_version": payload.format_version,
            "workflow": {
                "title": definition.title, "description": definition.description,
                "run_content_retention": definition.run_content_retention,
                "graph": definition.graph,
            },
            "binding_requirements": payload.binding_requirements,
        }
    else:
        value = payload
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        if depth > _MAX_DOCUMENT_DEPTH:
            raise WorkflowFileImportError("Workflow file is nested too deeply")
        count += 1
        if count > _MAX_DOCUMENT_ITEMS:
            raise WorkflowFileTooLargeError("Workflow file contains too many items")
        if isinstance(item, dict):
            count += len(item)
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        if count > _MAX_DOCUMENT_ITEMS:
            raise WorkflowFileTooLargeError("Workflow file contains too many items")
    try:
        byte_count = 0
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":")).iterencode(value):
            byte_count += len(chunk.encode("utf-8"))
            if byte_count > WORKFLOW_FILE_MAX_BYTES:
                raise WorkflowFileTooLargeError("Workflow file exceeds 1 MB")
    except WorkflowFileTooLargeError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise WorkflowFileImportError("Workflow file contains invalid JSON values") from exc


def _reject_unknown_fields(value: Any, allowed: set[str], path: str) -> None:
    if not isinstance(value, dict):
        raise WorkflowFileImportError(f"{path} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise WorkflowFileImportError(f"{path} contains unsupported fields: {sorted(unknown)}")


def _reject_sensitive_fields(value: Any, path: str = "$.workflow.graph") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in _FORBIDDEN_FIELDS or normalized.endswith(_CREDENTIAL_SUFFIXES):
                raise WorkflowFileImportError(f"{path}.{key} contains a private or runtime field")
            _reject_sensitive_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, f"{path}[{index}]")


def _derive_bindings(graph: WorkflowGraph) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for node in graph.nodes:
        if node.type == WorkflowNodeType.SCHEDULE_TRIGGER:
            bindings.append({"type": "schedule", "node_id": node.id})
        elif node.type == WorkflowNodeType.APP_SKILL_ACTION:
            bindings.append({
                "type": "app_skill", "node_id": node.id,
                "app_id": node.config["app_id"], "skill_id": node.config["skill_id"],
            })
        elif node.type == WorkflowNodeType.SEND_CHAT_MESSAGE and node.config.get("destination_required") is True:
            bindings.append({"type": "chat_destination", "node_id": node.id})
        elif node.type in {WorkflowNodeType.SEND_NOTIFICATION, WorkflowNodeType.SEND_EMAIL_NOTIFICATION}:
            bindings.append({"type": "notification_preferences", "node_id": node.id})
    return bindings


def _remap_value(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _remap_value(child, id_map) for key, child in value.items()}
    if isinstance(value, list):
        return [_remap_value(child, id_map) for child in value]
    if isinstance(value, str):
        def mapped(node_id: str) -> str:
            if node_id not in id_map:
                raise WorkflowFileImportError(f"Reference to unknown step: {node_id}")
            return id_map[node_id]
        value = _STRUCTURED_REF.sub(lambda match: "$nodes." + mapped(match.group(1)), value)
        value = re.sub(r"\$items\.([A-Za-z0-9_-]+)(?=\.|\b)", lambda match: "$items." + mapped(match.group(1)), value)
        value = re.sub(r"(\{\{\s*items\.)([A-Za-z0-9_-]+)(?=\.|\s*\}\})", lambda match: match.group(1) + mapped(match.group(2)), value)
        return _INLINE_REF.sub(lambda match: match.group(1) + mapped(match.group(2)), value)
    return value


def _remap_graph(graph: WorkflowGraph) -> WorkflowGraph:
    id_map = {node.id: str(uuid.uuid4()) for node in graph.nodes}
    data = graph.model_dump(mode="json", by_alias=True)
    layout = data.pop("ui_layout")
    data = _remap_value(data, id_map)
    data["ui_layout"] = _remap_value(layout, id_map)
    data["ui_layout"] = {id_map.get(key, key): child for key, child in data["ui_layout"].items()}
    data["trigger_node_id"] = id_map.get(graph.trigger_node_id) if graph.trigger_node_id else None
    for node in data["nodes"]:
        node["id"] = id_map[node["id"]]
    for edge in data["edges"]:
        edge["from"] = id_map[edge["from"]]
        edge["to"] = id_map[edge["to"]]
    return WorkflowGraph.model_validate(data)


class WorkflowFileService:
    def __init__(self, workflow_service: WorkflowService) -> None:
        self.workflow_service = workflow_service

    def export_document(self, workflow: WorkflowDetail) -> WorkflowFileDocument:
        """Canonical portable definition: never include owner, runtime or chat IDs."""
        graph = deepcopy(workflow.graph.model_dump(mode="json", by_alias=True))
        id_map = {node["id"]: f"step_{index + 1}" for index, node in enumerate(graph["nodes"])}
        for node in graph["nodes"]:
            if node["type"] == WorkflowNodeType.SEND_CHAT_MESSAGE.value:
                config = node["config"]
                bound = config.pop("chat_id", None)
                if bound or config.get("destination_required") or any(
                    item.get("type") == "chat_destination" and item.get("node_id") == node["id"]
                    for item in workflow.binding_requirements
                ):
                    config["destination_required"] = True
        layout = graph.pop("ui_layout", {})
        graph = _remap_value(graph, id_map)
        graph["ui_layout"] = {id_map.get(key, key): _remap_value(child, id_map) for key, child in layout.items()}
        graph["trigger_node_id"] = id_map.get(graph["trigger_node_id"]) if graph["trigger_node_id"] else None
        for node in graph["nodes"]:
            node["id"] = id_map[node["id"]]
        for edge in graph["edges"]:
            edge["from"], edge["to"] = id_map[edge["from"]], id_map[edge["to"]]
        portable_graph = WorkflowGraph.model_validate(graph)
        document = WorkflowFileDocument(
            format="openmates-workflow", format_version=1,
            workflow=WorkflowFileDefinition(title=workflow.title, description=workflow.description,
                run_content_retention=workflow.run_content_retention.value, graph=graph),
            binding_requirements=_derive_bindings(portable_graph),
        )
        self.validate_document(document)
        return document

    def validate_document(self, payload: dict[str, Any] | WorkflowFileDocument) -> tuple[WorkflowFileDocument, WorkflowGraph]:
        try:
            _bounded_document(payload)
            document = payload if isinstance(payload, WorkflowFileDocument) else WorkflowFileDocument.model_validate(payload)
            if not document.workflow.title.strip():
                raise WorkflowFileImportError("Workflow file requires a non-empty title")
            data = document.workflow.graph
            _reject_unknown_fields(data, _GRAPH_FIELDS, "$.workflow.graph")
            if isinstance(data.get("version"), bool) or not isinstance(data.get("version"), int) or data["version"] < 1:
                raise WorkflowFileImportError("Workflow graph version must be a positive integer")
            for index, node in enumerate(data.get("nodes") or []):
                _reject_unknown_fields(node, _NODE_FIELDS, f"$.workflow.graph.nodes[{index}]")
                if node.get("type") == WorkflowNodeType.SEND_CHAT_MESSAGE.value:
                    config = node.get("config") or {}
                    if "chat_id" in config:
                        raise WorkflowFileImportError("Portable message destinations must omit chat_id")
                    if config.get("destination_required") not in {None, True}:
                        raise WorkflowFileImportError("destination_required must be true when present")
            for index, edge in enumerate(data.get("edges") or []):
                _reject_unknown_fields(edge, _EDGE_FIELDS, f"$.workflow.graph.edges[{index}]")
            _reject_sensitive_fields(data)
            graph = WorkflowGraph.model_validate(data)
            validate_workflow_composition_refs(graph)
            expected = _derive_bindings(graph)
            declared = document.binding_requirements
            if len(declared) != len(expected) or {tuple(sorted(item.items())) for item in declared} != {tuple(sorted(item.items())) for item in expected}:
                raise WorkflowFileImportError("Binding requirements do not match the authored graph")
            return document, _remap_graph(graph)
        except (ValidationError, KeyError, TypeError) as exc:
            raise WorkflowFileImportError(str(exc)) from exc

    def import_document(
        self, user_id: str, document: WorkflowFileDocument, graph: WorkflowGraph,
        vault_key_id: str | None = None,
    ) -> WorkflowDetail:
        workflow = self.workflow_service.create_workflow(
            user_id, document.workflow.title, graph,
            enabled=False, source="import", vault_key_id=vault_key_id,
            description=document.workflow.description,
            run_content_retention=WorkflowRunContentRetention(document.workflow.run_content_retention),
            initial_binding_requirements=_derive_bindings(graph),
        )
        return workflow
