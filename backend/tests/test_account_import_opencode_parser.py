"""Account Import V1 OpenCode transcript parser contract tests.

The synthetic fixture mirrors the JSON emitted by `opencode export`. The parser
must retain visible user and assistant text while excluding private reasoning
and tool payloads from the imported chat transcript.
"""

from __future__ import annotations

import json

from backend.core.api.app.services.account_import_service import parse_opencode_export_bytes


def test_opencode_cli_transcript_export_normalizes_visible_messages() -> None:
    payload = json.dumps({
        "info": {
            "id": "ses_opencode_1",
            "title": "Synthetic OpenCode session",
            "time": {"created": 1785000000000, "updated": 1785000010000},
        },
        "messages": [
            {
                "info": {"id": "msg_user_1", "role": "user", "time": {"created": 1785000001000}},
                "parts": [
                    {"id": "part_user", "type": "text", "text": "Synthetic OpenCode user text."},
                    {"id": "part_file", "type": "file", "filename": "notes.txt", "mime": "text/plain", "url": "data:text/plain;base64,cHJpdmF0ZQ=="},
                ],
            },
            {
                "info": {"id": "msg_assistant_1", "role": "assistant", "time": {"created": 1785000002000}},
                "parts": [
                    {"id": "part_reasoning", "type": "reasoning", "text": "Private reasoning must not import."},
                    {"id": "part_assistant", "type": "text", "text": "Synthetic OpenCode assistant text."},
                    {"id": "part_tool", "type": "tool", "state": {"status": "completed", "output": "Tool output must not import."}},
                ],
            },
        ],
    }).encode("utf-8")

    chats = parse_opencode_export_bytes(payload, source_name="opencode-session.json")

    assert len(chats) == 1
    assert chats[0]["provider"] == "opencode"
    assert chats[0]["source_chat_id"] == "ses_opencode_1"
    assert chats[0]["title"] == "Synthetic OpenCode session"
    assert [message["role"] for message in chats[0]["messages"]] == ["user", "assistant"]
    assert [message["content"] for message in chats[0]["messages"]] == [
        "Synthetic OpenCode user text.",
        "Synthetic OpenCode assistant text.",
    ]
    assert chats[0]["uploads"] == []
    assert "cHJpdmF0ZQ==" not in json.dumps(chats)
    assert "Private reasoning must not import." not in json.dumps(chats)
    assert "Tool output must not import." not in json.dumps(chats)
