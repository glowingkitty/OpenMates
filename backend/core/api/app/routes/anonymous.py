"""Anonymous free-usage API routes.

Public official-cloud endpoints for anonymous free chat availability and guarded
text-only execution. Anonymous file upload attempts fail closed with a signup
requirement; real file processing uses the authenticated upload flow after
account creation.
"""

from __future__ import annotations

import re
import uuid
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService
from backend.core.api.app.utils.device_fingerprint import _extract_client_ip
from backend.core.api.app.utils.server_mode import validate_request_domain

try:
    from backend.core.api.app.services.limiter import limiter
except ModuleNotFoundError:  # pragma: no cover - unit env without slowapi
    class _NoopLimiter:
        def limit(self, _rate: str):
            def decorator(func):
                return func

            return decorator

    limiter = _NoopLimiter()


router = APIRouter(prefix="/v1/anonymous", tags=["Anonymous"])

EMBED_REFERENCE_PATTERN = re.compile(
    r'```(?:json|json_embed)\s*\n\s*\{[^`]*("embed_id"|"type"\s*:\s*"(?:image|audio|pdf|document|file)")',
    re.IGNORECASE,
)


class AnonymousHistoryMessage(BaseModel):
    role: str
    content: str
    created_at: int
    sender_name: Optional[str] = None


class AnonymousChatStreamRequest(BaseModel):
    anonymous_id: str = Field(..., min_length=1, max_length=128)
    client_chat_id: str = Field(..., min_length=1, max_length=128)
    client_message_id: str = Field(..., min_length=1, max_length=128)
    plaintext_message: str = Field(..., min_length=1)
    message_history: list[AnonymousHistoryMessage | dict[str, Any]] = Field(default_factory=list)
    requested_skill_ids: Optional[list[str]] = None
    encrypted_context_metadata: Optional[dict[str, Any]] = None
    files: Optional[list[dict[str, Any]]] = None
    embeds: Optional[list[dict[str, Any]]] = None


class AnonymousStatusResponse(BaseModel):
    active: bool
    can_send_text: bool = False
    reason: Optional[str] = None
    reset_at: str
    cta: str


class AnonymousChatResponse(BaseModel):
    status: str
    chatId: str
    messageId: str
    assistant: str
    category: Optional[str] = None
    modelName: Optional[str] = None
    creditsCharged: int = 0
    followUpSuggestions: list[str] = Field(default_factory=list)


def validate_anonymous_skill_allowed(app_id: str, skill: dict[str, Any]) -> None:
    """Fail closed unless skill metadata explicitly classifies account needs."""
    if "connected_account_required" not in skill:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "skill_metadata_missing",
                "message": f"Skill {app_id}.{skill.get('id', 'unknown')} is missing connected-account classification.",
            },
        )
    if skill.get("connected_account_required") is True:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "signup_required",
                "message": "Create an account to connect this app and use this skill.",
            },
        )


def reject_anonymous_file_payloads(payload: AnonymousChatStreamRequest) -> None:
    if payload.files or payload.embeds:
        raise _signup_required_for_uploads()
    if _contains_embed_reference(payload.plaintext_message):
        raise _signup_required_for_uploads()
    for message in payload.message_history:
        content = message.content if isinstance(message, AnonymousHistoryMessage) else str(message.get("content", ""))
        if _contains_embed_reference(content):
            raise _signup_required_for_uploads()


def _get_directus_service(request: Request) -> Any:
    directus_service = getattr(request.app.state, "directus_service", None)
    if directus_service is None:
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return directus_service


@router.get("/free-usage/status", response_model=AnonymousStatusResponse)
@limiter.limit("60/minute")
async def get_anonymous_free_usage_status(
    request: Request,
    anonymous_id: Optional[str] = Query(default=None),
    directus_service: Any = Depends(_get_directus_service),
) -> AnonymousStatusResponse:
    _require_official_cloud(request)
    service = AnonymousFreeUsageService(directus_service=directus_service)
    return AnonymousStatusResponse(**(await service.get_public_status(
        anonymous_id=anonymous_id or request.headers.get("X-OpenMates-Anonymous-ID"),
        ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
    )))


