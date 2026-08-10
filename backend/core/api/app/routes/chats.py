"""Session-authenticated encrypted chat reads for first-party clients.

The routes expose only the encrypted metadata required by native chat lists and
threads. They reuse cookie authentication and Directus ownership checks, never
decrypt content server-side, and return the same 404 for missing or foreign
chats to avoid existence disclosure.
"""

import json
import hashlib
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.handlers.websocket_handlers.get_draft_versions_handler import get_authoritative_user_draft
from backend.core.api.app.routes.sdk import (
    SdkChatForkRequest,
    SdkChatRewindRequest,
    _invalidate_rewound_chat_state,
    _load_owned_personal_sdk_chat,
    _message_slice_through_boundary,
    _sdk_message_id,
    _sdk_message_row_id,
    _validate_encrypted_fork_payload,
    _validate_encrypted_message_for_chat,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.team_workspace_service import TeamWorkspaceMoveError, move_workspace_record_to_team


router = APIRouter(prefix="/v1", tags=["Chats"])
NATIVE_CHAT_SORT = "-pinned,-last_edited_overall_timestamp"
CHAT_COMPRESSION_CHECKPOINT_COLLECTION = "chat_compression_checkpoints"
DEFAULT_MESSAGE_WINDOW_LIMIT = 30
MAX_MESSAGE_WINDOW_LIMIT = 100


class ChatMoveRequest(BaseModel):
    team_id: str
    confirmed: bool
    moved_at: int | None = None


def _string_timestamp(value: Any) -> str | None:
    return str(value) if value is not None else None


def _watch_chat_payload(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": chat.get("id"),
        "encrypted_title": chat.get("encrypted_title"),
        "encrypted_chat_summary": chat.get("encrypted_chat_summary"),
        "encrypted_chat_key": chat.get("encrypted_chat_key"),
        "chat_key_wrappers": chat.get("chat_key_wrappers") or [],
        "pinned": chat.get("pinned", False),
        "updated_at": _string_timestamp(chat.get("updated_at")),
        "last_message_at": _string_timestamp(chat.get("last_message_timestamp")),
    }


def _watch_message_payload(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message.get("id") or message.get("client_message_id"),
        "chat_id": message.get("chat_id"),
        "role": message.get("role"),
        "encrypted_content": message.get("encrypted_content"),
        "created_at": _string_timestamp(message.get("created_at")) or "",
    }


def _message_record(message: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(message, dict):
        return message
    try:
        decoded = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _encrypted_message_payload(message: str | dict[str, Any]) -> dict[str, Any] | None:
    record = _message_record(message)
    if record is None:
        return None
    record.pop("content", None)
    record.pop("text", None)
    record["message_id"] = record.get("message_id") or record.get("client_message_id") or record.get("id")
    return record


async def _require_chat_read_access(request: Request, chat_id: str, team_id: str | None, user_id: str) -> dict[str, Any] | None:
    chat_service = request.app.state.directus_service.chat
    if team_id:
        try:
            await request.app.state.directus_service.team.require_team_role(team_id, user_id, {"owner", "admin", "member", "viewer"})
        except TeamPermissionError as exc:
            raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
        chat = await chat_service.get_chat_metadata(chat_id, admin_required=True)
        if not chat or chat.get("hashed_team_id") != hash_id(team_id):
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat
    if not await chat_service.check_chat_ownership(chat_id, user_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return await chat_service.get_chat_metadata(chat_id, admin_required=True)


async def _get_chat_compression_checkpoints(request: Request, chat_id: str) -> list[dict[str, Any]]:
    rows = await request.app.state.directus_service.get_items(
        CHAT_COMPRESSION_CHECKPOINT_COLLECTION,
        params={
            "filter": {"chat_id": {"_eq": chat_id}},
            "fields": "id,chat_id,encrypted_summary,compressed_up_to_timestamp,compressed_message_count,summary_token_estimate,key_version,created_at,updated_at",
            "sort": "created_at",
            "limit": -1,
        },
        admin_required=True,
    )
    return rows if isinstance(rows, list) else []


def _latest_compression_boundary(checkpoints: list[dict[str, Any]]) -> int | None:
    boundary = None
    for checkpoint in checkpoints:
        try:
            candidate = int(checkpoint.get("compressed_up_to_timestamp") or 0)
        except (TypeError, ValueError):
            continue
        boundary = max(boundary or candidate, candidate)
    return boundary


@router.get("/chats")
async def list_chats(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    team_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if team_id:
        try:
            await request.app.state.directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})
        except TeamPermissionError as exc:
            raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
    chats = await request.app.state.directus_service.chat.get_user_chats_metadata(
        current_user.id,
        limit=limit,
        offset=0,
        sort=NATIVE_CHAT_SORT,
        admin_required=True,
        team_id=team_id,
    )
    hashed_chat_ids = [
        hashlib.sha256(str(chat.get("id")).encode()).hexdigest()
        for chat in chats
        if chat.get("id")
    ]
    wrappers = await request.app.state.directus_service.chat_key_wrapper.get_wrappers_by_hashed_chat_ids_batch(
        hashed_chat_ids,
        hashed_user_id=hashlib.sha256(current_user.id.encode()).hexdigest(),
    )
    wrappers_by_hash: dict[str, list[dict[str, Any]]] = {}
    for wrapper in wrappers:
        hashed_chat_id = wrapper.get("hashed_chat_id")
        if isinstance(hashed_chat_id, str):
            wrappers_by_hash.setdefault(hashed_chat_id, []).append(wrapper)
    for chat in chats:
        chat_id = chat.get("id")
        if chat_id:
            chat["chat_key_wrappers"] = wrappers_by_hash.get(hashlib.sha256(str(chat_id).encode()).hexdigest(), [])
    return {"chats": [_watch_chat_payload(chat) for chat in chats], "limit": limit}


@router.get("/chats/{chat_id}/messages")
async def list_chat_messages(
    chat_id: str,
    request: Request,
    team_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    chat_service = request.app.state.directus_service.chat
    if team_id:
        try:
            await request.app.state.directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})
        except TeamPermissionError as exc:
            raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
        chat = await chat_service.get_chat_metadata(chat_id, admin_required=True)
        if not chat or chat.get("hashed_team_id") != hash_id(team_id):
            raise HTTPException(status_code=404, detail="Chat not found")
    elif not await chat_service.check_chat_ownership(chat_id, current_user.id):
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = await chat_service.get_all_messages_for_chat(chat_id, decrypt_content=False)
    records = [_message_record(message) for message in messages or []]
    return [_watch_message_payload(record) for record in records if record is not None]


@router.get("/chats/{chat_id}/messages/window")
async def get_chat_message_window(
    chat_id: str,
    request: Request,
    direction: Literal["latest", "before", "after", "around"] = Query(default="latest"),
    limit: int = Query(default=DEFAULT_MESSAGE_WINDOW_LIMIT, ge=1, le=MAX_MESSAGE_WINDOW_LIMIT),
    before_timestamp: int | None = Query(default=None),
    before_message_id: str | None = Query(default=None),
    after_timestamp: int | None = Query(default=None),
    after_message_id: str | None = Query(default=None),
    anchor_message_id: str | None = Query(default=None),
    respect_compression_boundary: bool = Query(default=True),
    team_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a bounded first-party encrypted viewing window; sync APIs stay full-history."""
    chat = await _require_chat_read_access(request, chat_id, team_id, current_user.id)
    checkpoints = await _get_chat_compression_checkpoints(request, chat_id)
    compression_boundary_timestamp = _latest_compression_boundary(checkpoints)
    lower_bound_timestamp = compression_boundary_timestamp if respect_compression_boundary else None
    window = await request.app.state.directus_service.chat.get_message_window_for_chat(
        chat_id=chat_id,
        direction=direction,
        limit=limit,
        before_timestamp=before_timestamp,
        before_message_id=before_message_id,
        after_timestamp=after_timestamp,
        after_message_id=after_message_id,
        anchor_message_id=anchor_message_id,
        lower_bound_timestamp=lower_bound_timestamp,
    )
    messages = [_encrypted_message_payload(message) for message in window.get("messages", [])]
    server_message_count = None
    try:
        server_message_count = await request.app.state.directus_service.chat.get_message_count_for_chat(chat_id)
    except Exception:
        server_message_count = None
    if server_message_count is None and chat:
        server_message_count = chat.get("messages_v")
    return {
        "chat_id": chat_id,
        "messages": [message for message in messages if message is not None],
        "has_more_before": bool(window.get("has_more_before")),
        "has_more_after": bool(window.get("has_more_after")),
        "start_cursor": window.get("start_cursor"),
        "end_cursor": window.get("end_cursor"),
        "anchor_found": bool(window.get("anchor_found", True)),
        "server_message_count": server_message_count,
        "messages_v": chat.get("messages_v") if chat else None,
        "compression_boundary_timestamp": compression_boundary_timestamp,
        "compression_checkpoints": checkpoints,
        "respect_compression_boundary": respect_compression_boundary,
    }


@router.post("/chats/{chat_id}/fork")
async def fork_chat(
    chat_id: str,
    body: SdkChatForkRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Persist a zero-knowledge personal-chat fork for first-party clients."""
    if body.protocol_version != 1:
        raise HTTPException(status_code=426, detail={"error": "client_update_required"})

    _source_chat, source_messages, hashed_user_id = await _load_owned_personal_sdk_chat(request, chat_id, current_user.id)
    _boundary_index, source_slice = _message_slice_through_boundary(source_messages, body.from_message_id)
    chat_metadata = _validate_encrypted_fork_payload(body, len(source_slice), hashed_user_id)
    try:
        created_chat, existed = await request.app.state.directus_service.chat.create_chat_in_directus(chat_metadata)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "encrypted_history_required"}) from exc
    if existed:
        raise HTTPException(status_code=409, detail={"error": "chat_already_exists"})
    if not created_chat:
        raise HTTPException(status_code=502, detail={"error": "fork_persist_failed"})

    for encrypted_message in body.encrypted_messages:
        message_payload = _validate_encrypted_message_for_chat(encrypted_message, body.new_chat_id, hashed_user_id)
        try:
            stored = await request.app.state.directus_service.chat.create_message_in_directus(message_payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": "encrypted_history_required"}) from exc
        if not stored:
            raise HTTPException(status_code=502, detail={"error": "fork_persist_failed"})

    return {
        "success": True,
        "source_chat_id": chat_id,
        "chat_id": body.new_chat_id,
        "copied_message_count": len(body.encrypted_messages),
        "messages_v": len(body.encrypted_messages),
    }


@router.post("/chats/{chat_id}/rewind")
async def rewind_chat(
    chat_id: str,
    body: SdkChatRewindRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete encrypted message rows after a boundary for first-party clients."""
    if body.protocol_version != 1:
        raise HTTPException(status_code=426, detail={"error": "client_update_required"})

    chat, messages, hashed_user_id = await _load_owned_personal_sdk_chat(request, chat_id, current_user.id)
    current_messages_v = int(chat.get("messages_v") or 0)
    if current_messages_v != body.expected_messages_v:
        raise HTTPException(status_code=409, detail={"error": "version_conflict"})
    boundary_index, _source_slice = _message_slice_through_boundary(messages, body.to_message_id)
    remaining_messages_v = boundary_index + 1
    tail = messages[remaining_messages_v:]
    planned_deleted_ids = [_sdk_message_id(row) for row in tail]

    if body.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "chat_id": chat_id,
            "to_message_id": body.to_message_id,
            "planned_deleted_message_ids": planned_deleted_ids,
            "planned_deleted_message_count": len(tail),
            "messages_v": current_messages_v,
            "resulting_messages_v": remaining_messages_v,
        }
    if not body.confirm_destructive:
        raise HTTPException(status_code=400, detail={"error": "destructive_confirmation_required"})

    invalidation = await _invalidate_rewound_chat_state(request, current_user.id, hashed_user_id, chat_id, remaining_messages_v)
    tail_row_ids = [_sdk_message_row_id(row) for row in tail if _sdk_message_row_id(row)]
    if tail_row_ids:
        deleted = await request.app.state.directus_service.bulk_delete_items("messages", tail_row_ids)
        if not deleted:
            raise HTTPException(status_code=502, detail={"error": "rewind_delete_failed"})

    update_fields: dict[str, Any] = {"messages_v": remaining_messages_v}
    boundary_created_at = messages[boundary_index].get("created_at")
    if isinstance(boundary_created_at, int):
        update_fields["last_edited_overall_timestamp"] = boundary_created_at
    updated = await request.app.state.directus_service.update_item("chats", chat_id, update_fields)
    if not updated:
        raise HTTPException(status_code=502, detail={"error": "rewind_version_update_failed"})

    return {
        "success": True,
        "dry_run": False,
        "chat_id": chat_id,
        "to_message_id": body.to_message_id,
        "deleted_message_ids": planned_deleted_ids,
        "deleted_message_count": len(tail),
        "messages_v": remaining_messages_v,
        "invalidation": invalidation,
    }


@router.get("/drafts/{chat_id}")
async def get_draft(
    chat_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    draft = await get_authoritative_user_draft(
        request.app.state.cache_service,
        request.app.state.directus_service,
        current_user.id,
        chat_id,
    )
    if not draft:
        return {"draft": None}
    encrypted_md, draft_v, encrypted_preview = draft
    return {"draft": {
        "chat_id": chat_id,
        "encrypted_draft_md": encrypted_md,
        "encrypted_draft_preview": encrypted_preview,
        "draft_v": int(draft_v),
    }}


@router.post("/chats/{chat_id}/move")
async def move_chat_to_team(
    chat_id: str,
    body: ChatMoveRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        chat = await move_workspace_record_to_team(
            directus_service=request.app.state.directus_service,
            actor_user_id=current_user.id,
            team_id=body.team_id,
            workspace_type="chat",
            object_id=chat_id,
            confirmed=body.confirmed,
            moved_at=body.moved_at,
        )
    except TeamPermissionError as exc:
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
    except TeamWorkspaceMoveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"chat": _watch_chat_payload(chat)}
