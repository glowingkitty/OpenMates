# backend/core/api/app/routes/handlers/websocket_handlers/sync_message_hydration.py
#
# Shared message hydration for websocket phased sync and REST offline sync.
# Redis sync-message lists are performance caches only; Directus remains the
# authoritative durable source for encrypted chat messages. This helper keeps
# cold-boot clients from accepting incomplete cache entries as complete history.

import logging
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)


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
    """Load encrypted sync messages, falling back when Redis is missing rows."""

    _otel_span, _otel_token = _start_ws_span(
        "sync_message_hydration",
        user_id,
        {"chat_id": chat_id},
        user_otel_attrs,
    )

    try:
        cached_messages: List[str] = []
        try:
            cached_messages = await cache_service.get_sync_messages_history(user_id, chat_id) or []
        except Exception as exc:
            logger.warning(f"{log_prefix}: Failed to read sync cache for {chat_id}: {exc}")

        directus_count = None
        if cached_messages:
            try:
                directus_count = await directus_service.chat.get_message_count_for_chat(chat_id)
            except Exception as exc:
                logger.warning(f"{log_prefix}: Failed to count Directus messages for {chat_id}: {exc}")

            if directus_count is None or len(cached_messages) >= directus_count:
                return cached_messages, directus_count if directus_count is not None else len(cached_messages)

            logger.warning(
                f"{log_prefix}: Sync cache incomplete for {chat_id}: "
                f"cached={len(cached_messages)}, directus={directus_count}. Fetching Directus messages."
            )

        try:
            messages = await directus_service.chat.get_all_messages_for_chat(
                chat_id=chat_id,
                decrypt_content=False,
            ) or []
        except Exception as exc:
            logger.warning(f"{log_prefix}: Failed to fetch messages for {chat_id}: {exc}")
            messages = []

        return messages, len(messages)
    finally:
        _end_ws_span(_otel_span, _otel_token)
