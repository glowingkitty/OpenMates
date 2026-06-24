# backend/core/api/app/routes/workflows.py
#
# Authenticated Workflows V1 API shared by web, CLI, npm SDK, pip SDK, and Apple.
# All mutations pass through WorkflowService so graph validation, ownership, and
# feature availability are consistent across clients.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.feature_availability_guards import ensure_workflows_enabled
from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowLifecycle, WorkflowMissingInputError, WorkflowRunContentRetention
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_service import (
    DirectusWorkflowRepository,
    WorkflowFeatureDisabledError,
    WorkflowNotFoundError,
    WorkflowService,
)


router = APIRouter(prefix="/v1/workflows", tags=["Workflows"], dependencies=[Depends(ensure_workflows_enabled)])


class WorkflowCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
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
    graph: WorkflowGraph | None = None
    enabled: bool | None = None
    run_content_retention: WorkflowRunContentRetention | None = None


class WorkflowRunRequest(BaseModel):
    mode: str = Field(default="manual", pattern="^(manual|test)$")
    input: dict[str, Any] = Field(default_factory=dict)


def get_workflow_service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        service = WorkflowService(repository=DirectusWorkflowRepository())
        request.app.state.workflow_service = service
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
    if isinstance(exc, WorkflowFeatureDisabledError):
        raise HTTPException(status_code=403, detail="FEATURE_DISABLED") from exc
    if isinstance(exc, WorkflowNotFoundError):
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    if isinstance(exc, WorkflowMissingInputError):
        raise HTTPException(status_code=400, detail="MISSING_WORKFLOW_INPUT") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.get("")
async def list_workflows(
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflows = await run_in_threadpool(service.list_workflows, current_user.id)
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
        capabilities = await run_in_threadpool(service.capabilities, user_id)
        return {"capabilities": [item.model_dump(mode="json") for item in capabilities]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/temporary")
async def list_temporary_workflows(
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflows = await run_in_threadpool(service.list_temporary_workflows, current_user.id)
        return {"workflows": [item.model_dump(mode="json") for item in workflows]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id)
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
        workflow = await run_in_threadpool(service.update_workflow, workflow_id, current_user.id, enabled=True)
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
        workflow = await run_in_threadpool(service.update_workflow, workflow_id, current_user.id, enabled=False)
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    body: WorkflowRunRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.get_workflow, workflow_id, current_user.id)
        run = await WorkflowRunner(service).run_workflow(workflow, current_user.id, trigger_type=body.mode, input_payload=body.input)
        return {"run": run.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("/{workflow_id}/keep")
async def keep_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = await run_in_threadpool(service.keep_temporary_workflow, workflow_id, current_user.id)
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
        runs = await run_in_threadpool(service.list_runs, workflow_id, current_user.id)
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
        run = await run_in_threadpool(service.get_run, workflow_id, run_id, current_user.id)
        return {"run": run.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_error(exc)
