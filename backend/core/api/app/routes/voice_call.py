"""First-party Voxtral speech input for an encrypted personal chat.

This socket owns STT, call lifecycle and source-frame authorization. Completed
user requests enter the ordinary client-encrypted chat path; normal routing,
permissions, rich answers, speech assets and billing stay on that path.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
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
from backend.apps.audio.pricing import (
    REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE,
    REALTIME_TRANSCRIPTION_MINIMUM_CREDITS,
    calculate_realtime_transcription_credits,
)
from backend.core.api.app.routes.audio_realtime import _browser_request_is_allowed
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user, get_directus_service, get_cache_service
from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.shared.python_utils.voice_call_pasted import mark_pasted
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.voice_call_support import (
    LOCK_RENEW_SECONDS, _acquire_lock, _authoritative_credits, _billing,
    _decode_media, _finish_accepted_job, _release_lock, _renew_lock, _session_still_valid,
)
from backend.core.api.app.services.direct_chat_access import is_direct_chat
from backend.core.api.app.utils.server_mode import is_payment_enabled
from backend.core.api.app.routes.voice_call_terms import parse_terms
from backend.shared.providers.voxtral_voice import (
    STREAM_RECEIVE_TIMEOUT, STREAMING_DELAY_MS, VOXTRAL_VOICE_MODEL, VoxtralVoiceSession,
)
from backend.shared.python_utils.voice_pause_decision import (
    PAUSE_WAIT_SECONDS, PauseDecision, as_pause_decision, classify_voice_pause,
    instant_feedback_enabled, voice_feedback_key,
)
from backend.shared.python_utils.voice_call_intent import is_prerecorded_clip_echo
from backend.shared.providers.live_voice import LiveVoiceSession
from backend.shared.python_utils.voice_call_visuals import VoiceCallVisuals
from backend.shared.python_utils.voice_call_registry import (
    ACTIVE_TTL_SECONDS, finalize_active_call, issue_message_id, register_active_call, renew_active_call,
)
from backend.core.api.app.routes.voice_call_orchestration import CallInterpretationGate
from backend.core.api.app.routes.voice_call_waiting import VoiceWaiting
from backend.shared.testing.voice_call_fixture import (
    IsolatedVoxtralVoiceFixture, VOICE_ACK_DEFAULT_TIMESTAMP, consume_voice_ack_fixture_write_failure,
    isolated_voice_fixture_enabled, set_voice_ack_fixture_fail_next_write,
    set_voice_ack_fixture_profile_mode, voice_ack_fixture_requires_profile,
)

from backend.core.api.app.routes.voice_call_audio import MicAudioForwarder

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
# After an "uncertain" (or twice "unavailable") completion decision, continued
# silence is the user's answer: submit once instead of holding the turn until
# new speech that may never come. "incomplete" thinking pauses stay held.
# Real TTS calls showed STT-punctuated pauses ("I would like to know.") judged
# uncertain; 2.5s keeps ordinary ~2-3s thinking pauses in one turn.
UNCERTAIN_SILENCE_FALLBACK_SECONDS = PAUSE_WAIT_SECONDS["unsure"]
# A "still thinking" verdict submits after this much further silence.
STILL_THINKING_SILENCE_SECONDS = PAUSE_WAIT_SECONDS["still_thinking"]
# Hard overall deadline of the "done talking?" check after turn.end. A miss or
# provider outage counts as complete (logged), so the check cannot block a turn.
COMPLETION_CHECK_DEADLINE_SECONDS = 0.6  # transport budget; the model call itself targets 0.25s
# A late delta only re-runs the check when this much budget is still left.
COMPLETION_RECHECK_MIN_BUDGET_SECONDS = 0.15
# Wait for streamed trailing words after the local VAD has sent its quiet tail.
LOCAL_ENDPOINT_TRANSCRIPT_GRACE_SECONDS = 0.35
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


class InsufficientCreditsError(RuntimeError):
    """The account cannot pay for the call; the client shows the credits message."""


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


def _likely_end_hints(message: str) -> bool:
    """Whether the client opted in to `turn.likely_end`/`turn.resumed` hints.

    Older native clients reject unknown call frames, so the server sends these
    preparation hints only to a client whose start frame asks for them.
    """
    value = json.loads(message).get("likely_end_hints", False)
    if not isinstance(value, bool):
        raise ValueError("Invalid likely end hint option")
    return value


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
    def seconds(self) -> float:
        return self.audio_bytes / PCM_INPUT_BYTES_PER_SECOND

    def credits_with(self, additional_bytes: int = 0) -> int:
        return calculate_realtime_transcription_credits(
            duration_seconds=(self.audio_bytes + additional_bytes) / PCM_INPUT_BYTES_PER_SECOND,
        )

    @property
    def credits(self) -> int:
        return self.credits_with()

    def view(self, elapsed: float) -> dict[str, Any]:
        return {"type": "usage", "billing_basis": "speech_duration_and_chat_usage",
                "elapsed_seconds": round(elapsed, 1),
                "stt_duration_seconds": self.seconds,
                "credits_accrued": self.credits, "credits_charged": self.charged,
                "stt_credits_per_second": REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE / 60}


async def _charge_voice(websocket: WebSocket, ledger: SpeechUsageLedger, *,
                        user_id: str, user_hash: str, call_id: str, chat_id: str) -> None:
    accrued = ledger.credits
    due = accrued - ledger.charged
    if due <= 0 or not is_payment_enabled():
        return
    result = await _billing(websocket).charge_user_credits(
        user_id=user_id, user_id_hash=user_hash, credits_to_deduct=due,
        app_id="ai", skill_id="voice_call", require_full_charge=True,
        idempotency_key=f"voice-call:{call_id}:stt:credit:{accrued}",
        usage_details={"usage_type": "voice_call_transcription", "model_used": VOXTRAL_VOICE_MODEL,
                       "chat_id": chat_id, "duration_seconds": ledger.seconds,
                       "billing_unit": "second",
                       "credits_per_minute": REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE,
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
    completion: asyncio.Task[str] | None = None
    completion_text: str = ""
    separate_next_delta: bool = False
    assistant_speaking: bool = False
    clip_text: str = ""
    completion_retried: bool = False
    completion_started: float = 0.0
    submit_on_silence: bool = False
    local_endpoint: bool = False
    drained_endpoint: bool = False
    # A likely end was hinted to the browser, which may prepare the send for it.
    likely_end_sent: bool = False


async def _classify(text: str, assistant_text: str, websocket: WebSocket, language: str,
                    assistant_speaking: bool = False) -> str:
    from backend.shared.python_utils.voice_call_intent import classify_voice_interruption
    try:
        return await asyncio.wait_for(classify_voice_interruption(
            text, assistant_text, websocket.app.state.secrets_manager, language=language,
            assistant_speaking=assistant_speaking,
        ), timeout=2)
    except Exception as exc:
        logger.warning("Voice intent unavailable category=%s", type(exc).__name__)
        return "uncertain"


def _material_change(checked: str, current: str) -> bool:
    """True when the words differ, ignoring case and punctuation-only edits."""
    def words(value: str) -> list[str]:
        return re.sub(r"[^\w\s]", "", value.lower()).split()
    return words(checked) != words(current)


async def _complete(text: str, websocket: WebSocket, timeout: float = COMPLETION_CHECK_DEADLINE_SECONDS,
                    *, with_feedback: bool = False, playback_control: bool = False) -> PauseDecision:
    """Separate, bounded completion gate; never run ordinary preprocessing here."""
    try:
        if isolated_voice_fixture_enabled():
            from backend.shared.testing.voice_call_fixture import (
                isolated_voice_completion_fixture, isolated_voice_intent_fixture)
            fixture_intent = isolated_voice_intent_fixture(text)
            if playback_control and fixture_intent == "wait" and text == "Wait a second.":
                fixture_intent = "pause_playback"
            if fixture_intent is not None:
                complete = as_pause_decision("complete")
                return PauseDecision(complete.verdict, fixture_intent, complete.wait_seconds,  # type: ignore[arg-type]  # fixed CI intents
                                     feedback_language="en" if with_feedback else None)
            result = as_pause_decision(isolated_voice_completion_fixture(text) or "uncertain")
            if with_feedback and result.completion == "complete":
                return PauseDecision(result.verdict, result.intent, result.wait_seconds, "answering", "en")
            return result
        options = {"with_feedback": True} if with_feedback else {}
        if playback_control:
            options["playback_control"] = True
        return await asyncio.wait_for(classify_voice_pause(
            text, websocket.app.state.secrets_manager, timeout, **options), timeout=timeout + 0.05)
    except TimeoutError:
        logger.warning("VOICE_COMPLETION_CHECK timeout after=%.2fs", timeout)
        return as_pause_decision("unavailable")
    except Exception as exc:
        logger.warning("VOICE_COMPLETION_CHECK unavailable category=%s", type(exc).__name__)
        return as_pause_decision("unavailable")


async def _prewarm_completion() -> None:
    """Warm the completion gate while the provider opens; never fails a call."""
    if isolated_voice_fixture_enabled():
        return
    from backend.shared.python_utils.voice_turn_completion import prewarm_voice_turn_completion
    try:
        await prewarm_voice_turn_completion()
    except ImportError:
        logger.warning("Voice completion tokenizer warmup unavailable")


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
    # The chat socket can predate refresh-token rotation. Both transports
    # already authenticate against the durable session ledger in auth_ws.
    user_id, session_id = auth_data["user_id"], auth_data.get("logical_session_id")
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
    prewarm_task: asyncio.Task[None] | None = None
    audio: MicAudioForwarder | None = None
    audio_progress = asyncio.Event()
    audio_progress_wait: asyncio.Task[bool] | None = None
    drain_audio = True
    lock_client: Any = None
    lock_key = lock_token = ""
    registered = False
    cleanup_attempt_id = None
    cleanup_tracking_started = False
    cleanup_eligible = False
    feedback_enabled = False
    cleanup_task: list[asyncio.Task[None] | None] = [None]
    cleanup_ready_exposed = False
    ledger = SpeechUsageLedger()
    visuals = VoiceCallVisuals()
    turns: dict[str, _SpeechTurn] = {}
    completion_tasks: set[asyncio.Task[str]] = set()
    current: _SpeechTurn | None = None
    local_endpoint_bytes: int | None = None
    verified_quiet_frame: int | None = None
    closed_local_turn = False
    seen_text_ids: dict[str, tuple[str, int]] = {}
    interrupted_ids: set[str] = set()
    assistant: dict[str, Any] = {"speaking": False, "generating": False, "text": "", "assistant_message_id": None,
                                 "assistant_task_id": None, "clip_text": "", "clip_url": None}
    recent_clip_text = ""
    recent_clip_until = 0.0
    captured_clip_text = ""
    captured_clip_until = 0.0
    language = "auto"
    last_order = 0
    started = last_auth_check = time.monotonic()
    last_usage: tuple[int, int] | None = None
    listening = True
    last_activity: tuple[bool, bool, bool] | None = None
    stage = "start_validation"
    gate: CallInterpretationGate | None = None
    waiting = VoiceWaiting()
    playback_only_barge_in = False

    async def send(event: dict[str, Any]) -> None:
        nonlocal recent_clip_text, recent_clip_until
        clip = event.get("clip")
        if isinstance(clip, dict) and isinstance(clip.get("asset_url"), str):
            from backend.apps.audio.assistant_speech.acknowledgements import prerecorded_clip_text
            recent_clip_text = prerecorded_clip_text(clip["asset_url"])
            recent_clip_until = time.monotonic() + 5.0
        await websocket.send_json(event)

    def echo_reference() -> str:
        return assistant["clip_text"] or (recent_clip_text if time.monotonic() <= recent_clip_until else "")

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
            if gate is not None:
                await gate.bind(ACTIVE_TTL_SECONDS)

    async def disqualify_cleanup() -> None:
        nonlocal cleanup_eligible
        from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
        try:
            await ChatRecoveryService(websocket.app.state.directus_service).execute(
                "update_call_cleanup_candidate", {"protocol_version": 1,
                    "hashed_user_id": user_hash, "chat_id": chat_id, "mode": "disqualify"},
            )
        except Exception:
            # Stays eligible so the next turn retries; the record only protects
            # a chat that now holds a user message from empty-call cleanup.
            logger.exception("Voice cleanup-candidate disqualify failed call_id=%s", call_id)
            return
        cleanup_eligible = False

    async def issue(message_id: str) -> None:
        # The disqualify write runs concurrently, off the transcript's critical
        # path; transcript() awaits it after the frame is sent.
        if cleanup_eligible and cleanup_task[0] is None:
            cleanup_task[0] = asyncio.create_task(disqualify_cleanup())
        await issue_message_id(websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
                               chat_id=chat_id, call_id=call_id, message_id=message_id, role="user")

    async def new_turn() -> _SpeechTurn:
        nonlocal last_order, captured_clip_text
        if len(turns) >= MAX_PENDING_TRANSCRIPTS:
            raise TranscriptLimitError("Too many pending speech turns")
        message_id, last_order = _ordered_message_id(last_order)
        clip_text = captured_clip_text if time.monotonic() <= captured_clip_until else ""
        captured_clip_text = ""
        turn = _SpeechTurn(message_id, _timestamp(), assistant["assistant_message_id"],
                           assistant["text"], bool(assistant["speaking"] or assistant["generating"]),
                           assistant_task_id=assistant["assistant_task_id"],
                           assistant_speaking=bool(assistant["speaking"]), clip_text=clip_text or echo_reference())
        turns[message_id] = turn
        return turn

    async def interrupt(turn: _SpeechTurn, reason: str = "completed_turn") -> None:
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
        logger.info("Voice interruption call_id=%s user_message_id=%s reason=%s", call_id, turn.message_id, reason)
        await send({"type": "audio.interrupted", "call_id": call_id,
                    **({"scope": "playback"} if playback_only_barge_in else {}),
                    "assistant_message_id": turn.assistant_id, "assistant_task_id": turn.assistant_task_id,
                    "user_message_id": turn.message_id,
                    **({"clip_audio_url": assistant["clip_url"]} if turn.clip_text and assistant["clip_url"] else {})})

    async def settle_cleanup() -> None:
        task, cleanup_task[0] = cleanup_task[0], None
        if task is not None:
            await task

    async def transcript(
        turn: _SpeechTurn, *, final: bool, feedback: Awaitable[dict[str, object] | None] | None = None,
    ) -> None:
        if final:
            # Partial drafts grant no ordinary ask/tool authority.
            if feedback is None:
                await issue(turn.message_id)
            else:
                # Cache the optional cue in parallel with issuance, but publish
                # neither the cue nor the transcript until the ID is authorized.
                issuance = asyncio.create_task(issue(turn.message_id))
                try:
                    clip = await feedback
                    await issuance
                except BaseException:
                    issuance.cancel()
                    await asyncio.gather(issuance, return_exceptions=True)
                    raise
                if clip is not None:
                    await send({"type": "voice_feedback", "call_id": call_id, "clip": clip})
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
        if final:
            await settle_cleanup()

    async def prepare_voice_feedback(turn: _SpeechTurn, decision: PauseDecision | None) -> dict[str, object] | None:
        category = decision.feedback if decision else "none"
        clip_language = decision.feedback_language if decision else None
        clip = None
        if cleanup_eligible and category in {"answering", "working"} and clip_language:
            # An empty new chat has no routed Mate yet. Move its existing neutral
            # startup cue ahead of ordinary chat admission while keeping one clip.
            from backend.apps.audio.assistant_speech.acknowledgements import build_chat_start_clip
            clip = build_chat_start_clip(language=clip_language)
        try:
            async with asyncio.timeout(0.15):
                saved = await websocket.app.state.cache_service.set(
                    voice_feedback_key(call_id, turn.message_id),
                    {"category": category, "language": clip_language, "delivered": bool(clip)}, ttl=300)
        except TimeoutError:
            return None
        return clip if saved else None

    async def classify_latest(turn: _SpeechTurn) -> None:
        from backend.shared.python_utils.voice_call_intent import is_explicit_voice_stop, is_microphone_recapture
        if not turn.assistant_active:
            return
        if is_explicit_voice_stop(turn.text):
            await interrupt(turn, "explicit_stop")
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
            if (turn.assistant_speaking
                    and is_microphone_recapture(turn.text, turn.assistant_text, minimum_words=1)
                    and not is_microphone_recapture(turn.text, turn.assistant_text)):
                # A matching short partial has no independent intent yet. A
                # finalized short request still enters completion.
                turn.classifier = None
                return
            turn.classifier = asyncio.create_task(_classify(
                turn.text, turn.assistant_text, websocket, language, turn.assistant_speaking))

    async def barge_in(turn: _SpeechTurn) -> None:
        """Yield to real user speech on its first words, not at turn end."""
        from backend.shared.python_utils.voice_call_intent import is_immediate_barge_in
        if turn.interrupted:
            return
        same_task = turn.assistant_task_id == assistant["assistant_task_id"]
        same_answer = turn.assistant_id == assistant["assistant_message_id"]
        if (not turn.assistant_active and (assistant["speaking"] or assistant["generating"])) or (
            assistant["speaking"] and same_task and (same_answer or turn.assistant_id is None)
        ):
            # A provider turn can start while the task is still generating.
            # Bind the text delta to playback once that same answer starts.
            turn.assistant_active = True
            turn.assistant_id = assistant["assistant_message_id"]
            turn.assistant_task_id = assistant["assistant_task_id"]
            turn.assistant_text = assistant["text"]
            turn.assistant_speaking = bool(assistant["speaking"])
        if turn.assistant_active and is_immediate_barge_in(
                turn.text, turn.assistant_text, assistant_speaking=turn.assistant_speaking):
            await interrupt(turn, "barge_in")

    async def withdraw_likely_end(turn: _SpeechTurn) -> None:
        # Continued speech withdraws the hint; the browser drops its prepared
        # send without sending anything and may prepare again later.
        if turn.likely_end_sent:
            turn.likely_end_sent = False
            await send({"type": "turn.resumed", "call_id": call_id, "message_id": turn.message_id})

    def invalidate_completion(turn: _SpeechTurn) -> None:
        # Cancel without waiting on network work: resumed speech must continue
        # to arrive. Retired checks remain tracked until they settle or hangup.
        if turn.completion is not None:
            turn.completion.cancel()
            turn.completion = None
            # A cancelled decision never settled this text revision. A later
            # stable endpoint may retry it even when STT added no new words.
            turn.completion_text = ""
        # Resumed speech revokes a silence fallback and earns a fresh retry.
        turn.submit_on_silence = False
        turn.completion_retried = False
        turn.completion_started = 0.0

    def start_completion(turn: _SpeechTurn, text: str, timeout: float = COMPLETION_CHECK_DEADLINE_SECONDS) -> None:
        turn.completion_text = text
        turn.completion_started = turn.completion_started or time.monotonic()
        if playback_only_barge_in and turn.assistant_active and not waiting.active:
            check = _complete(text, websocket, timeout, playback_control=True)
        elif feedback_enabled:
            check = _complete(text, websocket, timeout, with_feedback=True)
        elif timeout == COMPLETION_CHECK_DEADLINE_SECONDS:
            check = _complete(text, websocket)
        else:
            check = _complete(text, websocket, timeout)
        turn.completion = asyncio.create_task(check)
        completion_tasks.add(turn.completion)
        turn.completion.add_done_callback(completion_finished)

    def schedule_endpoint(turn: _SpeechTurn, now: float, *, local: bool, drained: bool = False) -> None:
        if local and (turn.deadline is not None or turn.submit_on_silence):
            return
        grace = LOCAL_ENDPOINT_TRANSCRIPT_GRACE_SECONDS if local else STREAMING_DELAY_MS / 1000
        deadline = now if drained else now + grace
        if turn.deadline is not None:
            # Preserve an existing thinking delay. An earlier verified endpoint
            # can otherwise stand when the provider repeats it.
            deadline = max(deadline, turn.deadline) if turn.submit_on_silence else min(deadline, turn.deadline)
        turn.deadline = deadline
        turn.local_endpoint = local
        turn.drained_endpoint = drained
        text = turn.text.strip()
        if (text and not turn.assistant_active and turn.completion is None and turn.completion_text != text
                and not is_prerecorded_clip_echo(text, turn.clip_text)):
            start_completion(turn, text)

    def completion_finished(task: asyncio.Task[str]) -> None:
        completion_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def finish_ready_turns(now: float) -> None:
        nonlocal current, closed_local_turn
        from backend.shared.python_utils.voice_call_intent import (
            assistant_question_pending, is_explicit_voice_stop, is_listener_acknowledgement, is_microphone_recapture)
        for turn in list(turns.values()):
            if turn.classifier is not None:
                if not turn.classifier.done():
                    continue
                turn.verdict = turn.classifier.result()
                turn.classifier = None
                if turn.verdict == "interrupt":
                    await interrupt(turn, "intent")
            if turn.deadline is None or now < turn.deadline:
                continue
            text = turn.text.strip()
            explicit_stop = turn.assistant_active and is_explicit_voice_stop(text)
            reason = None
            if not text:
                reason = "empty"
            elif is_prerecorded_clip_echo(text, turn.clip_text):
                reason = "echo"
            elif explicit_stop and not feedback_enabled:
                await interrupt(turn, "explicit_stop")
                reason = "stop"
            elif (turn.verdict == "echo" and turn.assistant_speaking and assistant["speaking"]
                    and turn.assistant_id is not None and turn.assistant_id == assistant["assistant_message_id"]
                    and turn.assistant_task_id == assistant["assistant_task_id"]):
                # A model-supported echo verdict is tied to playback of this
                # exact answer. Never let late results suppress real new speech.
                reason = "echo"
            elif turn.verdict != "interrupt" and turn.assistant_speaking and (
                    is_microphone_recapture(text, turn.assistant_text) or (
                        turn.assistant_id is not None and turn.assistant_id == assistant["assistant_message_id"]
                        and is_microphone_recapture(text, assistant["text"]))):
                # Heard during playback and nothing but a verbatim slice of that
                # speech: microphone recapture, which also never barges in. A
                # deliberate quote is an interrupt verdict and stays a turn.
                reason = "echo"
            elif turn.assistant_active and (turn.verdict == "backchannel" or (turn.verdict == "uncertain" and is_listener_acknowledgement(text)
                    and not assistant_question_pending(turn.assistant_text))):
                reason = "backchannel"
            else:
                # Native endpointing only schedules this small text decision.
                # No chat admission, skill selection or ordinary inference runs
                # until this exact text revision is confirmed complete.
                if turn.submit_on_silence and turn.completion is None and turn.completion_text == text:
                    # The silence window after an uncertain decision elapsed
                    # without new speech for this exact text revision.
                    verdict = "complete"
                    decision = None
                else:
                    if turn.completion is None:
                        if turn.completion_text != text:
                            start_completion(turn, text)
                        continue
                    if not turn.completion.done():
                        continue
                    decision = as_pause_decision(turn.completion.result())
                    verdict = decision.completion
                    turn.completion = None
                    if turn.completion_text != text and _material_change(turn.completion_text, text):
                        # Words arrived after the check started: its verdict is
                        # stale. Re-check only inside the overall deadline.
                        remaining = COMPLETION_CHECK_DEADLINE_SECONDS - (now - turn.completion_started)
                        if remaining >= COMPLETION_RECHECK_MIN_BUDGET_SECONDS:
                            start_completion(turn, text, remaining)
                            continue
                        verdict = "unavailable"
                        decision = as_pause_decision("unavailable")
                    elif turn.completion_text != text:
                        turn.completion_text = text
                # The model-judged intent (hold, back, repeat) is acted on by the
                # waiting state below, whatever the verdict.
                intent = decision.intent if decision is not None else "none"
                if explicit_stop and intent not in {"wait", "pause_playback"}:
                    await interrupt(turn, "explicit_stop")
                    intent = "stop"
                if verdict == "unavailable":
                    # Timeout/outage never blocks the turn: send it as complete.
                    logger.warning("VOICE_COMPLETION_CHECK fail_open call_id=%s verdict=complete", call_id)
                    verdict = "complete"
                if verdict != "complete" and intent == "none":
                    if decision is not None and decision.verdict == "wait":
                        # The user asked to hold: no automatic submission; the
                        # turn stays open until speech continues it.
                        turn.deadline = None
                    elif verdict == "incomplete":
                        turn.submit_on_silence = True
                        turn.deadline = now + STILL_THINKING_SILENCE_SECONDS
                    else:
                        turn.submit_on_silence = True
                        turn.deadline = now + UNCERTAIN_SILENCE_FALLBACK_SECONDS
                    await send({"type": "transcript.pending", "call_id": call_id,
                                "message_id": turn.message_id,
                                "reason": "incomplete" if verdict == "incomplete" or (
                                    decision is not None and decision.verdict == "wait") else "uncertain"})
                    continue
                if intent == "wait" and turn.assistant_active:
                    await interrupt(turn, "waiting")
                clip = None
                if feedback_enabled and intent == "wait" and decision and decision.feedback_language:
                    from backend.apps.ai.assistant_speech.voice_status import select_categorized_voice_feedback
                    try:
                        async with asyncio.timeout(0.15):
                            profile = await websocket.app.state.cache_service.get(f"voice_call_last_profile:{call_id}")
                    except TimeoutError:
                        profile = None
                    if isinstance(profile, str):
                        clip = select_categorized_voice_feedback(
                            voice_profile_id=profile, category="wait", language=decision.feedback_language,
                            seed=turn.message_id,
                        )
                    if clip is None:
                        from backend.apps.audio.assistant_speech.acknowledgements import build_waiting_line_clip
                        clip = build_waiting_line_clip(line="waiting_start", language=decision.feedback_language)
                reason, text = await waiting.route(text, intent, send=send, call_id=call_id, clip=clip,
                                                   categorized=feedback_enabled)
                if reason in {"waiting", "pause_playback"} and turn.assistant_active:
                    await interrupt(turn, "waiting")
                if reason is None:
                    await interrupt(turn)
                    turn.text = text
                    feedback = prepare_voice_feedback(turn, decision) if feedback_enabled else None
                    await transcript(turn, final=True, feedback=feedback)
            if reason is not None:
                # No transcript text is logged; the reason makes discards diagnosable.
                logger.info("Voice transcript discarded call_id=%s message_id=%s reason=%s",
                            call_id, turn.message_id, reason)
                await send({"type": "transcript.discarded", "call_id": call_id,
                            "message_id": turn.message_id, "reason": reason})
            invalidate_completion(turn)
            turns.pop(turn.message_id)
            if current is turn:
                closed_local_turn = turn.local_endpoint
                current = None

    try:
        accepted_at = time.monotonic()
        start_message = await asyncio.wait_for(websocket.receive_text(), 10)
        # Stage timing: a start that never reaches ready shows where it waits.
        logger.info("Voice call start stage=start_received call_id=%s elapsed_ms=%d",
                    call_id, (time.monotonic() - accepted_at) * 1000)
        chat_id, _summary, _messages, startup_ms = _start(start_message)
        likely_end_hints = _likely_end_hints(start_message)
        start_options = json.loads(start_message)
        playback_only_barge_in = start_options.get("playback_only_barge_in", False)
        state_cues = start_options.get("voice_state_cues", False)
        if not isinstance(playback_only_barge_in, bool) or not isinstance(state_cues, bool):
            raise ValueError("Invalid voice call capability")
        state_cues = state_cues or playback_only_barge_in
        _context_options(start_options.get("context", {}))
        allowance = startup_ms * PCM_INPUT_BYTES_PER_SECOND // 1000
        stage = "personal_chat"
        logger.info("Voice call start stage=%s call_id=%s elapsed_ms=%d", stage, call_id,
                    (time.monotonic() - accepted_at) * 1000)
        if not await _personal_chat(websocket, chat_id, user_id):
            raise ValueError("Chat unavailable")
        # Bind call admission before provider work under the same durable chat
        # lock as automatic cleanup. Older clients disqualify any prior attempt.
        from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
        cleanup_attempt_id = start_options.get("cleanup_attempt_id")
        feedback_enabled = instant_feedback_enabled(start_options) and not state_cues
        cleanup_state = await ChatRecoveryService(websocket.app.state.directus_service).execute(
            "update_call_cleanup_candidate", {"protocol_version": 1,
                "hashed_user_id": user_hash, "chat_id": chat_id, "mode": "start",
                "cleanup_attempt_id": cleanup_attempt_id, "call_id": call_id},
        )
        cleanup_tracking_started = True
        cleanup_eligible = cleanup_state.get("eligible") is True
        stage = "session"
        logger.info("Voice call start stage=%s call_id=%s elapsed_ms=%d", stage, call_id,
                    (time.monotonic() - accepted_at) * 1000)
        if not await _session_still_valid(websocket, auth_data):
            raise ValueError("Session unavailable")
        stage = "credits"
        logger.info("Voice call start stage=%s call_id=%s elapsed_ms=%d", stage, call_id,
                    (time.monotonic() - accepted_at) * 1000)
        if is_payment_enabled() and await _authoritative_credits(websocket, user_id) < REALTIME_TRANSCRIPTION_MINIMUM_CREDITS:
            raise InsufficientCreditsError("Insufficient credits")
        stage = "lock"
        logger.info("Voice call start stage=%s call_id=%s elapsed_ms=%d", stage, call_id,
                    (time.monotonic() - accepted_at) * 1000)
        lock_client, lock_key, lock_token = await _acquire_lock(websocket, user_hash)
        lease_task = asyncio.create_task(_renew_lock(lock_client, lock_key, lock_token))
        await register_active_call(websocket.app.state.cache_service, user_id=user_id,
                                   session_id=session_id, chat_id=chat_id, call_id=call_id,
                                   instant_feedback=feedback_enabled, state_cues=state_cues)
        registered = True
        # Updates from chats this chat started are spoken at quiet moments.
        gate = CallInterpretationGate(
            cache_service=websocket.app.state.cache_service, directus_service=websocket.app.state.directus_service,
            encryption_service=websocket.app.state.encryption_service, user_id=user_id, chat_id=chat_id,
            call_id=call_id, issue=issue, send=send,
        )
        await gate.bind(ACTIVE_TTL_SECONDS)
        registry_task = asyncio.create_task(registry_renewal())
        stage = "provider_open"
        logger.info("Voice call start stage=%s call_id=%s elapsed_ms=%d", stage, call_id,
                    (time.monotonic() - accepted_at) * 1000)
        prewarm_task = asyncio.create_task(_prewarm_completion())
        provider = await _provider(websocket)
        await provider.open()
        stage = "active"
        logger.info("Voice call start stage=%s call_id=%s elapsed_ms=%d", stage, call_id,
                    (time.monotonic() - accepted_at) * 1000)
        started = last_auth_check = time.monotonic()
        # Set before awaiting transport: a send failure/cancellation may still
        # have exposed Ready, so it must never grant null-ID cleanup authority.
        cleanup_ready_exposed = True
        await send({"type": "ready", "call_id": call_id, "provider": "mistral", "model": provider.model,
                    **({"verified_endpoint": True} if playback_only_barge_in else {}),
                    "speech_output_transport": SPEECH_OUTPUT_TRANSPORT,
                    "input_sample_rate": 16000, "output_sample_rate": 24000,
                    "billing_basis": "speech_duration_and_chat_usage",
                    "rates": {
                        "stt_credits_per_second": REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE / 60,
                        # Older Apple clients require this field on the ready frame.
                        "stt_credits_per_started_minute": REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE,
                    },
                    "camera_available": True})
        await activity()
        client_receive = asyncio.create_task(websocket.receive_text())
        provider_receive = asyncio.create_task(provider.receive())
        live_provider = provider

        async def admit_audio(size: int) -> None:
            # Check headroom before sending a frame that raises the rounded credit total.
            reserve = ledger.credits_with(size) - ledger.charged
            if is_payment_enabled() and reserve > 0 and await _authoritative_credits(websocket, user_id) < reserve:
                raise InsufficientCreditsError("Insufficient credits")

        async def accept_audio(size: int) -> None:
            ledger.audio_bytes += size
            await _charge_voice(websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id, chat_id=chat_id)

        audio = MicAudioForwarder(call_id=call_id, admit=admit_audio, send_audio=live_provider.send_audio,
                                  end_audio=live_provider.end_audio, accepted=accept_audio, progress=audio_progress.set)
        audio_progress_wait = asyncio.create_task(audio_progress.wait())
        while True:
            now = time.monotonic()
            if lease_task.done():
                await lease_task
            if audio.task.done():
                await audio.task
                raise RuntimeError("Voice audio forwarding stopped")
            if registry_task.done():
                await registry_task
            if now - last_auth_check >= 5:
                if not await _session_still_valid(websocket, auth_data):
                    raise RuntimeError("Session expired or revoked")
                last_auth_check = now
            waiters = {client_receive, provider_receive, lease_task, registry_task, audio.task, audio_progress_wait}
            waiters.update(turn.classifier for turn in turns.values() if turn.classifier is not None)
            # A decision can settle before trailing words have finished arriving.
            # An already-finished future would wake the call continuously until
            # the deadline. Wait for new input, an unfinished check or its timer.
            waiters.update(turn.completion for turn in turns.values()
                           if turn.completion is not None and not turn.completion.done())
            deadlines = [turn.deadline for turn in turns.values() if turn.deadline is not None
                         and turn.classifier is None and (turn.completion is None or turn.completion.done())]
            timeout = min(1.0, max(0, min(deadlines) - now)) if deadlines else 1.0
            done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if audio_progress_wait in done:
                audio_progress.clear()
                audio_progress_wait = asyncio.create_task(audio_progress.wait())
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
                    prospective = audio.queued_bytes + len(chunk)
                    if prospective > ((time.monotonic() - started + AUDIO_JITTER_SECONDS) * PCM_INPUT_BYTES_PER_SECOND + allowance):
                        raise ValueError("Audio stream exceeds real-time rate")
                    # Credits, provider write and charge run in order on the
                    # forwarder, so transcript events keep flowing meanwhile.
                    audio.push(event["data"], len(chunk))
                    # Voxtral can return the words after playback has already
                    # switched to the generated answer. Keep the clip on the
                    # audio that was captured while its reference was active.
                    clip_text = echo_reference()
                    if clip_text:
                        if current is None:
                            captured_clip_text = clip_text
                            captured_clip_until = time.monotonic() + STREAM_RECEIVE_TIMEOUT
                        elif not current.text and not current.clip_text:
                            current.clip_text = clip_text
                    verified_quiet_frame = None
                    local_endpoint_bytes = None
                    if current is not None and (current.local_endpoint or current.drained_endpoint):
                        await withdraw_likely_end(current)
                        invalidate_completion(current)
                        current.deadline = None
                        current.local_endpoint = False
                        current.drained_endpoint = False
                    listening = True
                elif kind == "ping":
                    pass
                elif kind == "hold":
                    if event.get("call_id") != call_id or type(event.get("active")) is not bool:
                        raise ValueError("Invalid hold event")
                    pending = current.text if current is not None else ""
                    if event["active"] and current is not None:
                        invalidate_completion(current)
                        turns.pop(current.message_id, None)
                        await send({"type": "transcript.discarded", "call_id": call_id,
                                    "message_id": current.message_id, "reason": "waiting"})
                        current = None
                    await waiting.set_active(event["active"], send=send, call_id=call_id, pending_text=pending)
                elif kind == "audio_stream_end":
                    audio.end()
                    listening = False
                    verified_quiet_frame = None
                    local_endpoint_bytes = None
                    if event.get("verified_silence") is True and audio.queued_bytes:
                        local_endpoint_bytes = audio.queued_bytes
                        verified_quiet_frame = audio.queued_frames
                elif kind == "assistant_state":
                    speaking, generating = event.get("speaking"), event.get("generating", False)
                    text, identity = event.get("text", ""), event.get("assistant_message_id")
                    task_id = event.get("assistant_task_id")
                    clip_audio_url = event.get("clip_audio_url")
                    if (type(speaking) is not bool or type(generating) is not bool or not isinstance(text, str)
                            or len(text) > MAX_TEXT_CHARS or (identity is not None and
                            (not isinstance(identity, str) or not MESSAGE_ID.fullmatch(identity)))
                            or (task_id is not None and (not isinstance(task_id, str) or not MESSAGE_ID.fullmatch(task_id)))
                            or (clip_audio_url is not None and (not isinstance(clip_audio_url, str) or len(clip_audio_url) > 256))):
                        raise ValueError("Invalid assistant state")
                    clip_text = ""
                    if clip_audio_url:
                        # A playing prerecorded clip: its approved words join the
                        # spoken text so its microphone echo is recapture (EYHC5).
                        from backend.apps.audio.assistant_speech.acknowledgements import prerecorded_clip_text
                        clip_text = prerecorded_clip_text(clip_audio_url)
                        text = "\n".join(part for part in (clip_text, text) if part)
                    if clip_text:
                        recent_clip_text = clip_text
                        recent_clip_until = time.monotonic() + 1.0
                    elif assistant["clip_text"]:
                        recent_clip_until = time.monotonic() + 0.7
                    assistant.update(speaking=speaking, generating=generating, text=text,
                                     assistant_message_id=identity, assistant_task_id=task_id,
                                     clip_text=clip_text, clip_url=clip_audio_url if clip_text else None)
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
                                if event.get("pasted") is True:
                                    await mark_pasted(websocket.app.state.cache_service, call_id, identity)
                                await interrupt(turn, "text_input")
                                await transcript(turn, final=True)
                                seen_text_ids[identity] = (text, created)
                            await send({"type": "text_input.accepted", "call_id": call_id, "message_id": identity})
                elif kind == "stt_terms":
                    set_bias = getattr(provider, "set_context_bias", None)
                    try:
                        terms = parse_terms(event)
                    except ValueError:
                        await send({"type": "stt_terms_rejected", "call_id": call_id, "code": "invalid_terms"})
                    else:
                        if set_bias is not None:
                            await set_bias(terms)
                        await send({"type": "stt_terms.accepted", "call_id": call_id, "count": len(terms)})
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
                    closed_local_turn = False
                    if current is not None:
                        # A provider can split a thinking pause into multiple
                        # turns. Retain the unfinished request and its identity.
                        await withdraw_likely_end(current)
                        invalidate_completion(current)
                        current.deadline = None
                        current.local_endpoint = False
                        current.drained_endpoint = False
                        current.separate_next_delta = bool(current.text)
                    else:
                        current = await new_turn()
                elif kind == "transcription.text.delta":
                    delta = event.get("text")
                    if not isinstance(delta, str):
                        raise ValueError("Invalid transcript delta")
                    if delta and not closed_local_turn:
                        if current is None:
                            current = await new_turn()
                        if (current.completion is not None and not current.completion.done()
                                and current.deadline is not None):
                            # Late delta after turn.end: keep the check in flight;
                            # the verdict is reconciled against the new text.
                            current.submit_on_silence = False
                        else:
                            invalidate_completion(current)
                        separator = " " if (current.separate_next_delta and current.text
                            and not current.text[-1].isspace() and not delta[0].isspace()) else ""
                        current.separate_next_delta = False
                        current.text = _bounded_transcript(current.text + separator + delta)
                        language = event.get("language") if isinstance(event.get("language"), str) and len(event["language"]) <= 32 else language
                        if not current.clip_text:
                            current.clip_text = echo_reference()
                        if not is_prerecorded_clip_echo(current.text, current.clip_text):
                            if gate is not None:
                                gate.user_spoke()
                            await transcript(current, final=False)
                            await barge_in(current)
                            await classify_latest(current)
                elif kind == "turn.end":
                    if current is not None:
                        # Every word in this exact quiet capture window has arrived.
                        # Keep the semantic decision; only its trailing-word timer
                        # can be skipped. Later microphone input revokes the endpoint.
                        frame = event.get("drained_input_frame")
                        drained = type(frame) is int and frame == verified_quiet_frame
                        schedule_endpoint(current, time.monotonic(), local=False, drained=drained)
                    else:
                        captured_clip_text = ""
                elif kind == "turn.eager_end":
                    # Eager endpointing never authorizes chat or tools. The
                    # browser may only prepare the send (no model call) and
                    # commits it on the final transcript.
                    if (likely_end_hints and current is not None and current.text.strip()
                            and not is_prerecorded_clip_echo(current.text, current.clip_text)
                            and not current.assistant_active and not current.likely_end_sent):
                        current.likely_end_sent = True
                        await send({"type": "turn.likely_end", "call_id": call_id,
                                    "message_id": current.message_id})
                elif kind == "turn.resume":
                    closed_local_turn = False
                    if current is not None:
                        await withdraw_likely_end(current)
                        invalidate_completion(current)
                        current.deadline = None
                        current.local_endpoint = False
                        current.drained_endpoint = False
                elif kind == "transcription.done":
                    # input_audio.end is never sent for mute. An unexpected
                    # terminal provider session cannot silently drop future audio.
                    raise RuntimeError("Voice transcription session ended")
                elif kind == "error":
                    raise RuntimeError("Voice transcription failed")
                provider_receive = asyncio.create_task(provider.receive())
            now = time.monotonic()
            if (local_endpoint_bytes is not None and ledger.audio_bytes >= local_endpoint_bytes
                    and current is not None and current.text.strip()):
                local_endpoint_bytes = None
                schedule_endpoint(current, now, local=True)
            await finish_ready_turns(now)
            await gate.tick(assistant_active=bool(assistant["speaking"] or assistant["generating"]),
                            speech_pending=current is not None or bool(turns))
            usage = (ledger.audio_bytes, ledger.charged)
            if usage != last_usage:
                await send(ledger.view(time.monotonic() - started))
                last_usage = usage
            await activity()
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        drain_audio = False
        raise
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        origin = frames[-1] if frames else None
        logger.warning("Voice call ended category=%s function=%s line=%s stage=%s call_id=%s",
                       type(exc).__name__, origin.name if origin else "unknown", origin.lineno if origin else 0, stage, call_id)
        try:
            code = ("context_too_large" if isinstance(exc, ContextLimitError)
                    else "transcript_limit" if isinstance(exc, TranscriptLimitError)
                    else "insufficient_credits" if isinstance(exc, InsufficientCreditsError)
                    else "call_unavailable")
            await send({"type": "error", "code": code, "stage": stage, "message": "Call unavailable. Your call has ended."})
        except Exception:
            pass
    finally:
        visuals.close()
        if audio is not None and drain_audio:
            # Frames the client sent before the end still reach the provider in order.
            try:
                await audio.drain()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Voice audio drain failed call_id=%s category=%s", call_id, type(exc).__name__)
        tasks = [task for task in (client_receive, provider_receive, lease_task, registry_task, prewarm_task,
                 audio.task if audio is not None else None, audio_progress_wait,
                 *(turn.classifier for turn in turns.values()), *completion_tasks) if task is not None]
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
        if gate is not None:
            try:
                await _finish_accepted_job(asyncio.create_task(gate.close()))
            except asyncio.CancelledError:
                cancelled = True
            except (RuntimeError, ValueError, ConnectionError) as exc:
                # Buffered updates stay stored; the next event or call retries them.
                logger.warning("Voice call orchestration unbind failed call_id=%s category=%s", call_id, type(exc).__name__)
        if registered:
            try:
                await _finish_accepted_job(asyncio.create_task(finalize_active_call(
                    websocket.app.state.cache_service, user_id=user_id, session_id=session_id, chat_id=chat_id, call_id=call_id,
                )))
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                logger.warning("Voice registry finalization failed call_id=%s", call_id)
        if cleanup_tracking_started:
            try:
                from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
                await _finish_accepted_job(asyncio.create_task(
                    ChatRecoveryService(websocket.app.state.directus_service).execute(
                        "update_call_cleanup_candidate", {"protocol_version": 1,
                            "hashed_user_id": user_hash, "chat_id": chat_id, "mode": "finish",
                            "cleanup_attempt_id": cleanup_attempt_id, "call_id": call_id,
                            "ready_exposed": cleanup_ready_exposed},
                    ),
                ))
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                # RUNNING is deliberately retained when finalization cannot be
                # proved; missing/failed authority always preserves the chat.
                logger.warning("Voice cleanup finalization unavailable")
        if lock_client is not None:
            await _release_lock(lock_client, lock_key, lock_token)
        try:
            await websocket.close()
        except Exception:
            pass
        if cancelled:
            raise asyncio.CancelledError
