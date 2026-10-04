"""Byte-bounded encrypted message windows with an explicit oversized cursor."""
from __future__ import annotations

import json
from typing import Any

MESSAGE_WINDOW_LIMIT = 20
MESSAGE_WINDOW_BYTES = 256 * 1024
EXACT_MESSAGE_BYTES = 2 * 1024 * 1024


def _record(value: str | dict[str, Any]) -> dict[str, Any]:
    row = json.loads(value) if isinstance(value, str) else value
    if not isinstance(row, dict):
        raise ValueError("Invalid encrypted message window row")
    return row


def _cursor(value: str | dict[str, Any]) -> dict[str, Any]:
    row = _record(value)
    message_id = row.get("client_message_id") or row.get("message_id") or row.get("id")
    if not isinstance(message_id, str) or not message_id:
        raise ValueError("Encrypted message window row lacks stable ID")
    return {"created_at": int(row["created_at"]), "message_id": message_id}


def encrypted_message_bytes(value: str | dict[str, Any]) -> int:
    row = _record(value)
    ref = row.get("large_payload")
    if row.get("encrypted_content") is None and isinstance(ref, dict):
        size = ref.get("size_bytes")
        checksum = ref.get("checksum")
        object_key = ref.get("object_key")
        if (not isinstance(size, int) or isinstance(size, bool) or size <= 0
                or size > EXACT_MESSAGE_BYTES or not isinstance(object_key, str) or not object_key
                or not isinstance(checksum, str) or len(checksum) != 64
                or any(ch not in "0123456789abcdef" for ch in checksum)):
            raise ValueError("Invalid large encrypted message reference")
        return size
    return len(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def bound_encrypted_message_window(
    window: dict[str, Any], *, direction: str, anchor_message_id: str | None = None,
) -> dict[str, Any]:
    """Keep a contiguous viewport and signal rows that need an exact read."""
    rows = list(window.get("messages") or [])
    if not rows:
        return {**window, "oversized_message": bool(window.get("oversized_message")),
                "oversized_message_cursor": window.get("oversized_message_cursor"),
                "payload_bytes": int(window.get("payload_bytes") or 0)}
    if len(rows) > MESSAGE_WINDOW_LIMIT:
        raise ValueError("Encrypted message window exceeded count limit")
    sizes = [encrypted_message_bytes(row) for row in rows]
    selected: set[int] = set()
    used = 0
    oversized_cursor = None

    def admit(index: int) -> bool:
        nonlocal used, oversized_cursor
        size = sizes[index]
        if used + size > MESSAGE_WINDOW_BYTES:
            if not selected and size > MESSAGE_WINDOW_BYTES:
                oversized_cursor = _cursor(rows[index])
            return False
        selected.add(index)
        used += size
        return True

    if direction == "after":
        for index in range(len(rows)):
            if not admit(index):
                break
    elif direction == "around" and anchor_message_id:
        anchor_index = next((index for index, row in enumerate(rows)
                             if _cursor(row)["message_id"] == anchor_message_id), None)
        if anchor_index is None:
            raise ValueError("Anchor missing from successful message window")
        if admit(anchor_index):
            before_open = after_open = True
            for distance in range(1, len(rows)):
                before_index, after_index = anchor_index - distance, anchor_index + distance
                if before_open and before_index >= 0:
                    before_open = admit(before_index)
                if after_open and after_index < len(rows):
                    after_open = admit(after_index)
                if (not before_open or before_index < 0) and (not after_open or after_index >= len(rows)):
                    break
    else:
        for index in range(len(rows) - 1, -1, -1):
            if not admit(index):
                break

    kept = [rows[index] for index in sorted(selected)]
    first_index = min(selected) if selected else len(rows)
    last_index = max(selected) if selected else -1
    return {
        **window,
        "messages": kept,
        "has_more_before": bool(window.get("has_more_before")) or first_index > 0,
        "has_more_after": bool(window.get("has_more_after")) or last_index < len(rows) - 1,
        "start_cursor": _cursor(kept[0]) if kept else None,
        "end_cursor": _cursor(kept[-1]) if kept else None,
        "oversized_message": oversized_cursor is not None or bool(window.get("oversized_message")),
        "oversized_message_cursor": oversized_cursor or window.get("oversized_message_cursor"),
        "payload_bytes": used,
    }
