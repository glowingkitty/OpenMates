#!/usr/bin/env python3
"""Live first-party Apple startup-sync contract probe.

This checks the real dev WebSocket against the authenticated Apple-equivalent
session flow. It emits only check names and statuses: encrypted payloads,
cookies, tokens, account identifiers, and message content never leave process
memory. The startup-sync surface is first-party only and carries ciphertext.
"""

from __future__ import annotations

# contract-test-file: infrastructure

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import ssl
import struct
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from verify_test_account_login import (  # noqa: E402
    AccountLoginError,
    derive_email_encryption_key,
    generate_totp,
    hash_email,
    hash_lookup_key,
    load_test_account,
    post_json,
)


DEFAULT_API = "https://api.dev.openmates.org"
DEFAULT_ORIGIN = "https://app.dev.openmates.org"
MAX_PHASE1_CHATS = 10
MAX_PHASE2_CHATS = 100
PHASE1_KEYS = {"chat_id", "chat_details", "messages", "recent_chat_metadata", "new_chat_suggestions", "daily_inspirations", "team_id", "context_epoch", "phase", "already_synced"}
PHASE2_BASE_KEYS = {"chats", "chat_count", "total_chat_count", "phase", "team_id", "context_epoch", "authoritative"}
PHASE2_RECONCILIATION_KEYS = {"authoritative_chat_ids", "deleted_chat_ids"}
HYDRATION_KEYS = {"messages_by_chat_id", "versions_by_chat_id", "compression_checkpoints_by_chat_id", "embeds", "embed_keys", "chat_key_wrappers", "code_run_outputs", "notebook_run_outputs", "partial_error"}
PLAINTEXT_MESSAGE_FIELDS = {"content", "thinking_content", "message", "text", "body"}


class ContractFailure(RuntimeError):
    """A sanitized, visible contract assertion failure."""


def require_https(api_url: str) -> None:
    """Reject plaintext transport before credentials, cookies, or tokens are used."""
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ContractFailure("credential-bearing contract probes require an https API URL")


class WireWebSocket:
    """Minimal masked client WebSocket implementation for the live contract only."""

    def __init__(
        self,
        api_url: str,
        *,
        query: dict[str, str],
        cookie: str = "",
        handshake_timeout: float = 20,
    ) -> None:
        require_https(api_url)
        parsed = urllib.parse.urlparse(api_url)
        self.host = parsed.hostname or ""
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.path = (parsed.path.rstrip("/") or "") + "/v1/ws?" + urllib.parse.urlencode(query)
        self.cookie = cookie
        self.handshake_timeout = handshake_timeout
        self.sock: socket.socket | ssl.SSLSocket | None = None

    def connect(self) -> int:
        raw = socket.create_connection((self.host, self.port), timeout=self.handshake_timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        self.sock.settimeout(self.handshake_timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        headers = [
            f"GET {self.path} HTTP/1.1",
            f"Host: {self.host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        if self.cookie:
            headers.append(f"Cookie: {self.cookie}")
        self.sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
        response = self._read_http_headers()
        response_lines = response.split("\r\n")
        first_line = response_lines[0]
        try:
            status = int(first_line.split()[1])
        except (IndexError, ValueError) as exc:
            raise ContractFailure("WebSocket handshake returned an invalid HTTP status") from exc
        if status == 101:
            response_headers = {}
            for line in response_lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    response_headers[name.strip().lower()] = value.strip()
            expected_accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            ).decode("ascii")
            if response_headers.get("sec-websocket-accept") != expected_accept:
                raise ContractFailure("WebSocket handshake did not validate Sec-WebSocket-Accept")
        return status

    def _read_http_headers(self) -> str:
        assert self.sock is not None
        received = bytearray()
        while b"\r\n\r\n" not in received:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            received.extend(chunk)
            if len(received) > 16384:
                raise ContractFailure("WebSocket handshake headers exceeded the contract limit")
        return received.decode("latin-1", errors="replace")

    def send_json(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, payload)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length < 65536:
            header = bytes((0x80 | opcode, 0xFE)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 0xFF)) + struct.pack("!Q", length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        assert self.sock is not None
        self.sock.sendall(header + mask + masked)

    def receive_json(self, timeout: float) -> dict[str, Any]:
        assert self.sock is not None
        deadline = time.monotonic() + timeout
        self.sock.settimeout(timeout)
        first, second = self._read_exact(2, deadline=deadline)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2, deadline=deadline))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8, deadline=deadline))[0]
        masked = bool(second & 0x80)
        mask = self._read_exact(4, deadline=deadline) if masked else b""
        payload = self._read_exact(length, deadline=deadline)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            raise ContractFailure("WebSocket closed before the expected response")
        if opcode == 0x9:
            self._send_frame(0xA, payload)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("timed out")
            return self.receive_json(remaining)
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractFailure("WebSocket returned non-JSON data") from exc
        if not isinstance(decoded, dict):
            raise ContractFailure("WebSocket returned a non-object event")
        return decoded

    def _read_exact(self, length: int, *, deadline: float | None = None) -> bytes:
        assert self.sock is not None
        chunks = bytearray()
        while len(chunks) < length:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise socket.timeout("timed out")
                self.sock.settimeout(remaining)
            chunk = self.sock.recv(length - len(chunks))
            if not chunk:
                raise ContractFailure("WebSocket closed during a response frame")
            chunks.extend(chunk)
        return bytes(chunks)

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None


