# backend/core/api/app/routes/embed_user_revisions.py
#
# User-made embed versions and their pending chat notices.
# Specification: feature.embed-user-edits. Plan: docs/plans/embed-user-edit-versions.
#
# Access model: first-party client surface only. Session auth through
# get_current_user (web, CLI/TUI and Apple through the shared Rust client core);
# developer API keys are not accepted. Both routes carry client-encrypted embed
# ciphertext or metadata about client-encrypted chats, so they are not part of
# the developer API and are hidden from the OpenAPI schema. Caddy routing: the
# web app calls both with credentials (session cookie), so
# /v1/embeds/*/user-revisions is listed in @webapp_paths, @webapp_general_options
# and @webapp_actual (FastAPI's specific-origin CORS, like /v1/embeds/*/versions);
# /v1/chats/* is already listed there. Requests without the web app Origin (CLI,
# Apple) fall through the public /v1/embeds/* and /v1/chats/* matchers, where
# FastAPI still requires the session; a developer API key is refused.
#
# - POST /v1/embeds/{embed_id}/user-revisions (30/minute): publishes version N+1
#   of an embed as one atomic, idempotent transaction (Directus extension
#   embed-version-transaction, commitUserEmbedRevision). Scope is either the
#   embed's chat (owner, or Team owner/admin/member) or a Project that links the
#   embed (Project write access); a Project-linked embed is accepted only in
#   Project scope. Stale version or head hash -> 409 embed_version_conflict.
#   No credits are charged here; Enhance is charged by its own route.
# - GET /v1/chats/{chat_id}/pending-embed-notices (120/minute): content-free
#   list of user versions whose "embed updated" system message the client core
#   still has to write. Chat owner, or Team owner/admin/member with team_id.

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.embed_version_transaction_service import (
    EmbedVersionTransactionError,
    EmbedVersionTransactionService,
)
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.pending_embed_notices import list_pending_embed_notices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Embed user revisions"])

CIPHERTEXT_MAX_LENGTH = 4 * 1024 * 1024
OPERATION_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"
HEX_64_PATTERN = r"^[0-9a-f]{64}$"
MAX_VERSION = 2_147_483_647
TEAM_WRITE_ROLES = {"owner", "admin", "member"}
# Refusals of the atomic operation that are part of the contract. Anything else
# is a server fault and is reported as such, never as success.
STABLE_ERROR_CODES = frozenset({
    "invalid_request", "invalid_scope", "invalid_action", "invalid_operation_id", "invalid_embed_id",
    "invalid_chat_id", "invalid_project_id", "invalid_team_id", "invalid_expected_revision",
    "invalid_content_hash", "invalid_ciphertext", "invalid_status", "invalid_timestamp",
    "invalid_history_rows", "invalid_restored_from", "invalid_file_source", "invalid_file_reference",
    "file_source_required", "unsupported_file_source", "invalid_s3_file_keys", "invalid_actor",
    "chat_access_denied", "project_access_denied", "project_item_access_denied", "project_context_required",
    "embed_access_denied", "embed_type_not_editable", "foreign_file_key", "enhance_result_not_found",
    "embed_not_found",
    "operation_payload_mismatch", "immutable_history_mismatch", "base_snapshot_required",
    "restore_source_missing", "enhance_result_not_ready", "enhance_result_expired", "enhance_version_mismatch",
    "enhance_scope_mismatch",
    "invalid_current_revision",
})
_SAFE_VARIANT = re.compile(r"^[a-z0-9_]{1,32}$")
# Bucket of every image variant (images.generate, Enhance and uploads store them in chatfiles).
MEDIA_INDEX_BUCKET = "chatfiles"


class ChatScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["chat"]
    chat_id: str = Field(min_length=1, max_length=512)
    team_id: Optional[str] = Field(default=None, min_length=1, max_length=512)


class ProjectScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["project"]
    project_id: str = Field(min_length=1, max_length=512)
    team_id: Optional[str] = Field(default=None, min_length=1, max_length=512)


class RevisionHead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encrypted_content: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)
    encrypted_text_preview: Optional[str] = Field(default=None, max_length=CIPHERTEXT_MAX_LENGTH)
    content_hash: Optional[str] = Field(default=None, pattern=HEX_64_PATTERN)
    status: Literal["finished"]
    updated_at: int = Field(ge=0)


class HistoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_number: int = Field(ge=1, le=MAX_VERSION)
    encrypted_snapshot: str = Field(min_length=1, max_length=CIPHERTEXT_MAX_LENGTH)
    created_at: int = Field(ge=0)


class FileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket: str = Field(min_length=1, max_length=128)
    key: str = Field(min_length=1, max_length=1024)


class FileSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["enhance", "upload"]
    operation_id: Optional[str] = Field(default=None, pattern=OPERATION_ID_PATTERN)
    upload_id: Optional[str] = Field(default=None, min_length=1, max_length=128)


class RevisionFiles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    head_file_keys: Optional[List[FileRef]] = Field(default=None, min_length=1, max_length=64)
    new_files: Optional[List[FileSource]] = Field(default=None, min_length=1, max_length=1)


class MediaIndex(BaseModel):
    """Server-readable index of the new image head (owner's 24-hour processing window).

    The same fields every image index row already holds: variant metadata with
    S3 keys, the shared nonce and the Vault-wrapped file key. Every variant key
    must be one of the head file keys of the commit.
    """

    model_config = ConfigDict(extra="forbid")

    files: Dict[str, Dict[str, Any]] = Field(min_length=1, max_length=16)
    # Media format V2 keeps the nonce inside each file, so the index nonce is empty.
    aes_nonce: str = Field(default="", max_length=256)
    vault_wrapped_aes_key: str = Field(min_length=1, max_length=4096, pattern=r"^vault:v[0-9]+:")
    content_type: Optional[str] = Field(default=None, pattern=r"^image/[a-z0-9.+-]{1,64}$")


class UserRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(pattern=OPERATION_ID_PATTERN)
    scope: Annotated[Union[ChatScope, ProjectScope], Field(discriminator="kind")]
    action: Literal["edit", "enhance", "restore", "crop"]
    expected_revision: int = Field(ge=1, le=MAX_VERSION - 1)
    expected_content_hash: str = Field(pattern=HEX_64_PATTERN)
    head: RevisionHead
    history_rows: List[HistoryRow] = Field(min_length=1, max_length=2)
    restored_from: Optional[int] = Field(default=None, ge=1, le=MAX_VERSION)
    files: Optional[RevisionFiles] = None
    media_index: Optional[MediaIndex] = None


