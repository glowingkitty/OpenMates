# backend/tests/test_chat_version_integrity.py
#
# Durable Directus chat history is zero-knowledge encrypted client data. These
# tests guard the metadata-only integrity contract between `chats.messages_v`
# and stored `chat_messages` rows without requiring plaintext content, keys, or
# live Directus access.

from __future__ import annotations

import pytest

from backend.shared.python_utils.chat_version_integrity import (
    ChatVersionIntegrityError,
    assess_chat_version_integrity,
    repair_chat_version_fields,
)


def test_detects_messages_v_above_durable_message_count() -> None:
    issue = assess_chat_version_integrity(
        chat_id="chat-1",
        stored_messages_v=3,
        durable_message_count=0,
    )

    assert issue.is_mismatch is True
    assert issue.chat_id == "chat-1"
    assert issue.stored_messages_v == 3
    assert issue.durable_message_count == 0
    assert issue.reason == "messages_v_exceeds_durable_message_count"


def test_no_issue_when_messages_v_matches_durable_message_count() -> None:
    issue = assess_chat_version_integrity(
        chat_id="chat-1",
        stored_messages_v=2,
        durable_message_count=2,
    )

    assert issue.is_mismatch is False
    assert issue.reason == "ok"
    assert repair_chat_version_fields(issue, allow_repair=True) == {}


def test_repair_requires_explicit_allow_flag() -> None:
    issue = assess_chat_version_integrity(
        chat_id="chat-1",
        stored_messages_v=3,
        durable_message_count=0,
    )

    with pytest.raises(ChatVersionIntegrityError, match="explicit repair flag"):
        repair_chat_version_fields(issue, allow_repair=False)


def test_repair_aligns_only_metadata_to_durable_row_count() -> None:
    issue = assess_chat_version_integrity(
        chat_id="chat-1",
        stored_messages_v=3,
        durable_message_count=0,
    )

    repair_fields = repair_chat_version_fields(issue, allow_repair=True)

    assert repair_fields == {"messages_v": 0}
    assert "encrypted_content" not in repair_fields
    assert "content" not in repair_fields
    assert "message" not in repair_fields


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ChatVersionIntegrityError, match="non-negative"):
        assess_chat_version_integrity(
            chat_id="chat-1",
            stored_messages_v=-1,
            durable_message_count=0,
        )
