# backend/core/api/app/routes/project_item_links.py
#
# Project link operations for existing embeds: adopt a chat embed as a Project
# file / application / test result, rename a file link and delete a file link.
#
# Access model: first-party client surface only (session auth; web, CLI/TUI and
# Apple through the shared Rust core). Display names, metadata, the encrypted
# target id and the Project-key wrapper are client-encrypted, so these routes
# are not part of the public or developer API-key surface. Every write runs as
# one atomic operation in the embed-version-transaction Directus extension,
# idempotent by operation_id. Contract:
# docs/plans/cloud-project-development/contracts/project-embed-adoption.md

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.projects import TEAM_MUTATE_ROLES, get_directus_service, hash_id
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.embed_version_transaction_service import (
    EmbedVersionTransactionError,
    EmbedVersionTransactionService,
)
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.limiter import limiter

router = APIRouter(prefix="/v1/projects", tags=["Project item links"], dependencies=[Depends(ensure_projects_enabled)])

CIPHERTEXT_MAX_LENGTH = 4 * 1024 * 1024
OPERATION_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
# Stable error codes forwarded from the atomic operation. Anything else is a
# server fault and is reported as such, never as success.
STABLE_ERROR_CODES = frozenset({
    "project_not_found", "forbidden", "embed_not_found", "embed_already_linked", "path_conflict",
    "invalid_request", "project_item_not_found", "operation_payload_mismatch", "embed_key_ambiguous",
})


class AdoptEmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(pattern=OPERATION_ID_PATTERN)
    chat_id: str = Field(min_length=1, max_length=512)
    embed_id: str = Field(min_length=1, max_length=512)
    project_item_id: str = Field(pattern=UUID_PATTERN)
    kind: Literal["file", "application", "test_result"]
    target_id_encrypted: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)
    encrypted_display_name: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)
    encrypted_metadata: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)
    project_key_wrapper: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)
    team_id: Optional[str] = Field(default=None, min_length=1, max_length=512)


class RenameItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(pattern=OPERATION_ID_PATTERN)
    new_project_item_id: str = Field(pattern=UUID_PATTERN)
    encrypted_display_name: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)
    encrypted_metadata: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)


class DeleteItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(pattern=OPERATION_ID_PATTERN)


async def _require_writable_project(
    directus_service: DirectusService, project_id: str, user: User, team_id: str | None,
) -> dict[str, Any] | None:
    """Return the Team membership (None for Personal) after the Project write check."""
    membership = None
    if team_id:
        try:
            membership = await directus_service.team.require_team_role(team_id, user.id, TEAM_MUTATE_ROLES)
        except TeamPermissionError as exc:
            raise HTTPException(status_code=403, detail="forbidden") from exc
    if not await directus_service.project.get_project(project_id, user.id, team_id=team_id):
        raise HTTPException(status_code=404, detail="project_not_found")
    return membership


async def _require_own_item_for_member(
    directus_service: DirectusService, project_id: str, project_item_id: str, user: User,
    team_id: str | None, membership: dict[str, Any] | None,
) -> None:
    """Team members manage only the items they attached; admins and owners manage any."""
    if not membership or membership.get("role") != "member":
        return
    item = await directus_service.project.get_item(project_id, project_item_id, user.id, team_id=team_id)
    if not item:
        raise HTTPException(status_code=404, detail="project_item_not_found")
    if item.get("attached_by_user_hash") != hash_id(user.id):
        raise HTTPException(status_code=403, detail="forbidden")


async def _run(directus_service: DirectusService, action: str, data: Dict[str, Any], user: User) -> Dict[str, Any]:
    try:
        return await EmbedVersionTransactionService(directus_service).project_item_operation(
            action, data, user_id=user.id,
        )
    except EmbedVersionTransactionError as exc:
        if exc.code in STABLE_ERROR_CODES and 400 <= exc.status_code < 500:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
        raise HTTPException(status_code=500, detail="project_item_transaction_failed") from exc


@router.post("/{project_id}/items/adopt-embed")
@limiter.limit("60/minute")
async def adopt_project_embed(
    request: Request,
    project_id: str,
    body: AdoptEmbedRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Link an existing chat embed into the Project; the chat keeps reading it."""
    await _require_writable_project(directus_service, project_id, current_user, body.team_id)
    data = {**body.model_dump(exclude_none=True), "project_id": project_id}
    return {"result": await _run(directus_service, "adopt", data, current_user)}


@router.post("/{project_id}/items/{project_item_id}/rename")
@limiter.limit("60/minute")
async def rename_project_item(
    request: Request,
    project_id: str,
    project_item_id: str,
    body: RenameItemRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Change a file link's path; the embed id and its revision history are kept."""
    membership = await _require_writable_project(directus_service, project_id, current_user, team_id)
    await _require_own_item_for_member(directus_service, project_id, project_item_id, current_user, team_id, membership)
    data = {
        **body.model_dump(), "project_id": project_id, "project_item_id": project_item_id,
        **({"team_id": team_id} if team_id else {}),
    }
    return {"result": await _run(directus_service, "rename", data, current_user)}


@router.delete("/{project_id}/items/{project_item_id}")
@limiter.limit("60/minute")
async def delete_project_item_link(
    request: Request,
    project_id: str,
    project_item_id: str,
    body: DeleteItemRequest = Body(...),
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Remove the link from the folder; the embed and its revisions stay for restore."""
    membership = await _require_writable_project(directus_service, project_id, current_user, team_id)
    await _require_own_item_for_member(directus_service, project_id, project_item_id, current_user, team_id, membership)
    data = {
        **body.model_dump(), "project_id": project_id, "project_item_id": project_item_id,
        **({"team_id": team_id} if team_id else {}),
    }
    return {"result": await _run(directus_service, "delete", data, current_user)}
