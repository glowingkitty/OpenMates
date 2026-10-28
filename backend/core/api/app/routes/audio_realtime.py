"""First-party realtime audio transcription WebSocket proxy.

The browser streams ephemeral PCM to this first-party endpoint. The API key,
provider connection, billing, and transcript correction remain server-side.
Plaintext audio and transcript text are never persisted by this route.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import struct
import uuid
from typing import Any, Optional, Callable

import aiohttp
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from backend.apps.audio.pricing import (
    REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE,
    REALTIME_TRANSCRIPTION_MINIMUM_CREDITS,
    REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER,
    REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE,
    calculate_realtime_transcription_credits,
)
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.services.guest_transcription_meter import (
    GuestTranscriptionDenied, GuestTranscriptionMeter, GUEST_IDLE_SECONDS,
    GUEST_WALL_SECONDS, GUEST_MAX_TRANSCRIPT_CHARACTERS,
)
from backend.shared.providers.transcript_correction_accounting import correction_accountant, CorrectionAccountingError
from backend.core.api.app.services.cache_user_mixin import canonical_session_user_id
from backend.core.api.app.services.streaming_transcript_correction import StreamingTranscriptCorrection
from backend.core.api.app.utils.server_mode import is_payment_enabled
from backend.core.api.app.utils.text_sanitization import sanitize_text_simple
from backend.core.api.app.utils.ws_token import verify_ws_token
from backend.shared.providers.gemini_transcript_correction import (
    GEMINI_CORRECTION_MODEL,
    clean_transcript_title,
    correct_transcript_with_gemini,
)
from backend.shared.providers.workflow_transcript_correction import (
    CEREBRAS_WORKFLOW_CORRECTION_MODEL,
    GROQ_WORKFLOW_CORRECTION_MODEL,
    correct_workflow_transcript_with_cerebras,
    correct_workflow_transcript_with_groq,
)
from backend.shared.providers.transcript_correction import (
    MERCURY_CORRECTION_MODEL,
    correct_transcript,
    mercury_correction_enabled,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/apps/audio")

MISTRAL_REALTIME_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
MISTRAL_REALTIME_MODEL = "voxtral-mini-transcribe-realtime-3-0"
# Dictation favors accuracy over aggressive endpointing. Keep the existing
# one-second preview delay; turn detection is for calls, not manually ended input.
REALTIME_STREAMING_DELAY_MS = 1000
PCM_SAMPLE_RATE = 16_000
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * 2
MAX_CHUNK_BYTES = 256 * 1024
MAX_AUDIO_SECONDS = 20 * 60
LOCK_TTL_SECONDS = MAX_AUDIO_SECONDS + 120
REALTIME_CREDITS_PER_MINUTE = REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE
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
    credits_to_charge = calculate_realtime_transcription_credits(
        duration_seconds=audio_seconds
    )
    if credits_to_charge == 0:
        return
    usage_details: dict[str, Any] = {
        "duration_seconds": audio_seconds,
        "billing_unit": "second",
        "requests_transcribed": 1,
        "model": MISTRAL_REALTIME_MODEL,
        "provider_cost_usd_per_minute": float(
            REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE
        ),
        "price_markup_percent": int(
            (REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER - 1) * 100
        ),
        "credits_per_minute": REALTIME_CREDITS_PER_MINUTE,
        "minimum_credits": REALTIME_TRANSCRIPTION_MINIMUM_CREDITS,
        "usage_type": (
            INTERRUPTED_REALTIME_USAGE_TYPE if interrupted else REALTIME_USAGE_TYPE
        ),
    }
    if chat_id:
        usage_details["chat_id"] = chat_id
    billing = _create_billing_service(websocket)
    await billing.charge_user_credits(
        user_id=user_id,
        user_id_hash=user_id_hash,
        credits_to_deduct=credits_to_charge,
        app_id="audio",
        skill_id="transcribe",
        idempotency_key=f"audio-realtime:{request_id}",
        usage_details=usage_details,
    )


def _correction_enabled(context: Optional[str]) -> bool:
    """Preserve the workflow rollout switch for both streaming and finalization."""
    return context != "workflow" or os.getenv(
        "WORKFLOW_TRANSCRIPT_CORRECTION_ENABLED", ""
    ).strip().lower() in {"1", "true", "yes"}


def _initial_correction_model(language: Optional[str], context: Optional[str]) -> str:
    if context == "workflow":
        return (
            GROQ_WORKFLOW_CORRECTION_MODEL
            if (language or "").lower().startswith("en")
            else CEREBRAS_WORKFLOW_CORRECTION_MODEL
        )
    return MERCURY_CORRECTION_MODEL if mercury_correction_enabled() else GEMINI_CORRECTION_MODEL


async def _correct_segment(
    websocket: WebSocket,
    raw_transcript: str,
    language: Optional[str],
    context: Optional[str] = None,
) -> dict[str, str]:
    """Correct one bounded batch through the established provider policy."""
    workflow_context = context == "workflow"
    first_workflow_model = _initial_correction_model(language, context)
    result: dict[str, str] | None = None
    correction_model = GEMINI_CORRECTION_MODEL
    if not workflow_context:
        result = await correct_transcript(
            raw_transcript, websocket.app.state.secrets_manager, language
        )
        correction_model = result["model"]
    if workflow_context:
        workflow_providers = (
            (
                (
                    GROQ_WORKFLOW_CORRECTION_MODEL,
                    "kv/data/providers/groq",
                    correct_workflow_transcript_with_groq,
                ),
                (
                    CEREBRAS_WORKFLOW_CORRECTION_MODEL,
                    "kv/data/providers/cerebras",
                    correct_workflow_transcript_with_cerebras,
                ),
            )
            if first_workflow_model == GROQ_WORKFLOW_CORRECTION_MODEL
            else (
                (
                    CEREBRAS_WORKFLOW_CORRECTION_MODEL,
                    "kv/data/providers/cerebras",
                    correct_workflow_transcript_with_cerebras,
                ),
            )
        )
        for model, secret_path, correct in workflow_providers:
            try:
                key = await websocket.app.state.secrets_manager.get_secret(
                    secret_path, "api_key"
                )
                if not key:
                    continue
                result = await correct(raw_transcript, key, language)
                correction_model = model
                break
            except Exception as exc:
                logger.warning(
                    "Workflow transcript %s correction failed: %s",
                    model,
                    type(exc).__name__,
                )
    if result is None:
        google_key = await websocket.app.state.secrets_manager.get_secret(
            "kv/data/providers/google_ai_studio", "api_key"
        )
        if not google_key:
            raise RuntimeError("Transcript correction is unavailable")
        result = await correct_transcript_with_gemini(
            raw_transcript, google_key, language
        )
    corrected = sanitize_text_simple(
        result["corrected_transcript"], log_prefix="[AudioRealtime][Correction] "
    )
    if not corrected.strip():
        raise RuntimeError("Transcript correction returned empty text")
    title = clean_transcript_title(
        sanitize_text_simple(
            result.get("title", ""), log_prefix="[AudioRealtime][Correction title] "
        )
    )
    return {"title": title, "transcript": corrected, "correction_model": correction_model}


async def _correct_and_send(
    websocket: WebSocket,
    raw_transcript: str,
    language: Optional[str],
    context: Optional[str] = None,
    streaming_correction: Optional[StreamingTranscriptCorrection] = None,
    success_guard: Optional[Callable[[], None]] = None,
) -> None:
    if not _correction_enabled(context):
        await websocket.send_json(
            {"type": "correction.skipped", "transcript": raw_transcript}
        )
        return
    await websocket.send_json(
        {"type": "correction.started", "model": _initial_correction_model(language, context)}
    )
    try:
        result = (
            await streaming_correction.finish(raw_transcript, language)
            if streaming_correction is not None
            else await _correct_segment(websocket, raw_transcript, language, context)
        )
        if success_guard is not None:
            success_guard()
        await websocket.send_json({"type": "correction.done", **result})
    except Exception as exc:
        # Both correction completion frames resolve the browser's pending draft.
        # Propagate guest admission/accounting failures before either can permit
        # raw-text insertion or a pending Send to complete.
        if success_guard is not None:
            success_guard()
        logger.warning("Realtime transcript correction failed: %s", type(exc).__name__)
        await websocket.send_json({"type": "correction.failed"})


async def _optional_transcription_actor(websocket: WebSocket) -> Optional[dict]:
    # Only a genuinely credential-free connection may select guest admission.
    # Invalid/expired supplied credentials keep the existing close-and-return path.
    if ("auth_refresh_token" in websocket.cookies or "token" in websocket.query_params
            or "authorization" in websocket.headers):
        actor = await get_current_user_ws(websocket)
        return actor if actor is not None else {"authentication_failed": True}
    return None


# First-party browser surface. Guests get no account/file/workflow ownership;
# every paid provider attempt is guarded by atomic anonymous budget admission.
@router.websocket("/realtime-transcription")
async def realtime_transcription(
    websocket: WebSocket,
    auth_data: Optional[dict] = Depends(_optional_transcription_actor),
) -> None:
    if auth_data is not None and auth_data.get("authentication_failed"):
        return
    guest = GuestTranscriptionMeter(websocket) if auth_data is None else None
    if not (_origin_is_allowed(websocket) if guest else await _browser_request_is_allowed(websocket, auth_data)):
        logger.warning(
            "Realtime audio WebSocket rejected: neither first-party Origin nor "
            "a user-bound short-lived token was present"
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed"
        )
        return

    user_id = auth_data["user_id"] if auth_data else ""
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    user_data = (auth_data.get("user_data") or {}) if auth_data else {}
    credits = user_data.get("credits")
    if (
        is_payment_enabled()
        and isinstance(credits, (int, float))
        and credits < REALTIME_TRANSCRIPTION_MINIMUM_CREDITS
    ):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Not enough credits"
        )
        return

    if guest:
        await websocket.accept()
        try:
            await asyncio.wait_for(guest.admit(), timeout=10)
        except asyncio.CancelledError:
            await guest.release_locks()
            raise
        except Exception as exc:
            await guest.release_locks()
            code = exc.code if isinstance(exc, GuestTranscriptionDenied) else "anonymous_meter_unavailable"
            await websocket.send_json({"type": "session.error", "code": code, "signup_required": isinstance(exc, GuestTranscriptionDenied) and exc.signup_required,
                                       "message": "Free recording allowance unavailable. Please try again or create an account."})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        lock_client, lock_key, lock_token = None, "", ""
    else:
        lock_client, lock_key, lock_token = await _acquire_stream_lock(
            websocket.app.state.cache_service, user_id_hash
        )
    if lock_client is False:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="A recording is already active"
        )
        return

    if not guest:
        await websocket.accept()
    bytes_received = 0
    guest_forwarded_bytes = 0
    guest_audio_ambiguous = False
    guest_deadline = asyncio.get_running_loop().time() + GUEST_WALL_SECONDS
    guest_failure = asyncio.Event()
    guest_correction_error: Optional[Exception] = None
    peak_pcm = 0
    transcript_deltas: list[str] = []
    provider_request_id = uuid.uuid4().hex
    provider_done = False
    billing_task: Optional[asyncio.Task[None]] = None
    chat_id = (websocket.query_params.get("chat_id") or None) if not guest else None
    correction_context = (
        "workflow"
        if not guest and websocket.query_params.get("correction_context") == "workflow"
        else None
    )
    # First-party stream: account billing or guest atomic reservations guard
    # the audio and every background correction provider attempt.
    # Audio, raw text and corrected batches stay ephemeral in this connection.
    async def correct_batch(text: str, language: Optional[str]) -> dict[str, str]:
        nonlocal guest_correction_error
        token = correction_accountant.set(guest) if guest else None
        try:
            return await _correct_segment(websocket, text, language, correction_context)
        except Exception as exc:
            if guest and isinstance(exc, (CorrectionAccountingError, GuestTranscriptionDenied)):
                cause = exc.__cause__ if isinstance(exc, CorrectionAccountingError) else exc
                guest_correction_error = cause if isinstance(cause, GuestTranscriptionDenied) else exc
                guest_failure.set()
            raise
        finally:
            if token is not None:
                correction_accountant.reset(token)

    def guest_correction_success_guard() -> None:
        # A later rejected batch must not turn an earlier successful batch into
        # an apparently successful final correction containing unadmitted text.
        if guest_correction_error is not None:
            raise guest_correction_error

    async def correction_progress(processed_chars: int) -> None:
        # Progress is additive protocol metadata. Existing clients retain their
        # live raw preview and wait for the single final correction result.
        await websocket.send_json(
            {"type": "correction.progress", "processed_chars": processed_chars}
        )

    streaming_correction = (
        StreamingTranscriptCorrection(correct_batch, correction_progress)
        if _correction_enabled(correction_context)
        else None
    )
    try:
        secret_request = websocket.app.state.secrets_manager.get_secret("kv/data/providers/mistral_ai", "api_key")
        mistral_key = await asyncio.wait_for(secret_request, timeout=10) if guest else await secret_request
        if not mistral_key:
            raise RuntimeError("Realtime transcription is unavailable")

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=GUEST_IDLE_SECONDS if guest else 90)
        provider_url = f"{MISTRAL_REALTIME_URL}?model={MISTRAL_REALTIME_MODEL}"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                provider_url,
                headers={"Authorization": f"Bearer {mistral_key}"},
                heartbeat=20,
                max_msg_size=2 * 1024 * 1024,
            ) as provider:
                async def receive_setup_event() -> dict[str, Any]:
                    if not guest:
                        return await provider.receive_json()
                    remaining = guest_deadline - asyncio.get_running_loop().time()
                    try:
                        return await asyncio.wait_for(
                            provider.receive_json(), timeout=max(0, min(GUEST_IDLE_SECONDS, remaining)),
                        )
                    except asyncio.TimeoutError:
                        raise GuestTranscriptionDenied("recording_timeout") from None

                created = await receive_setup_event()
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
                            "target_streaming_delay_ms": REALTIME_STREAMING_DELAY_MS,
                        },
                    }
                )
                updated = await receive_setup_event()
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
                guest_failure_wait = asyncio.create_task(guest_failure.wait()) if guest else None
                last_client_activity = asyncio.get_running_loop().time()
                input_ended = False
                try:
                    while not provider_done:
                        receive_tasks = {client_receive, provider_receive}
                        if guest_failure_wait is not None:
                            receive_tasks.add(guest_failure_wait)
                        now = asyncio.get_running_loop().time()
                        timeout_seconds = min(guest_deadline - now, last_client_activity + GUEST_IDLE_SECONDS - now) if guest else None
                        done, _ = await asyncio.wait(
                            receive_tasks, timeout=max(0, timeout_seconds) if timeout_seconds is not None else None,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if guest and (not done or guest_failure_wait in done):
                            if guest_correction_error:
                                raise guest_correction_error
                            raise GuestTranscriptionDenied("recording_timeout")
                        if client_receive in done:
                            raw_message = client_receive.result()
                            last_client_activity = asyncio.get_running_loop().time()
                            if guest and len(raw_message) > MAX_CHUNK_BYTES * 2:
                                raise GuestTranscriptionDenied("audio_chunk_limit")
                            message = json.loads(raw_message)
                            event_type = message.get("type")
                            if event_type == "input_audio.append":
                                encoded = message.get("audio")
                                if not isinstance(encoded, str):
                                    raise ValueError("Audio chunk is missing")
                                decoded = base64.b64decode(encoded, validate=True)
                                if not decoded or len(decoded) > MAX_CHUNK_BYTES:
                                    raise ValueError("Audio chunk size is invalid")
                                if guest and (input_ended or len(decoded) % 2):
                                    raise GuestTranscriptionDenied("invalid_audio_chunk")
                                if guest:
                                    await guest.reserve_audio((guest_forwarded_bytes + len(decoded)) / PCM_BYTES_PER_SECOND)
                                bytes_received += len(decoded)
                                peak_pcm = max(peak_pcm, max((abs(sample) for (sample,) in
                                    struct.iter_unpack("<h", decoded[:len(decoded) // 2 * 2])), default=0))
                                if (
                                    bytes_received
                                    > PCM_BYTES_PER_SECOND * MAX_AUDIO_SECONDS
                                ):
                                    raise ValueError("Recording is too long")
                                if guest:
                                    guest_audio_ambiguous = True
                                await provider.send_json(
                                    {"type": event_type, "audio": encoded}
                                )
                                if guest:
                                    guest_forwarded_bytes += len(decoded)
                                    guest_audio_ambiguous = False
                            elif event_type == "input_audio.end":
                                if guest and input_ended:
                                    raise GuestTranscriptionDenied("invalid_audio_end")
                                input_ended = True
                                await provider.send_json({"type": "input_audio.end"})
                            elif event_type == "session.metadata" and not guest:
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
                                if guest and not guest_forwarded_bytes:
                                    delta = ""
                                if delta:
                                    if guest and sum(map(len, transcript_deltas)) + len(delta) > GUEST_MAX_TRANSCRIPT_CHARACTERS:
                                        raise GuestTranscriptionDenied("transcript_limit")
                                    transcript_deltas.append(delta)
                                    if streaming_correction is not None:
                                        streaming_correction.append(delta, event.get("language"))
                                    await websocket.send_json(
                                        {"type": event_type, "text": delta}
                                    )
                            elif event_type == "transcription.done":
                                provider_final_text = sanitize_text_simple(
                                    str(event.get("text") or "").strip(),
                                    log_prefix="[AudioRealtime][Mistral] ",
                                )
                                # Realtime text is delivered through deltas. The
                                # done payload can contain only the final window;
                                # never let it replace earlier streamed speech.
                                streamed_transcript = "".join(transcript_deltas).strip()
                                raw_transcript = (
                                    provider_final_text
                                    if provider_final_text.startswith(streamed_transcript)
                                    else streamed_transcript
                                )
                                if guest and not guest_forwarded_bytes:
                                    raw_transcript = ""
                                if guest and len(raw_transcript) > GUEST_MAX_TRANSCRIPT_CHARACTERS:
                                    raise GuestTranscriptionDenied("transcript_limit")
                                language = event.get("language")
                                if guest and isinstance(language, str) and len(language) > 64:
                                    language = None
                                usage = (
                                    event.get("usage")
                                    if isinstance(event.get("usage"), dict)
                                    else {}
                                )
                                audio_seconds = float(
                                    usage.get("prompt_audio_seconds")
                                    or bytes_received / PCM_BYTES_PER_SECOND
                                )
                                logger.info(
                                    "Realtime transcription completed: audio_bytes=%d peak_pcm=%d "
                                    "provider_seconds=%.3f transcript_chars=%d "
                                    "streamed_chars=%d provider_final_chars=%d",
                                    bytes_received, peak_pcm, audio_seconds, len(raw_transcript),
                                    len(streamed_transcript), len(provider_final_text),
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
                                    guest.settle_audio(guest_forwarded_bytes / PCM_BYTES_PER_SECOND) if guest else _bill_realtime_usage(
                                        websocket,
                                        user_id=user_id,
                                        user_id_hash=user_id_hash,
                                        request_id=provider_request_id,
                                        audio_seconds=audio_seconds,
                                        chat_id=chat_id,
                                    )
                                )
                                if raw_transcript:
                                    correction = _correct_and_send(
                                        websocket, raw_transcript, language, correction_context, streaming_correction,
                                        guest_correction_success_guard if guest else None,
                                    )
                                    if guest:
                                        await asyncio.wait_for(correction, timeout=max(0.001, guest_deadline - asyncio.get_running_loop().time()))
                                    else:
                                        await correction
                                else:
                                    await websocket.send_json(
                                        {"type": "correction.failed"}
                                    )
                                if guest_correction_error:
                                    raise guest_correction_error
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
                    if guest_failure_wait is not None:
                        guest_failure_wait.cancel()
                        await asyncio.gather(guest_failure_wait, return_exceptions=True)
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
                {"type": "session.error", "message": ("Free recording unavailable. Please try again or create an account." if guest else str(exc)[:240]),
                 **({"code": exc.code if isinstance(exc, GuestTranscriptionDenied) else "anonymous_meter_unavailable",
                     "signup_required": isinstance(exc, GuestTranscriptionDenied) and exc.signup_required} if guest else {})}
            )
        except Exception:
            pass
    finally:
        if streaming_correction is not None:
            await streaming_correction.cancel()
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
        if (bytes_received or guest) and billing_task is None:
            try:
                if guest:
                    if guest_audio_ambiguous:
                        await guest.settle_ambiguous_audio()
                    else:
                        await guest.settle_audio(guest_forwarded_bytes / PCM_BYTES_PER_SECOND)
                else:
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
        if guest:
            await guest.release_locks()
        else:
            await _release_stream_lock(lock_client, lock_key, lock_token)
