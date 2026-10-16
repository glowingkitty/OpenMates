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
import math
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from backend.core.api.app.routes.audio_realtime import _browser_request_is_allowed
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user, get_directus_service, get_cache_service
from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.video_call_experiment import (
    GEMINI_MODEL, INPUT_RATES, LOCK_RENEW_SECONDS, MIN_VOICE_HEADROOM,
    UsageLedger, _acquire_lock, _authoritative_credits, _billing, _credits_for,
    _finish_accepted_job, _release_lock, _renew_lock, _session_still_valid,
)
from backend.core.api.app.services.direct_chat_access import is_direct_chat
from backend.core.api.app.utils.server_mode import is_payment_enabled
from backend.shared.providers.gemini_live_voice import GeminiLiveVoiceSession
from backend.shared.providers.live_voice import LiveVoiceSession
from backend.apps.ai.processing.voice_call_broker import VoiceToolOperationError
from backend.shared.python_utils.voice_call_registry import (
    finalize_active_call, issue_message_id, register_active_call, renew_active_call,
)
from backend.shared.testing.voice_call_fixture import (
    IsolatedGeminiVoiceFixture, VOICE_ACK_DEFAULT_TIMESTAMP, consume_voice_ack_fixture_write_failure,
    isolated_voice_fixture_enabled, set_voice_ack_fixture_fail_next_write,
    set_voice_ack_fixture_profile_mode, voice_ack_fixture_requires_profile,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")
MAX_START_BYTES = 256_000
MAX_CONTEXT_CHARS = 64_000
MAX_SUMMARY_CHARS = 48_000
MAX_TEXT_CHARS = 8_000
MAX_AUDIO_CHUNK = 128 * 1024
PCM_INPUT_BYTES_PER_SECOND = 32000
MAX_STARTUP_AUDIO_ALLOWANCE_MS = 10_000
AUDIO_JITTER_SECONDS = 2
MAX_QUEUED_INPUT_BYTES = 2 * 1024 * 1024
MAX_PENDING_TRANSCRIPTS = 32
AUDIO_TOKENS_PER_SECOND_ADMISSION = Decimal(40)  # Conservative over Google's documented 32 tokens/s.
MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
GOOGLE_PROCESSING_ACK_FIELD = "voice_google_processing_ack_v1_at"
GOOGLE_PROCESSING_ACK_VERSION = 1


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


async def _prompt_configuration(websocket: WebSocket, *, mate_category: str | None = None,
                                user_id: str | None = None) -> dict[str, str]:
    """Load trusted shared ethics and public app descriptions, never tool schemas."""
    cache = websocket.app.state.cache_service
    loader = getattr(cache, "get_base_instructions", None)
    instructions = await loader() if loader else None
    if not isinstance(instructions, dict) or not instructions.get("base_ethics_instruction"):
        from backend.apps.ai.utils.instruction_loader import load_base_instructions
        instructions = load_base_instructions()
    ethics = instructions.get("base_ethics_instruction")
    if not isinstance(ethics, str) or not ethics.strip():
        raise RuntimeError("Voice ethics configuration unavailable")
    metadata = getattr(websocket.app.state, "discovered_apps_metadata", {}) or {}
    registry = getattr(websocket.app.state, "skill_registry", None)
    translation = getattr(websocket.app.state, "translation_service", None)
    def field(item: Any, name: str, default: Any = None) -> Any:
        return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)
    catalogue = []
    for app_id, app in sorted(metadata.items()):
        if (not re.fullmatch(r"[a-z0-9_\-]{1,128}", app_id) or field(app, "internal", False)
                or field(app, "default_enabled") is False):
            continue
        has_skill = any(
            not field(skill, "internal", False) and field(skill, "default_enabled") is not False
            and bool(field(skill, "tool_schema")) and registry is not None
            and registry.is_skill_available(app_id, field(skill, "id"))
            for skill in field(app, "skills", [])
        )
        has_focus = any(field(focus, "default_enabled") is not False for focus in field(app, "focuses", []))
        has_memory = any(field(memory, "default_enabled") is not False for memory in field(app, "memory_fields", []))
        if app_id != "projects" and not (has_skill or has_focus or has_memory):
            continue
        key = field(app, "description_translation_key")
        description = translation.get_nested_translation(key, "en") if translation and isinstance(key, str) else ""
        if not isinstance(description, str):
            description = ""
        catalogue.append(f"{app_id}: {' '.join(description.split())[:240]}")
    learning_mode = {"enabled": False}
    if user_id:
        from backend.core.api.app.routes.learning_mode import _load_learning_mode_policy
        from backend.shared.python_utils.learning_mode import build_learning_mode_context, build_learning_mode_global_prompt
        learning_mode = build_learning_mode_context(await _load_learning_mode_policy(
            user_id, cache, websocket.app.state.directus_service,
        ))
        if learning_mode.get("enabled"):
            ethics += "\n\n" + build_learning_mode_global_prompt(learning_mode["age_group"])
    configuration = {"base_instruction": ethics, "app_catalogue": "\n".join(catalogue)}
    if mate_category:
        from backend.apps.ai.utils.mate_utils import load_mates_config
        from backend.apps.ai.utils.voice_mate import mate_voice_configuration
        load_mates = getattr(cache, "get_mates_configs", None)
        mates = (await load_mates() if load_mates else None) or load_mates_config()
        mate = next((mate for mate in mates if mate.category == mate_category), None)
        if mate is None:
            raise ValueError("Unknown voice mate category")
        configuration.update(mate_voice_configuration(mate, learning_mode=learning_mode.get("enabled") is True))
    return configuration


