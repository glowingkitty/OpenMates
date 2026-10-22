"""Call authority at canonical chat admission and paid inference boundaries.

The registry contains identities only. Partial speech is never issued there.
Ciphertext synchronization uses require_active_call directly and retains its
finalizing grace; a new paid request requires the stricter active state here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from backend.shared.python_utils.voice_call_registry import require_active_call

_CALL_ID = re.compile(r"^[a-f0-9]{32}$")


@dataclass(frozen=True)
class VoiceCallDelivery:
    voice_mode: bool = False
    voice_call_id: str | None = None
    voice_turn_id: str | None = None


def _value(request: Any, key: str, default: Any = None) -> Any:
    return request.get(key, default) if isinstance(request, Mapping) else getattr(request, key, default)


def _identity(call_id: Any, turn_id: Any, message_id: Any) -> None:
    if (not isinstance(call_id, str) or not _CALL_ID.fullmatch(call_id)
            or not isinstance(turn_id, str) or not turn_id or len(turn_id) > 128
            or turn_id != message_id):
        raise ValueError("Voice turn is not bound to this authenticated call")


async def admit_voice_call_turn(
    cache: Any, *, message: Mapping[str, Any], websocket_scope: Mapping[str, Any],
    user_id: str, chat_id: str, message_id: str,
) -> VoiceCallDelivery:
    """Bind a completed canonical WS turn to the authenticated call session."""
    if message.get("voice_mode") is not True:
        return VoiceCallDelivery()
    session_id = websocket_scope.get("voice_call_session_hash")
    call_id, turn_id = message.get("voice_call_id"), message.get("voice_turn_id")
    _identity(call_id, turn_id, message_id)
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Voice turn is not bound to this authenticated call")
    binding = await require_active_call(
        cache, user_id=user_id, session_id=session_id, chat_id=chat_id,
        call_id=call_id, message_id=message_id, role="user",
    )
    if binding.state != "active":
        raise ValueError("Voice call has ended")
    return VoiceCallDelivery(True, call_id, turn_id)


async def require_active_voice_dispatch(cache: Any, request: Any) -> None:
    """Recheck trusted ordinary-request identities immediately before paid work.

    WS admission already checked the exact authenticated session. A queued
    worker reloads that registry session instead of adding its hash to payloads.
    Ownership, chat, issued role, and lifecycle are checked again atomically by
    require_active_call. This does not select any model or provider.
    """
    if _value(request, "voice_mode") is not True:
        return
    if any(_value(request, key) for key in ("is_external", "is_anonymous", "is_incognito", "team_id")):
        raise ValueError("Voice calls require a personal first-party chat")
    call_id, turn_id, message_id = (_value(request, key) for key in ("voice_call_id", "voice_turn_id", "message_id"))
    _identity(call_id, turn_id, message_id)
    client = await cache.client
    if client is None:
        raise RuntimeError("Voice call authority unavailable")
    session_id = await client.hget(f"voice:call:{call_id}", "session")
    if isinstance(session_id, bytes):
        session_id = session_id.decode()
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Voice call has ended")
    binding = await require_active_call(
        cache, user_id=_value(request, "user_id"), session_id=session_id,
        chat_id=_value(request, "chat_id"), call_id=call_id, message_id=message_id, role="user",
    )
    if binding.state != "active":
        raise ValueError("Voice call has ended")


def queued_voice_delivery(members: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain the first queued request's delivery mode when legacy batching it.

    Every voice member is separately checked before dispatch; mixed batches do
    not acquire call delivery merely from a later member's client metadata.
    """
    first = members[0]
    voice = first.get("voice_mode") is True
    return {"voice_mode": voice,
            "voice_call_id": first.get("voice_call_id") if voice else None,
            "voice_turn_id": first.get("voice_turn_id") if voice else None,
            "voice_heard_boundary": first.get("voice_heard_boundary") if voice else None,
            "auto_speak_response": voice or first.get("auto_speak_response") is True,
            "assistant_speech_lazy_dispatch": False if voice else first.get("assistant_speech_lazy_dispatch") is True}
