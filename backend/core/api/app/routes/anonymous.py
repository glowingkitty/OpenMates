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
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService
from backend.core.api.app.utils.device_fingerprint import _extract_client_ip
from backend.core.api.app.utils.server_mode import validate_request_domain
from backend.shared.python_utils.learning_mode import build_anonymous_request_learning_mode_context

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
logger = logging.getLogger(__name__)
MAX_ANONYMOUS_MESSAGE_CHARS = 20_000
MAX_ANONYMOUS_HISTORY_MESSAGES = 50
ANONYMOUS_INFERENCE_ERROR_MESSAGE = "Anonymous inference failed. Please try again."
ANONYMOUS_STATUS_LOCAL_RATE_LIMIT_PER_MINUTE = 60
ANONYMOUS_CHAT_LOCAL_RATE_LIMIT_PER_MINUTE = 20
MAX_ANONYMOUS_SKILL_BODY_BYTES = 20_000

EMBED_REFERENCE_PATTERN = re.compile(
    r'```(?:json|json_embed)\s*\n\s*\{[^`]*("embed_id"|"type"\s*:\s*"(?:image|audio|pdf|document|file)")',
    re.IGNORECASE,
)
ANONYMOUS_SKILL_DISPLAY_PATTERN = re.compile(
    r"^[ \t]*```(?:json|json_embed)[ \t]*\r?\n(?P<body>.*?)\r?\n[ \t]*```[ \t]*(?=\r?$)",
    re.MULTILINE | re.DOTALL,
)
ANONYMOUS_SKILL_DISPLAY_FIELDS = frozenset({"type", "embed_id", "app_id", "skill_id"})
ANONYMOUS_SKILL_DISPLAY_TYPE = "app_skill_use"


class AnonymousHistoryMessage(BaseModel):
    role: str
    content: str = Field(..., max_length=MAX_ANONYMOUS_MESSAGE_CHARS)
    created_at: int
    sender_name: Optional[str] = None


class AnonymousChatStreamRequest(BaseModel):
    anonymous_id: str = Field(..., min_length=1, max_length=128)
    client_chat_id: str = Field(..., min_length=1, max_length=128)
    client_message_id: str = Field(..., min_length=1, max_length=128)
    plaintext_message: str = Field(..., min_length=1, max_length=MAX_ANONYMOUS_MESSAGE_CHARS)
    message_history: list[AnonymousHistoryMessage] = Field(
        default_factory=list,
        max_length=MAX_ANONYMOUS_HISTORY_MESSAGES,
    )
    requested_skill_ids: Optional[list[str]] = None
    learning_mode: Optional[dict[str, Any]] = None
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
    """Only explicitly classified inline skills can run without an account."""
    from backend.shared.python_utils.anonymous_skill_policy import is_anonymous_inline_skill

    if skill.get("anonymous_access") is None:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "skill_metadata_missing",
                "message": f"Skill {app_id}.{skill.get('id', 'unknown')} is missing anonymous access classification.",
            },
        )
    if not is_anonymous_inline_skill(app_id, skill):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "signup_required",
                "message": "Create an account to use this skill.",
            },
        )


def _anonymous_history_content(message: AnonymousHistoryMessage | dict[str, Any]) -> str:
    """Discard local display references, never resolve client-supplied embed IDs.

    Anonymous history is untrusted even when its role says assistant. Only the
    exact display-only skill reference is removed; extra fields and attachment
    references stay intact for the upload guard to reject. The same projection
    must be used for validation and dispatch so forged IDs never reach inference.
    See docs/architecture/apps/rest-api.md for anonymous API boundaries.
    """
    content = message.content if isinstance(message, AnonymousHistoryMessage) else str(message.get("content", ""))
    role = message.role if isinstance(message, AnonymousHistoryMessage) else message.get("role")
    if role != "assistant":
        return content

    def discard_display_reference(match: re.Match[str]) -> str:
        try:
            reference = json.loads(match.group("body"))
        except json.JSONDecodeError:
            return match.group(0)
        if (
            isinstance(reference, dict)
            and reference.keys() == ANONYMOUS_SKILL_DISPLAY_FIELDS
            and reference["type"] == ANONYMOUS_SKILL_DISPLAY_TYPE
            and all(isinstance(value, str) for value in reference.values())
        ):
            return ""
        return match.group(0)

    return ANONYMOUS_SKILL_DISPLAY_PATTERN.sub(discard_display_reference, content)


def _require_anonymous_answer(content: str) -> None:
    # A worker can close normally after reservation denial with only skill
    # display fences. Those are progress, not a completed answer. Validate before
    # the final marker; keep provider accounting in its existing worker lifecycle.
    if not _anonymous_history_content({"role": "assistant", "content": content}).strip():
        raise RuntimeError("Anonymous inference ended without answer content")


