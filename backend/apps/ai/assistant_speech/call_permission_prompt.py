"""Tell a live voice call that a request now waits for the user's tap.

A turn that pauses for an approval (Memory access, a connected account) ends
without an answer. In a call that used to mean silence. This publishes one
transient event with the pre-recorded lines in the answering Mate's voice; the
client plays the "needs you" chime, the request line, a reminder, the thanks
after the tap and, for a Memory request, the timeout line. Approval itself
stays a manual tap: nothing here grants or decides anything.

The event carries static public asset URLs only, never request content.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any, Literal

from backend.apps.audio.assistant_speech.acknowledgements import build_permission_prompt_clips

logger = logging.getLogger(__name__)

PermissionPromptKind = Literal["memory", "approval"]
CALL_PERMISSION_PROMPT_EVENT = "send_voice_call_permission_prompt"


def _speaks_in_call(request_data: Any) -> bool:
    return (
        getattr(request_data, "voice_mode", False) is True
        and getattr(request_data, "auto_speak_response", False) is True
        and not getattr(request_data, "is_external", False)
        and not getattr(request_data, "is_incognito", False)
        and bool(getattr(request_data, "voice_call_id", None))
    )


def build_call_permission_prompt(
    *,
    request_data: Any,
    mates: Iterable[Any],
    mate_id: str | None,
    language: str | None,
    request_id: str,
    kind: PermissionPromptKind,
) -> dict[str, Any] | None:
    """The client payload, or None when the turn is not spoken or nothing fits.

    The voice is the answering Mate's own; with no known Mate or an unsupported
    language the call stays silent instead of guessing.
    """
    if not _speaks_in_call(request_data) or not mate_id or not language:
        return None
    mate = next((item for item in mates if getattr(item, "id", None) == mate_id), None)
    profile = getattr(mate, "voice_profile", None)
    if profile is None:
        return None
    clips = build_permission_prompt_clips(voice_profile_id=profile.key, language=language)
    if not clips:
        return None
    request_line = clips["needs_memory" if kind == "memory" else "needs_approval"]
    return {
        "chat_id": request_data.chat_id,
        "request_id": request_id,
        "voice_call_id": request_data.voice_call_id,
        "kind": kind,
        "clips": {
            "request": request_line,
            "reminder": clips["needs_reminder"],
            "thanks": clips["approval_thanks"],
            **({"timeout": clips["memory_timeout"]} if kind == "memory" else {}),
        },
    }


async def publish_call_permission_prompt(
    *, cache_service: Any, user_id: str, payload: dict[str, Any] | None, log_prefix: str,
) -> bool:
    """Publish the prompt to the user's devices; a failure only costs the spoken line."""
    if payload is None or cache_service is None:
        return False
    redis_client = await cache_service.client
    if not redis_client:
        logger.warning("%s No Redis client; the call stays silent for request %s", log_prefix, payload["request_id"])
        return False
    await redis_client.publish(
        f"user_cache_events:{user_id}",
        json.dumps({"event_type": CALL_PERMISSION_PROMPT_EVENT, "payload": payload}),
    )
    logger.info("%s Published voice call permission prompt for request %s", log_prefix, payload["request_id"])
    return True
