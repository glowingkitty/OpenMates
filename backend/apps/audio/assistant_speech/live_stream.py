"""Deliver one validated speech synthesis as transient live audio only.

No storage, billing or retries live here. Callers must retain their existing
safeguard, credit and call authority checks before invoking this helper.
"""
from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from backend.shared.providers.mistral_speech import (
    MISTRAL_SPEECH_MODEL,
    MistralSpeechClient,
)
from backend.shared.python_utils.assistant_speech_audio import (
    MAX_AUDIO_CHUNK_BYTES,
    MAX_AUDIO_CHUNKS,
    validate_assistant_speech_audio_event,
)

MAX_LIVE_AUDIO_BYTES = 4 * 1024 * 1024
ACTIVE_CHECK_INTERVAL_SECONDS = 0.5
PUBLISH_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class LiveSpeechCompletion:
    """Content-free accounting after a provider-complete live delivery."""

    submitted_characters: int
    generated_audio_bytes: int
    chunk_count: int


class LiveSpeechDeliveryUnavailable(RuntimeError):
    """A live consumer is unavailable; the paid stream must stop immediately."""

    def __init__(self) -> None:
        super().__init__("Live speech delivery unavailable")


async def generate_live_speech(
    *, client: MistralSpeechClient, text: str, voice_id: str,
    context: Mapping[str, object],
    publish_event: Callable[[str, dict[str, object]], Awaitable[object]],
    ensure_active: Callable[[], Awaitable[None]],
    model: str = MISTRAL_SPEECH_MODEL,
) -> LiveSpeechCompletion:
    """Deliver ordered live chunks without accumulating or storing audio.

    Context contains chat_id, message_id, user_id_hash, voice_call_id, segment_id,
    sequence, kind, source_version and execution_version. A new public attempt
    UUID never derives from the private execution lease. Failed publication,
    provider/lease error or cancellation releases HTTP without retry. Return
    accounting only after provider completion and a published end event.
    """
    metadata = {field: context[field] for field in (
        "chat_id", "message_id", "voice_call_id", "segment_id", "sequence",
        "source_version", "execution_version", "kind",
    )}
    metadata.update(attempt_id=str(uuid4()), mime_type="audio/mpeg")
    channel = f"chat_stream::{metadata['chat_id']}"
    chunk_index = 0

    def envelope(phase: str, audio: bytes | None = None) -> dict[str, object]:
        payload = {**metadata, "phase": phase, "chunk_index": chunk_index}
        if audio is not None:
            payload["audio_data"] = base64.b64encode(audio).decode("ascii")
        return {
            "type": "assistant_speech_audio", "chat_id": metadata["chat_id"],
            "message_id": metadata["message_id"], "user_id_hash": context["user_id_hash"],
            "payload": payload,
        }

    # Validate all identities and versions before any publication or paid work.
    validate_assistant_speech_audio_event(envelope("start"), channel=channel)

    async def emit(phase: str, audio: bytes | None = None) -> None:
        try:
            result = await asyncio.wait_for(publish_event(channel, envelope(phase, audio)), PUBLISH_TIMEOUT_SECONDS)
            if result is False:
                raise LiveSpeechDeliveryUnavailable
        except Exception:
            # Never log or retain a transport exception's private Redis payload.
            raise LiveSpeechDeliveryUnavailable from None

    audio_byte_count = 0
    try:
        await ensure_active()
        last_active_check = monotonic()
        await emit("start")
        async with aclosing(client.stream_text_to_speech(text=text, voice_id=voice_id, model=model)) as stream:
            pending: asyncio.Task[bytes] | None = None
            try:
                while True:
                    exhausted = False
                    pending = asyncio.create_task(anext(stream))
                    while True:
                        done, _ = await asyncio.wait({pending}, timeout=ACTIVE_CHECK_INTERVAL_SECONDS)
                        if done:
                            result_task, pending = pending, None
                            try:
                                audio = result_task.result()
                            except StopAsyncIteration:
                                exhausted = True
                                break
                            if monotonic() - last_active_check >= ACTIVE_CHECK_INTERVAL_SECONDS:
                                await ensure_active()
                                last_active_check = monotonic()
                            if not isinstance(audio, bytes) or not audio:
                                raise RuntimeError("Invalid live speech audio")
                            if audio_byte_count + len(audio) > MAX_LIVE_AUDIO_BYTES:
                                raise RuntimeError("Live speech audio limit exceeded")
                            required_chunks = (len(audio) + MAX_AUDIO_CHUNK_BYTES - 1) // MAX_AUDIO_CHUNK_BYTES
                            if chunk_index + required_chunks > MAX_AUDIO_CHUNKS:
                                raise RuntimeError("Live speech chunk limit exceeded")
                            audio_byte_count += len(audio)
                            for offset in range(0, len(audio), MAX_AUDIO_CHUNK_BYTES):
                                await emit("chunk", audio[offset:offset + MAX_AUDIO_CHUNK_BYTES])
                                chunk_index += 1
                            break
                        await ensure_active()
                        last_active_check = monotonic()
                    if exhausted:
                        break
            finally:
                # aclose cannot run while anext is active. Cancel and await the
                # pending read first, including when a stalled call loses its lease.
                if pending is not None:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
        if not audio_byte_count:
            raise RuntimeError("Empty live speech audio")
        await ensure_active()
        await emit("end")
        return LiveSpeechCompletion(
            submitted_characters=len(text), generated_audio_bytes=audio_byte_count, chunk_count=chunk_index,
        )
    except (Exception, asyncio.CancelledError) as error:
        # A failed transport must not trigger another publish/retry. Other
        # failures send one bounded, content-free terminal event if possible.
        if not isinstance(error, LiveSpeechDeliveryUnavailable):
            try:
                await emit("error")
            except LiveSpeechDeliveryUnavailable:
                pass
        raise
