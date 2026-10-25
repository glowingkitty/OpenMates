"""First-party Voxtral speech input for an encrypted personal chat.

This socket owns STT, call lifecycle and source-frame authorization. Completed
user requests enter the ordinary client-encrypted chat path; normal routing,
permissions, rich answers, speech assets and billing stay on that path.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import math
import re
import time
import traceback
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from backend.core.api.app.routes.audio_realtime import _browser_request_is_allowed, REALTIME_CREDITS_PER_MINUTE
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user, get_directus_service, get_cache_service
from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.voice_call_support import (
    LOCK_RENEW_SECONDS, _acquire_lock, _authoritative_credits, _billing,
    _decode_media, _finish_accepted_job, _release_lock, _renew_lock, _session_still_valid,
)
from backend.core.api.app.services.direct_chat_access import is_direct_chat
from backend.core.api.app.utils.server_mode import is_payment_enabled
from backend.shared.providers.voxtral_voice import VoxtralVoiceSession, VOXTRAL_VOICE_MODEL, STREAMING_DELAY_MS
from backend.shared.providers.live_voice import LiveVoiceSession
from backend.shared.python_utils.voice_call_visuals import VoiceCallVisuals
from backend.shared.python_utils.voice_call_registry import (
    finalize_active_call, issue_message_id, register_active_call, renew_active_call,
)
from backend.shared.testing.voice_call_fixture import (
    IsolatedVoxtralVoiceFixture, VOICE_ACK_DEFAULT_TIMESTAMP, consume_voice_ack_fixture_write_failure,
    isolated_voice_fixture_enabled, set_voice_ack_fixture_fail_next_write,
    set_voice_ack_fixture_profile_mode, voice_ack_fixture_requires_profile,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")
MAX_START_BYTES = 256_000
MAX_EVENT_BYTES = 384_000
MAX_CONTEXT_CHARS = 64_000
MAX_SUMMARY_CHARS = 48_000
MAX_TEXT_CHARS = 8_000
MAX_AUDIO_CHUNK = 128 * 1024
PCM_INPUT_BYTES_PER_SECOND = 32000
MAX_STARTUP_AUDIO_ALLOWANCE_MS = 10_000
AUDIO_JITTER_SECONDS = 2
MAX_PENDING_TRANSCRIPTS = 32
MAX_TEXT_IDENTITIES = 2048
MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PROCESSING_ACK_FIELD = "voice_processing_ack_v3_at"
PROCESSING_ACK_VERSION = 3
SPEECH_OUTPUT_TRANSPORT = "mp3_turn_stream_v2"

def _timestamp() -> int:
    return int(time.time())


def _ordered_message_id(last: int = 0) -> tuple[str, int]:
    """Return a monotonic UUIDv7 so equal-second chat rows retain call order."""
    value = max(int(time.time() * 1000) << 80 | (7 << 76) | (2 << 62) | (uuid.uuid4().int & ((1 << 62) - 1)), last + 1)
    return str(uuid.UUID(int=value)), value


class ContextLimitError(ValueError):
    pass


def _context(value: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise ValueError("Invalid call context")
    summary = value.get("summary") or ""
    messages = value.get("messages") or []
    if not isinstance(summary, str) or not isinstance(messages, list) or len(messages) > 30:
        raise ValueError("Invalid call context")
    total = len(summary)
    if len(summary) > MAX_SUMMARY_CHARS:
        raise ContextLimitError("Call context exceeds limit")
    clean: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant") or not isinstance(item.get("text"), str):
            raise ValueError("Invalid call context")
        text = item["text"]
        if not text:
            raise ValueError("Invalid call context")
        if len(text) > MAX_CONTEXT_CHARS:
            raise ContextLimitError("Call context exceeds limit")
        total += len(text)
        row: dict[str, Any] = {"role": item["role"], "text": text}
        if "message_id" in item:
            try:
                message_id = item["message_id"]
                if isinstance(message_id, str) and re.fullmatch(r"[0-9a-f]{64}", message_id):
                    # Legacy assistant messages use SHA-256 identities.
                    row["message_id"] = message_id
                elif (item["role"] == "user" and isinstance(message_id, str)
                      and re.fullmatch(r"[0-9a-f]{10}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", message_id)):
                    # The composer prefixes user UUIDs with the chat's last ten characters.
                    row["message_id"] = message_id
                else:
                    row["message_id"] = str(uuid.UUID(message_id))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("Invalid context message identity") from exc
        if "created_at" in item:
            created = item["created_at"]
            if isinstance(created, bool) or not isinstance(created, (int, float)) or not 0 <= created < 10**14:
                raise ValueError("Invalid context message timestamp")
            row["created_at"] = int(created)
        clean.append(row)
    if total > MAX_CONTEXT_CHARS:
        raise ContextLimitError("Call context exceeds limit")
    return summary, clean


def _context_options(value: dict[str, Any]) -> dict[str, Any]:
    """Only category identities and focus identity/state cross the start boundary."""
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > MAX_CONTEXT_CHARS:
        raise ContextLimitError("Call context exceeds limit")
    focus = value.get("active_focus")
    if focus is not None:
        if (not isinstance(focus, dict) or set(focus) - {"app_id", "focus_id", "state"}
                or any(not isinstance(focus.get(key), str) or not re.fullmatch(r"[a-z0-9_:\-]{1,128}", focus[key])
                       for key in ("app_id", "focus_id"))):
            raise ValueError("Invalid focus context")
        if len(json.dumps(focus)) > 8_000:
            raise ContextLimitError("Call context exceeds limit")
    metadata = value.get("app_settings_memories_metadata") or []
    if (not isinstance(metadata, list) or len(metadata) > 256
            or any(not isinstance(key, str) or len(key) > 256 for key in metadata)):
        raise ValueError("Invalid memory category context")
    mate_category = value.get("mate_category")
    if mate_category is not None and (not isinstance(mate_category, str) or not re.fullmatch(r"[a-z_]{1,80}", mate_category)):
        raise ValueError("Invalid mate category")
    options = {"active_focus": focus, "app_settings_memories_metadata": metadata}
    if mate_category is not None:
        options["mate_category"] = mate_category
    if "client_capabilities" in value:
        capabilities = value["client_capabilities"]
        if (not isinstance(capabilities, list) or len(capabilities) > 32
                or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9_\-]{1,64}", item) for item in capabilities)):
            raise ValueError("Invalid client capability context")
        options["client_capabilities"] = capabilities
    if "project_focus_candidates" in value:
        candidates = value["project_focus_candidates"]
        if not isinstance(candidates, list) or len(candidates) > 40:
            raise ValueError("Invalid Project context")
        for candidate in candidates:
            if (not isinstance(candidate, dict) or set(candidate) - {"project_id", "name", "summary", "focuses"}
                    or any(not isinstance(candidate.get(key), str) for key in ("project_id", "name", "summary"))):
                raise ValueError("Invalid Project context")
            focuses = candidate.get("focuses", [])
            if not isinstance(focuses, list) or len(focuses) > 20:
                raise ValueError("Invalid Project focus metadata")
            for item in focuses:
                if (not isinstance(item, dict) or set(item) - {"item_id", "revision", "title", "description", "when_to_use"}
                        or any(not isinstance(item.get(key), str) for key in ("item_id", "revision"))
                        or any(not isinstance(text, str) for text in item.values())):
                    raise ValueError("Invalid Project focus metadata")
        options["project_focus_candidates"] = candidates
    if "project_focus_documents" in value:
        documents = value["project_focus_documents"]
        if not isinstance(documents, list) or len(documents) > 1:
            raise ValueError("Invalid active Project focus document")
        for document in documents:
            if (not isinstance(document, dict) or set(document) != {"item_id", "revision", "document"}
                    or any(not isinstance(text, str) for text in document.values())):
                raise ValueError("Invalid active Project focus document")
        # This is a claimed selected document. The sealed worker checks active
        # accepted focus, owner access, item identity and current revision.
        options["project_focus_documents"] = documents
    return options


def _start(message: str) -> tuple[str, str, list[dict[str, Any]], int]:
    if len(message.encode("utf-8")) > MAX_START_BYTES:
        raise ContextLimitError("Call start exceeds limit")
    event = json.loads(message)
    if not isinstance(event, dict) or event.get("type") != "start":
        raise ValueError("Call start required")
    if event.get("speech_output_transport") != SPEECH_OUTPUT_TRANSPORT:
        raise ValueError("Unsupported speech output transport")
    startup_audio_allowance_ms = event.get("startup_audio_allowance_ms", 0)
    if (isinstance(startup_audio_allowance_ms, bool)
            or not isinstance(startup_audio_allowance_ms, int)
            or not 0 <= startup_audio_allowance_ms <= MAX_STARTUP_AUDIO_ALLOWANCE_MS):
        raise ValueError("Invalid startup audio allowance")
    chat_id = event.get("chat_id")
    try:
        chat_id = str(uuid.UUID(chat_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid chat identity") from exc
    # Current STT-only clients omit chat context entirely. Legacy clients may
    # still supply bounded context, which is validated but never sent to STT.
    summary, messages = _context(event.get("context", {}))
    return chat_id, summary, messages, startup_audio_allowance_ms


class TranscriptLimitError(ValueError):
    pass


def _bounded_transcript(value: str) -> str:
    if len(value) > MAX_TEXT_CHARS:
        raise TranscriptLimitError("Transcript exceeds call limit")
    return value


class SpeechUsageLedger:
    """Bill actual accepted PCM duration, cumulatively rounded once per call."""
    def __init__(self) -> None:
        self.audio_bytes = 0
        self.charged = 0

    @property
    def billed_minutes(self) -> int:
        return math.ceil(self.audio_bytes / (PCM_INPUT_BYTES_PER_SECOND * 60))

    @property
    def credits(self) -> int:
        return self.billed_minutes * REALTIME_CREDITS_PER_MINUTE

    def view(self, elapsed: float) -> dict[str, Any]:
        return {"type": "usage", "billing_basis": "speech_duration_and_chat_usage",
                "elapsed_seconds": round(elapsed, 1),
                "stt_duration_seconds": self.audio_bytes / PCM_INPUT_BYTES_PER_SECOND,
                "credits_accrued": self.credits, "credits_charged": self.charged,
                "stt_credits_per_started_minute": REALTIME_CREDITS_PER_MINUTE}


async def _charge_voice(websocket: WebSocket, ledger: SpeechUsageLedger, *,
                        user_id: str, user_hash: str, call_id: str, chat_id: str) -> None:
    due = ledger.credits - ledger.charged
    if due <= 0 or not is_payment_enabled():
        return
    result = await _billing(websocket).charge_user_credits(
        user_id=user_id, user_id_hash=user_hash, credits_to_deduct=due,
        app_id="ai", skill_id="voice_call", require_full_charge=True,
        idempotency_key=f"voice-call:{call_id}:stt:{ledger.billed_minutes}",
        usage_details={"usage_type": "voice_call_transcription", "model_used": VOXTRAL_VOICE_MODEL,
                       "chat_id": chat_id, "duration_seconds": ledger.audio_bytes / PCM_INPUT_BYTES_PER_SECOND,
                       "billed_minutes": ledger.billed_minutes,
                       "credits_per_started_minute": REALTIME_CREDITS_PER_MINUTE,
                       "charged_credits": due},
    )
    charged = int(result.get("charged_credits", due))
    if charged != due:
        raise RuntimeError("Voice transcription charge incomplete")
    ledger.charged += charged


async def _provider(websocket: WebSocket) -> LiveVoiceSession:
    if isolated_voice_fixture_enabled():
        return IsolatedVoxtralVoiceFixture()
    key = await websocket.app.state.secrets_manager.get_secret("kv/data/providers/mistral_ai", "api_key")
    if not key:
        raise RuntimeError("Voice provider unavailable")
    return VoxtralVoiceSession(key)


async def _personal_chat(websocket: WebSocket, chat_id: str, user_id: str) -> bool:
    chat = await websocket.app.state.directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
    if not isinstance(chat, dict) or chat.get("id") != chat_id or chat.get("storage_state") == "deleting":
        return False
    if chat.get("hashed_team_id") or is_direct_chat(chat):
        return False
    return chat.get("hashed_user_id") == hashlib.sha256(user_id.encode()).hexdigest()


async def _processing_ack_at(directus: DirectusService, user_id: str) -> int | None:
    """Read the durable profile field; session cache is never admission authority."""
    fields = await directus.get_user_fields_direct(user_id, [PROCESSING_ACK_FIELD], no_cache=True)
    if fields is None:
        raise RuntimeError("Voice processing acknowledgment unavailable")
    value = fields.get(PROCESSING_ACK_FIELD)
    return value if type(value) is int and value > 0 else None


async def _effective_processing_ack_at(
    directus: DirectusService, cache: CacheService, user_id: str,
) -> int | None:
    if isolated_voice_fixture_enabled() and not await voice_ack_fixture_requires_profile(cache, user_id):
        return VOICE_ACK_DEFAULT_TIMESTAMP
    return await _processing_ack_at(directus, user_id)


def _first_party_voice_request(request: Request) -> None:
    # First-party session surface only, never an API-key or cross-origin consent write.
    origin = request.headers.get("origin")
    allowed = getattr(request.app.state, "allowed_origins", []) or []
    if not origin or origin not in allowed:
        raise HTTPException(status_code=403, detail="Origin not allowed")


@router.get("/settings/voice-processing-ack", include_in_schema=False)
@limiter.limit("30/minute")
async def get_processing_ack(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus: DirectusService = Depends(get_directus_service),
    cache: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    _first_party_voice_request(request)
    try:
        acknowledged_at = await _effective_processing_ack_at(directus, cache, current_user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Voice acknowledgment unavailable") from exc
    return {"version": PROCESSING_ACK_VERSION, "acknowledged": acknowledged_at is not None,
            "acknowledged_at": acknowledged_at}


@router.post("/settings/voice-processing-ack", include_in_schema=False)
@limiter.limit("10/minute")
async def record_processing_ack(
    request: Request,
    body: dict[str, Any],
    current_user: User = Depends(get_current_user),
    directus: DirectusService = Depends(get_directus_service),
    cache: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    _first_party_voice_request(request)
    if body != {"version": PROCESSING_ACK_VERSION} or type(body.get("version")) is not int:
        raise HTTPException(status_code=422, detail="Unsupported acknowledgment version")
    try:
        acknowledged_at = await _effective_processing_ack_at(directus, cache, current_user.id)
        if acknowledged_at is None:
            if await consume_voice_ack_fixture_write_failure(cache, current_user.id):
                raise RuntimeError("Isolated voice acknowledgment write failure")
            if not await directus.update_user(current_user.id, {PROCESSING_ACK_FIELD: _timestamp()}):
                raise RuntimeError("Voice processing acknowledgment write failed")
            acknowledged_at = await _processing_ack_at(directus, current_user.id)
            if acknowledged_at is None:
                raise RuntimeError("Voice processing acknowledgment write not confirmed")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Voice acknowledgment unavailable") from exc
    return {"version": PROCESSING_ACK_VERSION, "acknowledged": True,
            "acknowledged_at": acknowledged_at}


@router.post("/settings/voice-processing-ack/fixture", include_in_schema=False)
@limiter.limit("10/minute")
async def configure_processing_ack_fixture(
    request: Request,
    body: dict[str, Any],
    current_user: User = Depends(get_current_user),
    directus: DirectusService = Depends(get_directus_service),
    cache: CacheService = Depends(get_cache_service),
) -> dict[str, bool]:
    if not isolated_voice_fixture_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    _first_party_voice_request(request)
    if body == {"action": "fail_next_write"}:
        await set_voice_ack_fixture_fail_next_write(cache, current_user.id)
        return {"configured": True}
    if body != {"action": "reset"}:
        raise HTTPException(status_code=422, detail="Invalid fixture action")
    # This is limited to the current isolated-CI account; the subsequent real
    # GET/POST and voice admission use the durable profile field.
    if not await directus.update_user(current_user.id, {PROCESSING_ACK_FIELD: None}):
        raise HTTPException(status_code=503, detail="Voice fixture unavailable")
    try:
        acknowledged_at = await _processing_ack_at(directus, current_user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Voice fixture unavailable") from exc
    if acknowledged_at is not None:
        raise HTTPException(status_code=503, detail="Voice fixture unavailable")
    await set_voice_ack_fixture_profile_mode(cache, current_user.id)
    return {"configured": True}


@dataclass
class _SpeechTurn:
    message_id: str
    created_at: int
    assistant_id: str | None
    assistant_text: str
    assistant_active: bool
    assistant_task_id: str | None = None
    text: str = ""
    deadline: float | None = None
    classifier: asyncio.Task[str] | None = None
    classifier_text: str = ""
    verdict: str = "uncertain"
    interrupted: bool = False


async def _classify(text: str, assistant_text: str, websocket: WebSocket, language: str) -> str:
    from backend.shared.python_utils.voice_call_intent import classify_voice_interruption
    try:
        return await asyncio.wait_for(classify_voice_interruption(
            text, assistant_text, websocket.app.state.secrets_manager, language=language,
        ), timeout=2)
    except Exception as exc:
        logger.warning("Voice intent unavailable category=%s", type(exc).__name__)
        return "uncertain"


def _text_input(event: dict[str, Any]) -> tuple[str, str, int]:
    message_id, text, created = event.get("message_id"), event.get("text"), event.get("created_at")
    if (not isinstance(message_id, str) or not MESSAGE_ID.fullmatch(message_id)
            or not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS
            or isinstance(created, bool) or not isinstance(created, (int, float))
            or not math.isfinite(created)):
        raise ValueError("Invalid text input")
    if uuid.UUID(message_id).version != 7:
        raise ValueError("Invalid text identity")
    created = int(created)
    if created > 10_000_000_000:
        created //= 1000
    if abs(created - _timestamp()) > 86400:
        raise ValueError("Invalid text timestamp")
    return message_id, text, created


@router.websocket("/voice-call")
async def voice_call(websocket: WebSocket, auth_data: dict[str, Any] | None = Depends(get_current_user_ws)) -> None:
    """First-party session auth only; owner-scoped, bounded, paid STT surface.

    Origin/session/consent and personal-chat ownership precede provider work.
    This route is outside the public developer API allowlist.
    """
    if auth_data is None:
        return
    if not await _browser_request_is_allowed(websocket, auth_data):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    user_id, session_id = auth_data["user_id"], auth_data.get("session_hash")
    if not isinstance(session_id, str) or not session_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session unavailable")
        return
    try:
        acknowledged = await _effective_processing_ack_at(
            websocket.app.state.directus_service, websocket.app.state.cache_service, user_id,
        )
    except RuntimeError:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="voice_ack_unavailable")
        return
    if acknowledged is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="voice_ack_required")
        return
    await websocket.accept()
    call_id = uuid.uuid4().hex
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    chat_id = ""
    provider: LiveVoiceSession | None = None
    client_receive: asyncio.Task[str] | None = None
    provider_receive: asyncio.Task[dict[str, Any]] | None = None
    lease_task: asyncio.Task[None] | None = None
    registry_task: asyncio.Task[None] | None = None
    lock_client: Any = None
    lock_key = lock_token = ""
    registered = False
    ledger = SpeechUsageLedger()
    visuals = VoiceCallVisuals()
    turns: dict[str, _SpeechTurn] = {}
    current: _SpeechTurn | None = None
    seen_text_ids: dict[str, tuple[str, int]] = {}
    interrupted_ids: set[str] = set()
    assistant: dict[str, Any] = {"speaking": False, "generating": False, "text": "", "assistant_message_id": None, "assistant_task_id": None}
    language = "auto"
    last_order = 0
    started = last_auth_check = time.monotonic()
    last_usage: tuple[int, int] | None = None
    listening = True
    last_activity: tuple[bool, bool, bool] | None = None
    stage = "start_validation"

    async def send(event: dict[str, Any]) -> None:
        await websocket.send_json(event)

    async def activity() -> None:
        nonlocal last_activity
        value = (listening, bool(assistant["speaking"] or assistant["generating"]), visuals.camera_active)
        if value != last_activity:
            await send({"type": "billing_activity", "call_id": call_id,
                        "input_listening": value[0], "processing": value[1], "camera_active": value[2]})
            last_activity = value

    async def registry_renewal() -> None:
        while True:
            await asyncio.sleep(LOCK_RENEW_SECONDS)
            await renew_active_call(websocket.app.state.cache_service, user_id=user_id,
                                    session_id=session_id, chat_id=chat_id, call_id=call_id)

    async def issue(message_id: str) -> None:
        await issue_message_id(websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
                               chat_id=chat_id, call_id=call_id, message_id=message_id, role="user")

    async def new_turn() -> _SpeechTurn:
        nonlocal last_order
        if len(turns) >= MAX_PENDING_TRANSCRIPTS:
            raise TranscriptLimitError("Too many pending speech turns")
        message_id, last_order = _ordered_message_id(last_order)
        turn = _SpeechTurn(message_id, _timestamp(), assistant["assistant_message_id"],
                           assistant["text"], bool(assistant["speaking"] or assistant["generating"]),
                           assistant_task_id=assistant["assistant_task_id"])
        turns[message_id] = turn
        return turn

    async def interrupt(turn: _SpeechTurn) -> None:
        if turn.interrupted or not turn.assistant_active:
            return
        if turn.assistant_task_id is not None and assistant["assistant_task_id"] != turn.assistant_task_id:
            return
        if turn.assistant_id is not None and assistant["assistant_message_id"] != turn.assistant_id:
            return  # A delayed decision cannot cancel a newer canonical answer.
        turn.interrupted = True
        interruption_key = (f"task:{turn.assistant_task_id}" if turn.assistant_task_id else
                            f"message:{turn.assistant_id}" if turn.assistant_id else None)
        if interruption_key in interrupted_ids:
            return
        if interruption_key:
            interrupted_ids.add(interruption_key)
        await send({"type": "audio.interrupted", "call_id": call_id,
                    "assistant_message_id": turn.assistant_id, "assistant_task_id": turn.assistant_task_id,
                    "user_message_id": turn.message_id})

    async def transcript(turn: _SpeechTurn, *, final: bool) -> None:
        if final:
            # Partial drafts grant no ordinary ask/tool authority.
            await issue(turn.message_id)
            frame = visuals.freeze(turn.message_id)
            if frame is not None:
                await send({"type": "voice_source_frame", "call_id": call_id,
                            "user_message_id": turn.message_id, "frame_id": frame.frame_id,
                            "data": frame.data, "captured_at": frame.captured_at,
                            "created_at": turn.created_at, "source": frame.source})
        await send({"type": "transcript", "role": "user", "call_id": call_id,
                    "message_id": turn.message_id, "user_message_id": turn.message_id,
                    "turn_id": turn.message_id, "created_at": turn.created_at,
                    "text": turn.text, "final": final, "interrupted": False})

    async def classify_latest(turn: _SpeechTurn) -> None:
        from backend.shared.python_utils.voice_call_intent import is_explicit_voice_stop
        if not turn.assistant_active:
            return
        if is_explicit_voice_stop(turn.text):
            await interrupt(turn)
            turn.verdict = "interrupt"
            if turn.classifier is not None:
                turn.classifier.cancel()
            turn.classifier = None
            turn.classifier_text = turn.text
        elif turn.classifier_text != turn.text:
            if turn.classifier is not None:
                turn.classifier.cancel()
                await asyncio.gather(turn.classifier, return_exceptions=True)
            turn.verdict = "uncertain"
            turn.classifier_text = turn.text
            turn.classifier = asyncio.create_task(_classify(turn.text, turn.assistant_text, websocket, language))

    async def finish_ready_turns(now: float) -> None:
        nonlocal current
        from backend.shared.python_utils.voice_call_intent import assistant_question_pending, is_explicit_voice_stop, is_listener_acknowledgement
        for turn in list(turns.values()):
            if turn.classifier is not None:
                if not turn.classifier.done():
                    continue
                turn.verdict = turn.classifier.result()
                turn.classifier = None
                if turn.verdict == "interrupt":
                    await interrupt(turn)
            if turn.deadline is None or now < turn.deadline:
                continue
            text = turn.text.strip()
            reason = None
            if not text:
                reason = "empty"
            elif turn.assistant_active and is_explicit_voice_stop(text):
                await interrupt(turn)
                reason = "stop"
            elif turn.assistant_active and (turn.verdict == "backchannel" or (turn.verdict == "uncertain" and is_listener_acknowledgement(text)
                    and not assistant_question_pending(turn.assistant_text))):
                reason = "backchannel"
            else:
                # A complete substantive request must survive model uncertainty.
                # Only a complete turn can authorize ordinary chat/tools.
                await interrupt(turn)
                turn.text = text
                await transcript(turn, final=True)
            if reason is not None:
                await send({"type": "transcript.discarded", "call_id": call_id,
                            "message_id": turn.message_id, "reason": reason})
            turns.pop(turn.message_id)
            if current is turn:
                current = None

    try:
        start_message = await asyncio.wait_for(websocket.receive_text(), 10)
        chat_id, _summary, _messages, startup_ms = _start(start_message)
        _context_options(json.loads(start_message).get("context", {}))
        allowance = startup_ms * PCM_INPUT_BYTES_PER_SECOND // 1000
        stage = "personal_chat"
        if not await _personal_chat(websocket, chat_id, user_id):
            raise ValueError("Chat unavailable")
        stage = "session"
        if not await _session_still_valid(websocket, auth_data):
            raise ValueError("Session unavailable")
        stage = "credits"
        if is_payment_enabled() and await _authoritative_credits(websocket, user_id) < REALTIME_CREDITS_PER_MINUTE:
            raise RuntimeError("Insufficient credits")
        stage = "lock"
        lock_client, lock_key, lock_token = await _acquire_lock(websocket, user_hash)
        lease_task = asyncio.create_task(_renew_lock(lock_client, lock_key, lock_token))
        await register_active_call(websocket.app.state.cache_service, user_id=user_id,
                                   session_id=session_id, chat_id=chat_id, call_id=call_id)
        registered = True
        registry_task = asyncio.create_task(registry_renewal())
        stage = "provider_open"
        provider = await _provider(websocket)
        await provider.open()
        stage = "active"
        started = last_auth_check = time.monotonic()
        await send({"type": "ready", "call_id": call_id, "provider": "mistral", "model": provider.model,
                    "speech_output_transport": SPEECH_OUTPUT_TRANSPORT,
                    "input_sample_rate": 16000, "output_sample_rate": 24000,
                    "billing_basis": "speech_duration_and_chat_usage",
                    "rates": {"stt_credits_per_started_minute": REALTIME_CREDITS_PER_MINUTE},
                    "camera_available": True})
        await activity()
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
                last_auth_check = now
            waiters = {client_receive, provider_receive, lease_task, registry_task}
            waiters.update(turn.classifier for turn in turns.values() if turn.classifier is not None)
            deadlines = [turn.deadline for turn in turns.values() if turn.deadline is not None and turn.deadline > now]
            timeout = min(1.0, max(0, min(deadlines) - now)) if deadlines else 1.0
            done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if client_receive in done:
                raw = client_receive.result()
                if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
                    raise ValueError("Call event exceeds limit")
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise ValueError("Invalid call event")
                kind = event.get("type")
                if kind == "hangup":
                    await send({"type": "ended", "reason": "user"})
                    break
                if kind == "mic_audio":
                    chunk = _decode_media(event.get("data"), max_bytes=MAX_AUDIO_CHUNK)
                    if len(chunk) % 2:
                        raise ValueError("PCM audio is invalid")
                    prospective = ledger.audio_bytes + len(chunk)
                    if prospective > ((time.monotonic() - started + AUDIO_JITTER_SECONDS) * PCM_INPUT_BYTES_PER_SECOND + allowance):
                        raise ValueError("Audio stream exceeds real-time rate")
                    prospective_credits = math.ceil(prospective / (PCM_INPUT_BYTES_PER_SECOND * 60)) * REALTIME_CREDITS_PER_MINUTE
                    reserve = prospective_credits - ledger.charged
                    if is_payment_enabled() and reserve > 0 and await _authoritative_credits(websocket, user_id) < reserve:
                        raise RuntimeError("Insufficient credits")
                    await asyncio.wait_for(provider.send_audio(event["data"]), 5)
                    ledger.audio_bytes = prospective
                    listening = True
                    await _charge_voice(websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id, chat_id=chat_id)
                elif kind == "audio_stream_end":
                    await asyncio.wait_for(provider.end_audio(), 5)
                    listening = False
                elif kind == "assistant_state":
                    speaking, generating = event.get("speaking"), event.get("generating", False)
                    text, identity = event.get("text", ""), event.get("assistant_message_id")
                    task_id = event.get("assistant_task_id")
                    if (type(speaking) is not bool or type(generating) is not bool or not isinstance(text, str)
                            or len(text) > MAX_TEXT_CHARS or (identity is not None and
                            (not isinstance(identity, str) or not MESSAGE_ID.fullmatch(identity)))
                            or (task_id is not None and (not isinstance(task_id, str) or not MESSAGE_ID.fullmatch(task_id)))):
                        raise ValueError("Invalid assistant state")
                    assistant.update(speaking=speaking, generating=generating, text=text,
                                     assistant_message_id=identity, assistant_task_id=task_id)
                elif kind == "text_input":
                    try:
                        identity, text, created = _text_input(event)
                    except (ValueError, TypeError, AttributeError):
                        await send({"type": "text_input_rejected", "message_id": event.get("message_id") if isinstance(event.get("message_id"), str) and len(event["message_id"]) <= 128 else None,
                                    "code": "invalid_text_input"})
                    else:
                        previous = seen_text_ids.get(identity)
                        if previous is not None and previous != (text, created):
                            await send({"type": "text_input_rejected", "message_id": identity, "code": "duplicate_message_id"})
                        else:
                            if previous is None:
                                if len(seen_text_ids) >= MAX_TEXT_IDENTITIES:
                                    raise TranscriptLimitError("Too many text identities")
                                turn = _SpeechTurn(identity, created, assistant["assistant_message_id"],
                                    assistant["text"], bool(assistant["speaking"] or assistant["generating"]),
                                    assistant_task_id=assistant["assistant_task_id"], text=text)
                                await interrupt(turn)
                                await transcript(turn, final=True)
                                seen_text_ids[identity] = (text, created)
                            await send({"type": "text_input.accepted", "call_id": call_id, "message_id": identity})
                elif kind in {"camera_state", "camera_frame", "source_frame_saved", "source_frame_failed"}:
                    if event.get("call_id") != call_id:
                        raise PermissionError("Visual call binding mismatch")
                    try:
                        if kind == "camera_state":
                            visuals.set_enabled(event.get("enabled"))
                            await send({"type": "camera_state", "call_id": call_id, "enabled": visuals.enabled})
                        elif kind == "camera_frame":
                            visuals.accept(event)
                        else:
                            await visuals.acknowledge(event, directus=websocket.app.state.directus_service, user_id=user_id)
                    except ValueError:
                        await send({"type": "camera_error", "call_id": call_id, "code": "camera_input_rejected", "enabled": visuals.enabled})
                else:
                    raise ValueError("Unknown call event")
                client_receive = asyncio.create_task(websocket.receive_text())
            if provider_receive in done:
                event = provider_receive.result()
                kind = event.get("type")
                if kind == "turn.start":
                    if current is not None:
                        current.deadline = time.monotonic()
                    current = await new_turn()
                elif kind == "transcription.text.delta":
                    delta = event.get("text")
                    if not isinstance(delta, str):
                        raise ValueError("Invalid transcript delta")
                    if delta:
                        if current is None:
                            current = await new_turn()
                        current.text = _bounded_transcript(current.text + delta)
                        language = event.get("language") if isinstance(event.get("language"), str) and len(event["language"]) <= 32 else language
                        await transcript(current, final=False)
                        await classify_latest(current)
                elif kind == "turn.end":
                    if current is not None:
                        current.deadline = time.monotonic() + STREAMING_DELAY_MS / 1000
                elif kind in {"turn.resume", "turn.eager_end"}:
                    # Eager endpointing never authorizes chat or tools.
                    if kind == "turn.resume" and current is not None:
                        current.deadline = None
                elif kind == "transcription.done":
                    # input_audio.end is never sent for mute. An unexpected
                    # terminal provider session cannot silently drop future audio.
                    raise RuntimeError("Voice transcription session ended")
                elif kind == "error":
                    raise RuntimeError("Voice transcription failed")
                provider_receive = asyncio.create_task(provider.receive())
            await finish_ready_turns(time.monotonic())
            usage = (ledger.audio_bytes, ledger.charged)
            if usage != last_usage:
                await send(ledger.view(time.monotonic() - started))
                last_usage = usage
            await activity()
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        origin = frames[-1] if frames else None
        logger.warning("Voice call ended category=%s function=%s line=%s stage=%s call_id=%s",
                       type(exc).__name__, origin.name if origin else "unknown", origin.lineno if origin else 0, stage, call_id)
        try:
            code = "context_too_large" if isinstance(exc, ContextLimitError) else "transcript_limit" if isinstance(exc, TranscriptLimitError) else "call_unavailable"
            await send({"type": "error", "code": code, "stage": stage, "message": "Call unavailable. Your call has ended."})
        except Exception:
            pass
    finally:
        visuals.close()
        tasks = [task for task in (client_receive, provider_receive, lease_task, registry_task,
                 *(turn.classifier for turn in turns.values())) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if provider is not None:
            try:
                await provider.close()
            except Exception:
                logger.warning("Voice provider close failed call_id=%s", call_id)
        cancelled = False
        if ledger.audio_bytes:
            try:
                await _finish_accepted_job(asyncio.create_task(_charge_voice(
                    websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id, chat_id=chat_id,
                )))
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                logger.warning("Voice final settlement failed call_id=%s", call_id)
        if registered:
            try:
                await _finish_accepted_job(asyncio.create_task(finalize_active_call(
                    websocket.app.state.cache_service, user_id=user_id, session_id=session_id, chat_id=chat_id, call_id=call_id,
                )))
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                logger.warning("Voice registry finalization failed call_id=%s", call_id)
        if lock_client is not None:
            await _release_lock(lock_client, lock_key, lock_token)
        try:
            await websocket.close()
        except Exception:
            pass
        if cancelled:
            raise asyncio.CancelledError
