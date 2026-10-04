# backend/core/api/app/routes/handlers/websocket_handlers/sync_message_hydration.py
#
# Shared message hydration for websocket phased sync and REST offline sync.
# Redis sync-message lists are performance caches only; Directus remains the
# authoritative durable source for encrypted chat messages. This helper keeps
# cold-boot clients from accepting incomplete cache entries as complete history.

import logging
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)

# A sync frame carries one recent display window. Older encrypted messages are
# available through the authenticated cursor window endpoint when requested.
SYNC_MESSAGE_PAGE_LIMIT = 20
SYNC_MESSAGE_PAGE_MAX_BYTES = 256 * 1024


def _start_ws_span(event_type: str, user_id: str, payload: dict[str, Any] | None, user_otel_attrs: dict | None):
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

        return start_ws_handler_span(event_type, user_id, payload, user_otel_attrs)
    except Exception:
        return None, None


def _end_ws_span(otel_span: Any, otel_token: Any) -> None:
    if otel_span is None:
        return
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

        end_ws_handler_span(otel_span, otel_token)
    except Exception:
        pass


async def load_sync_messages_with_directus_fallback(
    *,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    chat_id: str,
    log_prefix: str,
    user_otel_attrs: dict | None = None,
) -> Tuple[List[str], int]:
    """Compatibility wrapper for callers migrating to explicit window metadata."""

    window = await load_bounded_sync_message_window(
        cache_service=cache_service,
        directus_service=directus_service,
        user_id=user_id,
        chat_id=chat_id,
        log_prefix=log_prefix,
        user_otel_attrs=user_otel_attrs,
    )
    return window["messages"], window["server_message_count"]


async def load_bounded_sync_message_window(
    *,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    chat_id: str,
    log_prefix: str,
    user_otel_attrs: dict | None = None,
    before_timestamp: int | None = None,
    before_message_id: str | None = None,
    archive_service: Any | None = None,
) -> dict[str, Any]:
    """Read a bounded latest ciphertext window and an independent durable count.

    Redis sync lists are intentionally not read here: a cache entry may contain
    an entire long transcript and cannot be used as a bounded DB fallback.
    """

    _otel_span, _otel_token = _start_ws_span(
        "sync_message_hydration",
        user_id,
        {"chat_id": chat_id},
        user_otel_attrs,
    )

    try:
        window = await directus_service.chat.get_message_window_for_chat(
            chat_id=chat_id,
            direction="before" if before_timestamp is not None else "latest",
            limit=SYNC_MESSAGE_PAGE_LIMIT,
            before_timestamp=before_timestamp,
            before_message_id=before_message_id,
        )
        breakdown_method = getattr(directus_service.chat, "get_message_count_breakdown_for_chat", None)
        if breakdown_method is not None:
            breakdown = await breakdown_method(chat_id)
            if breakdown is None:
                raise RuntimeError(f"{log_prefix}: Directus message count unavailable for {chat_id}")
            hot_count, archived_count = breakdown
            count = hot_count + archived_count
        else:
            archived_count = 0
            count = await directus_service.chat.get_message_count_for_chat(chat_id)
        if count is None:
            raise RuntimeError(f"{log_prefix}: Directus message count unavailable for {chat_id}")

        if archived_count > 0:
            if archive_service is None:
                raise RuntimeError(f"{log_prefix}: archive reader unavailable for {chat_id}")
            window = await archive_service.merge_window(
                chat_id=chat_id,
                hot=window,
                direction="before" if before_timestamp is not None else "latest",
                limit=SYNC_MESSAGE_PAGE_LIMIT,
                before=(before_timestamp, before_message_id) if before_timestamp is not None and before_message_id else None,
            )

        import json

        messages = [
            message if isinstance(message, str) else json.dumps(message)
            for message in (window.get("messages") or [])
        ]
        kept_reversed: List[str] = []
        total_bytes = 0
        oversized_message = False
        oversized_message_cursor = None
        for message in reversed(messages):
            message_bytes = len(message.encode("utf-8"))
            if message_bytes > SYNC_MESSAGE_PAGE_MAX_BYTES and not kept_reversed:
                oversized_message = True
                oversized_row = json.loads(message)
                oversized_message_cursor = {
                    "created_at": int(oversized_row["created_at"]),
                    "message_id": oversized_row.get("message_id") or oversized_row.get("client_message_id") or oversized_row["id"],
                }
                break
            if total_bytes + message_bytes > SYNC_MESSAGE_PAGE_MAX_BYTES:
                break
            kept_reversed.append(message)
            total_bytes += message_bytes
        kept = list(reversed(kept_reversed))
        has_more_before = (
            bool(window.get("has_more_before"))
            or len(kept) < len(messages)
            or (before_timestamp is None and count > len(messages))
        )
        start_cursor = window.get("start_cursor") if len(kept) == len(messages) else None
        if kept and len(kept) < len(messages):
            # The first retained row is already normalized JSON from the window.
            first = json.loads(kept[0])
            start_cursor = {
                "created_at": int(first["created_at"]),
                "message_id": first.get("message_id") or first.get("client_message_id") or first["id"],
            }
        if oversized_message:
            logger.warning("%s: newest message exceeds sync page byte budget for %s", log_prefix, chat_id)
        return {
            "messages": kept,
            "server_message_count": count,
            "has_more_before": has_more_before,
            "start_cursor": start_cursor,
            "has_more_after": bool(window.get("has_more_after")),
            "end_cursor": window.get("end_cursor"),
            "oversized_message": oversized_message,
            "oversized_message_cursor": oversized_message_cursor,
            "payload_bytes": total_bytes,
            "storage_tier": window.get("storage_tier", "hot"),
        }
    finally:
        _end_ws_span(_otel_span, _otel_token)
