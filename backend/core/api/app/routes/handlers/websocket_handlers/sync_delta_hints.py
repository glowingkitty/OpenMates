"""Delta-sync skip decisions for phased sync: client embed hints and Phase 2 versions.

Clients report what they already hold so startup sync can avoid resending it.
These helpers decide, per row, whether that hint is safe to honour and record a
reason so the skip rate is visible in one log line per phase.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Collection, Dict, List, Optional

# Only a finished embed is stable enough to skip on a client hint; processing,
# rendering and needs_rerender rows can still change (embed_status.py).
FINAL_EMBED_STATUS = "finished"
FAILED_EMBED_STATUSES = ("error", "cancelled")


def client_final_embed_hint(
    embed: Dict[str, Any], client_embed_ids: Optional[Collection[str]],
) -> Optional[str]:
    """Return why a client-held embed may be skipped, or None to send it.

    Web clients report ``embed_id``; the TypeScript CLI reports the Directus row
    ``id``. Either hint suppresses only a finished embed.
    """
    if not client_embed_ids or embed.get("status") != FINAL_EMBED_STATUS:
        return None
    if embed.get("embed_id") in client_embed_ids:
        return "client_embed_id"
    row_id = embed.get("id")
    if row_id and row_id in client_embed_ids:
        return "client_row_id"
    return None


def select_sync_embeds(
    raw_embeds: Optional[List[Dict[str, Any]]],
    *,
    seen_embed_ids: set,
    sent_embed_ids: set,
    client_embed_ids: Optional[Collection[str]],
    skip_reasons: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Pick embeds to send, deduplicating across chats/phases and client hints."""
    selected: List[Dict[str, Any]] = []
    for embed in raw_embeds or []:
        embed_id = embed.get("embed_id")
        if not embed_id:
            continue
        if embed_id in seen_embed_ids or embed_id in sent_embed_ids:
            reason: Optional[str] = "already_sent"
        elif embed.get("status") in FAILED_EMBED_STATUSES:
            reason = "terminal_failure"
        else:
            reason = client_final_embed_hint(embed, client_embed_ids)
        if reason:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        selected.append(embed)
        seen_embed_ids.add(embed_id)
        sent_embed_ids.add(embed_id)
    return selected


def directus_chat_versions(chat_details: Dict[str, Any]) -> SimpleNamespace:
    """Version counters from a scoped Directus chat row, shaped like Redis versions."""

    def as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    return SimpleNamespace(
        title_v=as_int(chat_details.get("title_v")),
        metadata_v=chat_details.get("metadata_v"),
        messages_v=as_int(chat_details.get("messages_v")),
    )


def phase2_delta_reason(
    chat_details: Dict[str, Any],
    client_versions: Dict[str, Any],
    redis_versions: Any,
    *,
    refresh: bool,
    on_client: bool,
    is_current: Callable[[Dict[str, Any], Any, Dict[str, Any]], bool],
) -> str:
    """Classify one Phase 2 chat; reasons starting with ``skipped_`` are not sent.

    A cold Redis version entry falls back to the scoped Directus row, which
    carries the same title/metadata/messages counters.
    """
    if refresh:
        return "sent_refresh"
    if not on_client:
        return "sent_new"
    source = "redis" if redis_versions else "directus"
    server_versions = redis_versions or directus_chat_versions(chat_details)
    if is_current(client_versions, server_versions, chat_details):
        return f"skipped_current_{source}"
    return "sent_stale"


def format_skip_reasons(reasons: Dict[str, int]) -> str:
    return ",".join(f"{reason}={count}" for reason, count in sorted(reasons.items())) or "none"
