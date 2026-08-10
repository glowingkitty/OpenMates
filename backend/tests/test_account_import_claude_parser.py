"""Account Import V1 Claude parser contract tests.

These tests use synthetic, redacted Claude export payloads. They define the
normalization and fail-closed parser behavior before the backend implementation
exists, without committing private provider export content.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

import pytest

from backend.core.api.app.services.account_import_service import ImportParseError, parse_claude_export_bytes


def _claude_zip(conversations: list[dict]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._conversations.json", "ignored")
        archive.writestr(".DS_Store", "ignored")
        archive.writestr("users.json", json.dumps([{"uuid": "user-redacted"}]))
        archive.writestr("conversations.json", json.dumps(conversations))
    return buffer.getvalue()


def test_redacted_claude_zip_parses_into_normalized_chats_and_messages() -> None:
    payload = _claude_zip([
        {
            "uuid": "claude-chat-1",
            "name": "Redacted Claude Chat",
            "created_at": "2026-07-17T10:00:00Z",
            "updated_at": "2026-07-17T10:05:00Z",
            "account": {"uuid": "account-redacted"},
            "chat_messages": [
                {
                    "uuid": "msg-human-1",
                    "sender": "human",
                    "text": "Synthetic user request for import parser coverage.",
                    "content": [{"type": "text", "text": "Synthetic user request for import parser coverage."}],
                    "attachments": [{"file_name": "notes.txt", "file_type": "txt"}],
                    "files": [],
                    "created_at": "2026-07-17T10:00:00Z",
                },
                {
                    "uuid": "msg-assistant-1",
                    "sender": "assistant",
                    "text": "Synthetic assistant response.",
                    "content": [
                        {"type": "text", "text": "Synthetic assistant response."},
                        {"type": "tool_use", "name": "redacted_tool", "input": {"query": "redacted"}},
                        {"type": "tool_result", "content": "Synthetic tool result."},
                    ],
                    "attachments": [],
                    "files": [{"file_name": "diagram.png", "file_type": "png", "file_size": 1234}],
                    "created_at": "2026-07-17T10:05:00Z",
                },
            ],
        }
    ])

    chats = parse_claude_export_bytes(payload, source_name="claude-export-redacted.zip")

    assert len(chats) == 1
    chat = chats[0]
    assert chat["provider"] == "claude"
    assert chat["source_chat_id"] == "claude-chat-1"
    assert chat["title"] == "Redacted Claude Chat"
    assert chat["source_fingerprint"]
    assert chat["provider_labels"] == ["claude"]
    assert [message["role"] for message in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][0]["source_message_id"] == "msg-human-1"
    assert "Synthetic assistant response." in chat["messages"][1]["content"]
    assert chat["messages"][1]["provider_metadata"]["content_block_types"] == ["text", "tool_use", "tool_result"]
    assert chat["uploads"][0]["file_name"] == "notes.txt"


def test_claude_json_payload_without_zip_is_supported() -> None:
    payload = json.dumps([
        {
            "uuid": "claude-chat-json",
            "name": "JSON export",
            "chat_messages": [{"uuid": "msg-json", "sender": "human", "text": "Synthetic JSON message."}],
        }
    ]).encode("utf-8")

    chats = parse_claude_export_bytes(payload, source_name="conversations.json")

    assert len(chats) == 1
    assert chats[0]["source_chat_id"] == "claude-chat-json"
    assert chats[0]["messages"][0]["role"] == "user"


def test_malformed_claude_export_fails_before_scan_or_billing() -> None:
    with pytest.raises(ImportParseError, match="Claude export"):
        parse_claude_export_bytes(b"not json and not a zip", source_name="broken.txt")


def test_claude_source_fingerprint_is_stable_and_not_plaintext() -> None:
    conversation = {
        "uuid": "claude-chat-stable",
        "name": "Stable synthetic chat",
        "chat_messages": [{"uuid": "msg-stable", "sender": "human", "text": "Fingerprint input text."}],
    }

    first = parse_claude_export_bytes(_claude_zip([conversation]), source_name="one.zip")[0]
    second = parse_claude_export_bytes(_claude_zip([conversation]), source_name="two.zip")[0]

    assert first["source_fingerprint"] == second["source_fingerprint"]
    assert "Fingerprint input text" not in first["source_fingerprint"]
