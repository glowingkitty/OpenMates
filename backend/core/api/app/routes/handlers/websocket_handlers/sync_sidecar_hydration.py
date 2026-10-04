"""Bounded encrypted sidecar reads for startup and explicit recovery sync."""

from __future__ import annotations

import json
from typing import Any


SIDECAR_PAGE_LIMIT = 10
SIDECAR_PAGE_MAX_BYTES = 128 * 1024

CODE_RUN_FIELDS = "id,chat_id,embed_id,author_user_id,key_version,encrypted_payload,created_at,updated_at"
NOTEBOOK_FIELDS = "id,chat_id,notebook_embed_id,author_user_id,source_version,key_version,encrypted_payload,created_at,updated_at"


async def load_sync_sidecar_window(
    directus_service: Any,
    *,
    collection: str,
    chat_id: str,
    user_id: str,
    before_updated_at: int | None = None,
    before_id: str | None = None,
) -> dict[str, Any]:
    """Read one deterministic ciphertext page scoped to a checked chat and author."""
    if collection not in {"code_run_outputs", "notebook_run_outputs"}:
        raise ValueError("Unsupported sync sidecar collection")
    filters: dict[str, Any] = {
        "chat_id": {"_eq": chat_id},
        "author_user_id": {"_eq": user_id},
    }
    if before_updated_at is not None:
        if not before_id:
            raise ValueError("Sidecar continuation requires an id tie breaker")
        filters["_or"] = [
            {"updated_at": {"_lt": before_updated_at}},
            {"updated_at": {"_eq": before_updated_at}, "id": {"_lt": before_id}},
        ]
    rows = await directus_service.get_items(
        collection,
        params={
            "filter": filters,
            "fields": CODE_RUN_FIELDS if collection == "code_run_outputs" else NOTEBOOK_FIELDS,
            "sort": ["-updated_at", "-id"],
            "limit": SIDECAR_PAGE_LIMIT + 1,
        },
        admin_required=True,
        raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError(f"{collection} page unavailable")
    has_more_before = len(rows) > SIDECAR_PAGE_LIMIT
    rows = rows[:SIDECAR_PAGE_LIMIT]
    kept: list[dict[str, Any]] = []
    payload_bytes = 0
    oversized = None
    for row in rows:
        row_bytes = len(json.dumps(row, separators=(",", ":")).encode("utf-8"))
        if row_bytes > SIDECAR_PAGE_MAX_BYTES and not kept:
            oversized = {
                "id": row["id"],
                "updated_at": int(row["updated_at"]),
                "embed_id": row.get("embed_id") or row.get("notebook_embed_id"),
            }
            has_more_before = True
            break
        if payload_bytes + row_bytes > SIDECAR_PAGE_MAX_BYTES:
            has_more_before = True
            break
        kept.append(row)
        payload_bytes += row_bytes
    oldest = kept[-1] if kept else None
    return {
        "outputs": kept,
        "has_more_before": has_more_before,
        "start_cursor": {"updated_at": int(oldest["updated_at"]), "id": oldest["id"]} if oldest else None,
        "oversized_output": oversized,
        "payload_bytes": payload_bytes,
    }


async def load_sync_sidecars_for_chats(
    directus_service: Any,
    *,
    collection: str,
    chat_ids: list[str],
    user_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build bounded per-chat pages with explicit continuation for every chat."""
    outputs: list[dict[str, Any]] = []
    windows: dict[str, dict[str, Any]] = {}
    for chat_id in dict.fromkeys(chat_ids):
        page = await load_sync_sidecar_window(
            directus_service, collection=collection, chat_id=chat_id, user_id=user_id,
        )
        outputs.extend(page["outputs"])
        windows[chat_id] = {
            "has_more_before": page["has_more_before"],
            "start_cursor": page["start_cursor"],
            "oversized_output": page["oversized_output"],
        }
    return outputs, windows
