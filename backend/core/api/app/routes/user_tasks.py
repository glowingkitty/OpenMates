# backend/core/api/app/routes/user_tasks.py
#
# Authenticated Tasks V1 product API. This namespace is intentionally separate
# from /v1/tasks, which remains Celery/background skill task polling.
#
# Spec: docs/specs/tasks-v1/spec.yml
# test-file: backend/tests/test_user_task_activity_api.py

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from backend.apps.ai.processing.task_proposals import extract_review_task_proposals
from backend.apps.ai.processing.workspace_ask_planner import WorkspaceAskPlanningError, run_task_ask_pipeline
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user, get_current_user_or_api_key
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
from backend.core.api.app.services.user_work_control_service import (
    DirectusWorkControlRepository,
    UserWorkControlService,
    WorkControlPermissionError,
)
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
from backend.core.api.app.services.workflow_task_projection_service import WorkflowTaskProjectionService
from backend.core.api.app.services.workspace_change_history_service import WorkspaceChangeHistoryService, build_history_commands, s3_workspace_history_archive_io
from backend.shared.python_utils.encrypted_slug_metadata import DuplicateObjectSlugError


router = APIRouter(prefix="/v1/user-tasks", tags=["User Tasks"], dependencies=[Depends(ensure_tasks_enabled)])

TaskStatus = Literal["backlog", "todo", "in_progress", "blocked", "done"]
AssigneeType = Literal["user", "openmates", "external_ai", "unassigned"]
AssigneeIdentity = Literal["openmates", "opencode"]
KeyWrapperType = Literal["master", "chat", "project", "plan"]
ExternalChatProvider = Literal["opencode"]
BlockedReasonCode = Literal[
    "needs_user_input",
    "waiting_for_approval",
    "missing_credentials",
    "ambiguous_requirement",
    "external_dependency",
    "environment_unavailable",
    "verification_failed",
    "other",
]


class UserTaskKeyWrapperRequest(BaseModel):
    key_type: KeyWrapperType
    encrypted_task_key: str = Field(min_length=1)
    hashed_chat_id: str | None = None
    hashed_project_id: str | None = None
    hashed_plan_id: str | None = None
    created_at: int
    expires_at: int | None = None


class UserTaskCreateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    encrypted_task_key: str | None = None
    encrypted_title: str = Field(min_length=1)
    encrypted_slug: str | None = Field(default=None, min_length=1)
    slug_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    encrypted_description: str | None = None
    encrypted_labels: str | None = None
    encrypted_tags: str | None = None
    label_hashes: list[str] = Field(default_factory=list)
    encrypted_linked_project_ids: str | None = None
    encrypted_activity_summary: str | None = None
    encrypted_latest_instruction: str | None = None
    status: TaskStatus = "todo"
    assignee_type: AssigneeType = "user"
    assignee_identity: AssigneeIdentity | None = None
    assignee_hash: str | None = None
    primary_chat_id: str | None = None
    external_chat_provider: ExternalChatProvider | None = None
    external_chat_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    encrypted_external_chat_id: str | None = None
    encrypted_external_chat_title: str | None = None
    linked_project_ids: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    plan_id: str | None = None
    task_type: Literal["work", "verification"] = "work"
    verification_id: str | None = None
    due_at: int | None = None
    priority: int = Field(default=0, ge=0, le=4)
    position: int = 0
    blocked_reason_code: BlockedReasonCode | None = None
    encrypted_blocked_reason: str | None = None
    version: int
    created_at: int
    updated_at: int
    plaintext_title: str | None = None
    plaintext_description: str | None = None
    plaintext_latest_instruction: str | None = None
    plaintext_chat_title: str | None = None
    plaintext_project_context: str | None = None
    key_wrappers: list[UserTaskKeyWrapperRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_assignment(self) -> "UserTaskCreateRequest":
        _validate_assignment_fields(self.assignee_type, self.assignee_identity, self.assignee_hash)
        return self


class UserTaskUpdateRequest(BaseModel):
    encrypted_title: str | None = None
    encrypted_slug: str | None = Field(default=None, min_length=1)
    slug_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
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
    assignee_identity: AssigneeIdentity | None = None
    assignee_hash: str | None = None
    primary_chat_id: str | None = None
    external_chat_provider: ExternalChatProvider | None = None
    external_chat_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    encrypted_external_chat_id: str | None = None
    encrypted_external_chat_title: str | None = None
    linked_project_ids: list[str] | None = None
    parent_task_id: str | None = None
    plan_id: str | None = None
    task_type: Literal["work", "verification"] | None = None
    verification_id: str | None = None
    due_at: int | None = None
    priority: int | None = Field(default=None, ge=0, le=4)
    position: int | None = None
    blocked_reason_code: BlockedReasonCode | None = None
    encrypted_blocked_reason: str | None = None
    ai_execution_state: str | None = None
    updated_at: int | None = None
    version: int
    key_wrappers: list[UserTaskKeyWrapperRequest] | None = None

    @model_validator(mode="after")
    def validate_assignment(self) -> "UserTaskUpdateRequest":
        if self.assignee_type is not None:
            _validate_assignment_fields(self.assignee_type, self.assignee_identity, self.assignee_hash)
        elif self.assignee_identity is not None:
            raise ValueError("Task assignee identity requires assignee type")
        return self


class UserTaskMoveRequest(BaseModel):
    team_id: str
    confirmed: bool
    encrypted_slug: str | None = Field(default=None, min_length=1)
    slug_lookup_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    moved_at: int | None = None


class UserTaskStartAIRequest(BaseModel):
    team_id: str | None = None
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
    blocked_reason_code: BlockedReasonCode | None = None
    encrypted_blocked_reason: str | None = None
    team_id: str | None = None


class UserTaskReorderMoveRequest(BaseModel):
    task_id: str = Field(min_length=1)
    before_task_id: str | None = None
    after_task_id: str | None = None
    status: TaskStatus | None = None
    position: int | None = None
    version: int


class UserTaskReorderRequest(BaseModel):
    moves: list[UserTaskReorderMoveRequest] = Field(min_length=1)
    team_id: str | None = None


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


class UserTaskActivityCreateRequest(BaseModel):
    """Ciphertext-only Activity input for first-party clients."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(min_length=1)
    encrypted_message: str = Field(min_length=1)
    encrypted_embed_key_material: str | None = None
    embed_refs: list[str] = Field(default_factory=list)
    created_at: int


def _validate_assignment_fields(
    assignee_type: AssigneeType,
    assignee_identity: AssigneeIdentity | None,
    assignee_hash: str | None,
) -> None:
    expected_identity = {"openmates": "openmates", "external_ai": "opencode"}.get(assignee_type)
    if expected_identity is not None and assignee_identity != expected_identity:
        raise ValueError(f"Task {assignee_type} assignment requires identity {expected_identity}")
    if assignee_type in {"user", "unassigned"} and assignee_identity is not None:
        raise ValueError(f"Task {assignee_type} assignment cannot have an AI identity")
    if assignee_type != "user" and assignee_hash is not None:
        raise ValueError(f"Task {assignee_type} assignment cannot have a user hash")


class WorkDependencyRequest(BaseModel):
    target_ref: str = Field(pattern=r"^(plan|task):[^:]+$")


class UserTaskAskUpdateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    patch: UserTaskUpdateRequest


class UserTaskAskDeleteRequest(BaseModel):
    task_id: str = Field(min_length=1)
    version: int


class UserTaskAskRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    encrypted_create: UserTaskCreateRequest | None = None
    encrypted_creates: list[UserTaskCreateRequest] | None = None
    encrypted_update: UserTaskAskUpdateRequest | None = None
    encrypted_updates: list[UserTaskAskUpdateRequest] | None = None
    exact_delete: UserTaskAskDeleteRequest | None = None
    exact_deletes: list[UserTaskAskDeleteRequest] | None = None


class UserTaskAskPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    context_chat_id: str | None = None
    project_ids: list[str] = Field(default_factory=list)


def get_user_task_service(request: Request) -> UserTaskService:
    return UserTaskService(
        request.app.state.directus_service.user_task,
        cache_service=request.app.state.cache_service,
        encryption_service=request.app.state.encryption_service,
    )


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


async def _current_session_user(request: Request, response: Response) -> User:
    """Dependency mutations are first-party session-only encrypted operations."""
    return await get_current_user(
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
        response=response,
        request=request,
    )


def _work_control_service(request: Request, user_id: str) -> UserWorkControlService:
    return UserWorkControlService(
        DirectusWorkControlRepository(
            user_id=user_id,
            plan_methods=request.app.state.directus_service.user_plan,
            task_methods=request.app.state.directus_service.user_task,
            directus_service=request.app.state.directus_service,
            cache_service=request.app.state.cache_service,
        )
    )


async def _ensure_linked_plan_execution(request: Request, user_id: str, task: dict[str, Any]) -> None:
    plan_id = task.get("plan_id")
    if not plan_id:
        return
    blockers = await _work_control_service(request, user_id).plan_execution_blockers(str(plan_id))
    if blockers:
        raise ValueError(f"Plan task execution is blocked: {blockers}")


async def _require_task_team_role(request: Request, user_id: str, team_id: str | None) -> None:
    if team_id:
        await request.app.state.directus_service.team.require_team_role(team_id, user_id, {"owner", "admin", "member"})


def _handle_task_error(exc: Exception) -> None:
    if isinstance(exc, TeamPermissionError):
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
    if isinstance(exc, UserTaskConflictError):
        raise HTTPException(status_code=409, detail="TASK_VERSION_CONFLICT") from exc
    if isinstance(exc, DuplicateObjectSlugError):
        raise HTTPException(status_code=409, detail="TASK_SLUG_CONFLICT") from exc
    if isinstance(exc, UserTaskNotFoundError):
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if isinstance(exc, WorkControlPermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail="TASK_ACTIVITY_PERMISSION_DENIED") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


def _request_header(request: Request, name: str) -> str:
    headers = request.headers
    value = headers.get(name)
    if value is not None:
        return str(value).strip().lower()
    lowered = name.lower()
    for key, candidate in headers.items():
        if str(key).lower() == lowered:
            return str(candidate).strip().lower()
    return ""


def derive_task_activity_source_surface(request: Request) -> str:
    """Derive durable attribution from authenticated first-party client headers."""

    sdk_surface = _request_header(request, "X-OpenMates-SDK")
    client_surface = _request_header(request, "X-OpenMates-Client")
    raw_surface = sdk_surface or client_surface
    if not raw_surface:
        if _request_header(request, "Authorization").startswith("bearer "):
            raise HTTPException(status_code=403, detail="TASK_ACTIVITY_FIRST_PARTY_CLIENT_REQUIRED")
        return "web"
    mapped = {"web": "web", "apple": "apple", "cli": "cli", "npm": "sdk_npm", "pip": "sdk_pip"}.get(raw_surface)
    if mapped is None:
        raise HTTPException(status_code=400, detail="TASK_ACTIVITY_CLIENT_INVALID")
    return mapped


def derive_task_activity_actor_mode(request: Request, source_surface: str) -> str:
    """Allow the trusted CLI bridge to act as the Task's named assignee."""

    mode = _request_header(request, "X-OpenMates-Task-Actor") or "user"
    if mode not in {"user", "assignee"}:
        raise HTTPException(status_code=400, detail="TASK_ACTIVITY_ACTOR_INVALID")
    if mode == "assignee" and source_surface != "cli":
        raise HTTPException(status_code=403, detail="TASK_ACTIVITY_ASSIGNEE_CLIENT_REQUIRED")
    return mode


def _task_activity_response(entry: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "entry_id",
        "task_id",
        "kind",
        "actor_type",
        "actor_hash",
        "actor_display_name",
        "actor_profile_image_url",
        "actor_identity",
        "event_type",
        "source_surface",
        "previous_status",
        "next_status",
        "created_at",
        "deleted_at",
        "deleted_by_hash",
        "deleted_by_display_name",
        "encrypted_message",
        "encrypted_embed_key_material",
        "embed_refs",
    }
    projected = {key: value for key, value in entry.items() if key in allowed}
    if projected.get("kind") == "tombstone":
        projected["author_hash"] = projected.get("actor_hash")
    return projected


def _task_activity_cursor(entry: dict[str, Any]) -> str:
    return f"{int(entry['created_at'])}:{entry['entry_id']}"


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


def _task_ask_fallback(message: str) -> dict[str, Any]:
    return {
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


def _task_ask_applied_response(*, summary: str, history: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
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


def _task_ask_operation_for_patch(patch: dict[str, Any]) -> str:
    status_only_fields = {"status", "updated_at", "version", "blocked_reason_code"}
    return "status" if patch and set(patch) <= status_only_fields else "update"


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
    external_chat_provider: ExternalChatProvider | None = None,
    external_chat_lookup_hash: str | None = Query(default=None, pattern="^[0-9a-f]{64}$"),
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
    external_chat_lookup_hash = _unwrap_query_default(external_chat_lookup_hash)
    try:
        if team_id:
            await request.app.state.directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})
        if (external_chat_provider is None) != (external_chat_lookup_hash is None):
            raise ValueError("Task external chat filters require both provider and lookup hash")
        tasks = await service.list_tasks(
            current_user.id,
            status=status,
            project_id=project_id,
            chat_id=chat_id,
            external_chat_provider=external_chat_provider,
            external_chat_lookup_hash=external_chat_lookup_hash,
            assignee_hash=assignee_hash,
            label_hashes=label_hash_values,
            priority=priority_value,
            due_before=due_before,
            team_id=team_id,
            limit=limit,
        )
    except Exception as exc:
        _handle_task_error(exc)
    projections = []
    if not any((chat_id, external_chat_provider, external_chat_lookup_hash, project_id, assignee_hash, label_hash_values, priority_value is not None, due_before is not None)):
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
        if body.plan_id and body.assignee_type == "openmates":
            await _ensure_linked_plan_execution(request, current_user.id, body.model_dump())
        task = await service.create_task(current_user.id, body.model_dump())
        if task.get("plan_id"):
            try:
                await _work_control_service(request, current_user.id).invalidate_for_task_membership_change(
                    None, task, updated_at=int(task.get("updated_at") or time.time())
                )
            except Exception:
                await service.task_methods.delete_task(
                    str(task["task_id"]),
                    current_user.id,
                    int(task.get("version") or 1),
                )
                raise
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
        result = await run_task_ask_pipeline(body.instruction, secrets_manager)
        return {"proposed_tasks": [proposal.model_dump() for proposal in result.proposal], "inference_used": True, "processing": result.processing}
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
    encrypted_creates = body.encrypted_creates or ([body.encrypted_create] if body.encrypted_create is not None else [])
    encrypted_updates = body.encrypted_updates or ([body.encrypted_update] if body.encrypted_update is not None else [])
    exact_deletes = body.exact_deletes or ([body.exact_delete] if body.exact_delete is not None else [])
    operation_count = sum(bool(items) for items in (encrypted_creates, encrypted_updates, exact_deletes))
    if operation_count != 1:
        return _task_ask_fallback("Open or mention exact tasks before asking for task edits, deletes, or status changes.")
    try:
        tasks: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        action_type = "ask_create"
        summary = ""
        for encrypted_create in encrypted_creates:
            if encrypted_create.plan_id and encrypted_create.assignee_type == "openmates":
                await _ensure_linked_plan_execution(request, current_user.id, encrypted_create.model_dump())
            task = await service.create_task(current_user.id, encrypted_create.model_dump())
            if task.get("plan_id"):
                try:
                    await _work_control_service(request, current_user.id).invalidate_for_task_membership_change(
                        None, task, updated_at=int(task.get("updated_at") or time.time())
                    )
                except Exception:
                    await service.task_methods.delete_task(
                        str(task["task_id"]), current_user.id, int(task.get("version") or 1)
                    )
                    raise
            tasks.append(task)
            entries.append({"object_type": "task", "object_id": task["task_id"], "operation": "create", "after": task})
        for encrypted_update in encrypted_updates:
            patch = encrypted_update.patch.model_dump(exclude_unset=True)
            before = await service.task_methods.get_task(encrypted_update.task_id, current_user.id)
            task = await service.update_task(encrypted_update.task_id, current_user.id, patch)
            if "plan_id" in patch:
                await _work_control_service(request, current_user.id).invalidate_for_task_membership_change(
                    before, task, updated_at=int(patch.get("updated_at") or time.time())
                )
            tasks.append(task)
            entries.append({
                "object_type": "task",
                "object_id": encrypted_update.task_id,
                "operation": _task_ask_operation_for_patch(patch),
                "before": before,
                "after": task,
            })
        for exact_delete in exact_deletes:
            before = await service.task_methods.get_task(exact_delete.task_id, current_user.id)
            async with _work_control_service(request, current_user.id).delete_guard(f"task:{exact_delete.task_id}") as lease:
                if lease is not None:
                    await lease.assert_held()
                deleted = await service.task_methods.delete_task(exact_delete.task_id, current_user.id, exact_delete.version)
            if not deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            if before and before.get("plan_id"):
                await _work_control_service(request, current_user.id).invalidate_for_task_membership_change(
                    before, None, updated_at=int(time.time())
                )
            entries.append({"object_type": "task", "object_id": exact_delete.task_id, "operation": "delete", "before": before})
        if encrypted_updates:
            action_type = "ask_update"
            summary = f"Updated {len(encrypted_updates)} task(s)."
        elif exact_deletes:
            action_type = "ask_delete"
            summary = f"Deleted {len(exact_deletes)} task(s)."
        else:
            summary = f"Created {len(encrypted_creates)} task(s)."
        history = await _record_task_history(
            history_service,
            current_user.id,
            source="ai_ask",
            action_type=action_type,
            entries=entries,
            redacted_summary=f"{summary[:-1]} from ask" if summary.endswith(".") else f"{summary} from ask",
        )
        return _task_ask_applied_response(
            summary=summary,
            history=history,
            extra={
                "task": tasks[0] if len(tasks) == 1 else None,
                "tasks": tasks,
                "deleted_task_ids": [exact_delete.task_id for exact_delete in exact_deletes],
            },
        )
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


@router.get("/{task_id}/activity")
@limiter.limit("60/minute")
async def list_user_task_activity(
    request: Request,
    response: Response,
    task_id: str,
    team_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    """First-party ciphertext read; Task authorization applies, no credits."""

    current_user = await _current_user(request, response)
    team_id = _unwrap_query_default(team_id)
    cursor = _unwrap_query_default(cursor)
    limit = int(_unwrap_query_default(limit))
    try:
        if team_id:
            await request.app.state.directus_service.team.require_team_role(
                team_id, current_user.id, {"owner", "admin", "member", "viewer"}
            )
        entries = await service.list_task_activity(
            task_id,
            current_user.id,
            team_id=team_id,
            cursor=cursor,
            limit=limit + 1,
        )
        visible = entries[:limit]
        return {
            "entries": [_task_activity_response(entry) for entry in visible],
            "next_cursor": _task_activity_cursor(visible[-1]) if len(entries) > limit and visible else None,
        }
    except Exception as exc:
        _handle_task_error(exc)


@router.post("/{task_id}/activity")
@limiter.limit("30/minute")
async def create_user_task_activity(
    request: Request,
    response: Response,
    task_id: str,
    body: UserTaskActivityCreateRequest,
    team_id: str | None = Query(default=None),
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    """First-party ciphertext mutation; authenticated Task writers, no credits."""

    current_user = await _current_user(request, response)
    team_id = _unwrap_query_default(team_id)
    try:
        if team_id:
            await request.app.state.directus_service.team.require_team_role(
                team_id, current_user.id, {"owner", "admin", "member"}
            )
        source_surface = derive_task_activity_source_surface(request)
        entry = await service.create_task_activity(
            task_id,
            current_user.id,
            payload=body.model_dump(),
            team_id=team_id,
            source_surface=source_surface,
            actor_mode=derive_task_activity_actor_mode(request, source_surface),
            actor_display_name=getattr(current_user, "username", None),
            actor_profile_image_url=getattr(current_user, "profile_image_url", None),
        )
        return {"entry": _task_activity_response(entry)}
    except Exception as exc:
        _handle_task_error(exc)


@router.delete("/{task_id}/activity/{entry_id}")
@limiter.limit("30/minute")
async def delete_user_task_activity(
    request: Request,
    response: Response,
    task_id: str,
    entry_id: str,
    team_id: str | None = Query(default=None),
    service: UserTaskService = Depends(get_user_task_service),
) -> dict[str, Any]:
    """Logical Activity deletion preserving safe tombstone attribution."""

    current_user = await _current_user(request, response)
    team_id = _unwrap_query_default(team_id)
    try:
        allow_task_mutation = False
        if team_id:
            await request.app.state.directus_service.team.require_team_role(
                team_id, current_user.id, {"owner", "admin", "member"}
            )
            allow_task_mutation = True
        entry = await service.delete_task_activity(
            task_id,
            entry_id,
            current_user.id,
            team_id=team_id,
            deleted_at=int(time.time()),
            allow_task_mutation=allow_task_mutation,
            deleted_by_display_name=getattr(current_user, "username", None),
        )
        return {"entry": _task_activity_response(entry)}
    except Exception as exc:
        _handle_task_error(exc)


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
        async with _work_control_service(request, current_user.id).restore_delete_guard(
            history_service, user_id=current_user.id, object_type="task", object_id=task_id, entry_id=body.entry_id, state=body.state
        ) as lease:
            if lease is not None:
                await lease.assert_held()
            result = await history_service.restore_object_to_entry(
                user_id=current_user.id, object_type="task", object_id=task_id, entry_id=body.entry_id, state=body.state, source="cli"
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
    team_id: str | None = Query(default=None),
    service: UserTaskService = Depends(get_user_task_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    team_id = _unwrap_query_default(team_id)
    try:
        await _require_task_team_role(request, current_user.id, team_id)
        before = await service.task_methods.get_task(task_id, current_user.id, team_id)
        patch = body.model_dump(exclude_unset=True)
        task = await service.update_task(
            task_id,
            current_user.id,
            patch,
            team_id=team_id,
        )
        if not team_id and "plan_id" in patch:
            await _work_control_service(request, current_user.id).invalidate_for_task_membership_change(
                before, task, updated_at=int(patch.get("updated_at") or time.time())
            )
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


@router.post("/{task_id}/dependencies")
@limiter.limit("30/minute")
async def add_task_dependency(request: Request, response: Response, task_id: str, body: WorkDependencyRequest) -> dict[str, Any]:
    """First-party session or approved-device route; standard rate limit, no credits."""
    current_user = await _current_user(request, response)
    try:
        edge = await _work_control_service(request, current_user.id).add_dependency(f"task:{task_id}", body.target_ref)
        return {"dependency": edge}
    except Exception as exc:
        _handle_task_error(exc)


@router.delete("/{task_id}/dependencies/{target_kind}/{target_id}")
@limiter.limit("30/minute")
async def remove_task_dependency(request: Request, response: Response, task_id: str, target_kind: Literal["plan", "task"], target_id: str) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        await _work_control_service(request, current_user.id).remove_dependency(f"task:{task_id}", f"{target_kind}:{target_id}")
        return {"deleted": True}
    except Exception as exc:
        _handle_task_error(exc)


@router.get("/{task_id}/dependencies")
@limiter.limit("60/minute")
async def list_task_dependencies(request: Request, response: Response, task_id: str) -> dict[str, Any]:
    """First-party/API-key read; owner-scoped safe dependency metadata only."""
    current_user = await _current_user(request, response)
    try:
        return await _work_control_service(request, current_user.id).dependency_read_model(f"task:{task_id}")
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
        await _require_task_team_role(request, current_user.id, body.team_id)
        before = await service.task_methods.get_task(task_id, current_user.id, body.team_id)
        if body.team_id:
            raise ValueError("Team work-control task execution is not supported in this slice")
        if before:
            blockers = await _work_control_service(request, current_user.id).dependency_blockers(f"task:{task_id}")
            if blockers:
                raise ValueError(f"Task execution is blocked: {blockers}")
        if before:
            await _ensure_linked_plan_execution(request, current_user.id, before)
        task = await service.start_ai(
            task_id,
            current_user.id,
            body.model_dump(exclude_unset=True, exclude={"team_id"}),
            team_id=body.team_id,
        )
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
        await _work_control_service(request, current_user.id).ensure_unlinked(f"task:{task_id}")
        task = await move_workspace_record_to_team(
            directus_service=request.app.state.directus_service,
            actor_user_id=current_user.id,
            team_id=body.team_id,
            workspace_type="task",
            object_id=task_id,
            confirmed=body.confirmed,
            encrypted_slug=body.encrypted_slug,
            slug_lookup_hash=body.slug_lookup_hash,
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
    team_id: str | None = Query(default=None),
    service: UserTaskService = Depends(get_user_task_service),
    workflow_projection_service: WorkflowTaskProjectionService = Depends(get_workflow_task_projection_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    team_id = _unwrap_query_default(team_id)
    try:
        await _require_task_team_role(request, current_user.id, team_id)
        skipped_projection = None if team_id else await run_in_threadpool(workflow_projection_service.skip_scheduled_projection, current_user.id, task_id)
        if skipped_projection is not None:
            return {"deleted": True, "task_id": task_id, "workflow_run": skipped_projection}
        before = await service.task_methods.get_task(task_id, current_user.id, team_id)
        if team_id:
            raise ValueError("Team work-control task deletion is not supported in this slice")
        async with _work_control_service(request, current_user.id).delete_guard(f"task:{task_id}") as lease:
            if lease is not None:
                await lease.assert_held()
            deleted = await service.task_methods.delete_task(task_id, current_user.id, version, team_id=team_id)
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
        if before and before.get("plan_id"):
            await _work_control_service(request, current_user.id).invalidate_for_task_membership_change(
                before, None, updated_at=int(time.time())
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
        await _require_task_team_role(request, current_user.id, body.team_id)
        before = await queue_service.task_methods.get_task(task_id, current_user.id, body.team_id)
        if body.team_id:
            raise ValueError("Team work-control task completion is not supported in this slice")
        blockers = await _work_control_service(request, current_user.id).dependency_blockers(f"task:{task_id}")
        if blockers:
            raise ValueError(f"Task completion is blocked: {blockers}")
        if before:
            await _ensure_linked_plan_execution(request, current_user.id, before)
        task = await queue_service.complete_task(task_id, current_user.id, version=body.version, team_id=body.team_id)
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
        await _require_task_team_role(request, current_user.id, body.team_id)
        before = await queue_service.task_methods.get_task(task_id, current_user.id, body.team_id)
        task = await queue_service.block_task(
            task_id,
            current_user.id,
            version=body.version,
            blocked_reason_code=body.blocked_reason_code,
            encrypted_blocked_reason=body.encrypted_blocked_reason,
            team_id=body.team_id,
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
        await _require_task_team_role(request, current_user.id, body.team_id)
        before = await queue_service.task_methods.get_task(task_id, current_user.id, body.team_id)
        task = await queue_service.unblock_task(task_id, current_user.id, version=body.version, team_id=body.team_id)
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
        await _require_task_team_role(request, current_user.id, body.team_id)
        before = await queue_service.task_methods.get_task(task_id, current_user.id, body.team_id)
        task = await queue_service.skip_task(task_id, current_user.id, version=body.version, team_id=body.team_id)
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
    try:
        await _require_task_team_role(request, current_user.id, body.team_id)
    except Exception as exc:
        _handle_task_error(exc)
    now = int(time.time())
    tasks: list[dict[str, Any]] = []
    history_entries: list[dict[str, Any]] = []
    for move in body.moves:
        moved_before = await service.task_methods.get_task(move.task_id, current_user.id, body.team_id) if body.team_id else await service.task_methods.get_task(move.task_id, current_user.id)
        patch = move.model_dump(exclude_unset=True, exclude={"task_id", "before_task_id", "after_task_id"})
        patch["updated_at"] = now
        if "position" not in patch:
            if move.before_task_id:
                anchor_before = await service.task_methods.get_task(move.before_task_id, current_user.id, body.team_id) if body.team_id else await service.task_methods.get_task(move.before_task_id, current_user.id)
                patch["position"] = int(anchor_before.get("position") or 0) - 1 if anchor_before else now
            elif move.after_task_id:
                after = await service.task_methods.get_task(move.after_task_id, current_user.id, body.team_id) if body.team_id else await service.task_methods.get_task(move.after_task_id, current_user.id)
                patch["position"] = int(after.get("position") or 0) + 1 if after else now
        try:
            task = (
                await service.update_task(move.task_id, current_user.id, patch, team_id=body.team_id)
                if body.team_id
                else await service.update_task(move.task_id, current_user.id, patch)
            )
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
