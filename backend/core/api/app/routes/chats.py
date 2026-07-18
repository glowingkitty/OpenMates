"""Session-authenticated encrypted chat reads for first-party clients.

The routes expose only the encrypted metadata required by native chat lists and
threads. They reuse cookie authentication and Directus ownership checks, never
decrypt content server-side, and return the same 404 for missing or foreign
chats to avoid existence disclosure.
"""

import json
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.team_workspace_service import TeamWorkspaceMoveError, move_workspace_record_to_team


router = APIRouter(prefix="/v1", tags=["Chats"])
NATIVE_CHAT_SORT = "-pinned,-last_edited_overall_timestamp"


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
