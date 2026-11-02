#!/usr/bin/env python3
"""Independent fixed-route synthetic peer; never imports a product SDK."""

# contract-test-file: tooling
from __future__ import annotations
import argparse
import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CAPABILITY = "session.settings-reminders-read"


def validate_request(method, path, headers, cookie, identity):
    if method != "GET" or path != "/v1/settings/reminders":
        raise AssertionError("fixed settings request required")
    pairs = [(name.lower(), value) for name, value in headers]

    def values(name):
        return [value for key, value in pairs if key == name]

    if values("cookie") != [f"auth_refresh_token={cookie}"]:
        raise AssertionError("original settings credential required")
    if values("x-openmates-sdk") != [identity]:
        raise AssertionError("exact SDK identity required")
    for name, _ in pairs:
        if name in {
            "authorization",
            "x-api-key",
            "api-key",
            "x-team-id",
            "content-type",
            "content-length",
            "transfer-encoding",
        } or name.startswith("x-openmates-team"):
            raise AssertionError("unexpected settings request authority or body")
    if sum(len(k) + len(v) + 4 for k, v in pairs) + len(method) + len(path) > 8192:
        raise AssertionError("bounded settings request required")


def wire_response(response):
    status = response["status"]
    body = response["body"].encode("utf-8")
    headers = response["headers"]
    if type(status) is not int or not 100 <= status <= 999 or len(body) > 1024 * 1024:
        raise AssertionError("invalid fixed fixture response")
    for key, value in headers:
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or any(c in key + value for c in "\r\n")
        ):
            raise AssertionError("unsafe fixture response header")
    head = f"HTTP/1.1 {status} Fixture\r\nConnection: close\r\n"
    if not any(key.lower() == "content-length" for key, _ in headers):
        head += f"Content-Length: {len(body)}\r\n"
    head += "".join(f"{key}: {value}\r\n" for key, value in headers) + "\r\n"
    return head.encode("ascii") + body


class SettingsPeer:
    def __init__(self, case, identity):
        if identity not in {"npm", "pip"}:
            raise ValueError("synthetic foreign SDK identity required")
        self.case, self.identity = case, identity
        self.cookie = "fixture"
        self.requests = 0
        self.times = []
        self.failure = None
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.released = threading.Event()
        if case.get("action") not in {
            None,
            "truncate_body",
            "cancel_body",
            "cancel_retry",
        }:
            raise ValueError("exact shared action required")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path == "/__test/entered" and self.command == "GET":
                    if not owner.ready.wait(timeout=5):
                        with owner.lock:
                            owner.failure = "fixture_phase_deadline"
                if self.path == "/__test/release" and self.command == "POST":
                    owner.released.set()
                if (
                    self.path in {"/__test/status", "/__test/entered"}
                    and self.command == "GET"
                ) or (self.path == "/__test/release" and self.command == "POST"):
                    raw = json.dumps(owner.status()).encode()
                    self.connection.sendall(
                        b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                        + str(len(raw)).encode()
                        + b"\r\n\r\n"
                        + raw
                    )
                    self.close_connection = True
                    return
                try:
                    if self.client_address[0] != "127.0.0.1":
                        raise AssertionError("loopback peer required")
                    with owner.lock:
                        validate_request(
                            self.command,
                            self.path,
                            self.headers.raw_items(),
                            owner.cookie,
                            owner.identity,
                        )
                        index = owner.requests
                        if index >= owner.case["expected"]["requests"] or index >= len(
                            owner.case["responses"]
                        ):
                            raise AssertionError("unexpected extra settings request")
                        response = owner.case["responses"][index]
                        owner.requests += 1
                        owner.times.append(time.monotonic_ns())
                        for key, value in response["headers"]:
                            if key.lower() == "set-cookie" and value.startswith(
                                "auth_refresh_token=rotated;"
                            ):
                                owner.cookie = "rotated"
                    try:
                        wire = wire_response(response)
                        if owner.case.get("action") == "cancel_body":
                            head, body = wire.split(b"\r\n\r\n", 1)
                            self.connection.sendall(head + b"\r\n\r\n")
                            owner.ready.set()
                            if not owner.released.wait(timeout=5):
                                raise AssertionError("fixture body release deadline")
                            self.connection.sendall(body)
                        else:
                            self.connection.sendall(wire)
                            if owner.case.get("action") == "cancel_retry":
                                owner.ready.set()
                                if not owner.released.wait(timeout=5):
                                    raise AssertionError(
                                        "fixture retry release deadline"
                                    )
                    except (BrokenPipeError, ConnectionResetError):
                        # A legitimate header/body-bound guard may close first.
                        pass
                except Exception:
                    with owner.lock:
                        owner.failure = "settings_peer_protocol_refused"
                    try:
                        self.connection.sendall(
                            b"HTTP/1.1 500 Refused\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                        )
                    except OSError:
                        pass
                finally:
                    self.close_connection = True

            do_POST = do_GET
            do_PUT = do_GET
            do_DELETE = do_GET

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True
        )

    def start(self):
        self.thread.start()
        return self

    def status(self):
        with self.lock:
            return {
                "requests": self.requests,
                "times_ns": list(self.times),
                "cookie": self.cookie,
                "failure": self.failure,
            }

    def close(self):
        self.released.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise AssertionError("fixture peer did not close")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--identity", choices=["npm", "pip"], required=True)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("bounded shared fixture required")
    suite = json.loads(raw)
    if suite["capability"] != CAPABILITY:
        raise ValueError("exact reminders capability required")
    cases = [case for case in suite["cases"] if case["id"] == args.case]
    if len(cases) != 1:
        raise ValueError("exact shared case required")
    peer = SettingsPeer(cases[0], args.identity).start()
    finished = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: finished.set())
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        finished.wait()
    finally:
        peer.close()


if __name__ == "__main__":
    main()
