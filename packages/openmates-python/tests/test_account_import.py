"""Account Import V1 Python SDK contract tests.

Purpose: verify pip SDK helpers mirror the CLI-green Account Import V1 contract.
Architecture: docs/specs/account-import-v1/spec.yml.
Security: tests monkeypatch requests and assert encrypted persistence payloads do
not contain raw synthetic import plaintext.
Run: python3 -m pytest packages/openmates-python/tests/test_account_import.py
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from openmates import OpenMates
from openmates import sdk as sdk_module


def wrap_master_key(api_key: str, master_key: bytes) -> dict[str, str]:
    salt = b"\x01" * 16
    iv = b"\x02" * 12
    wrapping_key = sdk_module._derive_api_key_wrapping_key(api_key, base64.b64encode(salt).decode("utf-8"))
    encrypted = AESGCM(wrapping_key).encrypt(iv, master_key, None)
    return {
        "encrypted_key": base64.b64encode(encrypted).decode("utf-8"),
        "salt": base64.b64encode(salt).decode("utf-8"),
        "key_iv": base64.b64encode(iv).decode("utf-8"),
    }


def test_account_import_parses_openmates_v1_archive():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("manifest.yml", "format: openmates-account-export\nversion: 1\ndomains:\n  chats:\n    count: 1\n  projects:\n    count: 1\n")
        zipped.writestr("chats/chat-1.yml", "id: chat-1\ntitle: Synthetic chat\n")

    client = OpenMates(api_key="sk-api-test")
    parsed = client.account.parse_openmates_import(archive.getvalue())

    assert parsed["source"] == "openmates"
    assert parsed["chats"][0]["source_chat_id"] == "chat-1"
    assert parsed["skipped_domains"] == ["projects"]


def test_account_import_parses_chatgpt_official_export():
    client = OpenMates(api_key="sk-api-test")
    parsed = client.account.parse_chatgpt_import(json.dumps([
        {
            "id": "chatgpt-chat-1",
            "conversation_id": "chatgpt-conversation-1",
            "title": "Synthetic ChatGPT SDK chat",
            "current_node": "assistant-1",
            "mapping": {
                "root": {"id": "root", "message": None, "parent": None},
                "user-1": {
                    "id": "user-1",
                    "parent": "root",
                    "message": {
                        "id": "message-user-1",
                        "author": {"role": "user"},
                        "content": {
                            "content_type": "multimodal_text",
                            "parts": ["Synthetic ChatGPT SDK user text.", {"asset_pointer": "file-service://redacted"}],
                        },
                    },
                },
                "assistant-1": {
                    "id": "assistant-1",
                    "parent": "user-1",
                    "message": {
                        "id": "message-assistant-1",
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": ["Synthetic ChatGPT SDK assistant text."]},
                    },
                },
            },
        }
    ]).encode("utf-8"))

    assert parsed["source"] == "chatgpt"
    assert parsed["chats"][0]["provider"] == "chatgpt"
    assert [message["role"] for message in parsed["chats"][0]["messages"]] == ["user", "assistant"]
    assert parsed["chats"][0]["messages"][0]["provider_metadata"] == {"content_type": "multimodal_text", "asset_count": 1}
    assert "Synthetic" not in parsed["chats"][0]["source_fingerprint"]


def test_account_import_sdk_encrypts_and_uses_shared_endpoints(monkeypatch):
    api_key = "sk-api-test-import"
    requests_seen: list[tuple[str, str, dict[str, Any] | None]] = []
    wrapper = wrap_master_key(api_key, b"\x00" * 32)

    class FakeResponse:
        status_code = 200

        def __init__(self, payload: dict[str, Any]):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url, json))
        if url.endswith("/v1/account-imports/preview"):
            return FakeResponse({"import_id": "import-1", "default_selection_count": 1, "max_batch_count": 1, "can_import": True})
        if url.endswith("/v1/account-imports/import-1/scan"):
            return FakeResponse({"chats": json["chats"], "credits_reserved": 1, "messages_blocked": [], "failures": []})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": wrapper})
        if url.endswith("/v1/account-imports/import-1/persist-encrypted"):
            return FakeResponse({"status": "complete", "imported_chat_ids": ["chat-imported-1"], "encrypted_record_counts": {"chats": 1, "messages": 1}, "failures": []})
        if url.endswith("/v1/account-imports/import-1/complete"):
            return FakeResponse({"status": "complete", "imported_count": 1, "failures": []})
        return FakeResponse({"ok": True})

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    parsed = client.account.parse_claude_import(json.dumps([
        {"uuid": "chat-1", "name": "SDK import", "chat_messages": [{"uuid": "msg-1", "sender": "human", "text": "SDK plaintext message"}]}
    ]).encode("utf-8"))
    result = client.account.import_chats(parsed)

    assert result["complete"]["status"] == "complete"
    assert requests_seen[0] == ("POST", "https://api.openmates.org/v1/account-imports/preview", {"source": "claude", "chat_count": 1, "source_fingerprints": [parsed["chats"][0]["source_fingerprint"]], "estimated_tokens": 0, "estimated_bytes": 0})
    assert [request[1] for request in requests_seen] == [
        "https://api.openmates.org/v1/account-imports/preview",
        "https://api.openmates.org/v1/account-imports/import-1/scan",
        "https://api.openmates.org/v1/sdk/session",
        "https://api.openmates.org/v1/account-imports/import-1/persist-encrypted",
        "https://api.openmates.org/v1/account-imports/import-1/complete",
    ]
    persisted = requests_seen[3][2]
    assert persisted is not None
    encrypted_chat = persisted["chats"][0]
    assert isinstance(encrypted_chat["encrypted_title"], str)
    assert "SDK import" not in encrypted_chat["encrypted_title"]
    encrypted_message = encrypted_chat["messages"][0]
    assert isinstance(encrypted_message["encrypted_content"], str)
    assert "SDK plaintext message" not in encrypted_message["encrypted_content"]
