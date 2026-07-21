# backend/core/api/app/routes/user_tasks.py
#
# Authenticated Tasks V1 product API. This namespace is intentionally separate
# from /v1/tasks, which remains Celery/background skill task polling.
#
# Spec: docs/specs/tasks-v1/spec.yml

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.apps.ai.processing.task_proposals import extract_review_task_proposals
from backend.apps.ai.processing.workspace_ask_planner import WorkspaceAskPlanningError, plan_task_ask
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.feature_availability_guards import ensure_tasks_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.team_workspace_service import move_workspace_record_to_team
from backend.core.api.app.services.user_task_service import (
    UserTaskConflictError,
    UserTaskNotFoundError,
    UserTaskService,
)
from backend.core.api.app.services.user_task_queue_service import UserTaskQueueService
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
from backend.core.api.app.services.workflow_task_projection_service import WorkflowTaskProjectionService
from backend.core.api.app.services.workspace_change_history_service import WorkspaceChangeHistoryService, build_history_commands, s3_workspace_history_archive_io


router = APIRouter(prefix="/v1/user-tasks", tags=["User Tasks"], dependencies=[Depends(ensure_tasks_enabled)])

TaskStatus = Literal["backlog", "todo", "in_progress", "blocked", "done"]
AssigneeType = Literal["ai", "user"]
KeyWrapperType = Literal["master", "chat", "project"]


class UserTaskKeyWrapperRequest(BaseModel):
    key_type: KeyWrapperType
    encrypted_task_key: str = Field(min_length=1)
    hashed_chat_id: str | None = None
    hashed_project_id: str | None = None
    created_at: int
    expires_at: int | None = None


class UserTaskCreateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    encrypted_task_key: str | None = None
    encrypted_title: str = Field(min_length=1)
    encrypted_description: str | None = None
    encrypted_labels: str | None = None
    encrypted_tags: str | None = None
    label_hashes: list[str] = Field(default_factory=list)
    encrypted_linked_project_ids: str | None = None
    encrypted_activity_summary: str | None = None
    encrypted_latest_instruction: str | None = None
    status: TaskStatus = "todo"
    assignee_type: AssigneeType = "user"
    assignee_hash: str | None = None
    primary_chat_id: str | None = None
    linked_project_ids: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    plan_id: str | None = None
    plan_step_id: str | None = None
    task_type: Literal["work", "verification"] = "work"
    verification_id: str | None = None
    due_at: int | None = None
    priority: int = Field(default=0, ge=0, le=4)
    position: int = 0
    version: int
    created_at: int
    updated_at: int
    key_wrappers: list[UserTaskKeyWrapperRequest] = Field(default_factory=list)


class UserTaskUpdateRequest(BaseModel):
    encrypted_title: str | None = None
    encrypted_task_key: str | None = None
    encrypted_description: str | None = None
    encrypted_labels: str | None = None
    encrypted_tags: str | None = None
    label_hashes: list[str] | None = None
    encrypted_linked_project_ids: str | None = None
    encrypted_activity_summary: str | None = None
    encrypted_latest_instruction: str | None = None
    status: TaskStatus | None = None
    assignee_type: AssigneeType | None = None
    assignee_hash: str | None = None
    primary_chat_id: str | None = None
    linked_project_ids: list[str] | None = None
    parent_task_id: str | None = None
    plan_id: str | None = None
    plan_step_id: str | None = None
    task_type: Literal["work", "verification"] | None = None
    verification_id: str | None = None
    due_at: int | None = None
    priority: int | None = Field(default=None, ge=0, le=4)
    position: int | None = None
    blocked_reason_code: str | None = None
    ai_execution_state: str | None = None
    updated_at: int | None = None
    version: int
    key_wrappers: list[UserTaskKeyWrapperRequest] | None = None


class UserTaskMoveRequest(BaseModel):
    team_id: str
    confirmed: bool
    moved_at: int | None = None


class UserTaskStartAIRequest(BaseModel):
    primary_chat_id: str | None = None
    linked_project_ids: list[str] | None = None
    encrypted_latest_instruction: str | None = None
    plaintext_title: str | None = None
    plaintext_description: str | None = None
    plaintext_latest_instruction: str | None = None
    plaintext_chat_title: str | None = None
    plaintext_project_context: str | None = None
    updated_at: int | None = None
    version: int


