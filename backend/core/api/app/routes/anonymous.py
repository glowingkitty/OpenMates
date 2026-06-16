"""Anonymous free-usage API routes.

Public official-cloud endpoints for anonymous free chat availability and guarded
text-only execution. Anonymous file upload attempts fail closed with a signup
requirement; real file processing uses the authenticated upload flow after
account creation.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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
    reason: Optional[str] = None
    reset_at: str
    cta: str


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
    directus_service: Any = Depends(_get_directus_service),
) -> AnonymousStatusResponse:
    _require_official_cloud(request)
    service = AnonymousFreeUsageService(directus_service=directus_service)
    return AnonymousStatusResponse(**(await service.get_public_status()))


@router.post("/chat/stream", include_in_schema=False)
@limiter.limit("20/minute")
async def anonymous_chat_stream(
    request: Request,
    payload: AnonymousChatStreamRequest,
    directus_service: Any = Depends(_get_directus_service),
) -> dict[str, Any]:
    """Reserve anonymous budget for text-only chat.

    The actual streaming AI execution will be wired through the normal AI stack in
    a later slice. This endpoint already enforces the critical upload/signup
    boundary and budget reservation contract.
    """
    _require_official_cloud(request)
    reject_anonymous_file_payloads(payload)
    service = AnonymousFreeUsageService(directus_service=directus_service)
    reservation = await service.reserve_budget(
        request_id=str(uuid.uuid4()),
        anonymous_id=payload.anonymous_id,
        ip_address=_extract_client_ip(request),
        estimated_credits=1,
    )
    if not reservation.accepted:
        raise HTTPException(
            status_code=429,
            detail={"code": reservation.reason or "budget_exhausted", "message": "Create an account to keep using OpenMates."},
        )
    await service.release_reservation(reservation.request_id, reason="stream_not_implemented")
    return {"status": "signup_required", "message": "Anonymous streaming is not enabled in this slice yet."}


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


def _require_official_cloud(request: Request) -> None:
    _domain, is_self_hosted, _edition = validate_request_domain(request)
    if is_self_hosted:
        raise HTTPException(status_code=404, detail="Feature not available on this server edition")