def _anonymous_sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _anonymous_title_from_message(message: str) -> str:
    first_line = next((line.strip() for line in message.splitlines() if line.strip()), "Anonymous chat")
    return first_line if len(first_line) <= 50 else f"{first_line[:50]}..."


async def _iter_openai_sse_payloads(streaming_response: Any):
    buffer = ""
    async for chunk in streaming_response.body_iterator:
        if isinstance(chunk, bytes):
            buffer += chunk.decode("utf-8", errors="replace")
        else:
            buffer += str(chunk)
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            data_lines = [line[5:].strip() for line in frame.splitlines() if line.strip().startswith("data:")]
            if not data_lines:
                continue
            payload_text = "\n".join(data_lines)
            if not payload_text or payload_text == "[DONE]":
                continue
            yield json.loads(payload_text)
    if buffer.strip():
        data_lines = [line[5:].strip() for line in buffer.splitlines() if line.strip().startswith("data:")]
        payload_text = "\n".join(data_lines)
        if payload_text and payload_text != "[DONE]":
            yield json.loads(payload_text)


def _wants_event_stream(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "").lower()


@router.post("/chat/stream", response_model=None, include_in_schema=False)
@limiter.limit("20/minute")
async def anonymous_chat_stream(
    request: Request,
    payload: AnonymousChatStreamRequest,
    directus_service: Any = Depends(_get_directus_service),
) -> StreamingResponse | AnonymousChatResponse:
    """Run a text-only anonymous chat turn against the shared free-usage budget."""
    _require_official_cloud(request)
    reject_anonymous_file_payloads(payload)
    request_id = str(uuid.uuid4())
    service = AnonymousFreeUsageService(directus_service=directus_service)

    messages = [
        {
            "role": message.role if isinstance(message, AnonymousHistoryMessage) else str(message.get("role", "user")),
            "content": message.content if isinstance(message, AnonymousHistoryMessage) else str(message.get("content", "")),
            "name": message.sender_name if isinstance(message, AnonymousHistoryMessage) else message.get("sender_name"),
        }
        for message in payload.message_history
    ]
    messages.append({"role": "user", "content": payload.plaintext_message, "name": "User"})

    if not _wants_event_stream(request):
        reservation = await service.reserve_budget(
            request_id=request_id,
            anonymous_id=payload.anonymous_id,
            ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
            estimated_credits=10,
        )
        if not reservation.accepted:
            raise HTTPException(
                status_code=429,
                detail={"code": reservation.reason or "budget_exhausted", "message": "Create an account to keep using OpenMates."},
            )
        try:
            from backend.core.api.app.services.skill_registry import get_global_registry

            result = await get_global_registry().dispatch_skill(
                "ai",
                "ask",
                {
                    "messages": messages,
                    "stream": False,
                    "is_incognito": True,
                    "is_anonymous": True,
                    "anonymous_reservation_id": reservation.request_id,
                    "apps_enabled": True,
                },
            )
            usage = result.get("usage") if isinstance(result, dict) else None
            actual_credits = _safe_positive_int((usage or {}).get("total_credits"), fallback=reservation.reserved_credits)
            await service.finalize_reservation(reservation.request_id, actual_credits=actual_credits)
        except HTTPException:
            await service.release_reservation(reservation.request_id, reason="ai_http_error")
            raise
        except Exception as exc:
            await service.release_reservation(reservation.request_id, reason="ai_error")
            raise HTTPException(status_code=500, detail={"code": "anonymous_inference_failed", "message": str(exc)}) from exc

        choice = (result.get("choices") or [{}])[0] if isinstance(result, dict) else {}
        message = choice.get("message") or {}
        assistant = str(message.get("content") or "")
        return AnonymousChatResponse(
            status="completed",
            chatId=payload.client_chat_id,
            messageId=f"{payload.client_chat_id[-10:]}-{uuid.uuid4()}",
            assistant=assistant,
            category=result.get("category") if isinstance(result, dict) else None,
            modelName=result.get("model") if isinstance(result, dict) else None,
            creditsCharged=actual_credits,
        )

    async def stream_anonymous_events():
        from backend.core.api.app.services.skill_registry import get_global_registry

        task_id = request_id
        assistant_message_id = f"{payload.client_chat_id[-10:]}-{uuid.uuid4()}"
        category = "general_knowledge"
        model_name: str | None = None
        full_content = ""
        sequence = 0
        finalized = False
        reservation = None
        actual_credits = 10

        yield _anonymous_sse_event({
            "type": "ai_task_initiated",
            "chat_id": payload.client_chat_id,
            "user_message_id": payload.client_message_id,
            "ai_task_id": task_id,
            "status": "processing_started",
        })
        yield _anonymous_sse_event({
            "type": "ai_typing_started",
            "chat_id": payload.client_chat_id,
            "message_id": assistant_message_id,
            "user_message_id": payload.client_message_id,
            "category": category,
            "model_name": model_name,
            "provider_name": None,
            "server_region": None,
            "title": _anonymous_title_from_message(payload.plaintext_message),
            "icon_names": ["ai"],
            "task_id": task_id,
        })

        try:
            reservation = await service.reserve_budget(
                request_id=request_id,
                anonymous_id=payload.anonymous_id,
                ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
                estimated_credits=10,
            )
            if not reservation.accepted:
                yield _anonymous_sse_event({
                    "type": "ai_message_chunk",
                    "task_id": task_id,
                    "chat_id": payload.client_chat_id,
                    "message_id": assistant_message_id,
                    "user_message_id": payload.client_message_id,
                    "full_content_so_far": "Create an account to keep using OpenMates.",
                    "sequence": sequence + 1,
                    "is_final_chunk": True,
                    "model_name": model_name,
                    "rejection_reason": reservation.reason or "budget_exhausted",
                })
                yield _anonymous_sse_event({
                    "type": "ai_task_ended",
                    "chatId": payload.client_chat_id,
                    "taskId": task_id,
                    "status": "failed",
                })
                return

            actual_credits = reservation.reserved_credits
            result = await get_global_registry().dispatch_skill(
                "ai",
                "ask",
                {
                    "messages": messages,
                    "stream": True,
                    "is_incognito": True,
                    "is_anonymous": True,
                    "anonymous_reservation_id": reservation.request_id,
                    "apps_enabled": True,
                },
            )
            if isinstance(result, dict):
                choice = (result.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                full_content = str(message.get("content") or "")
                model_name = result.get("model")
                usage = result.get("usage") if isinstance(result, dict) else None
                actual_credits = _safe_positive_int((usage or {}).get("total_credits"), fallback=reservation.reserved_credits)
                sequence = 1
                yield _anonymous_sse_event({
                    "type": "ai_message_chunk",
                    "task_id": task_id,
                    "chat_id": payload.client_chat_id,
                    "message_id": assistant_message_id,
                    "user_message_id": payload.client_message_id,
                    "full_content_so_far": full_content,
                    "sequence": sequence,
                    "is_final_chunk": True,
                    "model_name": model_name,
                })
            else:
                async for openai_payload in _iter_openai_sse_payloads(result):
                    if isinstance(openai_payload.get("model"), str):
                        model_name = openai_payload["model"]
                    for choice in openai_payload.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content_delta = delta.get("content")
                        if content_delta:
                            full_content += str(content_delta)
                            sequence += 1
                            yield _anonymous_sse_event({
                                "type": "ai_message_chunk",
                                "task_id": task_id,
                                "chat_id": payload.client_chat_id,
                                "message_id": assistant_message_id,
                                "user_message_id": payload.client_message_id,
                                "full_content_so_far": full_content,
                                "sequence": sequence,
                                "is_final_chunk": False,
                                "model_name": model_name,
                            })
                    usage = openai_payload.get("usage") or {}
                    if usage:
                        actual_credits = _safe_positive_int(usage.get("total_credits"), fallback=reservation.reserved_credits)
                sequence += 1
                yield _anonymous_sse_event({
                    "type": "ai_message_chunk",
                    "task_id": task_id,
                    "chat_id": payload.client_chat_id,
                    "message_id": assistant_message_id,
                    "user_message_id": payload.client_message_id,
                    "full_content_so_far": full_content,
                    "sequence": sequence,
                    "is_final_chunk": True,
                    "model_name": model_name,
                })
            await service.finalize_reservation(reservation.request_id, actual_credits=actual_credits)
            finalized = True
            yield _anonymous_sse_event({
                "type": "ai_task_ended",
                "chatId": payload.client_chat_id,
                "taskId": task_id,
                "status": "completed",
            })
            yield _anonymous_sse_event(_anonymous_post_processing_event(
                chat_id=payload.client_chat_id,
                task_id=task_id,
                user_message=payload.plaintext_message,
                assistant=full_content,
            ))
        except Exception as exc:
            if reservation is not None and not finalized:
                await service.release_reservation(reservation.request_id, reason="ai_error")
            yield _anonymous_sse_event({
                "type": "ai_message_chunk",
                "task_id": task_id,
                "chat_id": payload.client_chat_id,
                "message_id": assistant_message_id,
                "user_message_id": payload.client_message_id,
                "full_content_so_far": f"Error: {exc}",
                "sequence": sequence + 1,
                "is_final_chunk": True,
                "model_name": model_name,
                "rejection_reason": "anonymous_inference_failed",
            })
            yield _anonymous_sse_event({
                "type": "ai_task_ended",
                "chatId": payload.client_chat_id,
                "taskId": task_id,
                "status": "failed",
            })

    return StreamingResponse(
        stream_anonymous_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _anonymous_post_processing_event(
    *,
    chat_id: str,
    task_id: str,
    user_message: str,
    assistant: str,
) -> dict[str, Any]:
    """Return local-only anonymous post-processing metadata for the web client."""
    summary = _anonymous_summary_from_turn(user_message=user_message, assistant=assistant)
    return {
        "type": "post_processing_completed",
        "event_for_client": "post_processing_completed",
        "chat_id": chat_id,
        "task_id": task_id,
        "follow_up_request_suggestions": _anonymous_follow_up_suggestions(user_message),
        "new_chat_request_suggestions": [],
        "chat_summary": summary,
        "chat_tags": [],
        "harmful_response": 0,
        "quick_tip_slugs": [],
    }


def _anonymous_summary_from_turn(*, user_message: str, assistant: str) -> str:
    compact_user = " ".join(user_message.split())
    compact_assistant = " ".join(assistant.split())
    if compact_assistant:
        first_sentence = compact_assistant.split(". ", 1)[0].strip().rstrip(".")
        summary = first_sentence or compact_user
    else:
        summary = compact_user or "Anonymous chat"
    return summary[:180]


def _anonymous_follow_up_suggestions(user_message: str) -> list[str]:
    topic = " ".join(user_message.split()).strip().rstrip("?.!") or "this topic"
    short_topic = topic[:80]
    return [
        f"Explain {short_topic} in simpler terms",
        f"Give me practical examples about {short_topic}",
        f"What should I know next about {short_topic}",
        f"Compare different perspectives on {short_topic}",
        f"Summarize the key facts about {short_topic}",
        f"Ask a follow-up question about {short_topic}",
    ]


def _contains_embed_reference(content: str) -> bool:
    return bool(content and EMBED_REFERENCE_PATTERN.search(content))


def _signup_required_for_uploads() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "signup_required",
            "message": "Create an account to upload files. Your typed message can be kept as a draft.",
        },
    )


def _safe_positive_int(value: Any, *, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _require_official_cloud(request: Request) -> None:
    _domain, is_self_hosted, _edition = validate_request_domain(request)
    if is_self_hosted:
        raise HTTPException(status_code=404, detail="Feature not available on this server edition")
