"""Independent synthetic proxy oracle. Never imports SDK, provider or learning code."""

# contract-test-file: tooling
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs


class WikipediaPeer:
    def __init__(self, suite, vector, language, iterations=1):
        self.suite, self.vector, self.language = suite, vector, language
        self.iterations, self.requests, self.failure = iterations, 0, None

    def dispatch(self, method, path, headers, body):
        self.requests += 1
        try:
            steps = self.vector["steps"]
            assert not self.vector["anonymous"] and steps
            assert self.requests <= len(steps) * self.iterations, (
                "retry or extra inference"
            )
            step = steps[(self.requests - 1) % len(steps)]
            h = {k.lower(): v for k, v in headers.items()}
            key = self.suite["api_key"]
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
            assert (
                not u.scheme
                and not u.netloc
                and not u.fragment
                and u.path == "/v1/wikipedia/" + step["operation"]
            )
            # Contract: an omitted or empty language is sent as "en" by every SDK;
            # the backend proxy rejects an empty language (min_length=2).
            language = self.vector["language"] or "en"
            query = {"language": [language]}
            if step["operation"] == "search":
                query["query"] = [self.vector["query"]]
                if self.vector["limit"] is not None:
                    query["limit"] = [str(self.vector["limit"])]
            else:
                query["title"] = [step["expected_title"]]
            assert parse_qs(u.query, keep_blank_values=True) == query, (
                "exact proxy params/no model/provider override"
            )
            return step["http_status"], step["response"]
        except AssertionError:
            self.failure = "wikipedia wire refusal"
            return 400, {"detail": "closed synthetic Wikipedia refusal"}

    def server(self):
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.connection.settimeout(2)
                try:
                    assert int(self.headers.get("Content-Length", "0")) == 0
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
