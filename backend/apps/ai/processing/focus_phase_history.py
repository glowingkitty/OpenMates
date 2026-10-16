"""Exclude stored focus phase notices from the inference-only history."""

from __future__ import annotations

import json
from typing import Any, TypeVar
from uuid import UUID


MessageT = TypeVar("MessageT")
_EVENT_KEYS = frozenset({
    "type", "event_id", "chat_id", "focus_id", "run_id", "version",
    "created_at", "previous_phase_id", "phase_id", "phase_title", "direction",
})


def _uuid(value: Any, *, version: int | None = 4) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
        return str(parsed) == value and (version is None or parsed.version == version)
    except ValueError:
        return False


def _phase_notice(message: Any, chat_id: str) -> bool:
    role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if role != "system" or not isinstance(content, str) or not content.startswith("{") or len(content) > 4096:
        return False
    try:
        event = json.loads(content)
    except (ValueError, TypeError):
        return False
    return (
        isinstance(event, dict)
        and event.keys() == _EVENT_KEYS
        and event.get("type") == "focus_phase_changed"
        and event.get("chat_id") == chat_id
        and _uuid(event.get("chat_id"), version=None)
        and _uuid(event.get("event_id"))
        and _uuid(event.get("run_id"))
        and all(isinstance(event.get(key), str) and 0 < len(event[key]) <= 255
                for key in ("focus_id", "previous_phase_id", "phase_id", "phase_title"))
        and type(event.get("version")) is int and event["version"] > 0
        and type(event.get("created_at")) is int and event["created_at"] > 0
        and event.get("direction") in {"forward", "backward"}
    )


def filter_focus_phase_history(history: list[MessageT], *, chat_id: str) -> list[MessageT]:
    """Return a new model-facing history; keep encrypted chat records untouched."""
    return [message for message in history if not _phase_notice(message, chat_id)]
