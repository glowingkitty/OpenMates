# backend/core/api/app/services/workflow_models.py
#
# Typed workflow graph, run, and validation models for Workflows V1. These
# models are deliberately independent from FastAPI and Directus so the runner,
# routes, CLI/SDK tests, and Apple parity tests share one contract.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"
    DELETED = "deleted"


class WorkflowRunStatus(str, Enum):
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    CANCELLATION_REQUESTED = "cancellation_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED_BY_USER = "skipped_by_user"


class WorkflowNodeRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class WorkflowRunContentRetention(str, Enum):
    LAST_5 = "last_5"
    NONE = "none"


class WorkflowRunContentStorage(str, Enum):
    DURABLE = "durable"
    EPHEMERAL = "ephemeral"
    DELETED = "deleted"


class WorkflowLifecycle(str, Enum):
    PERSISTED = "persisted"
    TEMPORARY = "temporary"


class WorkflowAssistantProposalAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RUN = "run"


class WorkflowAssistantProposalStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class WorkflowAssistantProposal(BaseModel):
    """Safe proposal metadata surfaced to approval clients and assistant skills."""

    proposal_id: str
    action: WorkflowAssistantProposalAction
    status: WorkflowAssistantProposalStatus
    workflow_id: str | None = None
    lifecycle: WorkflowLifecycle | None = None
    title: str | None = None
    required_input_summary: list[str] = Field(default_factory=list)
    expected_actions: list[str] = Field(default_factory=list)
    risk_level: str
    requires_approval: bool = True
    created_at: int
    expires_at: int
    resolved_at: int | None = None
    result_id: str | None = None


class WorkflowNodeType(str, Enum):
    SCHEDULE_TRIGGER = "schedule_trigger"
    MANUAL_TRIGGER = "manual_trigger"
    WEBHOOK_TRIGGER = "webhook_trigger"
    EVENT_TRIGGER = "event_trigger"
    APP_SKILL_ACTION = "app_skill_action"
    DECISION = "decision"
    CHECK = "check"
    SEND_CHAT_MESSAGE = "send_chat_message"
    REPEAT = "repeat"
    CREATE_CHAT_REPORT = "create_chat_report"
    START_NEW_CHAT = "start_new_chat"
    SEND_NOTIFICATION = "send_notification"
    SEND_EMAIL_NOTIFICATION = "send_email_notification"
    ASK_USER = "ask_user"
    WAIT = "wait"
    CUSTOM_CODE = "custom_code"
    END = "end"


SUPPORTED_DECISION_OPERATORS = {
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "starts_with",
    "exists",
    "and",
    "or",
    "not",
}
EXECUTABLE_NODE_TYPES = {
    WorkflowNodeType.SCHEDULE_TRIGGER,
    WorkflowNodeType.MANUAL_TRIGGER,
    WorkflowNodeType.APP_SKILL_ACTION,
    WorkflowNodeType.DECISION,
    WorkflowNodeType.CHECK,
    WorkflowNodeType.SEND_CHAT_MESSAGE,
    WorkflowNodeType.REPEAT,
    WorkflowNodeType.CREATE_CHAT_REPORT,
    WorkflowNodeType.START_NEW_CHAT,
    WorkflowNodeType.SEND_NOTIFICATION,
    WorkflowNodeType.SEND_EMAIL_NOTIFICATION,
    WorkflowNodeType.ASK_USER,
    WorkflowNodeType.WAIT,
    WorkflowNodeType.EVENT_TRIGGER,
    WorkflowNodeType.END,
}
DISABLED_FUTURE_NODE_TYPES = {
    WorkflowNodeType.WEBHOOK_TRIGGER,
    WorkflowNodeType.CUSTOM_CODE,
}
QUALIFYING_WORKFLOW_EFFECT_TYPES = {
    WorkflowNodeType.SEND_CHAT_MESSAGE,
    WorkflowNodeType.CREATE_CHAT_REPORT,
    WorkflowNodeType.START_NEW_CHAT,
    WorkflowNodeType.SEND_NOTIFICATION,
    WorkflowNodeType.SEND_EMAIL_NOTIFICATION,
}
FORBIDDEN_WORKFLOW_TEMPLATE_KEYS = {
    "token",
    "refreshtoken",
    "accesstoken",
    "authtoken",
    "bearertoken",
    "secret",
    "credential",
    "credentials",
    "accountid",
    "connectionid",
    "connectedaccountid",
    "provideruserid",
    "webhooksecret",
    "apikey",
    "password",
    "vault",
    "runid",
}


class WorkflowValidationError(ValueError):
    """Raised when a workflow graph violates the V1 executable contract."""


class WorkflowMissingInputError(ValueError):
    """Raised when a manual workflow run lacks required trigger input."""


class WorkflowTemplateSensitiveFieldError(ValueError):
    """Raised when workflow template export sees runtime-only or secret fields."""


class WorkflowEdge(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    branch: str | None = None

    model_config = {"populate_by_name": True}


class WorkflowNode(BaseModel):
    id: str
    type: WorkflowNodeType
    title: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    input_mapping: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)


class WorkflowGraph(BaseModel):
    version: int = 1
    trigger_node_id: str | None = None
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    ui_layout: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self) -> "WorkflowGraph":
        validate_workflow_graph(self)
        return self


