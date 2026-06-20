# backend/core/api/app/routes/projects.py
#
# Authenticated Projects V1 API. All user-facing metadata is already encrypted
# by the client; the API only stores hashed identifiers and opaque ciphertexts.

import hashlib
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects", tags=["Projects"], dependencies=[Depends(ensure_projects_enabled)])


def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, "directus_service"):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ProjectCreateRequest(BaseModel):
    project_id: str
    encrypted_project_key: str
    encrypted_name: str
    encrypted_description: Optional[str] = None
    encrypted_icon: Optional[str] = None
    encrypted_color: Optional[str] = None
    pinned: bool = False
    created_at: int
    updated_at: int
    last_opened_at: int


class ProjectUpdateRequest(BaseModel):
    encrypted_name: Optional[str] = None
    encrypted_description: Optional[str] = None
    encrypted_icon: Optional[str] = None
    encrypted_color: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None
    updated_at: int
    last_opened_at: Optional[int] = None


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


class DeletePrecheckRequest(BaseModel):
    chat_id: str


class DeletePrecheckResponse(BaseModel):
    requires_decision: bool
    protected_embed_ids: List[str]
    project_reference_counts: Dict[str, int]


@router.get("")
@limiter.limit("60/minute")
async def list_projects(
    request: Request,
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    projects = await directus_service.project.list_projects(current_user.id, include_archived=include_archived)
    return {"projects": projects}


@router.post("")
@limiter.limit("30/minute")
async def create_project(
    request: Request,
    body: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    created = await directus_service.project.create_project(current_user.id, body.model_dump())
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create project")
    return {"project": created}


@router.get("/{project_id}")
@limiter.limit("60/minute")
async def get_project(
    request: Request,
    project_id: str,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    project = await directus_service.project.get_project(project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    folders, items = await _load_project_children(project_id, current_user.id, directus_service)
    return {"project": project, "folders": folders, "items": items}


@router.patch("/{project_id}")
@limiter.limit("30/minute")
async def update_project(
    request: Request,
    project_id: str,
    body: ProjectUpdateRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    updated = await directus_service.project.update_project(project_id, current_user.id, patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": updated}


@router.delete("/{project_id}")
@limiter.limit("20/minute")
async def delete_project(
    request: Request,
    project_id: str,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    deleted = await directus_service.project.delete_project(project_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": True}


@router.post("/{project_id}/folders")
@limiter.limit("30/minute")
async def create_folder(
    request: Request,
    project_id: str,
    body: FolderCreateRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    project = await directus_service.project.get_project(project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = body.model_dump()
    parent_folder_id = payload.pop("parent_folder_id", None)
    if parent_folder_id and not await directus_service.project.folder_exists(
        project_id,
        parent_folder_id,
        current_user.id,
    ):
        raise HTTPException(status_code=400, detail="Parent folder not found in project")
    payload["hashed_project_id"] = hash_id(project_id)
    payload["hashed_parent_folder_id"] = hash_id(parent_folder_id) if parent_folder_id else None
    folder = await directus_service.project.create_folder(current_user.id, payload)
    if not folder:
        raise HTTPException(status_code=500, detail="Failed to create folder")
    return {"folder": folder}


@router.post("/{project_id}/items")
@limiter.limit("60/minute")
async def create_item(
    request: Request,
    project_id: str,
    body: ProjectItemCreateRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    project = await directus_service.project.get_project(project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    payload = body.model_dump()
    folder_id = payload.pop("folder_id", None)
    target_id = payload.pop("target_id")
    if folder_id and not await directus_service.project.folder_exists(
        project_id,
        folder_id,
        current_user.id,
    ):
        raise HTTPException(status_code=400, detail="Folder not found in project")
    await _validate_project_target(payload["item_type"], target_id, current_user.id, directus_service)
    payload["hashed_project_id"] = hash_id(project_id)
    payload["hashed_folder_id"] = hash_id(folder_id) if folder_id else None
    payload["target_id_hash"] = hash_id(target_id)
    item = await directus_service.project.create_item(current_user.id, payload)
    if not item:
        raise HTTPException(status_code=500, detail="Failed to add project item")
    return {"item": item}


@router.post("/{project_id}/upload-embed")
@limiter.limit("30/minute")
async def create_project_upload_embed(
    request: Request,
    project_id: str,
    body: ProjectUploadEmbedRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    project = await directus_service.project.get_project(project_id, current_user.id)
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
    item = await directus_service.project.create_item(current_user.id, item_payload)
    if not item:
        await _cleanup_failed_upload_embed(directus_service, created_embed, created_key_ids)
        raise HTTPException(status_code=500, detail="Failed to add upload to project")
    return {"embed": created_embed, "item": item}


@router.get("/{project_id}/items")
@limiter.limit("60/minute")
async def list_items(
    request: Request,
    project_id: str,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    project = await directus_service.project.get_project(project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    folders, items = await _load_project_children(project_id, current_user.id, directus_service)
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
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    folders = await directus_service.project.list_folders(project_id, user_id)
    items = await directus_service.project.list_items(project_id, user_id)
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
