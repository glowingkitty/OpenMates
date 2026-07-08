# backend/shared/python_utils/chat_version_integrity.py
#
# Metadata-only integrity helpers for zero-knowledge chat history. The server can
# compare durable encrypted row counts with `chats.messages_v`, but it must never
# invent, decrypt, or rewrite private message content while repairing metadata
# drift from interrupted Apple/web storage flows.

from __future__ import annotations

from dataclasses import dataclass


class ChatVersionIntegrityError(ValueError):
    """Raised when chat version integrity input or repair intent is invalid."""


@dataclass(frozen=True)
class ChatVersionIntegrityIssue:
    chat_id: str
    stored_messages_v: int
    durable_message_count: int
    is_mismatch: bool
    reason: str


def assess_chat_version_integrity(
    *,
    chat_id: str,
    stored_messages_v: int | None,
    durable_message_count: int,
) -> ChatVersionIntegrityIssue:
    """Compare durable message rows with Directus chat metadata version state."""

    stored = int(stored_messages_v or 0)
    durable = int(durable_message_count)
    if stored < 0 or durable < 0:
        raise ChatVersionIntegrityError("messages_v and durable_message_count must be non-negative")

    if stored > durable:
        return ChatVersionIntegrityIssue(
            chat_id=chat_id,
            stored_messages_v=stored,
            durable_message_count=durable,
            is_mismatch=True,
            reason="messages_v_exceeds_durable_message_count",
        )

    if stored < durable:
        return ChatVersionIntegrityIssue(
            chat_id=chat_id,
            stored_messages_v=stored,
            durable_message_count=durable,
            is_mismatch=True,
            reason="messages_v_below_durable_message_count",
        )

    return ChatVersionIntegrityIssue(
        chat_id=chat_id,
        stored_messages_v=stored,
        durable_message_count=durable,
        is_mismatch=False,
        reason="ok",
    )


def repair_chat_version_fields(
    issue: ChatVersionIntegrityIssue,
    *,
    allow_repair: bool,
) -> dict[str, int]:
    """Return a safe Directus chat metadata patch for an explicit repair action."""

    if not issue.is_mismatch:
        return {}
    if not allow_repair:
        raise ChatVersionIntegrityError("chat version repair requires an explicit repair flag")
    return {"messages_v": issue.durable_message_count}
