"""Session-authenticated Apps workspace saved-result endpoints."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.apps_workspace_results_service import AppsResultConflict, AppsWorkspaceResultsService
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.limiter import limiter
from slowapi.util import get_remote_address

router = APIRouter(prefix="/v1/apps/workspace/results", tags=["Apps Workspace"])
_APP_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _session_rate_key(request: Request) -> str:
    auth = getattr(request.state, "auth_info", None)
    if isinstance(auth, dict) and auth.get("auth_source") == "session" and auth.get("user_id"):
        return f"apps-results:{auth['user_id']}"
    return f"apps-results-ip:{get_remote_address(request)}"


def _ciphertext(value: str) -> str:
    if len(value) > 700_000 or len(value) < 40 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value):
        raise ValueError("Expected bounded AES-GCM ciphertext")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Expected AES-GCM ciphertext") from exc
    if len(decoded) < 29:
        raise ValueError("AES-GCM ciphertext is too short")
    return value


class EncryptedResultEmbed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embed_id: UUID
    encrypted_type: str
    encrypted_content: str
    encrypted_text_preview: str | None = None
    status: Literal["processing", "finished", "error", "cancelled"] = "finished"
    embed_ids: list[UUID] | None = Field(default=None, max_length=500)
    parent_embed_id: UUID | None = None

    @field_validator("encrypted_type", "encrypted_content", "encrypted_text_preview")
    @classmethod
    def validate_ciphertext(cls, value: str | None) -> str | None:
        return _ciphertext(value) if value is not None else None


class SaveAppsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str
    skill_id: str
    team_id: UUID | None = None
    root_embed_id: UUID
    embeds: list[EncryptedResultEmbed] = Field(min_length=1, max_length=501)
    linked_embed_ids: list[UUID] = Field(default_factory=list, max_length=500)
    encrypted_embed_key: str
    expected_user_id: UUID

    @field_validator("app_id", "skill_id")
    @classmethod
    def validate_catalog_id(cls, value: str) -> str:
        if not _APP_ID.fullmatch(value):
            raise ValueError("Invalid app or skill ID")
        return value

    @field_validator("encrypted_embed_key")
    @classmethod
    def validate_key_wrapper(cls, value: str) -> str:
        _ciphertext(value)
        if len(value) > 256:
            raise ValueError("Key wrapper is too large")
        return value

    @model_validator(mode="after")
    def validate_graph(self) -> "SaveAppsResult":
        ids = [row.embed_id for row in self.embeds]
        if len(set(ids)) != len(ids) or ids.count(self.root_embed_id) != 1:
            raise ValueError("Result graph must have one unique root")
        root = next(row for row in self.embeds if row.embed_id == self.root_embed_id)
        child_ids = {row.embed_id for row in self.embeds if row.embed_id != self.root_embed_id}
        linked_ids = set(self.linked_embed_ids)
        if (root.parent_embed_id is not None or child_ids & linked_ids
            or set(root.embed_ids or []) != child_ids | linked_ids
            or len(root.embed_ids or []) != len(child_ids) + len(linked_ids)):
            raise ValueError("Root must reference exactly its child embeds")
        if any(row.parent_embed_id != self.root_embed_id or row.embed_ids for row in self.embeds if row.embed_id != self.root_embed_id):
            raise ValueError("Children must reference the root")
        if sum(len(row.encrypted_content) + len(row.encrypted_type) + len(row.encrypted_text_preview or "") for row in self.embeds) > 16_000_000:
            raise ValueError("Result graph is too large")
        return self


class IndexSavedEmbed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embed_id: UUID
    app_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    team_id: UUID | None = None


class LegacyIndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embed_id: UUID
    chat_id: UUID
    app_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    skill_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class LegacyIndexBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_user_id: UUID
    team_id: UUID | None = None
    items: list[LegacyIndexItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_roots(self) -> "LegacyIndexBatch":
        if len({item.embed_id for item in self.items}) != len(self.items):
            raise ValueError("Legacy index batch must have unique roots")
        return self


def _service(request: Request) -> AppsWorkspaceResultsService:
    return AppsWorkspaceResultsService(request.app.state.directus_service)


@router.post("")
@limiter.limit("30/minute", key_func=_session_rate_key)
async def save_result(body: SaveAppsResult, request: Request, user: User = Depends(get_current_user)) -> dict[str, Any]:
    if str(body.expected_user_id) != user.id:
        raise HTTPException(409, "APPS_RESULT_ACCOUNT_CHANGED")
    try:
        return await _service(request).save(user.id, body.model_dump(mode="json"))
    except TeamPermissionError as exc:
        raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc
    except AppsResultConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/index")
@limiter.limit("30/minute", key_func=_session_rate_key)
async def index_saved_embed(body: IndexSavedEmbed, request: Request, user: User = Depends(get_current_user)) -> dict[str, str]:
    try:
        root_id = await _service(request).index_existing(user.id, str(body.embed_id), body.app_id, str(body.team_id) if body.team_id else None)
        return {"root_embed_id": root_id}
    except TeamPermissionError as exc:
        raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc
    except AppsResultConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/index/batch")
@limiter.limit("12/minute", key_func=_session_rate_key)
async def index_legacy_embed_batch(
    body: LegacyIndexBatch, request: Request, user: User = Depends(get_current_user),
) -> dict[str, int]:
    if str(body.expected_user_id) != user.id:
        raise HTTPException(409, "APPS_RESULT_ACCOUNT_CHANGED")
    try:
        return await _service(request).index_legacy_batch(
            user.id, str(body.team_id) if body.team_id else None,
            [item.model_dump(mode="json") for item in body.items],
        )
    except TeamPermissionError as exc:
        raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc


@router.get("")
@limiter.limit("60/minute", key_func=_session_rate_key)
async def list_results(
    request: Request,
    app_id: str = Query(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
    team_id: UUID | None = None,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return await _service(request).list(user.id, app_id, str(team_id) if team_id else None, offset, limit)
    except TeamPermissionError as exc:
        raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc


@router.get("/{root_embed_id}")
@limiter.limit("60/minute", key_func=_session_rate_key)
async def get_result(
    root_embed_id: UUID, request: Request, team_id: UUID | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = await _service(request).detail(user.id, str(root_embed_id), str(team_id) if team_id else None)
    except TeamPermissionError as exc:
        raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc
    if result is None:
        raise HTTPException(404, "Result not found")
    return result
