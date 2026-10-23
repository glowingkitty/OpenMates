"""Bounded, content-free history discovery after the caller authorizes a chat."""
from __future__ import annotations

import json
from typing import Any

from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService, LARGE_MESSAGE_BYTES

CATALOGUE_LIMIT = 200


def _position(row: dict[str, Any]) -> tuple[int, str]:
    return int(row["created_at"]), str(row.get("client_message_id") or row.get("message_id") or row["id"])


async def timeline_page(*, directus: Any, s3: Any, chat_id: str, archived: bool,
                        before_timestamp: int | None, before_message_id: str | None,
                        limit: int = CATALOGUE_LIMIT) -> dict[str, Any]:
    """Keyset pages contain only stable identity, role and turn association.

    Old cold-page catalogues have positions but no roles. Recover that metadata
    through at most ten small archive windows, never an entire history.
    The browser still receives no content or ciphertext during discovery.
    """
    limit = max(1, min(limit, CATALOGUE_LIMIT))
    before = (before_timestamp, before_message_id or "\uffff") if before_timestamp is not None else None
    # Directus item filters reject inequalities on string IDs. The existing
    # internal window reader supports stable SQL cursors with a fixed metadata
    # projection, including legacy rows whose client ID is absent.
    hot = await directus.chat.get_message_timeline_metadata(
        chat_id, before_timestamp=before_timestamp, before_message_id=before_message_id, limit=limit + 1)
    if not isinstance(hot, list) or len(hot) > limit + 1:
        raise ValueError("TIMELINE_METADATA_UNAVAILABLE")
    cold: dict[str, Any] = {}
    if archived:
        service = ChatMessageArchiveService(directus_service=directus, s3_service=s3)
        cold = {"messages": [], "has_more_before": True}
        cursor = before
        hydrated_bytes = 0
        while len(cold["messages"]) < limit and cold["has_more_before"]:
            page = await service.read_before(chat_id=chat_id, before=cursor, limit=min(limit - len(cold["messages"]), 20))
            records = page["messages"]
            # Preserve the existing aggregate large-object budget across this
            # entire catalogue request. A partial page advances its cursor;
            # multiple large messages must not permanently block older entries.
            partial = False
            for record in reversed(records):
                row = record
                if row.get("role") is None:
                    size = int((row.get("large_payload") or {}).get("size_bytes") or 0)
                    if hydrated_bytes + size > LARGE_MESSAGE_BYTES and cold["messages"]:
                        partial = True
                        break
                    row = (await service.hydrate_records([record]))[0]
                    hydrated_bytes += size
                metadata = {key: row.get(key) for key in (
                    "id", "client_message_id", "created_at", "role", "user_message_id")}
                metadata["chat_id"] = row.get("chat_id", chat_id)
                cold["messages"].append(metadata)
            cold["has_more_before"] = partial or bool(page.get("has_more_before"))
            if partial:
                break
            if not records:
                if cold["has_more_before"]:
                    raise ValueError("TIMELINE_ARCHIVE_CURSOR_UNAVAILABLE")
                break
            next_cursor = _position(records[0])
            if cursor is not None and next_cursor >= cursor:
                raise ValueError("TIMELINE_ARCHIVE_CURSOR_DID_NOT_ADVANCE")
            cursor = next_cursor
    merged: dict[str, dict[str, Any]] = {}
    for raw in [*cold.get("messages", []), *hot]:
        row = json.loads(raw) if isinstance(raw, str) else raw
        position = _position(row)
        if row.get("chat_id", chat_id) != chat_id or row.get("role") not in {"user", "assistant", "system"}:
            raise ValueError("TIMELINE_IDENTITY_UNAVAILABLE")
        if before is None or position < before:
            merged[position[1]] = {"message_id": position[1], "created_at": position[0], "role": row["role"],
                                   "user_message_id": row.get("user_message_id")}
    rows = sorted(merged.values(), key=_position)
    has_more = len(hot) > limit or bool(cold.get("has_more_before")) or len(rows) > limit
    rows = rows[-limit:]
    return {"chat_id": chat_id, "entries": rows, "has_more": has_more,
            "before": {"created_at": rows[0]["created_at"], "message_id": rows[0]["message_id"]} if rows else None}
