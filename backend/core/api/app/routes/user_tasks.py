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
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.feature_availability_guards import ensure_tasks_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.user_task_service import (
    UserTaskConflictError,
    UserTaskNotFoundError,
    UserTaskService,
)
from backend.core.api.app.services.user_task_queue_service import UserTaskQueueService
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
from backend.core.api.app.services.workflow_task_projection_service import WorkflowTaskProjectionService


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


async def _current_user(request: Request, response: Response) -> User:
    return await get_current_user_or_api_key(
        request=request,
        response=response,
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
    )


def _handle_task_error(exc: Exception) -> None:
    if isinstance(exc, UserTaskConflictError):
        raise HTTPException(status_code=409, detail="TASK_VERSION_CONFLICT") from exc
    if isinstance(exc, UserTaskNotFoundError):
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


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
    limit: int = 100,
    service: UserTaskService = Depends(get_user_task_service),
    workflow_projection_service: WorkflowTaskProjectionService = Depends(get_workflow_task_projection_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    tasks = await service.list_tasks(
        current_user.id,
        status=status,
        project_id=project_id,
        chat_id=chat_id,
        assignee_hash=assignee_hash,
        label_hashes=[*(label_hash or []), *(label_hashes or [])],
        priority=priority,
        due_before=due_before,
        limit=limit,
    )
    projections = []
    if not any((chat_id, project_id, assignee_hash, label_hash, label_hashes, priority is not None, due_before is not None)):
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
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await service.create_task(current_user.id, body.model_dump())
        return {"task": task}
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


@router.patch("/{task_id}")
@limiter.limit("30/minute")
async def update_user_task(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskUpdateRequest,
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await service.update_task(task_id, current_user.id, body.model_dump(exclude_unset=True))
        return {"task": task}
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
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await service.start_ai(task_id, current_user.id, body.model_dump(exclude_unset=True))
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
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    skipped_projection = await run_in_threadpool(workflow_projection_service.skip_scheduled_projection, current_user.id, task_id)
    if skipped_projection is not None:
        return {"deleted": True, "task_id": task_id, "workflow_run": skipped_projection}
    try:
        deleted = await service.task_methods.delete_task(task_id, current_user.id, version)
        if not deleted:
            raise HTTPException(status_code=404, detail="Task not found")
    except Exception as exc:
        _handle_task_error(exc)
    return {"deleted": True, "task_id": task_id}


@router.post("/{task_id}/complete")
@limiter.limit("30/minute")
async def complete_user_task(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskActionRequest,
    queue_service: UserTaskQueueService = Depends(get_user_task_queue_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await queue_service.complete_task(task_id, current_user.id, version=body.version)
        return {"task": task}
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
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await queue_service.block_task(
            task_id,
            current_user.id,
            version=body.version,
            blocked_reason_code=body.blocked_reason_code,
        )
        return {"task": task}
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
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await queue_service.unblock_task(task_id, current_user.id, version=body.version)
        return {"task": task}
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
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        task = await queue_service.skip_task(task_id, current_user.id, version=body.version)
        return {"task": task}
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/reorder")
@limiter.limit("30/minute")
async def reorder_user_tasks(
    request: Request,
    response: Response,
    body: UserTaskReorderRequest,
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    now = int(time.time())
    tasks: list[dict[str, Any]] = []
    for move in body.moves:
        patch = move.model_dump(exclude_unset=True, exclude={"task_id", "before_task_id", "after_task_id"})
        patch["updated_at"] = now
        if "position" not in patch:
            if move.before_task_id:
                before = await service.task_methods.get_task(move.before_task_id, current_user.id)
                patch["position"] = int(before.get("position") or 0) - 1 if before else now
            elif move.after_task_id:
                after = await service.task_methods.get_task(move.after_task_id, current_user.id)
                patch["position"] = int(after.get("position") or 0) + 1 if after else now
        try:
            task = await service.update_task(move.task_id, current_user.id, patch)
            tasks.append(task)
        except Exception as exc:
            _handle_task_error(exc)
    return {"tasks": tasks}


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
