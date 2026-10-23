"""Validate and route transient speech bytes to one authenticated live-call owner.

This is an internal Redis-to-first-party-WebSocket surface, never a public,
history, sync or replay channel. It adds no provider work, billing or durable
storage. Live-call registry authority must remain available: cache miss/failure
must not fall back to a database or broaden delivery to active-chat devices.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

from backend.shared.python_utils.voice_call_registry import active_call_session

MAX_AUDIO_CHUNK_BYTES = 32 * 1024
MAX_AUDIO_CHUNKS = 4096
MAX_AUDIO_BASE64_LENGTH = 4 * ((MAX_AUDIO_CHUNK_BYTES + 2) // 3)
MAX_SAFE_INTEGER = (1 << 53) - 1
LIVE_HANDOFF_ERROR = "Speech is temporarily unavailable."
_HEX_32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_ENVELOPE_FIELDS = {"type", "chat_id", "message_id", "user_id_hash", "payload"}
_COMMON_FIELDS = {
    "chat_id", "message_id", "voice_call_id", "segment_id", "sequence", "kind",
    "source_version", "execution_version", "attempt_id", "phase", "chunk_index", "mime_type",
}


def _uuid_identity(value: object) -> bool:
    """Accept canonical UUID strings without coercing arbitrary input objects."""
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _integer(value: object, minimum: int, maximum: int = MAX_SAFE_INTEGER) -> bool:
    """JSON booleans must not pass Python's otherwise permissive integer check."""
    return type(value) is int and minimum <= value <= maximum


def validate_assistant_speech_sealed_segments(payload: Mapping[str, object]) -> list[dict[str, object]]:
    """Validate final live membership without forwarding nested private fields."""
    call_id = payload.get("voice_call_id")
    source_version = payload.get("source_version")
    segments = payload.get("segments")
    if (not isinstance(call_id, str) or not _HEX_32.fullmatch(call_id)
            or not _integer(source_version, 1) or not isinstance(segments, list) or len(segments) > 1024
            or ("error" in payload and payload["error"] != LIVE_HANDOFF_ERROR)):
        raise ValueError("invalid_sealed_membership")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    previous = -1
    fields = {"segment_id", "sequence", "kind", "source_version"}
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != fields:
            raise ValueError("invalid_sealed_member")
        segment_id, sequence = segment["segment_id"], segment["sequence"]
        if (not isinstance(segment_id, str) or not (_HEX_64.fullmatch(segment_id) or _uuid_identity(segment_id))
                or segment_id in seen or not _integer(sequence, 0, 65535) or sequence <= previous
                or segment["kind"] != "voice_prose_clause"
                or type(segment["source_version"]) is not int or segment["source_version"] != source_version):
            raise ValueError("invalid_sealed_member")
        result.append({field: segment[field] for field in fields})
        seen.add(segment_id)
        previous = sequence
    return result


