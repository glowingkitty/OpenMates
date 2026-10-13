"""Authenticated first-party voice calls bound to one encrypted personal chat.

Plaintext chat context, microphone audio and transcripts exist only in this
WebSocket session and the disclosed voice provider. Durable chat writes use the
separate client-encrypted message path.
"""

from __future__ import annotations

import asyncio
from collections import deque
from decimal import Decimal
import hashlib
import json
import logging
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from backend.core.api.app.routes.audio_realtime import _browser_request_is_allowed
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.routes.video_call_experiment import (
    GEMINI_MODEL, INPUT_RATES, LOCK_RENEW_SECONDS, MIN_VOICE_HEADROOM,
    UsageLedger, _acquire_lock, _authoritative_credits, _billing, _credits_for,
    _finish_accepted_job, _release_lock, _renew_lock, _session_still_valid,
)
from backend.core.api.app.services.direct_chat_access import is_direct_chat
from backend.core.api.app.utils.server_mode import is_payment_enabled
from backend.shared.providers.gemini_live_voice import GeminiLiveVoiceSession
from backend.shared.providers.live_voice import LiveVoiceSession
from backend.shared.python_utils.voice_call_registry import (
    finalize_active_call, issue_message_id, register_active_call, renew_active_call,
)
from backend.shared.testing.voice_call_fixture import IsolatedGeminiVoiceFixture, isolated_voice_fixture_enabled


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")
MAX_START_BYTES = 30_000
MAX_CONTEXT_CHARS = 20_000
MAX_TEXT_CHARS = 8_000
MAX_AUDIO_CHUNK = 128 * 1024
MAX_QUEUED_INPUT_BYTES = 2 * 1024 * 1024
MAX_PENDING_TRANSCRIPTS = 32
AUDIO_TOKENS_PER_SECOND_ADMISSION = Decimal(40)  # Conservative over Google's documented 32 tokens/s.
MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _timestamp() -> int:
    return int(time.time())


def _ordered_message_id(last: int = 0) -> tuple[str, int]:
    """Return a monotonic UUIDv7 so equal-second chat rows retain call order."""
    value = max(int(time.time() * 1000) << 80 | (7 << 76) | (2 << 62) | (uuid.uuid4().int & ((1 << 62) - 1)), last + 1)
    return str(uuid.UUID(int=value)), value


def _context(value: Any) -> tuple[str, list[dict[str, str]]]:
    if not isinstance(value, dict):
        raise ValueError("Invalid call context")
    summary = value.get("summary") or ""
    messages = value.get("messages") or []
    if not isinstance(summary, str) or not isinstance(messages, list) or len(messages) > 30:
        raise ValueError("Invalid call context")
    total = len(summary)
    if len(summary) > 4000:
        raise ValueError("Call context exceeds limit")
    clean: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant") or not isinstance(item.get("text"), str):
            raise ValueError("Invalid call context")
        text = item["text"]
        if not text or len(text) > 4000:
            raise ValueError("Invalid call context")
        total += len(text)
        clean.append({"role": item["role"], "text": text})
    if total > MAX_CONTEXT_CHARS:
        raise ValueError("Call context exceeds limit")
    return summary, clean