async def _broker(websocket: WebSocket, **kwargs: Any) -> Any:
    # This import loads only the sealed transport; AI model execution is in the worker.
    from backend.apps.ai.processing.voice_call_broker import create_voice_call_broker
    return await create_voice_call_broker(websocket, **kwargs)


def _start(message: str) -> tuple[str, str, list[dict[str, Any]], int]:
    if len(message.encode("utf-8")) > MAX_START_BYTES:
        raise ContextLimitError("Call start exceeds limit")
    event = json.loads(message)
    if not isinstance(event, dict) or event.get("type") != "start":
        raise ValueError("Call start required")
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
    summary, messages = _context(event.get("context"))
    return chat_id, summary, messages, startup_audio_allowance_ms


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


async def _charge_voice(websocket: WebSocket, ledger: UsageLedger, *, user_id: str, user_hash: str, call_id: str, chat_id: str) -> None:
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
            "usage_type": "voice_call", "model_used": GEMINI_MODEL,
            "chat_id": chat_id,
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


async def _google_processing_ack_at(directus: DirectusService, user_id: str) -> int | None:
    """Read the durable profile field; session cache is never admission authority."""
    fields = await directus.get_user_fields_direct(user_id, [GOOGLE_PROCESSING_ACK_FIELD], no_cache=True)
    if fields is None:
        raise RuntimeError("Google voice acknowledgment unavailable")
    value = fields.get(GOOGLE_PROCESSING_ACK_FIELD)
    return value if type(value) is int and value > 0 else None


async def _effective_google_processing_ack_at(
    directus: DirectusService, cache: CacheService, user_id: str,
) -> int | None:
    if isolated_voice_fixture_enabled() and not await voice_ack_fixture_requires_profile(cache, user_id):
        return VOICE_ACK_DEFAULT_TIMESTAMP
    return await _google_processing_ack_at(directus, user_id)


def _first_party_voice_request(request: Request) -> None:
    # First-party session surface only, never an API-key or cross-origin consent write.
    origin = request.headers.get("origin")
    allowed = getattr(request.app.state, "allowed_origins", []) or []
    if not origin or origin not in allowed:
        raise HTTPException(status_code=403, detail="Origin not allowed")


