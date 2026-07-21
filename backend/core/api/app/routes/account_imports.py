"""Account Import V1 API routes.

Routes in this module are control-plane endpoints for previewing, transiently
scanning, and completing imports. They must not persist plaintext imported chat,
message, or embed content; encrypted persistence is performed by clients.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.services.account_import_service import AccountImportService, ImportScanError
from backend.core.api.app.services.limiter import limiter


router = APIRouter(prefix="/v1/account-imports", tags=["Account Imports"])

MAX_IMPORT_PREVIEW_CHATS = 500
MAX_IMPORT_SCAN_CHATS = 500
MAX_IMPORT_PERSIST_CHATS = 500
MAX_IMPORT_MESSAGES_PER_CHAT = 10_000


class ScanImportRequest(BaseModel):
    chats: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_IMPORT_SCAN_CHATS)


class PreviewImportRequest(BaseModel):
    source: str
    chat_count: int = Field(ge=0, le=MAX_IMPORT_PREVIEW_CHATS)
    source_fingerprints: list[str] = Field(default_factory=list, max_length=MAX_IMPORT_PREVIEW_CHATS)
    estimated_tokens: int = Field(default=0, ge=0)
    estimated_bytes: int = Field(default=0, ge=0)


class CompleteImportRequest(BaseModel):
    imported_chat_ids: list[str] = Field(default_factory=list, max_length=MAX_IMPORT_PERSIST_CHATS)
    source_fingerprints: list[str] = Field(default_factory=list, max_length=MAX_IMPORT_PERSIST_CHATS)
    encrypted_record_counts: dict[str, int] = Field(default_factory=dict, max_length=16)
    client_failures: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_IMPORT_PERSIST_CHATS)


class PersistEncryptedMessage(BaseModel):
    message_id: str
    role: str
    encrypted_content: str
    encrypted_sender_name: str | None = None
    created_at: int
    updated_at: int | None = None
    user_message_id: str | None = None


class PersistEncryptedChat(BaseModel):
    chat_id: str
    encrypted_title: str
    encrypted_chat_key: str
    created_at: int
    updated_at: int
    source_fingerprint: str
    messages: list[PersistEncryptedMessage] = Field(default_factory=list, max_length=MAX_IMPORT_MESSAGES_PER_CHAT)


class PersistEncryptedImportRequest(BaseModel):
    chats: list[PersistEncryptedChat] = Field(default_factory=list, max_length=MAX_IMPORT_PERSIST_CHATS)


def get_account_import_service(
    request: Request,
) -> AccountImportService:
    if not hasattr(request.app.state, "account_import_jobs"):
        request.app.state.account_import_jobs = {}
    return AccountImportService(directus_service=request.app.state.directus_service)


async def get_current_user_info(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
) -> dict[str, Any]:
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key

    current_user = await get_current_user_or_api_key(
        request=request,
        response=response,
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=refresh_token,
    )
    return {"user_id": current_user.id, "credits": int(current_user.credits or 0)}


@router.post("/preview")
@limiter.limit("20/minute")
async def preview_import(
    request: Request,
    payload: PreviewImportRequest,
    service: AccountImportService = Depends(get_account_import_service),
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    del request
    synthetic_chats = [
        {"source_fingerprint": fingerprint, "messages": []}
        for fingerprint in payload.source_fingerprints[: payload.chat_count]
    ]
    while len(synthetic_chats) < payload.chat_count:
        synthetic_chats.append({"source_fingerprint": f"unknown-{len(synthetic_chats)}", "messages": []})
    return await service.preview_import(
        user_id=str(user_info["user_id"]),
        source=payload.source,
        chats=synthetic_chats,
        available_credits=int(user_info.get("credits") or 0),
        imported_count_last_30_days=0,
        existing_fingerprints=set(),
    )


@router.post("/{import_id}/scan")
@limiter.limit("10/minute")
async def scan_import(
    import_id: str,
    request: Request,
    payload: ScanImportRequest,
    service: AccountImportService = Depends(get_account_import_service),
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    del request
    user_id = str(user_info.get("user_id") or user_info.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return await service.scan_selected_chats(user_id=user_id, import_id=import_id, chats=payload.chats)
    except ImportScanError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{import_id}/complete")
@limiter.limit("20/minute")
async def complete_import(
    import_id: str,
    request: Request,
    payload: CompleteImportRequest,
    service: AccountImportService = Depends(get_account_import_service),
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    del request
    return await service.complete_import(
        user_id=str(user_info["user_id"]),
        import_id=import_id,
        imported_chat_ids=payload.imported_chat_ids,
        source_fingerprints=payload.source_fingerprints,
        encrypted_record_counts=payload.encrypted_record_counts,
        client_failures=payload.client_failures,
    )


@router.post("/{import_id}/persist-encrypted")
@limiter.limit("10/minute")
async def persist_encrypted_import(
    import_id: str,
    payload: PersistEncryptedImportRequest,
    request: Request,
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    del import_id
    user_id = str(user_info["user_id"])
    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
    directus_service = request.app.state.directus_service
    imported_chat_ids: list[str] = []
    failures: list[dict[str, Any]] = []
    for chat in payload.chats:
        try:
            created_chat, is_duplicate = await directus_service.chat.create_chat_in_directus({
                "id": chat.chat_id,
                "hashed_user_id": hashed_user_id,
                "created_at": chat.created_at,
                "updated_at": chat.updated_at,
                "messages_v": len(chat.messages),
                "title_v": 1,
                "metadata_v": 1,
                "last_edited_overall_timestamp": chat.updated_at,
                "last_message_timestamp": chat.updated_at,
                "unread_count": 0,
                "encrypted_title": chat.encrypted_title,
                "encrypted_chat_key": chat.encrypted_chat_key,
            })
            if not created_chat and not is_duplicate:
                failures.append({"chat_id": chat.chat_id, "reason": "chat_create_failed"})
                continue
            for message in chat.messages:
                created_message = await directus_service.chat.create_message_in_directus({
                    "id": message.message_id,
                    "chat_id": chat.chat_id,
                    "hashed_user_id": hashed_user_id,
                    "role": message.role,
                    "encrypted_content": message.encrypted_content,
                    "encrypted_sender_name": message.encrypted_sender_name,
                    "created_at": message.created_at,
                    **({"user_message_id": message.user_message_id} if message.user_message_id else {}),
                })
                if not created_message:
                    failures.append({"chat_id": chat.chat_id, "message_id": message.message_id, "reason": "message_create_failed"})
            imported_chat_ids.append(chat.chat_id)
        except Exception as exc:
            failures.append({"chat_id": chat.chat_id, "reason": type(exc).__name__})
    return {
        "status": "partial" if failures else "complete",
        "imported_chat_ids": imported_chat_ids,
        "failures": failures,
        "encrypted_record_counts": {
            "chats": len(imported_chat_ids),
            "messages": sum(len(chat.messages) for chat in payload.chats) - len([failure for failure in failures if "message_id" in failure]),
        },
    }
