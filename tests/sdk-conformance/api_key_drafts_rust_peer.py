#!/usr/bin/env python3
"""Offline synthetic Rust facade coordinator. No products, accounts or inference."""

import argparse
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

CAPABILITY = "sdk.drafts"


def responses(suite, vector):
    raw = suite["vectors"][0]["draft"]
    kind = vector["kind"]

    def get(value):
        return ("GET", "/v1/sdk/drafts/" + raw["chat_id"], 200, {"draft": value})

    def session(value):
        return ("POST", "/v1/sdk/session", 200, value)

    if kind == "record":
        raw = vector["draft"]
        return [
            ("GET", "/v1/sdk/drafts", 200, {"drafts": [raw]}),
            get(raw),
            ("GET", "/v1/sdk/drafts", 200, {"drafts": [raw]}),
            session(suite["session"]),
            get(raw),
            ("GET", "/v1/sdk/drafts/missing", 200, {"draft": None}),
        ]
    if kind == "wrong-account-key":
        return [get(raw), session(suite["wrong_account_session"])]
    if kind == "project-grant-not-account-key":
        return [get(raw), session(suite["project_grant_session"])]
    if kind == "corrupt-markdown":
        broken = deepcopy(raw)
        broken["encrypted_draft_md"] = "not-authenticated"
        return [get(broken), session(suite["session"])]
    if kind == "missing":
        return [("GET", "/v1/sdk/drafts/missing", 200, {"draft": None})]
    if kind == "empty-list":
        return [("GET", "/v1/sdk/drafts", 200, {"drafts": []})]
    if kind == "anonymous":
        return []
    if kind == "http-error":
        return [
            (
                "GET",
                "/v1/sdk/drafts/" + raw["chat_id"],
                vector["status"],
                {"detail": "synthetic-error"},
            )
        ]
    if kind == "open-parity-limit":
        raw = vector["draft"]
        return [get(raw), session(suite["session"])]
    raise AssertionError("unknown scenario")


class Peer:
    def __init__(self, suite, vector):
        self.suite = suite
        self.expected = responses(suite, vector)
        self.requests = 0
        self.failure = None

    def dispatch(self, method, path, headers, body):
        try:
            index = self.requests
            self.requests += 1
            assert index < len(self.expected), "extra/replayed operation"
            expected_method, expected_path, status, payload = self.expected[index]
            assert (method, path) == (expected_method, expected_path), (
                "exact operation order and route"
            )
            headers = {k.lower(): v for k, v in headers.items()}
            assert headers.get("authorization") == "Bearer sk-api-synthetic", (
                "explicit owner bearer"
            )
            assert headers.get("x-openmates-device-identity") == "synthetic-device"
            assert headers.get("x-openmates-sdk") == "rust"
            assert not set(headers).intersection(
                {
                    "cookie",
                    "x-session-id",
                    "x-openmates-anonymous-id",
                    "x-openmates-task-owner",
                    "x-openmates-task-actor",
                }
            )
            assert ".synthetic" not in json.dumps([headers, path, body]), (
                "setup suffix leaked"
            )
            assert body == (
                {"sdk_name": "rust", "device_identity": "synthetic-device"}
                if method == "POST"
                else None
            )
            return status, payload
        except AssertionError as error:
            self.failure = str(error)
            return 400, {"detail": "synthetic protocol refusal"}

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
                    status, payload = peer.dispatch(
                        self.command,
                        self.path,
                        dict(self.headers),
                        json.loads(raw) if raw else None,
                    )
                except Exception:
                    peer.failure = "invalid bounded request"
                    status, payload = 400, {}
                raw = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            do_GET = handle_request
            do_POST = handle_request
            do_PATCH = handle_request
            do_DELETE = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.block_on_close = False
        return server


def invoke(binary, case):
    child = subprocess.Popen(
        [str(binary), "--case"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, _err = child.communicate(json.dumps(case).encode(), timeout=20)
        assert child.returncode == 0 and len(out) <= 1024 * 1024, (
            "Rust adapter failed/bound"
        )
        return json.loads(out)
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)


def check(suite, vector, observed):
    kind = vector["kind"]
    if "expected_error" in vector:
        assert observed == {"ok": False, "error": vector["expected_error"]}
    elif kind in ("record", "open-parity-limit"):
        expected = {
            "markdown": vector["markdown"],
            "preview": vector["preview"]
            if kind == "record"
            else vector["previews"]["rust"],
        }
        assert observed == {"ok": True, "value": expected}
    else:
        assert observed == {"ok": True, "value": [] if kind == "empty-list" else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", choices=[CAPABILITY], required=True)
    parser.add_argument("--rust-executable", type=Path, required=True)
    args = parser.parse_args()
    binary = args.rust_executable.resolve(strict=True)
    assert binary.is_file()
    raw = args.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    document = json.loads(raw)
    suite = document["capabilities"][args.capability]
    assert document["schema_version"] == 1
    assert (
        len(suite["vectors"]) == 15 and len({v["id"] for v in suite["vectors"]}) == 15
    )
    results, limits = [], []
    for vector in suite["vectors"] + [
        dict(v, kind="open-parity-limit") for v in suite["open_parity_limits"]
    ]:
        peer = Peer(suite, vector)
        server = peer.server()
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        thread.start()
        try:
            case = {
                "endpoint": "http://127.0.0.1:" + str(server.server_address[1]),
                "credential": suite["credential"],
                "vector": vector,
                "base_draft": suite["vectors"][0]["draft"],
            }
            observed = invoke(binary, case)
            check(suite, vector, observed)
            assert peer.failure is None and peer.requests == len(peer.expected), (
                "exact wire/no replay"
            )
            if vector["kind"] == "open-parity-limit":
                limits.append(
                    {
                        "id": vector["id"],
                        "status": "open-existing-sdk-divergence",
                        "observed": "Unicode scalar slice",
                    }
                )
            else:
                results.append({"id": vector["id"], "status": "passed"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive()
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": "rust",
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
                "openParityLimits": limits,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Rust drafts adapter conformance failed", file=sys.stderr)
        raise SystemExit(1)
