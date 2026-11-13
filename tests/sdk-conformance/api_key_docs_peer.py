"""Independent bounded wire oracle, no SDK imports, account or provider IO."""

# contract-test-file: tooling
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote


class DocsPeer:
    def __init__(self, suite, vector, language, iterations=1):
        self.suite, self.vector, self.language = suite, vector, language
        self.iterations, self.requests, self.failure = iterations, 0, None

    def dispatch(self, method, path, headers, body):
        self.requests += 1
        try:
            assert self.requests <= self.iterations, "unexpected retry/request"
            h = {k.lower(): v for k, v in headers.items()}
            key = self.suite["api_key"]
            assert not self.vector["anonymous"], "anonymous request forbidden"
            assert self.vector["expected_request_count"] > 0, (
                "locally refused slug reached transport"
            )
            assert h.get("authorization") == "Bearer " + key.split(".")[0]
            assert h.get("x-openmates-device-identity") == self.suite["device_id"]
            assert (
                h.get("x-openmates-sdk")
                == {"rust": "rust", "npm": "npm", "python": "pip"}[self.language]
            )
            assert all(
                k not in h
                for k in (
                    "cookie",
                    "x-session-id",
                    "x-openmates-anonymous-id",
                    "x-openmates-task-owner",
                    "x-openmates-task-actor",
                )
            )
            assert key.split(".")[1] not in json.dumps([h, path, body]), (
                "setup secret leaked"
            )
            assert method == "GET" and body is None
            u = urlsplit(path)
            assert not u.scheme and not u.netloc and not u.fragment
            op = self.vector["operation"]
            prefix = "/v1/sdk/docs"
            if op == "list":
                assert u.path == prefix and not u.query
            elif op == "search":
                assert u.path == prefix + "/search" and parse_qs(
                    u.query, keep_blank_values=True
                ) == {"q": [self.vector["query"]]}
            else:
                suffix = "/download" if op == "download" else ""
                assert not u.query
                assert u.path.startswith(prefix + "/") and (
                    not suffix or u.path.endswith(suffix)
                )
                encoded = u.path[
                    len(prefix) + 1 : len(u.path) - len(suffix) if suffix else None
                ]
                assert "/" not in encoded and unquote(encoded) == self.vector["slug"]
            return self.vector["http_status"], self.vector["response"]
        except AssertionError:
            self.failure = "docs wire refusal"
            return 400, {"detail": "closed synthetic docs refusal"}

    def server(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.connection.settimeout(2)
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    assert size == 0
                    status, value = peer.dispatch(
                        self.command, self.path, dict(self.headers), None
                    )
                except Exception:
                    peer.failure = "bounded request refusal"
                    status, value = 400, {"detail": "closed request refusal"}
                data = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":")
                ).encode()
                assert len(data) <= 1024 * 1024
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

        return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
