# backend/core/api/app/routes/workflows.py
#
# Authenticated Workflows V1 API shared by web, CLI, npm SDK, pip SDK, and Apple.
# All mutations pass through WorkflowService so graph validation, ownership, and
# feature availability are consistent across clients.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import time
import json
import asyncio
import logging
import hashlib
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.apps.ai.processing.workspace_ask_planner import WorkspaceAskPlanningError, run_workflow_ask_pipeline
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.feature_availability_guards import ensure_workflows_enabled
from backend.core.api.app.services.team_workspace_service import TeamWorkspaceMoveError, move_workspace_record_to_team
from backend.core.api.app.services.workflow_input_service import (
    DirectusWorkflowInputRepository, DragonflyWorkflowInputCheckpointStore, WorkflowInputService,
)
from backend.core.api.app.services.workflow_file_service import WorkflowFileDocument, WorkflowFileImportError, WorkflowFileService, WorkflowFileTooLargeError
from backend.core.api.app.services.workflow_registry_planner import WorkflowRegistryPlanner
from backend.core.api.app.services.workflow_identity_service import (
    WorkflowIdentity,
    WorkflowIdentityService,
    build_preprocessing_workflow_classifier,
    normalize_workflow_identity,
)
from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowNode, WorkflowNodeType, WorkflowLifecycle, WorkflowMissingInputError, WorkflowRunContentRetention, WorkflowRunStatus, validate_workflow_composition_refs, validate_workflow_readiness
from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeProtocolError, WorkflowRuntimeService
from backend.core.api.app.services.workflow_runner import WorkflowRunner, _precheck_workflow_ai_check, _charge_workflow_ai_check
from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter, WorkflowSkillBillingError
from backend.core.api.app.services.workflow_yaml_compiler import (
    WorkflowYamlCompilationError,
    compile_workflow_yaml,
    validate_workflow_yaml,
)
from backend.core.api.app.services.workflow_service import (
    WorkflowBindingRequirementUnresolvedError,
    DirectusWorkflowRepository,
    WorkflowBindingRequirementsUnresolvedError,
    WorkflowFeatureDisabledError,
    WorkflowNotFoundError,
    WorkflowRunNotCancellableError,
    WorkflowService,
    WorkflowTeamExecutionUnavailableError,
    WorkflowVersionCurrentError,
    _hash_owner_id,
    validate_workflow_return_outputs,
)
from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter, WorkflowActionExecutionError
from backend.core.api.app.services.workflow_ai_service import (
    WorkflowAiService,
    WorkflowReferenceHint,
)
from backend.core.api.app.services.billing_settlement_service import BillingSettlementLock
from backend.core.api.app.services.workflow_assistant_service import (
    DirectusWorkflowAssistantProposalRepository,
    WorkflowAssistantService,
)
from backend.core.api.app.services.workflow_template_service import (
    WorkflowTemplateImportError,
    WorkflowTemplateProjectionNotFoundError,
    WorkflowTemplateImportPayload,
    WorkflowTemplateProjectionError,
    WorkflowTemplateProjectionRevokedError,
    WorkflowTemplateProjectionService,
    WorkflowTemplateProjectionStaleError,
)
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.workspace_change_history_service import WorkspaceChangeHistoryService, build_history_commands, s3_workspace_history_archive_io
from backend.shared.python_utils.encrypted_slug_metadata import DuplicateObjectSlugError


_TEAM_CONTEXT_ROUTES = {
    ("GET", "/v1/workflows"),
    ("POST", "/v1/workflows"),
    ("GET", "/v1/workflows/capabilities"),
    ("POST", "/v1/workflows/validate"),
    ("GET", "/v1/workflows/{workflow_id}"),
    ("PATCH", "/v1/workflows/{workflow_id}"),
    ("DELETE", "/v1/workflows/{workflow_id}"),
    ("POST", "/v1/workflows/{workflow_id}/enable"),
    ("POST", "/v1/workflows/{workflow_id}/disable"),
    ("GET", "/v1/workflows/{workflow_id}/versions"),
    ("GET", "/v1/workflows/{workflow_id}/versions/{version_id}"),
    ("POST", "/v1/workflows/{workflow_id}/versions/{version_id}/restore"),
    ("GET", "/v1/workflows/{workflow_id}/runs"),
    ("GET", "/v1/workflows/{workflow_id}/runs/{run_id}"),
    ("POST", "/v1/workflows/input"),
    ("POST", "/v1/workflows/input/stream"),
    ("GET", "/v1/workflows/input/{session_id}"),
    ("GET", "/v1/workflows/input/{session_id}/events"),
    ("POST", "/v1/workflows/input/{session_id}/follow-up"),
    ("POST", "/v1/workflows/input/{session_id}/stop"),
    ("POST", "/v1/workflows/input/{session_id}/undo"),
}


def enforce_team_workflow_surface(request: Request, team_id: str | None = Query(default=None, min_length=1)) -> None:
    """A Team query must never fall through to a Personal-only workflow route."""
    if not team_id:
        return
    route = request.scope.get("route")
    if (request.method, getattr(route, "path", None)) not in _TEAM_CONTEXT_ROUTES:
        raise HTTPException(status_code=409, detail="TEAM_WORKFLOW_OPERATION_UNAVAILABLE")


router = APIRouter(prefix="/v1/workflows", tags=["Workflows"], dependencies=[Depends(ensure_workflows_enabled), Depends(enforce_team_workflow_surface)])
logger = logging.getLogger(__name__)
_STEP_TEST_PRODUCERS: set[asyncio.Task[None]] = set()


class WorkflowCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    team_id: str | None = Field(default=None, min_length=1)
    encrypted_slug: str | None = Field(default=None, min_length=1)
    slug_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    description: str | None = Field(default=None, max_length=2_000)
    category: str | None = Field(default=None, max_length=80)
    icon: str | None = Field(default=None, max_length=80)
    graph: WorkflowGraph
    enabled: bool = False
    run_content_retention: WorkflowRunContentRetention = WorkflowRunContentRetention.LAST_5
    lifecycle: WorkflowLifecycle = WorkflowLifecycle.PERSISTED
    source: str = "manual"
    source_chat_id: str | None = None
    created_by_assistant: bool = False
    auto_delete_at: int | None = None


class WorkflowUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    encrypted_slug: str | None = Field(default=None, min_length=1)
    slug_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    description: str | None = Field(default=None, max_length=2_000)
    category: str | None = Field(default=None, max_length=80)
    icon: str | None = Field(default=None, max_length=80)
    graph: WorkflowGraph | None = None
    enabled: bool | None = None
    run_content_retention: WorkflowRunContentRetention | None = None
    version: int | None = None


class WorkflowMoveRequest(BaseModel):
    team_id: str
    confirmed: bool
    encrypted_slug: str | None = Field(default=None, min_length=1)
    slug_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    moved_at: int | None = None


class WorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(default="manual", pattern="^(manual|test)$")
    input: dict[str, Any] = Field(default_factory=dict)
    source_chat_id: str | None = Field(default=None, min_length=1, max_length=200)
    message_destination_overrides: dict[str, str] = Field(default_factory=dict)
    return_outputs: dict[str, dict[str, str]] = Field(default_factory=dict)


class WorkflowRunOnceRequest(WorkflowRunRequest):
    title: str = Field(min_length=1, max_length=200)
    graph: WorkflowGraph
    source_chat_id: str = Field(min_length=1, max_length=200)


class WorkflowSaveAsReusableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class WorkflowStepTestRequest(BaseModel):
    """Ephemeral editor input; testing never saves a workflow version."""

    input: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
    node: WorkflowNode | None = None
    upstream_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    stream: bool = False



class WorkflowRunResponseRequest(BaseModel):
    step_id: str = Field(min_length=1, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowYamlRequest(BaseModel):
    """CLI YAML authoring request; the server remains the authoritative compiler."""

    source: str = Field(min_length=1, max_length=65_536)


class WorkflowAiAuthoringReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1, max_length=250)
    label: str = Field(min_length=1, max_length=120)
    value_type: str = Field(min_length=1, max_length=24)
    inserted: bool = False


class WorkflowAiAuthoringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(max_length=4_000)
    references: list[WorkflowAiAuthoringReferenceRequest] = Field(default_factory=list, max_length=24)


def _yaml_validation_payload(source: str) -> dict[str, Any]:
    result = validate_workflow_yaml(source)
    return {
        "draft_valid": result.draft_valid,
        "enable_ready": result.enable_ready,
        "diagnostics": [
            {
                "code": item.code,
                "path": item.path,
                "message": item.message,
                "step_id": item.step_id,
                "field": item.field,
                "expected_type": item.expected_type,
                "help_command": item.help_command,
            }
            for item in result.diagnostics
        ],
    }


class WorkflowInputStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str | None = Field(default=None, max_length=20_000)
    input_type: str = Field(default="text", pattern="^(text|audio)$")
    audio_ref: dict[str, str | int] | None = None
    selected_workflow_id: str | None = Field(default=None, min_length=1, max_length=200)
    selected_project_id: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    optimistic_save: bool = False
    idempotency_key: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")

    @model_validator(mode="after")
    def validate_input_source(self) -> WorkflowInputStartRequest:
        if self.input_type == "text" and (self.text is None or not self.text.strip() or self.audio_ref is not None):
            raise ValueError("text workflow input requires non-empty text and no audio_ref")
        if self.input_type == "audio" and (self.text is not None or not self.audio_ref or not isinstance(self.audio_ref.get("id"), str)):
            raise ValueError("audio workflow input requires audio_ref.id and no text")
        return self


class WorkflowInputFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=20_000)


class WorkflowTemplateProjectionUpsertRequest(BaseModel):
    """Opaque projection data; fragment/template keys are not API fields."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=200)
    source_version: int = Field(ge=1)
    ciphertext: str = Field(min_length=1, max_length=100_000)
    ciphertext_checksum: str = Field(min_length=1, max_length=200)
    owner_wrapped_key: str = Field(min_length=1, max_length=100_000)
    projection_schema_version: int = Field(ge=1)


class WorkflowTemplateBindingCompletionRequest(BaseModel):
    """Identifies a recipient-local binding completed outside template ciphertext."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=100)
    node_id: str = Field(min_length=1, max_length=200)
    chat_id: str | None = Field(default=None, min_length=1, max_length=200)
    new_chat: bool = False


class WorkflowAssistantDeleteConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool


class WorkflowHistoryRestoreRequest(BaseModel):
    entry_id: str = Field(min_length=1)
    state: str = Field(default="after", pattern="^(before|after)$")


class WorkflowAskPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)


class WorkflowAskUpdateRequest(BaseModel):
    workflow_id: str = Field(min_length=1)
    patch: WorkflowUpdateRequest


class WorkflowAskActionRequest(BaseModel):
    workflow_id: str = Field(min_length=1)
    action: Literal["enable", "disable", "delete"]


class WorkflowAskRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    create: WorkflowCreateRequest | None = None
    exact_update: WorkflowAskUpdateRequest | None = None
    exact_action: WorkflowAskActionRequest | None = None
    selected_object_id: str | None = Field(default=None, min_length=1)


def get_workflow_service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        service = WorkflowService(repository=DirectusWorkflowRepository())
        request.app.state.workflow_service = service
    return service


def get_workflow_identity_service(request: Request) -> WorkflowIdentityService:
    secrets_manager = getattr(request.app.state, "secrets_manager", None)
    classifier = build_preprocessing_workflow_classifier(secrets_manager) if secrets_manager is not None else None
    return WorkflowIdentityService(classifier=classifier)


def get_workflow_ai_service(request: Request) -> WorkflowAiService:
    return WorkflowAiService(
        secrets_manager=getattr(request.app.state, "secrets_manager", None),
        cache_service=getattr(request.app.state, "cache_service", None),
    )


def _is_ask_ai_node(node: WorkflowNode) -> bool:
    return (
        node.type == WorkflowNodeType.APP_SKILL_ACTION
        and node.config.get("app_id") == "ai"
        and node.config.get("skill_id") == "ask"
    )


async def _paid_save_verdict(
    service: WorkflowAiService,
    *,
    cache_key: str,
    owner_id: str,
    node_id: str,
    skill_id: str,
    unavailable_code: str,
    preflight: Any,
    evaluate: Any,
) -> bool:
    """Serialize one owner/text proof across workers before billing and Jev."""
    if service.cache_service is None:
        raise HTTPException(status_code=503, detail=unavailable_code)
    try:
        async with BillingSettlementLock(service.cache_service).hold(cache_key) as lease:
            if not lease.acquired or lease.lock_lost:
                raise HTTPException(status_code=503, detail=unavailable_code)
            cached = await service._cache_get(cache_key)
            if isinstance(cached, bool):
                return cached
            if cached == "unavailable":
                raise HTTPException(status_code=503, detail=unavailable_code)
            if not await preflight():
                raise HTTPException(status_code=503, detail=unavailable_code)
            try:
                await _precheck_workflow_ai_check(owner_id)
                await _charge_workflow_ai_check(
                    user_id=owner_id,
                    context={"workflow": {"workflow_id": "authoring", "run_id": cache_key, "node_id": node_id}},
                    node_id=node_id, operation_id=str(uuid.uuid4()), source_override="workflow",
                    skill_id=skill_id, billing_purpose="save_validation_jev",
                )
            except WorkflowSkillBillingError as exc:
                raise HTTPException(status_code=402 if exc.code == "INSUFFICIENT_CREDITS" else 503, detail=exc.code) from exc
            verdict = await evaluate()
            if verdict is None:
                await service._cache_set(cache_key, "unavailable", 30)
                raise HTTPException(status_code=503, detail=unavailable_code)
            if not await service._cache_set(cache_key, verdict, 24 * 60 * 60):
                raise HTTPException(status_code=503, detail=unavailable_code)
            return verdict
    except RuntimeError as exc:
        if str(exc) == "billing_settlement_busy":
            raise HTTPException(status_code=503, detail=unavailable_code) from exc
        raise


def _prevalidate_paid_workflow_save(
    graph: WorkflowGraph,
    *,
    prior_graph: WorkflowGraph | None = None,
    enabled: bool = False,
) -> None:
    """Reject deterministic graph failures before any billable AI validation."""
    validate_workflow_composition_refs(
        graph, prior_graph=prior_graph, allow_data_dependencies=graph.version >= 2,
    )
    if enabled:
        validate_workflow_readiness(graph, require_schedule=True)


def _workflow_ancestors(graph: WorkflowGraph, node_id: str) -> set[str]:
    incoming: dict[str, list[str]] = {}
    for edge in graph.edges:
        incoming.setdefault(edge.to_node, []).append(edge.from_node)
    ancestors: set[str] = set()
    pending = list(incoming.get(node_id, ()))
    while pending:
        ancestor = pending.pop()
        if ancestor in ancestors:
            continue
        ancestors.add(ancestor)
        pending.extend(incoming.get(ancestor, ()))
    return ancestors


def _coarse_schema_type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "unknown"
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        non_null = [str(item) for item in declared if item != "null"]
        return non_null[0] if len(non_null) == 1 else "mixed"
    return "unknown"


def _ask_ai_reference_hints(graph: WorkflowGraph, node: WorkflowNode) -> list[WorkflowReferenceHint]:
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry

    prompt = str((node.config.get("input") or {}).get("prompt") or "")
    ancestors = _workflow_ancestors(graph, node.id)
    registry = WorkflowCapabilityRegistry()
    hints: list[WorkflowReferenceHint] = []
    for source in graph.nodes:
        if source.id not in ancestors:
            continue
        output_schema: dict[str, Any] | None = None
        if source.type == WorkflowNodeType.APP_SKILL_ACTION:
            capability = registry.get_capability(f"{source.config.get('app_id')}.{source.config.get('skill_id')}")
            candidate = capability.metadata.get("output_schema")
            output_schema = candidate if isinstance(candidate, dict) else None
        elif source.type == WorkflowNodeType.CHECK:
            matched_type: str | list[str] = ["boolean", "null"] if source.config.get("mode", "exact") == "ai" else "boolean"
            output_schema = {
                "type": "object",
                "properties": {"matched": {"type": matched_type}, "branch": {"type": "string"}},
            }
        elif source.type in {WorkflowNodeType.SCHEDULE_TRIGGER, WorkflowNodeType.MANUAL_TRIGGER}:
            output_schema = {
                "type": "object",
                "properties": {"triggered": {"type": "boolean"}, "trigger": {"type": "string"}},
            }
        elif source.type == WorkflowNodeType.SEND_CHAT_MESSAGE:
            output_schema = {
                "type": "object",
                "properties": {"chat_id": {"type": "string"}, "message": {"type": "string"}},
            }
        properties = output_schema.get("properties") if output_schema else None
        if not isinstance(properties, dict):
            continue
        for field, field_schema in properties.items():
            reference = f"$nodes.{source.id}.output.{field}"
            template_reference = "{{" + reference.replace("$nodes.", "steps.").replace(".output.", ".") + "}}"
            field_title = field_schema.get("title") if isinstance(field_schema, dict) else None
            label = f"{source.title or source.id} · {field_title or str(field).replace('_', ' ').title()}"
            hints.append(
                WorkflowReferenceHint(
                    reference=reference,
                    label=label,
                    value_type=_coarse_schema_type(field_schema),
                    inserted=template_reference in prompt,
                )
            )
    return hints[:24]


async def _validate_workflow_ask_ai_nodes(
    request: Request,
    graph: WorkflowGraph,
    owner_id: str,
    prior_graph: WorkflowGraph | None = None,
) -> list[dict[str, str]]:
    service = get_workflow_ai_service(request)
    previous = {node.id: node for node in prior_graph.nodes} if prior_graph else {}
    for node in graph.nodes:
        if not _is_ask_ai_node(node):
            continue
        instruction = str((node.config.get("input") or {}).get("prompt") or "")
        prior = previous.get(node.id)
        if prior and _is_ask_ai_node(prior) and str((prior.config.get("input") or {}).get("prompt") or "") == instruction:
            continue
        # The owner-scoped daily proof lets a retried graph Save reuse its
        # charged verdict without sending an unbilled second provider request.
        proof = hashlib.sha256(f"{owner_id}\0{int(time.time() // 86_400)}\0{instruction}".encode()).hexdigest()
        cache_key = f"workflow-ai:ask-validation:{proof}"
        valid = await _paid_save_verdict(
            service, cache_key=cache_key, owner_id=owner_id, node_id=node.id,
            skill_id="workflow-ask-validation", unavailable_code="WORKFLOW_AI_ASK_VALIDATION_UNAVAILABLE",
            preflight=lambda: service.preflight_ask_instruction(instruction),
            evaluate=lambda: service.validate_ask_instruction(instruction),
        )
        if not valid:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "WORKFLOW_AI_ASK_REQUIRES_APP_ACTION",
                    "node_id": node.id,
                    "message": "You can't ask for using app skills here. Instead add a 'Use app' action to trigger an app skill.",
                },
            )
    return []


async def _validate_workflow_ai_check_nodes(
    request: Request,
    graph: WorkflowGraph,
    owner_id: str,
    prior_graph: WorkflowGraph | None = None,
) -> None:
    """Charge and validate changed authored AI Check semantics before saving."""
    ai_service = get_workflow_ai_service(request)
    previous = {node.id: node for node in prior_graph.nodes} if prior_graph else {}
    for node in graph.nodes:
        if node.type != WorkflowNodeType.CHECK or node.config.get("mode", "exact") != "ai":
            continue
        config = node.config
        prior = previous.get(node.id)
        is_options = config.get("result_type", "boolean") == "options"
        if prior and prior.type == WorkflowNodeType.CHECK and prior.config.get("mode") == "ai" and (
            prior.config == config if is_options else prior.config.get("result_type", "boolean") != "options"
            and str(prior.config.get("question") or "").strip() == str(config.get("question") or "").strip()
        ):
            continue
        # Preserve the Boolean question's existing billing identity. Options
        # include the full authored selection semantics in their paid proof.
        authored = (json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                    if is_options else str(config.get("question") or "").strip())
        proof = hashlib.sha256(f"{owner_id}\0{int(time.time() // 86_400)}\0{authored}".encode()).hexdigest()
        cache_key = f"workflow-ai:check-validation:{proof}"
        valid = await _paid_save_verdict(
            ai_service, cache_key=cache_key, owner_id=owner_id, node_id=node.id,
            skill_id="workflow-check", unavailable_code="WORKFLOW_AI_CHECK_VALIDATION_UNAVAILABLE",
            preflight=lambda: ai_service.preflight_check_config(config),
            evaluate=lambda: ai_service.validate_check_config(config),
        )
        if not valid:
            code = "WORKFLOW_AI_CHECK_OPTIONS_INVALID" if config.get("result_type") == "options" else "WORKFLOW_AI_CHECK_NOT_BOOLEAN"
            raise HTTPException(status_code=422, detail={"code": code, "node_id": node.id})


async def _resolve_create_identity(body: WorkflowCreateRequest, identity_service: WorkflowIdentityService) -> WorkflowIdentity:
    if body.category is not None or body.icon is not None:
        return normalize_workflow_identity(body.category, body.icon)
    return await identity_service.resolve(title=body.title, description=body.description, graph=body.graph)


def get_directus_service(request: Request) -> Any:
    if not hasattr(request.app.state, "directus_service"):
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_workspace_history_service(request: Request) -> WorkspaceChangeHistoryService:
    s3_service = getattr(request.app.state, "s3_service", None)
    if s3_service is not None:
        archive_writer, archive_reader = s3_workspace_history_archive_io(s3_service)
        return WorkspaceChangeHistoryService(get_directus_service(request), archive_writer=archive_writer, archive_reader=archive_reader)
    return WorkspaceChangeHistoryService(get_directus_service(request))


