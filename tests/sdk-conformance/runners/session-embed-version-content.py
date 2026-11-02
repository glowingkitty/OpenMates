#!/usr/bin/env python3
"""Actual direct Cookie adapters against the closed independent synthetic peer."""

import argparse
import asyncio
import hashlib
import json
import os
import signal
import selectors
import time
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "session.embeds.version-content.v1"


def validate(case):
    url = urlsplit(case["endpoint"])
    assert (
        url.scheme == "http"
        and url.hostname == "127.0.0.1"
        and url.port
        and not url.username
        and not url.password
        and not url.query
        and not url.fragment
        and url.path == ""
    )
    assert (
        case["suite"]["account"]["cookie"] == "synthetic-cookie"
        and case["suite"]["account"]["session_id"] == "synthetic-session"
    )


async def python_case(case):
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import SessionClient, SessionClientError

    s, v = case["suite"], case["vector"]
    client = SessionClient(
        api_url=case["endpoint"],
        app_url=s["protocol"]["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=v["mode"] != "policy-denied",
    )
    try:
        if v["mode"] != "noauth":
            await client.import_session(
                dict(
                    api_url=case["endpoint"],
                    session_id=s["account"]["session_id"],
                    cookies={"auth_refresh_token": s["account"]["cookie"]},
                    ws_token=None,
                    master_key=s["account"]["master_key"],
                    hashed_email=s["account"]["hashed_email"],
                    user_email_salt="",
                    email_encryption_key=None,
                    created_at=1,
                    paired_session_expires_at=None,
                    active_team_id=s["protocol"]["team_id"]
                    if v["mode"] == "team"
                    else None,
                )
            )
        try:
            return {
                "ok": True,
                "value": await client.embeds.version_content(
                    v["embed_id"], v["version"]
                ),
            }
        except SessionClientError as error:
            return {"ok": False, "error": error.code}
    finally:
        await client.close()


def invoke(argv, case):
    child = subprocess.Popen(
        argv,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    try:
        payload = json.dumps(case).encode()
        assert len(payload) <= 1024 * 1024
        os.set_blocking(child.stdin.fileno(), False)
        os.set_blocking(child.stdout.fileno(), False)
        selector.register(child.stdin, selectors.EVENT_WRITE)
        selector.register(child.stdout, selectors.EVENT_READ)
        written = 0
        output = bytearray()
        deadline = time.monotonic() + 20
        while selector.get_map():
            remaining = deadline - time.monotonic()
            assert remaining > 0, "Adapter timed out"
            ready = selector.select(remaining)
            assert ready, "Adapter timed out"
            for key, mask in ready:
                if mask & selectors.EVENT_WRITE:
                    written += os.write(key.fd, payload[written : written + 65536])
                    if written == len(payload):
                        selector.unregister(key.fileobj)
                        child.stdin.close()
                else:
                    chunk = os.read(key.fd, min(65536, 1024 * 1024 + 1 - len(output)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        assert len(output) <= 1024 * 1024, "Adapter output bound"
        assert child.wait(timeout=max(0.001, deadline - time.monotonic())) == 0
        return json.loads(output)
    finally:
        selector.close()
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
        child.stdout.close()
        if not child.stdin.closed:
            child.stdin.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="store_true")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--capability")
    parser.add_argument(
        "--language", choices=["rust", "npm", "python"], default="python"
    )
    parser.add_argument("--rust-executable", type=Path)
    a = parser.parse_args()
    if a.case:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        assert len(raw) <= 1024 * 1024
        c = json.loads(raw)
        validate(c)
        print(json.dumps(asyncio.run(python_case(c))))
        return
    assert a.capability == CAPABILITY and a.fixture
    raw = a.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    s = json.loads(raw)["capabilities"][CAPABILITY]
    assert len(s["vectors"]) == 21 and len({v["id"] for v in s["vectors"]}) == 21
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from session_embed_version_peer import CookieVersionPeer

    if a.language == "rust":
        binary = a.rust_executable.resolve(strict=True)
        assert binary.is_file()
        argv = [str(binary), "--case"]
    elif a.language == "npm":
        argv = [
            "node",
            str(
                ROOT / "tests/sdk-conformance/runners/session-embed-version-content.mjs"
            ),
            "--case",
        ]
    else:
        argv = [sys.executable, str(Path(__file__)), "--case"]
    results = []
    for v in s["vectors"]:
        peer = CookieVersionPeer(
            s, v, {"rust": "rust", "npm": "npm", "python": "pip"}[a.language]
        ).start()
        try:
            peer.check(
                invoke(argv, {"endpoint": peer.endpoint, "suite": s, "vector": v})
            )
            results.append({"id": v["id"], "status": "passed"})
        finally:
            peer.close()
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": a.language,
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()