class UserTaskActionRequest(BaseModel):
    version: int
    blocked_reason_code: str | None = None


class UserTaskReorderMoveRequest(BaseModel):
    task_id: str = Field(min_length=1)
    before_task_id: str | None = None
    after_task_id: str | None = None
    status: TaskStatus | None = None
    position: int | None = None
    version: int


class UserTaskReorderRequest(BaseModel):
    moves: list[UserTaskReorderMoveRequest] = Field(min_length=1)


class UserTaskExtractRequest(BaseModel):
    corrected_text: str = Field(min_length=1, max_length=8000)
    mode: Literal["create", "update"] = "create"
    context_chat_id: str | None = None
    project_ids: list[str] = Field(default_factory=list)


class UserTaskKeyWrappersRequest(BaseModel):
    version: int
    key_wrappers: list[UserTaskKeyWrapperRequest] = Field(min_length=1)


class UserTaskRestoreRequest(BaseModel):
    entry_id: str = Field(min_length=1)
    state: Literal["before", "after"] = "after"


class UserTaskAskRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    apply_mode: Literal["auto_apply", "confirm_first"] = "auto_apply"
    encrypted_create: UserTaskCreateRequest | None = None
    encrypted_creates: list[UserTaskCreateRequest] | None = None


class UserTaskAskPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    context_chat_id: str | None = None
    project_ids: list[str] = Field(default_factory=list)


def get_user_task_service(request: Request) -> UserTaskService:
    return UserTaskService(request.app.state.directus_service.user_task, cache_service=request.app.state.cache_service)


def get_user_task_queue_service(request: Request) -> UserTaskQueueService:
    return UserTaskQueueService(request.app.state.directus_service.user_task)


def get_workflow_task_projection_service(request: Request) -> WorkflowTaskProjectionService:
    workflow_service = getattr(request.app.state, "workflow_service", None)
    if workflow_service is None:
        workflow_service = WorkflowService(repository=DirectusWorkflowRepository())
        request.app.state.workflow_service = workflow_service
    return WorkflowTaskProjectionService(workflow_service.repository)


def get_workspace_history_service(request: Request) -> WorkspaceChangeHistoryService:
    s3_service = getattr(request.app.state, "s3_service", None)
    if s3_service is not None:
        archive_writer, archive_reader = s3_workspace_history_archive_io(s3_service)
        return WorkspaceChangeHistoryService(request.app.state.directus_service, archive_writer=archive_writer, archive_reader=archive_reader)
    return WorkspaceChangeHistoryService(request.app.state.directus_service)


async def _current_user(request: Request, response: Response) -> User:
    return await get_current_user_or_api_key(
        request=request,
        response=response,
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
    )


def _handle_task_error(exc: Exception) -> None:
    if isinstance(exc, TeamPermissionError):
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
    if isinstance(exc, UserTaskConflictError):
        raise HTTPException(status_code=409, detail="TASK_VERSION_CONFLICT") from exc
    if isinstance(exc, UserTaskNotFoundError):
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


async def _record_task_history(
    history_service: WorkspaceChangeHistoryService,
    user_id: str,
    *,
    source: str,
    action_type: str,
    entries: list[dict[str, Any]],
    redacted_summary: str,
) -> dict[str, Any]:
    history = await history_service.record_change_set(
        user_id=user_id,
        source=source,
        namespace="tasks",
        action_type=action_type,
        entries=entries,
        redacted_summary=redacted_summary,
    )
    return {**history, **build_history_commands(history["change_set"]["change_set_id"], history["entries"])}


def _unwrap_query_default(value: Any) -> Any:
    if value.__class__.__module__ == "fastapi.params":
        return value.default
    return value


def _query_list_values(value: Any) -> list[str]:
    value = _unwrap_query_default(value)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [str(value)]


