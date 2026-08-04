"""Account Import V1 Python SDK contract tests.

Purpose: verify pip SDK helpers mirror the CLI-green Account Import V1 contract.
Architecture: docs/specs/account-import-v1/spec.yml.
Security: tests monkeypatch requests and assert encrypted persistence payloads do
not contain raw synthetic import plaintext.
Run: python3 -m pytest packages/openmates-python/tests/test_account_import.py
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from typing import Any
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from openmates import OpenMates, OpenMatesConfigError
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


def encrypted_openmates_export_zip(password: str) -> bytes:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("manifest.yml", "format: openmates-account-export\nversion: 1\ndomains:\n  chats: included\n")
        zipped.writestr("chats/chat-password.yml", "id: chat-password\ntitle: Password chat\n")
    salt = b"\x03" * 16
    iv = b"\x04" * 12
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    ciphertext_with_tag = AESGCM(key).encrypt(iv, archive_buffer.getvalue(), None)
    header = json.dumps({
        "magic": "OMZIP1",
        "version": 1,
        "kdf": "scrypt",
        "cipher": "aes-256-gcm",
        "salt": base64.b64encode(salt).decode("utf-8"),
        "iv": base64.b64encode(iv).decode("utf-8"),
        "tag": base64.b64encode(ciphertext_with_tag[-16:]).decode("utf-8"),
    }).encode("utf-8")
    return b"OMZIP1\n" + str(len(header)).encode("utf-8") + b"\n" + header + ciphertext_with_tag[:-16]


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


def test_account_import_parses_password_protected_openmates_export():
    payload = encrypted_openmates_export_zip("correct horse battery staple")
    client = OpenMates(api_key="sk-api-test")

    try:
        client.account.parse_openmates_import(payload)
        raise AssertionError("missing password should fail")
    except OpenMatesConfigError as exc:
        assert "requires a password" in str(exc)

    try:
        client.account.parse_openmates_import(payload, password="wrong")
        raise AssertionError("wrong password should fail")
    except OpenMatesConfigError as exc:
        assert "could not be decrypted" in str(exc)

    parsed = client.account.parse_openmates_import(payload, password="correct horse battery staple")
    assert parsed["source"] == "openmates"
    assert parsed["chats"][0]["source_chat_id"] == "chat-password"


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


def test_account_import_parses_opencode_cli_transcript_export():
    client = OpenMates(api_key="sk-api-test")
    parsed = client.account.parse_opencode_import(json.dumps({
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
    }))

    assert parsed["source"] == "opencode"
    assert parsed["chats"][0]["provider"] == "opencode"
    assert [message["content"] for message in parsed["chats"][0]["messages"]] == [
        "Synthetic OpenCode user text.",
        "Synthetic OpenCode assistant text.",
    ]
    assert "Private reasoning must not import." not in json.dumps(parsed)
    assert "Tool output must not import." not in json.dumps(parsed)
    assert "cHJpdmF0ZQ==" not in json.dumps(parsed)


def test_account_import_parses_strict_generic_transcript_with_selected_identity():
    client = OpenMates(api_key="sk-api-test")
    parsed = client.account.parse_generic_import(json.dumps({
        "messages": [
            {"role": "user", "content": "Synthetic generic user text."},
            {"role": "assistant", "content": "Synthetic generic assistant text."},
        ]
    }), source="other")

    assert parsed["source"] == "other"
    assert parsed["parser_format"] == "generic"
    assert parsed["chats"][0]["messages"][0]["imported_assistant_identity"] is None
    assert parsed["chats"][0]["messages"][1]["imported_assistant_identity"] == {
        "category": "other",
        "sender_name": "AI assistant",
        "model_name": "Other",
        "avatar_key": "ai-star",
    }
    for malformed in ({"messages": [{"author": "user", "text": "ambiguous"}]}, {"conversations": []}):
        try:
            client.account.parse_generic_import(json.dumps(malformed), source="gemini")
            raise AssertionError("ambiguous generic transcript should fail")
        except OpenMatesConfigError as exc:
            assert "role/content" in str(exc)


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
        if url.endswith("/v1/account-imports/import-1/confirm"):
            return FakeResponse({"status": "confirmed"})
        if url.endswith("/v1/account-imports/import-1/scan"):
            return FakeResponse({"batch_id": "scan-0", "sequence": 0, "status": "acknowledged", "chats": json["chats"], "failures": []})
        if url.endswith("/v1/account-imports/import-1/compress"):
            return FakeResponse({"batch_id": "compress-0", "sequence": 0, "status": "acknowledged", "final_batch": True, "usage": {}})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": wrapper})
        if url.endswith("/v1/account-imports/import-1/persist-encrypted"):
            return FakeResponse({"status": "complete", "imported_chat_ids": ["chat-imported-1"], "encrypted_record_counts": {"chats": 1, "messages": 1}, "failures": []})
        if url.endswith("/v1/account-imports/import-1/complete"):
            return FakeResponse({"status": "complete", "imported_count": 1, "failures": []})
        return FakeResponse({"ok": True})

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url, None))
        return FakeResponse({"status": "processing", "last_scan_sequence": 0, "last_compression_sequence": -1})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key=api_key)
    parsed = client.account.parse_claude_import(json.dumps([
        {"uuid": "chat-1", "name": "SDK import", "chat_messages": [{"uuid": "msg-1", "sender": "human", "text": "SDK plaintext message"}]}
    ]).encode("utf-8"))
    result = client.account.import_chats(parsed)

    assert result["complete"]["status"] == "complete"
    expected_tokens = (len(parsed["chats"][0]["messages"][0]["content"]) + 3) // 4
    assert requests_seen[0] == ("POST", "https://api.openmates.org/v1/account-imports/preview", {"source": "claude", "parser_format": "claude", "chat_count": 1, "source_fingerprints": [parsed["chats"][0]["source_fingerprint"]], "estimated_tokens": 0, "estimated_tokens_by_chat": [expected_tokens], "estimated_bytes": 0})
    assert [request[1] for request in requests_seen] == [
        "https://api.openmates.org/v1/account-imports/preview",
        "https://api.openmates.org/v1/account-imports/import-1/confirm",
        "https://api.openmates.org/v1/account-imports/import-1/status",
        "https://api.openmates.org/v1/account-imports/import-1/scan",
        "https://api.openmates.org/v1/account-imports/import-1/compress",
        "https://api.openmates.org/v1/sdk/session",
        "https://api.openmates.org/v1/account-imports/import-1/persist-encrypted",
        "https://api.openmates.org/v1/account-imports/import-1/complete",
    ]
    assert requests_seen[1][2] == {"selected_fingerprints": [parsed["chats"][0]["source_fingerprint"]]}
    assert requests_seen[3][2]["batch_id"] == "scan-0"
    assert requests_seen[3][2]["sequence"] == 0
    assert requests_seen[3][2]["final_batch"] is True
    persisted = requests_seen[6][2]
    assert persisted is not None
    encrypted_chat = persisted["chats"][0]
    assert isinstance(encrypted_chat["encrypted_title"], str)
    assert "SDK import" not in encrypted_chat["encrypted_title"]
    encrypted_message = encrypted_chat["messages"][0]
    assert isinstance(encrypted_message["encrypted_content"], str)
    assert "SDK plaintext message" not in encrypted_message["encrypted_content"]
