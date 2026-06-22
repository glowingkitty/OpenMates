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


class WorkflowNodeType(str, Enum):
    SCHEDULE_TRIGGER = "schedule_trigger"
    MANUAL_TRIGGER = "manual_trigger"
    WEBHOOK_TRIGGER = "webhook_trigger"
    APP_SKILL_ACTION = "app_skill_action"
    DECISION = "decision"
    REPEAT = "repeat"
    CREATE_CHAT_REPORT = "create_chat_report"
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
    WorkflowNodeType.SEND_NOTIFICATION,
    WorkflowNodeType.SEND_EMAIL_NOTIFICATION,
    WorkflowNodeType.END,
}
DISABLED_FUTURE_NODE_TYPES = {
    WorkflowNodeType.WEBHOOK_TRIGGER,
    WorkflowNodeType.ASK_USER,
    WorkflowNodeType.CUSTOM_CODE,
}
SUPPORTED_WORKFLOW_APP_SKILLS = {("weather", "forecast"), ("news", "search")}


class WorkflowValidationError(ValueError):
    """Raised when a workflow graph violates the V1 executable contract."""


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
    title: str
    status: WorkflowStatus
    enabled: bool
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
    type: Literal["node", "app_skill"]
    id: str
    title: str
    enabled: bool = True
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def validate_workflow_graph(graph: WorkflowGraph) -> None:
    node_ids = [node.id for node in graph.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise WorkflowValidationError("Duplicate workflow node ids are not allowed")

    nodes_by_id = {node.id: node for node in graph.nodes}
    if graph.trigger_node_id not in nodes_by_id:
        raise WorkflowValidationError("trigger_node_id must reference an existing node")

    trigger_nodes = [
        node for node in graph.nodes
        if node.type in {WorkflowNodeType.SCHEDULE_TRIGGER, WorkflowNodeType.MANUAL_TRIGGER, WorkflowNodeType.WEBHOOK_TRIGGER}
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
