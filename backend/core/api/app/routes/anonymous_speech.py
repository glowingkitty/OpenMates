"""Spoken reply for signed-out visitors: text in, Eleven v4 Turbo audio out.

Access model: first-party client surface only (the web app's guest voice call);
credential-free, official cloud only, allowed browser Origin required, not part
of the public developer API. Reachable through Caddy's existing
``/v1/anonymous/*`` first-party matcher only.

The price is the signed-in assistant speech price per character
(``ASSISTANT_SPEECH_CREDITS_PER_CHARACTER``), charged on the anonymous free
allowance: the quote is reserved before the provider is called and settled
afterwards. Neither text nor audio is stored; the audio is returned once.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from backend.apps.audio.assistant_speech.voice_profiles import resolve_assistant_voice_profile
from backend.apps.audio.pricing import (
    ELEVEN_V4_TURBO_SPEECH_MODEL, calculate_assistant_response_speech_credits,
)
from backend.core.api.app.routes.anonymous import (
    _allowance_denial, _anonymous_client_ip, _anonymous_usage_service, _enforce_local_rate_limit,
    _get_cache_service, _get_directus_service, _open_anonymous_request, _require_official_cloud,
)
from backend.core.api.app.services.anonymous_free_usage_service import AnonymousUsageTransactionError
from backend.core.api.app.services.limiter import limiter
from backend.shared.providers.elevenlabs import ElevenLabsClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/anonymous", tags=["Anonymous"])

MAX_SPEECH_CHARACTERS = 4_000
SPEECH_LOCAL_RATE_LIMIT_PER_MINUTE = 20
GUEST_SPEECH_VOICE_KEY = "ace"
GUEST_SPEECH_VOICE_VERSION = 3


class AnonymousSpeechRequest(BaseModel):
    anonymous_id: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=MAX_SPEECH_CHARACTERS)
    language: Optional[str] = Field(default=None, max_length=32)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Speech text is empty")
        return value


def _require_first_party_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    allowed = set(getattr(request.app.state, "allowed_origins", []) or [])
    if not origin or origin not in allowed:
        raise HTTPException(status_code=403, detail={"code": "origin_not_allowed"})


# First-party client surface (credential-free guest); outside the developer API.
@router.post("/speech", include_in_schema=False)
@limiter.limit("20/minute")
async def anonymous_speech(
    request: Request,
    body: AnonymousSpeechRequest,
    directus_service: object = Depends(_get_directus_service),
    cache_service: object = Depends(_get_cache_service),
) -> Response:
    _require_official_cloud(request)
    _require_first_party_origin(request)
    if "auth_refresh_token" in request.cookies or "authorization" in request.headers:
        raise HTTPException(status_code=403, detail={"code": "credentials_not_allowed"})
    service = _anonymous_usage_service(directus_service, cache_service)
    ip = _anonymous_client_ip(request)
    await _enforce_local_rate_limit(
        service, anonymous_id=service.request_identity(body.anonymous_id, ip),
        bucket="speech", max_requests=SPEECH_LOCAL_RATE_LIMIT_PER_MINUTE)
    request_id = "speech-guest:" + uuid.uuid4().hex
    await _open_anonymous_request(service, request_id=request_id, anonymous_id=body.anonymous_id, ip_address=ip)
    quote = calculate_assistant_response_speech_credits(
        submitted_characters=len(body.text), model=ELEVEN_V4_TURBO_SPEECH_MODEL)
    operation_id = request_id + ":speech"
    try:
        reservation = await service.reserve_operation(
            parent_request_id=request_id, operation_id=operation_id, charge_id=operation_id,
            quoted_credits=quote)
    except AnonymousUsageTransactionError as exc:
        logger.warning("Guest speech reservation unavailable: %s", exc.code)
        raise HTTPException(status_code=503, detail={"code": "anonymous_meter_unavailable"}) from exc
    if not reservation.accepted:
        raise HTTPException(status_code=429, detail=_allowance_denial(reservation.reason))

    profile = resolve_assistant_voice_profile(GUEST_SPEECH_VOICE_KEY, version=GUEST_SPEECH_VOICE_VERSION)
    provider_request = profile.elevenlabs_request()
    try:
        generated = await ElevenLabsClient(secrets_manager=request.app.state.secrets_manager).text_to_speech(
            text=body.text, voice_id=str(provider_request["voice_id"]),
            model=str(provider_request["model"]), output_format=str(provider_request["output_format"]))
    except (RuntimeError, ValueError) as exc:
        # The request may have reached the provider: keep the quote charged so an
        # expired reservation cannot refund work that was possibly billed.
        logger.warning("Guest speech generation failed: %s", type(exc).__name__)
        await service.finalize_charge(operation_id, actual_credits=quote)
        raise HTTPException(status_code=502, detail={"code": "speech_unavailable"}) from exc
    await service.finalize_charge(operation_id, actual_credits=quote)
    return Response(content=generated.audio_bytes, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store"})