class WorkflowSummary(BaseModel):
    id: str
    version: int = 1
    title: str
    encrypted_slug: str | None = None
    slug_lookup_hash: str | None = None
    description: str | None = None
    category: str = "general_knowledge"
    icon: str = "help-circle"
    status: WorkflowStatus
    enabled: bool
    lifecycle: WorkflowLifecycle = WorkflowLifecycle.PERSISTED
    source: str = "manual"
    source_chat_id: str | None = None
    created_by_assistant: bool = False
    auto_delete_at: int | None = None
    kept_at: int | None = None
    trigger_summary: str | None = None
    next_run_at: int | None = None
    last_run_status: WorkflowRunStatus | None = None
    run_content_retention: WorkflowRunContentRetention = WorkflowRunContentRetention.LAST_5
    current_version_id: str
    created_at: int
    updated_at: int


class WorkflowDetail(WorkflowSummary):
    graph: WorkflowGraph


class WorkflowVersionSummary(BaseModel):
    version_id: str
    version_number: int
    created_at: int
    created_by_client: str
    graph_hash: str
    restored_from_version_id: str | None = None
    current: bool = False
    change_summary: dict[str, Any] | None = None


class WorkflowVersionDetail(WorkflowVersionSummary):
    graph: WorkflowGraph


class WorkflowNodeRun(BaseModel):
    id: str
    run_id: str
    workflow_id: str
    node_id: str
    node_type: WorkflowNodeType
    status: WorkflowNodeRunStatus
    started_at: int | None = None
    finished_at: int | None = None
    attempt: int = 1
    skipped_reason: str | None = None
    error_code: str | None = None
    error_summary: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    credit_cost: int = 0


class WorkflowRunSummary(BaseModel):
    id: str
    workflow_id: str
    version_id: str
    trigger_type: str
    status: WorkflowRunStatus
    started_at: int | None = None
    finished_at: int | None = None
    error_summary: str | None = None
    cost_summary: dict[str, Any] = Field(default_factory=dict)
    content_retention_mode: WorkflowRunContentRetention = WorkflowRunContentRetention.LAST_5
    content_available: bool = False
    content_storage: WorkflowRunContentStorage | None = None
    content_expires_at: int | None = None
    encrypted_content_ref: str | None = None
    encrypted_content_checksum: str | None = None
    cancellation_requested_at: int | None = None
    cancelled_at: int | None = None


class WorkflowRunDetail(WorkflowRunSummary):
    node_runs: list[WorkflowNodeRun] = Field(default_factory=list)
    output_summary: dict[str, Any] = Field(default_factory=dict)


class WorkflowCapability(BaseModel):
    type: Literal["node", "app_skill", "workflow"]
    id: str
    title: str
    enabled: bool = True
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowTemplateSharePayload(BaseModel):
    template_version: int = 1
    title: str
    description: str | None = None
    trigger_template: dict[str, Any]
    node_templates: list[dict[str, Any]] = Field(default_factory=list)
    edge_templates: list[dict[str, Any]] = Field(default_factory=list)
    variables_schema: dict[str, Any] = Field(default_factory=dict)
    required_app_capabilities: list[str] = Field(default_factory=list)
    binding_requirements: list[dict[str, Any]] = Field(default_factory=list)
    created_at: int
    import_enabled: bool = False


