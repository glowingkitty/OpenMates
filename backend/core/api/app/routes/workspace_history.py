# backend/core/api/app/routes/workspace_history.py
#
# Owner-scoped workspace history endpoints for tasks, plans, projects, and
# workflows. The route returns metadata and opaque encrypted refs only; clients
# with the relevant object keys perform any private content reconstruction.

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.workspace_change_history_service import WorkspaceChangeHistoryService, s3_workspace_history_archive_io
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService


router = APIRouter(prefix="/v1/workspace/history", tags=["Workspace History"])

WorkspaceObjectType = Literal["task", "plan", "project", "workflow"]


class ArchiveDueRequest(BaseModel):
    object_type: WorkspaceObjectType
    object_id: str = Field(min_length=1)


class WorkspaceRestoreRequest(BaseModel):
    entry_id: str = Field(min_length=1)
    state: Literal["before", "after"] = "after"


def get_workspace_history_service(request: Request) -> WorkspaceChangeHistoryService:
    s3_service = getattr(request.app.state, "s3_service", None)
    if s3_service is not None:
        archive_writer, archive_reader = s3_workspace_history_archive_io(s3_service)
        return WorkspaceChangeHistoryService(request.app.state.directus_service, archive_writer=archive_writer, archive_reader=archive_reader)
    return WorkspaceChangeHistoryService(request.app.state.directus_service)


def get_workflow_service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        service = WorkflowService(repository=DirectusWorkflowRepository())
        request.app.state.workflow_service = service
    return service


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


async def _current_user(request: Request, response: Response) -> User:
    return await get_current_user_or_api_key(
        request=request,
        response=response,
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
    )


@router.get("")
@limiter.limit("60/minute")
async def list_workspace_history(
    request: Request,
    response: Response,
    object_type: WorkspaceObjectType | None = None,
    object_id: str | None = None,
    limit: int = 50,
    service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    changes = await service.list_change_sets(current_user.id, object_type=object_type, object_id=object_id, limit=limit)
    return {"change_sets": changes}


@router.get("/{change_set_id}")
@limiter.limit("60/minute")
async def get_workspace_history(
    request: Request,
    response: Response,
    change_set_id: str,
    service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    change_set = await service.get_change_set(current_user.id, change_set_id)
    if not change_set:
        raise HTTPException(status_code=404, detail="Workspace change set not found")
    return change_set


@router.post("/{change_set_id}/undo")
@limiter.limit("30/minute")
async def undo_workspace_history(
    request: Request,
    response: Response,
    change_set_id: str,
    service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        async def undo_workflow_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
            workflow_id = str(entry.get("object_id") or "")
            if not workflow_id:
                raise ValueError("Workflow history entry is missing object_id")
            if entry.get("operation") == "create":
                await run_in_threadpool(workflow_service.delete_workflow, workflow_id, current_user.id)
                return {"workflow_version_before_id": entry.get("workflow_version_after_id")}
            if entry.get("operation") == "status":
                current = await run_in_threadpool(workflow_service.get_workflow, workflow_id, current_user.id, current_user.vault_key_id)
                target_enabled = _workflow_enabled_from_snapshot(service.snapshot_for_entry_state(entry, "before"))
                if target_enabled is None:
                    target_enabled = not bool(current.enabled)
                workflow = await run_in_threadpool(
                    workflow_service.update_workflow,
                    workflow_id,
                    current_user.id,
                    enabled=target_enabled,
                    vault_key_id=current_user.vault_key_id,
                )
                return {
                    "before": _workflow_status_snapshot(current),
                    "after": _workflow_status_snapshot(workflow),
                    "workflow_version_before_id": entry.get("workflow_version_after_id"),
                    "workflow_version_after_id": workflow.current_version_id,
                }
            version_id = entry.get("workflow_version_before_id")
            if not isinstance(version_id, str) or not version_id:
                raise ValueError("Workflow history entry is missing workflow_version_before_id")
            workflow = await run_in_threadpool(
                workflow_service.restore_workflow_version_from_history,
                workflow_id,
                current_user.id,
                version_id,
                current_user.vault_key_id,
            )
            return {"workflow_version_before_id": entry.get("workflow_version_after_id"), "workflow_version_after_id": workflow.current_version_id}

        return await service.undo_change_set(user_id=current_user.id, change_set_id=change_set_id, workflow_undo_handler=undo_workflow_entry)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{object_type}/{object_id}/restore")
@limiter.limit("20/minute")
async def restore_workspace_object_history(
    request: Request,
    response: Response,
    object_type: WorkspaceObjectType,
    object_id: str,
    body: WorkspaceRestoreRequest,
    service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        return await service.restore_object_to_entry(
            user_id=current_user.id,
            object_type=object_type,
            object_id=object_id,
            entry_id=body.entry_id,
            state=body.state,
            source="cli",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/archive-due")
@limiter.limit("10/minute")
async def archive_due_workspace_history(
    request: Request,
    response: Response,
    body: ArchiveDueRequest,
    service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    return await service.archive_due_entries(user_id=current_user.id, object_type=body.object_type, object_id=body.object_id)
