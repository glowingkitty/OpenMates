# backend/core/api/app/routes/workflows.py
#
# Authenticated Workflows V1 API shared by web, CLI, npm SDK, pip SDK, and Apple.
# All mutations pass through WorkflowService so graph validation, ownership, and
# feature availability are consistent across clients.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.feature_availability_guards import ensure_workflows_enabled
from backend.core.api.app.services.workflow_input_service import DirectusWorkflowInputRepository, WorkflowInputService
from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowLifecycle, WorkflowMissingInputError, WorkflowRunContentRetention, WorkflowRunStatus
from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeProtocolError, WorkflowRuntimeService
from backend.core.api.app.services.workflow_runner import WorkflowRunner
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
    WorkflowVersionCurrentError,
)
from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter, WorkflowActionExecutionError
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


router = APIRouter(prefix="/v1/workflows", tags=["Workflows"], dependencies=[Depends(ensure_workflows_enabled)])


class WorkflowCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
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
    description: str | None = Field(default=None, max_length=2_000)
    graph: WorkflowGraph | None = None
    enabled: bool | None = None
    run_content_retention: WorkflowRunContentRetention | None = None
    version: int | None = None


class WorkflowRunRequest(BaseModel):
    mode: str = Field(default="manual", pattern="^(manual|test)$")
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepTestRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class WorkflowRunResponseRequest(BaseModel):
    step_id: str = Field(min_length=1, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowYamlRequest(BaseModel):
    """CLI YAML authoring request; the server remains the authoritative compiler."""

    source: str = Field(min_length=1, max_length=65_536)


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


class WorkflowAssistantDeleteConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool


def get_workflow_service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        service = WorkflowService(repository=DirectusWorkflowRepository())
        request.app.state.workflow_service = service
    return service


def get_workflow_input_service(request: Request) -> WorkflowInputService:
    service = getattr(request.app.state, "workflow_input_service", None)
    if service is None:
        service = WorkflowInputService(
            workflow_service=get_workflow_service(request),
            repository=DirectusWorkflowInputRepository(payload_cipher=get_workflow_service(request).payload_cipher),
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
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _handle_workflow_input_error(exc: Exception) -> None:
    if isinstance(exc, PermissionError | KeyError):
        raise HTTPException(status_code=404, detail="Workflow input session not found") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _handle_workflow_error(exc)


@router.get("")
async def list_workflows(
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflows = await run_in_threadpool(service.list_workflows, current_user.id, current_user.vault_key_id)
        return {"workflows": [item.model_dump(mode="json") for item in workflows]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("")
async def create_workflow(
    body: WorkflowCreateRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
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
        )
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/capabilities")
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
async def validate_yaml_workflow(
    body: WorkflowYamlRequest,
    current_user: User = Depends(get_current_user_or_api_key),
) -> dict[str, Any]:
    """Validate CLI YAML without persisting or executing a workflow."""
    del current_user
    return {"validation": _yaml_validation_payload(body.source)}


@router.post("/yaml")
async def create_yaml_workflow(
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
        )
        return {"workflow": workflow.model_dump(mode="json", by_alias=True), "validation": validation}
    except WorkflowYamlCompilationError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKFLOW_YAML_INVALID", **validation}) from exc
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/yaml")
async def update_yaml_workflow(
    workflow_id: str,
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
        return {"workflow": workflow.model_dump(mode="json", by_alias=True), "validation": validation}
    except HTTPException:
        raise
    except WorkflowYamlCompilationError as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKFLOW_YAML_INVALID", **validation}) from exc
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/temporary")
async def list_temporary_workflows(
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflows = await run_in_threadpool(service.list_temporary_workflows, current_user.id, current_user.vault_key_id)
        return {"workflows": [item.model_dump(mode="json") for item in workflows]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/input")
async def start_workflow_input(
    body: WorkflowInputStartRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            service.start,
            user_id=current_user.id,
            text=body.text,
            input_type=body.input_type,
            audio_ref=body.audio_ref,
            selected_workflow_id=body.selected_workflow_id,
            selected_project_id=body.selected_project_id,
            vault_key_id=current_user.vault_key_id,
        )
        return {"session": result.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.get("/input/{session_id}")
async def get_workflow_input_session(
    session_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(service.status, session_id, current_user.id, current_user.vault_key_id)
        return {"session": result.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.get("/input/{session_id}/events")
async def list_workflow_input_events(
    session_id: str,
    after_event_id: int = 0,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
) -> dict[str, Any]:
    try:
        events = await run_in_threadpool(service.events, session_id, after_event_id, current_user.id, current_user.vault_key_id)
        return {"events": [event.model_dump(mode="json") for event in events]}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.post("/input/{session_id}/follow-up")
async def follow_up_workflow_input(
    session_id: str,
    body: WorkflowInputFollowUpRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            service.follow_up,
            user_id=current_user.id,
            session_id=session_id,
            text=body.text,
            vault_key_id=current_user.vault_key_id,
        )
        return {"session": result.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.post("/input/{session_id}/stop")
async def stop_workflow_input(
    session_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            service.stop,
            user_id=current_user.id,
            session_id=session_id,
            vault_key_id=current_user.vault_key_id,
        )
        return {"session": result.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.post("/input/{session_id}/undo")
async def undo_workflow_input(
    session_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowInputService = Depends(get_workflow_input_service),
) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            service.undo,
            user_id=current_user.id,
            session_id=session_id,
            vault_key_id=current_user.vault_key_id,
        )
        return {"session": result.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_input_error(exc)


@router.put("/{workflow_id}/template-projection")
async def upsert_workflow_template_projection(
    workflow_id: str,
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
async def import_workflow_template(
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


@router.get("/assistant-proposals/{proposal_id}")
async def get_workflow_assistant_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowAssistantService = Depends(get_workflow_assistant_service),
) -> dict[str, Any]:
    return await run_in_threadpool(service.get_draft_preview, current_user.id, proposal_id)


@router.post("/assistant-proposals/{proposal_id}/save")
async def save_workflow_assistant_proposal(
    proposal_id: str,
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
async def cancel_workflow_assistant_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowAssistantService = Depends(get_workflow_assistant_service),
) -> dict[str, bool]:
    return {"cancelled": await run_in_threadpool(service.cancel_pending, current_user.id, proposal_id)}


@router.post("/assistant-proposals/{proposal_id}/confirm-delete")
async def confirm_workflow_assistant_delete(
    proposal_id: str,
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
async def get_public_workflow_template_projection(
    template_id: str,
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    """Serve a revocation-aware opaque projection without exposing key material."""
    try:
        projection = await run_in_threadpool(service.get_public_projection, template_id)
        return projection.model_dump(mode="json")
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/template-projection/revoke")
async def revoke_workflow_template_projection(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    try:
        projection = await run_in_threadpool(service.revoke_projection, workflow_id, current_user.id)
        return {"template_id": projection.template_id, "revoked_at": projection.revoked_at}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/template-projection/unrevoke")
async def unrevoke_workflow_template_projection(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowTemplateProjectionService = Depends(get_workflow_template_service),
) -> dict[str, Any]:
    try:
        projection = await run_in_threadpool(service.unrevoke_projection, workflow_id, current_user.id)
        return {"template_id": projection.template_id, "revoked_at": projection.revoked_at}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/binding-requirements/complete")
async def complete_workflow_template_binding(
    workflow_id: str,
    body: WorkflowTemplateBindingCompletionRequest,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    """Persist only binding completion proven by the matching server service."""
    try:
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
        return {"workflow_id": workflow_id, "binding_requirement": completed, "completed": True}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/versions")
async def list_workflow_versions(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        versions = await run_in_threadpool(service.list_workflow_versions, workflow_id, current_user.id, current_user.vault_key_id)
        return {
            "versions": [version.model_dump(mode="json") for version in versions],
            "current_version_id": service.get_workflow(workflow_id, current_user.id, current_user.vault_key_id).current_version_id,
            "retention": {"mode": "last_25_versions", "max_versions": 25},
        }
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/versions/{version_id}")
async def get_workflow_version(
    workflow_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        version = await run_in_threadpool(
            service.get_workflow_version_detail,
            workflow_id,
            current_user.id,
            version_id,
            current_user.vault_key_id,
        )
        return {"version": version.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/versions/{version_id}/restore")
async def restore_workflow_version(
    workflow_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(
            service.restore_workflow_version,
            workflow_id,
            current_user.id,
            version_id,
            current_user.vault_key_id,
        )
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.patch("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdateRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
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
        )
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        await run_in_threadpool(service.delete_workflow, workflow_id, current_user.id)
        return {"deleted": True}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/enable")
async def enable_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.update_workflow, workflow_id, current_user.id, enabled=True, vault_key_id=current_user.vault_key_id)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/disable")
async def disable_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.update_workflow, workflow_id, current_user.id, enabled=False, vault_key_id=current_user.vault_key_id)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    body: WorkflowRunRequest,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    runtime_service: WorkflowRuntimeService = Depends(get_workflow_runtime_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        if not workflow.enabled:
            raise HTTPException(status_code=409, detail="WORKFLOW_DISABLED")
        await run_in_threadpool(service.validate_manual_run_input, workflow, body.input)
        idempotency_key = request.headers.get("Idempotency-Key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        accepted = await runtime_service.execute(
            "accept_manual_run",
            {
                "workflow_id": workflow_id,
                "hashed_user_id": service.repository.workflow_owner_hash(current_user.id),
                "trigger_type": body.mode,
                "idempotency_key": idempotency_key,
            },
        )
        run_id = _accepted_run_field(accepted, "run_id")
        version_id = _accepted_run_field(accepted, "version_id")
        if accepted.get("status") == "queued":
            _dispatch_accepted_workflow_run(workflow_id, current_user.id, run_id, version_id, body.mode, body.input)
        return {"run": _accepted_run_response(accepted, workflow_id, body.mode)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/steps/{step_id}/test")
async def test_workflow_step(
    workflow_id: str,
    step_id: str,
    body: WorkflowStepTestRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        node = next((item for item in workflow.graph.nodes if item.id == step_id), None)
        if node is None:
            raise HTTPException(status_code=404, detail="Workflow step not found")
        side_effect = node.type.value in {"send_notification", "send_email_notification", "start_new_chat", "ask_user"}
        if side_effect and not body.confirmed:
            raise HTTPException(status_code=409, detail="WORKFLOW_STEP_TEST_CONFIRMATION_REQUIRED")
        run = await WorkflowRunner(service).run_step_test(
            workflow,
            current_user.id,
            step_id,
            input_override=body.input,
            vault_key_id=current_user.vault_key_id,
        )
        return {"run": run.model_dump(mode="json")}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/runs/{run_id}/respond")
async def respond_to_workflow_run_wait(
    workflow_id: str,
    run_id: str,
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
) -> None:
    """Enqueue the exact run accepted by Directus; never create a replacement run."""
    from backend.core.api.app.tasks.workflow_tasks import run_workflow_task

    run_workflow_task.delay(workflow_id, user_id, run_id, version_id, trigger_type, input_payload)


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
async def keep_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.keep_temporary_workflow, workflow_id, current_user.id, current_user.vault_key_id)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        runs = await run_in_threadpool(service.list_runs, workflow_id, current_user.id, current_user.vault_key_id)
        return {"runs": [item.model_dump(mode="json") for item in runs]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/runs/{run_id}")
async def get_workflow_run(
    workflow_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        run = await run_in_threadpool(service.get_run, workflow_id, run_id, current_user.id, current_user.vault_key_id)
        return {"run": run.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/runs/{run_id}/cancel")
async def cancel_workflow_run(
    workflow_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
    runtime_service: WorkflowRuntimeService = Depends(get_workflow_runtime_service),
) -> dict[str, Any]:
    try:
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
    from backend.core.api.app.tasks.workflow_tasks import run_scheduled_workflow_trigger_task

    run_scheduled_workflow_trigger_task.delay(trigger_id)
