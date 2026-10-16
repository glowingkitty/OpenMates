"""Bounded ciphertext-only Plan and Task pages for public shared chats.

The share route checks that the chat is currently public before calling these
helpers. Every query here remains scoped to that chat, including key retries.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.core.api.app.services.user_plan_share_bundle import (
    CHAT_SHARE_PLAN_STATUSES, SHARED_PLAN_FIELDS, SHARED_PLAN_KEY_WRAPPER_FIELDS,
)
from backend.core.api.app.services.user_task_share_bundle import (
    SHARED_TASK_FIELDS, SHARED_TASK_KEY_WRAPPER_FIELDS,
)

PAGE_LIMIT = 20
PAGE_BYTES = 128 * 1024
EXACT_BYTES = 2 * 1024 * 1024

KINDS = {
    "plans": ("user_plans", "plan_id", SHARED_PLAN_FIELDS,
              "user_plan_key_wrappers", "hashed_plan_id", SHARED_PLAN_KEY_WRAPPER_FIELDS),
    "tasks": ("user_tasks", "task_id", SHARED_TASK_FIELDS,
              "user_task_key_wrappers", "hashed_task_id", SHARED_TASK_KEY_WRAPPER_FIELDS),
}


def _config(kind: str) -> tuple[str, str, str, str, str, str]:
    if kind not in KINDS:
        raise ValueError("Unknown shared Plan or Task kind")
    return KINDS[kind]


def _size(value: dict[str, Any]) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def _scope(chat_id: str, kind: str) -> dict[str, Any]:
    scope: dict[str, Any] = {"hashed_primary_chat_id": {"_eq": hashlib.sha256(chat_id.encode()).hexdigest()}}
    if kind == "plans":
        scope["status"] = {"_in": CHAT_SHARE_PLAN_STATUSES}
    return scope


def _validate_items(items: list[dict[str, Any]], chat_id: str, id_field: str) -> None:
    if any(not isinstance(item.get(id_field), str) or not item[id_field]
           or item.get("primary_chat_id") not in (None, chat_id) for item in items):
        raise RuntimeError("SHARED_PLAN_TASK_SCOPE_CHANGED")


async def _items_by_ids(directus: Any, *, chat_id: str, kind: str,
                        item_ids: list[str]) -> list[dict[str, Any]]:
    collection, id_field, fields, *_ = _config(kind)
    if (not item_ids or len(item_ids) > PAGE_LIMIT or len(set(item_ids)) != len(item_ids)
            or any(not isinstance(item_id, str) or not item_id or len(item_id) > 256 for item_id in item_ids)):
        raise ValueError("Invalid shared Plan or Task identifiers")
    rows = await directus.get_items(collection, params={
        "filter": {**_scope(chat_id, kind), id_field: {"_in": item_ids}},
        "fields": fields, "limit": PAGE_LIMIT,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("SHARED_PLAN_TASK_VALIDATION_UNAVAILABLE")
    _validate_items(rows, chat_id, id_field)
    if {row[id_field] for row in rows} != set(item_ids):
        raise ValueError("Shared Plan or Task is outside this chat")
    return rows


async def shared_plan_task_key_window(
    directus: Any, *, chat_id: str, kind: str, item_ids: list[str],
    after_key_id: str | None = None, key_id: str | None = None,
) -> dict[str, Any]:
    """Return chat wrappers only, with a bounded ID continuation or exact read."""
    _, id_field, _, wrapper_collection, hash_field, wrapper_fields = _config(kind)
    await _items_by_ids(directus, chat_id=chat_id, kind=kind, item_ids=item_ids)
    if after_key_id is not None and key_id is not None:
        raise ValueError("Conflicting key cursors")
    if after_key_id is not None and (not after_key_id or len(after_key_id) > 256):
        raise ValueError("Invalid key cursor")
    if key_id is not None and (not key_id or len(key_id) > 256):
        raise ValueError("Invalid key identifier")
    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
    hashes = [hashlib.sha256(item_id.encode()).hexdigest() for item_id in item_ids]
    filters: dict[str, Any] = {
        hash_field: {"_in": hashes}, "key_type": {"_eq": "chat"},
        "hashed_chat_id": {"_eq": hashed_chat_id},
    }
    if key_id is not None:
        filters["id"] = {"_eq": key_id}
    elif after_key_id is not None:
        filters["id"] = {"_gt": after_key_id}
    rows = await directus.get_items(wrapper_collection, params={
        "filter": filters, "fields": f"id,{wrapper_fields}", "sort": "id",
        "limit": 1 if key_id is not None else PAGE_LIMIT + 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("SHARED_PLAN_TASK_KEYS_UNAVAILABLE")
    if key_id is not None:
        if rows and _size(rows[0]) > EXACT_BYTES:
            raise OverflowError("SHARED_PLAN_TASK_KEY_REQUIRES_BOUNDED_READER")
        return {"key_wrappers": rows, "key_wrapper_window": {
            "has_more_after": False, "end_cursor": rows[-1]["id"] if rows else None,
            "oversized_key_id": None,
        }}
    admitted: list[dict[str, Any]] = []
    used = 0
    oversized_key_id = None
    for row in rows[:PAGE_LIMIT]:
        size = _size(row)
        if used + size > PAGE_BYTES:
            if not admitted:
                oversized_key_id = row["id"]
            break
        admitted.append(row)
        used += size
    return {"key_wrappers": admitted, "key_wrapper_window": {
        "has_more_after": len(rows) > len(admitted),
        "end_cursor": admitted[-1]["id"] if admitted else None,
        "oversized_key_id": oversized_key_id,
    }}


async def shared_plan_task_window(
    directus: Any, *, chat_id: str, kind: str,
    before_timestamp: int | None = None, before_id: str | None = None,
) -> dict[str, Any]:
    """Read one newest-first keyset page, displayed in chronological order."""
    collection, id_field, fields, *_ = _config(kind)
    if (before_timestamp is None) != (before_id is None):
        raise ValueError("Incomplete shared Plan or Task cursor")
    if before_timestamp is not None and (not isinstance(before_timestamp, int) or before_timestamp < 0
                                         or not isinstance(before_id, str) or not before_id or len(before_id) > 256):
        raise ValueError("Invalid shared Plan or Task cursor")
    filters = _scope(chat_id, kind)
    if before_timestamp is not None:
        filters["_or"] = [
            {"updated_at": {"_lt": before_timestamp}},
            {"_and": [{"updated_at": {"_eq": before_timestamp}}, {id_field: {"_lt": before_id}}]},
        ]
    rows = await directus.get_items(collection, params={
        "filter": filters, "fields": fields, "sort": ["-updated_at", f"-{id_field}"],
        "limit": PAGE_LIMIT + 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("SHARED_PLAN_TASK_PAGE_UNAVAILABLE")
    _validate_items(rows, chat_id, id_field)
    admitted: list[dict[str, Any]] = []
    used = 0
    oversized_id = None
    for row in rows[:PAGE_LIMIT]:
        size = _size(row)
        if used + size > PAGE_BYTES:
            if not admitted:
                oversized_id = row[id_field]
            break
        admitted.append(row)
        used += size
    oldest = admitted[-1] if admitted else None
    key_page = ({"key_wrappers": [], "key_wrapper_window": {
        "has_more_after": False, "end_cursor": None, "oversized_key_id": None,
    }} if not admitted else await shared_plan_task_key_window(
        directus, chat_id=chat_id, kind=kind, item_ids=[row[id_field] for row in admitted],
    ))
    return {"items": list(reversed(admitted)),
            "has_more_before": len(rows) > len(admitted),
            "start_cursor": {"timestamp": int(oldest["updated_at"]), "id": oldest[id_field]} if oldest else None,
            "oversized_id": oversized_id, "payload_bytes": used, **key_page}


async def shared_plan_task_by_id(
    directus: Any, *, chat_id: str, kind: str, record_id: str,
) -> dict[str, Any] | None:
    """Exact oversized ciphertext item, still under the checked share scope."""
    collection, id_field, fields, *_ = _config(kind)
    if not record_id or len(record_id) > 256:
        raise ValueError("Invalid shared Plan or Task identifier")
    rows = await directus.get_items(collection, params={
        "filter": {**_scope(chat_id, kind), id_field: {"_eq": record_id}},
        "fields": fields, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("SHARED_PLAN_TASK_RECORD_UNAVAILABLE")
    if not rows:
        return None
    _validate_items(rows, chat_id, id_field)
    if _size(rows[0]) > EXACT_BYTES:
        raise OverflowError("SHARED_PLAN_TASK_RECORD_REQUIRES_BOUNDED_READER")
    return {"item": rows[0], **await shared_plan_task_key_window(
        directus, chat_id=chat_id, kind=kind, item_ids=[record_id],
    )}
