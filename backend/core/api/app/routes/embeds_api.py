# backend/core/api/app/routes/embeds_api.py
#
# External API endpoints for accessing embed files (images, PDFs, etc.).
# This router provides a unified endpoint for downloading files from embeds.
#
# Architecture:
# - Embeds can contain file references (e.g., generated images with S3 keys)
# - This endpoint decrypts the embed content using Vault, extracts file data,
#   and returns the decrypted file to the client
# - Used by both REST API clients and web app for downloading generated content
# - See docs/architecture/apps/images.md for image generation flow

import logging
import base64
import os
import io
import json
import re
import hashlib
from typing import Any
from fastapi import APIRouter, HTTPException, Request, Depends, Path, Query, Body
from fastapi.responses import StreamingResponse
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user,
    get_current_user_optional,
    get_current_user_or_api_key,
)
from backend.core.api.app.models.user import User
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/embeds", tags=["Embeds"])


# --- Dependencies to get services from app.state ---

def get_directus_service(request: Request) -> DirectusService:
    """Get DirectusService from app state."""
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_cache_service(request: Request):
    """Get the cache used for fresh Project focus and policy authorization."""
    if not hasattr(request.app.state, 'cache_service'):
        logger.error("CacheService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.cache_service


def get_encryption_service(request: Request) -> EncryptionService:
    """Get EncryptionService from app state."""
    if not hasattr(request.app.state, 'encryption_service'):
        logger.error("EncryptionService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.encryption_service


def get_s3_service(request: Request) -> S3UploadService:
    """Get S3UploadService from app state."""
    if not hasattr(request.app.state, 's3_service'):
        logger.error("S3UploadService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.s3_service


def _hash_value(value: str) -> str:
    """Create SHA256 hash of a value for privacy protection."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


async def _require_chat_embed_read(
    chat_id: str, team_id: str | None, current_user: User,
    directus_service: DirectusService,
) -> None:
    chat = directus_service.chat
    if team_id:
        try:
            await directus_service.team.require_team_role(
                team_id, current_user.id, {"owner", "admin", "member", "viewer"},
            )
        except TeamPermissionError as exc:
            raise HTTPException(status_code=404, detail="Chat not found") from exc
        metadata = await chat.get_chat_metadata(chat_id, admin_required=True)
        if not metadata or metadata.get("hashed_team_id") != _hash_value(team_id):
            raise HTTPException(status_code=404, detail="Chat not found")
    elif not await chat.check_chat_ownership(chat_id, current_user.id):
        raise HTTPException(status_code=404, detail="Chat not found")


_REFERENCE_PROBE_LIMIT = 20
_REFERENCE_PROBE_REQUEST_BYTES = 4 * 1024
_REFERENCE_PROBE_RESPONSE_BYTES = 8 * 1024


async def _reference_target_scope(
    chat_id: str, team_id: str | None, current_user: User,
    directus_service: DirectusService, *, write_required: bool = True,
) -> tuple[str, str, bool, bool]:
    """Check one existing or not-yet-created destination without cache authority."""
    if not re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    actor_hash = _hash_value(current_user.id)
    team_hash = _hash_value(team_id) if team_id else None
    if team_id:
        try:
            await directus_service.team.require_team_role(
                team_id, current_user.id,
                {"owner", "admin", "member"} if write_required
                else {"owner", "admin", "member", "viewer"},
            )
        except TeamPermissionError as exc:
            raise HTTPException(status_code=404, detail="Chat not found") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Reference authorization unavailable") from exc
    try:
        rows = await directus_service.get_items(
            "chats", params={"filter": {"id": {"_eq": chat_id}},
                             "fields": "id,hashed_user_id,hashed_team_id,storage_state", "limit": 2},
            no_cache=True, admin_required=True, raise_on_error=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Reference authorization unavailable") from exc
    if not isinstance(rows, list) or len(rows) > 1:
        raise HTTPException(status_code=503, detail="Reference authorization unavailable")
    if rows:
        row = rows[0]
        if (row.get("id") != chat_id or row.get("storage_state") == "deleting"
                or (row.get("hashed_team_id") or None) != team_hash
                or not team_hash and row.get("hashed_user_id") != actor_hash):
            raise HTTPException(status_code=404, detail="Chat not found")
    return _hash_value(chat_id), actor_hash, bool(team_id), bool(rows)


async def _reference_availability(
    embed_ids: list[str], chat_hash: str, actor_hash: str, is_team: bool,
    directus_service: DirectusService, *, team_target_live: bool = True,
) -> list[dict[str, str]]:
    """Read bounded metadata only; mask foreign heads unless a Team chat key grants access."""
    embed_filter = {"embed_id": {"_in": embed_ids}}
    try:
        heads = await directus_service.get_items(
            "embeds", params={"filter": embed_filter,
                              "fields": "embed_id,hashed_embed_id,hashed_user_id,hashed_chat_id,status",
                              "limit": _REFERENCE_PROBE_LIMIT + 1},
            no_cache=True, admin_required=True, raise_on_error=True,
        )
        ready_heads = await directus_service.get_items(
            "embeds", params={"filter": {**embed_filter,
                "encrypted_content": {"_nempty": True},
                "encrypted_type": {"_nempty": True}, "status": {"_eq": "finished"}},
                "fields": "embed_id", "limit": _REFERENCE_PROBE_LIMIT + 1},
            no_cache=True, admin_required=True, raise_on_error=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Reference lookup unavailable") from exc
    if (not isinstance(heads, list) or len(heads) > _REFERENCE_PROBE_LIMIT
            or not isinstance(ready_heads, list) or len(ready_heads) > _REFERENCE_PROBE_LIMIT):
        raise HTTPException(status_code=503, detail="Reference lookup unavailable")
    by_id = {row.get("embed_id"): row for row in heads if isinstance(row, dict)}
    if len(by_id) != len(heads):
        raise HTTPException(status_code=503, detail="Reference lookup unavailable")
    ready_ids = {row.get("embed_id") for row in ready_heads if isinstance(row, dict)}
    hashes = [row.get("hashed_embed_id") or _hash_value(embed_id)
              for embed_id, row in by_id.items() if embed_id in ready_ids]
    keys: list[dict[str, Any]] = []
    if hashes:
        chat_key = {"key_type": {"_eq": "chat"}, "hashed_chat_id": {"_eq": chat_hash}}
        if not is_team:
            chat_key["hashed_user_id"] = {"_eq": actor_hash}
        key_scope = chat_key if is_team else {"_or": [chat_key, {
            "key_type": {"_eq": "master"}, "hashed_user_id": {"_eq": actor_hash},
        }]}
        try:
            keys = await directus_service.get_items(
                "embed_keys", params={"filter": {
                    "hashed_embed_id": {"_in": hashes}, "encrypted_embed_key": {"_nempty": True},
                    **key_scope,
                }, "fields": "hashed_embed_id,hashed_user_id,hashed_chat_id,key_type",
                    "limit": 2 * _REFERENCE_PROBE_LIMIT + 1},
                no_cache=True, admin_required=True, raise_on_error=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Reference key lookup unavailable") from exc
        if not isinstance(keys, list) or len(keys) > 2 * _REFERENCE_PROBE_LIMIT:
            raise HTTPException(status_code=503, detail="Reference key lookup unavailable")
    key_hashes = {row.get("hashed_embed_id") for row in keys if isinstance(row, dict)}
    result: list[dict[str, str]] = []
    for embed_id in embed_ids:
        head = by_id.get(embed_id)
        own_head = bool(head and head.get("hashed_user_id") == actor_hash)
        embed_hash = (head.get("hashed_embed_id") or _hash_value(embed_id)) if head else None
        can_read = bool(head and embed_id in ready_ids and embed_hash in key_hashes
                        and (not is_team or team_target_live))
        state = "ready" if can_read and (is_team or own_head) else "unusable" if own_head else "missing"
        result.append({"embed_id": embed_id, "state": state})
    return result


@router.post("/chats/{chat_id}/references/availability")
@limiter.limit("120/minute")
async def get_embed_reference_availability(
    chat_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Tell a sender which references are readable without returning ciphertext."""
    ids = payload.get("embed_ids") if isinstance(payload, dict) and set(payload) == {"embed_ids"} else None
    if (not isinstance(ids, list) or not 1 <= len(ids) <= _REFERENCE_PROBE_LIMIT
            or any(not isinstance(value, str) or not value
                   or len(value.encode("utf-8")) > 512 for value in ids)
            or len(set(ids)) != len(ids)
            or len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > _REFERENCE_PROBE_REQUEST_BYTES):
        raise HTTPException(status_code=400, detail="Invalid embed reference probe")
    chat_hash, actor_hash, is_team, target_live = await _reference_target_scope(
        chat_id, team_id, current_user, directus_service,
    )
    results = await _reference_availability(
        ids, chat_hash, actor_hash, is_team, directus_service, team_target_live=target_live,
    )
    response = {"results": results}
    if len(json.dumps(response, separators=(",", ":")).encode("utf-8")) > _REFERENCE_PROBE_RESPONSE_BYTES:
        raise HTTPException(status_code=413, detail="Embed reference probe exceeds response limit")
    return response


@router.get("/chats/{chat_id}/window")
@limiter.limit("120/minute")
async def get_chat_embed_window(
    chat_id: str,
    request: Request,
    before_created_at: int | None = None,
    before_id: str | None = None,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Return one bounded ciphertext/key page after fresh Personal or Team access."""
    if (before_created_at is None) != (before_id is None) or (
        before_created_at is not None and before_created_at < 0
    ) or (before_id is not None and (not before_id or len(before_id) > 128)):
        raise HTTPException(status_code=400, detail="Invalid embed cursor")
    await _require_chat_embed_read(chat_id, team_id, current_user, directus_service)

    hashed_chat_id = _hash_value(chat_id)
    page = await directus_service.embed.get_embed_window_by_hashed_chat_id(
        hashed_chat_id, before_created_at=before_created_at, before_id=before_id,
    )
    rows = page["embeds"]
    hashes = [row.get("hashed_embed_id") or _hash_value(row["embed_id"])
              for row in rows if row.get("embed_id")]
    key_page = await directus_service.embed.get_sync_embed_key_window_for_page(
        hashed_chat_id, _hash_value(current_user.id), hashes,
    )
    return {
        "chat_id": chat_id,
        "embeds": rows,
        "embed_keys": key_page["embed_keys"],
        "embed_keys_has_more_after": key_page["has_more_after"],
        "embed_keys_end_cursor": key_page["end_cursor"],
        "oversized_embed_key_id": key_page["oversized_key_id"],
        "has_more_before": page["has_more_before"],
        "start_cursor": page["start_cursor"],
        "oversized_embed_id": page["oversized_embed_id"],
        "oversized_embed_cursor": page.get("oversized_embed_cursor"),
    }


@router.get("/chats/{chat_id}/keys/window")
@limiter.limit("120/minute")
async def get_chat_embed_key_window(
    chat_id: str,
    request: Request,
    embed_ids: str,
    after_key_id: str | None = None,
    key_id: str | None = None,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Continue wrappers for a checked embed page without exposing other chats' keys."""
    selected = embed_ids.split(",")
    if (not 1 <= len(selected) <= 30 or any(not value or len(value) > 128 for value in selected)
            or len(set(selected)) != len(selected) or after_key_id and key_id
            or any(value is not None and (not value or len(value) > 128) for value in (after_key_id, key_id))):
        raise HTTPException(status_code=400, detail="Invalid embed key cursor")
    await _require_chat_embed_read(chat_id, team_id, current_user, directus_service)
    hashed_chat_id = _hash_value(chat_id)
    try:
        hashes = await directus_service.embed.validate_embed_ids_in_chat(hashed_chat_id, selected)
    except ValueError:
        hashes = []
    if not hashes:
        scope_hash, actor_hash, is_team, target_live = await _reference_target_scope(
            chat_id, team_id, current_user, directus_service, write_required=False,
        )
        states = await _reference_availability(
            selected, scope_hash, actor_hash, is_team, directus_service,
            team_target_live=target_live,
        )
        if any(item["state"] != "ready" for item in states):
            raise HTTPException(status_code=404, detail="Embed page not found")
        hashes = [_hash_value(value) for value in selected]
    if not hashes:
        raise HTTPException(status_code=404, detail="Embed page not found")
    if key_id:
        key = await directus_service.embed.get_sync_embed_key_by_id(
            hashed_chat_id, _hash_value(current_user.id), hashes, key_id,
        )
        if not key:
            raise HTTPException(status_code=404, detail="Embed key not found")
        return {"embed_keys": [key], "has_more_after": False, "end_cursor": key_id,
                "oversized_key_id": None}
    page = await directus_service.embed.get_sync_embed_key_window_for_page(
        hashed_chat_id, _hash_value(current_user.id), hashes,
        after_key_id=after_key_id,
    )
    return {"embed_keys": page["embed_keys"], "has_more_after": page["has_more_after"],
            "end_cursor": page["end_cursor"], "oversized_key_id": page["oversized_key_id"]}


@router.get("/chats/{chat_id}/embeds/{embed_id}")
@limiter.limit("120/minute")
async def get_chat_embed_by_id(
    chat_id: str,
    embed_id: str,
    request: Request,
    team_id: str | None = None,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Load ciphertext only after current chat and readable-wrapper checks."""
    hashed_chat_id, actor_hash, is_team, target_live = await _reference_target_scope(
        chat_id, team_id, current_user, directus_service, write_required=False,
    )
    states = await _reference_availability(
        [embed_id], hashed_chat_id, actor_hash, is_team, directus_service,
        team_target_live=target_live,
    )
    if states[0]["state"] != "ready":
        raise HTTPException(status_code=404, detail="Embed not found")
    embed = await directus_service.embed.get_sync_embed_by_id(embed_id)
    if not embed or (not is_team and embed.get("hashed_user_id") != actor_hash):
        raise HTTPException(status_code=404, detail="Embed not found")
    key_page = await directus_service.embed.get_sync_embed_key_window_for_page(
        hashed_chat_id, actor_hash, [_hash_value(embed_id)],
        include_master_keys=not is_team,
    )
    if not key_page["embed_keys"] and not key_page["oversized_key_id"]:
        raise HTTPException(status_code=404, detail="Embed not found")
    return {"embed": embed, "embed_keys": key_page["embed_keys"],
            "embed_keys_has_more_after": key_page["has_more_after"],
            "embed_keys_end_cursor": key_page["end_cursor"],
            "oversized_embed_key_id": key_page["oversized_key_id"]}


async def _get_user_vault_key_id(directus_service: DirectusService, user_id: str) -> str:
    """Load the user's Vault key id needed to decrypt server-side version rows."""
    success, profile, error_msg = await directus_service.get_user_profile(user_id)
    if not success or not profile or not profile.get("vault_key_id"):
        logger.error("Failed to load vault_key_id for embed version request: %s", error_msg)
        raise HTTPException(status_code=500, detail="User encryption key not found")
    return profile["vault_key_id"]


async def _assert_embed_owner(
    embed_id: str,
    hashed_user_id: str,
    directus_service: DirectusService,
) -> dict:
    """Return embed metadata if the authenticated user owns it, else 404."""
    embed = await directus_service.embed.get_embed_by_id(embed_id)
    if not embed or embed.get("hashed_user_id") != hashed_user_id:
        raise HTTPException(status_code=404, detail="Embed not found")
    return embed


async def _authorize_version_read(
    embed_id: str,
    current_user: User,
    directus_service: DirectusService,
    project_id: str | None,
    team_id: str | None,
    chat_id: str | None,
) -> dict:
    """Resolve the stored owner only after checking live Project membership."""
    if team_id and not (project_id or chat_id):
        raise HTTPException(status_code=400, detail="Scoped context required")
    if project_id and chat_id:
        raise HTTPException(status_code=400, detail="Choose one version scope")
    if not project_id and not chat_id:
        return await _assert_embed_owner(embed_id, _hash_value(current_user.id), directus_service)
    if project_id:
        await _require_project_embed_access(
            directus_service=directus_service, user_id=current_user.id,
            project_id=project_id, embed_id=embed_id, team_id=team_id,
        )
    elif team_id:
        try:
            await directus_service.team.require_team_role(
                team_id, current_user.id, {"owner", "admin", "member", "viewer"},
            )
        except TeamPermissionError as exc:
            raise HTTPException(status_code=404, detail="Embed not found") from exc
        metadata = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
        if not metadata or metadata.get("hashed_team_id") != _hash_value(team_id):
            raise HTTPException(status_code=404, detail="Embed not found")
    elif not await directus_service.chat.check_chat_ownership(chat_id, current_user.id):
        raise HTTPException(status_code=404, detail="Embed not found")
    embed = await directus_service.embed.get_embed_by_id(embed_id)
    if (not embed or not isinstance(embed.get("hashed_user_id"), str)
            or chat_id and embed.get("hashed_chat_id") != _hash_value(chat_id)):
        raise HTTPException(status_code=404, detail="Embed not found")
    return embed


async def _read_version_rows(
    directus_service: DirectusService,
    embed_id: str,
    hashed_user_id: str,
    max_version: int | None = None,
    min_version: int | None = None,
    limit: int = 100,
    descending: bool = False,
    include_payload: bool = True,
) -> list[dict]:
    filters = {
        "embed_id": {"_eq": embed_id},
        "hashed_user_id": {"_eq": hashed_user_id},
    }
    if max_version is not None:
        filters["version_number"] = {"_lte": max_version}
    if min_version is not None:
        filters.setdefault("version_number", {})["_gte"] = min_version
    params = {
        "filter": filters,
        "fields": ("version_number,created_at,has_snapshot,has_patch,archive_state,"
                   "encrypted_snapshot,encrypted_patch,archive_object_key,archive_checksum"
                   if include_payload else "version_number,created_at,has_snapshot,has_patch,archive_state"),
        "sort": ["-version_number" if descending else "version_number"],
        "limit": limit,
    }
    if hasattr(directus_service, "read_items"):
        rows = await directus_service.read_items("embed_diffs", params=params)
    else:
        rows = await directus_service.get_items("embed_diffs", params=params)
    return list(rows or [])


def _version_meta(row: dict) -> dict:
    version = int(row["version_number"])
    return {
        "version_number": version,
        "created_at": row.get("created_at"),
        "has_snapshot": bool(row.get("has_snapshot")) or version == 1 or row.get("encrypted_snapshot") is not None,
        "has_patch": bool(row.get("has_patch")) or version > 1 or row.get("encrypted_patch") is not None,
        "archive_state": row.get("archive_state") or "hot",
    }


async def _require_project_embed_access(
    *,
    directus_service: DirectusService,
    user_id: str,
    project_id: str,
    embed_id: str,
    team_id: str | None,
) -> dict:
    """Require current Personal/Team Project and exact opaque item membership."""
    user_hash = _hash_value(user_id)
    team_hash = _hash_value(team_id) if team_id else None
    if team_id:
        try:
            await directus_service.team.require_team_role(
                team_id,
                user_id,
                {"owner", "admin", "member", "viewer"},
            )
        except TeamPermissionError as exc:
            raise HTTPException(status_code=404, detail="Project embed not found") from exc
    project = await directus_service.project.get_project(project_id, user_id, team_id=team_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project embed not found")
    params = {
        "filter[hashed_project_id][_eq]": _hash_value(project_id),
        "filter[target_id_hash][_eq]": _hash_value(embed_id),
        "filter[item_type][_in]": "embed,upload",
        "fields": "id",
        "limit": 1,
    }
    if team_hash:
        params["filter[hashed_team_id][_eq]"] = team_hash
        params["filter[hashed_user_id][_null]"] = True
    else:
        params["filter[hashed_user_id][_eq]"] = user_hash
        params["filter[hashed_team_id][_null]"] = True
    items = await directus_service.get_items(
        "project_items",
        params=params,
        no_cache=True,
        admin_required=True,
    )
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=404, detail="Project embed not found")
    return project


@router.get("/{embed_id}/encrypted")
@limiter.limit("120/minute")
async def get_encrypted_project_embed(
    embed_id: str,
    request: Request,
    project_id: str = Query(..., min_length=1),
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Return a fresh hosted-file ciphertext head to first-party clients only.

    This endpoint never decrypts content and returns only the wrapper bound to
    the requested Project. Private paths and plaintext content hashes are not
    part of the projection.
    """
    await _require_project_embed_access(
        directus_service=directus_service,
        user_id=current_user.id,
        project_id=project_id,
        embed_id=embed_id,
        team_id=team_id,
    )
    embed = await directus_service.embed.get_embed_by_id(embed_id)
    if not embed or embed.get("encryption_mode", "client") != "client":
        raise HTTPException(status_code=404, detail="Project embed not found")
    hashed_embed_id = _hash_value(embed_id)
    hashed_project_id = _hash_value(project_id)
    wrappers = await directus_service.get_items(
        "embed_keys",
        params={
            "filter[hashed_embed_id][_eq]": hashed_embed_id,
            "filter[key_type][_eq]": "project",
            "filter[hashed_project_id][_eq]": hashed_project_id,
            "fields": "hashed_embed_id,key_type,hashed_project_id,encrypted_embed_key,created_at",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    initial_rows = await directus_service.get_items(
        "embed_diffs",
        params={
            "filter[embed_id][_eq]": embed_id,
            "filter[version_number][_eq]": 1,
            "fields": "id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    safe_embed_fields = (
        "embed_id", "encrypted_type", "encrypted_content", "encrypted_text_preview",
        "encrypted_diff", "status", "version_number", "encryption_mode", "created_at", "updated_at",
    )
    return {
        "embed": {field: embed.get(field) for field in safe_embed_fields},
        "embed_keys": list(wrappers) if isinstance(wrappers, list) else [],
        "has_initial_history": isinstance(initial_rows, list) and bool(initial_rows),
    }


@router.get("/{embed_id}/revision-receipts/{operation_id}")
@limiter.limit("120/minute")
async def get_project_embed_revision_receipt(
    embed_id: str,
    request: Request,
    operation_id: str = Path(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    project_id: str = Query(..., min_length=1, max_length=512),
    chat_id: str = Query(..., min_length=1, max_length=512),
    proposal_digest: str = Query(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
    team_id: str | None = None,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Reconcile one exact committed operation without exposing its payload."""
    await _require_project_embed_access(
        directus_service=directus_service,
        user_id=current_user.id,
        project_id=project_id,
        embed_id=embed_id,
        team_id=team_id,
    )
    try:
        await ProjectWriteAuthorizationService(
            directus_service,
            get_cache_service(request),
        ).require_write_authorization(
            requester_user_id=current_user.id,
            chat_id=chat_id,
            project_id=project_id,
            operation_id=operation_id,
            proposal_digest=proposal_digest,
            team_id=team_id,
            consume_approval=False,
        )
    except ProjectWriteAuthorizationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    params = {
        "filter[embed_id][_eq]": embed_id,
        "filter[operation_id][_eq]": operation_id,
        "filter[hashed_project_id][_eq]": _hash_value(project_id),
        "filter[actor_user_hash][_eq]": _hash_value(current_user.id),
        "filter[hashed_chat_id][_eq]": _hash_value(chat_id),
        "filter[proposal_digest][_eq]": proposal_digest,
        "fields": "committed_revision",
        "limit": 1,
    }
    if team_id:
        params["filter[hashed_team_id][_eq]"] = _hash_value(team_id)
    else:
        params["filter[hashed_team_id][_null]"] = True
    receipts = await directus_service.get_items(
        "embed_version_commits",
        params=params,
        no_cache=True,
        admin_required=True,
    )
    if not isinstance(receipts, list) or not receipts:
        raise HTTPException(status_code=404, detail="Revision receipt not found")
    return {
        "status": "committed",
        "current_revision": receipts[0].get("committed_revision"),
    }


@router.get("/{embed_id}/versions")
@limiter.limit("120/minute")
async def list_embed_versions(
    embed_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    cursor: int = 0,
    limit: int = 100,
    order: str = "asc",
    project_id: str | None = None,
    team_id: str | None = None,
    chat_id: str | None = None,
):
    """List one stable metadata page; ciphertext is never part of timeline pages."""
    if cursor < 0 or not 1 <= limit <= 100 or order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Invalid version page")
    embed = await _authorize_version_read(embed_id, current_user, directus_service, project_id, team_id, chat_id)
    hashed_user_id = embed["hashed_user_id"]
    if order == "desc":
        rows = await _read_version_rows(
            directus_service, embed_id, hashed_user_id,
            max_version=(cursor - 1 if cursor else int(embed.get("version_number") or 1)),
            limit=limit + 1, descending=True, include_payload=False,
        )
    else:
        rows = await _read_version_rows(
            directus_service, embed_id, hashed_user_id, min_version=cursor + 1,
            limit=limit + 1, include_payload=False,
        )
    page = rows[:limit]
    versions = [_version_meta(row) for row in page]
    current_version = embed.get("version_number") or (versions[-1]["version_number"] if versions else 1)
    return {
        "embed_id": embed_id,
        "current_version": current_version,
        "versions": versions,
        "next_cursor": versions[-1]["version_number"] if len(rows) > limit else None,
        "readonly": False,
    }


@router.get("/{embed_id}/versions/{version_number}")
@limiter.limit("120/minute")
async def get_embed_version(
    embed_id: str,
    version_number: int,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    capability: str | None = None,
    project_id: str | None = None,
    team_id: str | None = None,
    chat_id: str | None = None,
):
    """Return encrypted rows needed to reconstruct an owned historical version client-side."""
    if version_number < 1:
        raise HTTPException(status_code=404, detail="Version not found")
    embed = await _authorize_version_read(embed_id, current_user, directus_service, project_id, team_id, chat_id)
    hashed_user_id = embed["hashed_user_id"]
    if capability == "bounded-v1":
        recent = await _read_version_rows(
            directus_service, embed_id, hashed_user_id, max_version=version_number,
            limit=33, descending=True, include_payload=False,
        )
        # Recovery must distinguish an absent target from an existing chain
        # that needs a client snapshot before it can be reconstructed.
        if not recent or recent[0].get("version_number") != version_number:
            raise HTTPException(status_code=404, detail="Version not found")
        nearest = next((row["version_number"] for row in recent if _version_meta(row)["has_snapshot"]), None)
        if nearest is None:
            raise HTTPException(status_code=409, detail="snapshot_required")
        rows = await _read_version_rows(
            directus_service, embed_id, hashed_user_id, min_version=nearest,
            max_version=version_number, limit=33,
        )
    else:
        # Legacy readers keep their source payloads and old reconstruction path.
        rows = []
        cursor = 1
        while cursor <= version_number:
            page = await _read_version_rows(
                directus_service, embed_id, hashed_user_id,
                min_version=cursor, max_version=version_number, limit=100,
            )
            if not page:
                break
            rows.extend(page)
            cursor = int(page[-1]["version_number"]) + 1
            if len(rows) > 10000:
                raise HTTPException(status_code=413, detail="Version chain exceeds legacy read budget")
    if not rows or rows[-1].get("version_number") != version_number:
        raise HTTPException(status_code=404, detail="Version not found")
    expected = int(rows[0]["version_number"])
    for row in rows:
        if row["version_number"] != expected:
            raise HTTPException(status_code=409, detail="Version chain is incomplete")
        expected += 1
        if row.get("archive_state") in {"reader_active", "pruned"}:
            from backend.core.api.app.services.embed_version_archive_service import read_archived_version
            try:
                archived = await read_archived_version(s3_service=get_s3_service(request), row=row)
                # A later snapshot publication may have raced a copy. Until
                # P-6 cutover, prefer the unchanged authoritative hot row.
                if any(row.get(field) and row[field] != archived.get(field) for field in (
                    "encrypted_snapshot", "encrypted_patch",
                )):
                    raise RuntimeError("Archived ciphertext is older than the hot row")
                row.update(archived)
            except Exception:
                if row.get("archive_state") == "pruned" or (
                    not row.get("encrypted_snapshot") and not row.get("encrypted_patch")
                ):
                    raise HTTPException(status_code=503, detail="Version archive temporarily unavailable")
        elif not row.get("encrypted_snapshot") and not row.get("encrypted_patch"):
            raise HTTPException(status_code=503, detail="Version source missing before reader activation")
    if not rows[0].get("encrypted_snapshot"):
        raise HTTPException(status_code=409, detail="Version chain has no starting snapshot")
    public_rows = [{
        "version_number": row["version_number"],
        "created_at": row.get("created_at"),
        "encrypted_snapshot": row.get("encrypted_snapshot"),
        "encrypted_patch": row.get("encrypted_patch"),
    } for row in rows]
    return {
        "embed_id": embed_id,
        "version_number": version_number,
        "current_version": embed.get("version_number") or version_number,
        "rows": public_rows,
        "bounded": capability == "bounded-v1",
        "readonly": False,
    }


@router.post("/{embed_id}/versions/{version_number}/snapshot")
@limiter.limit("20/minute")
async def publish_embed_version_snapshot(
    embed_id: str,
    version_number: int,
    request: Request,
    payload: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Publish a client-encrypted checkpoint with current authorization and a head fence."""
    if set(payload) - {"encrypted_snapshot", "expected_revision", "operation_id", "project_id", "team_id"}:
        raise HTTPException(status_code=400, detail="Invalid snapshot request")
    snapshot = payload.get("encrypted_snapshot")
    expected = payload.get("expected_revision")
    operation = payload.get("operation_id")
    if (not isinstance(snapshot, str) or not snapshot or len(snapshot.encode()) > 4 * 1024 * 1024
            or not isinstance(expected, int) or isinstance(expected, bool)
            or not isinstance(operation, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", operation)):
        raise HTTPException(status_code=400, detail="Invalid snapshot request")
    project_id = payload.get("project_id")
    team_id = payload.get("team_id")
    if project_id:
        await _require_project_embed_access(
            directus_service=directus_service, user_id=current_user.id,
            project_id=project_id, embed_id=embed_id, team_id=team_id,
        )
    else:
        await _assert_embed_owner(embed_id, _hash_value(current_user.id), directus_service)
    token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Snapshot publication unavailable")
    body = {
        "embed_id": embed_id, "version_number": version_number,
        "expected_revision": expected, "encrypted_snapshot": snapshot,
        "operation_id": operation, "actor_user_hash": _hash_value(current_user.id),
        "project_id": project_id, "team_id": team_id,
    }
    response = await directus_service._make_api_request(
        "POST", f"{directus_service.base_url.rstrip('/')}/embed-version-transaction/snapshots",
        headers={"X-Internal-Service-Token": token}, json=body,
    )
    result = response.json() if response.status_code == 200 else None
    if response.status_code != 200 or not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        raise HTTPException(status_code=response.status_code if response.status_code < 500 else 503,
                            detail="Snapshot publication failed")
    return result["data"]


@router.post("/{embed_id}/versions/{version_number}/restore")
@limiter.limit("30/minute")
async def restore_embed_version(
    embed_id: str,
    version_number: int,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Reject server-side restore; clients must reconstruct and encrypt restores."""
    del version_number, directus_service
    raise HTTPException(status_code=400, detail="Restore must be performed client-side with encrypted storage")


def _generate_filename_from_prompt(prompt: str | None, extension: str = "png") -> str:
    """
    Generate a clean, human-readable filename from an image generation prompt.

    Rules:
    - Lowercase, words separated by underscores
    - Only alphanumeric characters and underscores
    - Truncated to ~60 characters at a word boundary
    - Prefixed with "openmates_" for brand recognition
    - Falls back to "openmates_generated_image" if prompt is empty

    Args:
        prompt: The image generation prompt text
        extension: File extension without dot (e.g. "png", "webp")

    Returns:
        A sanitized filename string like "openmates_a_cat_sitting_on_a_windowsill.png"
    """
    if not prompt or not prompt.strip():
        return f"openmates_generated_image.{extension}"

    # Normalize: lowercase, replace non-alphanumeric with spaces, collapse whitespace
    slug = re.sub(r'[^a-z0-9\s]', ' ', prompt.lower())
    slug = re.sub(r'\s+', ' ', slug).strip()

    # Truncate to ~60 chars at a word boundary
    if len(slug) > 60:
        slug = slug[:60]
        last_space = slug.rfind(' ')
        if last_space > 20:
            slug = slug[:last_space]

    # Replace spaces with underscores, remove trailing underscores
    slug = slug.replace(' ', '_').rstrip('_')

    if not slug:
        return f"openmates_generated_image.{extension}"

    return f"openmates_{slug}.{extension}"


@router.get("/presigned-url")
@limiter.limit("120/minute")
async def get_presigned_url(
    request: Request,
    s3_key: str = Query(..., description="S3 object key for the encrypted file"),
    current_user: User | None = Depends(get_current_user_optional),
    s3_service: S3UploadService = Depends(get_s3_service),
):
    """
    Generate a presigned URL for downloading an encrypted file from S3.

    The chatfiles S3 bucket is private — files cannot be fetched without a
    presigned URL. This endpoint generates a short-lived (15-minute) presigned
    URL that the client uses to download the AES-256-GCM ciphertext, which it
    then decrypts locally using the Web Crypto API.

    Security model:
    - Authentication is optional so shared-chat visitors can render encrypted
      assets after decrypting a shared embed locally.
    - The presigned URL grants anonymous GET access to one S3 object for 15 minutes.
    - Even with the URL, the downloaded content is useless without the AES key
      (which lives only in the client-encrypted embed content in IndexedDB).
    - No embed ownership check is performed here — the client already proved it
      has the S3 key (which requires having decrypted the embed content locally).

    Args:
        s3_key: Full S3 object key (e.g. "user-uuid/hash/timestamp_original.bin").

    Returns:
        JSON with the presigned URL.

    Raises:
        400: Invalid or missing s3_key.
        500: Presigned URL generation failed.
    """
    user_label = current_user.id[:8] if current_user else "anonymous"
    log_prefix = f"[Presigned URL] [user:{user_label}...]"

    if not s3_key or not s3_key.strip():
        raise HTTPException(status_code=400, detail="s3_key is required")

    # Sanitise: S3 keys should not contain path traversal or protocol schemes
    if ".." in s3_key or s3_key.startswith("/") or "://" in s3_key:
        logger.warning(f"{log_prefix} Rejected suspicious s3_key: {s3_key[:80]}")
        raise HTTPException(status_code=400, detail="Invalid s3_key")

    try:
        environment = os.getenv("SERVER_ENVIRONMENT", "development")
        bucket_name = get_bucket_name("chatfiles", environment)
        presigned_url = s3_service.generate_presigned_url(
            bucket_name, s3_key, expiration=900  # 15 minutes
        )
        return {"url": presigned_url, "expires_in": 900}

    except Exception as e:
        logger.error(f"{log_prefix} Failed to generate presigned URL for {s3_key[:60]}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate presigned URL")


@router.get("/{embed_id}/file")
@limiter.limit("60/minute")
async def download_embed_file(
    embed_id: str,
    request: Request,
    format: str = Query("preview", description="File format to download: preview, full, or original"),
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    s3_service: S3UploadService = Depends(get_s3_service)
):
    """
    Download a file from an embed.
    
    This endpoint is used to download files from embeds, such as generated images.
    The server decrypts the file using Vault and returns the plaintext content.
    
    Args:
        embed_id: The unique identifier of the embed
        format: The file format to download (preview, full, or original)
                - preview: Scaled-down version for thumbnails (600x400)
                - full: Full-resolution WEBP for web display
                - original: Original PNG from provider
    
    Returns:
        StreamingResponse with the decrypted file content
    
    Raises:
        404: Embed not found or user doesn't have access
        400: Invalid format or embed doesn't contain files
        500: Decryption or download error
    """
    user_id = current_user.id
    hashed_user_id = _hash_value(user_id)
    log_prefix = f"[Embed: {embed_id[:8]}...]"
    
    logger.info(f"{log_prefix} Download request for format '{format}' by user {user_id[:8]}...")
    
    # Validate format parameter
    valid_formats = {"preview", "full", "original"}
    if format not in valid_formats:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid format '{format}'. Must be one of: {', '.join(valid_formats)}"
        )
    
    try:
        # 1. Fetch embed from Directus
        embed = await directus_service.embed.get_embed_by_id(embed_id)
        if not embed:
            logger.warning(f"{log_prefix} Embed not found")
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 2. Verify user ownership
        embed_hashed_user_id = embed.get("hashed_user_id")
        if embed_hashed_user_id != hashed_user_id:
            logger.warning(f"{log_prefix} Access denied: user hash mismatch")
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 3. Check encryption mode
        encryption_mode = embed.get("encryption_mode", "client")
        if encryption_mode != "vault":
            # For client-encrypted embeds, the server CANNOT decrypt the content.
            # (Note: Standard file uploads use a different flow, this router is for server-side files)
            raise HTTPException(
                status_code=400, 
                detail="This embed is client-side encrypted. The server cannot decrypt its files."
            )
        
        # 4. Get user's vault_key_id for decryption
        # Prefer the ID stored in the embed itself, fallback to user profile
        vault_key_id = embed.get("vault_key_id")
        if not vault_key_id:
            # get_user_profile returns (success, data, error_msg)
            success, user_profile, error_msg = await directus_service.get_user_profile(user_id)
            if not success or not user_profile:
                logger.error(f"{log_prefix} User profile not found: {error_msg}")
                raise HTTPException(status_code=500, detail="User profile not found")
            vault_key_id = user_profile.get("vault_key_id")
            
        if not vault_key_id:
            logger.error(f"{log_prefix} Vault key ID not found for user")
            raise HTTPException(status_code=500, detail="User encryption key not found")
        
        # 5. Decrypt embed content using Vault
        encrypted_content = embed.get("encrypted_content")
        if not encrypted_content:
            logger.warning(f"{log_prefix} Embed has no encrypted_content")
            raise HTTPException(status_code=400, detail="Embed does not contain file data")
        
        decrypted_content_str = await encryption_service.decrypt_with_user_key(
            encrypted_content, vault_key_id
        )
        if not decrypted_content_str:
            logger.error(f"{log_prefix} Failed to decrypt embed content")
            raise HTTPException(status_code=500, detail="Failed to decrypt embed content")
        
        # 5. Parse embed content JSON
        try:
            embed_content = json.loads(decrypted_content_str)
        except json.JSONDecodeError as e:
            logger.error(f"{log_prefix} Failed to parse embed content JSON: {e}")
            raise HTTPException(status_code=500, detail="Invalid embed content format")
        
        # 6. Verify this is a file-containing embed
        embed_type = embed_content.get("type")
        if embed_type != "image":
            logger.warning(f"{log_prefix} Embed type '{embed_type}' does not support file downloads")
            raise HTTPException(status_code=400, detail="This embed type does not contain downloadable files")
        
        files = embed_content.get("files")
        if not files:
            logger.warning(f"{log_prefix} Embed has no files metadata")
            raise HTTPException(status_code=400, detail="Embed does not contain file data")
        
        # 7. Get file metadata for requested format
        file_metadata = files.get(format)
        if not file_metadata:
            available_formats = list(files.keys())
            logger.warning(f"{log_prefix} Format '{format}' not found. Available: {available_formats}")
            raise HTTPException(
                status_code=400, 
                detail=f"Format '{format}' not available. Available formats: {', '.join(available_formats)}"
            )
        
        s3_key = file_metadata.get("s3_key")
        file_format = file_metadata.get("format", "webp")
        
        if not s3_key:
            logger.error(f"{log_prefix} No S3 key in file metadata for format '{format}'")
            raise HTTPException(status_code=500, detail="File storage reference missing")
        
        # 8. Get AES key and nonce for file decryption
        encrypted_aes_key = embed_content.get("encrypted_aes_key")
        aes_nonce_b64 = embed_content.get("aes_nonce")
        
        if not encrypted_aes_key or not aes_nonce_b64:
            logger.error(f"{log_prefix} Missing AES encryption data in embed content")
            raise HTTPException(status_code=500, detail="File encryption data missing")
        
        # 9. Decrypt AES key using Vault
        aes_key_b64 = await encryption_service.decrypt_with_user_key(
            encrypted_aes_key, vault_key_id
        )
        if not aes_key_b64:
            logger.error(f"{log_prefix} Failed to decrypt AES key")
            raise HTTPException(status_code=500, detail="Failed to decrypt file access key")
        
        # 10. Download encrypted file from S3
        bucket_name = get_bucket_name('chatfiles', os.getenv('SERVER_ENVIRONMENT', 'development'))
        logger.info(f"{log_prefix} Downloading from S3: {s3_key}")
        
        encrypted_data = await s3_service.get_file(bucket_name=bucket_name, object_key=s3_key)
        if not encrypted_data:
            logger.error(f"{log_prefix} File not found in S3: {s3_key}")
            raise HTTPException(status_code=404, detail="File not found in storage")
        
        # 11. Decrypt file content
        try:
            aes_key = base64.b64decode(aes_key_b64)
            nonce = base64.b64decode(aes_nonce_b64)
            aesgcm = AESGCM(aes_key)
            decrypted_content = aesgcm.decrypt(nonce, encrypted_data, None)
        except Exception as e:
            logger.error(f"{log_prefix} File decryption failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to decrypt file content")
        
        # 12. Determine content type and filename.
        # SVG files are served with the correct XML-based MIME type so browsers and
        # design tools recognise them as scalable vector graphics.
        content_type_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "svg": "image/svg+xml",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
            "ogg": "audio/ogg",
        }
        content_type = content_type_map.get(file_format, "application/octet-stream")

        # Generate a human-readable filename from the prompt (if available in embed content)
        embed_prompt = embed_content.get("prompt")
        filename = _generate_filename_from_prompt(embed_prompt, file_format)
        
        logger.info(f"{log_prefix} Successfully decrypted {len(decrypted_content)} bytes, serving as {content_type}")
        
        # 13. Stream response to client
        # Use "attachment" disposition so browsers trigger a download with the proper filename.
        # Quote the filename per RFC 6266 for safety with special characters.
        return StreamingResponse(
            io.BytesIO(decrypted_content),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, max-age=3600"  # Cache for 1 hour
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error during file download: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during file download")


@router.get("/{embed_id}/content")
@limiter.limit("60/minute")
async def get_embed_content(
    embed_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Get the decrypted content (metadata) of an embed.
    
    For embeds with encryption_mode='vault', this endpoint allows the client to
    fetch the decrypted JSON metadata (like the prompt for a generated image).
    
    Args:
        embed_id: The unique identifier of the embed
        
    Returns:
        The decrypted embed content as a JSON object
    """
    user_id = current_user.id
    hashed_user_id = _hash_value(user_id)
    log_prefix = f"[Embed: {embed_id[:8]}...]"
    
    try:
        # 1. Fetch embed from Directus
        embed = await directus_service.embed.get_embed_by_id(embed_id)
        if not embed:
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 2. Verify user ownership
        if embed.get("hashed_user_id") != hashed_user_id:
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 3. Check encryption mode
        encryption_mode = embed.get("encryption_mode", "client")
        if encryption_mode != "vault":
            # For client-encrypted embeds, the server CANNOT decrypt the content.
            # The client must use the embed_key from the embed_keys collection.
            raise HTTPException(
                status_code=400, 
                detail="This embed is client-side encrypted. The server cannot decrypt its content."
            )
        
        # 4. Get user's vault_key_id for decryption
        # Prefer the ID stored in the embed itself, fallback to user profile
        vault_key_id = embed.get("vault_key_id")
        if not vault_key_id:
            success, user_profile, error_msg = await directus_service.get_user_profile(user_id)
            if not success or not user_profile:
                logger.error(f"{log_prefix} User profile not found: {error_msg}")
                raise HTTPException(status_code=500, detail="User profile not found")
            vault_key_id = user_profile.get("vault_key_id")
            
        if not vault_key_id:
            raise HTTPException(status_code=500, detail="User encryption key not found")
        
        # 5. Decrypt embed content using Vault
        encrypted_content = embed.get("encrypted_content")
        if not encrypted_content:
            raise HTTPException(status_code=400, detail="Embed does not contain content")
        
        decrypted_content_str = await encryption_service.decrypt_with_user_key(
            encrypted_content, vault_key_id
        )
        if not decrypted_content_str:
            raise HTTPException(status_code=500, detail="Failed to decrypt embed content")
        
        # 6. Parse and return
        try:
            return json.loads(decrypted_content_str)
        except json.JSONDecodeError:
            return {"raw_content": decrypted_content_str}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Error getting decrypted embed content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to decrypt embed content")
