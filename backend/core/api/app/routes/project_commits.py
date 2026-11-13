# backend/core/api/app/routes/project_commits.py
#
# Native Project commits API. Access model: first-party client surface only
# (session auth; web, CLI/TUI and Apple through the shared Rust core). The
# message and affected paths are client-encrypted with the Project key, so the
# routes are not part of the public or developer API-key surface.
#
# A commit names a snapshot of hosted-file revisions: pointers of
# {target_id_hash, embed_version}, never file content. The server cannot decrypt
# file revisions, so a whole-commit restore is executed by the client: it
# reconstructs each file at the commit's version, writes it as a NEW revision
# through the existing atomic embed revision path, then records the restore here
# as a new commit that points at the new revisions. History is append-only.

import re
import uuid
from typing import Annotated, Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.projects import (
    TEAM_MUTATE_ROLES,
    TEAM_READ_ROLES,
    _require_project_role,
    get_directus_service,
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.limiter import limiter

router = APIRouter(prefix="/v1/projects", tags=["Project commits"], dependencies=[Depends(ensure_projects_enabled)])

COMMIT_MAX_ENTRIES = 500
COMMIT_MESSAGE_MAX_LENGTH = 64_000
COMMIT_PATHS_MAX_LENGTH = 512_000
COMMIT_PAGE_MAX = 100
MAX_EMBED_VERSION = 2_147_483_647
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class CommitEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id_hash: str
    embed_version: int = Field(ge=1, le=MAX_EMBED_VERSION)

    @field_validator("target_id_hash")
    @classmethod
    def _hash_shape(cls, value: str) -> str:
        if not SHA256_HEX_RE.fullmatch(value):
            raise ValueError("target_id_hash must be a lowercase SHA-256 hex digest")
        return value


class ProjectCommitCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit_id: str
    author_kind: Literal["user", "assistant"]
    chat_id: Optional[str] = Field(default=None, min_length=1, max_length=512)
    encrypted_message: str = Field(min_length=1, max_length=COMMIT_MESSAGE_MAX_LENGTH)
    encrypted_paths: Optional[str] = Field(default=None, min_length=1, max_length=COMMIT_PATHS_MAX_LENGTH)
    entries: List[CommitEntry] = Field(min_length=1, max_length=COMMIT_MAX_ENTRIES)
    created_at: int = Field(ge=0)

    @field_validator("commit_id")
    @classmethod
    def _commit_id_uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("commit_id must be a UUID") from exc
        return value

    @field_validator("entries")
    @classmethod
    def _unique_targets(cls, value: List[CommitEntry]) -> List[CommitEntry]:
        if len({entry.target_id_hash for entry in value}) != len(value):
            raise ValueError("A commit lists each Project file once")
        return value


def _public_commit(row: Dict[str, Any]) -> Dict[str, Any]:
    """Project only the fields clients need; never ownership hashes of other members."""
    return {
        "commit_id": row.get("commit_id"),
        "author_kind": row.get("author_kind"),
        "hashed_chat_id": row.get("hashed_chat_id"),
        "encrypted_message": row.get("encrypted_message"),
        "encrypted_paths": row.get("encrypted_paths"),
        "entries": row.get("entries") or [],
        "entry_count": row.get("entry_count"),
        "restored_from_commit_id": row.get("restored_from_commit_id"),
        "created_at": row.get("created_at"),
    }


async def _require_project(
    directus_service: DirectusService, project_id: str, user: User, team_id: str | None, roles: set[str],
) -> None:
    await _require_project_role(directus_service, team_id, user.id, roles)
    project = await directus_service.project.get_project(project_id, user.id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")


async def _persist_commit(
    directus_service: DirectusService,
    project_id: str,
    user: User,
    team_id: str | None,
    body: ProjectCommitCreateRequest,
    restored_from: str | None,
) -> Dict[str, Any]:
    targets = [entry.target_id_hash for entry in body.entries]
    members = await directus_service.project_commit.find_member_target_hashes(
        project_id, user.id, targets, team_id=team_id,
    )
    if set(targets) - members:
        raise HTTPException(status_code=422, detail="COMMIT_ENTRY_NOT_IN_PROJECT")
    if await directus_service.project_commit.get_commit(project_id, body.commit_id, user.id, team_id=team_id):
        raise HTTPException(status_code=409, detail="COMMIT_ALREADY_EXISTS")
    payload = {
        **body.model_dump(),
        "entries": [entry.model_dump() for entry in body.entries],
        "restored_from_commit_id": restored_from,
    }
    created = await directus_service.project_commit.create_commit(project_id, user.id, payload, team_id=team_id)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create Project commit")
    return {"commit": _public_commit(created)}


@router.post("/{project_id}/commits", status_code=201)
@limiter.limit("60/minute")
async def create_project_commit(
    request: Request,
    project_id: str,
    body: ProjectCommitCreateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project(directus_service, project_id, current_user, team_id, TEAM_MUTATE_ROLES)
    return await _persist_commit(directus_service, project_id, current_user, team_id, body, None)


@router.get("/{project_id}/commits")
@limiter.limit("120/minute")
async def list_project_commits(
    request: Request,
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=COMMIT_PAGE_MAX)] = 50,
    cursor: Annotated[int, Query(ge=0)] = 0,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Newest first. `next_cursor` is an opaque offset; null on the last page."""
    await _require_project(directus_service, project_id, current_user, team_id, TEAM_READ_ROLES)
    rows = await directus_service.project_commit.list_commits(
        project_id, current_user.id, team_id=team_id, limit=limit + 1, offset=cursor,
    )
    page = rows[:limit]
    return {
        "commits": [_public_commit(row) for row in page],
        "next_cursor": cursor + limit if len(rows) > limit else None,
    }


@router.get("/{project_id}/commits/{commit_id}")
@limiter.limit("120/minute")
async def get_project_commit(
    request: Request,
    project_id: str,
    commit_id: str,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    await _require_project(directus_service, project_id, current_user, team_id, TEAM_READ_ROLES)
    row = await directus_service.project_commit.get_commit(project_id, commit_id, current_user.id, team_id=team_id)
    if not row:
        raise HTTPException(status_code=404, detail="Commit not found")
    return {"commit": _public_commit(row)}


@router.post("/{project_id}/commits/{commit_id}/restore", status_code=201)
@limiter.limit("30/minute")
async def record_project_commit_restore(
    request: Request,
    project_id: str,
    commit_id: str,
    body: ProjectCommitCreateRequest,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Record a whole-commit restore after the client wrote the new revisions.

    The body is a normal commit pointing at the new heads. It must cover exactly
    the restored commit's files and no entry may point to an older revision than
    the restored one, so a restore can only add history.
    """
    await _require_project(directus_service, project_id, current_user, team_id, TEAM_MUTATE_ROLES)
    source = await directus_service.project_commit.get_commit(project_id, commit_id, current_user.id, team_id=team_id)
    if not source:
        raise HTTPException(status_code=404, detail="Commit not found")
    source_versions = {entry["target_id_hash"]: entry["embed_version"] for entry in source.get("entries") or []}
    restored_versions = {entry.target_id_hash: entry.embed_version for entry in body.entries}
    if set(source_versions) != set(restored_versions):
        raise HTTPException(status_code=422, detail="RESTORE_ENTRIES_MISMATCH")
    if any(restored_versions[target] < version for target, version in source_versions.items()):
        raise HTTPException(status_code=422, detail="RESTORE_MUST_NOT_REWIND_HISTORY")
    return await _persist_commit(directus_service, project_id, current_user, team_id, body, commit_id)
