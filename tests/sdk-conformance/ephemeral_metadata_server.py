"""Independent no-key protocol peer. Only synthetic cookie auth and ciphertext DATA.

No Master, crypto operation, account, persistent profile or SDK implementation.
The existing bounded WebSocket fixture parser is reused without RecoveryPeer.
"""

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from recovery_server import WebSocket

CAPABILITY = "session.ephemeral-metadata-startup.v1"


class MetadataPeer:
    def __init__(self, suite, vector, identity):
        self.suite, self.vector, self.identity = suite, vector, identity
        self.counts = {
            "auth_requests": 0,
            "connections": 0,
            "startup_requests": 0,
            "metadata_requests": 0,
            "disconnects": 0,
            "unexpected": 0,
        }
        self.failure = None
        self.closed = threading.Event()
        self.cookies = {suite["account"]["cookie"]}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.server.daemon_threads = True
        self.thread = None
        self.auth_release = threading.Event()
        self.auth_finished = threading.Event()
        self.auth_events = []
        self.auth_active = 0

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.auth_release.set()
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3)

    def status(self):
        return {
            **self.counts,
            "failure": self.failure,
            "auth_events": list(self.auth_events),
            "auth_active": self.auth_active,
        }

    def row(self, chat_id=None):
        return {
            "id": chat_id or self.suite["protocol"]["initial_chat_id"],
            "encrypted_title": "opaque-not-a-key-or-decrypted-title",
            "messages_v": 1,
            "opaqueUserMetadata": {"camelCase": {"projectId": "雪"}},
        }

    def handler(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def reply(self, status, value, rotation=None):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if rotation:
                    self.send_header(
                        "Set-Cookie",
                        f"auth_refresh_token={rotation}; HttpOnly; Path=/; SameSite=Lax; Max-Age={0 if peer.vector['mode'] == 'expired' else 3600}",
                    )
                self.end_headers()
                self.wfile.write(raw)
                self.wfile.flush()

            def checked(self):
                assert self.headers.get("X-OpenMates-SDK") == peer.identity
                assert (
                    self.headers.get("Origin") == peer.suite["protocol"]["app_origin"]
                )
                assert any(
                    f"auth_refresh_token={cookie}" == self.headers.get("Cookie")
                    for cookie in peer.cookies
                )

            def do_POST(self):
                actual_auth = False
                try:
                    assert self.path == "/v1/auth/session"
                    self.checked()
                    length = int(self.headers["Content-Length"])
                    assert length < 4096
                    assert json.loads(self.rfile.read(length)) == {
                        "session_id": peer.suite["account"]["session_id"]
                    }
                    peer.counts["auth_requests"] += 1
                    n = peer.counts["auth_requests"]
                    mode = peer.vector["mode"]
                    actual_auth = True
                    peer.auth_active += 1
                    peer.auth_events.append("request")
                    rotation = f"synthetic-rotation-{n}"
                    peer.cookies = {rotation}
                    if mode in {
                        "late_invalid_cookie",
                        "late_undecodable_cookie",
                        "malformed_body",
                        "truncated_body",
                        "held_malformed_body",
                        "cancel_before_headers",
                        "cancel_after_headers",
                        "foreign_auth_cancel",
                        "early_invalid_cookie",
                        "early_undecodable_cookie",
                    }:
                        self.special_auth(mode, rotation)
                        return
                    if mode == "denied" or mode == "rotation_failure" and n == 2:
                        self.reply(401, {"success": False}, rotation)
                        return
                    owner = peer.suite["account"]["owner_id"]
                    if mode == "changed_principal" and n == 2:
                        owner = "99999999-9999-4999-8999-999999999999"
                    user = (
                        {"id": owner}
                        if mode != "malformed"
                        else {"username": "not-authority"}
                    )
                    self.reply(
                        200,
                        {
                            "success": True,
                            "user": user,
                            "ws_token": "synthetic-authenticated-websocket-token",
                        },
                        rotation,
                    )
                except Exception as error:
                    peer.failure = type(error).__name__
                    self.reply(500, {"success": False})
                finally:
                    if actual_auth:
                        peer.auth_active -= 1
                        peer.auth_finished.set()

            def special_auth(self, mode, rotation):
                # Real HTTP barriers, controlled only by the external fixture
                # adapter. No caller flag or receipt is consumed by the SDK.
                if mode == "cancel_before_headers":
                    peer.auth_events.append("before_headers_held")
                    assert peer.auth_release.wait(8), "bounded auth header release"
                    peer.auth_events.append("released")
                good = json.dumps(
                    {
                        "success": True,
                        "user": {"id": peer.suite["account"]["owner_id"]},
                        "ws_token": "synthetic-authenticated-websocket-token",
                    }
                ).encode()
                malformed = mode in {"malformed_body", "held_malformed_body"}
                raw = b'{"success":' if malformed or mode == "truncated_body" else good
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header(
                    "Content-Length",
                    str(len(raw) + (17 if mode == "truncated_body" else 0)),
                )
                if mode == "early_invalid_cookie":
                    self.send_header("Set-Cookie", "preference.v1=1")
                if mode == "early_undecodable_cookie":
                    self.send_header("Set-Cookie", "preference=\xff")
                self.send_header(
                    "Set-Cookie",
                    f"auth_refresh_token={rotation}; HttpOnly; Path=/; Max-Age=3600",
                )
                if mode == "late_invalid_cookie":
                    self.send_header("Set-Cookie", "preference.v1=1")
                if mode == "late_undecodable_cookie":
                    self.send_header("Set-Cookie", "preference=\xff")
                self.end_headers()
                self.wfile.flush()
                peer.auth_events.append("headers_flushed")
                if mode in {
                    "held_malformed_body",
                    "cancel_after_headers",
                    "foreign_auth_cancel",
                }:
                    peer.auth_events.append("body_held")
                    assert peer.auth_release.wait(8), "bounded auth body release"
                    peer.auth_events.append("released")
                try:
                    self.wfile.write(raw)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    # Header refusal may retire this original before body IO.
                    assert mode in {
                        "late_invalid_cookie",
                        "late_undecodable_cookie",
                        "early_invalid_cookie",
                        "early_undecodable_cookie",
                    }
                peer.auth_events.append(
                    "body_truncated" if mode == "truncated_body" else "body_written"
                )
                if mode == "truncated_body":
                    self.close_connection = True

            def do_GET(self):
                try:
                    route = urlsplit(self.path)
                    if route.path == "/__test/status":
                        self.reply(200, peer.status())
                        return
                    if route.path == "/__test/release-auth":
                        peer.auth_release.set()
                        self.reply(200, {"released": True})
                        return
                    assert (
                        route.path == "/v1/ws"
                        and self.headers.get("Upgrade", "").lower() == "websocket"
                    )
                    self.checked()
                    query = parse_qs(route.query)
                    assert query["token"] == ["synthetic-authenticated-websocket-token"]
                    assert "sessionId" in query
                    assert query["client_capabilities"] == [
                        "canonical_embed_receipts_v1,typed_recovery_outputs_v2,agentic-storage-v2"
                    ]
                    accept = base64.b64encode(
                        hashlib.sha1(
                            (
                                self.headers["Sec-WebSocket-Key"]
                                + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                            ).encode()
                        ).digest()
                    ).decode()
                    self.send_response(101)
                    self.send_header("Upgrade", "websocket")
                    self.send_header("Connection", "Upgrade")
                    self.send_header("Sec-WebSocket-Accept", accept)
                    self.end_headers()
                    peer.websocket(WebSocket(self))
                except (EOFError, BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    peer.failure = type(error).__name__

        return Handler

    def websocket(self, socket):
        self.counts["connections"] += 1
        socket.handler.connection.settimeout(5)
        epoch = None
        terminal = False
        try:
            while (frame := socket.receive()) is not None:
                kind, payload = frame["type"], frame["payload"]
                if kind == "native_client_lifecycle":
                    assert payload == {
                        "client_type": self.identity,
                        "is_foreground": False,
                        "interactive": False,
                    }
                    socket.send(
                        "recovery_outputs_discovery_complete", {"status": "disabled"}
                    )
                elif kind == "phased_sync_request":
                    self.counts["startup_requests"] += 1
                    assert self.counts["startup_requests"] == 1
                    epoch = payload["context_epoch"]
                    assert type(epoch) is int and epoch > 0
                    assert payload == {
                        "phase": "all",
                        "context_epoch": epoch,
                        "client_chat_versions": {},
                        "client_chat_ids": [],
                        "client_embed_ids": [],
                    }
                    common = {"context_epoch": epoch, "team_id": None}
                    if self.vector["mode"] == "phase1":
                        rows = [self.row()] + [
                            self.row(f"30000000-0000-4000-8000-{n:012}")
                            for n in range(1, 25)
                        ]
                        rows.append(
                            {
                                **self.row("60000000-0000-4000-8000-000000000001"),
                                "parent_id": rows[0]["id"],
                                "is_sub_chat": True,
                            }
                        )
                        socket.send(
                            "phase_1_last_chat_ready",
                            {**common, "recent_chat_metadata": rows},
                        )
                    socket.send(
                        "phase_2_last_20_chats_ready",
                        {
                            **common,
                            "total_chat_count": self.vector.get(
                                "total_chat_count", 1234
                            ),
                            "chats": [{"chat_details": self.row()}],
                        },
                    )
                    socket.send("phase_3_chunk_ready", {**common, "chats": []})
                    socket.send("phased_sync_complete", {**common, "phase": "all"})
                    terminal = True
                elif kind == "sync_metadata_chats":
                    self.counts["metadata_requests"] += 1
                    assert terminal and self.counts["metadata_requests"] == 1
                    assert payload == {"context_epoch": epoch, "existing_chat_ids": []}
                    if self.vector["mode"] == "cancel_inflight":
                        continue
                    page = {
                        "context_epoch": epoch,
                        "team_id": None,
                        "total_count": 1234,
                        "chats": [
                            {
                                "chat_details": self.row(
                                    "70000000-0000-4000-8000-000000000001"
                                )
                            }
                        ],
                    }
                    if self.vector["mode"] == "foreign_epoch":
                        socket.send(
                            "sync_metadata_chats_response",
                            {
                                **page,
                                "context_epoch": epoch - 1,
                                "chats": [
                                    {
                                        "chat_details": self.row(
                                            "80000000-0000-4000-8000-000000000001"
                                        )
                                    }
                                ],
                            },
                        )
                    if self.vector["mode"] == "foreign_team":
                        page["team_id"] = "99999999-9999-4999-8999-999999999999"
                    socket.send("sync_metadata_chats_response", page)
                else:
                    self.counts["unexpected"] += 1
                    raise AssertionError(
                        "metadata mode cannot claim, ACK, write or fetch private content"
                    )
        except (EOFError, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.counts["disconnects"] += 1
            self.closed.set()
