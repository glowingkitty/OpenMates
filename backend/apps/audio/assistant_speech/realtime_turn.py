"""One transient, incremental speech owner for a canonical assistant turn.

Only released immutable prose enters its bounded in-memory queue. Dependencies
are injected; provider work, safety and delivery never run on the text-yield path.
No text mailbox, generated audio file or asset is created by this module.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Any
from uuid import uuid4

MAX_TURN_CHARACTERS = 10_000
MAX_TURN_AUDIO_BYTES = 16 * 1024 * 1024
MAX_TURN_SECONDS = 600
MAX_PENDING_SPANS = 64
AUTHORITY_INTERVAL_SECONDS = 0.5
PUBLISH_TIMEOUT_SECONDS = 1.0
AUDIO_CHUNK_BYTES = 32 * 1024
SAFE_ERROR = "Speech is temporarily unavailable."
logger = logging.getLogger(__name__)

# Diagnostic values are fixed categories, never exception bodies or provider text.
_PROVIDER_FAILURE_CODES = frozenset({
    "audio_limit", "cancelled", "concurrent_receive", "credentials_unavailable",
    "handshake_failed", "input_limit", "invalid_alignment", "invalid_audio",
    "invalid_configuration", "invalid_event", "invalid_input", "invalid_state",
    "keepalive_failed", "provider_error", "receive_timeout", "send_failed",
    "session_timeout", "transport_failed", "truncated_stream", "unexpected_final",
})
_SPEECH_FAILURE_CODES = {
    "Speech safeguard denied": "safeguard_denied",
    "Speech audio bound exceeded": "audio_limit",
    "Speech provider did not complete": "incomplete_stream",
    "Speech delivery unavailable": "publication_failed",
    "Speech track lease unavailable": "lease_unavailable",
    "Speech track lease renewal unavailable": "lease_renewal_failed",
}


def _failure_diagnostic(error: BaseException) -> tuple[str, str]:
    """Allowlist classifications; even an unexpected provider code stays private."""
    if isinstance(error, asyncio.CancelledError):
        return "cancelled", "none"
    if isinstance(error, TimeoutError):
        return "timeout", "none"
    provider_code = getattr(error, "code", None)
    if isinstance(provider_code, str):
        return "provider", provider_code if provider_code in _PROVIDER_FAILURE_CODES else "unknown"
    if isinstance(error, RealtimeTurnUnavailable):
        return "speech", _SPEECH_FAILURE_CODES.get(str(error), "unavailable")
    if isinstance(error, PermissionError):
        return "authority", "denied"
    return "unexpected", "none"


class RealtimeTurnUnavailable(RuntimeError):
    """A content-free terminal delivery failure; paid input is never retried."""


class RealtimeSpeechTurn:
    """A single writer and reader share exactly one provider WebSocket.

    ``enqueue`` performs bounded handoff only. ``finish_input`` schedules EOS;
    ``wait`` belongs after canonical persistence/final output, never before it.
    Missing provider alignment deliberately produces no claimed heard positions.
    """

    def __init__(self, *, context: Mapping[str, object], provider_factory: Callable[[], Any],
                 prepare: Callable[[], Awaitable[int]], ensure_active: Callable[[], Awaitable[None]],
                 safety_check: Callable[[str], Awaitable[bool]],
                 credit_check: Callable[[int], Awaitable[None]],
                 publish_event: Callable[[str, dict[str, object]], Awaitable[object]],
                 finalize: Callable[[bool, int], Awaitable[None]],
                 max_seconds: float = MAX_TURN_SECONDS,
                 on_first_audio: Callable[[], Awaitable[None]] | None = None) -> None:
        self.context = dict(context)
        self.track_id = str(context["segment_id"])
        self._provider_factory, self._prepare = provider_factory, prepare
        self._ensure_active, self._safety_check, self._credit_check = ensure_active, safety_check, credit_check
        self._publish, self._finalize = publish_event, finalize
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(MAX_PENDING_SPANS + 1)
        self._prepare_task: asyncio.Task[int] | None = None
        self._task: asyncio.Task[None] | None = None
        self._provider: Any = None
        self._input_finished = False
        self._closed = False
        self._queued_characters = 0
        self._seen: set[str] = set()
        self._chunk_index = self._audio_bytes = 0
        self._audio_started = False
        self._attempt_id = str(uuid4())
        self._max_seconds = max_seconds
        self._started = monotonic()
        self._execution_version = 1
        self.failed = False
        self.is_mock = False
        self._on_first_audio = on_first_audio
        self._finalized = False
        self._cancelled_for_timeout = False

    async def prepare(self) -> None:
        """Publish/claim track metadata before any semantic status or paid work."""
        if self._prepare_task is None:
            self._prepare_task = asyncio.create_task(self._prepare())
        self._execution_version = await self._prepare_task

    async def enqueue(self, segment: Mapping[str, object]) -> None:
        """Hand off one already projected span; repeated immutable IDs are no-ops."""
        if self._closed or self._input_finished:
            raise RealtimeTurnUnavailable("Speech turn is closed")
        await self.prepare()
        identity = str(segment["segment_id"])
        if identity in self._seen:
            return
        text = str(segment["speakable_text"])
        # Preserve exact submitted characters; the space separates independently
        # projected clauses and is included in credit accounting.
        submitted = text + " "
        if (not text or len(self._seen) >= 1024
                or self._queued_characters + len(submitted) > MAX_TURN_CHARACTERS
                or self._queue.qsize() >= MAX_PENDING_SPANS):
            await self.cancel()
            raise RealtimeTurnUnavailable("Speech input bound exceeded")
        self._seen.add(identity)
        self._queued_characters += len(submitted)
        self._queue.put_nowait(submitted)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def finish_input(self) -> None:
        """Append EOS after all handoffs without waiting for audio drain."""
        if self._input_finished or self._closed:
            return
        self._input_finished = True
        # One extra reserved queue slot guarantees EOS never waits on paid work.
        self._queue.put_nowait(None)

    async def _emit(self, phase: str, audio: bytes | None = None) -> None:
        payload = {**self.context, "execution_version": self._execution_version,
                   "attempt_id": self._attempt_id, "phase": phase,
                   "chunk_index": self._chunk_index, "mime_type": "audio/mpeg"}
        owner = payload.pop("user_id_hash")
        if audio is not None:
            payload["audio_data"] = base64.b64encode(audio).decode("ascii")
        envelope = {"type": "assistant_speech_audio", "chat_id": payload["chat_id"],
                    "message_id": payload["message_id"], "user_id_hash": owner, "payload": payload}
        try:
            result = await asyncio.wait_for(
                self._publish(f"chat_stream::{payload['chat_id']}", envelope), PUBLISH_TIMEOUT_SECONDS,
            )
            if result is False:
                raise RealtimeTurnUnavailable("Speech delivery unavailable")
        except asyncio.CancelledError:
            raise
        except Exception:
            raise RealtimeTurnUnavailable("Speech delivery unavailable") from None

    async def _write(self) -> None:
        count = 0
        while True:
            text = await self._queue.get()
            if text is None:
                await self._ensure_active()
                await self._provider.finish_input()
                return
            await self._ensure_active()
            if not await self._safety_check(text):
                raise RealtimeTurnUnavailable("Speech safeguard denied")
            await self._credit_check(count + len(text))
            await self._ensure_active()
            await self._provider.append_text(text)
            count += len(text)
            await self._provider.flush()

    async def _read(self) -> None:
        completed = False
        async for event in self._provider.audio_events():
            await self._ensure_active()
            if event.audio_bytes:
                audio = event.audio_bytes
                if not isinstance(audio, bytes) or self._audio_bytes + len(audio) > MAX_TURN_AUDIO_BYTES:
                    raise RealtimeTurnUnavailable("Speech audio bound exceeded")
                if not self._audio_started:
                    if self._on_first_audio is not None:
                        await self._on_first_audio()
                    await self._ensure_active()
                    await self._emit("start")
                    self._audio_started = True
                self._audio_bytes += len(audio)
                for offset in range(0, len(audio), AUDIO_CHUNK_BYTES):
                    await self._emit("chunk", audio[offset:offset + AUDIO_CHUNK_BYTES])
                    self._chunk_index += 1
            # Alignment timebase is provider-unspecified until independently
            # proved. Never guess positions from its text or chunk boundaries.
            if event.final:
                completed = True
                break
        if not completed or not self._input_finished or not self._audio_bytes:
            raise RealtimeTurnUnavailable("Speech provider did not complete")
        await self._ensure_active()
        await self._emit("end")

    async def _watch_authority(self) -> None:
        while True:
            await self._ensure_active()
            await asyncio.sleep(AUTHORITY_INTERVAL_SECONDS)

    async def _run(self) -> None:
        success = False
        children: list[asyncio.Task[Any]] = []
        stage = "authority"
        try:
            async with asyncio.timeout(self._max_seconds):
                await self._ensure_active()
                stage = "provider_setup"
                self._provider = self._provider_factory()
                authority = asyncio.create_task(self._watch_authority())
                opening = asyncio.create_task(self._provider.open())
                children = [opening, authority]
                stage = "opening"
                done, _ = await asyncio.wait(children, return_when=asyncio.FIRST_COMPLETED)
                for child in done:
                    stage = "authority" if child is authority else "opening"
                    child.result()
                await opening
                writer = asyncio.create_task(self._write())
                reader = asyncio.create_task(self._read())
                children.extend([writer, reader])
                # Authority is intentionally infinite. Any child failure stops
                # paid work immediately; successful writer waits for the reader.
                pending = {writer, reader, authority}
                stages = {writer: "writing", reader: "reading", authority: "authority"}
                while reader in pending or writer in pending:
                    stage = "streaming"
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for child in done:
                        stage = stages[child]
                        child.result()
                success = True
        except (Exception, asyncio.CancelledError) as error:
            self.failed = True
            cause, code = _failure_diagnostic(error)
            if cause == "cancelled" and self._cancelled_for_timeout:
                cause = "timeout"
            # Track identity is a server-issued hash; no chat/user text, settings,
            # URLs, raw provider event shape or exception messages enter logs.
            track = self.track_id if len(self.track_id) == 64 and all(
                char in "0123456789abcdef" for char in self.track_id) else "unavailable"
            logger.log(logging.INFO if cause == "cancelled" else logging.WARNING,
                       "Realtime speech terminated track=%s stage=%s cause=%s code=%s "
                       "audio_started=%s chunks=%d input_finished=%s",
                       track, stage, cause, code, self._audio_started,
                       self._chunk_index, self._input_finished)
            try:
                await self._emit("error")
            except RealtimeTurnUnavailable:
                pass
        finally:
            self._closed = True
            for child in children:
                child.cancel()
            if children:
                await asyncio.gather(*children, return_exceptions=True)
            if self._provider is not None:
                try:
                    await self._provider.cancel()
                except Exception:
                    logger.warning("Realtime speech transport cleanup failed")
            while not self._queue.empty():
                self._queue.get_nowait()
            try:
                submitted = int(self._provider.submitted_characters) if success and self._provider else 0
                self._finalized = True
                await self._finalize(success, submitted)
            except Exception:
                # Safe metadata only; durable ready rows retain billing-sweep
                # recovery if the billing queue handoff alone failed.
                self.failed = True
                logger.warning("Realtime speech completion metadata unavailable")

    async def cancel(self, *, timed_out: bool = False) -> None:
        """Stop the provider without draining or granting completion/heard state."""
        self._closed = True
        self._cancelled_for_timeout = self._cancelled_for_timeout or timed_out
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        elif self._prepare_task is not None and self._prepare_task.done() and not self._finalized:
            # Registration may succeed before a later semantic handoff fails.
            # Release the durable claim even though no provider was opened.
            try:
                self._prepare_task.result()
                self._finalized = True
                await self._finalize(False, 0)
            except Exception:
                logger.warning("Realtime speech unstarted claim cleanup unavailable")

    async def wait(self) -> None:
        """Keep the request loop alive only after canonical final work finished."""
        if self._task is not None:
            remaining = max(0.01, self._max_seconds - (monotonic() - self._started))
            try:
                await asyncio.wait_for(asyncio.shield(self._task), remaining)
            except TimeoutError:
                await self.cancel(timed_out=True)
            except asyncio.CancelledError:
                await self.cancel()
                raise


def create_realtime_speech_turn(*, metadata: Mapping[str, object], user_id: str,
                                voice_profile: Mapping[str, object], directus: Any,
                                cache: Any, secrets_manager: Any,
                                live_mock_context: Mapping[str, object] | None = None,
                                on_first_audio: Callable[[], Awaitable[None]] | None = None) -> RealtimeSpeechTurn:
    """Bind the in-request owner to the existing audio authority and ledger."""
    from datetime import datetime, timedelta, timezone
    from backend.apps.audio.assistant_speech.persistence import (
        LEASE_TTL_SECONDS, claim_speech_segment_execution, create_manifest_and_segments,
        finalize_speech_segment_execution, get_speech_segment,
    )
    from backend.apps.audio.assistant_speech.voice_profiles import resolve_assistant_voice_profile
    from backend.apps.audio.pricing import calculate_assistant_response_speech_credits, estimate_speech_duration_seconds
    from backend.shared.python_utils.voice_call_admission import require_active_voice_dispatch

    from backend.apps.audio.assistant_speech.live_mock import assistant_speech_live_mock_audio
    mock_audio = assistant_speech_live_mock_audio(dict(live_mock_context or {}))
    profile = resolve_assistant_voice_profile(str(voice_profile["key"]), version=int(voice_profile["version"]))
    if profile.version != 3 or profile.provider != "elevenlabs":
        raise ValueError("Realtime call profile unavailable")
    identity = f"{metadata['voice_call_id']}:{metadata['assistant_message_id']}:{metadata['source_version']}:{profile.key}:v3:turn-track"
    track_id = hashlib.sha256(identity.encode()).hexdigest()
    lease_id = uuid4().hex
    claim: dict[str, Any] = {}
    last_renewed = monotonic()
    context = {
        "chat_id": str(metadata["chat_id"]), "message_id": str(metadata["assistant_message_id"]),
        "voice_call_id": str(metadata["voice_call_id"]), "source_version": int(metadata["source_version"]),
        "segment_id": track_id, "sequence": 0, "kind": "voice_prose_turn",
        "user_id_hash": hashlib.sha256(user_id.encode()).hexdigest(),
    }

    async def status(state: str, *, error: bool = False) -> None:
        result = await cache.publish_event(f"chat_stream::{context['chat_id']}", {
            "type": "assistant_speech_status", "chat_id": context["chat_id"],
            "message_id": context["message_id"], "user_id_hash": context["user_id_hash"],
            "payload": {**{key: value for key, value in context.items() if key != "user_id_hash"},
                        "execution_version": int(claim.get("execution_version") or 1), "status": state,
                        **({"error": SAFE_ERROR, "retryable": False} if error else {})},
        })
        if result is False:
            raise RealtimeTurnUnavailable("Speech status delivery unavailable")

    async def active_call() -> None:
        await require_active_voice_dispatch(cache, {
            "voice_mode": True, "user_id": user_id, "chat_id": metadata["chat_id"],
            "message_id": metadata["voice_turn_id"], "voice_turn_id": metadata["voice_turn_id"],
            "voice_call_id": metadata["voice_call_id"],
        })

    async def prepare() -> int:
        await active_call()
        if await get_speech_segment(directus, track_id) is not None:
            # A prior delivery/continuation is not permission for an automatic
            # paid replay, including after a failed or cancelled provider call.
            raise RealtimeTurnUnavailable("Speech track already attempted")
        await create_manifest_and_segments(
            directus, user_id=user_id, chat_id=str(context["chat_id"]),
            assistant_message_id=str(context["message_id"]), source_version=int(context["source_version"]),
            voice_profile=voice_profile, voice_call_id=str(context["voice_call_id"]),
            segments=[{"segment_id": track_id, "sequence": 0, "kind": "voice_prose_turn",
                       "source_hash": hashlib.sha256(identity.encode()).hexdigest()}],
        )
        acquired = await claim_speech_segment_execution(directus, track_id, lease_id=lease_id)
        if acquired is None:
            raise RealtimeTurnUnavailable("Speech track already owned")
        claim.update(acquired)
        await status("queued")
        return int(claim["execution_version"])

    async def ensure_active() -> None:
        nonlocal last_renewed
        await active_call()
        current = await get_speech_segment(directus, track_id)
        if (not current or current.get("status") != "generating" or current.get("lease_id") != lease_id
                or current.get("execution_version") != claim.get("execution_version")):
            raise RealtimeTurnUnavailable("Speech track lease unavailable")
        if monotonic() - last_renewed > 30:
            updated = await directus.update_item_if_version(
                "assistant_speech_segments", str(current.get("id") or track_id),
                {"lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=LEASE_TTL_SECONDS)).isoformat()},
                int(claim["execution_version"]), version_field="execution_version",
                extra_filters={"lease_id": lease_id, "status": "generating"},
            )
            if not updated:
                raise RealtimeTurnUnavailable("Speech track lease renewal unavailable")
            last_renewed = monotonic()

    async def safety(text: str) -> bool:
        if mock_audio is not None:
            return True
        from backend.apps.audio.skills.speak_skill import classify_audio_speech_safety
        decision = await classify_audio_speech_safety(
            text=text, voice=profile.key, accent="en_us", style="natural",
            secrets_manager=secrets_manager, trusted_narration=True,
        )
        return bool(decision.approved)

    async def credits(characters: int) -> None:
        if mock_audio is not None:
            return
        from backend.apps.audio.tasks.common import ensure_audio_credit_headroom
        await ensure_audio_credit_headroom(
            user_id=user_id,
            estimated_credits=calculate_assistant_response_speech_credits(submitted_characters=characters, model=profile.model),
            operation_name="assistant response speech", log_prefix="[assistant-speech turn]",
        )

    def provider_factory() -> Any:
        if mock_audio is not None:
            return _ReplayTurnSession(mock_audio)
        from backend.shared.providers.elevenlabs.realtime import ElevenLabsRealtimeSession
        request = profile.elevenlabs_request()
        return ElevenLabsRealtimeSession(
            voice_id=str(request["voice_id"]), secrets_manager=secrets_manager,
            max_session_seconds=MAX_TURN_SECONDS, max_input_characters=MAX_TURN_CHARACTERS,
            max_audio_bytes=MAX_TURN_AUDIO_BYTES,
        )

    async def finalize(success: bool, characters: int) -> None:
        from backend.core.api.app.tasks.celery_config import app
        finalized = await finalize_speech_segment_execution(
            directus, track_id,
            {"status": "ready" if success else "error", "kind": "voice_prose_turn",
             **({"billable_character_count": characters,
                 "duration_seconds": estimate_speech_duration_seconds(" " * characters)} if success else
                {"error": SAFE_ERROR, "retryable": False})},
            lease_id=lease_id, execution_version=int(claim["execution_version"]), completed_live=success,
        )
        if finalized and success and mock_audio is None:
            # Existing durable metadata and idempotent billing sweep recover a
            # queue-send failure; no audio or source text enters the ledger.
            app.send_task("apps.audio.tasks.assistant_speech_billing",
                          kwargs={"arguments": {"manifest_id": str(claim["manifest_id"])}}, queue="app_music")
        # Publication needs current authority; successful accounting may still
        # settle when hangup won this race, without sending stale ready events.
        try:
            await active_call()
            await status("ready" if success and finalized else "error", error=not (success and finalized))
        except (ValueError, RuntimeError):
            pass

    owner = RealtimeSpeechTurn(
        context=context, provider_factory=provider_factory, prepare=prepare, ensure_active=ensure_active,
        safety_check=safety, credit_check=credits, publish_event=cache.publish_event, finalize=finalize,
        on_first_audio=on_first_audio,
    )
    owner.is_mock = mock_audio is not None
    return owner


class ElevenRealtimeFiniteClient:
    """Use v4 for the existing finite waiting prelude, with no saved audio."""

    def __init__(self, *, secrets_manager: Any) -> None:
        self._secrets_manager = secrets_manager

    async def stream_text_to_speech(self, *, text: str, voice_id: str, model: str):
        from backend.shared.providers.elevenlabs.realtime import ElevenLabsRealtimeSession
        provider = ElevenLabsRealtimeSession(voice_id=voice_id, secrets_manager=self._secrets_manager,
                                            max_input_characters=MAX_TURN_CHARACTERS,
                                            max_audio_bytes=4 * 1024 * 1024)
        try:
            await provider.open()
            await provider.append_text(text)
            await provider.flush()
            await provider.finish_input()
            complete = False
            async for event in provider.audio_events():
                if event.audio_bytes:
                    yield event.audio_bytes
                if event.final:
                    complete = True
                    break
            if not complete:
                raise RealtimeTurnUnavailable("Speech provider did not complete")
        finally:
            await provider.cancel()


class _ReplayTurnSession:
    """Exact authorized CI binary replay through the continuous-turn owner."""

    def __init__(self, audio_path: Any) -> None:
        from backend.apps.audio.assistant_speech.live_mock import AssistantSpeechReplayStreamClient
        self._client = AssistantSpeechReplayStreamClient(audio_path)
        self._first_input = asyncio.Event()
        self._finished = asyncio.Event()
        self.submitted_characters = 0

    async def open(self) -> None:
        return None

    async def append_text(self, text: str) -> None:
        self.submitted_characters += len(text)
        self._first_input.set()

    async def flush(self) -> None:
        return None

    async def finish_input(self) -> None:
        self._finished.set()

    async def cancel(self) -> None:
        self._finished.set()

    async def audio_events(self):
        from types import SimpleNamespace
        await self._first_input.wait()
        async for audio in self._client.stream_text_to_speech():
            yield SimpleNamespace(audio_bytes=audio, alignment=None, final=False)
        await self._finished.wait()
        yield SimpleNamespace(audio_bytes=b"", alignment=None, final=True)
