#!/usr/bin/env python3
"""Test-only protocol peer; binds exclusively to ephemeral IPv4 loopback.

Clients under test call their native SDK directly. This fixture service is never
imported or started by SDK production code. All keys and payloads are synthetic.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import struct
import threading
import traceback
from urllib.parse import parse_qs, urlsplit
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CAPABILITY = "session.recovery-replay.v1"


def b64url(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def unurl(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hkdf(value, salt, info):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(
        value
    )


def fingerprint(key):
    value = 2166136261
    for byte in key:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value.to_bytes(4, "big")


def encrypt(plain, key):
    nonce = os.urandom(12)
    return base64.b64encode(
        b"OM" + fingerprint(key) + nonce + AESGCM(key).encrypt(nonce, plain, None)
    ).decode()


def decrypt(value, key):
    data = base64.b64decode(value, validate=True)
    if data[:2] == b"OM":
        assert data[2:6] == fingerprint(key), "ciphertext fingerprint"
        data = data[6:]
    return AESGCM(key).decrypt(data[:12], data[12:], None)


def lp(value):
    data = value.encode()
    return struct.pack(">I", len(data)) + data


def seal(public, identity, payload, tamper=False):
    aad = b"OMCR1" + b"".join(lp(value) for value in identity) + struct.pack(">I", 1)
    # Public fixture-only private key. AAD-bound nonce differs for each turn.
    secret = X25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    ephemeral = secret.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    shared = secret.exchange(X25519PublicKey.from_public_bytes(unurl(public)))
    key = hkdf(
        shared,
        hashlib.sha256(b"openmates:chat-recovery-envelope:v1").digest(),
        hashlib.sha256(aad).digest(),
    )
    nonce = hashlib.sha256(b"synthetic-fixture-nonce" + aad).digest()[:12]
    encrypted = bytearray(AESGCM(key).encrypt(nonce, json.dumps(payload).encode(), aad))
    if tamper:
        encrypted[-1] ^= 1
    return {
        "v": 1,
        "epk": b64url(ephemeral),
        "nonce": b64url(nonce),
        "ciphertext": b64url(encrypted),
    }


class WebSocket:
    def __init__(self, handler):
        self.handler = handler

    def read_exact(self, length):
        data = self.handler.rfile.read(length)
        if len(data) != length:
            raise EOFError
        return data

    def receive(self):
        while True:
            first, second = self.read_exact(2)
            assert first & 0x80 and second & 0x80, "masked final client frame"
            opcode, length = first & 15, second & 127
            if length == 126:
                length = struct.unpack(">H", self.read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self.read_exact(8))[0]
            assert length < 1024 * 1024, "bounded fixture frame"
            mask = self.read_exact(4)
            data = bytes(
                byte ^ mask[i % 4] for i, byte in enumerate(self.read_exact(length))
            )
            if opcode == 8:
                return None
            if opcode == 9:
                self.raw(10, data)
            elif opcode == 1:
                return json.loads(data)
            else:
                assert opcode == 10, "unexpected fixture frame"

    def raw(self, opcode, data):
        size = len(data)
        header = bytes([0x80 | opcode])
        header += (
            bytes([size])
            if size < 126
            else b"\x7e" + struct.pack(">H", size)
            if size < 65536
            else b"\x7f" + struct.pack(">Q", size)
        )
        self.handler.wfile.write(header + data)
        self.handler.wfile.flush()

    def send(self, kind, payload):
        self.raw(1, json.dumps({"type": kind, "payload": payload}).encode())


class RecoveryPeer:
    def __init__(self, suite, vector, identity):
        assert identity in ("rust", "npm", "pip")
        self.suite, self.vector, self.identity = suite, vector, identity
        self.account, self.protocol = suite["account"], suite["protocol"]
        self.master = base64.b64decode(self.account["master_key"])
        self.key = base64.b64decode(self.protocol["initial_chat_key"])
        self.chat_id = self.protocol["initial_chat_id"]
        self.wrapped = encrypt(self.key, self.master)
        self.messages, self.admission = [], None
        self.checks, self.failure = set(), None
        self.counts = {"admissions": 0, "claims": 0, "persists": 0, "connections": 0}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True
        self.thread = None

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3)

    def mark(self, name):
        self.checks.add(name)

    def status(self):
        return {"failure": self.failure, "checks": sorted(self.checks), **self.counts}

    def row(self):
        key = bytes([91]) * 32 if self.vector["mode"] == "bad_key" else self.key
        version = (
            0
            if self.vector["mode"] == "bad_version"
            else self.protocol["fresh_messages_v"]
        )
        return {
            "id": self.chat_id,
            "encrypted_chat_key": encrypt(key, self.master),
            "encrypted_title": encrypt(b"Synthetic recovery chat", key),
            "messages_v": version,
        }

    def headers(self, handler):
        assert handler.headers.get("X-OpenMates-SDK") == self.identity, "SDK identity"
        assert handler.headers.get("Origin") == self.protocol["app_origin"], (
            "explicit origin"
        )
        assert (
            handler.headers.get("Cookie")
            == f"auth_refresh_token={self.account['cookie']}"
        ), "session cookie"
        assert handler.headers.get("Authorization") is None, "no bearer escalation"
        self.mark("explicit-native-session")

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def response(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                try:
                    peer.headers(self)
                    length = int(self.headers["Content-Length"])
                    assert 0 < length < 65536, "bounded HTTP input"
                    value = json.loads(self.rfile.read(length))
                    if self.path == "/v1/auth/session":
                        assert value == {"session_id": peer.account["session_id"]}
                        self.response(
                            200,
                            {
                                "success": True,
                                "ws_token": "synthetic-ws-token",
                                "user": {"id": peer.account["owner_id"]},
                            },
                        )
                    elif self.path == "/v1/chats/metadata/batch":
                        assert value == {"chat_ids": [peer.chat_id]}, "metadata target"
                        peer.mark("fresh-metadata-reread")
                        self.response(200, {"chats": [peer.row()]})
                    else:
                        raise AssertionError("unexpected HTTP mutation")
                except Exception:
                    peer.failure = peer.failure or "http-request"
                    self.response(500, {})

            def do_GET(self):
                try:
                    route = urlsplit(self.path)
                    if route.path == "/__test/status":
                        self.response(200, peer.status())
                        return
                    peer.headers(self)
                    if route.path == "/v1/ws":
                        query = parse_qs(route.query)
                        assert query["token"] == ["synthetic-ws-token"]
                        uuid.UUID(query["sessionId"][0])
                        assert (
                            "typed_recovery_outputs_v2"
                            in query["client_capabilities"][0]
                        )
                        key = self.headers["Sec-WebSocket-Key"]
                        accept = base64.b64encode(
                            hashlib.sha1(
                                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                            ).digest()
                        ).decode()
                        self.send_response(101)
                        self.send_header("Upgrade", "websocket")
                        self.send_header("Connection", "Upgrade")
                        self.send_header("Sec-WebSocket-Accept", accept)
                        self.end_headers()
                        try:
                            peer.websocket(WebSocket(self))
                        finally:
                            self.close_connection = True
                    elif route.path == f"/v1/chats/{peer.chat_id}/messages/window":
                        assert parse_qs(route.query) == {
                            "direction": ["latest"],
                            "limit": ["100"],
                            "respect_compression_boundary": ["false"],
                        }
                        assert peer.messages, "canonical message exists"
                        peer.mark("canonical-message-reread")
                        self.response(
                            200, {"messages": peer.messages, "has_more_before": False}
                        )
                    elif (
                        route.path
                        == f"/v1/embeds/chats/{peer.chat_id}/embeds/{peer.protocol['embed_id']}"
                    ):
                        peer.mark("canonical-embed-reread")
                        self.response(200, {"embed": peer.embed()})
                    else:
                        raise AssertionError("unexpected HTTP read")
                except (EOFError, BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    where = traceback.extract_tb(error.__traceback__)[-1]
                    peer.failure = (
                        peer.failure or f"protocol:{where.name}:{where.lineno}"
                    )
                    self.close_connection = True
                    if self.headers.get("Upgrade", "").lower() != "websocket":
                        self.response(500, {})

        return Handler

    def embed(self):
        if not hasattr(self, "encrypted_embed"):
            key = hkdf(
                self.key, b"openmates-embed-key-v1", self.protocol["embed_id"].encode()
            )
            self.encrypted_embed = encrypt(b'{"type":"code","code":"synthetic"}', key)
        return {
            "hashed_chat_id": hashlib.sha256(self.chat_id.encode()).hexdigest(),
            "version_number": 1,
            "encrypted_content": self.encrypted_embed,
        }

    def output(self):
        return {
            "record_id": self.protocol["record_id"],
            "root_chat_id": self.chat_id,
            "target_chat_id": self.chat_id,
            "turn_id": "33333333-3333-4333-8333-333333333333",
            "subject_id": self.protocol["embed_id"],
            "output_kind": "embed",
            "output_version": 1,
            "chat_key_version": 1,
        }

    def canonical(self, content):
        return {
            "client_message_id": self.protocol["assistant_id"],
            "chat_id": self.chat_id,
            "role": "assistant",
            "encrypted_content": encrypt(content.encode(), self.key),
            "encrypted_sender_name": encrypt(b"Assistant", self.key),
            "created_at": 1,
            "updated_at": 1,
        }

    def websocket(self, socket):
        self.counts["connections"] += 1
        try:
            while (event := socket.receive()) is not None:
                kind, payload = event["type"], event["payload"]
                if kind == "native_client_lifecycle":
                    assert payload["client_type"] == self.identity
                    assert (
                        payload["interactive"] is False
                        and payload["is_foreground"] is True
                    )
                elif kind == "set_active_chat":
                    if self.admission is None and self.vector["mode"] != "bad_digest":
                        assert uuid.UUID(payload["chat_id"]).version == 4
                        self.chat_id = payload["chat_id"]
                    else:
                        assert payload["chat_id"] == self.chat_id
                elif kind == "personal_send_context_snapshot":
                    socket.send(
                        "personal_send_context_snapshot_result",
                        {
                            "request_id": payload["request_id"],
                            "turn_id": payload["turn_id"],
                            "success": True,
                            "unchanged": False,
                            "receipt_id": "synthetic-privacy-receipt",
                            "privacy_generation": 1,
                            "personal_memories": {"memories": []},
                            "project_candidates": [],
                        },
                    )
                elif kind == "chat_turn_admit":
                    self.admit(socket, payload)
                elif kind == "recovery_job_claim":
                    self.claim(socket, payload)
                elif kind == "recovery_job_persist":
                    self.persist(socket, payload)
                    if self.vector["mode"] == "lost_ack":
                        return
                elif kind == "phased_sync_request":
                    assert payload["phase"] == "all"
                    socket.send(
                        "phase_2_last_20_chats_ready",
                        {"chats": [{"chat_details": self.row()}]},
                    )
                    socket.send(
                        "recovery_outputs_available", {"outputs": [self.output()]}
                    )
                    socket.send("phased_sync_complete", {})
                    socket.send(
                        "recovery_outputs_discovery_complete", {"status": "completed"}
                    )
                    self.mark("reconnect-discovery")
                elif kind == "recovery_output_get":
                    assert payload["record_id"] == self.protocol["record_id"]
                    socket.send(
                        "error",
                        {
                            "request_id": payload["request_id"],
                            "code": "already_acknowledged",
                            "message": "synthetic-private-server-diagnostic",
                        },
                    )
                elif kind == "recovery_output_status":
                    assert payload["record_id"] == self.protocol["record_id"]
                    digest = hashlib.sha256(
                        self.embed()["encrypted_content"].encode()
                    ).hexdigest()
                    if self.vector["mode"] == "bad_digest":
                        digest = ("0" if digest[0] != "0" else "1") + digest[1:]
                    socket.send(
                        "recovery_output_status_ready",
                        {
                            **self.output(),
                            "request_id": payload["request_id"],
                            "state": "ACKNOWLEDGED",
                            "canonical_verified": True,
                            "canonical_source": "head",
                            "canonical_digest": digest,
                        },
                    )
                    self.mark("acknowledged-output-status")
                else:
                    raise AssertionError("unexpected client frame")
        except (EOFError, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.mark("socket-closed")

    def admit(self, socket, payload):
        self.counts["admissions"] += 1
        assert self.counts["admissions"] == 1, "ambiguous turn was resubmitted"
        self.admission = payload
        for field in ("chat_id", "turn_id", "message_id"):
            assert uuid.UUID(payload[field]).version == 4
        self.chat_id, self.wrapped = payload["chat_id"], payload["encrypted_chat_key"]
        self.key = decrypt(self.wrapped, self.master)
        assert len(self.key) == 32 and self.key != self.master
        assert (
            decrypt(
                payload["encrypted_user_message"]["encrypted_content"], self.key
            ).decode()
            == self.protocol["input"]
        )
        assert (
            payload["inference_request"]["message"]["content"] == self.protocol["input"]
        )
        assert payload["expected_messages_v"] == 0
        assert payload["privacy_receipt_id"] == "synthetic-privacy-receipt"
        assert payload["privacy_generation"] == 1
        assert not {"model", "provider"} & payload["inference_request"].keys()
        self.mark("encrypted-admission-default-routing")
        socket.send(
            "chat_turn_preflight_ack",
            {
                "turn_id": payload["turn_id"],
                "preflight_id": "synthetic-preflight",
                "committed_messages_v": 1,
            },
        )
        socket.send(
            "chat_message_confirmed",
            {
                "chat_id": self.chat_id,
                "message_id": payload["message_id"],
                "new_messages_v": 1,
            },
        )
        socket.send(
            "ai_task_initiated",
            {
                "chat_id": self.chat_id,
                "user_message_id": payload["message_id"],
                "task_id": "synthetic-task",
            },
        )
        socket.send(
            "ai_message_update",
            {
                "chat_id": self.chat_id,
                "user_message_id": payload["message_id"],
                "task_id": "synthetic-task",
                "message_id": self.protocol["assistant_id"],
                "full_content_so_far": self.protocol["transient_content"],
                "is_final_chunk": True,
                "recovery_protocol_version": 1,
                "recovery_turn_id": payload["turn_id"],
                "recovery_job_id": self.protocol["job_id"],
                "created_at": 1,
            },
        )
        socket.send("recovery_outputs_discovery_complete", {"status": "completed"})

    def claim(self, socket, payload):
        self.counts["claims"] += 1
        assert (
            payload["protocol_version"] == 1
            and payload["job_id"] == self.protocol["job_id"]
        )
        assert uuid.UUID(payload["request_id"]).version == 4
        self.mark("lease-claim")
        if self.vector["mode"] == "cancel":
            return
        turn = self.admission["turn_id"]
        claim = {
            "job_id": self.protocol["job_id"],
            "request_id": payload["request_id"],
            "chat_id": self.chat_id,
            "turn_id": turn,
            "assistant_message_id": self.protocol["assistant_id"],
            "chat_key_version": 1,
            "state": "LEASED",
            "lease_token": self.protocol["lease_token"],
            "lease_generation": self.protocol["lease_generation"],
        }
        if self.vector["mode"] == "terminal":
            claim["state"] = "TERMINAL"
            self.messages = [self.canonical(self.protocol["canonical_content"])]
        else:
            identity = [
                self.account["owner_id"],
                self.chat_id,
                turn,
                self.protocol["job_id"],
                self.protocol["assistant_id"],
            ]
            content = {
                "assistant_message_id": self.protocol["assistant_id"],
                "chat_id": self.chat_id,
                "turn_id": turn,
                "job_id": self.protocol["job_id"],
                "key_version": 1,
                "content": self.protocol["sealed_content"],
                "category": None,
                "model_name": None,
            }
            claim["sealed_payload"] = json.dumps(
                seal(
                    self.admission["recovery_public_key"],
                    identity,
                    content,
                    self.vector["mode"] == "bad_envelope",
                )
            )
            if self.vector["mode"] == "bad_lease":
                claim["lease_generation"] = 0
            elif self.vector["mode"] == "bad_identity":
                claim["turn_id"] = "99999999-9999-4999-8999-999999999999"
        socket.send("recovery_job_claimed", claim)

    def persist(self, socket, payload):
        self.counts["persists"] += 1
        assert payload["job_id"] == self.protocol["job_id"]
        assert payload["lease_token"] == self.protocol["lease_token"]
        assert payload["lease_generation"] == self.protocol["lease_generation"]
        assert payload["expected_messages_v"] == self.protocol["fresh_messages_v"]
        message = payload["encrypted_assistant_message"]
        assert (
            message["chat_id"] == self.chat_id
            and message["client_message_id"] == self.protocol["assistant_id"]
        )
        assert (
            decrypt(message["encrypted_content"], self.key).decode()
            == self.protocol["sealed_content"]
        )
        assert self.protocol["sealed_content"] not in json.dumps(payload)
        self.mark("fenced-encrypted-persist")
        if self.vector["mode"] == "persist_error":
            socket.send(
                "error",
                {"code": "conflict", "message": "synthetic-private-server-diagnostic"},
            )
            return
        self.messages = [message]
        self.mark("canonical-commit")
        if self.vector["mode"] != "lost_ack":
            socket.send(
                "recovery_job_persisted",
                {
                    "job_id": self.protocol["job_id"],
                    "state": "TERMINAL",
                    "committed_messages_v": self.protocol["fresh_messages_v"] + 1,
                },
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--identity", required=True, choices=["rust", "npm", "pip"])
    args = parser.parse_args()
    suite = json.loads(Path(args.fixture).read_bytes())["capabilities"][CAPABILITY]
    vector = next(item for item in suite["vectors"] if item["id"] == args.vector)
    peer = RecoveryPeer(suite, vector, args.identity)
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    peer.server.serve_forever()


if __name__ == "__main__":
    main()
