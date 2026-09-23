"""First-party realtime audio transcription WebSocket proxy.

The browser streams ephemeral PCM to this authenticated endpoint. The API key,
provider connection, billing, and transcript correction remain server-side.
Plaintext audio and transcript text are never persisted by this route.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import uuid
from typing import Any, Optional

import aiohttp
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from backend.apps.audio.pricing import (
    REALTIME_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE,
    REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER,
    REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE,
)
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.services.cache_user_mixin import canonical_session_user_id
from backend.core.api.app.utils.server_mode import is_payment_enabled
from backend.core.api.app.utils.text_sanitization import sanitize_text_simple
from backend.core.api.app.utils.ws_token import verify_ws_token
from backend.shared.providers.gemini_transcript_correction import (
    GEMINI_CORRECTION_MODEL,
    clean_transcript_title,
    correct_transcript_with_gemini,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/apps/audio")

MISTRAL_REALTIME_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
MISTRAL_REALTIME_MODEL = "voxtral-mini-transcribe-realtime-2602"
PCM_SAMPLE_RATE = 16_000
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * 2
MAX_CHUNK_BYTES = 256 * 1024
MAX_AUDIO_SECONDS = 20 * 60
LOCK_TTL_SECONDS = MAX_AUDIO_SECONDS + 120
REALTIME_CREDITS_PER_MINUTE = REALTIME_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE
REALTIME_USAGE_TYPE = "realtime_transcription"
INTERRUPTED_REALTIME_USAGE_TYPE = "realtime_transcription_interrupted"


def _origin_is_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    allowed = set(getattr(websocket.app.state, "allowed_origins", []) or [])
    return bool(origin and origin in allowed)


async def _browser_request_is_allowed(
    websocket: WebSocket, auth_data: dict[str, Any]
) -> bool:
    """Authorize the browser origin or a user-bound short-lived WS token.

    Safari can omit or rewrite Origin on an otherwise authenticated WebSocket
    upgrade. A valid HMAC token is stored in sessionStorage (not a cookie), so a
    third-party origin cannot obtain it through a cross-site request. Bind the
    token back to the already-authenticated user before allowing this fallback.
    Cookie-only connections still require an exact first-party Origin match.
    """
    if _origin_is_allowed(websocket):
        return True

    ws_token = websocket.query_params.get("token")
    token_hash = verify_ws_token(ws_token) if ws_token else None
    if not token_hash:
        return False

    cache = websocket.app.state.cache_service
    session_data = await cache.get(f"{cache.SESSION_KEY_PREFIX}{token_hash}")
    return canonical_session_user_id(session_data) == auth_data.get("user_id")


def _safe_provider_error(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return str(
            error.get("message") or error.get("code") or "Realtime transcription failed"
        )[:240]
    return "Realtime transcription failed"


async def _acquire_stream_lock(
    cache: Any, user_id_hash: str
) -> tuple[Optional[Any], str, str]:
    key = f"audio:realtime:active:{user_id_hash}"
    token = uuid.uuid4().hex
    client = await cache.client
    if not client:
        # Realtime provider use is spend-bearing. If admission control is
        # unavailable, fail closed instead of opening an unbounded stream.
        return False, key, token
    acquired = await client.set(key, token, nx=True, ex=LOCK_TTL_SECONDS)
    return (client if acquired else False), key, token


async def _release_stream_lock(client: Any, key: str, token: str) -> None:
    if not client:
        return
    try:
        current = await client.get(key)
        current_text = current.decode() if isinstance(current, bytes) else current
        if current_text == token:
            await client.delete(key)
    except Exception:
        logger.warning("Failed to release realtime audio lock", exc_info=True)


def _create_billing_service(websocket: WebSocket) -> Any:
    # BillingService imports the wider websocket/task graph, so keep it out of
    # route module import time (and make protocol helper tests lightweight).
    from backend.core.api.app.services.billing_service import BillingService

    return BillingService(
        websocket.app.state.cache_service,
        websocket.app.state.directus_service,
        websocket.app.state.encryption_service,
        websocket.app.state.server_stats_service,
    )


async def _bill_realtime_usage(
    websocket: WebSocket,
    *,
    user_id: str,
    user_id_hash: str,
    request_id: str,
    audio_seconds: float,
    chat_id: Optional[str],
    interrupted: bool = False,
) -> None:
    if audio_seconds <= 0:
        return
    billed_minutes = max(1, math.ceil(audio_seconds / 60))
    usage_details: dict[str, Any] = {
        "duration_seconds": audio_seconds,
        "billed_minutes": billed_minutes,
        "requests_transcribed": 1,
        "model": MISTRAL_REALTIME_MODEL,
        "provider_cost_usd_per_minute": float(
            REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE
        ),
        "price_markup_percent": int(
            (REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER - 1) * 100
        ),
        "credits_per_started_minute": REALTIME_CREDITS_PER_MINUTE,
        "usage_type": (
            INTERRUPTED_REALTIME_USAGE_TYPE
            if interrupted
            else REALTIME_USAGE_TYPE
        ),
    }
    if chat_id:
        usage_details["chat_id"] = chat_id
    billing = _create_billing_service(websocket)
    await billing.charge_user_credits(
        user_id=user_id,
        user_id_hash=user_id_hash,
        credits_to_deduct=billed_minutes * REALTIME_CREDITS_PER_MINUTE,
        app_id="audio",
        skill_id="transcribe",
        idempotency_key=f"audio-realtime:{request_id}",
        usage_details=usage_details,
    )


async def _correct_and_send(
    websocket: WebSocket,
    raw_transcript: str,
    language: Optional[str],
) -> None:
    await websocket.send_json(
        {"type": "correction.started", "model": GEMINI_CORRECTION_MODEL}
    )
    try:
        google_key = await websocket.app.state.secrets_manager.get_secret(
            "kv/data/providers/google_ai_studio", "api_key"
        )
        if not google_key:
            raise RuntimeError("Transcript correction is unavailable")
        result = await correct_transcript_with_gemini(
            raw_transcript, google_key, language
        )
        corrected = sanitize_text_simple(
            result["corrected_transcript"], log_prefix="[AudioRealtime][Gemini] "
        )
        title = clean_transcript_title(
            sanitize_text_simple(
                result["title"], log_prefix="[AudioRealtime][Gemini title] "
            )
        )
        await websocket.send_json(
            {
                "type": "correction.done",
                "title": title,
                "transcript": corrected,
                "correction_model": GEMINI_CORRECTION_MODEL,
            }
        )
    except Exception as exc:
        logger.warning("Realtime transcript correction failed: %s", type(exc).__name__)
        await websocket.send_json({"type": "correction.failed"})


@router.websocket("/realtime-transcription")
async def realtime_transcription(
    websocket: WebSocket,
    auth_data: Optional[dict] = Depends(get_current_user_ws),
) -> None:
    if auth_data is None:
        return
    if not await _browser_request_is_allowed(websocket, auth_data):
        logger.warning(
            "Realtime audio WebSocket rejected: neither first-party Origin nor "
            "a user-bound short-lived token was present"
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed"
        )
        return

    user_id = auth_data["user_id"]
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    user_data = auth_data.get("user_data") or {}
    credits = user_data.get("credits")
    if (
        is_payment_enabled()
        and isinstance(credits, (int, float))
        and credits < REALTIME_CREDITS_PER_MINUTE
    ):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Not enough credits"
        )
        return

    lock_client, lock_key, lock_token = await _acquire_stream_lock(
        websocket.app.state.cache_service, user_id_hash
    )
    if lock_client is False:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="A recording is already active"
        )
        return

    await websocket.accept()
    bytes_received = 0
    provider_request_id = uuid.uuid4().hex
    provider_done = False
    billing_task: Optional[asyncio.Task[None]] = None
    chat_id = websocket.query_params.get("chat_id") or None
    try:
        mistral_key = await websocket.app.state.secrets_manager.get_secret(
            "kv/data/providers/mistral_ai", "api_key"
        )
        if not mistral_key:
            raise RuntimeError("Realtime transcription is unavailable")

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=90)
        provider_url = f"{MISTRAL_REALTIME_URL}?model={MISTRAL_REALTIME_MODEL}"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                provider_url,
                headers={"Authorization": f"Bearer {mistral_key}"},
                heartbeat=20,
                max_msg_size=2 * 1024 * 1024,
            ) as provider:
                created = await provider.receive_json()
                if created.get("type") != "session.created":
                    raise RuntimeError("Provider did not create a realtime session")
                session_data = created.get("session") or {}
                provider_request_id = str(
                    session_data.get("request_id")
                    or session_data.get("id")
                    or provider_request_id
                )
                await provider.send_json(
                    {
                        "type": "session.update",
                        "session": {
                            "audio_format": {
                                "encoding": "pcm_s16le",
                                "sample_rate": PCM_SAMPLE_RATE,
                            },
                            "target_streaming_delay_ms": 1000,
                        },
                    }
                )
                updated = await provider.receive_json()
                if updated.get("type") != "session.updated":
                    raise RuntimeError("Provider did not accept realtime settings")
                await websocket.send_json(
                    {
                        "type": "session.ready",
                        "model": MISTRAL_REALTIME_MODEL,
                        "sample_rate": PCM_SAMPLE_RATE,
                    }
                )

                client_receive = asyncio.create_task(websocket.receive_text())
                provider_receive = asyncio.create_task(provider.receive())
                try:
                    while not provider_done:
                        done, _ = await asyncio.wait(
                            {client_receive, provider_receive},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if client_receive in done:
                            raw_message = client_receive.result()
                            message = json.loads(raw_message)
                            event_type = message.get("type")
                            if event_type == "input_audio.append":
                                encoded = message.get("audio")
                                if not isinstance(encoded, str):
                                    raise ValueError("Audio chunk is missing")
                                decoded = base64.b64decode(encoded, validate=True)
                                if not decoded or len(decoded) > MAX_CHUNK_BYTES:
                                    raise ValueError("Audio chunk size is invalid")
                                bytes_received += len(decoded)
                                if (
                                    bytes_received
                                    > PCM_BYTES_PER_SECOND * MAX_AUDIO_SECONDS
                                ):
                                    raise ValueError("Recording is too long")
                                await provider.send_json(
                                    {"type": event_type, "audio": encoded}
                                )
                            elif event_type == "input_audio.end":
                                await provider.send_json({"type": "input_audio.flush"})
                                await provider.send_json({"type": "input_audio.end"})
                            elif event_type == "session.metadata":
                                candidate_chat_id = message.get("chat_id")
                                if (
                                    isinstance(candidate_chat_id, str)
                                    and len(candidate_chat_id) <= 128
                                ):
                                    chat_id = candidate_chat_id
                            elif event_type == "session.cancel":
                                return
                            client_receive = asyncio.create_task(
                                websocket.receive_text()
                            )

                        if provider_receive in done:
                            provider_message = provider_receive.result()
                            if provider_message.type != aiohttp.WSMsgType.TEXT:
                                raise RuntimeError(
                                    "Provider realtime connection closed"
                                )
                            event = json.loads(provider_message.data)
                            event_type = event.get("type")
                            if event_type == "transcription.text.delta":
                                delta = sanitize_text_simple(
                                    str(event.get("text") or ""),
                                    log_prefix="[AudioRealtime][Mistral delta] ",
                                )
                                if delta:
                                    await websocket.send_json(
                                        {"type": event_type, "text": delta}
                                    )
                            elif event_type == "transcription.done":
                                raw_transcript = sanitize_text_simple(
                                    str(event.get("text") or "").strip(),
                                    log_prefix="[AudioRealtime][Mistral] ",
                                )
                                language = event.get("language")
                                usage = (
                                    event.get("usage")
                                    if isinstance(event.get("usage"), dict)
                                    else {}
                                )
                                audio_seconds = float(
                                    usage.get("prompt_audio_seconds")
                                    or bytes_received / PCM_BYTES_PER_SECOND
                                )
                                await websocket.send_json(
                                    {
                                        "type": "transcription.done",
                                        "transcript": raw_transcript,
                                        "language": language,
                                        "model": MISTRAL_REALTIME_MODEL,
                                    }
                                )
                                provider_done = True
                                billing_task = asyncio.create_task(
                                    _bill_realtime_usage(
                                        websocket,
                                        user_id=user_id,
                                        user_id_hash=user_id_hash,
                                        request_id=provider_request_id,
                                        audio_seconds=audio_seconds,
                                        chat_id=chat_id,
                                    )
                                )
                                if raw_transcript:
                                    await _correct_and_send(
                                        websocket, raw_transcript, language
                                    )
                                else:
                                    await websocket.send_json(
                                        {"type": "correction.failed"}
                                    )
                                try:
                                    await billing_task
                                except Exception:
                                    logger.exception(
                                        "Realtime audio billing settlement failed"
                                    )
                            elif event_type == "error":
                                raise RuntimeError(_safe_provider_error(event))
                            provider_receive = asyncio.create_task(provider.receive())
                finally:
                    client_receive.cancel()
                    provider_receive.cancel()
                    await asyncio.gather(
                        client_receive, provider_receive, return_exceptions=True
                    )
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Realtime transcription ended with %s", type(exc).__name__)
        try:
            await websocket.send_json(
                {"type": "session.error", "message": str(exc)[:240]}
            )
        except Exception:
            pass
    finally:
        # A client may close after receiving the raw transcript while correction
        # is still being sent. Billing was already started at transcription.done;
        # always observe and settle that task before releasing admission control.
        if billing_task is not None and not billing_task.done():
            try:
                await asyncio.shield(billing_task)
            except Exception:
                logger.exception("Realtime audio billing settlement failed")
        # The provider may have accepted audio before either side disconnects.
        # Settle that usage even when no transcription.done event arrives; the
        # provider request ID keeps a retry idempotent.
        if bytes_received and billing_task is None:
            try:
                await _bill_realtime_usage(
                    websocket,
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    request_id=provider_request_id,
                    audio_seconds=bytes_received / PCM_BYTES_PER_SECOND,
                    chat_id=chat_id,
                    interrupted=True,
                )
            except Exception:
                logger.exception("Realtime audio disconnect billing failed")
        await _release_stream_lock(lock_client, lock_key, lock_token)
