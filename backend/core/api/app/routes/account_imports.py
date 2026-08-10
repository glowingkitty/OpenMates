"""Account Import V1 API routes.

Routes in this module are control-plane endpoints for previewing, transiently
scanning, and completing imports. They must not persist plaintext imported chat,
message, or embed content; encrypted persistence is performed by clients.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.services.account_import_service import (
    AccountImportService,
    BillingServiceImportBilling,
    DirectusImportJobStore,
    ImportCompressionError,
    ImportCreditError,
    ImportPersistenceError,
    ImportScanError,
    ImportSequenceError,
    RedisImportLock,
)
from backend.core.api.app.services.limiter import limiter
from backend.shared.python_utils.billing_utils import calculate_total_credits


router = APIRouter(prefix="/v1/account-imports", tags=["Account Imports"])
# First-party authenticated client surface. Plaintext is transient; persisted chat payloads must be client-encrypted.

MAX_IMPORT_PREVIEW_CHATS = 500
MAX_IMPORT_SCAN_CHATS = 500
MAX_IMPORT_PERSIST_CHATS = 500
MAX_IMPORT_MESSAGES_PER_CHAT = 10_000


class ScanImportRequest(BaseModel):
    batch_id: str | None = Field(default=None, max_length=128)
    sequence: int = Field(default=0, ge=0)
    final_batch: bool = True
    chats: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_IMPORT_SCAN_CHATS)


class ImportSource(StrEnum):
    CLAUDE = "claude"
    CHATGPT = "chatgpt"
    GEMINI = "gemini"
    OPENMATES = "openmates"
    OPENCODE = "opencode"
    OTHER = "other"


class ImportParserFormat(StrEnum):
    CLAUDE = "claude"
    CHATGPT = "chatgpt"
    OPENMATES = "openmates"
    OPENCODE = "opencode"
    GENERIC = "generic"


class PreviewImportRequest(BaseModel):
    source: ImportSource
    parser_format: ImportParserFormat | None = None
    chat_count: int = Field(ge=0, le=MAX_IMPORT_PREVIEW_CHATS)
    source_fingerprints: list[str] = Field(default_factory=list, max_length=MAX_IMPORT_PREVIEW_CHATS)
    estimated_tokens: int = Field(default=0, ge=0)
    estimated_tokens_by_chat: list[Annotated[int, Field(ge=0)]] = Field(
        default_factory=list,
        max_length=MAX_IMPORT_PREVIEW_CHATS,
    )
    estimated_bytes: int = Field(default=0, ge=0)


class CompressImportRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    final_batch: bool = True
    scan_sequence: int = Field(ge=0)
    source_fingerprint: str | None = Field(default=None, max_length=128)
    sanitized_messages: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_IMPORT_MESSAGES_PER_CHAT)
    prior_summary: str | None = None


class ConfirmImportRequest(BaseModel):
    selected_fingerprints: list[str] = Field(min_length=1, max_length=MAX_IMPORT_PREVIEW_CHATS)


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
    encrypted_category: str | None = None
    encrypted_model_name: str | None = None
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
    from backend.apps.ai.processing.chat_compressor import compress_chat_history
    from backend.apps.ai.processing.content_sanitization import sanitize_message_for_import

    async def scanner(content: str, *, task_id: str, **_: Any) -> dict[str, Any]:
        return await sanitize_message_for_import(
            content,
            task_id=task_id,
            secrets_manager=request.app.state.secrets_manager,
            cache_service=request.app.state.cache_service,
            return_metadata=True,
        )

    async def compressor(
        messages: list[dict[str, Any]], *, task_id: str, prior_summary: str | None, force: bool
    ) -> Any:
        return await compress_chat_history(
            messages,
            task_id=task_id,
            secrets_manager=request.app.state.secrets_manager,
            prior_summary=prior_summary,
            force=force,
        )

    directus_service = request.app.state.directus_service
    config_manager = request.app.state.config_manager

    def usage_pricer(model_id: str, input_tokens: int, output_tokens: int) -> int:
        provider_id, _, model_suffix = model_id.partition("/")
        if not provider_id or not model_suffix:
            raise ImportCreditError("Import model usage is missing a priced provider model ID")
        pricing = config_manager.get_model_pricing(provider_id, model_suffix)
        if not pricing:
            pricing = config_manager.get_model_pricing(provider_id, model_id)
        if not pricing:
            raise ImportCreditError("Import model pricing is unavailable")
        return calculate_total_credits(
            pricing_config=pricing,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    billing_service = getattr(request.app.state, "billing_service", None)
    if billing_service is None:
        from backend.core.api.app.services.billing_service import BillingService

        billing_service = BillingService(
            request.app.state.cache_service,
            directus_service,
            request.app.state.encryption_service,
            getattr(request.app.state, "server_stats_service", None),
        )
    return AccountImportService(
        directus_service=directus_service,
        scanner=scanner,
        compressor=compressor,
        billing=BillingServiceImportBilling(billing_service),
        job_store=DirectusImportJobStore(directus_service),
        import_lock=RedisImportLock(request.app.state.cache_service),
        usage_pricer=usage_pricer,
        require_billing_for_paid=True,
    )


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
    token_estimates = list(payload.estimated_tokens_by_chat[: payload.chat_count])
    if not token_estimates and payload.chat_count:
        per_chat = (payload.estimated_tokens + payload.chat_count - 1) // payload.chat_count
        token_estimates = [per_chat] * payload.chat_count
    if len(payload.source_fingerprints) != payload.chat_count or len(token_estimates) != payload.chat_count:
        raise HTTPException(status_code=422, detail="Preview requires one fingerprint and token estimate per chat")
    synthetic_chats = [{
        "source_fingerprint": fingerprint,
        "estimated_input_tokens": token_estimates[index] if index < len(token_estimates) else 0,
        "messages": [],
    } for index, fingerprint in enumerate(payload.source_fingerprints[: payload.chat_count])]
    from backend.apps.ai.processing.chat_compressor import COMPRESSION_MODEL_ID
    from backend.apps.ai.processing.content_sanitization import _load_llm_key_from_app_yml

    scanner_model_id = _load_llm_key_from_app_yml("chat_import_sanitization_model")
    if not scanner_model_id:
        raise HTTPException(status_code=503, detail="Import scanner configuration unavailable")
    estimated_input_tokens = sum(token_estimates)
    conservative_scan_input = estimated_input_tokens + payload.chat_count * 15_000
    conservative_scan_output = payload.chat_count * 1_000
    try:
        estimated_credits = service.usage_pricer(scanner_model_id, conservative_scan_input, conservative_scan_output)
        estimated_credits += service.usage_pricer(
            f"google/{COMPRESSION_MODEL_ID}",
            estimated_input_tokens,
            payload.chat_count * 5_000,
        )
    except ImportCreditError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return await service.preview_import(
            user_id=str(user_info["user_id"]),
            source=payload.source.value,
            chats=synthetic_chats,
            available_credits=int(user_info.get("credits") or 0),
            imported_count_last_30_days=0,
            existing_fingerprints=set(),
            estimated_credits=estimated_credits,
        )
    except ImportCreditError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ImportScanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{import_id}/confirm")
@limiter.limit("20/minute")
async def confirm_import(
    import_id: str,
    request: Request,
    payload: ConfirmImportRequest,
    service: AccountImportService = Depends(get_account_import_service),
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    del request
    try:
        return await service.confirm_import(
            user_id=str(user_info["user_id"]),
            import_id=import_id,
            selected_fingerprints=payload.selected_fingerprints,
            available_credits=int(user_info.get("credits") or 0),
        )
    except ImportCreditError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ImportScanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportSequenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        if payload.batch_id is None:
            return await service.scan_selected_chats(user_id=user_id, import_id=import_id, chats=payload.chats)
        return await service.scan_import_batch(
            user_id=user_id,
            import_id=import_id,
            batch_id=payload.batch_id,
            sequence=payload.sequence,
            final_batch=payload.final_batch,
            chats=payload.chats,
        )
    except ImportScanError as exc:
        status_code = 503 if "retryable" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ImportCreditError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ImportSequenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{import_id}/compress")
@limiter.limit("10/minute")
async def compress_import(
    import_id: str,
    request: Request,
    payload: CompressImportRequest,
    service: AccountImportService = Depends(get_account_import_service),
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    del request
    try:
        return await service.compress_import_batch(
            user_id=str(user_info["user_id"]),
            import_id=import_id,
            batch_id=payload.batch_id,
            sequence=payload.sequence,
            final_batch=payload.final_batch,
            scan_sequence=payload.scan_sequence,
            sanitized_messages=payload.sanitized_messages,
            source_fingerprint=payload.source_fingerprint,
            prior_summary=payload.prior_summary,
        )
    except ImportCompressionError as exc:
        status_code = 503 if "retryable" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ImportCreditError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ImportSequenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{import_id}/status")
@limiter.limit("60/minute")
async def import_status(
    import_id: str,
    request: Request,
    service: AccountImportService = Depends(get_account_import_service),
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    del request
    return await service.get_import_status(user_id=str(user_info["user_id"]), import_id=import_id)


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
    try:
        return await service.complete_import(
            user_id=str(user_info["user_id"]),
            import_id=import_id,
            imported_chat_ids=payload.imported_chat_ids,
            source_fingerprints=payload.source_fingerprints,
            encrypted_record_counts=payload.encrypted_record_counts,
            client_failures=payload.client_failures,
        )
    except ImportPersistenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ImportCreditError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc


@router.post("/{import_id}/persist-encrypted")
@limiter.limit("10/minute")
async def persist_encrypted_import(
    import_id: str,
    payload: PersistEncryptedImportRequest,
    request: Request,
    service: AccountImportService = Depends(get_account_import_service),
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    user_id = str(user_info["user_id"])
    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
    directus_service = request.app.state.directus_service
    imported_chat_ids: list[str] = []
    failures: list[dict[str, Any]] = []
    successful_messages = 0
    async with service.lock_operation(user_id=user_id, import_id=import_id):
        try:
            await service.validate_encrypted_persistence(
                user_id=user_id,
                import_id=import_id,
                source_fingerprints=[chat.source_fingerprint for chat in payload.chats],
            )
        except ImportPersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        persisted_fingerprints: list[str] = []
        for chat in payload.chats:
            try:
                chat_failed = False
                chat_messages_created = 0
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
                if not created_chat or is_duplicate:
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
                        "encrypted_category": message.encrypted_category,
                        "encrypted_model_name": message.encrypted_model_name,
                        "created_at": message.created_at,
                        **({"user_message_id": message.user_message_id} if message.user_message_id else {}),
                    })
                    if not created_message:
                        failures.append({"chat_id": chat.chat_id, "message_id": message.message_id, "reason": "message_create_failed"})
                        chat_failed = True
                        break
                    chat_messages_created += 1
                if chat_failed:
                    await directus_service.chat.delete_all_messages_for_chat(chat.chat_id)
                    await directus_service.chat.persist_delete_chat(chat.chat_id)
                    continue
                imported_chat_ids.append(chat.chat_id)
                persisted_fingerprints.append(chat.source_fingerprint)
                successful_messages += chat_messages_created
            except Exception as exc:
                await directus_service.chat.delete_all_messages_for_chat(chat.chat_id)
                await directus_service.chat.persist_delete_chat(chat.chat_id)
                failures.append({"chat_id": chat.chat_id, "reason": type(exc).__name__})
        try:
            await service.record_encrypted_persistence(
                user_id=user_id,
                import_id=import_id,
                chat_ids=imported_chat_ids,
                source_fingerprints=persisted_fingerprints,
            )
        except Exception as exc:
            rollback_failed = False
            for chat_id in imported_chat_ids:
                try:
                    await directus_service.chat.delete_all_messages_for_chat(chat_id)
                except Exception:
                    rollback_failed = True
                try:
                    await directus_service.chat.persist_delete_chat(chat_id)
                except Exception:
                    rollback_failed = True
            detail = (
                "Encrypted import metadata acknowledgement failed; rollback incomplete"
                if rollback_failed
                else "Encrypted import metadata acknowledgement failed; persisted chats were rolled back"
            )
            raise HTTPException(status_code=500, detail=detail) from exc
    return {
        "status": "partial" if failures else "complete",
        "imported_chat_ids": imported_chat_ids,
        "failures": failures,
        "encrypted_record_counts": {
            "chats": len(imported_chat_ids),
            "messages": successful_messages,
        },
    }
