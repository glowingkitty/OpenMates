"""Credential-free voice call socket for signed-out visitors (guests).

Access model: first-party client surface only. It is not part of the public
developer API and is not reachable with account credentials: a connection that
carries a session cookie, token or Authorization header is refused. Only the
official cloud serves it, from an allowed browser Origin.

The server only turns microphone audio into finished turn text. It creates no
chat, message, user or call registry row and stores no audio or text. The
browser sends each finished turn through the guest chat stream and plays the
reply through ``POST /v1/anonymous/speech``. Speech-to-text minutes are metered
on the same anonymous free allowance as guest chat and composer dictation
(``GuestTranscriptionMeter``): identity/IP admission, a credit reservation before audio reaches the provider, settlement on end, and the
admission locks are released on every exit.

Protocol (JSON text frames)
  client -> server
    {"type": "start", "privacy_ack_version": 3, "language"?: str}   first frame
    {"type": "mic_audio", "data": <base64 PCM s16le 16 kHz mono, <= 128 KiB>}
    {"type": "audio_stream_end"}   flush a muted microphone
    {"type": "ping"}               keep-alive while the microphone is muted
    {"type": "hangup"}
  server -> client
    {"type": "ready", "call_id", "provider", "model", "input_sample_rate",
     "max_call_seconds", "billing_basis": "anonymous_free_allowance"}
    {"type": "transcript", "role": "user", "call_id", "message_id",
     "user_message_id", "turn_id", "created_at", "text", "final": bool,
     "interrupted": false}
    {"type": "waiting", "call_id", "active", "line"}
    {"type": "error", "code", "stage", "signup_required", "message"}
    {"type": "ended", "reason": "user" | "time_limit"}
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import math
import time
import uuid
from typing import Any

import aiohttp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from backend.apps.audio.pricing import calculate_realtime_transcription_credits
from backend.core.api.app.routes.audio_realtime import _origin_is_allowed
from backend.core.api.app.routes.anonymous_speech import GUEST_SPEECH_VOICE_KEY
from backend.core.api.app.routes.voice_call_waiting import VoiceWaiting
from backend.core.api.app.services.anonymous_free_usage_service import AnonymousUsageTransactionError
from backend.core.api.app.services.guest_transcription_meter import (
    GuestTranscriptionDenied, GuestTranscriptionMeter,
)
from backend.shared.providers.voxtral_voice import VoxtralVoiceSession
from backend.shared.providers.transcript_correction_accounting import CorrectionAccountingError, correction_accountant
from backend.shared.python_utils.voice_call_intent import is_prerecorded_clip_echo
from backend.shared.python_utils.voice_pause_decision import (
    PauseDecision, classify_metered_voice_pause, instant_feedback_enabled,
)
from backend.shared.testing.voice_call_fixture import (
    IsolatedVoxtralVoiceFixture, isolated_voice_fixture_enabled, isolated_voice_intent_fixture,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")

PRIVACY_ACK_VERSION = 3
MAX_CALL_SECONDS = 600
MAX_START_BYTES = 4_000
MAX_EVENT_BYTES = 384_000
MAX_AUDIO_CHUNK = 128 * 1024
MAX_TURN_CHARS = 8_000
PCM_BYTES_PER_SECOND = 32_000
AUDIO_JITTER_SECONDS = 12
GUEST_TURN_SILENCE_SECONDS = 1.2
GUEST_LOCAL_ENDPOINT_GRACE_SECONDS = 0.35
LOCK_RENEW_SECONDS = 60
LOCK_LEASE_SECONDS = 180
_RENEW_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)
_SIGNUP_MESSAGE = "The free allowance cannot cover this call. Create an account to keep talking."


class GuestCallMeter(GuestTranscriptionMeter):
    """Dictation meter whose audio reservation uses the call-length bound."""

    async def reserve_audio(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds > MAX_CALL_SECONDS:
            raise GuestTranscriptionDenied("call_time_limit")
        target = calculate_realtime_transcription_credits(duration_seconds=seconds)
        additional = target - self.audio_reserved
        if additional <= 0:
            return
        result = await self.service.reserve_operation(
            parent_request_id=self.request_id,
            operation_id=self.request_id + f":pcm:{self.audio_reserved}",
            charge_id=self.audio_charge_id,
            quoted_credits=additional,
        )
        if not result.accepted:
            raise GuestTranscriptionDenied(result.reason or "anonymous_usage_limit")
        self.audio_reserved = target

    async def renew_locks(self) -> None:
        for client, key, token in self.locks:
            await client.eval(_RENEW_SCRIPT, 1, key, token, LOCK_LEASE_SECONDS)


class _Turn:
    def __init__(self) -> None:
        self.message_id = uuid.uuid4().hex
        self.created_at = int(time.time())
        self.text = ""
        self.deadline: float | None = None
        self.separate_next = False
        self.clip_text = ""


def _refused_credentials(websocket: WebSocket) -> bool:
    return ("auth_refresh_token" in websocket.cookies or "token" in websocket.query_params
            or "authorization" in websocket.headers)


async def _provider(websocket: WebSocket) -> Any:
    if isolated_voice_fixture_enabled():
        return IsolatedVoxtralVoiceFixture()
    key = await asyncio.wait_for(
        websocket.app.state.secrets_manager.get_secret("kv/data/providers/mistral_ai", "api_key"), 10)
    if not key:
        raise RuntimeError("Voice provider unavailable")
    return VoxtralVoiceSession(key)


async def _guest_pause_decision(text: str, websocket: WebSocket, meter: GuestCallMeter,
                                *, with_feedback: bool = False) -> PauseDecision:
    if isolated_voice_fixture_enabled():
        intent = isolated_voice_intent_fixture(text)
        return PauseDecision("finished", "wait" if intent == "wait" else "resume" if intent == "resume" else "none",
                             0.5, "answering" if with_feedback else "none", "en" if with_feedback else None)
    token = correction_accountant.set(meter)
    try:
        options = {"with_feedback": True} if with_feedback else {}
        return await classify_metered_voice_pause(text, websocket.app.state.secrets_manager, **options)
    except CorrectionAccountingError as error:
        if isinstance(error.__cause__, GuestTranscriptionDenied):
            raise error.__cause__ from None
        raise
    finally:
        correction_accountant.reset(token)


async def _read_start(websocket: WebSocket) -> dict[str, Any]:
    raw = await asyncio.wait_for(websocket.receive_text(), 10)
    if len(raw.encode("utf-8")) > MAX_START_BYTES:
        raise ValueError("Call start exceeds limit")
    event = json.loads(raw)
    if not isinstance(event, dict) or event.get("type") != "start":
        raise ValueError("Call start required")
    return event


def _error_event(code: str, stage: str, *, signup_required: bool = False) -> dict[str, Any]:
    return {"type": "error", "code": code, "stage": stage, "signup_required": signup_required,
            "message": _SIGNUP_MESSAGE if signup_required else "Call unavailable. Please try again."}


# First-party client surface (credential-free guest); outside the developer API.
@router.websocket("/voice-call/guest")
async def guest_voice_call(websocket: WebSocket) -> None:
    from backend.core.api.app.utils.server_mode import validate_request_domain

    if _refused_credentials(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Credentials not allowed")
        return
    if not _origin_is_allowed(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    if validate_request_domain(websocket)[1]:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Not available on this server")
        return
    await websocket.accept()
    try:
        start = await _read_start(websocket)
        acknowledged = start.get("privacy_ack_version") == PRIVACY_ACK_VERSION and not isinstance(
            start.get("privacy_ack_version"), bool)
    except (ValueError, asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid_start")
        return
    if not acknowledged:
        await websocket.send_json(_error_event("voice_ack_required", "start_validation"))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="voice_ack_required")
        return

    meter = GuestCallMeter(websocket)
    feedback_enabled = instant_feedback_enabled(start)
    forwarded_bytes = 0
    audio_ambiguous = False
    provider: Any = None
    stage = "admission"
    try:
        try:
            await asyncio.wait_for(meter.admit(), timeout=10)
        except GuestTranscriptionDenied as exc:
            await websocket.send_json(_error_event(exc.code, stage, signup_required=exc.signup_required))
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except (AnonymousUsageTransactionError, RuntimeError, asyncio.TimeoutError) as exc:
            logger.warning("Guest call admission unavailable: %s", type(exc).__name__)
            await websocket.send_json(_error_event("anonymous_meter_unavailable", stage))
            await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
            return
        stage = "provider_open"
        provider = await _provider(websocket)
        await provider.open()
        stage = "active"
        call_id = uuid.uuid4().hex
        await websocket.send_json({
            "type": "ready", "call_id": call_id, "provider": "mistral", "model": provider.model,
            "input_sample_rate": 16000, "max_call_seconds": MAX_CALL_SECONDS,
            "billing_basis": "anonymous_free_allowance"})
        loop = asyncio.get_running_loop()
        started = last_renew = loop.time()
        local_endpoint: float | None = None
        closed_local_turn = False
        client_receive = asyncio.create_task(websocket.receive_text())
        provider_receive = asyncio.create_task(provider.receive())
        turn: _Turn | None = None
        waiting = VoiceWaiting()
        feedback_clip: dict[str, object] | None = None
        feedback_clip_text = ""
        feedback_until = 0.0

        async def send_feedback_event(event: dict[str, Any]) -> None:
            nonlocal feedback_clip, feedback_clip_text, feedback_until
            clip = event.get("clip")
            if isinstance(clip, dict):
                from backend.apps.audio.assistant_speech.acknowledgements import prerecorded_clip_text
                feedback_clip = clip
                feedback_clip_text = prerecorded_clip_text(str(clip["asset_url"]))
                feedback_until = loop.time() + 5.0
            await websocket.send_json(event)

        try:
            while True:
                now = loop.time()
                if now - started >= MAX_CALL_SECONDS:
                    await websocket.send_json({"type": "ended", "reason": "time_limit"})
                    break
                if now - last_renew >= LOCK_RENEW_SECONDS:
                    await meter.renew_locks()
                    last_renew = now
                wakeups = [started + MAX_CALL_SECONDS, last_renew + LOCK_RENEW_SECONDS]
                if turn is not None and turn.deadline is not None:
                    wakeups.append(turn.deadline)
                if local_endpoint is not None and local_endpoint > now:
                    wakeups.append(local_endpoint)
                done, _ = await asyncio.wait({client_receive, provider_receive},
                                             timeout=max(0.0, min(wakeups) - now),
                                             return_when=asyncio.FIRST_COMPLETED)
                if client_receive in done:
                    raw = client_receive.result()
                    if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
                        raise ValueError("Call event exceeds limit")
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError("Invalid call event")
                    kind = event.get("type")
                    if kind == "hangup":
                        await websocket.send_json({"type": "ended", "reason": "user"})
                        break
                    if kind == "mic_audio":
                        local_endpoint = None
                        data = event.get("data")
                        if not isinstance(data, str):
                            raise ValueError("Audio chunk is missing")
                        chunk = base64.b64decode(data, validate=True)
                        if not chunk or len(chunk) > MAX_AUDIO_CHUNK or len(chunk) % 2:
                            raise ValueError("Audio chunk is invalid")
                        if forwarded_bytes + len(chunk) > (
                                loop.time() - started + AUDIO_JITTER_SECONDS) * PCM_BYTES_PER_SECOND:
                            raise ValueError("Audio stream exceeds real-time rate")
                        await meter.reserve_audio((forwarded_bytes + len(chunk)) / PCM_BYTES_PER_SECOND)
                        audio_ambiguous = True
                        await provider.send_audio(data)
                        forwarded_bytes += len(chunk)
                        audio_ambiguous = False
                    elif kind == "audio_stream_end":
                        await provider.end_audio()
                        if event.get("verified_silence") is True and forwarded_bytes:
                            local_endpoint = loop.time() + GUEST_LOCAL_ENDPOINT_GRACE_SECONDS
                    elif kind != "ping":
                        raise ValueError("Unknown call event")
                    client_receive = asyncio.create_task(websocket.receive_text())
                if provider_receive in done:
                    event = provider_receive.result()
                    kind = event.get("type")
                    if kind == "turn.start":
                        closed_local_turn = False
                        if turn is None:
                            turn = _Turn()
                        else:
                            # A provider can split a thinking pause into several turns.
                            turn.separate_next = bool(turn.text)
                        turn.deadline = None
                    elif kind == "transcription.text.delta":
                        delta = event.get("text")
                        if not isinstance(delta, str):
                            raise ValueError("Invalid transcript delta")
                        if delta and not closed_local_turn:
                            if turn is None:
                                turn = _Turn()
                            if not turn.clip_text and loop.time() <= feedback_until:
                                turn.clip_text = feedback_clip_text
                            turn.deadline = None
                            separator = " " if (turn.separate_next and turn.text
                                                and not turn.text[-1].isspace()
                                                and not delta[0].isspace()) else ""
                            turn.separate_next = False
                            turn.text += separator + delta
                            if len(turn.text) > MAX_TURN_CHARS:
                                raise GuestTranscriptionDenied("transcript_limit")
                            if not is_prerecorded_clip_echo(turn.text, turn.clip_text):
                                if turn.clip_text and feedback_clip is not None:
                                    await websocket.send_json({"type": "voice_feedback_stop", "clip": feedback_clip})
                                    feedback_clip = None
                                await _send_transcript(websocket, call_id, turn, final=False)
                    elif kind == "turn.end":
                        if turn is not None:
                            turn.deadline = loop.time() + GUEST_TURN_SILENCE_SECONDS
                    elif kind == "turn.resume":
                        closed_local_turn = False
                        local_endpoint = None
                        if turn is not None:
                            turn.deadline = None
                    elif kind == "transcription.done":
                        raise RuntimeError("Voice transcription session ended")
                    provider_receive = asyncio.create_task(provider.receive())
                now = loop.time()
                local_finished = local_endpoint is not None and now >= local_endpoint
                if turn is not None and (local_finished or (turn.deadline is not None and now >= turn.deadline)):
                    if is_prerecorded_clip_echo(turn.text, turn.clip_text):
                        turn = None
                        local_endpoint = None
                    elif turn.text.strip():
                        options = {"with_feedback": True} if feedback_enabled else {}
                        decision = await _guest_pause_decision(turn.text, websocket, meter, **options)
                        # Guest calls do not store a replayable previous answer.
                        intent = decision.intent if decision.intent in {"wait", "resume"} else "none"
                        clip = None
                        if feedback_enabled and (intent == "wait" or not waiting.active):
                            from backend.apps.ai.assistant_speech.voice_status import select_categorized_voice_feedback
                            clip = select_categorized_voice_feedback(
                                voice_profile_id=GUEST_SPEECH_VOICE_KEY,
                                category="wait" if intent == "wait" else decision.feedback,
                                language=decision.feedback_language, seed=turn.message_id,
                            )
                        discard, words = await waiting.route(
                            turn.text, intent, send=send_feedback_event, call_id=call_id,
                            clip=clip, categorized=feedback_enabled,
                        )
                        if discard is None:
                            turn.text = words
                            if clip:
                                await send_feedback_event({"type": "voice_feedback", "clip": clip})
                            await _send_transcript(websocket, call_id, turn, final=True)
                        local_endpoint = None
                        closed_local_turn = local_finished
                        turn = None
                    elif not local_finished:
                        turn = None
        finally:
            client_receive.cancel()
            provider_receive.cancel()
            await asyncio.gather(client_receive, provider_receive, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    except GuestTranscriptionDenied as exc:
        await _send_error(websocket, _error_event(exc.code, stage, signup_required=exc.signup_required))
    except (ValueError, binascii.Error):
        await _send_error(websocket, _error_event("invalid_event", stage))
    except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        logger.warning("Guest voice call ended with %s", type(exc).__name__)
        await _send_error(websocket, _error_event("call_unavailable", stage))
    finally:
        try:
            if provider is not None:
                await provider.close()
        finally:
            try:
                await _settle(meter, forwarded_bytes, audio_ambiguous)
            finally:
                await meter.release_locks()
        try:
            await websocket.close()
        except RuntimeError:
            logger.debug("Guest voice call socket already closed")


async def _send_transcript(websocket: WebSocket, call_id: str, turn: _Turn, *, final: bool) -> None:
    await websocket.send_json({
        "type": "transcript", "role": "user", "call_id": call_id, "message_id": turn.message_id,
        "user_message_id": turn.message_id, "turn_id": turn.message_id, "created_at": turn.created_at,
        "text": turn.text, "final": final, "interrupted": False})


async def _send_error(websocket: WebSocket, event: dict[str, Any]) -> None:
    try:
        await websocket.send_json(event)
    except (RuntimeError, WebSocketDisconnect):
        logger.debug("Guest voice call error frame not delivered")


async def _settle(meter: GuestCallMeter, forwarded_bytes: int, ambiguous: bool) -> None:
    """Settle reserved audio: at the reservation when a send was in doubt."""
    try:
        if ambiguous:
            await meter.settle_ambiguous_audio()
        else:
            await meter.settle_audio(forwarded_bytes / PCM_BYTES_PER_SECOND)
    except (AnonymousUsageTransactionError, RuntimeError):
        logger.exception("Guest voice call audio settlement failed")
