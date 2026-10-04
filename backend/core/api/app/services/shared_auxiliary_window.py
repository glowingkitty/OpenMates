"""Bounded encrypted auxiliary records for public shared-chat readers."""
from __future__ import annotations

import json
from typing import Any

PAGE_LIMIT = 20
PAGE_BYTES = 128 * 1024
EXACT_BYTES = 2 * 1024 * 1024

FIELDS = {
    "sub_chats": ("chats", "parent_id", "created_at", "id,encrypted_title,created_at,updated_at,messages_v,title_v,metadata_v,last_edited_overall_timestamp,unread_count,encrypted_chat_summary,encrypted_icon,encrypted_category,parent_id,is_sub_chat,budget_limit,budget_spent"),
    "message_highlights": ("message_highlights", "chat_id", "created_at", "id,chat_id,message_id,author_user_id,key_version,encrypted_payload,created_at,updated_at"),
    "code_run_outputs": ("code_run_outputs", "chat_id", "updated_at", "id,chat_id,embed_id,author_user_id,key_version,encrypted_payload,created_at,updated_at"),
    "notebook_run_outputs": ("notebook_run_outputs", "chat_id", "updated_at", "id,chat_id,notebook_embed_id,author_user_id,source_version,key_version,encrypted_payload,created_at,updated_at"),
}


def _size(row: dict[str, Any]) -> int:
    return len(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode())


def _position(row: dict[str, Any], timestamp_field: str) -> tuple[int, str]:
    return int(row[timestamp_field]), str(row["id"])


async def shared_auxiliary_window(
    directus: Any, *, chat_id: str, kind: str,
    before_timestamp: int | None = None, before_id: str | None = None,
) -> dict[str, Any]:
    """One latest-first query; response items preserve chronological order."""
    if kind not in FIELDS:
        raise ValueError("Unknown shared auxiliary kind")
    if (before_timestamp is None) != (before_id is None):
        raise ValueError("Incomplete shared auxiliary cursor")
    if before_timestamp is not None and (before_timestamp < 0 or not isinstance(before_id, str)
                                         or not before_id or len(before_id) > 256):
        raise ValueError("Invalid shared auxiliary cursor")
    collection, scope_field, timestamp_field, fields = FIELDS[kind]
    scope: dict[str, Any] = {scope_field: {"_eq": chat_id}}
    if before_timestamp is not None:
        scope["_or"] = [
            {timestamp_field: {"_lt": before_timestamp}},
            {"_and": [{timestamp_field: {"_eq": before_timestamp}}, {"id": {"_lt": before_id}}]},
        ]
    params = {"filter": scope, "fields": fields, "sort": [f"-{timestamp_field}", "-id"],
              "limit": PAGE_LIMIT + 1}
    rows = await directus.get_items(collection, params=params, admin_required=True,
                                    no_cache=True, raise_on_error=True,
                                    return_none_on_403=kind == "sub_chats")
    if kind == "sub_chats" and rows is None:
        params["fields"] = ",".join(field for field in fields.split(",") if field != "metadata_v")
        rows = await directus.get_items(collection, params=params, admin_required=True,
                                        no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("SHARED_AUXILIARY_PAGE_UNAVAILABLE")
    admitted: list[dict[str, Any]] = []
    payload_bytes = 0
    oversized_id = None
    for row in rows[:PAGE_LIMIT]:
        size = _size(row)
        if payload_bytes + size > PAGE_BYTES:
            if not admitted:
                oversized_id = row.get("id")
            break
        admitted.append(row)
        payload_bytes += size
    oldest = admitted[-1] if admitted else None
    return {"items": list(reversed(admitted)),
            "has_more_before": len(rows) > len(admitted),
            "start_cursor": {"timestamp": _position(oldest, timestamp_field)[0], "id": oldest["id"]} if oldest else None,
            "oversized_id": oversized_id, "payload_bytes": payload_bytes}


async def shared_auxiliary_by_id(directus: Any, *, chat_id: str, kind: str, record_id: str) -> dict[str, Any] | None:
    if kind not in FIELDS:
        raise ValueError("Unknown shared auxiliary kind")
    if not record_id or len(record_id) > 256:
        raise ValueError("Invalid shared auxiliary record ID")
    collection, scope_field, _timestamp_field, fields = FIELDS[kind]
    rows = await directus.get_items(collection, params={
        "filter": {scope_field: {"_eq": chat_id}, "id": {"_eq": record_id}},
        "fields": fields, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True,
        return_none_on_403=kind == "sub_chats")
    if kind == "sub_chats" and rows is None:
        rows = await directus.get_items(collection, params={
            "filter": {scope_field: {"_eq": chat_id}, "id": {"_eq": record_id}},
            "fields": ",".join(field for field in fields.split(",") if field != "metadata_v"),
            "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("SHARED_AUXILIARY_RECORD_UNAVAILABLE")
    if not rows:
        return None
    if _size(rows[0]) > EXACT_BYTES:
        raise OverflowError("SHARED_AUXILIARY_RECORD_REQUIRES_BOUNDED_READER")
    return rows[0]