def get_directus_service(request: Request) -> DirectusService:
    service = getattr(request.app.state, "directus_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return service


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _variant_refs(media_index: MediaIndex) -> set[tuple[str, str]]:
    """``(bucket, key)`` of every variant; image variants live in ``chatfiles`` unless one names its bucket."""
    refs = set()
    for name, variant in media_index.files.items():
        key = variant.get("s3_key")
        bucket = variant.get("bucket", MEDIA_INDEX_BUCKET)
        if (not _SAFE_VARIANT.fullmatch(name) or not isinstance(key, str) or not key
                or not isinstance(bucket, str) or not bucket):
            raise HTTPException(status_code=400, detail="invalid_media_index")
        refs.add((bucket, key))
    return refs


async def _forget_cached_embed(request: Request, embed_id: str) -> None:
    cache_service = getattr(request.app.state, "cache_service", None)
    if cache_service is None:
        raise RuntimeError("CacheService is not configured")
    client = await cache_service.client
    if client:
        await client.delete(f"embed:{embed_id}")


async def _broadcast_committed(user_id: str, result: Dict[str, Any]) -> None:
    """Tell the user's devices that the head moved (same event as the WebSocket commits)."""
    from backend.core.api.app.routes.websockets import manager

    await manager.broadcast_to_user(
        message={
            "type": "embed_revision_committed",
            "payload": {
                "embed_id": result["embed_id"],
                "current_revision": result.get("current_revision"),
                "current_content_hash": result.get("current_content_hash"),
                "revision_origin": "user",
                "revision_action": result.get("revision_action"),
            },
        },
        user_id=user_id,
    )


async def _repoint_media_index(
    directus_service: DirectusService, *, embed_id: str, user_id: str, media_index: MediaIndex,
) -> str | None:
    """Point the owner's image index row at the new head and restart its 24-hour window.

    Returns ``None`` on success, else the reason the row was left unchanged.
    The stored ``file_size_bytes`` is left as it is: storage of new files is
    accounted by the producer of those files (the Enhance task).
    """
    rows = await directus_service.get_items(
        "upload_files",
        params={"filter[embed_id][_eq]": embed_id, "filter[user_id][_eq]": user_id, "fields": "id", "limit": 2},
        no_cache=True, admin_required=True, raise_on_error=True,
    )
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return "media_index_not_found"
    update = {
        "files_metadata": media_index.files,
        "aes_nonce": media_index.aes_nonce,
        "vault_wrapped_aes_key": media_index.vault_wrapped_aes_key,
        # Never keep a plaintext file key of an earlier version on the row.
        "aes_key": None,
        "created_at": int(time.time()),
    }
    if media_index.content_type:
        update["content_type"] = media_index.content_type
    if not await directus_service.update_item("upload_files", rows[0]["id"], update, admin_required=True):
        logger.error("Image index of embed %s was not repointed after a user version", embed_id[:8])
        return "media_index_update_failed"
    return None


@router.post("/embeds/{embed_id}/user-revisions")
@limiter.limit("30/minute")
async def commit_user_embed_revision(
    request: Request,
    body: UserRevisionRequest,
    embed_id: str = Path(..., min_length=1, max_length=512),
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """Save a user's own edit, Enhance result or restore as the next version of the embed."""
    if body.scope.kind == "project":
        ensure_projects_enabled(request)
    if body.files and body.media_index is None:
        raise HTTPException(status_code=400, detail="media_index_required")
    if body.media_index is not None:
        if not body.files:
            raise HTTPException(status_code=400, detail="invalid_media_index")
        index_refs = _variant_refs(body.media_index)
        if body.files.head_file_keys and index_refs != {(ref.bucket, ref.key) for ref in body.files.head_file_keys}:
            raise HTTPException(status_code=400, detail="media_index_mismatch")
    data = body.model_dump(exclude_unset=True, exclude={"media_index"})
    data["embed_id"] = embed_id
    try:
        result = await EmbedVersionTransactionService(directus_service).commit_user_revision(
            data, user_id=current_user.id,
        )
    except EmbedVersionTransactionError as exc:
        if exc.code in STABLE_ERROR_CODES and 400 <= exc.status_code < 500:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
        raise HTTPException(status_code=500, detail="user_revision_failed") from exc
    if result["status"] == "conflict":
        raise HTTPException(status_code=409, detail={
            "code": "embed_version_conflict",
            "current_revision": result.get("current_revision"),
            "current_content_hash": result.get("current_content_hash"),
        })

    media_reason = None
    image = result.get("image")
    if body.media_index is not None:
        head_refs = {(ref["bucket"], ref["key"]) for ref in (image or {}).get("head_file_keys") or []}
        if not image or not head_refs:
            media_reason = "not_an_image_head"
        elif _variant_refs(body.media_index) != head_refs:
            media_reason = "media_index_mismatch"
        elif not image.get("owner_is_actor"):
            # The index row and its Vault-wrapped key belong to the embed's owner.
            media_reason = "not_owner"
        else:
            media_reason = await _repoint_media_index(
                directus_service, embed_id=embed_id, user_id=current_user.id, media_index=body.media_index,
            )
    await _forget_cached_embed(request, embed_id)
    if not result.get("idempotent"):
        await _broadcast_committed(current_user.id, result)
    return {
        "status": "committed",
        "operation_id": result["operation_id"],
        "embed_id": embed_id,
        "current_revision": result.get("current_revision"),
        "current_content_hash": result.get("current_content_hash"),
        "revision_origin": "user",
        "revision_action": result.get("revision_action"),
        "idempotent": bool(result.get("idempotent")),
        "pending_notice": bool(result.get("pending_notice")),
        "media_index_repointed": body.media_index is not None and media_reason is None,
        **({"media_index_reason": media_reason} if media_reason else {}),
    }


@router.get("/chats/{chat_id}/pending-embed-notices")
@limiter.limit("120/minute")
async def get_pending_embed_notices(
    request: Request,
    chat_id: str = Path(..., min_length=1, max_length=512),
    team_id: str | None = Query(default=None, min_length=1, max_length=512),
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
) -> Dict[str, Any]:
    """List user versions of this chat's embeds whose "embed updated" event is still unwritten."""
    if team_id:
        try:
            await directus_service.team.require_team_role(team_id, current_user.id, TEAM_WRITE_ROLES)
        except TeamPermissionError as exc:
            raise HTTPException(status_code=403, detail="forbidden") from exc
    metadata = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
    if not metadata:
        raise HTTPException(status_code=404, detail="chat_not_found")
    if team_id:
        if metadata.get("hashed_team_id") != _hash(team_id):
            raise HTTPException(status_code=404, detail="chat_not_found")
    elif metadata.get("hashed_team_id") or metadata.get("hashed_user_id") != _hash(current_user.id):
        raise HTTPException(status_code=404, detail="chat_not_found")
    return {"chat_id": chat_id, "notices": await list_pending_embed_notices(directus_service, chat_id=chat_id)}