def validate_assistant_speech_audio_event(
    envelope: object, *, channel: object,
) -> dict[str, object]:
    """Return only an exact valid wire payload or raise a content-free category.

    Per-attempt ordering and duplicate rejection belong to the playback consumer;
    index bounds here prevent any valid attempt from declaring >4096 chunks.
    No decoded audio is retained or returned by this validator.
    """
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_FIELDS:
        raise ValueError("invalid_envelope")
    if envelope["type"] != "assistant_speech_audio":
        raise ValueError("invalid_event_type")
    chat_id, message_id = envelope["chat_id"], envelope["message_id"]
    # Canonical assistant replies use a deterministic SHA-256 message ID.
    # UUID message IDs remain valid for existing first-party messages.
    if not _uuid_identity(chat_id) or not isinstance(message_id, str) or not (
        _HEX_64.fullmatch(message_id) or _uuid_identity(message_id)
    ):
        raise ValueError("invalid_envelope_identity")
    owner_hash = envelope["user_id_hash"]
    if not isinstance(owner_hash, str) or not _HEX_64.fullmatch(owner_hash):
        raise ValueError("invalid_owner_hash")
    if not isinstance(channel, str) or channel != f"chat_stream::{chat_id}":
        raise ValueError("channel_scope_mismatch")
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    phase = payload.get("phase")
    if phase not in ("start", "chunk", "end", "error"):
        raise ValueError("invalid_phase")
    required = _COMMON_FIELDS | ({"audio_data"} if phase == "chunk" else set())
    if set(payload) != required:
        raise ValueError("invalid_payload_fields")
    if payload["chat_id"] != chat_id or payload["message_id"] != message_id:
        raise ValueError("envelope_identity_mismatch")
    call_id, segment_id = payload["voice_call_id"], payload["segment_id"]
    if not isinstance(call_id, str) or not _HEX_32.fullmatch(call_id):
        raise ValueError("invalid_call_identity")
    if not isinstance(segment_id, str) or not (_HEX_64.fullmatch(segment_id) or _uuid_identity(segment_id)):
        raise ValueError("invalid_segment_identity")
    if not _uuid_identity(payload["attempt_id"]):
        raise ValueError("invalid_attempt_identity")
    sequence, kind = payload["sequence"], payload["kind"]
    if not _integer(sequence, -1, 65535):
        raise ValueError("invalid_sequence")
    if not (kind == "waiting_confirmation" and sequence == -1
            or kind == "voice_prose_clause" and sequence >= 0):
        raise ValueError("invalid_audio_kind_sequence")
    if not all(_integer(payload[field], 1) for field in ("source_version", "execution_version")):
        raise ValueError("invalid_version")
    if payload["mime_type"] != "audio/mpeg":
        raise ValueError("invalid_audio_kind")
    index_limit = MAX_AUDIO_CHUNKS - 1 if phase == "chunk" else MAX_AUDIO_CHUNKS
    if not _integer(payload["chunk_index"], 0, index_limit) or phase == "start" and payload["chunk_index"] != 0:
        raise ValueError("invalid_chunk_index")
    if phase == "chunk":
        encoded = payload["audio_data"]
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= MAX_AUDIO_BASE64_LENGTH:
            raise ValueError("invalid_audio_size")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("invalid_audio_encoding") from None
        if not 1 <= len(decoded) <= MAX_AUDIO_CHUNK_BYTES:
            raise ValueError("invalid_audio_size")
        if base64.b64encode(decoded).decode("ascii") != encoded:
            raise ValueError("invalid_audio_encoding")
    return {field: payload[field] for field in required}


async def route_assistant_speech_audio(
    *, envelope: object, channel: object, manager: Any, cache: Any,
    session_lookup: Callable[..., Awaitable[str | None]] = active_call_session,
) -> str:
    """Fail closed and return a fixed log category, never a payload or exception.

    The connection manager contains authenticated first-party sockets only. An
    owner hash must match exactly one connected user, the registry must still
    bind this user/chat/call, and exactly one connection must own its session.
    Visible-chat state intentionally has no role in this delivery path.
    """
    try:
        payload = validate_assistant_speech_audio_event(envelope, channel=channel)
    except ValueError:
        return "invalid_event"
    try:
        owners = [
            user_id for user_id in manager.active_connections
            if isinstance(user_id, str)
            and hashlib.sha256(user_id.encode()).hexdigest() == envelope["user_id_hash"]
        ]
        if len(owners) != 1:
            return "owner_unavailable"
        owner = owners[0]
        session = await session_lookup(
            cache, user_id=owner, chat_id=payload["chat_id"], call_id=payload["voice_call_id"],
        )
        if not isinstance(session, str) or not session:
            return "inactive_call"
        targets = [
            device for device, connection in manager.get_connections_for_user(owner).items()
            if isinstance(getattr(connection, "scope", None), Mapping)
            and connection.scope.get("voice_call_session_hash") == session
        ]
        if len(targets) != 1:
            return "owner_connection_unavailable"
    except Exception:
        return "authority_unavailable"
    try:
        await manager.send_personal_message(
            message={"type": "assistant_speech_audio", "payload": payload},
            user_id=owner, device_fingerprint_hash=targets[0],
        )
    except Exception:
        return "delivery_unavailable"
    return "delivered"
