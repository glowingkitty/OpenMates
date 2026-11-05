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
CAPABILITY = "session.embeds.admitted-share-url.v1"


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
        allow_private_operations=v.get("mode") != "policy-denied",
    )
    try:
        if v.get("mode") != "noauth":
            await client.import_session(
                dict(
                    api_url=case["endpoint"],
                    session_id=s["account"]["session_id"],
                    cookies={"auth_refresh_token": s["account"]["cookie"]},
                    ws_token=None,
                    master_key=(
                        "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="
                        if v.get("mode") == "wrong-key"
                        else s["account"]["master_key"]
                    ),
                    hashed_email=s["account"]["hashed_email"],
                    user_email_salt="",
                    email_encryption_key=None,
                    created_at=1,
                    paired_session_expires_at=1
                    if v.get("mode") == "paired-expired"
                    else None,
                    active_team_id=s["protocol"]["team_id"]
                    if v.get("mode") == "team"
                    else None,
                )
            )
        try:
            return {
                "ok": True,
                "value": await client.embeds.share_url(
                    s["embed_id"], expires=v["expires"], password=v["password"]
                ),
            }
        except SessionClientError as error:
            return {"ok": False, "error": error.code}
    except SessionClientError as error:
        # Expired explicit imports are refused before a read can start.
        return {"ok": False, "error": error.code}
    finally:
        await client.close()


OWNER_CANCELLED = False


def cancel_owner(_signal, _frame):
    # Repeated signals cannot interrupt original-group cleanup.
    global OWNER_CANCELLED
    OWNER_CANCELLED = True


def invoke(argv, case):
    # Adapt the maintained run_owned stdin-free lifecycle to bounded case input.
    # WNOWAIT reserves the leader PID until TERM/KILL and reaping finish.
    payload = json.dumps(case).encode()
    assert len(payload) <= 1024 * 1024
    if OWNER_CANCELLED:
        raise ValueError("share conformance owner cancelled")
    child = None
    output = bytearray()
    sizes = {"stdout": 0, "stderr": 0}
    deadline = time.monotonic() + 20
    exited_at = None
    try:
        child = subprocess.Popen(
            argv,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        with selectors.DefaultSelector() as streams:
            for channel, events, name in [
                (child.stdin, selectors.EVENT_WRITE, "stdin"),
                (child.stdout, selectors.EVENT_READ, "stdout"),
                (child.stderr, selectors.EVENT_READ, "stderr"),
            ]:
                os.set_blocking(channel.fileno(), False)
                streams.register(channel, events, name)
            written = 0
            while True:
                now = time.monotonic()
                if OWNER_CANCELLED:
                    raise ValueError("share conformance owner cancelled")
                if now >= deadline:
                    raise ValueError("share adapter deadline")
                ended = os.waitid(
                    os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                )
                if ended is not None:
                    if not streams.get_map():
                        break
                    exited_at = now if exited_at is None else exited_at
                    if now - exited_at >= 0.25:
                        raise ValueError("share descendant retained pipes")
                for key, mask in streams.select(min(0.05, max(0, deadline - now))):
                    if mask & selectors.EVENT_WRITE:
                        written += os.write(key.fd, payload[written : written + 65536])
                        if written == len(payload):
                            streams.unregister(key.fileobj)
                            child.stdin.close()
                    else:
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            streams.unregister(key.fileobj)
                            continue
                        sizes[key.data] += len(chunk)
                        if sizes[key.data] > 1024 * 1024:
                            raise ValueError("share adapter output bound")
                        if key.data == "stdout":
                            output.extend(chunk)
                        # Stderr is bounded and discarded, never a secret receipt.
    finally:
        if child is not None:
            try:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                time.sleep(0.15)
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=1)
            finally:
                for channel in (child.stdin, child.stdout, child.stderr):
                    if channel is not None and not channel.closed:
                        channel.close()
    if OWNER_CANCELLED or child.returncode:
        raise ValueError("share adapter failed or cancelled")
    return json.loads(output)


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
    for kind in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(kind, cancel_owner)
    assert a.capability == CAPABILITY and a.fixture
    raw = a.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    s = json.loads(raw)["capabilities"][CAPABILITY]
    assert len(s["vectors"]) == 16 and len({v["id"] for v in s["vectors"]}) == 16
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from session_embed_share_peer import CookieSharePeer

    if a.language == "rust":
        binary = a.rust_executable.resolve(strict=True)
        assert binary.is_file()
        argv = [str(binary), "--case"]
    elif a.language == "npm":
        argv = [
            "node",
            str(ROOT / "tests/sdk-conformance/runners/session-embed-share.mjs"),
            "--case",
        ]
    else:
        argv = [sys.executable, str(Path(__file__)), "--case"]
    results = []
    for v in s["vectors"]:
        if OWNER_CANCELLED:
            raise ValueError("share conformance owner cancelled")
        peer = CookieSharePeer(
            s, v, {"rust": "rust", "npm": "npm", "python": "pip"}[a.language]
        ).start()
        try:
            peer.check(
                invoke(argv, {"endpoint": peer.endpoint, "suite": s, "vector": v})
            )
            results.append({"id": v["id"], "status": "passed"})
        finally:
            peer.close()
    if OWNER_CANCELLED:
        raise ValueError("share conformance owner cancelled")
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