def _start(message: str) -> tuple[str, str, list[dict[str, str]]]:
    if len(message.encode("utf-8")) > MAX_START_BYTES:
        raise ValueError("Call start exceeds limit")
    event = json.loads(message)
    if not isinstance(event, dict) or event.get("type") != "start":
        raise ValueError("Call start required")
    chat_id = event.get("chat_id")
    try:
        chat_id = str(uuid.UUID(chat_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid chat identity") from exc
    summary, messages = _context(event.get("context"))
    return chat_id, summary, messages


def _output_transcription(segments: list[tuple[tuple[float, float] | None, str]],
                          event: dict[str, Any]) -> str:
    """Assemble output deltas; only identical audio spans identify revisions."""
    fragment = event["text"]
    start = _audio_offset(event.get("startOffset"))
    end = _audio_offset(event.get("endOffset"))
    span = (start, end) if start is not None and end is not None and end > start else None
    if span is not None:
        for index, (previous_span, _) in enumerate(segments):
            if previous_span == span:
                segments[index] = (span, fragment)
                break
        else:
            segments.append((span, fragment))
    else:
        segments.append((None, fragment))
    result = "".join(text for _, text in segments)
    if len(result) > MAX_TEXT_CHARS:
        raise TranscriptLimitError("Transcript exceeds call limit")
    return result


class TranscriptLimitError(ValueError):
    pass


def _bounded_transcript(value: str) -> str:
    if len(value) > MAX_TEXT_CHARS:
        raise TranscriptLimitError("Transcript exceeds call limit")
    return value


def _audio_offset(value: Any) -> float | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", value) if isinstance(value, str) else None
    return float(match.group(1)) if match else None


def _unsettled_audio_credits(audio_bytes: int, settled_audio_bytes: int) -> int:
    """Admission reserve only; actual charges always use provider token usage."""
    if audio_bytes <= settled_audio_bytes:
        return 0
    seconds = Decimal(audio_bytes - settled_audio_bytes) / Decimal(32000)
    estimated_tokens = seconds * AUDIO_TOKENS_PER_SECOND_ADMISSION
    return _credits_for(estimated_tokens * INPUT_RATES["AUDIO"] / Decimal(1_000_000))


async def _personal_chat(websocket: WebSocket, chat_id: str, user_id: str) -> bool:
    chat = await websocket.app.state.directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
    if not isinstance(chat, dict) or chat.get("id") != chat_id or chat.get("storage_state") == "deleting":
        return False
    if chat.get("hashed_team_id") or is_direct_chat(chat):
        return False
    return chat.get("hashed_user_id") == hashlib.sha256(user_id.encode()).hexdigest()


async def _charge_voice(websocket: WebSocket, ledger: UsageLedger, *, user_id: str, user_hash: str, call_id: str) -> None:
    due = _credits_for(ledger.gemini_cost) - ledger.charged
    if due <= 0:
        return
    checkpoint = ledger.checkpoint + 1
    result = await _billing(websocket).charge_user_credits(
        user_id=user_id, user_id_hash=user_hash, credits_to_deduct=due,
        app_id="ai", skill_id="voice_call",
        idempotency_key=f"voice-call:{call_id}:{checkpoint}",
        require_full_charge=True,
        usage_details={
            "usage_type": "voice_call", "model": GEMINI_MODEL,
            "provider_cost_usd": float(ledger.gemini_cost),
            "gemini_input_tokens": ledger.prompt_tokens,
            "gemini_output_tokens": ledger.response_tokens,
            "gemini_context_tokens": ledger.context_tokens,
            "charged_credits": due,
        },
    )
    ledger.checkpoint = checkpoint
    ledger.charged += int(result.get("charged_credits", due))


async def _provider(websocket: WebSocket) -> LiveVoiceSession:
    if isolated_voice_fixture_enabled():
        return IsolatedGeminiVoiceFixture()
    key = await websocket.app.state.secrets_manager.get_secret("kv/data/providers/google_ai_studio", "api_key")
    if not key:
        raise RuntimeError("Voice provider unavailable")
    return GeminiLiveVoiceSession(key)


@router.websocket("/voice-call")
async def voice_call(websocket: WebSocket, auth_data: dict[str, Any] | None = Depends(get_current_user_ws)) -> None:
    """First-party client only; no developer API or team-chat access."""
    if auth_data is None:
        return
    if not await _browser_request_is_allowed(websocket, auth_data):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    user_id = auth_data["user_id"]
    session_id = auth_data.get("session_hash")
    if not isinstance(session_id, str) or not session_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session unavailable")
        return
    await websocket.accept()
    call_id = uuid.uuid4().hex
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    chat_id = ""
    lock_client: Any = None
    lock_key = lock_token = ""
    lease_task: asyncio.Task[None] | None = None
    registry_task: asyncio.Task[None] | None = None
    client_receive: asyncio.Task[str] | None = None
    provider_receive: asyncio.Task[dict[str, Any]] | None = None
    provider: LiveVoiceSession | None = None
    ledger = UsageLedger()
    registered = False
    started = time.monotonic()
    send_lock = asyncio.Lock()
    turn_user_id: str | None = None
    turn_user_text = ""
    turn_user_created = 0
    turn_user_final = False
    turn_user_authoritative = False
    turn_assistant_id: str | None = None
    turn_assistant_text = ""
    turn_assistant_segments: list[tuple[tuple[float, float] | None, str]] = []
    turn_assistant_created = 0
    last_message_order = 0
    activity_seen_for_current = False
    turn_completed = False
    last_activity_offset = -1.0
    pending_late_users: deque[tuple[str, int, str]] = deque()
    seen_text_ids: dict[str, tuple[str, int]] = {}
    audio_bytes = 0
    last_finalized_audio_bytes = 0
    settled_audio_bytes = 0
    resume_handle: str | None = None
    handoff_deadline = 0.0
    queued_inputs: deque[tuple[str, str]] = deque()
    queued_bytes = 0
    last_auth_check = 0.0

    async def send(event: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(event)

    async def issue(message_id: str, role: str) -> None:
        await issue_message_id(
            websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
            chat_id=chat_id, call_id=call_id, message_id=message_id, role=role,
        )

    async def user_turn(message_id: str | None = None, created_at: int | None = None) -> None:
        nonlocal turn_user_id, turn_user_text, turn_user_created, turn_user_final, turn_user_authoritative, last_message_order, activity_seen_for_current, turn_completed
        if turn_user_id is not None and not turn_user_authoritative:
            if len(pending_late_users) >= MAX_PENDING_TRANSCRIPTS:
                raise RuntimeError("Too many pending speech transcripts")
            pending_late_users.append((turn_user_id, turn_user_created, turn_user_text))
        if message_id is None:
            message_id, last_message_order = _ordered_message_id(last_message_order)
        else:
            last_message_order = max(last_message_order, uuid.UUID(message_id).int)
        turn_user_id = message_id
        turn_user_text = ""
        turn_user_created = created_at if created_at is not None else _timestamp()
        turn_user_final = False
        turn_user_authoritative = False
        activity_seen_for_current = False
        turn_completed = False
        await issue(turn_user_id, "user")

    async def emit_user(*, final: bool) -> None:
        nonlocal turn_user_final
        if turn_user_id is None or not turn_user_text:
            return
        turn_user_final = final
        await send({
            "type": "transcript", "role": "user", "call_id": call_id,
            "message_id": turn_user_id, "user_message_id": turn_user_id,
            "created_at": turn_user_created, "text": turn_user_text,
            "final": final, "interrupted": False,
        })

    async def emit_assistant(*, final: bool, interrupted: bool = False) -> None:
        if turn_assistant_id is None or not turn_assistant_text:
            return
        await send({
            "type": "transcript", "role": "assistant", "call_id": call_id,
            "message_id": turn_assistant_id, "user_message_id": turn_user_id,
            "created_at": turn_assistant_created, "text": turn_assistant_text,
            "final": final, "interrupted": interrupted,
        })

    async def assistant_turn() -> None:
        nonlocal turn_assistant_id, turn_assistant_text, turn_assistant_created, last_message_order
        if turn_assistant_id is None:
            turn_assistant_id, last_message_order = _ordered_message_id(last_message_order)
            turn_assistant_text = ""
            turn_assistant_segments.clear()
            turn_assistant_created = _timestamp()
            await issue(turn_assistant_id, "assistant")

    async def send_provider(kind: str, value: str) -> None:
        nonlocal queued_bytes
        if handoff_deadline:
            queued_bytes += len(value)
            if queued_bytes > MAX_QUEUED_INPUT_BYTES:
                raise ValueError("Provider handoff input overflow")
            queued_inputs.append((kind, value))
        elif kind == "audio":
            await provider.send_audio(value)  # type: ignore[union-attr]
        else:
            await provider.send_text(value)  # type: ignore[union-attr]

    async def registry_renewal() -> None:
        while True:
            await asyncio.sleep(LOCK_RENEW_SECONDS)
            await renew_active_call(
                websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
                chat_id=chat_id, call_id=call_id,
            )

    try:
        chat_id, summary, messages = _start(await asyncio.wait_for(websocket.receive_text(), timeout=10))
        if not await _personal_chat(websocket, chat_id, user_id):
            raise ValueError("Chat unavailable")
        if not await _session_still_valid(websocket, auth_data):
            raise ValueError("Session unavailable")
        if is_payment_enabled() and await _authoritative_credits(websocket, user_id) < MIN_VOICE_HEADROOM:
            raise ValueError("Insufficient credits")
        lock_client, lock_key, lock_token = await _acquire_lock(websocket, user_hash)
        lease_task = asyncio.create_task(_renew_lock(lock_client, lock_key, lock_token))
        await register_active_call(
            websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
            chat_id=chat_id, call_id=call_id,
        )
        registered = True
        registry_task = asyncio.create_task(registry_renewal())
        provider = await _provider(websocket)
        await provider.open(summary=summary, messages=messages)
        started = time.monotonic()
        await send({"type": "ready", "call_id": call_id, "model": provider.model,
                    "input_sample_rate": 16000, "output_sample_rate": 24000,
                    "audio_credits_per_minute": 27.6})
        client_receive = asyncio.create_task(websocket.receive_text())
        provider_receive = asyncio.create_task(provider.receive())
        while True:
            now = time.monotonic()
            if lease_task.done():
                await lease_task
            if registry_task.done():
                await registry_task
            if now - last_auth_check >= 5:
                if not await _session_still_valid(websocket, auth_data):
                    raise RuntimeError("Session expired or revoked")
                if is_payment_enabled():
                    pending = max(0, _credits_for(ledger.gemini_cost) - ledger.charged)
                    reserve = _unsettled_audio_credits(audio_bytes, settled_audio_bytes)
                    if await _authoritative_credits(websocket, user_id) < MIN_VOICE_HEADROOM + pending + reserve:
                        raise RuntimeError("Insufficient credits")
                last_auth_check = now
            if handoff_deadline and now >= handoff_deadline:
                raise RuntimeError("Voice provider handoff expired")
            done, _ = await asyncio.wait(
                {client_receive, provider_receive, lease_task, registry_task},
                timeout=1, return_when=asyncio.FIRST_COMPLETED,
            )
            if client_receive in done:
                incoming = json.loads(client_receive.result())
                if not isinstance(incoming, dict):
                    raise ValueError("Invalid call event")
                kind = incoming.get("type")
                if kind == "hangup":
                    await emit_assistant(final=True, interrupted=False)
                    await emit_user(final=True)
                    for late_id, late_created, late_text in pending_late_users:
                        if late_text:
                            await send({
                                "type": "transcript", "role": "user", "call_id": call_id,
                                "message_id": late_id, "user_message_id": late_id,
                                "created_at": late_created, "text": late_text,
                                "final": True, "interrupted": False,
                            })
                    await send({"type": "ended", "reason": "user"})
                    break
                if kind == "mic_audio":
                    encoded = incoming.get("data")
                    from backend.core.api.app.routes.video_call_experiment import _decode_media
                    chunk = _decode_media(encoded, max_bytes=MAX_AUDIO_CHUNK)
                    if len(chunk) % 2:
                        raise ValueError("PCM audio is invalid")
                    audio_bytes += len(chunk)
                    if audio_bytes > (now - started + 2) * 32000:
                        raise ValueError("Audio stream exceeds real-time rate")
                    if is_payment_enabled():
                        pending = max(0, _credits_for(ledger.gemini_cost) - ledger.charged)
                        reserve = _unsettled_audio_credits(audio_bytes, settled_audio_bytes)
                        if await _authoritative_credits(websocket, user_id) < MIN_VOICE_HEADROOM + pending + reserve:
                            raise RuntimeError("Insufficient credits")
                    if turn_user_id is None:
                        await user_turn()
                    await send_provider("audio", encoded)
                elif kind == "text_input":
                    message_id = incoming.get("message_id")
                    content = incoming.get("text")
                    created = incoming.get("created_at")
                    valid = (
                        isinstance(message_id, str) and bool(MESSAGE_ID.fullmatch(message_id))
                        and isinstance(content, str) and bool(content.strip()) and len(content) <= MAX_TEXT_CHARS
                        and not isinstance(created, bool) and isinstance(created, (int, float))
                    )
                    if valid:
                        try:
                            valid = uuid.UUID(message_id).version == 7
                        except ValueError:
                            valid = False
                    if valid:
                        created = int(created)
                        if created > 10_000_000_000:
                            created //= 1000
                        valid = abs(created - _timestamp()) <= 86400
                    if not valid:
                        await send({"type": "text_input_rejected", "message_id": message_id if isinstance(message_id, str) and len(message_id) <= 128 else None, "code": "invalid_text_input"})
                        client_receive = asyncio.create_task(websocket.receive_text())
                        continue
                    prior = seen_text_ids.get(message_id)
                    if prior is not None:
                        if prior != (content, created):
                            await send({"type": "text_input_rejected", "message_id": message_id, "code": "duplicate_message_id"})
                        else:
                            await send({
                                "type": "transcript", "role": "user", "call_id": call_id,
                                "message_id": message_id, "user_message_id": message_id,
                                "created_at": created, "text": content,
                                "final": True, "interrupted": False,
                            })
                        client_receive = asyncio.create_task(websocket.receive_text())
                        continue
                    if turn_assistant_id is not None:
                        await emit_assistant(final=True, interrupted=True)
                        await send({"type": "audio.interrupted"})
                        turn_assistant_id = None
                    await user_turn(message_id, created)
                    turn_user_text = content
                    turn_user_authoritative = True
                    await send_provider("text", content)
                    seen_text_ids[message_id] = (content, created)
                    await emit_user(final=True)
                else:
                    raise ValueError("Unknown call event")
                client_receive = asyncio.create_task(websocket.receive_text())
            if provider_receive in done:
                event = provider_receive.result()
                activity = event.get("voiceActivity")
                if isinstance(activity, dict) and activity.get("type") == "ACTIVITY_END":
                    last_finalized_audio_bytes = audio_bytes
                if isinstance(activity, dict) and activity.get("type") == "ACTIVITY_START":
                    offset = _audio_offset(activity.get("audioOffset"))
                    if offset is None or offset > last_activity_offset:
                        if offset is not None:
                            last_activity_offset = offset
                        if turn_user_id is None:
                            await user_turn(created_at=_timestamp())
                        elif activity_seen_for_current or turn_completed or turn_user_authoritative:
                            await user_turn(created_at=_timestamp())
                        else:
                            # First PCM packet reserved the ID before VAD. Anchor
                            # its ordering time to the provider's speech start.
                            turn_user_created = _timestamp()
                        activity_seen_for_current = True
                update = event.get("sessionResumptionUpdate")
                if isinstance(update, dict):
                    if update.get("resumable") is False:
                        resume_handle = None
                    elif update.get("resumable") is True and isinstance(update.get("newHandle"), str):
                        resume_handle = update["newHandle"]
                goaway = event.get("goAway")
                if isinstance(goaway, dict):
                    left = goaway.get("timeLeft")
                    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", left) if isinstance(left, str) else None
                    if not match or not resume_handle:
                        raise RuntimeError("Voice provider handoff unavailable")
                    handoff_deadline = now + float(match.group(1))
                    await provider.resume(resume_handle)
                    while queued_inputs:
                        queued_kind, queued_value = queued_inputs.popleft()
                        if queued_kind == "audio":
                            await provider.send_audio(queued_value)
                        else:
                            await provider.send_text(queued_value)
                    queued_bytes = 0
                    handoff_deadline = 0.0
                ledger.observe_gemini_output(event)
                usage = event.get("usageMetadata")
                if isinstance(usage, dict):
                    ledger.stage_gemini(usage)
                content = event.get("serverContent")
                if isinstance(content, dict):
                    if content.get("interrupted"):
                        await emit_assistant(final=True, interrupted=True)
                        await send({"type": "audio.interrupted"})
                        turn_assistant_id = None
                        turn_assistant_text = ""
                        turn_assistant_segments.clear()
                    interim_text = (content.get("interimInputTranscription") or {}).get("text")
                    if isinstance(interim_text, str) and interim_text:
                        if turn_user_id is None:
                            await user_turn()
                        turn_user_text = _bounded_transcript(interim_text)
                        await emit_user(final=False)
                    input_text = (content.get("inputTranscription") or {}).get("text")
                    if isinstance(input_text, str) and input_text:
                        last_finalized_audio_bytes = audio_bytes
                        if pending_late_users:
                            late_id, late_created, _ = pending_late_users.popleft()
                            await send({
                                "type": "transcript", "role": "user", "call_id": call_id,
                                "message_id": late_id, "user_message_id": late_id,
                                "created_at": late_created, "text": _bounded_transcript(input_text),
                                "final": True, "interrupted": False,
                            })
                        else:
                            if turn_user_id is None:
                                await user_turn()
                            turn_user_text = _bounded_transcript(input_text)
                            turn_user_authoritative = True
                            await emit_user(final=True)
                    output_transcription = content.get("outputTranscription") or {}
                    output_text = output_transcription.get("text") if isinstance(output_transcription, dict) else None
                    if isinstance(output_text, str) and output_text:
                        await assistant_turn()
                        turn_assistant_text = _output_transcription(turn_assistant_segments, output_transcription)
                        await emit_assistant(final=False)
                    for part in (content.get("modelTurn") or {}).get("parts") or []:
                        inline = part.get("inlineData") if isinstance(part, dict) else None
                        if isinstance(inline, dict) and str(inline.get("mimeType") or "").startswith("audio/") and isinstance(inline.get("data"), str):
                            await assistant_turn()
                            await send({"type": "audio_chunk", "data": inline["data"]})
                    if content.get("turnComplete"):
                        turn_completed = True
                        if turn_user_authoritative:
                            await emit_user(final=True)
                        await emit_assistant(final=True)
                        turn_assistant_id = None
                        turn_assistant_text = ""
                        turn_assistant_segments.clear()
                        if ledger.commit_gemini_turn():
                            await _charge_voice(websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id)
                            settled_audio_bytes = max(settled_audio_bytes, last_finalized_audio_bytes)
                            await send({"type": "usage", **{key: value for key, value in ledger.view(now - started).items() if key not in ("video_credits", "h3_generated_seconds", "h3_estimated_seconds", "video_credits_per_minute")}})
                provider_receive = asyncio.create_task(provider.receive())
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Exception messages and tracebacks can contain provider text or media.
        logger.warning("Voice call ended with %s call_id=%s", type(exc).__name__, call_id)
        try:
            if isinstance(exc, TranscriptLimitError):
                await send({"type": "error", "code": "transcript_limit", "message": "The transcript exceeded the call limit. Your call has ended."})
            else:
                await send({"type": "error", "code": "call_unavailable", "message": "Call unavailable. Your call has ended."})
        except Exception:
            pass
    finally:
        was_cancelled = False
        tasks = [task for task in (client_receive, provider_receive, lease_task, registry_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if provider is not None:
            try:
                await provider.close()
            except Exception:
                logger.warning("Voice provider close failed call_id=%s", call_id)
        try:
            ledger.commit_gemini_turn()
            if lock_client is not None:
                # An accepted provider turn can remain billable after browser
                # cancellation. Keep its settlement inside the call lease.
                charge_task = asyncio.create_task(_charge_voice(
                    websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id,
                ))
                await _finish_accepted_job(charge_task)
        except asyncio.CancelledError:
            was_cancelled = True
        except Exception:
            logger.warning("Voice call final settlement failed call_id=%s", call_id)
        if registered:
            try:
                finish_task = asyncio.create_task(finalize_active_call(
                    websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
                    chat_id=chat_id, call_id=call_id,
                ))
                await _finish_accepted_job(finish_task)
            except asyncio.CancelledError:
                was_cancelled = True
            except Exception:
                logger.warning("Voice call registry finalization failed call_id=%s", call_id)
        if lock_client is not None:
            await _release_lock(lock_client, lock_key, lock_token)
        try:
            await websocket.close()
        except Exception:
            pass
        if was_cancelled:
            raise asyncio.CancelledError
