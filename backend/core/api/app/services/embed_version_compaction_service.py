"""Metadata-only compaction of old unnamed session versions (live-collab.versions.named-snapshots).

Session versions older than 30 days collapse to one per embed per UTC day: the
last row of the day stays visible, the others get ``compacted_at`` and the
timeline hides them. Ciphertext is never read, changed or deleted, because
version previews rebuild earlier content from the stored snapshot/patch chain
and archive copy/prune jobs track the same rows. Named and commit versions,
assistant and restore versions, and rows that are already compacted are never
selected.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Iterable

logger = logging.getLogger(__name__)

COMPACTION_AGE_SECONDS = 30 * 24 * 3600
SECONDS_PER_DAY = 24 * 3600
SCAN_LIMIT = 500


def effective_kind(row: dict[str, Any]) -> str:
    """Stored kind, else the legacy rule (assistant origin, restore action, other user edits are sessions)."""
    stored = row.get("version_kind")
    if stored:
        return str(stored)
    if (row.get("revision_origin") or "assistant") != "user":
        return "assistant"
    return "restore" if row.get("revision_action") == "restore" else "session"


def plan_session_compaction(rows: Iterable[dict[str, Any]], *, now: int) -> list[dict[str, Any]]:
    """Rows to mark compacted: every eligible session row except the last of its embed and UTC day.

    A row is eligible when it is an unnamed, uncompacted ``session`` version
    older than 30 days. The kept row of a day is the highest version number
    among the eligible rows of that day. Pure function; reads metadata only.
    """
    cutoff = now - COMPACTION_AGE_SECONDS
    days: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        created_at = row.get("created_at")
        if not isinstance(created_at, int) or created_at <= 0 or created_at >= cutoff:
            continue
        if row.get("compacted_at") is not None or row.get("encrypted_version_name"):
            continue
        if effective_kind(row) != "session":
            continue
        days[(str(row["embed_id"]), created_at // SECONDS_PER_DAY)].append(row)
    doomed: list[dict[str, Any]] = []
    for group in days.values():
        keep = max(group, key=lambda item: int(item["version_number"]))
        doomed.extend(item for item in group if item is not keep)
    return sorted(doomed, key=lambda item: (str(item["embed_id"]), int(item["version_number"])))


async def compact_session_versions(directus_service: Any, *, now: int | None = None) -> dict[str, int]:
    """Scan one bounded batch of old user versions and mark the planned rows compacted."""
    timestamp = int(time.time()) if now is None else now
    cutoff = timestamp - COMPACTION_AGE_SECONDS
    rows = await directus_service.get_items(
        "embed_diffs",
        params={
            "filter": {
                "revision_origin": {"_eq": "user"},
                "created_at": {"_lt": cutoff},
                "compacted_at": {"_null": True},
            },
            "fields": "id,embed_id,version_number,created_at,revision_origin,revision_action,"
                      "version_kind,encrypted_version_name,compacted_at",
            "sort": ["embed_id", "version_number"],
            "limit": SCAN_LIMIT,
        },
        no_cache=True, admin_required=True, raise_on_error=True,
    ) or []
    planned = plan_session_compaction(rows, now=timestamp)
    marked = 0
    for row in planned:
        if await directus_service.update_item(
            "embed_diffs", row["id"], {"compacted_at": timestamp}, admin_required=True,
        ):
            marked += 1
        else:
            logger.error("Embed version %s v%s was not marked compacted", str(row["embed_id"])[:8], row["version_number"])
    return {"scanned": len(rows), "planned": len(planned), "marked": marked}
