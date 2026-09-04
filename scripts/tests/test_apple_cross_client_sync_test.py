#!/usr/bin/env python3
"""Linux-safe unit coverage for the Apple WebSocket sync contract probe.

These tests exercise only local protocol helpers and intentionally avoid live
credentials, network access, decrypted chat content, and Apple tooling.
"""

from __future__ import annotations

# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated,sync.startup.bounded-phases,sync.phase2.metadata-only

import importlib.util
import socket
import sys
from pathlib import Path
import base64
import hashlib

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/apple_cross_client_sync_test.py"


def load_module():
    spec = importlib.util.spec_from_file_location("apple_cross_client_sync_contract", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_rejected_websocket_access_requires_non_switching_handshake(monkeypatch):
    module = load_module()
    calls = []

    class FakeWebSocket:
        def __init__(self, _api, *, query, cookie=""):
            calls.append((query, cookie))

        def connect(self):
            return 403

        def close(self):
            return None

    monkeypatch.setattr(module, "WireWebSocket", FakeWebSocket)

    module._expect_rejected("https://api.dev.openmates.org", "opaque-developer-value")

    assert calls == [({"sessionId": "00000000-0000-4000-8000-000000000000", "token": "opaque-developer-value"}, "")]


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_rejected_websocket_access_fails_closed_when_server_switches_protocol(monkeypatch):
    module = load_module()

    class FakeWebSocket:
        def __init__(self, *_args, **_kwargs):
            pass

        def connect(self):
            return 101

        def close(self):
            return None

    monkeypatch.setattr(module, "WireWebSocket", FakeWebSocket)

    with pytest.raises(module.ContractFailure, match="was accepted"):
        module._expect_rejected("https://api.dev.openmates.org", "opaque-developer-value")


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_https_is_required_before_websocket_credentials_are_used():
    module = load_module()

    with pytest.raises(module.ContractFailure, match="require an https API URL"):
        module.WireWebSocket("http://api.dev.openmates.org", query={"token": "opaque"})


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_login_retains_the_explicit_cookie_jar_instead_of_assuming_handler_order():
    source = MODULE_PATH.read_text()

    assert "cookie_jar = http.cookiejar.CookieJar()" in source
    assert "HTTPCookieProcessor(cookie_jar)" in source
    assert "opener.handlers[0]" not in source


# contract-test: supporting surface=rest_api assertions=sync.startup.bounded-phases
def test_named_event_wait_ignores_unrelated_delivery_events(monkeypatch):
    module = load_module()
    events = iter([
        {"type": "reminder_fired", "payload": {}},
        {"type": "sync_status_response", "payload": {"is_primed": True}},
    ])

    class FakeWebSocket:
        def receive_json(self, _timeout):
            return next(events)

    monkeypatch.setattr(module.time, "monotonic", lambda: 0.0)

    assert module._receive_named_event(FakeWebSocket(), "sync_status_response", 1.0)["type"] == "sync_status_response"


# contract-test: supporting surface=rest_api assertions=sync.startup.bounded-phases
def test_named_event_wait_fails_closed_on_server_error(monkeypatch):
    module = load_module()

    class FakeWebSocket:
        def receive_json(self, _timeout):
            return {"type": "error", "payload": {"message": "private detail"}}

    monkeypatch.setattr(module.time, "monotonic", lambda: 0.0)

    with pytest.raises(module.ContractFailure, match="server returned an error") as exc_info:
        module._receive_named_event(FakeWebSocket(), "sync_status_response", 1.0)
    assert "private detail" not in str(exc_info.value)


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_websocket_handshake_requires_the_rfc_accept_value(monkeypatch):
    module = load_module()
    key_bytes = b"0123456789abcdef"
    key = base64.b64encode(key_bytes).decode("ascii")
    expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")

    class Socket:
        def settimeout(self, _timeout):
            return None

        def sendall(self, _data):
            return None

    class Context:
        def wrap_socket(self, _raw, server_hostname):
            assert server_hostname == "api.dev.openmates.org"
            return Socket()

    monkeypatch.setattr(module.socket, "create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(module.secrets, "token_bytes", lambda _size: key_bytes)
    ws = module.WireWebSocket("https://api.dev.openmates.org", query={})
    monkeypatch.setattr(ws, "_read_http_headers", lambda: f"HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: {expected}\r\n\r\n")
    assert ws.connect() == 101

    invalid = module.WireWebSocket("https://api.dev.openmates.org", query={})
    monkeypatch.setattr(invalid, "_read_http_headers", lambda: "HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: invalid\r\n\r\n")
    with pytest.raises(module.ContractFailure, match="Sec-WebSocket-Accept"):
        invalid.connect()


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_websocket_ping_frames_are_answered_with_masked_pong(monkeypatch):
    module = load_module()
    event_payload = b'{"type":"ready"}'
    incoming = bytearray(b"\x89\x02hi" + bytes([0x81, len(event_payload)]) + event_payload)

    class Socket:
        def __init__(self):
            self.sent = bytearray()

        def settimeout(self, _timeout):
            return None

        def recv(self, count):
            chunk = incoming[:count]
            del incoming[:count]
            return bytes(chunk)

        def sendall(self, data):
            self.sent.extend(data)

    sock = Socket()
    monkeypatch.setattr(module.secrets, "token_bytes", lambda _size: b"\x00\x00\x00\x00")
    ws = module.WireWebSocket("https://api.dev.openmates.org", query={})
    ws.sock = sock

    assert ws.receive_json(1.0) == {"type": "ready"}
    assert bytes(sock.sent) == b"\x8a\x82\x00\x00\x00\x00hi"


# contract-test: supporting surface=rest_api assertions=sync.access.first-party-authenticated
def test_websocket_receive_json_enforces_absolute_frame_deadline(monkeypatch):
    module = load_module()
    incoming = bytearray(b"\x81\x03{")
    times = iter([0.0, 0.0, 0.0, 2.0])

    class Socket:
        def settimeout(self, _timeout):
            return None

        def recv(self, count):
            chunk = incoming[:count]
            del incoming[:count]
            return bytes(chunk)

    monkeypatch.setattr(module.time, "monotonic", lambda: next(times, 2.0))
    ws = module.WireWebSocket("https://api.dev.openmates.org", query={})
    ws.sock = Socket()

    with pytest.raises(socket.timeout):
        ws.receive_json(1.0)


# contract-test: supporting surface=rest_api assertions=sync.startup.bounded-phases,sync.phase2.metadata-only
def test_phase_payloads_and_hydration_enforce_exact_bounded_ciphertext_shapes():
    module = load_module()
    phase1 = {"chat_id": "chat-1", "chat_details": {"id": "chat-1"}, "messages": None, "recent_chat_metadata": [], "new_chat_suggestions": [], "daily_inspirations": [], "team_id": None, "context_epoch": 0, "phase": "phase1", "already_synced": False}
    phase2 = {"chats": [{"chat_details": {"id": "chat-1"}}], "chat_count": 1, "total_chat_count": 1, "phase": "phase2", "team_id": None, "context_epoch": 0, "authoritative": True, "authoritative_chat_ids": ["chat-1"], "deleted_chat_ids": []}
    hydration = {"messages_by_chat_id": {"chat-1": ['{"message_id":"m-1","chat_id":"chat-1","encrypted_content":"opaque"}']}, "versions_by_chat_id": {"chat-1": {"messages_v": 1, "server_message_count": 1}}, "compression_checkpoints_by_chat_id": {}, "embeds": [], "embed_keys": [], "chat_key_wrappers": [], "code_run_outputs": [], "notebook_run_outputs": []}

    module._validate_phase1(phase1)
    assert module._validate_phase2(phase2) == phase2["chats"]
    module._validate_hydration(hydration, "chat-1")

    hydration["messages_by_chat_id"]["chat-1"] = ['{"chat_id":"chat-1","content":"plaintext"}']
    with pytest.raises(module.ContractFailure, match="encrypted content envelope"):
        module._validate_hydration(hydration, "chat-1")
