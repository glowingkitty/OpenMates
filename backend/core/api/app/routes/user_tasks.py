# backend/core/api/app/routes/user_tasks.py
#
# Authenticated Tasks V1 product API. This namespace is intentionally separate
# from /v1/tasks, which remains Celery/background skill task polling.
#
# Spec: docs/specs/tasks-v1/spec.yml

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.feature_availability_guards import ensure_tasks_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.user_task_service import (
    UserTaskConflictError,
    UserTaskNotFoundError,
    UserTaskService,
)


router = APIRouter(prefix="/v1/user-tasks", tags=["User Tasks"], dependencies=[Depends(ensure_tasks_enabled)])

TaskStatus = Literal["backlog", "todo", "in_progress", "blocked", "done"]
AssigneeType = Literal["ai", "user"]


class UserTaskCreateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    encrypted_task_key: str | None = None
    encrypted_title: str = Field(min_length=1)
    encrypted_description: str | None = None
    encrypted_tags: str | None = None
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
    priority: int = 0
    position: int = 0
    created_at: int
    updated_at: int


class UserTaskUpdateRequest(BaseModel):
    encrypted_title: str | None = None
    encrypted_task_key: str | None = None
    encrypted_description: str | None = None
    encrypted_tags: str | None = None
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
    priority: int | None = None
    position: int | None = None
    blocked_reason_code: str | None = None
    ai_execution_state: str | None = None
    updated_at: int | None = None
    version: int | None = None


class UserTaskStartAIRequest(BaseModel):
    primary_chat_id: str | None = None
    linked_project_ids: list[str] | None = None
    encrypted_latest_instruction: str | None = None
    plaintext_title: str | None = None
    plaintext_description: str | None = None
    plaintext_latest_instruction: str | None = None
    plaintext_chat_title: str | None = None
    updated_at: int | None = None
    version: int | None = None


def get_user_task_service(request: Request) -> UserTaskService:
    return UserTaskService(request.app.state.directus_service.user_task, cache_service=request.app.state.cache_service)


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
    due_before: int | None = None,
    limit: int = 100,
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    tasks = await service.list_tasks(
        current_user.id,
        status=status,
        project_id=project_id,
        chat_id=chat_id,
        assignee_hash=assignee_hash,
        due_before=due_before,
        limit=limit,
    )
    return {"tasks": tasks}


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
