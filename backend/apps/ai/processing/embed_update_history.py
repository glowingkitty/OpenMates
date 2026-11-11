# backend/apps/ai/processing/embed_update_history.py
#
# Turns the role:system "embed_updated" chat events (written when the user edits,
# enhances, restores or crops an embed themselves) into short user-role notes for
# the model, so the assistant's next turn knows which version is current.
# The payload is client-written JSON and reaches the model as text, so every
# value is validated and rebuilt from a fixed template; anything invalid is
# dropped from inference with a warning, never passed through raw.
# Spec: specifications/features/embed-user-edits (assistant.knows-current-version).

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

EMBED_UPDATED_TYPE = "embed_updated"
EMBED_UPDATED_SCHEMA_VERSION = 1
EMBED_KINDS = frozenset({"image", "diagram", "slides", "sheet", "document"})
EMBED_ACTIONS = frozenset({"edit", "enhance", "restore", "crop"})
EMBED_SURFACES = frozenset({"chat", "project"})
MAX_EVENT_CONTENT_CHARS = 4096
MAX_VERSION = 1_000_000
EMBED_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
EMBED_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_ACTION_PHRASE = {
    "edit": "edited",
    "enhance": "enhanced",
    "restore": "restored",
    "crop": "cropped",
}


def _is_version(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_VERSION


def _parse_event(content: Any) -> dict[str, Any] | None:
    """Return the decoded embed_updated payload, or None when the row is another event."""
    if not isinstance(content, str) or EMBED_UPDATED_TYPE not in content:
        return None
    if len(content) > MAX_EVENT_CONTENT_CHARS:
        return {}
    try:
        payload = json.loads(content)
    except ValueError:
        # Malformed JSON that names the event type is treated as an invalid event.
        return {} if content.lstrip().startswith("{") else None
    if not isinstance(payload, dict) or payload.get("type") != EMBED_UPDATED_TYPE:
        return None
    return payload


def _validated_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return the validated fields used for the note, or None when invalid."""
    if payload.get("schema_version") != EMBED_UPDATED_SCHEMA_VERSION:
        return None
    embed_id = payload.get("embed_id")
    embed_ref = payload.get("embed_ref")
    if not (isinstance(embed_id, str) and EMBED_ID_PATTERN.fullmatch(embed_id)):
        return None
    if not (isinstance(embed_ref, str) and EMBED_REF_PATTERN.fullmatch(embed_ref)):
        return None
    kind, action = payload.get("embed_kind"), payload.get("action")
    if kind not in EMBED_KINDS or action not in EMBED_ACTIONS:
        return None
    if payload.get("surface", "chat") not in EMBED_SURFACES:
        return None
    version = payload.get("version")
    if not _is_version(version):
        return None
    base_version = payload.get("base_version")
    if base_version is not None and not _is_version(base_version):
        return None
    restored_from = payload.get("restored_from")
    if action == "restore":
        if not _is_version(restored_from):
            return None
    elif restored_from is not None:
        return None
    return {
        "embed_id": embed_id,
        "embed_ref": embed_ref,
        "embed_kind": kind,
        "kind_label": kind,
        "action": action,
        "version": version,
        "restored_from": restored_from,
    }


def embed_update_note(event: dict[str, Any]) -> str:
    """Build the fixed-template note for a validated event."""
    action = event["action"]
    ref = f"{event['kind_label']} embed:{event['embed_ref']}"
    if action == "restore":
        head = f"The user restored version {event['restored_from']} of {ref} themselves (Restore)."
    else:
        head = f"The user {_ACTION_PHRASE[action]} {ref} themselves ({action.capitalize()})."
    return f"[{head} Version {event['version']} is now current; earlier versions remain in its history.]"


def _is_embed_event_row(row: Any) -> bool:
    return isinstance(row, dict) and row.get("role") == "system" and _parse_event(row.get("content")) is not None


def apply_embed_update_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite embed_updated system rows into user notes for inference.

    Valid events become user-role notes; invalid ones are dropped with a warning;
    a run of adjacent events for the same embed collapses to the newest. Every
    other row, including other system events, is returned untouched.
    """
    if not any(_is_embed_event_row(row) for row in messages):
        return messages
    result: list[dict[str, Any]] = []
    run_index: dict[str, int] = {}
    superseded: set[int] = set()
    for row in messages:
        if not _is_embed_event_row(row):
            run_index = {}
            result.append(row)
            continue
        payload = _parse_event(row.get("content")) or {}
        event = _validated_event(payload)
        if event is None:
            logger.warning(
                "Dropped invalid embed_updated history event from inference (message_id=%s)",
                str(row.get("message_id"))[:64],
            )
            continue
        note_row = {**row, "role": "user", "sender_name": "user", "content": embed_update_note(event)}
        previous = run_index.get(event["embed_id"])
        if previous is not None:
            superseded.add(previous)
        run_index[event["embed_id"]] = len(result)
        result.append(note_row)
    return [row for index, row in enumerate(result) if index not in superseded]
