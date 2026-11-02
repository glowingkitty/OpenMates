"""Independent history wire oracle. No SDK imports, key unwrap or account IO."""

# contract-test-file: tooling
from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

CAPABILITY = "sdk.history"


class HistoryPeer:
    def __init__(self, suite, vector, language):
        self.suite, self.vector, self.language = suite, vector, language
        self.requests = 0
        self.failure = None

    def dispatch(self, method, path, headers, body):
        self.requests += 1
        try:
            assert self.requests == 1, "duplicate/retried request"
            headers = {key.lower(): value for key, value in headers.items()}
            setup = self.suite["api_keys"][self.vector["owner"]]
            assert headers.get("authorization") == "Bearer " + setup.split(".", 1)[0], (
                "explicit owner bearer"
            )
            assert (
                headers.get("x-openmates-device-identity") == self.suite["device_id"]
            ), "explicit device"
            assert (
                headers.get("x-openmates-sdk")
                == {"rust": "rust", "npm": "npm", "python": "pip"}[self.language]
            ), "library identity"
            for key in (
                "cookie",
                "x-session-id",
                "x-openmates-anonymous-id",
                "x-openmates-task-owner",
                "x-openmates-task-actor",
            ):
                assert key not in headers, "credential/owner mixing"
            assert setup.split(".", 1)[1] not in json.dumps([headers, path, body]), (
                "setup suffix leaked"
            )
            parts = urlsplit(path)
            assert not parts.fragment and not parts.netloc and not parts.scheme
            op = self.vector["operation"]
            assert method == ("POST" if op == "undo" else "GET"), "method"
            prefix = "/v1/workspace/history"
            if op == "list":
                assert parts.path == prefix, "no bootstrap or alternate route"
                expected = (
                    self.vector.get("npm_expected_query", self.vector["expected_query"])
                    if self.language == "npm"
                    else self.vector["expected_query"]
                )
                assert parse_qs(parts.query, keep_blank_values=True) == expected, (
                    "exact filters/no Team or owner override"
                )
            else:
                assert not parts.query, "unexpected query"
                tail = "/undo" if op == "undo" else ""
                assert parts.path.startswith(prefix + "/") and (
                    not tail or parts.path.endswith(tail)
                ), "resource route"
                encoded = parts.path[
                    len(prefix) + 1 : len(parts.path) - len(tail) if tail else None
                ]
                assert (
                    "/" not in encoded
                    and unquote(encoded) == self.vector["change_set_id"]
                ), "one encoded ID segment"
            assert body == ({} if op == "undo" else None), (
                "empty undo object/no snapshot submission"
            )
            return self.vector["http_status"], self.vector["response"]
        except AssertionError as error:
            self.failure = str(error)
            return 400, {"detail": "synthetic history protocol refusal"}

    def server(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def handle_request(self):
                self.connection.settimeout(2)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    assert 0 <= length <= 65536
                    raw = self.rfile.read(length)
                    body = json.loads(raw) if raw else None
                    status, response = peer.dispatch(
                        self.command, self.path, dict(self.headers), body
                    )
                except Exception:
                    peer.failure = "invalid bounded JSON request"
                    status, response = (
                        400,
                        {"detail": "synthetic history protocol refusal"},
                    )
                data = json.dumps(
                    response, separators=(",", ":"), ensure_ascii=False
                ).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            do_GET = handle_request
            do_POST = handle_request
            do_PATCH = handle_request
            do_DELETE = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.block_on_close = False
        return server