def _login(api_url: str, *, slot: int, timeout: float) -> tuple[str, str, str]:
    require_https(api_url)
    credentials = load_test_account(slot, allow_base_fallback=True)
    if credentials is None:
        raise ContractFailure("configured test-account credentials are incomplete")
    import http.cookiejar
    import urllib.request
    import uuid

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    session_id = str(uuid.uuid4())
    hashed_email = hash_email(credentials.email)
    status, lookup = post_json(opener, api_url, "/v1/auth/lookup", {"hashed_email": hashed_email}, origin=DEFAULT_ORIGIN, timeout=timeout)
    salt = lookup.get("user_email_salt") if status == 200 else None
    if not isinstance(salt, str) or not salt:
        raise ContractFailure("first-party lookup did not return a usable salt")
    body = {"hashed_email": hashed_email, "lookup_hash": hash_lookup_key(credentials.password, salt), "email_encryption_key": derive_email_encryption_key(credentials.email, salt), "session_id": session_id}
    status, login = post_json(opener, api_url, "/v1/auth/login", body, origin=DEFAULT_ORIGIN, timeout=timeout)
    if status != 200 or login.get("success") is not True:
        raise ContractFailure("first-party password login failed")
    if login.get("tfa_required") is True:
        body.update({"tfa_code": generate_totp(credentials.otp_key), "code_type": "otp"})
        status, login = post_json(opener, api_url, "/v1/auth/login", body, origin=DEFAULT_ORIGIN, timeout=timeout)
    token = login.get("ws_token")
    if status != 200 or login.get("success") is not True or not isinstance(token, str) or not token:
        raise ContractFailure("authenticated session did not provide a WebSocket token")
    cookie = "; ".join(f"{item.name}={item.value}" for item in cookie_jar)
    if not cookie:
        raise ContractFailure("authenticated session did not provide an HTTP-only cookie")
    return session_id, token, cookie


def _expect_rejected(api_url: str, token: str) -> None:
    ws = WireWebSocket(api_url, query={"sessionId": "00000000-0000-4000-8000-000000000000", "token": token})
    try:
        if ws.connect() == 101:
            raise ContractFailure("unauthorized or developer-style WebSocket access was accepted")
    finally:
        ws.close()


