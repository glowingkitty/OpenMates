# backend/core/api/app/routes/projects.py
#
# Authenticated Projects V1 API. All user-facing metadata is already encrypted
# by the client; the API only stores hashed identifiers and opaque ciphertexts.

import hashlib
import logging
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from backend.apps.ai.processing.workspace_ask_planner import WorkspaceAskPlanningError, run_project_ask_pipeline
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.directus.project_methods import ProjectMoveError
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.project_remote_access_service import (
    ProjectRemoteAccessError,
    ProjectRemoteAccessService,
)
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowNotFoundError, WorkflowService
from backend.core.api.app.services.workspace_change_history_service import WorkspaceChangeHistoryService, build_history_commands, s3_workspace_history_archive_io

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects", tags=["Projects"], dependencies=[Depends(ensure_projects_enabled)])

PROJECT_SOURCE_ID_MAX_LENGTH = 128
PROJECT_SOURCE_CIPHERTEXT_MAX_LENGTH = 128_000
PROJECT_SOURCE_CAPABILITIES_MAX_COUNT = 8
PROJECT_SETTINGS_DEFAULT_WRITE_MODE = "always_ask"
TEAM_READ_ROLES = {"owner", "admin", "member", "viewer"}
TEAM_MUTATE_ROLES = {"owner", "admin", "member"}
TEAM_ADMIN_ROLES = {"owner", "admin"}
TEAM_PROJECT_HISTORY_UNSUPPORTED = "TEAM_PROJECT_HISTORY_UNSUPPORTED"
TEAM_SOURCE_SAFE_FIELDS = {
    "source_id",
    "source_type",
    "encrypted_display_name",
    "encrypted_metadata",
    "capabilities",
    "status",
    "created_at",
    "updated_at",
    "last_indexed_at",
}


def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, "directus_service"):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_workspace_history_service(request: Request) -> WorkspaceChangeHistoryService:
    s3_service = getattr(request.app.state, "s3_service", None)
    if s3_service is not None:
        archive_writer, archive_reader = s3_workspace_history_archive_io(s3_service)
        return WorkspaceChangeHistoryService(request.app.state.directus_service, archive_writer=archive_writer, archive_reader=archive_reader)
    return WorkspaceChangeHistoryService(request.app.state.directus_service)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _require_project_role(
    directus_service: DirectusService,
    team_id: str | None,
    user_id: str,
    allowed_roles: set[str],
) -> dict[str, Any] | None:
    if not team_id:
        return None
    try:
        return await directus_service.team.require_team_role(team_id, user_id, allowed_roles)
    except TeamPermissionError as exc:
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc


def _require_team_project_wrapper(payload: dict[str, Any], team_id: str | None) -> None:
    wrappers = payload.get("key_wrappers") or []
    if not team_id:
        if any(wrapper.get("key_type") == "team" for wrapper in wrappers):
            raise HTTPException(status_code=400, detail="PROJECT_KEY_WRAPPER_CONTEXT_MISMATCH")
        return
    expected_team_hash = hash_id(team_id)
    if not wrappers or not all(
        wrapper.get("key_type") == "team"
        and wrapper.get("hashed_team_id") == expected_team_hash
        and wrapper.get("team_key_epoch") == 1
        for wrapper in wrappers
    ):
        raise HTTPException(status_code=400, detail="TEAM_PROJECT_KEY_WRAPPER_REQUIRED")


class ProjectKeyWrapperRequest(BaseModel):
    key_type: Literal["master", "chat", "project", "plan", "team"]
    hashed_chat_id: Optional[str] = None
    hashed_plan_id: Optional[str] = None
    hashed_team_id: Optional[str] = None
    team_key_epoch: Optional[int] = Field(default=None, ge=1)
    encrypted_project_key: str = Field(min_length=1)
    wrapper_version: int = Field(default=1, ge=1)
    created_at: Optional[int] = None
    expires_at: Optional[int] = None


async def _record_project_history(
    history_service: WorkspaceChangeHistoryService,
    user_id: str,
    *,
    source: str = "web",
    action_type: str,
    entries: list[dict[str, Any]],
    redacted_summary: str,
) -> dict[str, Any]:
    history = await history_service.record_change_set(
        user_id=user_id,
        source=source,
        namespace="projects",
        action_type=action_type,
        entries=entries,
        redacted_summary=redacted_summary,
    )
    return {**history, **build_history_commands(history["change_set"]["change_set_id"], history["entries"])}


def _project_ask_fallback(message: str) -> Dict[str, Any]:
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


