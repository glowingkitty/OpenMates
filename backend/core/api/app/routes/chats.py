"""Session-authenticated encrypted chat reads for first-party clients.

The routes expose only the encrypted metadata required by native chat lists and
threads. They reuse cookie authentication and Directus ownership checks, never
decrypt content server-side, and return the same 404 for missing or foreign
chats to avoid existence disclosure.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User


router = APIRouter(prefix="/v1", tags=["Chats"])
NATIVE_CHAT_SORT = "-pinned,-last_edited_overall_timestamp"


def _string_timestamp(value: Any) -> str | None:
    return str(value) if value is not None else None


def _watch_chat_payload(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": chat.get("id"),
        "encrypted_title": chat.get("encrypted_title"),
        "encrypted_chat_summary": chat.get("encrypted_chat_summary"),
        "encrypted_chat_key": chat.get("encrypted_chat_key"),
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
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    chats = await request.app.state.directus_service.chat.get_user_chats_metadata(
        current_user.id,
        limit=limit,
        offset=0,
        sort=NATIVE_CHAT_SORT,
    )
    return {"chats": [_watch_chat_payload(chat) for chat in chats], "limit": limit}


@router.get("/chats/{chat_id}/messages")
async def list_chat_messages(
    chat_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    chat_service = request.app.state.directus_service.chat
    if not await chat_service.check_chat_ownership(chat_id, current_user.id):
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = await chat_service.get_all_messages_for_chat(chat_id, decrypt_content=False)
    records = [_message_record(message) for message in messages or []]
    return [_watch_message_payload(record) for record in records if record is not None]
