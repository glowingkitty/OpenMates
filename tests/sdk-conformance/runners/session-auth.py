#!/usr/bin/env python3
"""Positive auth through the real PyO3 facade and synthetic loopback transcripts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
CAPABILITY = "session.password-totp-rotation.v1"


def match(actual, expected, captures):
    if isinstance(expected, dict) and "$capture_uuid" in expected:
        parsed = uuid.UUID(actual)
        assert parsed.version == 4 and str(parsed) == actual
        assert actual not in captures.values()
        captures[expected["$capture_uuid"]] = actual
    elif isinstance(expected, dict) and "$ref" in expected:
        assert actual == captures[expected["$ref"]]
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key, value in expected.items():
            match(actual[key], value, captures)
    else:
        assert actual == expected


async def run_session_auth(vector):
    from openmates import SessionClient, SessionClientError

    state = {"index": 0, "failure": None}
    captures = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never print request bodies, credentials, or private diagnostics.

        def do_POST(self):
            index = state["index"]
            step = vector["steps"][index] if index < len(vector["steps"]) else None
            try:
                assert step and step["method"] == "POST" and self.path == step["path"]
                assert self.headers.get("X-OpenMates-SDK") == "pip"
                assert self.headers.get("Origin") == vector["app_origin"]
                assert self.headers.get("Cookie") == step["cookie"]
                assert (
                    self.headers.get("X-OpenMates-Expected-Principal")
                    == step["expected_principal"]
                )
                if step.get("blocked_effect"):
                    assert step["expected_principal"] != step["authenticated_principal"]
                    assert step["response"]["status"] == 403
                assert self.headers.get("Authorization") is None
                length = int(self.headers["Content-Length"])
                assert 0 < length < 65536
                raw = self.rfile.read(length).decode()
                assert all(
                    vector["account"][field] not in raw
                    for field in ("password", "master_key", "email")
                )
                match(json.loads(raw), step["body"], captures)
                state["index"] += 1
                response = step["response"]
                body = response.get("raw", json.dumps(response.get("json"))).encode()
                self.send_response(response["status"])
                for key, value in response["headers"]:
                    self.send_header(key, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                state["failure"] = state["failure"] or (
                    step["id"] if step else "unexpected-request"
                )
                self.send_response(500)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    client = SessionClient(
        api_url=endpoint,
        app_url=vector["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=False,
    )

    async def refused(operation, code):
        try:
            await operation
        except SessionClientError as error:
            assert error.code == code
            assert "synthetic-private-server-diagnostic" not in str(error)
        else:
            raise AssertionError("expected native error missing")

    async def operate(action):
        kind = action["kind"]
        if kind == "login":
            user = await client.login_password(
                vector["account"]["input_email"],
                vector["account"]["password"],
                tfa=action.get("tfa"),
                **(
                    {"stay_logged_in": action["stay_logged_in"]}
                    if "stay_logged_in" in action
                    else {}
                ),
            )
            assert user["id"] == vector["account"]["owner_id"]
        elif kind == "validate":
            await client.validate_session()
        elif kind == "validate_concurrently":
            await asyncio.gather(
                *(client.validate_session() for _ in range(action["count"]))
            )
        elif kind == "logout":
            await client.logout()
        else:
            raise AssertionError("unsupported transcript action")

    revision = 0
    try:
        for action in vector["actions"]:
            if action.get("error"):
                await refused(operate(action), action["error"])
            else:
                await operate(action)
            if action["snapshot"] is None:
                await refused(
                    client.export_session(include_secrets=True), "authentication"
                )
            else:
                snapshot = await client.export_session(include_secrets=True)
                assert snapshot["revision"] > revision
                revision = snapshot["revision"]
                session = snapshot["session"]
                assert session["api_url"] == endpoint
                assert session["master_key"] == vector["account"]["master_key"]
                assert session["cookies"] == {
                    "auth_refresh_token": action["snapshot"]["token"]
                }
                assert session["ws_token"] == action["snapshot"]["ws_token"]
                assert session["hashed_email"] == vector["account"]["hashed_email"]
                assert session["email_encryption_key"] == vector["account"]["email_key"]
        await refused(client.validate_session(), "authentication")
        assert state["failure"] is None
        assert state["index"] == len(vector["steps"])
        return {"id": vector["id"], "status": "passed"}
    finally:
        await client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


async def run(vectors):
    return [await run_session_auth(vector) for vector in vectors]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    raw = Path(args.fixture).read_bytes()
    try:
        assert args.capability == CAPABILITY
        results = asyncio.run(
            run(json.loads(raw)["capabilities"][CAPABILITY]["vectors"])
        )
        assert results
    except Exception:
        print("Python positive session auth conformance failed", file=sys.stderr)
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": "python",
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()
