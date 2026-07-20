"""Account Import V1 ChatGPT parser contract tests.

These tests use synthetic, redacted ChatGPT export payloads. They cover the
official export shape without committing private user export content.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

import pytest

from backend.core.api.app.services.account_import_service import ImportParseError, parse_chatgpt_export_bytes


def _chatgpt_conversation() -> dict:
    return {
        "id": "chatgpt-chat-1",
        "conversation_id": "chatgpt-conversation-1",
        "title": "Synthetic ChatGPT Chat",
        "create_time": 1_785_000_000.0,
        "update_time": 1_785_000_120.0,
        "current_node": "assistant-1",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None},
            "user-1": {
                "id": "user-1",
                "parent": "root",
                "message": {
                    "id": "message-user-1",
                    "author": {"role": "user"},
                    "create_time": 1_785_000_001.0,
                    "content": {
                        "content_type": "multimodal_text",
                        "parts": [
                            "Synthetic ChatGPT user text.",
                            {"asset_pointer": "file-service://redacted", "content_type": "image_asset_pointer"},
                        ],
                    },
                },
            },
            "assistant-1": {
                "id": "assistant-1",
                "parent": "user-1",
                "message": {
                    "id": "message-assistant-1",
                    "author": {"role": "assistant"},
                    "create_time": 1_785_000_020.0,
                    "content": {"content_type": "text", "parts": ["Synthetic ChatGPT assistant text."]},
                },
            },
            "unselected-branch": {
                "id": "unselected-branch",
                "parent": "user-1",
                "message": {
                    "id": "message-branch",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["This branch must not import."]},
                },
            },
        },
    }


def _chatgpt_zip(conversations: list[dict]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._conversations.json", "ignored")
        archive.writestr("ChatGPT Export/conversations.json", json.dumps(conversations))
        archive.writestr("ChatGPT Export/conversation_asset_file_names.json", json.dumps({"file_redacted.dat": "redacted.png"}))
    return buffer.getvalue()


def test_redacted_chatgpt_zip_parses_active_conversation_path() -> None:
    chats = parse_chatgpt_export_bytes(_chatgpt_zip([_chatgpt_conversation()]), source_name="chatgpt-export.zip")

    assert len(chats) == 1
    chat = chats[0]
    assert chat["provider"] == "chatgpt"
    assert chat["source_chat_id"] == "chatgpt-conversation-1"
    assert chat["title"] == "Synthetic ChatGPT Chat"
    assert chat["provider_labels"] == ["chatgpt"]
    assert [message["role"] for message in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][0]["content"] == "Synthetic ChatGPT user text."
    assert chat["messages"][0]["provider_metadata"] == {"content_type": "multimodal_text", "asset_count": 1}
    assert "This branch must not import" not in json.dumps(chat)
    assert chat["uploads"] == []


def test_chatgpt_json_payload_without_zip_is_supported() -> None:
    payload = json.dumps([_chatgpt_conversation()]).encode("utf-8")

    chats = parse_chatgpt_export_bytes(payload, source_name="conversations.json")

    assert chats[0]["messages"][1]["source_message_id"] == "message-assistant-1"
    assert chats[0]["created_at"].endswith("Z")


def test_malformed_chatgpt_export_fails_before_scan_or_billing() -> None:
    with pytest.raises(ImportParseError, match="ChatGPT export"):
        parse_chatgpt_export_bytes(b"not json and not a zip", source_name="broken.txt")


def test_chatgpt_source_fingerprint_is_stable_and_not_plaintext() -> None:
    conversation = _chatgpt_conversation()

    first = parse_chatgpt_export_bytes(_chatgpt_zip([conversation]), source_name="one.zip")[0]
    second = parse_chatgpt_export_bytes(_chatgpt_zip([conversation]), source_name="two.zip")[0]

    assert first["source_fingerprint"] == second["source_fingerprint"]
    assert "Synthetic" not in first["source_fingerprint"]