async def _record_workflow_history(
    history_service: WorkspaceChangeHistoryService,
    user_id: str,
    *,
    source: str = "cli",
    action_type: str,
    entries: list[dict[str, Any]],
    redacted_summary: str,
) -> dict[str, Any]:
    history = await history_service.record_change_set(
        user_id=user_id,
        source=source,
        namespace="workflows",
        action_type=action_type,
        entries=entries,
        redacted_summary=redacted_summary,
    )
    return {**history, **build_history_commands(history["change_set"]["change_set_id"], history["entries"])}


def _workflow_ask_fallback(message: str, *, processing: dict[str, Any] | None = None) -> dict[str, Any]:
    response = {
        "outcome": "fallback_to_chat",
        "applied": False,
        "fallback_to_chat": True,
        "fallback_message": message,
        "change_set_id": None,
        "summary": message,
        "changed_entries": [],
        "undo_all_command": None,
        "undo_entry_commands": [],
        "warnings": [],
    }
    if processing is not None:
        response["processing"] = processing
    return response


def _workflow_ask_applied_response(*, summary: str, history: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcome": "applied",
        "applied": True,
        "fallback_to_chat": False,
        "fallback_message": None,
        "change_set_id": history["change_set"]["change_set_id"],
        "summary": summary,
        "changed_entries": history["entries"],
        "undo_all_command": history["undo_all_command"],
        "undo_entry_commands": history["undo_entry_commands"],
        "warnings": [],
        "history": history,
        **extra,
    }


def _is_short_title_like_ask(instruction: str) -> bool:
    stripped = instruction.strip()
    if not stripped or "\n" in stripped:
        return False
    if any(token in stripped for token in ("- ", "* ", "1.")):
        return False
    return len(stripped.split()) <= 8


def _deterministic_workflow_create(instruction: str) -> WorkflowCreateRequest:
    graph = {
        "version": 1,
        "trigger_node_id": "manual-trigger",
        "nodes": [
            {"id": "manual-trigger", "type": "manual_trigger", "title": "Manual trigger"},
            {"id": "end", "type": "end", "title": "End"},
        ],
        "edges": [{"from": "manual-trigger", "to": "end"}],
    }
    return WorkflowCreateRequest(title=instruction.strip(), graph=graph, enabled=False, source="cli_ask", created_by_assistant=True)


def _looks_like_broad_workflow_edit(instruction: str) -> bool:
    normalized = " ".join(instruction.lower().split())
    if not any(phrase in normalized for phrase in ("all workflows", "all my workflows", "every workflow", "each workflow", "my workflows")):
        return False
    return any(
        term in normalized
        for term in (
            "add ",
            "archive",
            "change",
            "delete",
            "disable",
            "edit",
            "enable",
            "notification",
            "notify",
            "update",
        )
    )


def _workflow_ask_update_operation(patch: WorkflowUpdateRequest) -> str:
    if patch.graph is not None:
        return "workflow_version"
    if patch.enabled is not None and all(
        value is None
        for value in (
            patch.title,
            patch.encrypted_slug,
            patch.slug_lookup_hash,
            patch.description,
            patch.category,
            patch.icon,
            patch.run_content_retention,
        )
    ):
        return "status"
    return "update"


def _workflow_status_snapshot(workflow: Any) -> dict[str, Any]:
    enabled = bool(getattr(workflow, "enabled", False))
    status = getattr(workflow, "status", None)
    status_value = getattr(status, "value", status)
    if status_value is None:
        status_value = "active" if enabled else "disabled"
    return {
        "current_version_id": getattr(workflow, "current_version_id", None),
        "workflow_version_id": getattr(workflow, "current_version_id", None),
        "enabled": enabled,
        "status": str(status_value),
    }


def _workflow_enabled_from_snapshot(snapshot: Any) -> bool | None:
    if not isinstance(snapshot, dict):
        return None
    enabled = snapshot.get("enabled")
    if isinstance(enabled, bool):
        return enabled
    status = snapshot.get("status")
    if status == "active":
        return True
    if status == "disabled":
        return False
    return None


def get_workflow_input_service(request: Request) -> WorkflowInputService:
    service = getattr(request.app.state, "workflow_input_service", None)
    if service is None:
        service = WorkflowInputService(
            workflow_service=get_workflow_service(request),
            planner=WorkflowRegistryPlanner(
                secrets_manager=getattr(request.app.state, "secrets_manager", None),
                workflow_service=get_workflow_service(request),
            ),
            repository=DirectusWorkflowInputRepository(payload_cipher=get_workflow_service(request).payload_cipher),
            checkpoint_store=DragonflyWorkflowInputCheckpointStore(get_workflow_service(request).payload_cipher),
        )
        request.app.state.workflow_input_service = service
    return service


def get_workflow_runtime_service(request: Request) -> WorkflowRuntimeService:
    service = getattr(request.app.state, "workflow_runtime_service", None)
    if service is None:
        service = WorkflowRuntimeService(request.app.state.directus_service)
        request.app.state.workflow_runtime_service = service
    return service


def get_workflow_template_service(request: Request) -> WorkflowTemplateProjectionService:
    service = getattr(request.app.state, "workflow_template_service", None)
    if service is None:
        service = WorkflowTemplateProjectionService(get_workflow_service(request))
        request.app.state.workflow_template_service = service
    return service


def get_workflow_assistant_service(request: Request) -> WorkflowAssistantService:
    service = getattr(request.app.state, "workflow_assistant_service", None)
    if service is None:
        service = WorkflowAssistantService(
            get_workflow_service(request),
            proposal_repository=DirectusWorkflowAssistantProposalRepository(),
        )
        request.app.state.workflow_assistant_service = service
    return service


async def _get_current_user_or_api_key_optional(request: Request, response: Response) -> User | None:
    has_session = "auth_refresh_token" in request.cookies
    has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
    if not has_session and not has_bearer:
        return None
    try:
        return await get_current_user_or_api_key(
            request=request,
            response=response,
            directus_service=request.app.state.directus_service,
            cache_service=request.app.state.cache_service,
            refresh_token=request.cookies.get("auth_refresh_token"),
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            return None
        raise


def _handle_workflow_error(exc: Exception) -> None:
    if isinstance(exc, TeamPermissionError):
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
    if isinstance(exc, TeamWorkspaceMoveError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, WorkflowRuntimeProtocolError):
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    if isinstance(exc, WorkflowFeatureDisabledError):
        raise HTTPException(status_code=403, detail="FEATURE_DISABLED") from exc
    if isinstance(exc, WorkflowNotFoundError):
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    if isinstance(exc, WorkflowMissingInputError):
        raise HTTPException(status_code=400, detail="MISSING_WORKFLOW_INPUT") from exc
    if isinstance(exc, WorkflowRunNotCancellableError):
        raise HTTPException(status_code=400, detail="RUN_NOT_CANCELLABLE") from exc
    if isinstance(exc, WorkflowVersionCurrentError):
        raise HTTPException(status_code=409, detail="WORKFLOW_VERSION_ALREADY_CURRENT") from exc
    if isinstance(exc, WorkflowTeamExecutionUnavailableError):
        raise HTTPException(status_code=409, detail={
            "code": "TEAM_WORKFLOW_EXECUTION_UNAVAILABLE", "message": str(exc),
        }) from exc
    if isinstance(exc, DuplicateObjectSlugError):
        raise HTTPException(status_code=409, detail="WORKFLOW_SLUG_CONFLICT") from exc
    if isinstance(exc, WorkflowTemplateProjectionStaleError):
        raise HTTPException(status_code=409, detail="STALE_TEMPLATE_PROJECTION") from exc
    if isinstance(exc, WorkflowBindingRequirementsUnresolvedError):
        raise HTTPException(status_code=409, detail="UNRESOLVED_WORKFLOW_BINDINGS") from exc
    if isinstance(exc, WorkflowBindingRequirementUnresolvedError):
        raise HTTPException(
            status_code=409,
            detail={"code": "UNRESOLVED_WORKFLOW_BINDING", "reason": exc.reason},
        ) from exc
    if isinstance(exc, (WorkflowTemplateProjectionNotFoundError, WorkflowTemplateProjectionRevokedError)):
        raise HTTPException(status_code=404, detail="Workflow template projection not found") from exc
    if isinstance(exc, (WorkflowTemplateProjectionError, WorkflowTemplateImportError)):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, WorkflowFileTooLargeError):
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if isinstance(exc, WorkflowFileImportError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


async def _require_team_read_role(directus_service: Any, team_id: str | None, current_user: User) -> None:
    if team_id:
        await directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})


def _handle_workflow_input_error(exc: Exception) -> None:
    if isinstance(exc, TeamPermissionError):
        _handle_workflow_error(exc)
    if isinstance(exc, PermissionError | KeyError):
        raise HTTPException(status_code=404, detail="Workflow input session not found") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _handle_workflow_error(exc)


def _is_shifted_direct_user_arg(value: Any) -> bool:
    return not isinstance(value, Request) and hasattr(value, "id") and not hasattr(value, "app")


