"""Rebuild a Focus continuation from its exact admitted user turn."""

import json
from datetime import datetime, timezone
from typing import Any

from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key


class FocusContinuationHistoryError(Exception):
    """A stale or incomplete source turn must never be replayed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def source_user_message_id(pending_context: dict[str, Any]) -> str:
    source_id = pending_context.get("agentic_context_turn_id") or pending_context.get("message_id")
    if not isinstance(source_id, str) or not source_id:
        raise FocusContinuationHistoryError("missing_source_turn")
    return source_id


def _row_ids(row: dict[str, Any]) -> set[str]:
    return {
        value for key in ("id", "message_id", "client_message_id", "clientMessageId")
        if isinstance(value := row.get(key), str) and value
    }


def _is_activation_message(content: str) -> bool:
    return '"type":"focus_mode_activation"' in content or '"type": "focus_mode_activation"' in content


def _decoded_rows(cached: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for serialized in cached:
        try:
            row = json.loads(serialized)
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


async def current_focus_source_turn(cache_service: Any, pending_context: dict[str, Any]) -> bool:
    """Check both cached user order and the latest-turn key before dispatch."""
    try:
        source_id = source_user_message_id(pending_context)
    except FocusContinuationHistoryError:
        return False
    user_id = pending_context.get("user_id")
    chat_id = pending_context.get("chat_id")
    if not isinstance(user_id, str) or not user_id or not isinstance(chat_id, str) or not chat_id:
        return False
    rows = _decoded_rows(await cache_service.get_ai_messages_history(user_id, chat_id))
    matching = [index for index, row in enumerate(rows) if source_id in _row_ids(row)]
    if len(matching) != 1 or rows[matching[0]].get("role") != "user":
        return False
    if any(row.get("role") == "user" for row in rows[:matching[0]]):
        return False
    return await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id)) == source_id


async def rebuild_focus_continuation_history(
    *, cache_service: Any, encryption_service: Any, pending_context: dict[str, Any],
    user_vault_key_id: str,
) -> list[dict[str, Any]]:
    user_id = pending_context.get("user_id")
    chat_id = pending_context.get("chat_id")
    source_id = source_user_message_id(pending_context)
    if not isinstance(user_id, str) or not user_id or not isinstance(chat_id, str) or not chat_id:
        raise FocusContinuationHistoryError("missing_source_turn")
    latest = await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id))
    if latest != source_id:
        raise FocusContinuationHistoryError("stale_source_turn")
    cached = await cache_service.get_ai_messages_history(user_id, chat_id)
    rows = _decoded_rows(cached)
    matching = [index for index, row in enumerate(rows) if source_id in _row_ids(row)]
    if len(matching) != 1:
        raise FocusContinuationHistoryError("ambiguous_source_turn" if matching else "missing_source_turn")
    source_index = matching[0]
    if rows[source_index].get("role") != "user":
        raise FocusContinuationHistoryError("invalid_source_turn")
    if any(row.get("role") == "user" for row in rows[:source_index]):
        raise FocusContinuationHistoryError("stale_source_turn")

    # AI cache is newest first. Discard only rows newer than the exact source,
    # including provisional assistant/control output from this pending turn.
    history: list[dict[str, Any]] = []
    for row in reversed(rows[source_index:]):
        role = row.get("role")
        if role not in ("user", "assistant", "system"):
            continue
        encrypted = row.get("encrypted_content")
        if not isinstance(encrypted, str) or not encrypted:
            if row is rows[source_index]:
                raise FocusContinuationHistoryError("invalid_source_turn")
            continue
        try:
            content = await encryption_service.decrypt_with_user_key(encrypted, user_vault_key_id)
        except Exception as exc:
            if row is rows[source_index]:
                raise FocusContinuationHistoryError("invalid_source_turn") from exc
            continue
        if not isinstance(content, str) or not content:
            if row is rows[source_index]:
                raise FocusContinuationHistoryError("invalid_source_turn")
            continue
        if role == "assistant" and _is_activation_message(content):
            continue
        history.append({
            "role": role,
            "content": content,
            "created_at": row.get("created_at", int(datetime.now(timezone.utc).timestamp())),
            "sender_name": row.get("sender_name", role),
            "category": row.get("category"),
        })
    if not history or history[-1]["role"] != "user":
        raise FocusContinuationHistoryError("invalid_source_turn")
    if not await current_focus_source_turn(cache_service, pending_context):
        raise FocusContinuationHistoryError("stale_source_turn")
    return history


async def publish_current_focus_continuation_failure(
    cache_service: Any, pending_context: dict[str, Any],
) -> bool:
    """Send a fixed owner-scoped terminal error only for the still-current turn."""
    try:
        source_id = source_user_message_id(pending_context)
    except FocusContinuationHistoryError:
        return False
    user_id = pending_context.get("user_id")
    chat_id = pending_context.get("chat_id")
    if not isinstance(user_id, str) or not user_id or not isinstance(chat_id, str) or not chat_id:
        return False
    cached = await cache_service.get_ai_messages_history(user_id, chat_id)
    rows = _decoded_rows(cached)
    matching = [index for index, row in enumerate(rows) if source_id in _row_ids(row)]
    if matching and any(row.get("role") == "user" for row in rows[:matching[0]]):
        return False
    if await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id)) != source_id:
        return False
    published = await cache_service.publish_event(f"user_cache_events:{user_id}", {
        "event_type": "focus_mode_continuation_failed",
        "payload": {
            "chat_id": chat_id,
            "user_message_id": source_id,
        },
    })
    return bool(published)