def _project_ask_applied_response(*, summary: str, history: dict[str, Any], extra: dict[str, Any]) -> Dict[str, Any]:
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


def _project_ask_operation_for_patch(patch: dict[str, Any]) -> str:
    archive_only_fields = {"archived", "updated_at", "version"}
    return "archive" if patch and set(patch) <= archive_only_fields and patch.get("archived") is True else "update"


class ProjectCreateRequest(BaseModel):
    project_id: str
    encrypted_project_key: Optional[str] = None
    encrypted_name: str
    encrypted_description: Optional[str] = None
    encrypted_icon: Optional[str] = None
    encrypted_color: Optional[str] = None
    pinned: bool = False
    created_at: int
    updated_at: int
    last_opened_at: int
    key_wrappers: List[ProjectKeyWrapperRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_encrypted_project_key(self) -> "ProjectCreateRequest":
        if not self.encrypted_project_key and not self.key_wrappers:
            raise ValueError("encrypted_project_key or key_wrappers is required")
        return self


class ProjectUpdateRequest(BaseModel):
    encrypted_name: Optional[str] = None
    encrypted_description: Optional[str] = None
    encrypted_icon: Optional[str] = None
    encrypted_color: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None
    updated_at: Optional[int] = None
    last_opened_at: Optional[int] = None
    version: Optional[int] = None


class ProjectRestoreRequest(BaseModel):
    entry_id: str = Field(min_length=1)
    state: Literal["before", "after"] = "after"


class ProjectAskPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)


class ProjectAskUpdateRequest(BaseModel):
    project_id: str = Field(min_length=1)
    patch: ProjectUpdateRequest


class ProjectAskDeleteRequest(BaseModel):
    project_id: str = Field(min_length=1)
    version: int | None = None


class ProjectAskRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    encrypted_create: ProjectCreateRequest | None = None
    encrypted_update: ProjectAskUpdateRequest | None = None
    encrypted_updates: list[ProjectAskUpdateRequest] | None = None
    exact_delete: ProjectAskDeleteRequest | None = None
    exact_deletes: list[ProjectAskDeleteRequest] | None = None


class ProjectMoveRequest(BaseModel):
    team_id: str
    confirmed: bool
    moved_at: int | None = None
    team_project_key_wrapper: ProjectKeyWrapperRequest

    @model_validator(mode="after")
    def require_matching_team_wrapper(self) -> "ProjectMoveRequest":
        wrapper = self.team_project_key_wrapper
        if (
            wrapper.key_type != "team"
            or wrapper.hashed_team_id != hash_id(self.team_id)
            or wrapper.team_key_epoch != 1
            or wrapper.created_at is None
        ):
            raise ValueError("A matching Team epoch-1 Project key wrapper is required")
        return self


class FolderCreateRequest(BaseModel):
    folder_id: str
    parent_folder_id: Optional[str] = None
    encrypted_name: str
    encrypted_sort_key: Optional[str] = None
    created_at: int
    updated_at: int
    position: int = 0


class ProjectItemCreateRequest(BaseModel):
    project_item_id: str
    folder_id: Optional[str] = None
    item_type: str = Field(pattern="^(embed|chat|upload|workflow)$")
    target_id: str
    target_id_encrypted: str
    encrypted_display_name: Optional[str] = None
    encrypted_note: Optional[str] = None
    encrypted_metadata: Optional[str] = None
    created_at: int
    updated_at: int
    position: int = 0


class ProjectEmbedKeyRequest(BaseModel):
    hashed_embed_id: str
    key_type: str = Field(pattern="^(master|chat|project)$")
    hashed_chat_id: Optional[str] = None
    hashed_project_id: Optional[str] = None
    encrypted_embed_key: str
    created_at: int


class ProjectUploadEmbedRequest(BaseModel):
    embed: Dict[str, Any]
    embed_keys: List[ProjectEmbedKeyRequest]
    item: ProjectItemCreateRequest


class ProjectSourceCreateRequest(BaseModel):
    source_id: str = Field(max_length=PROJECT_SOURCE_ID_MAX_LENGTH)
    source_type: Literal[
        "local_folder",
        "local_git_repository",
        "remote_folder",
        "remote_git_repository",
    ]
    encrypted_display_name: str = Field(max_length=PROJECT_SOURCE_CIPHERTEXT_MAX_LENGTH)
    encrypted_metadata: str = Field(max_length=PROJECT_SOURCE_CIPHERTEXT_MAX_LENGTH)
    capabilities: List[Literal["read", "search", "import", "write_request"]] = Field(
        default_factory=list,
        max_length=PROJECT_SOURCE_CAPABILITIES_MAX_COUNT,
    )
    status: Literal["connected", "offline", "permission_required", "revoked"] = "connected"
    created_at: int
    updated_at: int
    last_indexed_at: Optional[int] = None


class ProjectRemoteAccessRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    requesting_client_id: str = Field(min_length=1, max_length=128)
    operation: Literal["list", "search", "read_text"]
    key_epoch: int = Field(ge=1)
    encrypted_envelope: str = Field(min_length=1, max_length=350_000)


class DeletePrecheckRequest(BaseModel):
    chat_id: str


class DeletePrecheckResponse(BaseModel):
    requires_decision: bool
    protected_embed_ids: List[str]
    project_reference_counts: Dict[str, int]


class ProjectSettingsUpdateRequest(BaseModel):
    write_mode: Literal["always_ask", "auto_approve_safe_writes"]
    encrypted_settings: Optional[str] = None
    updated_at: int


def serialize_project_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not settings:
        return {
            "write_mode": PROJECT_SETTINGS_DEFAULT_WRITE_MODE,
            "encrypted_settings": None,
            "updated_at": None,
        }
    return {
        "write_mode": settings.get("write_mode") or PROJECT_SETTINGS_DEFAULT_WRITE_MODE,
        "encrypted_settings": settings.get("encrypted_settings"),
        "updated_at": settings.get("updated_at"),
    }


@router.get("")
@limiter.limit("60/minute")
async def list_projects(
    request: Request,
    include_archived: bool = False,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    projects = await directus_service.project.list_projects(current_user.id, include_archived=include_archived, team_id=team_id)
    return {"projects": projects}


@router.post("")
@limiter.limit("30/minute")
async def create_project(
    request: Request,
    body: ProjectCreateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    payload = body.model_dump()
    _require_team_project_wrapper(payload, team_id)
    created = await directus_service.project.create_project(current_user.id, payload, team_id=team_id)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create project")
    history = await _record_project_history(
        history_service,
        current_user.id,
        action_type="create",
        entries=[{"object_type": "project", "object_id": created["project_id"], "operation": "create", "after": created}],
        redacted_summary="Created 1 project",
    )
    return {"project": created, "history": history}


@router.post("/ask/plan")
@limiter.limit("20/minute")
async def plan_project_ask_route(
    request: Request,
    body: ProjectAskPlanRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    del current_user
    secrets_manager = getattr(request.app.state, "secrets_manager", None)
    if secrets_manager is None:
        raise HTTPException(status_code=503, detail="Workspace ask inference is not configured")
    try:
        result = await run_project_ask_pipeline(body.instruction, secrets_manager)
        return {"proposed_project": result.proposal.model_dump(), "inference_used": True, "processing": result.processing}
    except WorkspaceAskPlanningError as exc:
        raise HTTPException(status_code=502, detail=f"Workspace ask inference failed: {exc}") from exc


@router.post("/ask")
@limiter.limit("20/minute")
async def ask_projects(
    request: Request,
    body: ProjectAskRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> Dict[str, Any]:
    encrypted_updates = body.encrypted_updates or ([body.encrypted_update] if body.encrypted_update is not None else [])
    exact_deletes = body.exact_deletes or ([body.exact_delete] if body.exact_delete is not None else [])
    operation_count = sum(bool(items) for items in (([body.encrypted_create] if body.encrypted_create is not None else []), encrypted_updates, exact_deletes))
    if operation_count != 1:
        return _project_ask_fallback("Open or mention an exact project before asking for project edits, archives, or deletes.")
    allowed_roles = TEAM_ADMIN_ROLES if exact_deletes else TEAM_MUTATE_ROLES
    await _require_project_role(directus_service, team_id, current_user.id, allowed_roles)
    projects: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    action_type = "ask_create"
    summary = ""
    if body.encrypted_create is not None:
        create_payload = body.encrypted_create.model_dump()
        _require_team_project_wrapper(create_payload, team_id)
        created = await directus_service.project.create_project(current_user.id, create_payload, team_id=team_id)
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create project")
        projects.append(created)
        entries.append({"object_type": "project", "object_id": created["project_id"], "operation": "create", "after": created})
        summary = "Created 1 project."
    for encrypted_update in encrypted_updates:
        patch = encrypted_update.patch.model_dump(exclude_unset=True)
        before = await directus_service.project.get_project(encrypted_update.project_id, current_user.id, team_id=team_id)
        updated = await directus_service.project.update_project(encrypted_update.project_id, current_user.id, patch, team_id=team_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Project not found")
        projects.append(updated)
        entries.append({
            "object_type": "project",
            "object_id": encrypted_update.project_id,
            "operation": _project_ask_operation_for_patch(patch),
            "before": before,
            "after": updated,
        })
    for exact_delete in exact_deletes:
        before = await directus_service.project.get_project(exact_delete.project_id, current_user.id, team_id=team_id)
        if not before:
            raise HTTPException(status_code=404, detail="Project not found")
        await _revoke_project_sources(
            request,
            directus_service,
            current_user.id,
            exact_delete.project_id,
            team_id=team_id,
        )
        deleted = await directus_service.project.delete_project(exact_delete.project_id, current_user.id, team_id=team_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        entries.append({"object_type": "project", "object_id": exact_delete.project_id, "operation": "delete", "before": before})
    if encrypted_updates:
        action_type = "ask_update"
        summary = f"Updated {len(encrypted_updates)} project(s)."
    elif exact_deletes:
        action_type = "ask_delete"
        summary = f"Deleted {len(exact_deletes)} project(s)."
    history = await _record_project_history(
        history_service,
        current_user.id,
        source="ai_ask",
        action_type=action_type,
        entries=entries,
        redacted_summary=f"{summary[:-1]} from ask" if summary.endswith(".") else f"{summary} from ask",
    )
    return _project_ask_applied_response(
        summary=summary,
        history=history,
        extra={
            "project": projects[0] if len(projects) == 1 else None,
            "projects": projects,
            "deleted_project_ids": [exact_delete.project_id for exact_delete in exact_deletes],
        },
    )


@router.get("/{project_id}")
@limiter.limit("60/minute")
async def get_project(
    request: Request,
    project_id: str,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    folders, items = await _load_project_children(project_id, current_user.id, directus_service, team_id=team_id)
    return {"project": project, "folders": folders, "items": items}


@router.post("/{project_id}/move")
@limiter.limit("20/minute")
async def move_project_to_team(
    request: Request,
    project_id: str,
    body: ProjectMoveRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    if not body.confirmed:
        raise HTTPException(status_code=409, detail="PROJECT_MOVE_CONFIRMATION_REQUIRED")
    await _require_project_role(directus_service, body.team_id, current_user.id, TEAM_MUTATE_ROLES)
    try:
        project = await directus_service.project.move_project_to_team(
            project_id,
            current_user.id,
            body.team_id,
            body.team_project_key_wrapper.model_dump(),
            moved_at=body.moved_at,
        )
    except ProjectMoveError as exc:
        raise HTTPException(status_code=409, detail="PROJECT_MOVE_FAILED") from exc
    return {"project": project}


@router.get("/{project_id}/history")
@limiter.limit("60/minute")
async def list_project_history(
    request: Request,
    project_id: str,
    limit: int = 50,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> Dict[str, Any]:
    del request
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    if team_id:
        raise HTTPException(status_code=409, detail=TEAM_PROJECT_HISTORY_UNSUPPORTED)
    if not await directus_service.project.get_project(project_id, current_user.id, team_id=team_id):
        raise HTTPException(status_code=404, detail="Project not found")
    entries = await history_service.list_object_history(current_user.id, object_type="project", object_id=project_id, limit=limit)
    return {"entries": entries}


@router.post("/{project_id}/restore")
@limiter.limit("20/minute")
async def restore_project_from_history(
    request: Request,
    project_id: str,
    body: ProjectRestoreRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> Dict[str, Any]:
    del request
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    if team_id:
        raise HTTPException(status_code=409, detail=TEAM_PROJECT_HISTORY_UNSUPPORTED)
    if not await directus_service.project.get_project(project_id, current_user.id, team_id=team_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        result = await history_service.restore_object_to_entry(
            user_id=current_user.id,
            object_type="project",
            object_id=project_id,
            entry_id=body.entry_id,
            state=body.state,
            source="cli",
        )
        return {"project": result.get("object"), "history": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{project_id}")
@limiter.limit("30/minute")
async def update_project(
    request: Request,
    project_id: str,
    body: ProjectUpdateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    patch = body.model_dump(exclude_unset=True)
    before = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    updated = await directus_service.project.update_project(project_id, current_user.id, patch, team_id=team_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")
    history = await _record_project_history(
        history_service,
        current_user.id,
        action_type="update",
        entries=[{"object_type": "project", "object_id": project_id, "operation": "update", "before": before, "after": updated}],
        redacted_summary="Updated 1 project",
    )
    return {"project": updated, "history": history}


@router.get("/{project_id}/sources")
@limiter.limit("60/minute")
async def list_project_sources(
    request: Request,
    project_id: str,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    membership = await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sources = await directus_service.project.list_sources(project_id, current_user.id, team_id=team_id)
    service = ProjectRemoteAccessService(request.app.state.cache_service)
    now = int(time.time())
    live_sources: List[Dict[str, Any]] = []
    for source in sources:
        status_value = "offline"
        binding: Dict[str, Any] = {}
        if source.get("status") == "revoked":
            status_value = "revoked"
        else:
            try:
                binding = await service.get_active_binding(
                    current_user.id,
                    project_id,
                    str(source.get("source_id") or ""),
                    team_id=team_id,
                    now=now,
                )
                status_value = "connected"
            except ProjectRemoteAccessError:
                pass
        if membership:
            safe_source = {key: value for key, value in source.items() if key in TEAM_SOURCE_SAFE_FIELDS}
            safe_source["status"] = status_value
            safe_source["ownership_label"] = (
                "attached_by_you"
                if source.get("attached_by_user_hash") == hash_id(current_user.id)
                else "team_source"
            )
            live_sources.append(safe_source)
        else:
            live_sources.append(
                {
                    **source,
                    "status": status_value,
                    "source_session_id": binding.get("source_session_id") if status_value == "connected" else None,
                    "key_epoch": binding.get("key_epoch") if status_value == "connected" else None,
                }
            )
    return {"sources": live_sources}


@router.post("/{project_id}/sources")
@limiter.limit("30/minute")
async def create_project_source(
    request: Request,
    project_id: str,
    body: ProjectSourceCreateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    source = await directus_service.project.create_source(
        project_id,
        current_user.id,
        body.model_dump(),
        team_id=team_id,
    )
    if not source:
        raise HTTPException(status_code=500, detail="Failed to create project source")
    return {"source": source}


@router.delete("/{project_id}/sources/{source_id}")
@limiter.limit("20/minute")
async def delete_project_source(
    request: Request,
    project_id: str,
    source_id: str,
    confirmed: bool = Query(False),
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    if not confirmed:
        raise HTTPException(status_code=409, detail="SOURCE_REMOVAL_CONFIRMATION_REQUIRED")
    membership = await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    source = await directus_service.project.get_source(
        project_id,
        current_user.id,
        source_id,
        team_id=team_id,
    )
    if not project or not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if membership and membership.get("role") == "member" and source.get("attached_by_user_hash") != hash_id(current_user.id):
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED")

    service = ProjectRemoteAccessService(request.app.state.cache_service)
    await service.revoke_source(
        user_id=current_user.id,
        project_id=project_id,
        source_id=source_id,
        team_id=team_id,
    )
    if not await directus_service.project.delete_source(
        project_id,
        current_user.id,
        source_id,
        team_id=team_id,
    ):
        raise HTTPException(status_code=404, detail="Source not found")
    return {"deleted": True}


@router.post("/{project_id}/sources/{source_id}/requests", status_code=202)
@limiter.limit("60/minute")
async def create_project_remote_access_request(
    project_id: str,
    source_id: str,
    body: ProjectRemoteAccessRequestCreate,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Create an opaque request on the first-party encrypted bridge."""

    await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    source = await directus_service.project.get_source(
        project_id, current_user.id, source_id, team_id=team_id
    )
    if not project or not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.get("status") == "revoked":
        raise HTTPException(status_code=409, detail="SOURCE_REVOKED")
    service = ProjectRemoteAccessService(request.app.state.cache_service)
    requester_device_hash = await _authenticated_request_device_hash(request, current_user.id)

    async def validate_team_host(host_user_id: str) -> bool:
        try:
            await directus_service.team.require_team_role(team_id, host_user_id, TEAM_READ_ROLES)
        except TeamPermissionError:
            return False
        return True

    async def mark_team_host_offline(host_user_id: str) -> None:
        await directus_service.project.mark_team_member_sources_offline(
            team_id,
            host_user_id,
            updated_at=int(time.time()),
        )

    try:
        return await service.create_request(
            user_id=current_user.id,
            team_id=team_id,
            project_id=project_id,
            source_id=source_id,
            request_id=body.request_id,
            requesting_client_id=body.requesting_client_id,
            requesting_device_fingerprint_hash=requester_device_hash,
            operation=body.operation,
            key_epoch=body.key_epoch,
            encrypted_envelope=body.encrypted_envelope,
            now=int(time.time()),
            validate_team_host=validate_team_host if team_id else None,
            mark_team_host_offline=mark_team_host_offline if team_id else None,
        )
    except ProjectRemoteAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("/{project_id}/sources/{source_id}/requests/{request_id}")
@limiter.limit("180/minute")
async def get_project_remote_access_request_result(
    project_id: str,
    source_id: str,
    request_id: str,
    requesting_client_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Return an opaque result only to its authenticated requesting client."""

    await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    source = await directus_service.project.get_source(
        project_id, current_user.id, source_id, team_id=team_id
    )
    if not project or not source:
        raise HTTPException(status_code=404, detail="Source not found")
    service = ProjectRemoteAccessService(request.app.state.cache_service)
    requester_device_hash = await _authenticated_request_device_hash(request, current_user.id)
    try:
        return await service.get_request_result(
            user_id=current_user.id,
            team_id=team_id,
            project_id=project_id,
            source_id=source_id,
            request_id=request_id,
            requesting_client_id=requesting_client_id,
            requesting_device_fingerprint_hash=requester_device_hash,
            now=int(time.time()),
        )
    except ProjectRemoteAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


async def _authenticated_request_device_hash(request: Request, user_id: str) -> str:
    """Resolve the current session's server-associated WebSocket identity."""
    auth_info = getattr(getattr(request, "state", None), "auth_info", None)
    connection_hash = auth_info.get("connection_hash") if isinstance(auth_info, dict) else None
    refresh_token = request.cookies.get("auth_refresh_token")
    if not connection_hash and not refresh_token:
        raise HTTPException(status_code=401, detail="FIRST_PARTY_SESSION_REQUIRED")
    if not connection_hash:
        assert refresh_token is not None
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        token_map = await request.app.state.cache_service.get(f"user_tokens:{user_id}") or {}
        metadata = token_map.get(token_hash) if isinstance(token_map, dict) else None
        connection_hash = metadata.get("connection_hash") if isinstance(metadata, dict) else None
    if (
        not isinstance(connection_hash, str)
        or len(connection_hash) != 64
        or any(character not in "0123456789abcdef" for character in connection_hash)
    ):
        raise HTTPException(status_code=409, detail="REQUESTER_DEVICE_IDENTITY_UNAVAILABLE")
    return connection_hash


@router.get("/{project_id}/settings")
@limiter.limit("60/minute")
async def get_project_settings(
    request: Request,
    project_id: str,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = await directus_service.project.get_project_settings(project_id, current_user.id, team_id=team_id)
    return {"settings": serialize_project_settings(settings)}


@router.patch("/{project_id}/settings")
@limiter.limit("30/minute")
async def update_project_settings(
    request: Request,
    project_id: str,
    body: ProjectSettingsUpdateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_ADMIN_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = await directus_service.project.upsert_project_settings(
        project_id,
        current_user.id,
        body.model_dump(),
        team_id=team_id,
    )
    if not settings:
        raise HTTPException(status_code=500, detail="Failed to update project settings")
    return {"settings": serialize_project_settings(settings)}


@router.delete("/{project_id}")
@limiter.limit("20/minute")
async def delete_project(
    request: Request,
    project_id: str,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    history_service: WorkspaceChangeHistoryService = Depends(get_workspace_history_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_ADMIN_ROLES)
    before = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not before:
        raise HTTPException(status_code=404, detail="Project not found")
    await _revoke_project_sources(request, directus_service, current_user.id, project_id, team_id=team_id)
    deleted = await directus_service.project.delete_project(project_id, current_user.id, team_id=team_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    history = await _record_project_history(
        history_service,
        current_user.id,
        action_type="delete",
        entries=[{"object_type": "project", "object_id": project_id, "operation": "delete", "before": before}],
        redacted_summary="Deleted 1 project",
    )
    return {"deleted": True, "history": history}


async def _revoke_project_sources(
    request: Request,
    directus_service: DirectusService,
    user_id: str,
    project_id: str,
    *,
    team_id: str | None,
) -> None:
    sources = await directus_service.project.list_sources(project_id, user_id, team_id=team_id)
    service = ProjectRemoteAccessService(request.app.state.cache_service)
    for source in sources:
        source_id = str(source.get("source_id") or "")
        if source_id:
            await service.revoke_source(
                user_id=user_id,
                project_id=project_id,
                source_id=source_id,
                team_id=team_id,
            )


@router.post("/{project_id}/folders")
@limiter.limit("30/minute")
async def create_folder(
    request: Request,
    project_id: str,
    body: FolderCreateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = body.model_dump()
    parent_folder_id = payload.pop("parent_folder_id", None)
    if parent_folder_id and not await directus_service.project.folder_exists(
        project_id,
        parent_folder_id,
        current_user.id,
        team_id=team_id,
    ):
        raise HTTPException(status_code=400, detail="Parent folder not found in project")
    payload["hashed_project_id"] = hash_id(project_id)
    payload["hashed_parent_folder_id"] = hash_id(parent_folder_id) if parent_folder_id else None
    folder = await directus_service.project.create_folder(current_user.id, payload, team_id=team_id)
    if not folder:
        raise HTTPException(status_code=500, detail="Failed to create folder")
    return {"folder": folder}


@router.post("/{project_id}/items")
@limiter.limit("60/minute")
async def create_item(
    request: Request,
    project_id: str,
    body: ProjectItemCreateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = body.model_dump()
    folder_id = payload.pop("folder_id", None)
    target_id = payload.pop("target_id")
    if folder_id and not await directus_service.project.folder_exists(
        project_id,
        folder_id,
        current_user.id,
        team_id=team_id,
    ):
        raise HTTPException(status_code=400, detail="Folder not found in project")
    await _validate_project_target(payload["item_type"], target_id, current_user.id, directus_service)
    payload["hashed_project_id"] = hash_id(project_id)
    payload["hashed_folder_id"] = hash_id(folder_id) if folder_id else None
    payload["target_id_hash"] = hash_id(target_id)
    item = await directus_service.project.create_item(current_user.id, payload, team_id=team_id)
    if not item:
        raise HTTPException(status_code=500, detail="Failed to add project item")
    return {"item": item}


@router.delete("/{project_id}/items")
@limiter.limit("60/minute")
async def delete_item(
    request: Request,
    project_id: str,
    item_type: Literal["embed", "chat", "workflow"] = Query(...),
    target_id: str = Query(..., min_length=1),
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    membership = await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if membership and membership.get("role") == "member":
        matching_items = [
            item
            for item in await directus_service.project.list_items(project_id, current_user.id, team_id=team_id)
            if item.get("item_type") == item_type and item.get("target_id_hash") == hash_id(target_id)
        ]
        if any(item.get("attached_by_user_hash") != hash_id(current_user.id) for item in matching_items):
            raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED")
    deleted = await directus_service.project.delete_item_for_project_target(
        project_id,
        item_type,
        target_id,
        current_user.id,
        team_id=team_id,
    )
    return {"deleted": deleted > 0, "deleted_count": deleted}


@router.post("/{project_id}/upload-embed")
@limiter.limit("30/minute")
async def create_project_upload_embed(
    request: Request,
    project_id: str,
    body: ProjectUploadEmbedRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_MUTATE_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    embed_payload = dict(body.embed)
    embed_id = embed_payload.get("embed_id")
    if not embed_id:
        raise HTTPException(status_code=400, detail="embed.embed_id is required")
    if body.item.target_id != embed_id:
        raise HTTPException(status_code=400, detail="Project item target must match upload embed")
    if body.item.folder_id and not await directus_service.project.folder_exists(
        project_id,
        body.item.folder_id,
        current_user.id,
        team_id=team_id,
    ):
        raise HTTPException(status_code=400, detail="Folder not found in project")
    _validate_project_upload_keys(body.embed_keys, embed_id, project_id)

    embed_payload["hashed_user_id"] = hash_id(current_user.id)
    embed_payload.setdefault("status", "finished")
    embed_payload.setdefault("created_at", body.item.created_at)
    embed_payload.setdefault("updated_at", body.item.updated_at)
    embed_payload.setdefault("encryption_mode", "client")
    embed_payload.setdefault("is_private", True)
    embed_payload.setdefault("is_shared", False)

    created_embed = await directus_service.embed.create_embed(embed_payload)
    if not created_embed:
        raise HTTPException(status_code=500, detail="Failed to create upload embed")

    created_key_ids: List[str] = []
    for key in body.embed_keys:
        key_payload = key.model_dump()
        key_payload["hashed_user_id"] = hash_id(current_user.id)
        created_key = await directus_service.embed.create_embed_key(key_payload)
        if not created_key:
            await _cleanup_failed_upload_embed(directus_service, created_embed, created_key_ids)
            raise HTTPException(status_code=500, detail="Failed to create upload embed key")
        key_id = created_key.get("id")
        if key_id:
            created_key_ids.append(key_id)

    item_payload = body.item.model_dump()
    folder_id = item_payload.pop("folder_id", None)
    target_id = item_payload.pop("target_id")
    item_payload["hashed_project_id"] = hash_id(project_id)
    item_payload["hashed_folder_id"] = hash_id(folder_id) if folder_id else None
    item_payload["target_id_hash"] = hash_id(target_id)
    item = await directus_service.project.create_item(current_user.id, item_payload, team_id=team_id)
    if not item:
        await _cleanup_failed_upload_embed(directus_service, created_embed, created_key_ids)
        raise HTTPException(status_code=500, detail="Failed to add upload to project")
    return {"embed": created_embed, "item": item}


@router.get("/{project_id}/items")
@limiter.limit("60/minute")
async def list_items(
    request: Request,
    project_id: str,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project_role(directus_service, team_id, current_user.id, TEAM_READ_ROLES)
    project = await directus_service.project.get_project(project_id, current_user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    folders, items = await _load_project_children(project_id, current_user.id, directus_service, team_id=team_id)
    return {"folders": folders, "items": items}


@router.post("/deletion-precheck/chat")
@limiter.limit("60/minute")
async def chat_delete_precheck(
    request: Request,
    body: DeletePrecheckRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> DeletePrecheckResponse:
    is_owner = await directus_service.chat.check_chat_ownership(body.chat_id, current_user.id)
    if not is_owner:
        chat_metadata = await directus_service.chat.get_chat_metadata(body.chat_id)
        if chat_metadata:
            raise HTTPException(status_code=403, detail="You do not have permission to delete this chat")

    hashed_chat_id = hash_id(body.chat_id)
    params = {
        "filter[hashed_chat_id][_eq]": hashed_chat_id,
        "fields": "embed_id",
        "limit": -1,
    }
    rows = await directus_service.get_items("embeds", params=params, no_cache=True)
    embed_ids = [row.get("embed_id") for row in rows or [] if row.get("embed_id")]
    counts = await directus_service.project.get_project_embed_reference_counts(embed_ids, current_user.id)
    protected = [embed_id for embed_id, count in counts.items() if count > 0]
    return DeletePrecheckResponse(
        requires_decision=bool(protected),
        protected_embed_ids=protected,
        project_reference_counts={embed_id: counts[embed_id] for embed_id in protected},
    )


async def _load_project_children(
    project_id: str,
    user_id: str,
    directus_service: DirectusService,
    team_id: str | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    folders = await directus_service.project.list_folders(project_id, user_id, team_id=team_id)
    items = await directus_service.project.list_items(project_id, user_id, team_id=team_id)
    return folders, items


async def _validate_project_target(
    item_type: str,
    target_id: str,
    user_id: str,
    directus_service: DirectusService,
) -> None:
    if item_type == "chat":
        if not await directus_service.chat.check_chat_ownership(target_id, user_id):
            raise HTTPException(status_code=404, detail="Chat not found")
        return
    if item_type == "embed":
        embed = await directus_service.embed.get_embed_by_id(target_id)
        if not embed or embed.get("hashed_user_id") != hash_id(user_id):
            raise HTTPException(status_code=404, detail="Embed not found")
        return
    if item_type == "workflow":
        try:
            await run_in_threadpool(WorkflowService(DirectusWorkflowRepository()).get_workflow, target_id, user_id)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Workflow not found") from exc


def _validate_project_upload_keys(
    embed_keys: List[ProjectEmbedKeyRequest],
    embed_id: str,
    project_id: str,
) -> None:
    expected_embed_hash = hash_id(embed_id)
    expected_project_hash = hash_id(project_id)
    key_types = {key.key_type for key in embed_keys}
    if key_types != {"master", "project"} or len(embed_keys) != 2:
        raise HTTPException(status_code=400, detail="Upload embeds require master and project key wrappers")
    for key in embed_keys:
        if key.hashed_embed_id != expected_embed_hash:
            raise HTTPException(status_code=400, detail="Embed key wrapper does not match upload embed")
        if key.key_type == "project" and key.hashed_project_id != expected_project_hash:
            raise HTTPException(status_code=400, detail="Project embed key wrapper does not match project")
        if key.key_type == "master" and key.hashed_project_id:
            raise HTTPException(status_code=400, detail="Master embed key wrapper must not include a project id")


async def _cleanup_failed_upload_embed(
    directus_service: DirectusService,
    created_embed: Dict[str, Any],
    created_key_ids: List[str],
) -> None:
    for key_id in created_key_ids:
        try:
            await directus_service.delete_item("embed_keys", key_id)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to clean up project upload embed key %s: %s",
                key_id,
                cleanup_error,
            )
    embed_directus_id = created_embed.get("id")
    if embed_directus_id:
        try:
            await directus_service.delete_item("embeds", embed_directus_id)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to clean up project upload embed %s: %s",
                embed_directus_id,
                cleanup_error,
            )
