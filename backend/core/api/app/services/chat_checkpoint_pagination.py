"""Stable, bounded checkpoint discovery; encrypted summaries remain opaque."""
from __future__ import annotations

import json
from typing import Any
from fastapi import HTTPException

FIELDS = "id,chat_id,encrypted_summary,compressed_up_to_timestamp,compressed_up_to_message_id,compressed_message_count,summary_token_estimate,key_version,created_at,updated_at"


async def checkpoint_by_id(directus: Any, *, chat_id: str, checkpoint_id: str) -> dict[str, Any]:
    """A selected large summary uses its own budget; manifests stay internal."""
    rows = await directus.get_items("chat_compression_checkpoints", params={
        "filter": {"chat_id": {"_eq": chat_id}, "id": {"_eq": checkpoint_id}},
        "fields": FIELDS, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise HTTPException(status_code=503, detail="CHECKPOINT_UNAVAILABLE")
    if not rows:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    row = rows[0]
    if len(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CHECKPOINT_REQUIRES_NEWER_BOUNDED_READER")
    return {"checkpoint": row}


async def checkpoint_window(directus: Any, *, chat_id: str, before_timestamp: int | None = None,
                            before_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    limit = min(max(int(limit), 1), 20)
    filters: list[dict[str, Any]] = [{"chat_id": {"_eq": chat_id}}]
    if before_timestamp is not None:
        filters.append({"_or": [{"created_at": {"_lt": before_timestamp}}, {"_and": [
            {"created_at": {"_eq": before_timestamp}}, {"id": {"_lt": before_id or "ffffffff-ffff-ffff-ffff-ffffffffffff"}},
        ]}]})
    rows = await directus.get_items("chat_compression_checkpoints", params={
        "filter": {"_and": filters}, "fields": FIELDS, "sort": "-created_at,-id", "limit": limit + 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("CHECKPOINT_PAGE_UNAVAILABLE")
    admitted, total, oversized = [], 0, None
    for row in rows[:limit]:
        size = len(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode())
        if total + size > 128 * 1024:
            if not admitted:
                oversized = row["id"]
            break
        total += size
        admitted.append(row)
    oldest = admitted[-1] if admitted else None
    return {"checkpoints": list(reversed(admitted)), "has_more_before": len(rows) > len(admitted),
            "start_cursor": {"created_at": int(oldest["created_at"]), "id": oldest["id"]} if oldest else None,
            "oversized_checkpoint_id": oversized}