@router.get("")
@limiter.limit("60/minute")
async def list_workflows(
    request: Request,
    team_id: str | None = Query(default=None),
    app_id: str | None = Query(default=None, min_length=1),
    offset: int | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1, le=50),
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    try:
        del request
        await _require_team_read_role(directus_service, team_id, current_user)
        if app_id is not None or offset is not None or limit is not None:
            page_offset = offset if offset is not None else 0
            page_limit = limit if limit is not None else 20
            workflows, has_more = await run_in_threadpool(
                service.list_workflows_page, current_user.id, current_user.vault_key_id,
                team_id, app_id, page_offset, page_limit,
            )
            return {
                "workflows": [item.model_dump(mode="json") for item in workflows],
                "has_more": has_more, "offset": page_offset, "limit": page_limit,
            }
        workflows = await run_in_threadpool(service.list_workflows, current_user.id, current_user.vault_key_id, team_id)
        return {"workflows": [item.model_dump(mode="json") for item in workflows]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("")
@limiter.limit("30/minute")
async def create_workflow(
    request: Request,
    body: WorkflowCreateRequest,
    team_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    identity_service: WorkflowIdentityService = Depends(get_workflow_identity_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    try:
        if team_id and team_id != body.team_id:
            raise ValueError("Workflow creation Team does not match request context")
        if body.team_id:
            await directus_service.team.require_team_role(body.team_id, current_user.id, {"owner", "admin", "member"})
            if body.enabled:
                raise WorkflowTeamExecutionUnavailableError()
        if body.lifecycle == WorkflowLifecycle.CHAT_EMBED:
            raise ValueError("Use run-once to create a chat-owned workflow")
        _prevalidate_paid_workflow_save(body.graph, enabled=body.enabled)
        await _validate_workflow_ai_check_nodes(request, body.graph, current_user.id)
        warnings = await _validate_workflow_ask_ai_nodes(request, body.graph, current_user.id)
        identity = await _resolve_create_identity(body, identity_service)
        workflow = await run_in_threadpool(
            service.create_workflow,
            current_user.id,
            body.title,
            body.graph,
            body.enabled,
            body.run_content_retention,
            body.lifecycle,
            body.source,
            body.source_chat_id,
            body.created_by_assistant,
            body.auto_delete_at,
            current_user.vault_key_id,
            body.description,
            body.encrypted_slug,
            body.slug_lookup_hash,
            identity.category,
            identity.icon,
            team_id=body.team_id,
        )
        after = workflow.model_dump(mode="json", by_alias=True)
        history = await _record_workflow_history(
            history_service,
            current_user.id,
            action_type="create",
            entries=[{
                "object_type": "workflow",
                "object_id": workflow.id,
                "operation": "create",
                "workflow_version_after_id": workflow.current_version_id,
            }],
            redacted_summary="Created 1 workflow",
        )
        return {"workflow": after, "history": history, "warnings": warnings}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/ask/plan")
@limiter.limit("20/minute")
async def plan_workflow_ask_route(
    request: Request,
    body: WorkflowAskPlanRequest,
    current_user: User = Depends(get_current_user_or_api_key),
) -> dict[str, Any]:
    del current_user
    secrets_manager = getattr(request.app.state, "secrets_manager", None)
    if secrets_manager is None:
        raise HTTPException(status_code=503, detail="Workspace ask inference is not configured")
    try:
        result = await run_workflow_ask_pipeline(body.instruction, secrets_manager)
        return {"proposed_workflow": result.proposal, "inference_used": True, "processing": result.processing}
    except WorkspaceAskPlanningError as exc:
        raise HTTPException(status_code=502, detail=f"Workspace ask inference failed: {exc}") from exc


@router.post("/ask")
@limiter.limit("20/minute")
async def ask_workflows(
    request: Request,
    body: WorkflowAskRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    identity_service: WorkflowIdentityService = Depends(get_workflow_identity_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    input_service: WorkflowInputService = Depends(get_workflow_input_service),
) -> dict[str, Any]:
    if sum(bool(value) for value in (body.create, body.exact_update, body.exact_action)) > 1:
        return _workflow_ask_fallback("Use one exact workflow ask action at a time.")
    if body.exact_action is not None:
        try:
            before = await run_in_threadpool(service.get_workflow, body.exact_action.workflow_id, current_user.id, current_user.vault_key_id)
            if body.exact_action.action == "delete":
                await run_in_threadpool(service.delete_workflow, body.exact_action.workflow_id, current_user.id)
                history = await _record_workflow_history(
                    history_service,
                    current_user.id,
                    source="ai_ask",
                    action_type="ask_delete",
                    entries=[{
                        "object_type": "workflow",
                        "object_id": body.exact_action.workflow_id,
                        "operation": "delete",
                        "workflow_version_before_id": before.current_version_id,
                    }],
                    redacted_summary="Deleted 1 workflow from ask",
                )
                return _workflow_ask_applied_response(
                    summary="Deleted 1 workflow.",
                    history=history,
                    extra={"deleted_workflow_id": body.exact_action.workflow_id},
                )
            enabled = body.exact_action.action == "enable"
            workflow = await run_in_threadpool(
                service.update_workflow,
                body.exact_action.workflow_id,
                current_user.id,
                enabled=enabled,
                vault_key_id=current_user.vault_key_id,
            )
            after = workflow.model_dump(mode="json", by_alias=True)
            summary_verb = "Enabled" if enabled else "Disabled"
            history = await _record_workflow_history(
                history_service,
                current_user.id,
                source="ai_ask",
                action_type=f"ask_{body.exact_action.action}",
                entries=[{
                    "object_type": "workflow",
                    "object_id": body.exact_action.workflow_id,
                    "operation": "status",
                    "before": _workflow_status_snapshot(before),
                    "after": _workflow_status_snapshot(workflow),
                    "workflow_version_before_id": before.current_version_id,
                    "workflow_version_after_id": workflow.current_version_id,
                }],
                redacted_summary=f"{summary_verb} 1 workflow from ask",
            )
            return _workflow_ask_applied_response(summary=f"{summary_verb} 1 workflow.", history=history, extra={"workflow": after})
        except Exception as exc:
            _handle_workflow_error(exc)
    if body.exact_update is not None:
        try:
            before = await run_in_threadpool(service.get_workflow, body.exact_update.workflow_id, current_user.id, current_user.vault_key_id)
            patch = body.exact_update.patch
            if patch.graph is not None:
                _prevalidate_paid_workflow_save(patch.graph, prior_graph=before.graph,
                                                enabled=before.enabled if patch.enabled is None else patch.enabled)
                await _validate_workflow_ai_check_nodes(request, patch.graph, current_user.id, before.graph)
            warnings = (
                await _validate_workflow_ask_ai_nodes(request, patch.graph, current_user.id, before.graph)
                if patch.graph is not None
                else []
            )
            workflow = await run_in_threadpool(
                service.update_workflow,
                body.exact_update.workflow_id,
                current_user.id,
                title=patch.title,
                graph=patch.graph,
                enabled=patch.enabled,
                run_content_retention=patch.run_content_retention,
                vault_key_id=current_user.vault_key_id,
                description=patch.description,
                encrypted_slug=patch.encrypted_slug,
                slug_lookup_hash=patch.slug_lookup_hash,
            )
            after = workflow.model_dump(mode="json", by_alias=True)
            operation = _workflow_ask_update_operation(patch)
            entry = {
                "object_type": "workflow",
                "object_id": body.exact_update.workflow_id,
                "operation": operation,
                "workflow_version_before_id": before.current_version_id,
                "workflow_version_after_id": workflow.current_version_id,
            }
            if operation == "status":
                entry["before"] = _workflow_status_snapshot(before)
                entry["after"] = _workflow_status_snapshot(workflow)
            history = await _record_workflow_history(
                history_service,
                current_user.id,
                source="ai_ask",
                action_type="ask_update",
                entries=[entry],
                redacted_summary="Updated 1 workflow from ask",
            )
            return _workflow_ask_applied_response(
                summary="Updated 1 workflow.",
                history=history,
                extra={"workflow": after, "warnings": warnings},
            )
        except Exception as exc:
            _handle_workflow_error(exc)
    create = body.create
    processing: dict[str, Any] | None = None
    if create is None:
        result = await run_in_threadpool(
            input_service.start,
            user_id=current_user.id, text=body.instruction,
            selected_workflow_id=body.selected_object_id,
            vault_key_id=current_user.vault_key_id,
        )
        if result.status in {"needs_clarification", "failed"}:
            return _workflow_ask_fallback(result.message or result.error or "Workflow authoring needs more detail.")
        details = result.workflows or ([result.workflow] if result.workflow else [])
        return {
            "outcome": "applied", "applied": True, "fallback_to_chat": False,
            "fallback_message": None, "change_set_id": None,
            "summary": f"Saved {len(details)} workflow{'s' if len(details) != 1 else ''}.",
            "changed_entries": result.changes,
            "undo_all_command": f"openmates workflows input-undo {result.session_id}" if result.undo_available else None,
            "undo_entry_commands": [], "warnings": [],
            "workflow": details[0].model_dump(mode="json", by_alias=True) if details else None,
            "workflows": [item.model_dump(mode="json", by_alias=True) for item in details],
            "session": result.model_dump(mode="json", by_alias=True),
            "processing": result.authoring_metrics,
        }
    if create is None:
        return _workflow_ask_fallback("Open a specific workflow to instruct more complex changes.")
    try:
        _prevalidate_paid_workflow_save(create.graph, enabled=create.enabled)
        await _validate_workflow_ai_check_nodes(request, create.graph, current_user.id)
        warnings = await _validate_workflow_ask_ai_nodes(request, create.graph, current_user.id)
        identity = await _resolve_create_identity(create, identity_service)
        workflow = await run_in_threadpool(
            service.create_workflow,
            current_user.id,
            create.title,
            create.graph,
            create.enabled,
            create.run_content_retention,
            create.lifecycle,
            create.source,
            create.source_chat_id,
            create.created_by_assistant,
            create.auto_delete_at,
            current_user.vault_key_id,
            create.description,
            create.encrypted_slug,
            create.slug_lookup_hash,
            identity.category,
            identity.icon,
        )
        after = workflow.model_dump(mode="json", by_alias=True)
        history = await _record_workflow_history(
            history_service,
            current_user.id,
            source="ai_ask",
            action_type="ask_create",
            entries=[{
                "object_type": "workflow",
                "object_id": workflow.id,
                "operation": "create",
                "workflow_version_after_id": workflow.current_version_id,
            }],
            redacted_summary="Created 1 workflow from ask",
        )
        return _workflow_ask_applied_response(
            summary="Created 1 workflow.",
            history=history,
            extra={"workflow": after, "processing": processing, "warnings": warnings},
        )
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/capabilities")
@limiter.limit("60/minute")
async def workflow_capabilities(
    request: Request,
    response: Response,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        current_user = await _get_current_user_or_api_key_optional(request, response)
        user_id = current_user.id if current_user is not None else None
        vault_key_id = current_user.vault_key_id if current_user is not None else None
        capabilities = await run_in_threadpool(service.capabilities, user_id, vault_key_id)
        return {"capabilities": [item.model_dump(mode="json") for item in capabilities]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/validate")
@limiter.limit("30/minute")
async def validate_yaml_workflow(
    request: Request,
    body: WorkflowYamlRequest,
    current_user: User = Depends(get_current_user_or_api_key),
) -> dict[str, Any]:
    """Validate CLI YAML without persisting or executing a workflow."""
    del current_user
    return {"validation": _yaml_validation_payload(body.source)}


@router.post("/ai-authoring/hints")
@limiter.limit("20/minute")
async def workflow_ai_authoring_hints(
    request: Request,
    body: WorkflowAiAuthoringRequest,
    current_user: User = Depends(get_current_user_or_api_key),
) -> dict[str, Any]:
    """Typing suggestions are local; paid validation occurs on Workflow Save."""
    del request, body, current_user
    raise HTTPException(status_code=410, detail="WORKFLOW_AI_HINTS_LOCAL_ONLY")


@router.post("/yaml")
@limiter.limit("30/minute")
async def create_yaml_workflow(
    request: Request,
    body: WorkflowYamlRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    """Create a YAML-authored Workflow as a disabled draft or reject invalid YAML."""
    validation = _yaml_validation_payload(body.source)
    if not validation["draft_valid"]:
        raise HTTPException(status_code=400, detail={"code": "WORKFLOW_YAML_INVALID", **validation})
    try:
        compilation = compile_workflow_yaml(body.source)
        _prevalidate_paid_workflow_save(compilation.graph)
        await _validate_workflow_ai_check_nodes(request, compilation.graph, current_user.id)
        warnings = await _validate_workflow_ask_ai_nodes(request, compilation.graph, current_user.id)
        workflow = await run_in_threadpool(
            service.create_workflow,
            current_user.id,
            compilation.title,
            compilation.graph,
            False,
            WorkflowRunContentRetention(compilation.run_content_retention),
            WorkflowLifecycle.PERSISTED,
            "cli_yaml",
            None,
            False,
            None,
            current_user.vault_key_id,
            compilation.description,
            None,
            None,
        )
        return {
            "workflow": workflow.model_dump(mode="json", by_alias=True),
            "validation": validation,
            "warnings": warnings,
        }
    except WorkflowYamlCompilationError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKFLOW_YAML_INVALID", **validation}) from exc
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/yaml")
@limiter.limit("30/minute")
async def update_yaml_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowYamlRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    """Update a YAML-authored Workflow after authoritative server validation."""
    validation = _yaml_validation_payload(body.source)
    if not validation["draft_valid"]:
        raise HTTPException(status_code=400, detail={"code": "WORKFLOW_YAML_INVALID", **validation})
    try:
        existing = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        if existing.enabled and not validation["enable_ready"]:
            raise HTTPException(status_code=409, detail={"code": "WORKFLOW_YAML_NOT_ENABLE_READY", **validation})
        compilation = compile_workflow_yaml(body.source)
        _prevalidate_paid_workflow_save(compilation.graph, prior_graph=existing.graph, enabled=existing.enabled)
        await _validate_workflow_ai_check_nodes(request, compilation.graph, current_user.id, existing.graph)
        warnings = await _validate_workflow_ask_ai_nodes(request, compilation.graph, current_user.id, existing.graph)
        workflow = await run_in_threadpool(
            service.update_workflow,
            workflow_id,
            current_user.id,
            title=compilation.title,
            description=compilation.description,
            graph=compilation.graph,
            enabled=existing.enabled,
            run_content_retention=WorkflowRunContentRetention(compilation.run_content_retention),
            vault_key_id=current_user.vault_key_id,
        )
        return {
            "workflow": workflow.model_dump(mode="json", by_alias=True),
            "validation": validation,
            "warnings": warnings,
        }
    except HTTPException:
        raise
    except WorkflowYamlCompilationError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKFLOW_YAML_INVALID", **validation}) from exc
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/temporary")
@limiter.limit("60/minute")
async def list_temporary_workflows(
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflows = await run_in_threadpool(service.list_temporary_workflows, current_user.id, current_user.vault_key_id)
        return {"workflows": [item.model_dump(mode="json") for item in workflows]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/input")
@limiter.limit("30/minute")
async def start_workflow_input(
    request: Request,
    body: WorkflowInputStartRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        result = await run_in_threadpool(
            service.start,
            user_id=current_user.id,
            text=body.text,
            input_type=body.input_type,
            audio_ref=body.audio_ref,
            selected_workflow_id=body.selected_workflow_id,
            selected_project_id=body.selected_project_id,
            timezone=body.timezone,
            vault_key_id=current_user.vault_key_id,
            optimistic_save=body.optimistic_save,
            idempotency_key=body.idempotency_key,
            team_id=team_id,
        )
        result = await _dispatch_queued_workflow_input(request, service, current_user, result)
        return {"session": result.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_input_error(exc)


async def _dispatch_queued_workflow_input(
    request: Request, service: WorkflowInputService, current_user: User, result: Any,
) -> Any:
    if result.status != "queued":
        return result
    cache_key = f"workflow-input:pending:{_hash_owner_id(current_user.id)}:{result.session_id}"
    try:
        client = await request.app.state.cache_service.client
        if client is not None:
            await client.set(cache_key, json.dumps({
                "session_id": result.session_id, "status": "queued", "event_cursor": result.event_cursor,
                "message": result.message,
            }), ex=10)
        from backend.core.api.app.tasks.workflow_tasks import commit_workflow_input_task
        commit_workflow_input_task.apply_async(args=[result.session_id], queue="workflow")
    except Exception:
        # The encrypted plan is durable; complete it here if the broker is unavailable.
        committed = await run_in_threadpool(service.commit_queued, result.session_id)
        if committed is not None:
            result = committed
        try:
            client = await request.app.state.cache_service.client
            if client is not None:
                await client.delete(cache_key)
        except Exception:
            pass
    return result


@router.post("/input/stream")
@limiter.limit("30/minute")
async def stream_workflow_input(
    request: Request,
    body: WorkflowInputStartRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
    team_id: str | None = Query(default=None),
) -> StreamingResponse:
    """Stream validated node prefixes while planning and persist the final or partial plan."""
    team_id = team_id if isinstance(team_id, str) else None
    if team_id:
        try:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        except Exception as exc:
            _handle_workflow_error(exc)
    async def events():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def run() -> None:
            try:
                result = await run_in_threadpool(
                    service.start,
                    user_id=current_user.id, text=body.text, input_type=body.input_type,
                    audio_ref=body.audio_ref, selected_workflow_id=body.selected_workflow_id,
                    selected_project_id=body.selected_project_id, timezone=body.timezone,
                    vault_key_id=current_user.vault_key_id, optimistic_save=body.optimistic_save,
                    idempotency_key=body.idempotency_key,
                    team_id=team_id,
                    on_event=emit,
                )
                result = await _dispatch_queued_workflow_input(request, service, current_user, result)
                await queue.put({"type": "session", "session": result.model_dump(mode="json", by_alias=True)})
            except Exception:
                await queue.put({"type": "error", "error": "Workflow input failed. Please try again."})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
        finally:
            # The thread can still finish and save the already submitted request.
            if not task.done():
                task.add_done_callback(lambda finished: finished.exception() if not finished.cancelled() else None)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/input/{session_id}")
@limiter.limit("60/minute")
async def get_workflow_input_session(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await _require_team_read_role(get_directus_service(request), team_id, current_user)
        # A queued status response includes its renderable preview. The short
        # Dragonfly marker deliberately contains no private graph, so status
        # reads use the encrypted durable session as their source of truth.
        result = await run_in_threadpool(service.status, session_id, current_user.id, current_user.vault_key_id, team_id)
        return {"session": result.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.get("/input/{session_id}/events")
@limiter.limit("60/minute")
async def list_workflow_input_events(
    session_id: str,
    request: Request,
    after_event_id: int = 0,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await _require_team_read_role(get_directus_service(request), team_id, current_user)
        events = await run_in_threadpool(service.events, session_id, after_event_id, current_user.id, current_user.vault_key_id, team_id)
        return {"events": [event.model_dump(mode="json") for event in events]}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.post("/input/{session_id}/follow-up")
@limiter.limit("30/minute")
async def follow_up_workflow_input(
    session_id: str,
    request: Request,
    body: WorkflowInputFollowUpRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        result = await run_in_threadpool(
            service.follow_up,
            user_id=current_user.id,
            session_id=session_id,
            text=body.text,
            vault_key_id=current_user.vault_key_id,
            team_id=team_id,
        )
        return {"session": result.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.post("/input/{session_id}/stop")
@limiter.limit("30/minute")
async def stop_workflow_input(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        result = await run_in_threadpool(
            service.stop,
            user_id=current_user.id,
            session_id=session_id,
            vault_key_id=current_user.vault_key_id,
            team_id=team_id,
        )
        if result.status == "stopped":
            try:
                client = await request.app.state.cache_service.client
                if client is not None:
                    await client.delete(f"workflow-input:pending:{_hash_owner_id(current_user.id)}:{session_id}")
            except Exception:
                pass
        return {"session": result.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.post("/input/{session_id}/undo")
@limiter.limit("30/minute")
async def undo_workflow_input(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        result = await run_in_threadpool(
            service.undo,
            user_id=current_user.id,
            session_id=session_id,
            vault_key_id=current_user.vault_key_id,
            team_id=team_id,
        )
        return {"session": result.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.get("/{workflow_id}/template-projection")
@limiter.limit("60/minute")
async def get_owner_workflow_template_projection(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    try:
        projection = await run_in_threadpool(service.get_owner_projection, workflow_id, current_user.id)
        return projection.model_dump(mode="json", exclude={"owner_hash"})
    except Exception as exc:
        _handle_workflow_error(exc)


@router.put("/{workflow_id}/template-projection")
@limiter.limit("30/minute")
async def upsert_workflow_template_projection(
    workflow_id: str,
    request: Request,
    body: WorkflowTemplateProjectionUpsertRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    try:
        projection = await run_in_threadpool(
            service.upsert_projection,
            workflow_id,
            current_user.id,
            template_id=body.template_id,
            source_version=body.source_version,
            ciphertext=body.ciphertext,
            ciphertext_checksum=body.ciphertext_checksum,
            owner_wrapped_key=body.owner_wrapped_key,
            projection_schema_version=body.projection_schema_version,
        )
        return {
            "template_id": projection.template_id,
            "source_version": projection.source_version,
            "updated_at": projection.updated_at,
        }
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/template-import")
@limiter.limit("20/minute")
async def import_workflow_template(
    request: Request,
    body: WorkflowTemplateImportPayload,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    try:
        imported = await run_in_threadpool(service.import_template, current_user.id, body)
        workflow = imported.workflow.model_dump(mode="json", by_alias=True)
        workflow["binding_requirements"] = imported.binding_requirements
        return {"workflow": workflow}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/file-import")
@limiter.limit("30/minute")
async def import_workflow_file(
    request: Request,
    body: WorkflowFileDocument,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    """Session or approved-device create surface; owner-scoped Vault storage."""
    try:
        file_service = WorkflowFileService(service)
        document, graph = await run_in_threadpool(file_service.validate_document, body)
        _prevalidate_paid_workflow_save(graph)
        await _validate_workflow_ai_check_nodes(request, graph, current_user.id)
        warnings = await _validate_workflow_ask_ai_nodes(request, graph, current_user.id)
        workflow = await run_in_threadpool(
            file_service.import_document, current_user.id, document, graph, current_user.vault_key_id,
        )
        return {"workflow": workflow.model_dump(mode="json", by_alias=True), "warnings": warnings}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/assistant-proposals/{proposal_id}")
@limiter.limit("60/minute")
async def get_workflow_assistant_proposal(
    proposal_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowAssistantService = Depends(get_workflow_assistant_service),
) -> dict[str, Any]:
    return await run_in_threadpool(service.get_draft_preview, current_user.id, proposal_id)


@router.post("/assistant-proposals/{proposal_id}/save")
@limiter.limit("30/minute")
async def save_workflow_assistant_proposal(
    proposal_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowAssistantService = Depends(get_workflow_assistant_service),
    runtime_service: WorkflowRuntimeService = Depends(get_workflow_runtime_service),
) -> dict[str, Any]:
    return await service.save(
        current_user.id,
        proposal_id,
        runtime_service,
        _dispatch_accepted_workflow_run,
    )


@router.post("/assistant-proposals/{proposal_id}/cancel")
@limiter.limit("30/minute")
async def cancel_workflow_assistant_proposal(
    proposal_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowAssistantService = Depends(get_workflow_assistant_service),
) -> dict[str, bool]:
    return {"cancelled": await run_in_threadpool(service.cancel_pending, current_user.id, proposal_id)}


@router.post("/assistant-proposals/{proposal_id}/confirm-delete")
@limiter.limit("20/minute")
async def confirm_workflow_assistant_delete(
    proposal_id: str,
    request: Request,
    body: WorkflowAssistantDeleteConfirmationRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowAssistantService = Depends(get_workflow_assistant_service),
    runtime_service: WorkflowRuntimeService = Depends(get_workflow_runtime_service),
) -> dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="DELETE_CONFIRMATION_REQUIRED")
    return await service.confirm_delete(
        current_user.id,
        proposal_id,
        runtime_service,
        _dispatch_accepted_workflow_run,
    )


@router.get("/template-projections/{template_id}")
@limiter.limit("60/minute")
async def get_public_workflow_template_projection(
    template_id: str,
    request: Request,
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    """Serve a revocation-aware opaque projection without exposing key material."""
    try:
        projection = await run_in_threadpool(service.get_public_projection, template_id)
        return projection.model_dump(mode="json")
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/template-projection/revoke")
@limiter.limit("30/minute")
async def revoke_workflow_template_projection(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    try:
        projection = await run_in_threadpool(service.revoke_projection, workflow_id, current_user.id)
        return {"template_id": projection.template_id, "revoked_at": projection.revoked_at}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/template-projection/unrevoke")
@limiter.limit("30/minute")
async def unrevoke_workflow_template_projection(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    try:
        projection = await run_in_threadpool(service.unrevoke_projection, workflow_id, current_user.id)
        return {"template_id": projection.template_id, "revoked_at": projection.revoked_at}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/binding-requirements/complete")
@limiter.limit("30/minute")
async def complete_workflow_template_binding(
    workflow_id: str,
    body: WorkflowTemplateBindingCompletionRequest,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    """Persist only binding completion proven by the matching server service."""
    try:
        if body.type == "chat_destination":
            if bool(body.chat_id) == body.new_chat:
                raise WorkflowBindingRequirementUnresolvedError("CHAT_DESTINATION_SELECTION_REQUIRED")
            await run_in_threadpool(
                service.get_import_binding_requirement,
                workflow_id,
                current_user.id,
                "chat_destination",
                body.node_id,
            )
            if body.chat_id and not await directus_service.chat.check_chat_ownership(body.chat_id, current_user.id):
                raise WorkflowBindingRequirementUnresolvedError("CHAT_DESTINATION_NOT_OWNED")
            completed = await run_in_threadpool(
                service.complete_chat_destination_binding,
                workflow_id,
                current_user.id,
                body.node_id,
                chat_id=body.chat_id,
                new_chat=body.new_chat,
                vault_key_id=current_user.vault_key_id,
            )
            workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
            return {"workflow_id": workflow_id, "binding_requirement": completed, "completed": True,
                    "workflow": workflow.model_dump(mode="json", by_alias=True)}
        if body.chat_id or body.new_chat:
            raise WorkflowBindingRequirementUnresolvedError("CHAT_DESTINATION_SELECTION_UNEXPECTED")
        if body.type == "schedule":
            requirement = await run_in_threadpool(
                service.validate_schedule_binding_requirement,
                workflow_id,
                current_user.id,
                body.node_id,
                current_user.vault_key_id,
            )
        elif body.type == "app_skill":
            registry = getattr(request.app.state, "skill_registry", None)
            if registry is None:
                from backend.core.api.app.services.skill_registry import get_global_registry

                registry = get_global_registry()
            requirement = await run_in_threadpool(
                service.validate_app_skill_binding_requirement,
                workflow_id,
                current_user.id,
                body.node_id,
                registry,
                current_user.vault_key_id,
            )
        elif body.type == "notification_preferences":
            requirement = await run_in_threadpool(
                service.get_import_binding_requirement,
                workflow_id,
                current_user.id,
                body.type,
                body.node_id,
            )
            try:
                await WorkflowActionAdapter().validate_notification_binding(current_user.id)
            except WorkflowActionExecutionError as exc:
                raise WorkflowBindingRequirementUnresolvedError(exc.code) from exc
        else:
            raise WorkflowBindingRequirementUnresolvedError("BINDING_TYPE_UNSUPPORTED")
        completed = await run_in_threadpool(
            service.complete_import_binding_requirement,
            workflow_id,
            current_user.id,
            requirement,
        )
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        return {"workflow_id": workflow_id, "binding_requirement": completed, "completed": True,
                "workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/versions")
@limiter.limit("60/minute")
async def list_workflow_versions(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        if _is_shifted_direct_user_arg(request):
            service = current_user
            current_user = request
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await _require_team_read_role(get_directus_service(request), team_id, current_user)
        versions = await run_in_threadpool(service.list_workflow_versions, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        return {
            "versions": [version.model_dump(mode="json") for version in versions],
            "current_version_id": service.get_workflow(workflow_id, current_user.id, current_user.vault_key_id, team_id).current_version_id,
            "retention": {"mode": "last_25_versions", "max_versions": 25},
        }
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/versions/{version_id}")
@limiter.limit("60/minute")
async def get_workflow_version(
    workflow_id: str,
    version_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        if _is_shifted_direct_user_arg(request):
            service = current_user
            current_user = request
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await _require_team_read_role(get_directus_service(request), team_id, current_user)
        version = await run_in_threadpool(
            service.get_workflow_version_detail,
            workflow_id,
            current_user.id,
            version_id,
            current_user.vault_key_id,
            team_id,
        )
        return {"version": version.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/versions/{version_id}/restore")
@limiter.limit("20/minute")
async def restore_workflow_version(
    workflow_id: str,
    version_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        if _is_shifted_direct_user_arg(request):
            service = current_user
            current_user = request
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        before = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        workflow = await run_in_threadpool(
            service.restore_workflow_version,
            workflow_id,
            current_user.id,
            version_id,
            current_user.vault_key_id,
            team_id,
        )
        after = workflow.model_dump(mode="json", by_alias=True)
        response = {"workflow": after}
        if hasattr(history_service, "record_change_set"):
            response["history"] = await _record_workflow_history(
                history_service,
                current_user.id,
                action_type="restore",
                entries=[{
                    "object_type": "workflow",
                    "object_id": workflow_id,
                    "operation": "restore",
                    "workflow_version_before_id": before.current_version_id,
                    "workflow_version_after_id": workflow.current_version_id,
                }],
                redacted_summary="Restored 1 workflow version",
            )
        return response
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/history")
@limiter.limit("60/minute")
async def list_workflow_history(
    workflow_id: str,
    request: Request,
    limit: int = 50,
    current_user: User = Depends(get_current_user_or_api_key),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    entries = await history_service.list_object_history(current_user.id, object_type="workflow", object_id=workflow_id, limit=limit)
    return {"entries": entries}


@router.post("/{workflow_id}/restore")
@limiter.limit("20/minute")
async def restore_workflow_from_history(
    workflow_id: str,
    request: Request,
    body: WorkflowHistoryRestoreRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    try:
        entry = await history_service.get_object_entry(current_user.id, object_type="workflow", object_id=workflow_id, entry_id=body.entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Workspace history entry not found")
        snapshot = history_service.snapshot_for_entry_state(entry, body.state)
        version_id = snapshot.get("workflow_version_id") if isinstance(snapshot, dict) else None
        if not version_id:
            raise HTTPException(status_code=400, detail="History entry does not contain a workflow version for restore")
        before = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        target_enabled = _workflow_enabled_from_snapshot(snapshot) if entry.get("operation") == "status" else None
        if target_enabled is None:
            workflow = await run_in_threadpool(
                service.restore_workflow_version,
                workflow_id,
                current_user.id,
                version_id,
                current_user.vault_key_id,
            )
            operation = "restore"
        else:
            workflow = await run_in_threadpool(
                service.update_workflow,
                workflow_id,
                current_user.id,
                enabled=target_enabled,
                vault_key_id=current_user.vault_key_id,
            )
            operation = "status"
        after = workflow.model_dump(mode="json", by_alias=True)
        history_entry = {
            "object_type": "workflow",
            "object_id": workflow_id,
            "operation": operation,
            "workflow_version_before_id": before.current_version_id,
            "workflow_version_after_id": workflow.current_version_id,
            "restored_from_entry_id": body.entry_id,
            "restore_state": body.state,
        }
        if operation == "status":
            history_entry["before"] = _workflow_status_snapshot(before)
            history_entry["after"] = _workflow_status_snapshot(workflow)
        history = await _record_workflow_history(
            history_service,
            current_user.id,
            action_type="restore",
            entries=[history_entry],
            redacted_summary="Restored 1 workflow from history",
        )
        return {"workflow": after, "history": history}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}")
@limiter.limit("60/minute")
async def get_workflow(
    workflow_id: str,
    request: Request,
    team_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    try:
        await _require_team_read_role(directus_service, team_id, current_user)
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/move")
@limiter.limit("20/minute")
async def move_workflow_to_team(
    workflow_id: str,
    request: Request,
    body: WorkflowMoveRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    try:
        workflow = await move_workspace_record_to_team(
            directus_service=directus_service,
            actor_user_id=current_user.id,
            team_id=body.team_id,
            workspace_type="workflow",
            object_id=workflow_id,
            confirmed=body.confirmed,
            encrypted_slug=body.encrypted_slug,
            slug_lookup_hash=body.slug_lookup_hash,
            moved_at=body.moved_at,
        )
        return {"workflow": workflow}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.patch("/{workflow_id}")
@limiter.limit("30/minute")
async def update_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowUpdateRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    team_id: str | None = Query(default=None),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    try:
        if team_id:
            await directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
            if body.enabled is True:
                raise WorkflowTeamExecutionUnavailableError()
        before = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        if body.graph is not None:
            _prevalidate_paid_workflow_save(body.graph, prior_graph=before.graph,
                                            enabled=before.enabled if body.enabled is None else body.enabled)
            await _validate_workflow_ai_check_nodes(request, body.graph, current_user.id, before.graph)
        warnings = (
            await _validate_workflow_ask_ai_nodes(request, body.graph, current_user.id, before.graph)
            if body.graph is not None
            else []
        )
        identity = (
            normalize_workflow_identity(body.category or before.category, body.icon or before.icon)
            if body.category is not None or body.icon is not None
            else None
        )
        workflow = await run_in_threadpool(
            service.update_workflow,
            workflow_id,
            current_user.id,
            title=body.title,
            graph=body.graph,
            enabled=body.enabled,
            run_content_retention=body.run_content_retention,
            vault_key_id=current_user.vault_key_id,
            description=body.description,
            encrypted_slug=body.encrypted_slug,
            slug_lookup_hash=body.slug_lookup_hash,
            category=identity.category if identity else None,
            icon=identity.icon if identity else None,
            team_id=team_id,
        )
        after = workflow.model_dump(mode="json", by_alias=True)
        operation = _workflow_ask_update_operation(body)
        history_entry = {
            "object_type": "workflow",
            "object_id": workflow_id,
            "operation": operation,
            "workflow_version_before_id": before.current_version_id,
            "workflow_version_after_id": workflow.current_version_id,
        }
        if operation == "status":
            history_entry["before"] = _workflow_status_snapshot(before)
            history_entry["after"] = _workflow_status_snapshot(workflow)
        history = await _record_workflow_history(
            history_service,
            current_user.id,
            action_type="update",
            entries=[history_entry],
            redacted_summary="Updated 1 workflow",
        )
        return {"workflow": after, "history": history, "warnings": warnings}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.delete("/{workflow_id}")
@limiter.limit("20/minute")
async def delete_workflow(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    team_id: str | None = Query(default=None),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    try:
        if team_id:
            await directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        before = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        await run_in_threadpool(service.delete_workflow, workflow_id, current_user.id, team_id)
        history = await _record_workflow_history(
            history_service,
            current_user.id,
            action_type="delete",
            entries=[{
                "object_type": "workflow",
                "object_id": workflow_id,
                "operation": "delete",
                "workflow_version_before_id": before.current_version_id,
            }],
            redacted_summary="Deleted 1 workflow",
        )
        return {"deleted": True, "history": history}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/enable")
@limiter.limit("30/minute")
async def enable_workflow(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
            raise WorkflowTeamExecutionUnavailableError()
        before = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        workflow = await run_in_threadpool(service.update_workflow, workflow_id, current_user.id, enabled=True, vault_key_id=current_user.vault_key_id, team_id=team_id)
        after = workflow.model_dump(mode="json", by_alias=True)
        history = await _record_workflow_history(
            history_service,
            current_user.id,
            action_type="enable",
            entries=[{
                "object_type": "workflow",
                "object_id": workflow_id,
                "operation": "status",
                "before": _workflow_status_snapshot(before),
                "after": _workflow_status_snapshot(workflow),
                "workflow_version_before_id": before.current_version_id,
                "workflow_version_after_id": workflow.current_version_id,
            }],
            redacted_summary="Enabled 1 workflow",
        )
        return {"workflow": after, "history": history}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/disable")
@limiter.limit("30/minute")
async def disable_workflow(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await get_directus_service(request).team.require_team_role(team_id, current_user.id, {"owner", "admin", "member"})
        before = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        workflow = await run_in_threadpool(service.update_workflow, workflow_id, current_user.id, enabled=False, vault_key_id=current_user.vault_key_id, team_id=team_id)
        after = workflow.model_dump(mode="json", by_alias=True)
        history = await _record_workflow_history(
            history_service,
            current_user.id,
            action_type="disable",
            entries=[{
                "object_type": "workflow",
                "object_id": workflow_id,
                "operation": "status",
                "before": _workflow_status_snapshot(before),
                "after": _workflow_status_snapshot(workflow),
                "workflow_version_before_id": before.current_version_id,
                "workflow_version_after_id": workflow.current_version_id,
            }],
            redacted_summary="Disabled 1 workflow",
        )
        return {"workflow": after, "history": history}
    except Exception as exc:
        _handle_workflow_error(exc)


async def _validated_invocation(
    request: Request, body: WorkflowRunRequest, graph: WorkflowGraph,
    user_id: str, directus_service: Any,
) -> dict[str, Any]:
    """First-party chat context, checked before a billable run is accepted."""
    state = getattr(request, "state", None)
    chat_context = bool(body.source_chat_id or body.message_destination_overrides or body.return_outputs)
    if chat_context and getattr(state, "auth_source", None) == "api_key":
        auth_info = getattr(state, "auth_info", {}) or {}
        if not auth_info.get("device_hash"):
            raise HTTPException(status_code=403, detail="FIRST_PARTY_DEVICE_REQUIRED")
        from backend.core.api.app.services.api_key_authorization import ApiKeyAuthorizationService, ApiKeyScopeError
        try:
            scopes = ApiKeyAuthorizationService()
            metadata = auth_info.get("api_key_metadata") or {}
            scopes.require_scope(metadata, "chat", "chat:read_existing")
            if body.source_chat_id or body.message_destination_overrides:
                scopes.require_scope(metadata, "chat", "chat:append_existing")
        except ApiKeyScopeError as exc:
            raise HTTPException(status_code=403, detail={"error": "missing_scope", "missing_scope": exc.missing_scope}) from exc
    if len(body.message_destination_overrides) > 20:
        raise ValueError("Too many workflow invocation routes")
    node_by_id = {node.id: node for node in graph.nodes}
    for node_id, chat_id in body.message_destination_overrides.items():
        if (not isinstance(node_id, str) or not isinstance(chat_id, str)
                or len(chat_id) > 200 or not chat_id
                or node_by_id.get(node_id) is None
                or node_by_id[node_id].type != WorkflowNodeType.SEND_CHAT_MESSAGE):
            raise ValueError("Invalid Send node destination override")
    validate_workflow_return_outputs(graph, body.return_outputs)
    for chat_id in {body.source_chat_id, *body.message_destination_overrides.values()} - {None}:
        if not await directus_service.chat.check_chat_ownership(chat_id, user_id):
            raise HTTPException(status_code=403, detail="CHAT_NOT_OWNED")
    return {
        "source_chat_id": body.source_chat_id,
        "message_destination_overrides": body.message_destination_overrides,
        "return_outputs": body.return_outputs,
        "input": body.input,
    }


async def _accept_workflow_run(
    workflow_id: str, body: WorkflowRunRequest, request: Request, user: User,
    service: WorkflowService, runtime_service: WorkflowRuntimeService,
    directus_service: Any, workflow: Any,
) -> dict[str, Any]:
    invocation = await _validated_invocation(request, body, workflow.graph, user.id, directus_service)
    await run_in_threadpool(
        service.validate_manual_run_input, workflow, body.input,
        allow_return_outputs=bool(invocation["return_outputs"]),
    )
    await run_in_threadpool(service.ensure_import_bindings_resolved, workflow_id, user.id)
    idempotency_key = request.headers.get("Idempotency-Key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 255:
        raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
    invocation_hash = hashlib.sha256(json.dumps(invocation, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    invocation_ref = await run_in_threadpool(service.save_run_invocation_blob, user.id, invocation, user.vault_key_id)
    try:
        accepted = await runtime_service.execute("accept_manual_run", {
            "workflow_id": workflow_id,
            "hashed_user_id": service.repository.workflow_owner_hash(user.id),
            "trigger_type": body.mode,
            "idempotency_key": idempotency_key,
            "encrypted_invocation_ref": invocation_ref,
            "invocation_hash": invocation_hash,
        })
    except Exception:
        await run_in_threadpool(service.repository.delete_encrypted_blob, invocation_ref)
        raise
    if not accepted.get("accepted"):
        await run_in_threadpool(service.repository.delete_encrypted_blob, invocation_ref)
    run_id = _accepted_run_field(accepted, "run_id")
    version_id = _accepted_run_field(accepted, "version_id")
    if accepted.get("status") == "queued":
        _dispatch_accepted_workflow_run(workflow_id, user.id, run_id, version_id, body.mode, body.input, invocation)
    return _accepted_run_response(accepted, workflow_id, body.mode)


@router.post("/run-once")
@limiter.limit("20/minute")
async def run_workflow_once(
    body: WorkflowRunOnceRequest,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    runtime_service: WorkflowRuntimeService = Depends(get_workflow_runtime_service),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    """First-party chat execution with an immutable, encrypted definition."""
    try:
        invocation = await _validated_invocation(request, body, body.graph, current_user.id, directus_service)
        from backend.core.api.app.services.workflow_models import validate_manual_run_input
        validate_manual_run_input(body.graph, body.input, allow_return_outputs=bool(invocation["return_outputs"]))
        validate_workflow_readiness(body.graph, require_schedule=False, allow_return_outputs=bool(invocation["return_outputs"]))
        _prevalidate_paid_workflow_save(body.graph)
        await _validate_workflow_ai_check_nodes(request, body.graph, current_user.id)
        await _validate_workflow_ask_ai_nodes(request, body.graph, current_user.id)
        idempotency_key = request.headers.get("Idempotency-Key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        workflow_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-run-once:{current_user.id}:{body.source_chat_id}:{idempotency_key}"))
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-run-once-version:{workflow_id}"))
        try:
            prior = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        except WorkflowNotFoundError:
            prior = None
        if prior is not None and (
            prior.lifecycle != WorkflowLifecycle.CHAT_EMBED or prior.source_chat_id != body.source_chat_id
            or prior.title != body.title or prior.graph != body.graph
        ):
            raise HTTPException(status_code=409, detail="WORKFLOW_RUN_ONCE_IDEMPOTENCY_CONFLICT")
        workflow = await run_in_threadpool(
            service.create_workflow, current_user.id, body.title, body.graph,
            False, WorkflowRunContentRetention.LAST_5, WorkflowLifecycle.CHAT_EMBED,
            "chat_run_once", body.source_chat_id, True, None, current_user.vault_key_id,
            workflow_id=workflow_id, initial_version_id=version_id,
            allow_data_dependencies=True,
        )
        run = await _accept_workflow_run(workflow.id, body, request, current_user, service, runtime_service, directus_service, workflow)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True), "run": run}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/save-as-reusable")
@limiter.limit("20/minute")
async def save_workflow_as_reusable(
    workflow_id: str,
    body: WorkflowSaveAsReusableRequest,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    """First-party copy of a retained chat definition; no run history is moved."""
    try:
        state = getattr(request, "state", None)
        if getattr(state, "auth_source", None) == "api_key" and not (getattr(state, "auth_info", {}) or {}).get("device_hash"):
            raise HTTPException(status_code=403, detail="FIRST_PARTY_DEVICE_REQUIRED")
        key = body.idempotency_key or request.headers.get("Idempotency-Key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        workflow = await run_in_threadpool(service.save_chat_embed_as_reusable, workflow_id, current_user.id, key, current_user.vault_key_id)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/run")
@limiter.limit("20/minute")
async def run_workflow(
    workflow_id: str,
    body: WorkflowRunRequest,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    runtime_service: WorkflowRuntimeService = Depends(get_workflow_runtime_service),
    directus_service: Any = Depends(get_directus_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        run = await _accept_workflow_run(workflow_id, body, request, current_user, service, runtime_service, directus_service, workflow)
        return {"run": run}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/steps/{step_id}/test")
@limiter.limit("20/minute")
async def test_workflow_step(
    workflow_id: str,
    step_id: str,
    request: Request,
    body: WorkflowStepTestRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> Any:
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        node = _workflow_editor_node(workflow.graph, step_id, body)
        if node.type == WorkflowNodeType.APP_SKILL_ACTION:
            from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
            capability = WorkflowCapabilityRegistry().get_capability(f"{node.config['app_id']}.{node.config['skill_id']}")
            metadata = capability.metadata.get("workflow") or {}
            if not capability.enabled or not metadata.get("test_allowed") or metadata.get("effect") != "read":
                raise HTTPException(status_code=409, detail="WORKFLOW_STEP_TEST_UNAVAILABLE")
        elif node.type != WorkflowNodeType.CHECK:
            raise HTTPException(status_code=409, detail="WORKFLOW_STEP_TEST_UNAVAILABLE")
        draft_nodes = [item for item in workflow.graph.nodes if item.id != step_id] + [node]
        draft = workflow.model_copy(update={"graph": workflow.graph.model_copy(update={"nodes": draft_nodes})})
        validate_workflow_composition_refs(draft.graph, prior_graph=workflow.graph)
        # Draft Tests need the same initialized safety dependencies as worker runs.
        # The output scanner remains mandatory and fails closed on any scan error.
        adapter = WorkflowAppSkillAdapter(
            secrets_manager=getattr(request.app.state, "secrets_manager", None),
            cache_service=getattr(request.app.state, "cache_service", None),
        )
        runner = WorkflowRunner(service, app_skill_adapter=adapter)
        if getattr(body, "stream", False) and node.type == WorkflowNodeType.APP_SKILL_ACTION and node.config.get("app_id") == "ai" and node.config.get("skill_id") == "ask":
            async def events():
                queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
                viewer_connected = True
                produced_run_id: str | None = None

                def enqueue(event: dict[str, Any], *, terminal: bool = False) -> None:
                    if not viewer_connected:
                        return
                    if terminal:
                        while queue.full():
                            queue.get_nowait()
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        # Intermediate cumulative snapshots may be skipped; the
                        # next snapshot and terminal run are authoritative.
                        pass

                async def progress(kind: str, value: str) -> None:
                    nonlocal produced_run_id
                    if kind == "processing":
                        produced_run_id = value
                        enqueue({"type": "processing", "run_id": value})
                    elif kind == "chunk":
                        enqueue({"type": "chunk", "content": value})
                    elif kind == "embeds":
                        enqueue({"type": "embeds", "embeds": json.loads(value)})

                async def produce() -> None:
                    try:
                        result = await runner.run_step_test(
                            draft, current_user.id, step_id, input_override=body.input,
                            upstream_outputs=body.upstream_outputs,
                            vault_key_id=current_user.vault_key_id, on_progress=progress,
                        )
                        if result.status == WorkflowRunStatus.FAILED:
                            failed = result.node_runs[0] if result.node_runs else None
                            enqueue({"type": "error", "code": failed.error_code if failed else "WORKFLOW_STEP_FAILED",
                                     "message": "Ask AI could not complete this step", "run": result.model_dump(mode="json")}, terminal=True)
                        else:
                            enqueue({"type": "completed", "run": result.model_dump(mode="json")}, terminal=True)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.error(
                            "Ask AI step-test producer failed workflow_id=%s step_id=%s run_id=%s exception_type=%s",
                            workflow_id, step_id, produced_run_id, type(exc).__name__,
                        )
                        enqueue({"type": "error", "code": "WORKFLOW_STEP_FAILED",
                                 "message": "Ask AI could not complete this step"}, terminal=True)

                producer = asyncio.create_task(produce())
                _STEP_TEST_PRODUCERS.add(producer)
                producer.add_done_callback(_STEP_TEST_PRODUCERS.discard)
                try:
                    while True:
                        if await request.is_disconnected():
                            break
                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=1.0)
                        except TimeoutError:
                            continue
                        yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
                        if event["type"] in {"completed", "error"}:
                            break
                finally:
                    # Inference can already have charged the owner. Let its run
                    # finish and persist even when this viewer closes the stream.
                    viewer_connected = False

            return StreamingResponse(events(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        run = await runner.run_step_test(
            draft, current_user.id, step_id, input_override=body.input,
            upstream_outputs=body.upstream_outputs, vault_key_id=current_user.vault_key_id,
        )
        return {"run": run.model_dump(mode="json")}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_workflow_error(exc)


def _workflow_editor_node(graph: WorkflowGraph, step_id: str, body: WorkflowStepTestRequest) -> WorkflowNode:
    """Validate a draft node independently without writing the definition."""
    node = body.node or next((item for item in graph.nodes if item.id == step_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="Workflow step not found")
    if node.id != step_id:
        raise HTTPException(status_code=422, detail="WORKFLOW_STEP_ID_MISMATCH")
    WorkflowGraph(nodes=[node])
    return node


@router.post("/{workflow_id}/steps/{step_id}/preview")
@limiter.limit("30/minute")
async def preview_workflow_message(
    workflow_id: str,
    step_id: str,
    request: Request,
    body: WorkflowStepTestRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    """Render unsaved deterministic content without delivery or history writes."""
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        node = _workflow_editor_node(workflow.graph, step_id, body)
        if node.type != WorkflowNodeType.SEND_CHAT_MESSAGE:
            raise HTTPException(status_code=409, detail="WORKFLOW_PREVIEW_SEND_MESSAGE_ONLY")
        context = {
            "nodes": {node_id: {"output": output} for node_id, output in body.upstream_outputs.items()},
            "trigger": {"input": body.input},
            "variables": workflow.graph.variables,
        }
        preview = await WorkflowActionAdapter().preview_message(node.config, context)
        return {"preview": preview}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.delete("/{workflow_id}/runs/{run_id}")
@limiter.limit("20/minute")
async def delete_workflow_run(
    workflow_id: str,
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    """Delete owned run history and its delivered-result membership."""
    try:
        return await run_in_threadpool(service.delete_run, workflow_id, run_id, current_user.id, current_user.vault_key_id)
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/runs/{run_id}/respond")
@limiter.limit("20/minute")
async def respond_to_workflow_run_wait(
    workflow_id: str,
    run_id: str,
    request: Request,
    body: WorkflowRunResponseRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        run = await run_in_threadpool(service.get_run, workflow_id, run_id, current_user.id, current_user.vault_key_id)
        if run.status.value != "waiting":
            raise HTTPException(status_code=409, detail="WORKFLOW_RUN_NOT_WAITING")
        if not any(node.node_id == body.step_id and node.output_summary.get("wait_for_user_input") for node in run.node_runs):
            raise HTTPException(status_code=404, detail="Workflow wait step not found")
        output_summary = dict(run.output_summary)
        output_summary["user_input_response"] = {"step_id": body.step_id, "input": body.input}
        completed = run.model_copy(
            update={
                "status": WorkflowRunStatus.COMPLETED,
                "finished_at": int(time.time()),
                "output_summary": output_summary,
            }
        )
        saved = await run_in_threadpool(service.save_run, current_user.id, completed, current_user.vault_key_id)
        return {"run": saved.model_dump(mode="json")}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_workflow_error(exc)


def _accepted_run_field(accepted: dict[str, Any], field: str) -> str:
    value = accepted.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Workflow runtime acceptance returned invalid {field}")
    return value


def _dispatch_accepted_workflow_run(
    workflow_id: str,
    user_id: str,
    run_id: str,
    version_id: str,
    trigger_type: str,
    input_payload: dict[str, Any],
    invocation: dict[str, Any] | None = None,
) -> None:
    """Enqueue the exact run accepted by Directus; never create a replacement run."""
    from backend.core.api.app.tasks.workflow_tasks import run_workflow_task

    if invocation is None:
        run_workflow_task.delay(workflow_id, user_id, run_id, version_id, trigger_type, input_payload)
    else:
        run_workflow_task.delay(workflow_id, user_id, run_id, version_id, trigger_type, input_payload, invocation)


def _accepted_run_response(accepted: dict[str, Any], workflow_id: str, trigger_type: str) -> dict[str, Any]:
    """Serialize only public pinned-run fields from the internal acceptance response."""
    status = accepted.get("status")
    if not isinstance(status, str) or not status:
        raise RuntimeError("Workflow runtime acceptance returned invalid status")
    return {
        "id": _accepted_run_field(accepted, "run_id"),
        "workflow_id": workflow_id,
        "version_id": _accepted_run_field(accepted, "version_id"),
        "trigger_type": trigger_type,
        "status": status,
        "started_at": None,
        "finished_at": None,
        "error_summary": None,
        "cost_summary": {},
        "content_retention_mode": "last_5",
        "content_available": False,
        "content_storage": None,
        "content_expires_at": None,
        "encrypted_content_ref": None,
        "encrypted_content_checksum": None,
        "node_runs": [],
        "output_summary": {},
    }


@router.post("/{workflow_id}/keep")
@limiter.limit("30/minute")
async def keep_workflow(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.keep_temporary_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/runs")
@limiter.limit("60/minute")
async def list_workflow_runs(
    workflow_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) else None
        if team_id:
            await _require_team_read_role(get_directus_service(request), team_id, current_user)
        runs = await run_in_threadpool(service.list_runs, workflow_id, current_user.id, current_user.vault_key_id, team_id)
        return {"runs": [item.model_dump(mode="json") for item in runs]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/runs/{run_id}")
@limiter.limit("60/minute")
async def get_workflow_run(
    workflow_id: str,
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    team_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        team_id = team_id if isinstance(team_id, str) and team_id else None
        if team_id:
            await _require_team_read_role(get_directus_service(request), team_id, current_user)
        else:
            # A deleted or revoked Personal Workflow cannot expose a retained outbox target.
            await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        run = await run_in_threadpool(service.get_run, workflow_id, run_id, current_user.id, current_user.vault_key_id, team_id)
        if team_id is None:
            from backend.core.api.app.services.workflow_completion_notification_service import owner_run_completion_projection
            directus = getattr(request.app.state, "directus_service", None)
            projection = await owner_run_completion_projection(directus, run, current_user.id) if directus else None
            if projection is not None:
                run = run.model_copy(update={"completion_notification": projection})
        return {"run": run.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/runs/{run_id}/cancel")
@limiter.limit("20/minute")
async def cancel_workflow_run(
    workflow_id: str,
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    runtime_service: WorkflowRuntimeService = Depends(get_workflow_runtime_service),
) -> dict[str, Any]:
    try:
        if _is_shifted_direct_user_arg(request):
            runtime_service = service
            service = current_user
            current_user = request
        result = await runtime_service.execute(
            "request_run_cancellation",
            {
                "workflow_id": workflow_id,
                "run_id": run_id,
                "hashed_user_id": service.repository.workflow_owner_hash(current_user.id),
            },
        )
        run_status = result.get("status")
        if run_status not in {"cancellation_requested", "cancelled"}:
            raise RuntimeError("Workflow runtime cancellation returned invalid status")
        if result.get("requeue_scheduled_trigger") is True:
            trigger_id = result.get("trigger_id")
            if not isinstance(trigger_id, str) or not trigger_id:
                raise RuntimeError("Workflow runtime cancellation did not return a scheduled trigger")
            _dispatch_cancelled_scheduled_trigger(trigger_id)
        return {"run_id": run_id, "status": run_status}
    except Exception as exc:
        _handle_workflow_error(exc)


def _dispatch_cancelled_scheduled_trigger(trigger_id: str) -> None:
    """Advance a cancelled due occurrence through the regular fenced scheduler path."""
    from backend.core.api.app.tasks.workflow_tasks import (
        _release_scheduled_execution_lock,
        run_scheduled_workflow_trigger_task,
    )

    _release_scheduled_execution_lock(trigger_id)
    run_scheduled_workflow_trigger_task.delay(trigger_id)
