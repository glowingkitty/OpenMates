"""Waiting state of a live voice call.

A hard signal (the call bar hold button) or the decision model's spoken
`wait` intent puts the call into waiting: the assistant stays quiet and
everything the caller says is held, then merged with the next turn after
waiting ends into ONE turn. Entering and leaving play ready-made lines on the
client (no inference, no credits). The `repeat` intent asks the client to
replay the stored last answer; the server never regenerates it.

The intent comes from the existing completion decision (`none|wait|resume|
repeat`); this module never inspects words itself.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

MAX_HELD_CHARS = 8000

WAITING_START_LINE = "waiting_start"
WAITING_RESUME_LINE = "waiting_resume"

Send = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class VoiceWaiting:
    """Per-call waiting flag and the caller speech held while waiting."""

    active: bool = False
    held: list[str] = field(default_factory=list)

    def _hold(self, text: str) -> None:
        text = text.strip()
        if text:
            self.held.append(text)
            while len(" ".join(self.held)) > MAX_HELD_CHARS and len(self.held) > 1:
                self.held.pop(0)

    def merged(self, text: str) -> str:
        """Join held speech and `text` as one turn, clearing what was held."""
        parts, self.held = [*self.held, text.strip()], []
        return " ".join(part for part in parts if part)

    async def set_active(self, active: bool, *, send: Send, call_id: str, pending_text: str = "",
                         clip: dict[str, object] | None = None, categorized: bool = False) -> bool:
        """Enter or leave waiting; `pending_text` is unsent speech to keep."""
        if active == self.active:
            return False
        self.active = active
        if active:
            self._hold(pending_text)
        event = {"type": "waiting", "call_id": call_id, "active": active,
                 "line": WAITING_START_LINE if active else WAITING_RESUME_LINE}
        if active and categorized:
            event["clip"] = clip
        await send(event)
        return True

    async def route(self, text: str, intent: str, *, send: Send, call_id: str,
                    clip: dict[str, object] | None = None, categorized: bool = False) -> tuple[str | None, str]:
        """Decide a complete utterance: (discard reason or None, text to send)."""
        if intent == "pause_playback":
            return "pause_playback", text
        if intent == "stop":
            return "stop", text
        if intent == "wait":
            await self.set_active(True, send=send, call_id=call_id, pending_text=text,
                                  clip=clip, categorized=categorized)
            return "waiting", text
        if intent == "resume" and self.active:
            await self.set_active(False, send=send, call_id=call_id)
            return "resume", text
        if intent == "repeat":
            await send({"type": "repeat_last_answer", "call_id": call_id})
            return "repeat", text
        if self.active:
            self._hold(text)
            return "waiting", text
        return None, self.merged(text) if self.held else text
