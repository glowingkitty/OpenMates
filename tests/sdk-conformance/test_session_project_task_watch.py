"""Raw loopback peer transport checks; no SDK import or application request."""

# contract-test-file: tooling
from __future__ import annotations

import base64
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import struct
from urllib.parse import urlsplit

import pytest

from session_project_task_watch_server import CAPABILITY, WatchPeer


@pytest.fixture
def peer():
    suite = json.loads(
        (
            Path(__file__).with_name("fixtures") / "session-project-task-watch.json"
        ).read_text()
    )["capabilities"][CAPABILITY]
    server = WatchPeer(suite, suite["vectors"][0], "rust").start()
    try:
        yield server
    finally:
        server.close()


def frame(opcode, value=b""):
    raw = json.dumps(value).encode() if isinstance(value, dict) else value
    mask = b"test"
    length = (
        bytes([0x80 | len(raw)])
        if len(raw) < 126
        else b"\xfe" + struct.pack(">H", len(raw))
    )
    return (
        bytes([0x80 | opcode])
        + length
        + mask
        + bytes(byte ^ mask[i % 4] for i, byte in enumerate(raw))
    )


def test_websocket_upgrade_uses_http11_and_closes_upgraded_stream(peer):
    endpoint = urlsplit(peer.endpoint)
    key = base64.b64encode(b"0123456789abcdef").decode()
    headers = (
        "GET /v1/ws?token=synthetic-watch-ws&sessionId=99999999-9999-4999-8999-999999999999&client_capabilities= HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{endpoint.port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Cookie: auth_refresh_token={peer.cookie}\r\n"
        "X-OpenMates-SDK: rust\r\nOrigin: https://app.example.invalid\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", endpoint.port), timeout=3) as client:
        client.sendall(headers.encode())
        stream = client.makefile("rb")
        assert stream.readline() == b"HTTP/1.1 101 Switching Protocols\r\n"
        response_headers = {}
        while (line := stream.readline()) != b"\r\n":
            assert line
            name, value = line.decode().split(":", 1)
            response_headers[name.lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        ).decode()
        assert response_headers["sec-websocket-accept"] == expected
        assert response_headers["upgrade"].lower() == "websocket"
        client.sendall(
            frame(
                1,
                {
                    "type": "native_client_lifecycle",
                    "payload": {
                        "client_type": "rust",
                        "is_foreground": False,
                        "interactive": False,
                    },
                },
            )
            + frame(
                1,
                {
                    "type": "project_task_sync_subscribe",
                    "payload": {
                        "bindings": [
                            {
                                "project_id": peer.suite["project_id"],
                                "source_id": peer.suite["source_id"],
                                "cursor": None,
                            }
                        ]
                    },
                },
            )
        )
        peer.wait(lambda: peer.counts["subscriptions"] == 1)
        # A complete close must end the upgraded connection, never parse this
        # trailing HTTP request as a fresh keep-alive request on the WS stream.
        client.sendall(
            frame(8) + b"GET /__test/status HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        )
        try:
            assert stream.read(1) == b""
        except ConnectionResetError:
            pass
        finally:
            stream.close()
    assert peer.status()["failure"] is None
    assert peer.status()["client_messages"] == 0


def test_json_content_length_keeps_http11_connection_reusable(peer):
    endpoint = urlsplit(peer.endpoint)
    client = HTTPConnection("127.0.0.1", endpoint.port, timeout=3)
    try:
        original_socket = None
        for _ in range(2):
            client.request("GET", "/__test/status")
            response = client.getresponse()
            raw = response.read()
            assert response.version == 11 and response.status == 200
            assert len(raw) == int(response.getheader("Content-Length"))
            assert json.loads(raw)["failure"] is None
            if original_socket is None:
                original_socket = client.sock
            else:
                assert client.sock is original_socket
    finally:
        client.close()


class FixtureSocket:
    """Routing-only sink; no SDK or alternate protocol implementation."""

    def __init__(self):
        self.messages = []
        self.handler = type("Handler", (), {"connection": self})()

    def shutdown(self, _how):
        pass

    def send(self, kind, payload):
        self.messages.append((kind, payload))


def bind(peer, logical, after):
    return peer.control(
        {
            "op": "bind_watch",
            "watch": logical,
            "after": after,
            "source_id": peer.suite["source_id"],
        }
    )["generation"]


def test_checkpoint_replacement_binds_fresh_generation_not_reused_physical_slot(peer):
    old, replacement = FixtureSocket(), FixtureSocket()
    name, first = peer.register_socket(old)
    assert bind(peer, "a", 0) == first
    peer.remove_socket(name, first, old)
    new_name, second = peer.register_socket(replacement)
    assert new_name == name and second > first
    assert bind(peer, "b", first) == second
    peer.control({"op": "send", "watch": "b", "generation": second, "kind": "empty"})
    assert len(replacement.messages) == 1 and old.messages == []


def test_cancelled_upgrade_has_no_subscription_to_claim_as_replacement(
    peer, monkeypatch
):
    # A cancelled, withheld upgrade has no registered subscription generation.
    # An unrelated remaining connection can never stand in for the new open.
    remaining = FixtureSocket()
    _, first = peer.register_socket(remaining)
    assert bind(peer, "existing", 0) == first

    def immediate_beacon(predicate):
        assert predicate(), "fresh observed subscription required"

    monkeypatch.setattr(peer, "wait", immediate_beacon)
    with pytest.raises(AssertionError, match="fresh observed subscription"):
        bind(peer, "b", first)
    assert "b" not in peer.aliases and remaining.messages == []
    replacement = FixtureSocket()
    _, second = peer.register_socket(replacement)
    assert bind(peer, "b", first) == second
    assert peer.target({"watch": "b", "generation": second}) is replacement


def test_reopened_logical_a_rejects_stale_generation_and_old_close_aba(peer):
    old, replacement = FixtureSocket(), FixtureSocket()
    name, first = peer.register_socket(old)
    bind(peer, "a", 0)
    peer.remove_socket(name, first, old)
    new_name, second = peer.register_socket(replacement)
    assert new_name == name
    assert bind(peer, "a", first) == second
    with pytest.raises(AssertionError, match="stale logical watch generation"):
        peer.target({"watch": "a", "generation": first})
    peer.remove_socket(name, first, old)  # Delayed old callback cannot erase new.
    assert peer.target({"watch": "a", "generation": second}) is replacement
    peer.control({"op": "send", "watch": "a", "generation": second, "kind": "empty"})
    assert len(replacement.messages) == 1 and old.messages == []


def test_old_socket_control_after_replacement_targets_only_historical_generation(peer):
    old, replacement = FixtureSocket(), FixtureSocket()
    name, first = peer.register_socket(old)
    bind(peer, "a", 0)
    peer.remove_socket(name, first, old)
    _, second = peer.register_socket(replacement)
    bind(peer, "b", first)
    peer.control({"op": "late_force_logout", "watch": "a", "generation": first})
    assert old.messages == [("force_logout", {"reason": "synthetic-old-transport"})]
    assert replacement.messages == []
    assert peer.target({"watch": "b", "generation": second}) is replacement


def test_ambiguous_new_connections_refuse_mapping_instead_of_guessing(peer):
    peer.register_socket(FixtureSocket())
    peer.register_socket(FixtureSocket())
    with pytest.raises(AssertionError, match="ambiguous connection generation"):
        bind(peer, "a", 0)
    assert peer.aliases == {}


def test_foreign_source_control_has_typed_failure_and_never_binds(peer):
    candidate = FixtureSocket()
    peer.register_socket(candidate)
    endpoint = urlsplit(peer.endpoint)
    client = HTTPConnection("127.0.0.1", endpoint.port, timeout=3)
    try:
        client.request(
            "POST",
            "/__test/control",
            body=json.dumps(
                {
                    "op": "bind_watch",
                    "watch": "a",
                    "after": 0,
                    "source_id": "foreign-source",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        response = client.getresponse()
        assert response.status == 500
        assert json.loads(response.read()) == {
            "error": "fixture_rejected",
            "failure_code": "AssertionError",
        }
        assert peer.aliases == {} and candidate.messages == []
    finally:
        client.close()