def validate_workflow_graph(graph: WorkflowGraph) -> None:
    node_ids = [node.id for node in graph.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise WorkflowValidationError("Duplicate workflow node ids are not allowed")

    nodes_by_id = {node.id: node for node in graph.nodes}
    trigger_nodes = [
        node for node in graph.nodes
        if node.type in {WorkflowNodeType.SCHEDULE_TRIGGER, WorkflowNodeType.MANUAL_TRIGGER, WorkflowNodeType.WEBHOOK_TRIGGER, WorkflowNodeType.EVENT_TRIGGER}
    ]
    if len(trigger_nodes) > 1:
        raise WorkflowValidationError("Workflows V1 must contain exactly one trigger node")
    if not trigger_nodes:
        if graph.trigger_node_id is not None:
            raise WorkflowValidationError("trigger_node_id must be null when a workflow has no trigger node")
    elif graph.trigger_node_id not in nodes_by_id:
        raise WorkflowValidationError("trigger_node_id must reference an existing node")
    elif trigger_nodes[0].id != graph.trigger_node_id:
        raise WorkflowValidationError("trigger_node_id must point to the only trigger node")

    for node in graph.nodes:
        if node.type in DISABLED_FUTURE_NODE_TYPES:
            raise WorkflowValidationError(f"Node type {node.type.value} is represented for future UI only and cannot run in V1")
        if node.type not in EXECUTABLE_NODE_TYPES:
            raise WorkflowValidationError(f"Unsupported node type: {node.type.value}")
        _validate_node_config(node)

    for edge in graph.edges:
        if edge.from_node not in nodes_by_id or edge.to_node not in nodes_by_id:
            raise WorkflowValidationError("Workflow edges must reference existing nodes")
        if nodes_by_id[edge.from_node].type == WorkflowNodeType.DECISION and not edge.branch:
            raise WorkflowValidationError("Decision node edges must include a branch label")

    if graph.version >= 2:
        _validate_builder_graph(graph, nodes_by_id)


def _validate_builder_graph(graph: WorkflowGraph, nodes_by_id: dict[str, WorkflowNode]) -> None:
    """Check modern builder ordering without changing historical graph semantics."""
    predecessors: dict[str, set[str]] = {node_id: set() for node_id in nodes_by_id}
    successors: dict[str, set[str]] = {node_id: set() for node_id in nodes_by_id}
    edge_keys = set()
    for edge in graph.edges:
        key = (edge.from_node, edge.branch)
        if key in edge_keys:
            raise WorkflowValidationError("Each node branch may have only one next step")
        edge_keys.add(key)
        if edge.branch and nodes_by_id[edge.from_node].type != WorkflowNodeType.CHECK:
            raise WorkflowValidationError("Only Check steps may have branches")
        if edge.branch not in {None, "yes", "no", "true", "false", "unsure", "default"}:
            raise WorkflowValidationError("Check branches must be true, false, unsure or default")
        if edge.branch == "unsure" and nodes_by_id[edge.from_node].config.get("mode", "exact") != "ai":
            raise WorkflowValidationError("Only an AI Check may have an Unsure branch")
        predecessors[edge.to_node].add(edge.from_node)
        successors[edge.from_node].add(edge.to_node)
    pending = [node_id for node_id, parents in predecessors.items() if not parents]
    remaining = {node_id: len(parents) for node_id, parents in predecessors.items()}
    ancestors: dict[str, set[str]] = {}
    for node_id in pending:
        parents = predecessors[node_id]
        ancestors[node_id] = set().union(*(ancestors[parent] | {parent} for parent in parents)) if parents else set()
        for child in successors[node_id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                pending.append(child)
    if len(ancestors) != len(nodes_by_id):
        raise WorkflowValidationError("Workflow steps cannot contain cycles")
    def references(value: Any):
        if isinstance(value, str):
            yield from re.findall(r"\$nodes\.([A-Za-z0-9_-]+)\.", value)
            yield from re.findall(r"\{\{\s*steps\.([A-Za-z0-9_-]+)(?:\.|\s*\}\})", value)
        elif isinstance(value, dict):
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)
    branch_scopes: list[set[str]] = []
    for check in graph.nodes:
        if check.type != WorkflowNodeType.CHECK:
            continue
        outgoing = [edge for edge in graph.edges if edge.from_node == check.id]
        continuation = next((edge.to_node for edge in outgoing if edge.branch in {None, "default"}), None)
        for edge in outgoing:
            if edge.branch in {None, "default"}:
                continue
            scope: set[str] = set()
            pending_branch = [edge.to_node]
            while pending_branch:
                candidate = pending_branch.pop()
                if candidate == continuation or candidate in scope:
                    continue
                scope.add(candidate)
                pending_branch.extend(successors[candidate])
            branch_scopes.append(scope)
    for node in graph.nodes:
        for source in references([node.config, node.input_mapping]):
            if any(source in scope and node.id not in scope for scope in branch_scopes):
                raise WorkflowValidationError(f"Step {node.id} references branch-local output: {source}")
            if source not in ancestors[node.id]:
                raise WorkflowValidationError(f"Step {node.id} references an unavailable upstream step: {source}")


def validate_workflow_readiness(graph: WorkflowGraph, *, require_schedule: bool = False) -> None:
    """Require a runnable path; only scheduled activation requires a trigger."""
    if require_schedule and not any(
        node.id == graph.trigger_node_id and node.type == WorkflowNodeType.SCHEDULE_TRIGGER
        for node in graph.nodes
    ):
        raise WorkflowValidationError("Enabling a workflow requires a time/date trigger")
    unsupported = {WorkflowNodeType.REPEAT, WorkflowNodeType.WAIT, WorkflowNodeType.EVENT_TRIGGER}
    for node in graph.nodes:
        if node.type in unsupported:
            raise WorkflowValidationError(
                f"Step {node.id} uses {node.type.value}, which is not executable in Workflows V1. "
                "Edit this workflow to use time/date, app skills, Check and Send message before running it."
            )
    if graph.version >= 2:
        _validate_builder_execution_inputs(graph)
    incoming = {edge.to_node for edge in graph.edges}
    roots = [node.id for node in graph.nodes if node.id not in incoming]
    start = graph.trigger_node_id or (roots[0] if len(roots) == 1 else None)
    if start is None:
        raise WorkflowValidationError("Workflow requires one connected starting path")

    nodes_by_id = {node.id: node for node in graph.nodes}
    reachable = {start}
    pending = [start]
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.from_node, []).append(edge.to_node)

    while pending:
        node_id = pending.pop()
        for next_node_id in outgoing.get(node_id, []):
            if next_node_id not in reachable:
                reachable.add(next_node_id)
                pending.append(next_node_id)

    if not any(nodes_by_id[node_id].type in QUALIFYING_WORKFLOW_EFFECT_TYPES for node_id in reachable):
        raise WorkflowValidationError("Workflow readiness requires a reachable qualifying effect")



