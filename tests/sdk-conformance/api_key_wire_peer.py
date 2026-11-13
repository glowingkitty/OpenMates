"""Independent synthetic peer for the API-key billing + memories wire vectors.

No listener on import. Each vector gets a fresh peer that serves only its
declared routes, in order (exact method, path including query, JSON body), plus
at most one lazy `/v1/sdk/session` exchange. It checks the credential boundary
on every request: bearer component only (or no credential for public reads),
SDK name, device identity, no cookie/session headers, and the local setup
suffix never leaves the client. Raw routes answer with declared bytes/headers.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlsplit

SDK_HEADER = {"rust": "rust", "npm": "npm", "python": "pip"}
MAX_REQUEST = 65536


class WirePeer:
    def __init__(self, suite: dict, vector: dict, language: str):
        assert language in SDK_HEADER
        self.suite, self.vector, self.language = suite, vector, language
        self.routes = 0
        self.sessions = 0
        self.failure: str | None = None

    def _credentials(self, headers: dict, path: str, body, auth: str) -> None:
        h = {key.lower(): value for key, value in headers.items()}
        bearer, suffix = self.suite["api_key"].split(".", 1)
        if auth == "public":
            assert "authorization" not in h, "public read carries no credential"
        else:
            assert h.get("authorization") == "Bearer " + bearer, "bearer component only"
            assert h.get("x-openmates-sdk") == SDK_HEADER[self.language]
            assert h.get("x-openmates-device-identity") == self.suite["device_id"]
        assert not set(h).intersection({"cookie", "x-session-id", "x-openmates-anonymous-id"})
        assert suffix not in json.dumps([h, path, body]), "setup suffix stays local"

    def dispatch(self, method: str, path: str, headers: dict, body):
        """Return (status, headers, bytes) for one request; failures are recorded."""
        try:
            if urlsplit(path).path == "/v1/sdk/session":
                self._credentials(headers, path, body, "bearer")
                assert method == "POST" and self.vector["session"] and self.sessions == 0, "single lazy key session"
                assert body == {"sdk_name": SDK_HEADER[self.language], "device_identity": self.suite["device_id"]}
                self.sessions += 1
                return _json(200, deepcopy(self.suite["session"]))
            assert self.routes < len(self.vector["routes"]), "no undeclared request or retry"
            route = self.vector["routes"][self.routes]
            self._credentials(headers, path, body, route["auth"])
            assert (method, path) == (route["method"], route["path"]), f"exact route/order: {method} {path}"
            assert body == route["body"], "exact JSON body"
            self.routes += 1
            response = route["response"]
            if "json" in response:
                return _json(route["status"], deepcopy(response["json"]))
            return route["status"], dict(response["headers"]), base64.b64decode(response["raw_b64"])
        except AssertionError as error:
            self.failure = self.failure or f"wire protocol refused: {error}"
            return _json(400, {"detail": "synthetic wire refusal"})

    def check(self, observed: dict) -> None:
        v = self.vector
        assert self.failure is None, self.failure
        assert self.routes == len(v["routes"]), "every declared route served"
        assert self.sessions == (1 if v["session"] else 0), "single lazy key session"
        if v["expected_error"]:
            assert observed == {"ok": False, "error": v["expected_error"]}, observed
        else:
            assert observed == {"ok": True, "value": v["expected"]}, observed

    def server(self) -> ThreadingHTTPServer:
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def handle_request(self):
                self.connection.settimeout(2)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    assert 0 <= length <= MAX_REQUEST
                    raw = self.rfile.read(length)
                    body = json.loads(raw) if raw else None
                    status, headers, data = peer.dispatch(self.command, self.path, dict(self.headers), body)
                except (AssertionError, ValueError):
                    peer.failure = peer.failure or "invalid bounded JSON request"
                    status, headers, data = _json(400, {"detail": "synthetic wire refusal"})
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.block_on_close = False
        return server


def _json(status: int, value) -> tuple[int, dict, bytes]:
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return status, {"Content-Type": "application/json"}, data


def error_code(status: int) -> str:
    """Language-neutral code for an HTTP error status (Rust `Error` mapping)."""
    return {401: "authentication", 403: "forbidden", 409: "conflict"}.get(status) or (
        "invalid" if status in (400, 404, 410, 422) else "offline" if status == 429 or status >= 500 else "protocol"
    )
