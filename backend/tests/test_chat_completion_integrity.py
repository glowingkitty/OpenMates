"""
Regression tests for metadata-only chat completion integrity checks.

The debug audit should flag completed/billed ai.ask turns that never produced a
durable assistant or system message, without needing to decrypt private content.
"""

from backend.shared.python_utils.chat_completion_integrity import (
    find_missing_assistant_responses_after_ai_usage,
)


def test_flags_ai_ask_usage_without_following_assistant_response() -> None:
    issues = find_missing_assistant_responses_after_ai_usage(
        chat_id="chat-123",
        messages=[
            {"id": "user-1", "role": "user", "created_at": 100},
            {"id": "assistant-1", "role": "assistant", "created_at": 110},
            {"id": "user-2", "role": "user", "created_at": 200},
        ],
        usage_entries=[
            {"id": "usage-1", "app_id": "ai", "skill_id": "ask", "message_id": "user-1", "created_at": 111},
            {"id": "usage-2", "app_id": "ai", "skill_id": "ask", "message_id": "user-2", "created_at": 210},
            {"id": "usage-3", "app_id": "pdf", "skill_id": "read", "message_id": "user-2", "created_at": 205},
        ],
    )

    assert len(issues) == 1
    assert issues[0].chat_id == "chat-123"
    assert issues[0].user_message_id == "user-2"
    assert issues[0].usage_ids == ("usage-2",)
    assert issues[0].reason == "ai_ask_usage_without_durable_assistant_response"


def test_later_response_after_next_user_does_not_satisfy_missing_turn() -> None:
    issues = find_missing_assistant_responses_after_ai_usage(
        chat_id="chat-123",
        messages=[
            {"id": "user-1", "role": "user", "created_at": 100},
            {"id": "user-2", "role": "user", "created_at": 200},
            {"id": "assistant-2", "role": "assistant", "created_at": 210},
        ],
        usage_entries=[
            {"id": "usage-1", "app_id": "ai", "skill_id": "ask", "message_id": "user-1", "created_at": 105},
            {"id": "usage-2", "app_id": "ai", "skill_id": "ask", "message_id": "user-2", "created_at": 205},
        ],
    )

    assert [issue.user_message_id for issue in issues] == ["user-1"]
    assert issues[0].next_user_message_id == "user-2"


def test_system_response_counts_as_terminal_response() -> None:
    issues = find_missing_assistant_responses_after_ai_usage(
        chat_id="chat-123",
        messages=[
            {"id": "user-1", "role": "user", "created_at": 100},
            {"id": "system-1", "role": "system", "created_at": 105},
        ],
        usage_entries=[
            {"id": "usage-1", "app_id": "ai", "skill_id": "ask", "message_id": "user-1", "created_at": 104},
        ],
    )

    assert issues == []
