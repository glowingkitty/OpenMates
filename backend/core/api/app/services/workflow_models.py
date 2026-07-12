# backend/core/api/app/services/workflow_models.py
#
# Typed workflow graph, run, and validation models for Workflows V1. These
# models are deliberately independent from FastAPI and Directus so the runner,
# routes, CLI/SDK tests, and Apple parity tests share one contract.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"
    DELETED = "deleted"


class WorkflowRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


class WorkflowNodeType(str, Enum):
    SCHEDULE_TRIGGER = "schedule_trigger"
    MANUAL_TRIGGER = "manual_trigger"
    WEBHOOK_TRIGGER = "webhook_trigger"
    EVENT_TRIGGER = "event_trigger"
    APP_SKILL_ACTION = "app_skill_action"
    DECISION = "decision"
    REPEAT = "repeat"
    CREATE_CHAT_REPORT = "create_chat_report"
    START_NEW_CHAT = "start_new_chat"
    SEND_NOTIFICATION = "send_notification"
    SEND_EMAIL_NOTIFICATION = "send_email_notification"
    ASK_USER = "ask_user"
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
    WorkflowNodeType.REPEAT,
    WorkflowNodeType.CREATE_CHAT_REPORT,
    WorkflowNodeType.START_NEW_CHAT,
    WorkflowNodeType.SEND_NOTIFICATION,
    WorkflowNodeType.SEND_EMAIL_NOTIFICATION,
    WorkflowNodeType.EVENT_TRIGGER,
    WorkflowNodeType.END,
}
DISABLED_FUTURE_NODE_TYPES = {
    WorkflowNodeType.WEBHOOK_TRIGGER,
    WorkflowNodeType.ASK_USER,
    WorkflowNodeType.CUSTOM_CODE,
}
SUPPORTED_WORKFLOW_APP_SKILLS = {("weather", "forecast"), ("news", "search")}
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
    trigger_node_id: str
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
    description: str | None = None
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
    if graph.trigger_node_id not in nodes_by_id:
        raise WorkflowValidationError("trigger_node_id must reference an existing node")

    trigger_nodes = [
        node for node in graph.nodes
        if node.type in {WorkflowNodeType.SCHEDULE_TRIGGER, WorkflowNodeType.MANUAL_TRIGGER, WorkflowNodeType.WEBHOOK_TRIGGER, WorkflowNodeType.EVENT_TRIGGER}
    ]
    if len(trigger_nodes) != 1:
        raise WorkflowValidationError("Workflows V1 must contain exactly one trigger node")
    if trigger_nodes[0].id != graph.trigger_node_id:
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


def build_workflow_template_share_payload(workflow: WorkflowDetail) -> WorkflowTemplateSharePayload:
    """Build a template-only share payload without runtime grants or run state."""
    trigger = next(node for node in workflow.graph.nodes if node.id == workflow.graph.trigger_node_id)
    non_trigger_nodes = [node for node in workflow.graph.nodes if node.id != workflow.graph.trigger_node_id]
    payload = WorkflowTemplateSharePayload(
        title=workflow.title,
        description=None,
        trigger_template=_template_node(trigger),
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
    if node.type == WorkflowNodeType.DECISION:
        return {"predicate": config.get("predicate")}
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
        if (app_id, skill_id) not in SUPPORTED_WORKFLOW_APP_SKILLS:
            raise WorkflowValidationError(f"Workflow app-skill action is not enabled for {app_id}:{skill_id} in V1")
    elif node.type == WorkflowNodeType.DECISION:
        predicate = node.config.get("predicate")
        if not isinstance(predicate, dict):
            raise WorkflowValidationError("Decision nodes require a structured predicate")
        _validate_predicate(predicate)
    elif node.type == WorkflowNodeType.REPEAT:
        for key in ("max_iterations", "max_duration_seconds", "max_credits", "per_iteration_timeout_seconds"):
            value = node.config.get(key)
            if not isinstance(value, int) or value <= 0:
                raise WorkflowValidationError(f"Repeat nodes require positive integer {key}")
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
    trigger = next(node for node in graph.nodes if node.id == graph.trigger_node_id)
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