@router.get("/settings/voice-google-processing-ack", include_in_schema=False)
@limiter.limit("30/minute")
async def get_google_processing_ack(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus: DirectusService = Depends(get_directus_service),
    cache: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    _first_party_voice_request(request)
    try:
        acknowledged_at = await _effective_google_processing_ack_at(directus, cache, current_user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Voice acknowledgment unavailable") from exc
    return {"version": GOOGLE_PROCESSING_ACK_VERSION, "acknowledged": acknowledged_at is not None,
            "acknowledged_at": acknowledged_at}


@router.post("/settings/voice-google-processing-ack", include_in_schema=False)
@limiter.limit("10/minute")
async def record_google_processing_ack(
    request: Request,
    body: dict[str, Any],
    current_user: User = Depends(get_current_user),
    directus: DirectusService = Depends(get_directus_service),
    cache: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    _first_party_voice_request(request)
    if body != {"version": GOOGLE_PROCESSING_ACK_VERSION} or type(body.get("version")) is not int:
        raise HTTPException(status_code=422, detail="Unsupported acknowledgment version")
    try:
        acknowledged_at = await _effective_google_processing_ack_at(directus, cache, current_user.id)
        if acknowledged_at is None:
            if await consume_voice_ack_fixture_write_failure(cache, current_user.id):
                raise RuntimeError("Isolated voice acknowledgment write failure")
            if not await directus.update_user(current_user.id, {GOOGLE_PROCESSING_ACK_FIELD: _timestamp()}):
                raise RuntimeError("Google voice acknowledgment write failed")
            acknowledged_at = await _google_processing_ack_at(directus, current_user.id)
            if acknowledged_at is None:
                raise RuntimeError("Google voice acknowledgment write not confirmed")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Voice acknowledgment unavailable") from exc
    return {"version": GOOGLE_PROCESSING_ACK_VERSION, "acknowledged": True,
            "acknowledged_at": acknowledged_at}


@router.post("/settings/voice-google-processing-ack/fixture", include_in_schema=False)
@limiter.limit("10/minute")
async def configure_google_processing_ack_fixture(
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
    if not await directus.update_user(current_user.id, {GOOGLE_PROCESSING_ACK_FIELD: None}):
        raise HTTPException(status_code=503, detail="Voice fixture unavailable")
    try:
        acknowledged_at = await _google_processing_ack_at(directus, current_user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Voice fixture unavailable") from exc
    if acknowledged_at is not None:
        raise HTTPException(status_code=503, detail="Voice fixture unavailable")
    await set_voice_ack_fixture_profile_mode(cache, current_user.id)
    return {"configured": True}


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
    try:
        acknowledged_at = await _effective_google_processing_ack_at(
            websocket.app.state.directus_service, websocket.app.state.cache_service, user_id,
        )
    except RuntimeError:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="google_voice_ack_unavailable")
        return
    if acknowledged_at is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="google_voice_ack_required")
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
    turn_assistant_user_id: str | None = None
    turn_assistant_artifacts: dict[str, str] = {}
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
    voiced_audio_bytes = 0
    audio_activity_active = False
    output_audio_bytes = 0
    checkpoint_audio_bytes = 0
    checkpoint_output_bytes = 0
    last_finalized_audio_bytes = 0
    settled_audio_bytes = 0
    resume_handle: str | None = None
    handoff_deadline = 0.0
    queued_inputs: deque[tuple[str, str]] = deque()
    queued_bytes = 0
    last_auth_check = 0.0
    broker: Any = None
    tool_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
    permission_paused_tools: set[str] = set()
    seen_tool_ids: set[str] = set()
    tool_bindings: dict[str, tuple[int, str, str, int]] = {}
    tool_responses: dict[str, dict[str, Any]] = {}
    compression_task: asyncio.Task[dict[str, Any]] | None = None
    pending_checkpoint: dict[str, Any] | None = None
    checkpoint_confirmed = False
    context_paused = False
    context_paused_at = 0.0
    pause_requested = False
    checkpoint_requested_at = 0.0
    compression_snapshot_id = ""
    compression_source_versions: dict[str, dict[str, Any]] = {}
    turn_generation = 0
    call_context: dict[str, Any] = {}
    context_messages: dict[str, dict[str, Any]] = {}
    input_listening = False
    processing = False
    compression_processing = False
    last_billing_activity: tuple[bool, bool] | None = None

    async def send(event: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(event)

    async def billing_activity(*, listening: bool | None = None, generating: bool | None = None,
                               compressing: bool | None = None) -> None:
        nonlocal input_listening, processing, compression_processing, last_billing_activity
        if listening is not None:
            input_listening = listening
        if generating is not None:
            processing = generating
        if compressing is not None:
            compression_processing = compressing
        activity = (input_listening, processing or compression_processing)
        if activity != last_billing_activity:
            await send({"type": "billing_activity", "call_id": call_id,
                        "input_listening": activity[0], "processing": activity[1]})
            last_billing_activity = activity

    async def issue(message_id: str, role: str) -> None:
        await issue_message_id(
            websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
            chat_id=chat_id, call_id=call_id, message_id=message_id, role=role,
        )

    async def invalidate_tools() -> None:
        nonlocal turn_generation
        had_pending_tools = bool(tool_tasks or tool_bindings)
        turn_generation += 1
        for task in tool_tasks.values():
            task.cancel()
        if tool_tasks:
            await asyncio.gather(*tool_tasks.values(), return_exceptions=True)
            tool_tasks.clear()
        tool_bindings.clear()
        tool_responses.clear()
        permission_paused_tools.clear()
        if broker is not None and had_pending_tools:
            await broker.invalidate()

    def remember(message_id: str, role: str, text: str, created_at: int) -> None:
        if text:
            context_messages[message_id] = {"role": role, "text": text, "message_id": message_id,
                                            "created_at": created_at}
            # Completed text is retained until the client confirms its encrypted
            # checkpoint. Dropping older rows here would silently forget facts.
            call_context["messages"] = list(context_messages.values())
            if len(context_messages) > 128 or sum(len(row["text"]) for row in context_messages.values()) > 96_000:
                raise ContextLimitError("Pending voice checkpoint exceeds context budget")

    async def tool_event(event: dict[str, Any]) -> None:
        if event.get("type") not in {"voice_tool_status", "voice_embed", "voice_focus", "voice_memory", "voice_context"}:
            raise ValueError("Invalid voice broker event")
        binding = tool_bindings.get(event.get("function_call_id"))
        if binding is None or binding[0] != turn_generation:
            return
        if event["type"] == "voice_memory":
            permission_paused_tools.add(event["function_call_id"])
            await billing_activity(generating=bool(set(tool_tasks) - permission_paused_tools))
        if event["type"] == "voice_embed" and binding[2] == turn_assistant_id:
            payload = event.get("payload", event)
            artifact_id = payload.get("embed_id") if isinstance(payload, dict) else None
            if isinstance(artifact_id, str) and artifact_id:
                reference = payload.get("embed_reference")
                turn_assistant_artifacts[artifact_id] = reference if isinstance(reference, str) else f"Artifact: {artifact_id}"
        await send({**event, "call_id": call_id, "assistant_message_id": binding[2],
                    "user_message_id": binding[1], "created_at": binding[3]})

    async def process_tool(function_id: str, request: str, generation: int,
                           user_message_id: str, assistant_message_id: str,
                           assistant_created_at: int) -> dict[str, Any]:
        try:
            result = await broker.process_request(
                function_id, generation, request, dict(call_context), user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                assistant_created_at=assistant_created_at,
            )
        except VoiceToolOperationError as exc:
            # A failed operation must unblock Live without ending its call or
            # leaking provider errors. Authority, billing and cancellation errors
            # retain the terminal/invalidation paths above this boundary.
            logger.warning("Voice tool operation failed category=%s call_id=%s function_id=%s",
                           type(exc).__name__, call_id, function_id)
            result = {"response": {"status": "failed", "error": "tool_operation_failed",
                                   "message": "The requested operation could not be completed. Tell the user it failed; do not claim success or retry automatically."},
                      "events": []}
        return {"result": result, "generation": generation, "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id}

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
        if final:
            remember(turn_user_id, "user", turn_user_text, turn_user_created)
        await send({
            "type": "transcript", "role": "user", "call_id": call_id,
            "message_id": turn_user_id, "user_message_id": turn_user_id,
            "created_at": turn_user_created, "text": turn_user_text,
            "final": final, "interrupted": False,
        })

    async def emit_assistant(*, final: bool, interrupted: bool = False) -> None:
        if turn_assistant_id is None or (not turn_assistant_text and not turn_assistant_artifacts):
            return
        if final:
            context_text = "\n".join([turn_assistant_text, *turn_assistant_artifacts.values()]).strip()
            remember(turn_assistant_id, "assistant", context_text, turn_assistant_created)
        await send({
            "type": "transcript", "role": "assistant", "call_id": call_id,
            "message_id": turn_assistant_id, "user_message_id": turn_assistant_user_id,
            "created_at": turn_assistant_created, "text": turn_assistant_text,
            "final": final, "interrupted": interrupted,
        })

    async def assistant_turn() -> None:
        nonlocal turn_assistant_id, turn_assistant_user_id, turn_assistant_text, turn_assistant_created, last_message_order
        if turn_assistant_id is None:
            turn_assistant_id, last_message_order = _ordered_message_id(last_message_order)
            turn_assistant_user_id = turn_user_id
            turn_assistant_artifacts.clear()
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
            await billing_activity(listening=True)
        elif kind == "end_audio":
            await provider.end_audio()  # type: ignore[union-attr]
            await billing_activity(listening=False)
        else:
            await provider.send_text(value)  # type: ignore[union-attr]

    async def registry_renewal() -> None:
        while True:
            await asyncio.sleep(LOCK_RENEW_SECONDS)
            await renew_active_call(
                websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
                chat_id=chat_id, call_id=call_id,
            )

    admission_stage = "start_validation"
    try:
        start_message = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        chat_id, summary, messages, startup_audio_allowance_ms = _start(start_message)
        # One immutable call-wide ingress allowance for audio captured while the
        # provider connects. All accepted bytes still enter the credit reserve
        # and provider token accounting; mute/resume never replenishes it.
        startup_audio_allowance_bytes = startup_audio_allowance_ms * PCM_INPUT_BYTES_PER_SECOND // 1000
        admission_stage = "context_options"
        options = _context_options(json.loads(start_message)["context"])
        call_context = {"summary": summary, "messages": messages, **options}
        context_messages = {item.get("message_id", f"context-{index}"): item for index, item in enumerate(messages)}
        admission_stage = "personal_chat"
        if not await _personal_chat(websocket, chat_id, user_id):
            raise ValueError("Chat unavailable")
        admission_stage = "session"
        if not await _session_still_valid(websocket, auth_data):
            raise ValueError("Session unavailable")
        admission_stage = "credits"
        if is_payment_enabled() and await _authoritative_credits(websocket, user_id) < MIN_VOICE_HEADROOM:
            raise ValueError("Insufficient credits")
        admission_stage = "lock"
        lock_client, lock_key, lock_token = await _acquire_lock(websocket, user_hash)
        lease_task = asyncio.create_task(_renew_lock(lock_client, lock_key, lock_token))
        admission_stage = "registry"
        await register_active_call(
            websocket.app.state.cache_service, user_id=user_id, session_id=session_id,
            chat_id=chat_id, call_id=call_id,
        )
        registered = True
        registry_task = asyncio.create_task(registry_renewal())
        admission_stage = "provider_selection"
        provider = await _provider(websocket)
        if getattr(getattr(provider, "capabilities", None), "tools", False):
            admission_stage = "broker_creation"
            broker = await _broker(websocket, user_id=user_id, user_hash=user_hash,
                                   chat_id=chat_id, call_id=call_id, session_id=session_id,
                                   emit_event=tool_event)
            admission_stage = "broker_prepare"
            prepared = await broker.prepare_context(call_context)
            call_context.update(prepared)
        admission_stage = "prompt_configuration"
        configuration = await _prompt_configuration(websocket, mate_category=options.get("mate_category"), user_id=user_id)
        mate_identity = {field: configuration.pop(field) for field in ("mate_category", "mate_name") if field in configuration}
        admission_stage = "provider_open"
        await provider.open(summary=summary, messages=messages, **configuration,
                            active_focus=call_context.get("active_focus") if broker else None)
        admission_stage = "active"
        started = time.monotonic()
        await send({"type": "ready", "call_id": call_id, "model": provider.model, **mate_identity,
                    "input_sample_rate": 16000, "output_sample_rate": 24000,
                    "billing_basis": "provider_tokens"})
        await billing_activity()
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
            recent_audio_tokens = ((voiced_audio_bytes - checkpoint_audio_bytes) / 32000
                                   + (output_audio_bytes - checkpoint_output_bytes) / 48000) * 40
            if ((compression_task is not None or pending_checkpoint is not None)
                    and (recent_audio_tokens >= 10_000 or now - checkpoint_requested_at >= 90)):
                raise ContextLimitError("Voice checkpoint could not be confirmed before context expiry")
            if (broker is not None and turn_completed and not tool_tasks and compression_task is None
                    and pending_checkpoint is None and (len(context_messages) >= 24
                    or sum(math.ceil(len(row["text"].encode("utf-8")) / 3) for row in context_messages.values()) >= 4_000
                    or recent_audio_tokens >= 6_000)):
                checkpoint_requested_at = now
                compression_snapshot_id = uuid.uuid4().hex
                compression_source_versions = {identity: dict(row) for identity, row in context_messages.items()}
                await billing_activity(compressing=True)
                await send({"type": "voice_compression_started", "call_id": call_id,
                            "snapshot_id": compression_snapshot_id, "message_ids": list(compression_source_versions)})
                compression_task = asyncio.create_task(broker.compress_context(
                    {**call_context, "messages": list(context_messages.values())}, user_message_id=turn_user_id,
                ))
            if (pending_checkpoint is not None and checkpoint_confirmed and turn_completed
                    and not tool_tasks and not pause_requested):
                pause_requested = True
                await send({"type": "voice_context_pause", "call_id": call_id,
                            "checkpoint_id": pending_checkpoint["event"]["summary_message_id"]})
            if (pending_checkpoint is not None and checkpoint_confirmed and context_paused and turn_completed
                    and not tool_tasks and now - context_paused_at >= 1):
                covered = set(pending_checkpoint["event"]["covered_message_ids"])
                context_messages = {identity: row for identity, row in context_messages.items()
                                    if identity not in covered or row != compression_source_versions.get(identity)}
                call_context["summary"] = pending_checkpoint["summary"]
                call_context["messages"] = list(context_messages.values())
                # No receive may still refer to the socket being replaced.
                provider_receive.cancel()
                await asyncio.gather(provider_receive, return_exceptions=True)
                await provider.update_context(summary=call_context["summary"], messages=call_context["messages"],
                                              active_focus=call_context.get("active_focus"))
                provider_receive = asyncio.create_task(provider.receive())
                resume_handle = None
                # update_context opens a fresh session rather than resuming the
                # previous timeline; its input audio offsets restart from zero.
                last_activity_offset = -1.0
                checkpoint_audio_bytes = voiced_audio_bytes
                checkpoint_output_bytes = output_audio_bytes
                await send({"type": "voice_context_resumed", "call_id": call_id,
                            "checkpoint_id": pending_checkpoint["event"]["summary_message_id"]})
                pending_checkpoint = None
                compression_source_versions.clear()
                checkpoint_confirmed = context_paused = pause_requested = False
            done, _ = await asyncio.wait(
                {client_receive, provider_receive, lease_task, registry_task, *tool_tasks.values(),
                 *([compression_task] if compression_task is not None else [])},
                timeout=1, return_when=asyncio.FIRST_COMPLETED,
            )
            if client_receive in done:
                incoming = json.loads(client_receive.result())
                if not isinstance(incoming, dict):
                    raise ValueError("Invalid call event")
                kind = incoming.get("type")
                if kind == "hangup":
                    await invalidate_tools()
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
                    if audio_activity_active:
                        voiced_audio_bytes += len(chunk)
                    if audio_bytes > ((now - started + AUDIO_JITTER_SECONDS) * PCM_INPUT_BYTES_PER_SECOND
                                      + startup_audio_allowance_bytes):
                        raise ValueError("Audio stream exceeds real-time rate")
                    if is_payment_enabled():
                        pending = max(0, _credits_for(ledger.gemini_cost) - ledger.charged)
                        reserve = _unsettled_audio_credits(audio_bytes, settled_audio_bytes)
                        if await _authoritative_credits(websocket, user_id) < MIN_VOICE_HEADROOM + pending + reserve:
                            raise RuntimeError("Insufficient credits")
                    if turn_user_id is None:
                        await user_turn()
                    await send_provider("audio", encoded)
                elif kind == "audio_stream_end":
                    await send_provider("end_audio", "")
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
                    await invalidate_tools()
                    await user_turn(message_id, created)
                    turn_user_text = content
                    turn_user_authoritative = True
                    await send_provider("text", content)
                    await billing_activity(generating=True)
                    seen_text_ids[message_id] = (content, created)
                    await emit_user(final=True)
                elif kind == "voice_memory_response":
                    if broker is None or incoming.get("call_id") != call_id:
                        raise ValueError("Invalid voice memory response")
                    if (not isinstance(incoming.get("request_id"), str)
                            or not isinstance(incoming.get("function_call_id"), str)
                            or not isinstance(incoming.get("approved"), bool)
                            or not isinstance(incoming.get("settings_memories", []), list)
                            or len(json.dumps(incoming)) > MAX_START_BYTES):
                        raise ValueError("Invalid voice memory response")
                    if incoming["function_call_id"] not in tool_bindings:
                        # A user may answer an approval card after barging in.
                        # The cancelled generation grants no memory authority.
                        client_receive = asyncio.create_task(websocket.receive_text())
                        continue
                    await broker.respond_memory(incoming["request_id"], incoming["approved"],
                                                incoming.get("settings_memories", []),
                                                incoming["function_call_id"])
                    permission_paused_tools.discard(incoming["function_call_id"])
                    await billing_activity(generating=True)
                elif kind in {"voice_compression_confirmed", "voice_context_paused"}:
                    if incoming.get("call_id") != call_id:
                        raise ValueError("Invalid voice checkpoint acknowledgement")
                    if pending_checkpoint is not None and incoming.get("checkpoint_id") == pending_checkpoint["event"]["summary_message_id"]:
                        if kind == "voice_compression_confirmed":
                            checkpoint_confirmed = True
                        elif pause_requested:
                            context_paused = True
                            context_paused_at = time.monotonic()
                            await provider.end_audio()
                            await billing_activity(listening=False)
                else:
                    raise ValueError("Unknown call event")
                client_receive = asyncio.create_task(websocket.receive_text())
            if provider_receive in done:
                event = provider_receive.result()
                cancellation = event.get("toolCallCancellation")
                if isinstance(cancellation, dict):
                    ids = cancellation.get("ids", [])
                    if not isinstance(ids, list):
                        raise ValueError("Invalid provider tool cancellation")
                    for function_id in ids:
                        if isinstance(function_id, str):
                            tool_responses.pop(function_id, None)
                    # The broker invalidates its current pending permission/
                    # execution generation together, so invalidate local siblings
                    # too. Gemini cancels affected IDs; no response is sent.
                    if any(isinstance(function_id, str) and function_id in tool_bindings for function_id in ids):
                        await invalidate_tools()
                        await billing_activity(generating=False)
                activity = event.get("voiceActivity")
                if isinstance(activity, dict) and activity.get("type") == "ACTIVITY_END":
                    audio_activity_active = False
                    last_finalized_audio_bytes = audio_bytes
                if isinstance(activity, dict) and activity.get("type") == "ACTIVITY_START":
                    offset = _audio_offset(activity.get("audioOffset"))
                    if offset is None or offset > last_activity_offset:
                        audio_activity_active = True
                        await billing_activity(generating=True)
                        await invalidate_tools()
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
                            await billing_activity(listening=True)
                        elif queued_kind == "end_audio":
                            await provider.end_audio()
                            await billing_activity(listening=False)
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
                        await invalidate_tools()
                        await billing_activity(generating=False)
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
                            remember(late_id, "user", _bounded_transcript(input_text), late_created)
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
                    if content.get("modelTurn"):
                        await billing_activity(generating=True)
                    output_text = output_transcription.get("text") if isinstance(output_transcription, dict) else None
                    if isinstance(output_text, str) and output_text:
                        await assistant_turn()
                        turn_assistant_text = _output_transcription(turn_assistant_segments, output_transcription)
                        await emit_assistant(final=False)
                    for part in (content.get("modelTurn") or {}).get("parts") or []:
                        inline = part.get("inlineData") if isinstance(part, dict) else None
                        if isinstance(inline, dict) and str(inline.get("mimeType") or "").startswith("audio/") and isinstance(inline.get("data"), str):
                            output_audio_bytes += len(inline["data"]) * 3 // 4
                            await assistant_turn()
                            await send({"type": "audio_chunk", "data": inline["data"]})
                    if content.get("turnComplete"):
                        waiting_for_tool = bool(tool_tasks) or bool((event.get("toolCall") or {}).get("functionCalls"))
                        turn_completed = not waiting_for_tool
                        await billing_activity(generating=bool(set(tool_tasks) - permission_paused_tools)
                                               or bool((event.get("toolCall") or {}).get("functionCalls")))
                        if turn_user_authoritative:
                            await emit_user(final=True)
                        await emit_assistant(final=not waiting_for_tool)
                        if not waiting_for_tool:
                            turn_assistant_id = None
                            turn_assistant_text = ""
                            turn_assistant_segments.clear()
                        if ledger.commit_gemini_turn():
                            await _charge_voice(websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id, chat_id=chat_id)
                            settled_audio_bytes = max(settled_audio_bytes, last_finalized_audio_bytes)
                            await send({"type": "usage", "billing_basis": "provider_tokens", **{key: value for key, value in ledger.view(now - started).items() if key not in ("video_credits", "h3_generated_seconds", "h3_estimated_seconds", "video_credits_per_minute", "audio_credits_per_minute")}})
                    elif content.get("generationComplete"):
                        await billing_activity(generating=bool(set(tool_tasks) - permission_paused_tools))
                tool_call = event.get("toolCall")
                if isinstance(tool_call, dict):
                    calls = tool_call.get("functionCalls", [])
                    if not isinstance(calls, list) or len(calls) > 8:
                        raise ValueError("Invalid provider tool call")
                    for function in calls:
                        if not isinstance(function, dict):
                            raise ValueError("Invalid provider tool call")
                        function_id = function.get("id")
                        args = function.get("args")
                        if (not isinstance(function_id, str) or not 0 < len(function_id) <= 256
                                or function.get("name") != "process_request" or not isinstance(args, dict)
                                or set(args) != {"request"} or not isinstance(args.get("request"), str)
                                or not args["request"].strip() or len(args["request"]) > MAX_TEXT_CHARS):
                            raise ValueError("Invalid provider tool call")
                        if function_id in seen_tool_ids:
                            if function_id in tool_responses:
                                await provider.send_tool_response(function_id, tool_responses[function_id])
                            continue  # Replayed provider calls must never repeat paid side effects.
                        if broker is None or len(seen_tool_ids) >= 256:
                            raise RuntimeError("Voice tool broker unavailable")
                        if turn_user_id is None:
                            await user_turn()
                        await assistant_turn()
                        seen_tool_ids.add(function_id)
                        tool_bindings[function_id] = (turn_generation, turn_user_id, turn_assistant_id, turn_assistant_created)
                        tool_tasks[function_id] = asyncio.create_task(process_tool(
                            function_id, args["request"], turn_generation, turn_user_id, turn_assistant_id,
                            turn_assistant_created,
                        ))
                        await billing_activity(generating=True)
                provider_receive = asyncio.create_task(provider.receive())
            for function_id, task in list(tool_tasks.items()):
                if task not in done:
                    continue
                tool_tasks.pop(function_id)
                permission_paused_tools.discard(function_id)
                completed = task.result()
                if completed["generation"] != turn_generation:
                    continue
                result = completed["result"]
                for event in result.get("events", []):
                    await tool_event({**event, "function_call_id": function_id})
                tool_responses[function_id] = result["response"]
                if "active_focus" in result["response"]:
                    call_context["active_focus"] = result["response"]["active_focus"]
                await provider.send_tool_response(function_id, result["response"])
                await billing_activity(generating=True)
                tool_bindings.pop(function_id, None)
            if compression_task is not None and compression_task in done:
                completed_compression = compression_task
                compression_task = None
                try:
                    compressed = completed_compression.result()
                finally:
                    # Canonical ciphertext/ACK waiting is idle; only the actual
                    # compression operation contributes processing activity.
                    await billing_activity(compressing=False)
                if not compressed.get("was_compressed"):
                    raise ContextLimitError("Voice context checkpoint could not be refreshed")
                if not isinstance(compressed.get("summary"), str) or len(compressed["summary"]) > MAX_SUMMARY_CHARS:
                    raise ContextLimitError("Voice context checkpoint exceeds protected budget")
                pending_checkpoint = compressed
                compressed["event"]["voice_snapshot_id"] = compression_snapshot_id
                checkpoint_confirmed = context_paused = pause_requested = False
                await send({"type": "voice_compression", "call_id": call_id, "payload": compressed["event"]})
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Exception messages and tracebacks can contain provider text or media.
        logger.warning("Voice call ended with %s stage=%s call_id=%s", type(exc).__name__, admission_stage, call_id)
        try:
            if isinstance(exc, ContextLimitError):
                await send({"type": "error", "code": "context_too_large", "message": "This chat's context is too large for a call. You can continue by text."})
            elif isinstance(exc, TranscriptLimitError):
                await send({"type": "error", "code": "transcript_limit", "message": "The transcript exceeded the call limit. Your call has ended."})
            else:
                await send({"type": "error", "code": "call_unavailable", "stage": admission_stage, "message": "Call unavailable. Your call has ended."})
        except Exception:
            pass
    finally:
        was_cancelled = False
        if registered:
            try:
                await billing_activity(listening=False, generating=False, compressing=False)
            except Exception:
                pass  # Disconnected clients cannot receive terminal activity.
        tasks = [task for task in (client_receive, provider_receive, lease_task, registry_task, compression_task, *tool_tasks.values()) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if provider is not None:
            try:
                await provider.close()
            except Exception:
                logger.warning("Voice provider close failed call_id=%s", call_id)
        if broker is not None:
            try:
                await broker.close()
            except Exception:
                logger.warning("Voice broker close failed call_id=%s", call_id)
        try:
            ledger.commit_gemini_turn()
            if lock_client is not None:
                # An accepted provider turn can remain billable after browser
                # cancellation. Keep its settlement inside the call lease.
                charge_task = asyncio.create_task(_charge_voice(
                    websocket, ledger, user_id=user_id, user_hash=user_hash, call_id=call_id, chat_id=chat_id,
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
