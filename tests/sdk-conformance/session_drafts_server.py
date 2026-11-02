"""Independent synthetic Cookie draft peer. Constructing state opens no socket;
start() is used only by explicitly executed isolated conformance. No product IO."""

from copy import deepcopy
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
from urllib.parse import parse_qs, urlsplit
from recovery_server import WebSocket

CAPABILITY = "session.drafts.v1"


class SessionDraftPeer:
    def __init__(self, suite, vector, identity):
        assert identity in ("rust", "npm", "pip")
        self.suite, self.vector, self.identity = suite, vector, identity
        self.counts = dict(http=0, ws=0, versions=0, phase2=0, lifecycle=0)
        self.gets = 0
        self.failure = None
        self.server = None
        self.thread = None

    def headers(self, headers):
        values = {key.lower(): value for key, value in headers.items()}
        assert (
            values.get("cookie")
            == "auth_refresh_token=" + self.suite["account"]["cookie"]
        )
        assert values.get("x-openmates-sdk") == self.identity
        assert values.get("origin") == self.suite["protocol"]["app_origin"]
        assert not set(values).intersection(
            {
                "authorization",
                "x-openmates-anonymous-id",
                "x-openmates-task-owner",
                "x-openmates-task-actor",
            }
        )

    def record(self, metadata=False):
        name = (
            "corrupt_preview"
            if self.vector["mode"] == "corrupt-preview"
            else "updated"
            if self.vector["mode"] == "updated"
            else "base"
        )
        value = deepcopy(self.suite["records"][name])
        if self.vector["preflight_get"] and self.gets == 1 and not metadata:
            value = deepcopy(self.suite["records"]["base"])
        return value

    def http(self, method, path, headers, body):
        self.headers(headers)
        self.counts["http"] += 1
        if method == "POST":
            assert path == "/v1/auth/session" and body == {
                "session_id": self.suite["account"]["session_id"]
            }
            return 200, {
                "success": True,
                "ws_token": "synthetic-drafts-ws",
                "user": {"id": self.suite["account"]["owner_id"]},
            }
        assert (
            method == "GET"
            and path == "/v1/drafts/" + self.suite["protocol"]["chat_id"]
            and body is None
        )
        self.gets += 1
        if self.vector["mode"] == "network-fallback":
            return None
        if self.vector["mode"].startswith("http-"):
            return int(self.vector["mode"].split("-")[1]), {
                "detail": "synthetic refusal"
            }
        if self.vector["mode"] == "missing":
            return 200, {"draft": None}
        record = self.record()
        wire = {
            k: record[k]
            for k in (
                "chat_id",
                "encrypted_draft_md",
                "encrypted_draft_preview",
                "draft_v",
            )
        }
        if self.vector["mode"] == "foreign-owner":
            wire["user_id"] = "different-owner"
        if self.vector["mode"] == "regressed" and self.gets > 1:
            wire["draft_v"] = 3
        return 200, {"draft": wire}

    def event(self, kind, payload):
        if kind == "native_client_lifecycle":
            assert (
                payload["client_type"] == self.identity
                and payload["interactive"] is False
            )
            self.counts["lifecycle"] += 1
            return []
        if kind == "get_draft_versions":
            self.counts["versions"] += 1
            chats = payload["chats"]
            assert 1 <= len(chats) <= 200 and {row["chat_id"] for row in chats} == {
                self.suite["protocol"]["chat_id"]
            }
            version = 0 if self.vector["mode"] == "deleted" else 4
            result = {"versions": {self.suite["protocol"]["chat_id"]: version}}
            if not version:
                result["tombstone_versions"] = {self.suite["protocol"]["chat_id"]: 5}
            return [("draft_versions_response", result)]
        assert kind == "phased_sync_request", (
            "no active-chat, history, job claim or inference operation"
        )
        assert (
            payload["phase"] == "phase2"
            and payload["client_chat_ids"] == []
            and payload["client_chat_versions"] == {}
            and payload.get("team_id") is None
        )
        epoch = payload["context_epoch"]
        assert type(epoch) is int and 2 <= epoch < 2**53
        if self.vector["mode"] == "network-fallback":
            assert payload["refresh_chat_ids"] == [self.suite["protocol"]["chat_id"]]
        self.counts["phase2"] += 1
        record = self.record(metadata=True)
        row = {
            "id": record["chat_id"],
            "user_id": self.suite["account"]["owner_id"],
            "messages_v": 7,
            **{
                k: record[k]
                for k in ("encrypted_draft_md", "encrypted_draft_preview", "draft_v")
            },
        }
        common = {"phase": "phase2", "context_epoch": epoch, "team_id": None}
        return [
            (
                "phase_2_last_20_chats_ready",
                {**common, "chats": [{"chat_details": row}]},
            ),
            ("phased_sync_complete", common),
        ]

    def start(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def reply(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    assert 0 <= length <= 65536
                    value = json.loads(self.rfile.read(length)) if length else None
                    status, body = peer.http(
                        "POST", self.path, dict(self.headers), value
                    )
                    self.reply(status, body)
                except Exception:
                    peer.failure = "bounded HTTP/auth request refused"
                    self.reply(500, {})

            def do_GET(self):
                try:
                    route = urlsplit(self.path)
                    if route.path == "/v1/ws":
                        peer.headers(dict(self.headers))
                        query = parse_qs(route.query)
                        assert query["token"] == ["synthetic-drafts-ws"]
                        caps = query["client_capabilities"][0]
                        assert (
                            "task_update_jobs" not in caps
                            and "chat_metadata_recovery" not in caps
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
                        peer.counts["ws"] += 1
                        self.connection.settimeout(5)
                        ws = WebSocket(self)
                        try:
                            while (event := ws.receive()) is not None:
                                for kind, payload in peer.event(
                                    event["type"], event["payload"]
                                ):
                                    ws.send(kind, payload)
                        except (EOFError, ConnectionError, socket.timeout):
                            pass
                        finally:
                            self.close_connection = True
                    else:
                        result = peer.http("GET", self.path, dict(self.headers), None)
                        if result is None:
                            self.close_connection = True
                            self.connection.shutdown(socket.SHUT_RDWR)
                            return
                        self.reply(*result)
                except Exception:
                    peer.failure = "Cookie draft route/protocol refused"
                    self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        self.thread.start()
        return self

    @property
    def endpoint(self):
        return "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
            assert not self.thread.is_alive()