@router.get("")
@limiter.limit("60/minute")
async def list_user_tasks(
    request: Request,
    response: Response,
    status: TaskStatus | None = None,
    project_id: str | None = None,
    chat_id: str | None = None,
    assignee_hash: str | None = None,
    label_hash: list[str] | None = Query(default=None),
    label_hashes: list[str] | None = Query(default=None),
    priority: int | None = Query(default=None, ge=0, le=4),
    due_before: int | None = None,
    team_id: str | None = None,
    limit: int = 100,
    service: UserTaskService = Depends(get_user_task_service),
    workflow_projection_service: WorkflowTaskProjectionService = Depends(get_workflow_task_projection_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    label_hash_values = [*_query_list_values(label_hash), *_query_list_values(label_hashes)]
    priority_value = _unwrap_query_default(priority)
    try:
        if team_id:
            await request.app.state.directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})
    except Exception as exc:
        _handle_task_error(exc)
    tasks = await service.list_tasks(
        current_user.id,
        status=status,
        project_id=project_id,
        chat_id=chat_id,
        assignee_hash=assignee_hash,
        label_hashes=label_hash_values,
        priority=priority_value,
        due_before=due_before,
        team_id=team_id,
        limit=limit,
    )
    projections = []
    if not any((chat_id, project_id, assignee_hash, label_hash_values, priority_value is not None, due_before is not None)):
        projections = await run_in_threadpool(workflow_projection_service.list_projections, current_user.id)
        if status is not None:
            projections = [projection for projection in projections if projection.status == status]
    return {"tasks": tasks + [projection.model_dump(mode="json") for projection in projections]}


