# backend/core/api/app/routes/workflows.py
#
# Authenticated Workflows V1 API shared by web, CLI, npm SDK, pip SDK, and Apple.
# All mutations pass through WorkflowService so graph validation, ownership, and
# feature availability are consistent across clients.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.feature_availability_guards import ensure_workflows_enabled
from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowRunContentRetention
from backend.core.api.app.services.workflow_runner import WorkflowRunner
from backend.core.api.app.services.workflow_service import (
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
        service = WorkflowService()
        request.app.state.workflow_service = service
    return service


def _handle_workflow_error(exc: Exception) -> None:
    if isinstance(exc, WorkflowFeatureDisabledError):
        raise HTTPException(status_code=403, detail="FEATURE_DISABLED") from exc
    if isinstance(exc, WorkflowNotFoundError):
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.get("")
async def list_workflows(
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        return {"workflows": [item.model_dump(mode="json") for item in service.list_workflows(current_user.id)]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.post("")
async def create_workflow(
    body: WorkflowCreateRequest,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        workflow = service.create_workflow(
            current_user.id,
            body.title,
            body.graph,
            enabled=body.enabled,
            run_content_retention=body.run_content_retention,
        )
        return {"workflow": workflow.model_dump(mode="json", by_alias=True)}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/capabilities")
async def workflow_capabilities(service: WorkflowService = Depends(get_workflow_service)) -> dict[str, Any]:
    try:
        return {"capabilities": [item.model_dump(mode="json") for item in service.capabilities()]}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        return {"workflow": service.get_workflow(workflow_id, current_user.id).model_dump(mode="json", by_alias=True)}
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
        workflow = service.update_workflow(
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
        service.delete_workflow(workflow_id, current_user.id)
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
        workflow = service.update_workflow(workflow_id, current_user.id, enabled=True)
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
        workflow = service.update_workflow(workflow_id, current_user.id, enabled=False)
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
        workflow = service.get_workflow(workflow_id, current_user.id)
        run = await WorkflowRunner(service).run_workflow(workflow, current_user.id, trigger_type=body.mode, input_payload=body.input)
        return {"run": run.model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_error(exc)


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    current_user: User = Depends(get_current_user_or_api_key),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    try:
        return {"runs": [item.model_dump(mode="json") for item in service.list_runs(workflow_id, current_user.id)]}
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
        return {"run": service.get_run(workflow_id, run_id, current_user.id).model_dump(mode="json")}
    except Exception as exc:
        _handle_workflow_error(exc)