def reject_anonymous_file_payloads(payload: AnonymousChatStreamRequest) -> None:
    if payload.files or payload.embeds:
        raise _signup_required_for_uploads()
    if _contains_embed_reference(payload.plaintext_message):
        raise _signup_required_for_uploads()
    for message in payload.message_history:
        content = _anonymous_history_content(message)
        if _contains_embed_reference(content):
            raise _signup_required_for_uploads()


def _reject_anonymous_skill_references(value: Any) -> None:
    """Do not let a public skill request refer to private chats or uploads."""
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key.startswith("_") or key in {
                "chat_id", "message_id", "user_id", "embed_id", "file_id",
                "file", "files", "attachments", "connected_account", "connected_account_id",
            }:
                raise _signup_required_for_uploads()
            _reject_anonymous_skill_references(child)
    elif isinstance(value, list):
        for child in value:
            _reject_anonymous_skill_references(child)


def _anonymous_skill_quote(request: Request, app_id: str, skill: Any, body: dict[str, Any]) -> int:
    """Price one inline skill operation before dispatch, failing closed for variable work."""
    from backend.core.api.app.utils.config_manager import ConfigManager
    from backend.shared.python_utils.billing_utils import calculate_total_credits

    pricing = skill.pricing.model_dump(exclude_none=True) if skill.pricing else None
    if pricing and "per_request_credits" in pricing:
        pricing = {"per_unit": {"credits": pricing["per_request_credits"]}}
    config = None if pricing else (getattr(request.app.state, "config_manager", None) or ConfigManager())
    if not pricing and skill.full_model_reference and "/" in skill.full_model_reference:
        provider_id, model_id = skill.full_model_reference.split("/", 1)
        pricing = config.get_model_pricing(provider_id, model_id)
    if not pricing and skill.providers:
        provider_name = skill.providers[0].name
        provider_id = provider_name.lower().replace(" ", "_")
        if provider_name == "Google" and app_id == "maps":
            provider_id = "google_maps"
        elif provider_name in {"Brave", "Brave Search"}:
            provider_id = "brave"
        provider = config.get_provider_config(provider_id) or {}
        provider_pricing = provider.get("pricing") or {}
        if "per_request_credits" in provider_pricing:
            pricing = {"per_unit": {"credits": provider_pricing["per_request_credits"]}}
        elif "per_unit" in provider_pricing:
            pricing = {"per_unit": provider_pricing["per_unit"]}
    if not pricing and skill.providers and all(provider.no_api_key for provider in skill.providers):
        pricing = {"fixed": 1}
    rules = (pricing or {}).get("pricing", pricing or {})
    if not rules or any(key in rules for key in ("tokens", "per_second", "per_minute", "per_started_minute")):
        raise HTTPException(status_code=403, detail={"code": "skill_unpriced"})
    quote = calculate_total_credits(pricing_config=pricing, units_processed=1)
    if quote < 1:
        raise HTTPException(status_code=403, detail={"code": "skill_unpriced"})
    return quote


def _anonymous_skill_result_succeeded(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("success") is False or result.get("error"):
        return False
    data = result.get("data", result)
    if isinstance(data, dict) and (data.get("success") is False or data.get("error")):
        return False
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(results, list) and results:
        return any(
            not isinstance(item, dict)
            or (not item.get("error") and item.get("status") not in {"error", "cancelled"})
            for item in results
        )
    return True


def _get_directus_service(request: Request) -> Any:
    directus_service = getattr(request.app.state, "directus_service", None)
    if directus_service is None:
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return directus_service


def _get_cache_service(request: Request) -> Any:
    cache_service = getattr(request.app.state, "cache_service", None)
    if cache_service is None:
        raise HTTPException(status_code=503, detail="Anonymous usage meter unavailable")
    return cache_service


def _anonymous_usage_service(directus_service: Any, cache_service: Any) -> AnonymousFreeUsageService:
    return AnonymousFreeUsageService(
        directus_service=directus_service,
        cache_service=cache_service,
        require_distributed_lock=True,
    )


async def _enforce_local_rate_limit(
    service: AnonymousFreeUsageService,
    *,
    anonymous_id: str,
    max_requests: int,
) -> None:
    try:
        allowed = await service.consume_local_rate_limit(anonymous_id, max_requests=max_requests)
    except Exception as exc:
        logger.exception("Anonymous local-ID rate limiter failed")
        raise HTTPException(status_code=503, detail="Anonymous usage meter unavailable") from exc
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": "Create an account to keep using OpenMates."},
        )