@router.post("")
@limiter.limit("30/minute")
async def create_user_task(
    request: Request,
    response: Response,
    body: UserTaskCreateRequest,
    service: UserTaskService = Depends(get_user_task_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await service.create_task(current_user.id, body.model_dump())
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="create",
            entries=[{"object_type": "task", "object_id": task["task_id"], "operation": "create", "after": task}],
            redacted_summary="Created 1 task",
        )
        return {"task": task, "history": history}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/extract")
@limiter.limit("20/minute")
async def extract_user_task_proposals(
    request: Request,
    response: Response,
    body: UserTaskExtractRequest,
) -> dict[str, Any]:
    await _current_user(request, response)
    proposals = extract_review_task_proposals(body.corrected_text)
    return {"proposed_tasks": [proposal.model_dump() for proposal in proposals]}


@router.post("/ask/plan")
@limiter.limit("20/minute")
async def plan_user_task_ask(
    request: Request,
    response: Response,
    body: UserTaskAskPlanRequest,
) -> dict[str, Any]:
    await _current_user(request, response)
    secrets_manager = getattr(request.app.state, "secrets_manager", None)
    if secrets_manager is None:
        raise HTTPException(status_code=503, detail="Workspace ask inference is not configured")
    try:
        proposals = await plan_task_ask(body.instruction, secrets_manager)
        return {"proposed_tasks": [proposal.model_dump() for proposal in proposals], "inference_used": True}
    except WorkspaceAskPlanningError as exc:
        raise HTTPException(status_code=502, detail=f"Workspace ask inference failed: {exc}") from exc


@router.post("/ask")
@limiter.limit("20/minute")
async def ask_user_tasks(
    request: Request,
    response: Response,
    body: UserTaskAskRequest,
    service: UserTaskService = Depends(get_user_task_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    if body.apply_mode == "confirm_first":
        return {
            "applied": False,
            "change_set_id": None,
            "summary": "Preview requires a client-encrypted task payload before apply.",
            "changed_entries": [],
            "undo_all_command": None,
            "undo_entry_commands": [],
            "warnings": [],
            "clarification_required": False,
        }
    encrypted_creates = body.encrypted_creates or ([body.encrypted_create] if body.encrypted_create is not None else [])
    if not encrypted_creates:
        raise HTTPException(status_code=400, detail="encrypted_create or encrypted_creates is required for task ask auto-apply")
    try:
        tasks = []
        for encrypted_create in encrypted_creates:
            tasks.append(await service.create_task(current_user.id, encrypted_create.model_dump()))
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="ai_ask",
            action_type="ask_create",
            entries=[{"object_type": "task", "object_id": task["task_id"], "operation": "create", "after": task} for task in tasks],
            redacted_summary=f"Created {len(tasks)} task(s) from ask",
        )
        return {
            "applied": True,
            "change_set_id": history["change_set"]["change_set_id"],
            "summary": f"Created {len(tasks)} task(s).",
            "changed_entries": history["entries"],
            "undo_all_command": history["undo_all_command"],
            "undo_entry_commands": history["undo_entry_commands"],
            "warnings": [],
            "clarification_required": False,
            "task": tasks[0] if len(tasks) == 1 else None,
            "tasks": tasks,
            "history": history,
        }
    except Exception as exc:
        _handle_task_error(exc)


@router.get("/{task_id}/history")
@limiter.limit("60/minute")
async def list_user_task_history(
    request: Request,
    response: Response,
    task_id: str,
    limit: int = 50,
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    entries = await history_service.list_object_history(current_user.id, object_type="task", object_id=task_id, limit=limit)
    return {"entries": entries}


@router.post("/{task_id}/restore")
@limiter.limit("20/minute")
async def restore_user_task_from_history(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskRestoreRequest,
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        result = await history_service.restore_object_to_entry(
            user_id=current_user.id,
            object_type="task",
            object_id=task_id,
            entry_id=body.entry_id,
            state=body.state,
            source="cli",
        )
        return {"task": result.get("object"), "history": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{task_id}")
@limiter.limit("30/minute")
async def update_user_task(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskUpdateRequest,
    service: UserTaskService = Depends(get_user_task_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        before = await service.task_methods.get_task(task_id, current_user.id)
        task = await service.update_task(task_id, current_user.id, body.model_dump(exclude_unset=True))
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="update",
            entries=[{"object_type": "task", "object_id": task_id, "operation": "update", "before": before, "after": task}],
            redacted_summary="Updated 1 task",
        )
        return {"task": task, "history": history}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/{task_id}/start-ai")
@limiter.limit("20/minute")
async def start_user_task_ai(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskStartAIRequest,
    service: UserTaskService = Depends(get_user_task_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        before = await service.task_methods.get_task(task_id, current_user.id)
        task = await service.start_ai(task_id, current_user.id, body.model_dump(exclude_unset=True))
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="start_ai",
            entries=[{"object_type": "task", "object_id": task_id, "operation": "status", "before": before, "after": task}],
            redacted_summary="Started 1 task with AI",
        )
        return {"task": task, "history": history}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/{task_id}/move")
@limiter.limit("20/minute")
async def move_user_task_to_team(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskMoveRequest,
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await move_workspace_record_to_team(
            directus_service=request.app.state.directus_service,
            actor_user_id=current_user.id,
            team_id=body.team_id,
            workspace_type="task",
            object_id=task_id,
            confirmed=body.confirmed,
            moved_at=body.moved_at,
        )
        return {"task": task}
    except Exception as exc:
        _handle_task_error(exc)


@router.delete("/{task_id}")
@limiter.limit("30/minute")
async def delete_user_task(
    request: Request,
    response: Response,
    task_id: str,
    version: int = Query(...),
    service: UserTaskService = Depends(get_user_task_service),
    workflow_projection_service: WorkflowTaskProjectionService = Depends(get_workflow_task_projection_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    skipped_projection = await run_in_threadpool(workflow_projection_service.skip_scheduled_projection, current_user.id, task_id)
    if skipped_projection is not None:
        return {"deleted": True, "task_id": task_id, "workflow_run": skipped_projection}
    try:
        before = await service.task_methods.get_task(task_id, current_user.id)
        deleted = await service.task_methods.delete_task(task_id, current_user.id, version)
        if not deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="delete",
            entries=[{"object_type": "task", "object_id": task_id, "operation": "delete", "before": before}],
            redacted_summary="Deleted 1 task",
        )
    except Exception as exc:
        _handle_task_error(exc)
    return {"deleted": True, "task_id": task_id, "history": history}


@router.post("/{task_id}/complete")
@limiter.limit("30/minute")
async def complete_user_task(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskActionRequest,
    queue_service: UserTaskQueueService = Depends(get_user_task_queue_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        before = await queue_service.task_methods.get_task(task_id, current_user.id)
        task = await queue_service.complete_task(task_id, current_user.id, version=body.version)
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="complete",
            entries=[{"object_type": "task", "object_id": task_id, "operation": "status", "before": before, "after": task}],
            redacted_summary="Completed 1 task",
        )
        return {"task": task, "history": history}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/{task_id}/block")
@limiter.limit("30/minute")
async def block_user_task(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskActionRequest,
    queue_service: UserTaskQueueService = Depends(get_user_task_queue_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        before = await queue_service.task_methods.get_task(task_id, current_user.id)
        task = await queue_service.block_task(
            task_id,
            current_user.id,
            version=body.version,
            blocked_reason_code=body.blocked_reason_code,
        )
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="block",
            entries=[{"object_type": "task", "object_id": task_id, "operation": "status", "before": before, "after": task}],
            redacted_summary="Blocked 1 task",
        )
        return {"task": task, "history": history}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/{task_id}/unblock")
@limiter.limit("30/minute")
async def unblock_user_task(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskActionRequest,
    queue_service: UserTaskQueueService = Depends(get_user_task_queue_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        before = await queue_service.task_methods.get_task(task_id, current_user.id)
        task = await queue_service.unblock_task(task_id, current_user.id, version=body.version)
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="unblock",
            entries=[{"object_type": "task", "object_id": task_id, "operation": "status", "before": before, "after": task}],
            redacted_summary="Unblocked 1 task",
        )
        return {"task": task, "history": history}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/{task_id}/skip")
@limiter.limit("30/minute")
async def skip_user_task(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskActionRequest,
    queue_service: UserTaskQueueService = Depends(get_user_task_queue_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        before = await queue_service.task_methods.get_task(task_id, current_user.id)
        task = await queue_service.skip_task(task_id, current_user.id, version=body.version)
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="cli",
            action_type="skip",
            entries=[{"object_type": "task", "object_id": task_id, "operation": "status", "before": before, "after": task}],
            redacted_summary="Skipped 1 task",
        )
        return {"task": task, "history": history}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/reorder")
@limiter.limit("30/minute")
async def reorder_user_tasks(
    request: Request,
    response: Response,
    body: UserTaskReorderRequest,
    service: UserTaskService = Depends(get_user_task_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    now = int(time.time())
    tasks: list[dict[str, Any]] = []
    history_entries: list[dict[str, Any]] = []
    for move in body.moves:
        moved_before = await service.task_methods.get_task(move.task_id, current_user.id)
        patch = move.model_dump(exclude_unset=True, exclude={"task_id", "before_task_id", "after_task_id"})
        patch["updated_at"] = now
        if "position" not in patch:
            if move.before_task_id:
                anchor_before = await service.task_methods.get_task(move.before_task_id, current_user.id)
                patch["position"] = int(anchor_before.get("position") or 0) - 1 if anchor_before else now
            elif move.after_task_id:
                after = await service.task_methods.get_task(move.after_task_id, current_user.id)
                patch["position"] = int(after.get("position") or 0) + 1 if after else now
        try:
            task = await service.update_task(move.task_id, current_user.id, patch)
            tasks.append(task)
            history_entries.append({"object_type": "task", "object_id": move.task_id, "operation": "reorder", "before": moved_before, "after": task})
        except Exception as exc:
            _handle_task_error(exc)
    history = await _record_task_history(
        history_service,
        current_user.id,
        source="cli",
        action_type="reorder",
        entries=history_entries,
        redacted_summary=f"Reordered {len(history_entries)} task(s)",
    )
    return {"tasks": tasks, "history": history}


@router.post("/{task_id}/key-wrappers")
@limiter.limit("20/minute")
async def add_user_task_key_wrappers(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskKeyWrappersRequest,
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    existing = await service.task_methods.get_task(task_id, current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    created = await service.task_methods.replace_task_key_wrappers(
        current_user.id,
        task_id,
        [wrapper.model_dump() for wrapper in body.key_wrappers],
        body.version,
    )
    if created is None:
        raise HTTPException(status_code=400, detail="Invalid task key wrappers")
    return {"key_wrappers": created}


@router.get("/{task_id}/key-wrappers")
@limiter.limit("60/minute")
async def list_user_task_key_wrappers(
    request: Request,
    response: Response,
    task_id: str,
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    existing = await service.task_methods.get_task(task_id, current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"key_wrappers": await service.task_methods.list_task_key_wrappers(current_user.id, task_id)}
