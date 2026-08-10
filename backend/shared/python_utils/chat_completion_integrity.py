# backend/shared/python_utils/chat_completion_integrity.py
#
# Metadata-only integrity helpers for completed AI turns. These checks correlate
# durable encrypted messages with cleartext billing metadata, but never inspect
# or reconstruct private message content. They are used by debug/audit tooling to
# catch turns where inference was billed but no assistant/system response row was
# persisted for the triggering user message.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


AI_APP_ID = "ai"
AI_ASK_SKILL_ID = "ask"
RESPONSE_ROLES = {"assistant", "system"}


@dataclass(frozen=True)
class MissingAssistantResponseIssue:
    chat_id: str
    user_message_id: str
    user_message_created_at: int
    usage_ids: tuple[str, ...]
    usage_created_at: tuple[int, ...]
    next_user_message_id: str | None
    reason: str = "ai_ask_usage_without_durable_assistant_response"


def _coerce_timestamp(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _message_identifiers(message: Mapping[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for key in ("id", "message_id", "client_message_id"):
        value = message.get(key)
        if value:
            identifiers.add(str(value))
    return identifiers


def _first_message_identifier(message: Mapping[str, Any] | None) -> str | None:
    if message is None:
        return None
    for key in ("id", "message_id", "client_message_id"):
        value = message.get(key)
        if value:
            return str(value)
    return None


def _is_ai_ask_usage(entry: Mapping[str, Any]) -> bool:
    return (
        entry.get("app_id") == AI_APP_ID
        and entry.get("skill_id") == AI_ASK_SKILL_ID
    )


def find_missing_assistant_responses_after_ai_usage(
    *,
    chat_id: str,
    messages: Sequence[Mapping[str, Any]],
    usage_entries: Sequence[Mapping[str, Any]],
) -> list[MissingAssistantResponseIssue]:
    """Find user turns with billed ai.ask usage but no following durable response.

    A response must be an assistant/system row after the user message and before
    the next user message. System rows count because rejection/limit responses are
    intentionally persisted as system messages, not assistant messages.
    """

    ask_usage_by_message_id: dict[str, list[Mapping[str, Any]]] = {}
    for entry in usage_entries:
        if not _is_ai_ask_usage(entry):
            continue
        message_id = entry.get("message_id")
        if not message_id:
            continue
        ask_usage_by_message_id.setdefault(str(message_id), []).append(entry)

    if not ask_usage_by_message_id:
        return []

    sortable_messages: list[tuple[int, int, Mapping[str, Any]]] = []
    for index, message in enumerate(messages):
        created_at = _coerce_timestamp(message.get("created_at"))
        if created_at is None:
            continue
        sortable_messages.append((created_at, index, message))
    sortable_messages.sort(key=lambda item: (item[0], item[1]))

    issues: list[MissingAssistantResponseIssue] = []
    for index, (created_at, _original_index, message) in enumerate(sortable_messages):
        if message.get("role") != "user":
            continue
        message_usage: list[Mapping[str, Any]] = []
        matched_message_ids: list[str] = []
        for message_identifier in sorted(_message_identifiers(message)):
            message_usage.extend(ask_usage_by_message_id.get(message_identifier, []))
            if message_identifier in ask_usage_by_message_id:
                matched_message_ids.append(message_identifier)
        if not message_usage:
            continue

        next_user_message: Mapping[str, Any] | None = None
        next_user_created_at: int | None = None
        for next_created_at, _next_original_index, next_message in sortable_messages[
            index + 1 :
        ]:
            if next_message.get("role") == "user":
                next_user_message = next_message
                next_user_created_at = next_created_at
                break

        has_response = False
        for response_created_at, _response_original_index, response in sortable_messages[
            index + 1 :
        ]:
            if next_user_created_at is not None and response_created_at >= next_user_created_at:
                break
            if response.get("role") in RESPONSE_ROLES:
                has_response = True
                break
        if has_response:
            continue

        usage_ids = tuple(str(entry.get("id")) for entry in message_usage if entry.get("id"))
        usage_created_at = tuple(
            timestamp
            for timestamp in (_coerce_timestamp(entry.get("created_at")) for entry in message_usage)
            if timestamp is not None
        )
        primary_message_id = (
            matched_message_ids[0]
            if matched_message_ids
            else (_first_message_identifier(message) or "unknown")
        )
        next_user_id = _first_message_identifier(next_user_message)
        issues.append(
            MissingAssistantResponseIssue(
                chat_id=chat_id,
                user_message_id=primary_message_id,
                user_message_created_at=created_at,
                usage_ids=usage_ids,
                usage_created_at=usage_created_at,
                next_user_message_id=next_user_id,
            )
        )

    return issues