@router.get("/free-usage/status", response_model=AnonymousStatusResponse)
@limiter.limit("60/minute")
async def get_anonymous_free_usage_status(
    request: Request,
    anonymous_id: Optional[str] = Query(default=None),
    directus_service: Any = Depends(_get_directus_service),
    cache_service: Any = Depends(_get_cache_service),
) -> AnonymousStatusResponse:
    _require_official_cloud(request)
    service = _anonymous_usage_service(directus_service, cache_service)
    local_id = anonymous_id or request.headers.get("X-OpenMates-Anonymous-ID")
    if local_id:
        await _enforce_local_rate_limit(
            service,
            anonymous_id=local_id,
            max_requests=ANONYMOUS_STATUS_LOCAL_RATE_LIMIT_PER_MINUTE,
        )
    return AnonymousStatusResponse(**(await service.get_public_status(
        anonymous_id=local_id,
        ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
    )))


@router.post("/apps/{app_id}/skills/{skill_id}", include_in_schema=False)
@limiter.limit("20/minute")
async def anonymous_app_skill(
    request: Request,
    app_id: str,
    skill_id: str,
    body: dict[str, Any],
    directus_service: Any = Depends(_get_directus_service),
    cache_service: Any = Depends(_get_cache_service),
) -> dict[str, Any]:
    """Public official-cloud CLI surface for transient, priced read-only skills."""
    _require_official_cloud(request)
    anonymous_id = request.headers.get("X-OpenMates-Anonymous-ID", "")
    if not 1 <= len(anonymous_id) <= 128:
        raise HTTPException(status_code=422, detail={"code": "anonymous_id_required"})
    if len(json.dumps(body).encode("utf-8")) > MAX_ANONYMOUS_SKILL_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"code": "skill_input_too_large"})
    _reject_anonymous_skill_references(body)
    from backend.shared.python_utils.anonymous_skill_policy import has_single_anonymous_provider_request
    if not has_single_anonymous_provider_request(app_id, skill_id, body):
        raise HTTPException(status_code=422, detail={"code": "invalid_request_count"})

    from backend.core.api.app.services.rest_skill_execution_policy import assert_rest_skill_execution_allowed
    from backend.core.api.app.services.skill_registry import get_global_registry
    from backend.core.api.app.utils.text_sanitization import sanitize_text_payload_for_ascii_smuggling
    from backend.shared.python_utils.anonymous_inline_execution import anonymous_inline_execution
    from backend.shared.python_utils.app_skill_output_safety import (
        APP_SKILL_SURFACE_REST, AppSkillOutputSafetyContext, central_app_skill_dispatch,
        sanitize_app_skill_output, strip_request_security_controls,
    )

    registry = get_global_registry()
    metadata = registry.get_metadata(app_id)
    if metadata is None or not registry.is_skill_available(app_id, skill_id):
        raise HTTPException(status_code=404, detail={"code": "skill_not_found"})
    skill = next((item for item in metadata.skills or [] if item.id == skill_id), None)
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "skill_not_found"})
    assert_rest_skill_execution_allowed(registry, app_id, skill_id)
    validate_anonymous_skill_allowed(app_id, skill.model_dump())
    sanitized_body, _ = sanitize_text_payload_for_ascii_smuggling(body, log_prefix="[anonymous skill]")
    sanitized_body = strip_request_security_controls(sanitized_body)
    quoted_credits = _anonymous_skill_quote(request, app_id, skill, sanitized_body)

    service = _anonymous_usage_service(directus_service, cache_service)
    await _enforce_local_rate_limit(
        service, anonymous_id=anonymous_id,
        max_requests=ANONYMOUS_CHAT_LOCAL_RATE_LIMIT_PER_MINUTE,
    )
    request_id = str(uuid.uuid4())
    admission = await service.open_request(
        request_id=request_id, anonymous_id=anonymous_id,
        ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
    )
    if not admission.accepted:
        raise HTTPException(status_code=429, detail={"code": admission.reason or "budget_exhausted"})
    operation_id = str(uuid.uuid4())
    reservation = await service.reserve_operation(
        parent_request_id=request_id, operation_id=operation_id,
        charge_id=operation_id, quoted_credits=quoted_credits,
    )
    if not reservation.accepted:
        raise HTTPException(status_code=429, detail={"code": reservation.reason or "budget_exhausted"})

    # No account, chat, message, embed, or Vault context is passed to the skill.
    # Keep ambiguous provider attempts reserved for the normal expiry path.
    with central_app_skill_dispatch(), anonymous_inline_execution():
        result = await registry.dispatch_skill(app_id, skill_id, sanitized_body)
    if isinstance(result, dict) and (
        result.get("task_id") or result.get("status") in {"scheduled", "queued", "processing"}
    ):
        # Unexpected deferred work must not expose a pollable task to a guest.
        # Retain the reservation because provider dispatch may have begun.
        raise HTTPException(status_code=503, detail={"code": "inline_result_unavailable"})
    safe_result = await sanitize_app_skill_output(
        result,
        AppSkillOutputSafetyContext(
            app_id=app_id, skill_id=skill_id, surface=APP_SKILL_SURFACE_REST,
            request_body=body,
            # CLI results are returned to the caller, not fed into a model turn.
            # Keep the mandatory ASCII cleanup without starting an unmetered
            # semantic-scanning provider operation after the skill call.
            external_data=False,
            secrets_manager=getattr(request.app.state, "secrets_manager", None),
            cache_service=cache_service, log_prefix="[anonymous skill]",
        ),
    )
    if not _anonymous_skill_result_succeeded(result):
        await service.release_reservation(operation_id, reason="skill_failed")
        return {"success": False, "data": safe_result, "credits_charged": 0}
    await service.finalize_charge(operation_id, actual_credits=quoted_credits)
    return {"success": True, "data": safe_result, "credits_charged": quoted_credits}


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
    cache_service: Any = Depends(_get_cache_service),
) -> StreamingResponse | AnonymousChatResponse:
    """Run a text-only anonymous chat turn against the shared free-usage budget."""
    _require_official_cloud(request)
    reject_anonymous_file_payloads(payload)
    request_id = str(uuid.uuid4())
    service = _anonymous_usage_service(directus_service, cache_service)
    await _enforce_local_rate_limit(
        service,
        anonymous_id=payload.anonymous_id,
        max_requests=ANONYMOUS_CHAT_LOCAL_RATE_LIMIT_PER_MINUTE,
    )

    messages = [
        {
            "role": message.role if isinstance(message, AnonymousHistoryMessage) else str(message.get("role", "user")),
            "content": _anonymous_history_content(message),
            "name": message.sender_name if isinstance(message, AnonymousHistoryMessage) else message.get("sender_name"),
        }
        for message in payload.message_history
    ]
    messages.append({"role": "user", "content": payload.plaintext_message, "name": "User"})
    try:
        learning_mode_context = build_anonymous_request_learning_mode_context(payload.learning_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_learning_mode", "message": str(exc)}) from exc

    if not _wants_event_stream(request):
        reservation = await service.open_request(
            request_id=request_id,
            anonymous_id=payload.anonymous_id,
            ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
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
                    "learning_mode": learning_mode_context,
                },
            )
            choice = (result.get("choices") or [{}])[0] if isinstance(result, dict) else {}
            message = choice.get("message") or {}
            assistant = str(message.get("content") or "")
            _require_anonymous_answer(assistant)
            usage = result.get("usage") if isinstance(result, dict) else None
            actual_credits = _safe_positive_int((usage or {}).get("total_credits"), fallback=0)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Anonymous non-streaming inference failed")
            raise HTTPException(
                status_code=500,
                detail={"code": "anonymous_inference_failed", "message": ANONYMOUS_INFERENCE_ERROR_MESSAGE},
            ) from exc

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
        reservation = None

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
            reservation = await service.open_request(
                request_id=request_id,
                anonymous_id=payload.anonymous_id,
                ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
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
                    "learning_mode": learning_mode_context,
                },
            )
            if isinstance(result, dict):
                choice = (result.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                full_content = str(message.get("content") or "")
                model_name = result.get("model")
            else:
                async for openai_payload in _iter_openai_sse_payloads(result):
                    if isinstance(openai_payload.get("model"), str):
                        model_name = openai_payload["model"]
                    for choice in openai_payload.get("choices") or []:
                        delta = choice.get("delta") or {}
                        for embed in delta.get("embeds") or []:
                            if not isinstance(embed, dict) or not embed.get("embed_id"):
                                continue
                            yield _anonymous_sse_event({
                                "type": "send_embed_data",
                                "payload": {
                                    **embed,
                                    "chat_id": payload.client_chat_id,
                                    "message_id": assistant_message_id,
                                    "user_id": payload.anonymous_id,
                                    "task_id": task_id,
                                },
                            })
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
            _require_anonymous_answer(full_content)
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
        except Exception:
            logger.exception("Anonymous streaming inference failed")
            yield _anonymous_sse_event({
                "type": "ai_message_chunk",
                "task_id": task_id,
                "chat_id": payload.client_chat_id,
                "message_id": assistant_message_id,
                "user_message_id": payload.client_message_id,
                "full_content_so_far": ANONYMOUS_INFERENCE_ERROR_MESSAGE,
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