def _validate_builder_execution_inputs(graph: WorkflowGraph) -> None:
    """Preflight the bounded authoring contract before any charged skill dispatch.

    Draft storage and historical inspection deliberately do not call this. Schema
    metadata comes from the same registry used to offer skills in the builder.
    """
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry, _matches_schema
    from backend.core.api.app.services.workflow_runtime_values import resolve_workflow_runtime_values

    registry = WorkflowCapabilityRegistry()
    outputs: dict[str, dict[str, Any]] = {}
    inputs: dict[str, dict[str, Any]] = {}
    modern_types = {WorkflowNodeType.SCHEDULE_TRIGGER, WorkflowNodeType.MANUAL_TRIGGER,
                    WorkflowNodeType.APP_SKILL_ACTION, WorkflowNodeType.CHECK,
                    WorkflowNodeType.SEND_CHAT_MESSAGE, WorkflowNodeType.END}
    for node in graph.nodes:
        if node.type not in modern_types:
            raise WorkflowValidationError(f"Step {node.id} uses a legacy node. Recreate it with the current workflow builder before running.")
        if node.type == WorkflowNodeType.APP_SKILL_ACTION:
            capability_id = f"{node.config['app_id']}.{node.config['skill_id']}"
            capability = registry.get_capability(capability_id)
            if not capability.enabled:
                raise WorkflowValidationError(f"Step {node.id}: {capability_id} is unavailable for workflows ({capability.reason}). Choose an available app skill.")
            input_schema = capability.metadata.get("input_schema")
            output_schema = capability.metadata.get("output_schema")
            if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
                raise WorkflowValidationError(f"Step {node.id}: the app skill has no typed workflow contract")
            inputs[node.id], outputs[node.id] = input_schema, output_schema
        elif node.type == WorkflowNodeType.CHECK:
            matched_type: str | list[str] = ["boolean", "null"] if node.config.get("mode", "exact") == "ai" else "boolean"
            outputs[node.id] = {"type": "object", "properties": {"matched": {"type": matched_type}, "branch": {"type": "string"}}}
        elif node.type in {WorkflowNodeType.SCHEDULE_TRIGGER, WorkflowNodeType.MANUAL_TRIGGER}:
            outputs[node.id] = {"type": "object", "properties": {"triggered": {"type": "boolean"}, "trigger": {"type": "string"}}}
        elif node.type == WorkflowNodeType.SEND_CHAT_MESSAGE:
            outputs[node.id] = {"type": "object", "properties": {"chat_id": {"type": "string"}, "message": {"type": "string"}}}

    def types(schema: dict[str, Any]) -> set[str]:
        declared = schema.get("type")
        return {declared} if isinstance(declared, str) else set(declared or [])

    def compatible(actual: set[str], expected: set[str]) -> bool:
        return bool(actual) and all(kind in expected or kind == "integer" and "number" in expected for kind in actual)

    def assignable(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
        if not compatible(types(actual), types(expected)):
            return False
        if "array" in types(expected):
            return assignable(actual.get("items") or {}, expected.get("items") or {})
        if "object" in types(expected):
            properties = actual.get("properties") or {}
            for required in expected.get("required") or []:
                if required not in properties or not assignable(properties[required], expected.get("properties", {}).get(required) or {}):
                    return False
        return True

    def literal_schema(value: Any) -> dict[str, Any]:
        kind = "null" if value is None else "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "string" if isinstance(value, str) else "array" if isinstance(value, list) else "object"
        return {"type": kind}

    def path_schema(path: str, label: str) -> dict[str, Any]:
        if path.startswith("$nodes."):
            parts = path[len("$nodes."):].split(".")
            if len(parts) < 2 or parts[1] != "output":
                raise WorkflowValidationError(f"{label}: references must select a declared step output")
            node_id, fields = parts[0], parts[2:]
        elif path.startswith("steps."):
            parts = path.split(".")
            if len(parts) < 2:
                raise WorkflowValidationError(f"{label}: select a step output")
            node_id, fields = parts[1], parts[2:]
        elif path == "clock.now":
            return {"type": "string"}
        elif path.startswith("trigger."):
            trigger = next((node for node in graph.nodes if node.id == graph.trigger_node_id), None)
            schema = (trigger.config.get("required_start_input_schema") if trigger else None) or {"type": "object", "properties": {}}
            fields = path.split(".")[1:]
            for field in fields:
                schema = schema.get("properties", {}).get(field)
                if not isinstance(schema, dict):
                    raise WorkflowValidationError(f"{label}: trigger input {path} is not declared")
            return schema
        else:
            raise WorkflowValidationError(f"{label}: unsupported workflow reference {path}")
        schema = outputs.get(node_id)
        if not isinstance(schema, dict):
            raise WorkflowValidationError(f"{label}: step {node_id} has no declared output")
        for field in fields:
            schema = schema.get("properties", {}).get(field)
            if not isinstance(schema, dict):
                raise WorkflowValidationError(f"{label}: output {path} is not declared by its app skill")
        return schema

    def value_schema(value: Any, label: str) -> dict[str, Any]:
        if isinstance(value, dict) and "$date" in value:
            try:
                resolve_workflow_runtime_values(value, now=0)
            except (ValueError, TypeError) as exc:
                raise WorkflowValidationError(f"{label}: {exc}") from exc
            return {"type": "string"}
        if isinstance(value, str) and value.startswith("$nodes."):
            return path_schema(value, label)
        if isinstance(value, str) and ("{{" in value or "}}" in value):
            matches = list(re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", value))
            if not matches or "{{" in re.sub(r"\{\{[^{}]+\}\}", "", value):
                raise WorkflowValidationError(f"{label}: invalid workflow template")
            schemas = []
            for match in matches:
                parts = [part.strip() for part in match.group(1).split("|")]
                schema = path_schema(parts[0], label)
                for date_filter in parts[1:]:
                    if not re.fullmatch(r"(?:plus_hours|plus_days):\s*-?\d+", date_filter) or types(schema) != {"string"}:
                        raise WorkflowValidationError(f"{label}: invalid date/time filter")
                schemas.append(schema)
            if len(matches) == 1 and matches[0].span() == (0, len(value)):
                return schemas[0]
            if any(types(schema) & {"array", "object"} for schema in schemas):
                raise WorkflowValidationError(f"{label}: select scalar fields for inline text, or add a result block")
            return {"type": "string"}
        return literal_schema(value)

    def validate_value(value: Any, schema: dict[str, Any], label: str) -> None:
        actual = value_schema(value, label)
        expected = types(schema)
        if not compatible(types(actual), expected):
            raise WorkflowValidationError(f"{label}: expected {'/'.join(sorted(expected)) or 'a declared type'}, got {'/'.join(sorted(types(actual)))}")
        dynamic = isinstance(value, dict) and "$date" in value or isinstance(value, str) and (value.startswith("$nodes.") or "{{" in value)
        if dynamic:
            if not assignable(actual, schema):
                raise WorkflowValidationError(f"{label}: selected output does not provide the required typed app input fields")
            return
        if isinstance(value, dict):
            properties = schema.get("properties") or {}
            for required in schema.get("required") or []:
                if required not in value or value[required] is None or isinstance(value[required], str) and not value[required].strip():
                    raise WorkflowValidationError(f"{label}.{required}: required app input is missing")
            for key, child in value.items():
                child_schema = properties.get(key)
                if not isinstance(child_schema, dict):
                    if schema.get("additionalProperties") is True:
                        continue
                    raise WorkflowValidationError(f"{label}.{key}: unknown app input")
                validate_value(child, child_schema, f"{label}.{key}")
        elif isinstance(value, list):
            if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")) or label.endswith(".requests") and not value:
                raise WorkflowValidationError(f"{label}: invalid number of request items")
            for index, child in enumerate(value):
                validate_value(child, schema.get("items") or {}, f"{label}[{index}]")
        else:
            leaf_schema = dict(schema, type=next(iter(types(actual))))
            if value is not None and not _matches_schema(value, leaf_schema):
                raise WorkflowValidationError(f"{label}: value is outside the app skill's allowed values")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
                    raise WorkflowValidationError(f"{label}: value is outside the app skill's allowed range")

    def validate_predicate(predicate: dict[str, Any], label: str) -> None:
        op = predicate["op"]
        if op in {"and", "or"}:
            for child in predicate["conditions"]:
                validate_predicate(child, label)
            return
        if op == "not":
            validate_predicate(predicate["condition"], label)
            return
        left = types(value_schema(predicate.get("left"), label)) - {"null"}
        if op == "exists":
            return
        right = types(value_schema(predicate.get("right"), label)) - {"null"}
        numeric = {"number", "integer"}
        if op in {"gt", "gte", "lt", "lte"}:
            valid = bool(left) and bool(right) and left <= numeric and right <= numeric
        elif op in {"contains", "starts_with"}:
            valid = left == right == {"string"}
        else:
            valid = not ((left | right) & {"array", "object"}) and (not left or not right or left == right or left <= numeric and right <= numeric)
        if not valid:
            raise WorkflowValidationError(f"{label}: {op} requires compatible scalar comparison values")

    for node in graph.nodes:
        label = f"Step {node.id}"
        if node.type == WorkflowNodeType.APP_SKILL_ACTION:
            authored = node.config.get("input", {})
            if not isinstance(authored, dict):
                raise WorkflowValidationError(f"{label}: app input must be an object")
            if node.config.get("app_id") == "ai" and node.config.get("skill_id") == "ask":
                prompt = authored.get("prompt")
                if not isinstance(prompt, str) or not prompt.strip():
                    raise WorkflowValidationError(f"{label}: Ask AI requires an instruction")
                matches = list(re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", prompt))
                remainder = re.sub(r"\{\{[^{}]+\}\}", "", prompt)
                if len(matches) > 24 or "{{" in remainder or "}}" in remainder:
                    raise WorkflowValidationError(f"{label}: Ask AI instruction contains invalid or excessive references")
                for index, match in enumerate(matches):
                    value_schema(match.group(0), f"{label}.input.prompt[{index}]")
                if node.input_mapping:
                    raise WorkflowValidationError(f"{label}: Ask AI inputs must be inserted into its instruction")
            else:
                validate_value({**authored, **node.input_mapping}, inputs[node.id], f"{label}.input")
        elif node.type == WorkflowNodeType.CHECK:
            if node.config.get("mode", "exact") == "ai":
                for index, reference in enumerate(node.config["selected_inputs"]):
                    value_schema(reference, f"{label}.selected_inputs[{index}]")
            else:
                validate_predicate(node.config["predicate"], label)
        elif node.type == WorkflowNodeType.SEND_CHAT_MESSAGE:
            if not node.config.get("chat_id") and not str(node.config.get("title") or "").strip():
                raise WorkflowValidationError(f"{label}: enter a title for the new chat")
            for field in ("title", "message", "chat_id"):
                if field in node.config:
                    validate_value(node.config[field], {"type": "string"}, f"{label}.{field}")
            for block in node.config.get("blocks") or []:
                block_label = f"{label}.blocks.{block['id']}"
                schema = value_schema(block["source"], block_label)
                if block.get("only_new_results") and (types(schema) != {"array"} or types(schema.get("items") or {}) != {"object"}):
                    raise WorkflowValidationError(f"{block_label}: Only new results requires a declared result list")
                if "include_if" in block:
                    validate_value(block["include_if"], {"type": ["boolean", "null"]}, f"{block_label}.include_if")
        elif node.type == WorkflowNodeType.SCHEDULE_TRIGGER:
            from backend.core.api.app.services.workflow_scheduler_service import WorkflowSchedulerService
            try:
                WorkflowSchedulerService.initial_next_run_at_from_schedule(node.config, now=0)
            except (ValueError, TypeError, KeyError) as exc:
                raise WorkflowValidationError(f"{label}: invalid schedule: {exc}") from exc

def build_workflow_template_share_payload(workflow: WorkflowDetail) -> WorkflowTemplateSharePayload:
    """Build a template-only share payload without runtime grants or run state."""
    trigger = next((node for node in workflow.graph.nodes if node.id == workflow.graph.trigger_node_id), None)
    non_trigger_nodes = [node for node in workflow.graph.nodes if node.id != workflow.graph.trigger_node_id]
    payload = WorkflowTemplateSharePayload(
        title=workflow.title,
        description=None,
        trigger_template=_template_node(trigger) if trigger else {},
        node_templates=[_template_node(node) for node in non_trigger_nodes],
        edge_templates=[edge.model_dump(mode="json", by_alias=True) for edge in workflow.graph.edges],
        variables_schema=_template_variables_schema(workflow.graph.variables),
        required_app_capabilities=_required_app_capabilities(workflow.graph),
        binding_requirements=_binding_requirements(workflow.graph),
        created_at=workflow.created_at,
        import_enabled=False,
    )
    _reject_sensitive_template_keys(payload.model_dump(mode="json"))
    return payload


def _template_node(node: WorkflowNode) -> dict[str, Any]:
    template: dict[str, Any] = {
        "id": node.id,
        "type": node.type.value,
    }
    if node.title:
        template["title"] = node.title
    config = _template_node_config(node)
    if config:
        template["config"] = config
    if node.input_mapping:
        template["input_mapping"] = dict(node.input_mapping)
    return template


def _template_node_config(node: WorkflowNode) -> dict[str, Any]:
    config = node.config
    if node.type == WorkflowNodeType.SCHEDULE_TRIGGER:
        return {"schedule": dict(config.get("schedule") or {})}
    if node.type == WorkflowNodeType.MANUAL_TRIGGER:
        schema = config.get("required_start_input_schema")
        return {"required_start_input_schema": schema} if schema is not None else {}
    if node.type == WorkflowNodeType.EVENT_TRIGGER:
        event_config = config.get("event") if isinstance(config.get("event"), dict) else config
        safe_event = {
            key: event_config[key]
            for key in ("source", "event_type", "filters", "rate_limit", "rate_limit_seconds")
            if key in event_config
        }
        return {"event": safe_event} if safe_event else {}
    if node.type == WorkflowNodeType.APP_SKILL_ACTION:
        safe_config = {
            "app_id": config.get("app_id"),
            "skill_id": config.get("skill_id"),
        }
        if "input" in config:
            safe_config["input"] = config["input"]
        return safe_config
    if node.type in {WorkflowNodeType.DECISION, WorkflowNodeType.CHECK}:
        if node.type == WorkflowNodeType.CHECK and config.get("mode", "exact") == "ai":
            return {
                "mode": "ai",
                "question": config.get("question"),
                "selected_inputs": list(config.get("selected_inputs") or []),
            }
        return {"mode": "exact", "predicate": config.get("predicate")}
    if node.type == WorkflowNodeType.SEND_CHAT_MESSAGE:
        return {key: config[key] for key in ("title", "message", "blocks") if key in config}
    if node.type == WorkflowNodeType.REPEAT:
        return {
            key: config.get(key)
            for key in ("max_iterations", "max_duration_seconds", "max_credits", "per_iteration_timeout_seconds")
            if key in config
        }
    if node.type in {WorkflowNodeType.CREATE_CHAT_REPORT, WorkflowNodeType.START_NEW_CHAT}:
        return {key: config[key] for key in ("title", "prompt", "template", "initial_message") if key in config}
    if node.type in {WorkflowNodeType.SEND_NOTIFICATION, WorkflowNodeType.SEND_EMAIL_NOTIFICATION}:
        return {key: config[key] for key in ("title", "body") if key in config}
    if node.type == WorkflowNodeType.ASK_USER:
        return {key: config[key] for key in ("prompt", "input_schema", "timeout_seconds") if key in config}
    if node.type == WorkflowNodeType.WAIT:
        return {key: config[key] for key in ("seconds", "until") if key in config}
    return {}


def _template_variables_schema(variables: dict[str, Any]) -> dict[str, Any]:
    schema = variables.get("schema") if isinstance(variables, dict) else None
    return dict(schema) if isinstance(schema, dict) else {}


def _required_app_capabilities(graph: WorkflowGraph) -> list[str]:
    capabilities: set[str] = set()
    for node in graph.nodes:
        if node.type == WorkflowNodeType.APP_SKILL_ACTION:
            app_id = str(node.config.get("app_id") or "").strip()
            skill_id = str(node.config.get("skill_id") or "").strip()
            if app_id:
                capabilities.add(app_id)
            if app_id and skill_id:
                capabilities.add(f"{app_id}.{skill_id}")
    return sorted(capabilities)


def _binding_requirements(graph: WorkflowGraph) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for node in graph.nodes:
        if node.type == WorkflowNodeType.SCHEDULE_TRIGGER:
            requirements.append({"type": "schedule", "node_id": node.id})
        elif node.type == WorkflowNodeType.APP_SKILL_ACTION:
            requirements.append({
                "type": "app_skill",
                "node_id": node.id,
                "app_id": node.config.get("app_id"),
                "skill_id": node.config.get("skill_id"),
            })
        elif node.type == WorkflowNodeType.SEND_CHAT_MESSAGE and node.config.get("chat_id"):
            requirements.append({"type": "chat_destination", "node_id": node.id})
        elif node.type in {WorkflowNodeType.SEND_NOTIFICATION, WorkflowNodeType.SEND_EMAIL_NOTIFICATION}:
            requirements.append({"type": "notification_preferences", "node_id": node.id})
    return requirements


def _reject_sensitive_template_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            contains_forbidden_key = any(
                forbidden in normalized_key
                for forbidden in FORBIDDEN_WORKFLOW_TEMPLATE_KEYS
            )
            if normalized_key in FORBIDDEN_WORKFLOW_TEMPLATE_KEYS or contains_forbidden_key:
                raise WorkflowTemplateSensitiveFieldError(f"Workflow template contains forbidden field at {path}.{key}")
            _reject_sensitive_template_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_template_keys(child, f"{path}[{index}]")


def _validate_node_config(node: WorkflowNode) -> None:
    if node.type == WorkflowNodeType.APP_SKILL_ACTION:
        app_id = str(node.config.get("app_id") or "").strip()
        skill_id = str(node.config.get("skill_id") or "").strip()
        if not app_id or not skill_id:
            raise WorkflowValidationError("App skill action nodes require app_id and skill_id")
        if (app_id, skill_id) == ("ai", "ask"):
            authored = node.config.get("input")
            prompt = authored.get("prompt") if isinstance(authored, dict) else None
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4_000:
                raise WorkflowValidationError("Ask AI requires one bounded text instruction")
            unsupported = set(authored) - {"prompt"}
            if unsupported:
                raise WorkflowValidationError("Ask AI accepts only its instruction; tools, conversation and provider controls are unavailable")
    elif node.type in {WorkflowNodeType.DECISION, WorkflowNodeType.CHECK}:
        mode = node.config.get("mode", "exact") if node.type == WorkflowNodeType.CHECK else "exact"
        if mode not in {"exact", "ai"}:
            raise WorkflowValidationError("Check mode must be exact or ai")
        if mode == "ai":
            question = node.config.get("question")
            selected_inputs = node.config.get("selected_inputs")
            if not isinstance(question, str) or not question.strip() or len(question) > 4_000:
                raise WorkflowValidationError("AI Check requires one bounded yes-or-no question")
            if not isinstance(selected_inputs, list) or not 1 <= len(selected_inputs) <= 24:
                raise WorkflowValidationError("AI Check requires between 1 and 24 selected earlier values")
            if any(not isinstance(reference, str) or not reference.startswith("$nodes.") for reference in selected_inputs):
                raise WorkflowValidationError("AI Check selected inputs must be earlier Workflow output references")
            if len(selected_inputs) != len(set(selected_inputs)):
                raise WorkflowValidationError("AI Check selected inputs must be unique")
        else:
            predicate = node.config.get("predicate")
            if not isinstance(predicate, dict):
                raise WorkflowValidationError("Decision nodes require a structured predicate")
            _validate_predicate(predicate)
    elif node.type == WorkflowNodeType.SEND_CHAT_MESSAGE:
        for field in ("title", "message", "chat_id"):
            if field in node.config and not isinstance(node.config[field], str):
                raise WorkflowValidationError(f"Send message {field} must be text")
        blocks = node.config.get("blocks", [])
        if not isinstance(blocks, list):
            raise WorkflowValidationError("Send message blocks must be a list")
        block_ids = set()
        for block in blocks:
            if not isinstance(block, dict) or not isinstance(block.get("id"), str) or not block["id"]:
                raise WorkflowValidationError("Every message block requires a stable id")
            if block["id"] in block_ids:
                raise WorkflowValidationError("Message block ids must be unique")
            block_ids.add(block["id"])
            if not isinstance(block.get("source"), str) or not block["source"].startswith("$nodes."):
                raise WorkflowValidationError("Message blocks require an upstream output source")
            if "only_new_results" in block and not isinstance(block["only_new_results"], bool):
                raise WorkflowValidationError("only_new_results must be boolean")
            if "include_if" in block and not isinstance(block["include_if"], (str, bool)):
                raise WorkflowValidationError("include_if must be a boolean or upstream boolean reference")
        if not blocks and not str(node.config.get("message") or "").strip():
            raise WorkflowValidationError("Send message requires text or result blocks")
    elif node.type == WorkflowNodeType.REPEAT:
        for key in ("max_iterations", "max_duration_seconds", "max_credits", "per_iteration_timeout_seconds"):
            value = node.config.get(key)
            if not isinstance(value, int) or value <= 0:
                raise WorkflowValidationError(f"Repeat nodes require positive integer {key}")
    elif node.type == WorkflowNodeType.WAIT:
        seconds = node.config.get("seconds")
        until = node.config.get("until")
        if seconds is None and until is None:
            raise WorkflowValidationError("Wait nodes require seconds or until")
        if seconds is not None and (not isinstance(seconds, int) or seconds <= 0):
            raise WorkflowValidationError("Wait nodes require positive integer seconds")
    elif node.type == WorkflowNodeType.ASK_USER:
        prompt = node.config.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise WorkflowValidationError("Ask user nodes require prompt")
    elif node.type == WorkflowNodeType.SCHEDULE_TRIGGER:
        schedule = node.config.get("schedule")
        if not isinstance(schedule, dict) or not schedule.get("type"):
            raise WorkflowValidationError("Schedule trigger nodes require schedule.type")
    elif node.type == WorkflowNodeType.MANUAL_TRIGGER:
        _validate_required_start_input_schema(node.config.get("required_start_input_schema"))
    elif node.type == WorkflowNodeType.EVENT_TRIGGER:
        _validate_event_trigger_config(node.config)


def validate_manual_run_input(graph: WorkflowGraph, input_payload: dict[str, Any] | None) -> None:
    """Validate run-now input against the trigger's required start input schema."""
    validate_workflow_readiness(graph)
    trigger = next((node for node in graph.nodes if node.id == graph.trigger_node_id), None)
    if trigger is None:
        return
    schema = trigger.config.get("required_start_input_schema")
    if schema is None:
        return
    _validate_required_start_input_schema(schema)
    required = schema.get("required") or []
    payload = input_payload or {}
    missing = [field for field in required if payload.get(field) in (None, "")]
    if missing:
        raise WorkflowMissingInputError(f"Missing workflow start input: {missing}")


def _validate_required_start_input_schema(schema: Any) -> None:
    if schema is None:
        return
    if not isinstance(schema, dict):
        raise WorkflowValidationError("required_start_input_schema must be an object")
    if schema.get("type") != "object":
        raise WorkflowValidationError("required_start_input_schema.type must be object")
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise WorkflowValidationError("required_start_input_schema.properties must be an object")
    required = schema.get("required") or []
    if not isinstance(required, list):
        raise WorkflowValidationError("required_start_input_schema.required must be an array")
    for field in required:
        if field not in properties:
            raise WorkflowValidationError(f"required_start_input_schema missing property for required field: {field}")


def _validate_event_trigger_config(config: dict[str, Any]) -> None:
    event_config = config.get("event") if isinstance(config.get("event"), dict) else config
    source = event_config.get("source") or event_config.get("event_type")
    if not source:
        raise WorkflowValidationError("Event trigger nodes require event.source")
    scope = event_config.get("scope")
    if not isinstance(scope, dict) or not scope:
        raise WorkflowValidationError("Event trigger nodes require event.scope")
    if not (scope.get("project_id") or scope.get("project_hash") or scope.get("hashed_project_id")):
        raise WorkflowValidationError("Event trigger nodes require event.scope.project_id")
    filters = event_config.get("filters")
    if not isinstance(filters, (dict, list)) or not filters:
        raise WorkflowValidationError("Event trigger nodes require event.filters")
    rate_limit = event_config.get("rate_limit") or {"rate_limit_seconds": event_config.get("rate_limit_seconds")}
    if not isinstance(rate_limit, dict) or not any(isinstance(value, (int, float)) and value > 0 for value in rate_limit.values()):
        raise WorkflowValidationError("Event trigger nodes require event.rate_limit")


def _validate_predicate(predicate: dict[str, Any]) -> None:
    op = predicate.get("op")
    if op not in SUPPORTED_DECISION_OPERATORS:
        raise WorkflowValidationError(f"Unsupported decision operator: {op}")

    if op in {"and", "or"}:
        conditions = predicate.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise WorkflowValidationError(f"Decision operator {op} requires conditions")
        for condition in conditions:
            if not isinstance(condition, dict):
                raise WorkflowValidationError("Decision conditions must be mappings")
            _validate_predicate(condition)
    elif op == "not":
        condition = predicate.get("condition")
        if not isinstance(condition, dict):
            raise WorkflowValidationError("Decision operator not requires condition")
        _validate_predicate(condition)
    elif op != "exists" and "left" not in predicate:
        raise WorkflowValidationError(f"Decision operator {op} requires left operand")