def _validate_phase1(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != PHASE1_KEYS:
        raise ContractFailure("Phase 1a payload did not match its exact startup shape")
    if payload["phase"] != "phase1" or payload["messages"] is not None or payload["already_synced"] is not False:
        raise ContractFailure("Phase 1a included content or invalid phase state")
    recent = payload["recent_chat_metadata"]
    if not isinstance(recent, list) or len(recent) > MAX_PHASE1_CHATS:
        raise ContractFailure("Phase 1a metadata exceeded its bounded chat limit")
    details = payload["chat_details"]
    if details is not None and (not isinstance(details, dict) or not isinstance(details.get("id"), str)):
        raise ContractFailure("Phase 1a chat details did not contain a chat identifier")
    if details and payload["chat_id"] != details["id"]:
        raise ContractFailure("Phase 1a chat identifier did not match its metadata")
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in recent):
        raise ContractFailure("Phase 1a recent metadata contained an invalid chat shell")
    if len(recent) + (1 if details else 0) > MAX_PHASE1_CHATS:
        raise ContractFailure("Phase 1a returned more than the bounded startup window")


def _validate_phase2(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not PHASE2_BASE_KEYS.issubset(payload):
        raise ContractFailure("Phase 2 payload did not contain its required metadata shape")
    allowed_keys = PHASE2_BASE_KEYS | PHASE2_RECONCILIATION_KEYS
    if set(payload) - allowed_keys:
        raise ContractFailure("Phase 2 included content or key material instead of metadata only")
    if payload["phase"] != "phase2" or not isinstance(payload["total_chat_count"], int) or payload["total_chat_count"] < 0:
        raise ContractFailure("Phase 2 reported invalid phase or total chat count")
    chats = payload["chats"]
    if not isinstance(chats, list) or payload["chat_count"] != len(chats) or len(chats) > MAX_PHASE2_CHATS:
        raise ContractFailure("Phase 2 metadata exceeds its current bounded chat limit")
    if payload["authoritative"] is True and not PHASE2_RECONCILIATION_KEYS.issubset(payload):
        raise ContractFailure("authoritative Phase 2 reconciliation omitted its explicit evidence")
    if payload["authoritative"] is False and PHASE2_RECONCILIATION_KEYS.intersection(payload):
        raise ContractFailure("partial Phase 2 metadata claimed deletion authority")
    for wrapper in chats:
        details = wrapper.get("chat_details") if isinstance(wrapper, dict) else None
        if not isinstance(details, dict) or not isinstance(details.get("id"), str):
            raise ContractFailure("Phase 2 metadata contained an invalid chat wrapper")
    return chats


def _validate_hydration(payload: Any, requested_chat_id: str) -> None:
    if not isinstance(payload, dict) or not set(payload).issubset(HYDRATION_KEYS) or not (HYDRATION_KEYS - {"partial_error"}).issubset(payload):
        raise ContractFailure("content hydration response did not match the handler's bounded shape")
    messages_by_chat = payload["messages_by_chat_id"]
    versions = payload["versions_by_chat_id"]
    if set(messages_by_chat) != {requested_chat_id} or set(versions) != {requested_chat_id}:
        raise ContractFailure("content hydration response did not correspond exactly to the requested chat")
    if not isinstance(messages_by_chat[requested_chat_id], list) or not isinstance(versions[requested_chat_id], dict):
        raise ContractFailure("content hydration response has invalid message or version envelopes")
    if set(versions[requested_chat_id]) != {"messages_v", "server_message_count"}:
        raise ContractFailure("content hydration response has an invalid version envelope")
    for key in ("compression_checkpoints_by_chat_id",):
        if not isinstance(payload[key], dict) or not set(payload[key]).issubset({requested_chat_id}):
            raise ContractFailure("content hydration response escaped the requested chat boundary")
    for key in ("embeds", "embed_keys", "chat_key_wrappers", "code_run_outputs", "notebook_run_outputs"):
        if not isinstance(payload[key], list):
            raise ContractFailure("content hydration response has an invalid bounded collection")
    for raw_message in messages_by_chat[requested_chat_id]:
        message = json.loads(raw_message) if isinstance(raw_message, str) else raw_message
        if not isinstance(message, dict) or not isinstance(message.get("encrypted_content"), str) or not message["encrypted_content"]:
            raise ContractFailure("hydration message omitted its encrypted content envelope")
        if PLAINTEXT_MESSAGE_FIELDS.intersection(message):
            raise ContractFailure("hydration message included a plaintext content field")
        if message.get("chat_id") not in (None, requested_chat_id):
            raise ContractFailure("hydration message did not belong to the requested chat")


def _receive_named_event(ws: WireWebSocket, expected_type: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = ws.receive_json(max(0.1, deadline - time.monotonic()))
        event_type = event.get("type")
        if event_type == "error":
            raise ContractFailure(f"server returned an error while waiting for {expected_type}")
        if event_type == expected_type:
            return event
    raise ContractFailure(f"timed out waiting for {expected_type}")


def run(api_url: str, *, slot: int, timeout: float) -> dict[str, Any]:
    require_https(api_url)
    _expect_rejected(api_url, "developer-api-key-is-not-a-websocket-token")
    _expect_rejected(api_url, "")
    session_id, ws_token, cookie = _login(api_url, slot=slot, timeout=timeout)
    ws = WireWebSocket(api_url, query={"sessionId": session_id, "token": ws_token}, cookie=cookie)
    try:
        if ws.connect() != 101:
            raise ContractFailure("authenticated first-party WebSocket connection was rejected")
        ws.send_json({"type": "request_cache_status", "payload": {}})
        status_event = _receive_named_event(ws, "sync_status_response", timeout)
        if not isinstance(status_event.get("payload"), dict):
            raise ContractFailure("startup status response has an invalid shape")
        rich_state = {"client_chat_versions": {}, "client_chat_ids": [], "client_suggestions_count": 0, "client_embed_ids": [], "context_epoch": 0, "phase": "all"}
        ws.send_json({"type": "phased_sync_request", "payload": rich_state})
        phase1 = phase2 = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = ws.receive_json(max(0.1, deadline - time.monotonic()))
            if event.get("type") == "phase_1_last_chat_ready":
                phase1 = event.get("payload")
            if event.get("type") == "phase_2_last_20_chats_ready":
                phase2 = event.get("payload")
            if phase1 is not None and phase2 is not None:
                break
        _validate_phase1(phase1)
        chats = _validate_phase2(phase2)
        chat_id = next((item.get("chat_details", item).get("id") for item in chats if isinstance(item, dict) and isinstance(item.get("chat_details", item), dict) and isinstance(item.get("chat_details", item).get("id"), str)), None)
        if chat_id is None:
            raise ContractFailure("cannot prove metadata-only hydration: the test account has no Phase 2 chat")
        ws.send_json({"type": "request_chat_content_batch", "payload": {"chat_ids": [chat_id]}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = ws.receive_json(max(0.1, deadline - time.monotonic()))
            if event.get("type") == "chat_content_batch_response":
                _validate_hydration(event.get("payload"), chat_id)
                return {"status": "passed", "checks": ["unauthorized_ws_rejected", "developer_ws_rejected", "rich_first_party_state", "bounded_phase1_metadata", "bounded_phase2_metadata", "bounded_ciphertext_hydration_response"], "phase2_chat_count": len(chats), "phase1_limit": MAX_PHASE1_CHATS}
        raise ContractFailure("metadata-only chat hydration did not return a response")
    finally:
        ws.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.environ.get("OPENMATES_API_URL", DEFAULT_API))
    parser.add_argument("--producer", choices=("websocket",), default="websocket")
    parser.add_argument("--slot", type=int, default=int(os.environ.get("OPENMATES_APPLE_CONTRACT_ACCOUNT_SLOT", "14")))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.api.rstrip("/"), slot=args.slot, timeout=args.timeout)
        code = 0
    except (AccountLoginError, ContractFailure, OSError, socket.timeout) as exc:
        result, code = {"status": "failed", "failure_class": "contract_or_transport", "error": str(exc)}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
