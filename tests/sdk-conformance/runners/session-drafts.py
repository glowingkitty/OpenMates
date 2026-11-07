#!/usr/bin/env python3
"""Actual Rust/NAPI/PyO3 direct-session draft conformance driver. The developer
harness may spawn fixed adapters; production libraries never spawn a CLI."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import selectors
import time
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "session.drafts.v1"


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

    suite, vector = case["suite"], case["vector"]
    client = SessionClient(
        api_url=case["endpoint"],
        app_url=suite["protocol"]["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=vector["mode"] != "policy-denied",
    )
    try:
        if vector["mode"] != "noauth":
            key = (
                suite["account"]["master_key"]
                if vector["mode"] != "wrong-key"
                else base64.b64encode(bytes([2]) * 32).decode()
            )
            await client.import_session(
                dict(
                    api_url=case["endpoint"],
                    session_id=suite["account"]["session_id"],
                    cookies={"auth_refresh_token": suite["account"]["cookie"]},
                    ws_token=None,
                    master_key=key,
                    hashed_email=suite["account"]["hashed_email"],
                    user_email_salt="",
                    email_encryption_key=None,
                    created_at=1,
                    paired_session_expires_at=None,
                    active_team_id=suite["protocol"]["team_id"]
                    if vector["mode"] == "team"
                    else None,
                )
            )
        if vector["preflight_get"]:
            assert (
                await client.drafts.get(suite["protocol"]["chat_id"], refresh=True)
                == suite["records"]["base"]
            )
        try:
            refresh = vector["options"].get("force_refresh", False)
            if vector["operation"] == "cached-list":
                value = await client.drafts.cached_list()
            elif vector["operation"] == "list":
                value = await client.drafts.list(refresh=refresh)
            elif vector["operation"] == "get":
                value = await client.drafts.get(
                    suite["protocol"]["chat_id"], refresh=refresh
                )
            else:
                value = await client.drafts.sync()
            return {"ok": True, "value": value}
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
        stderr=None,  # inherited: the driver projects only class and tracked frames
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
    args = parser.parse_args()
    if args.case:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        assert len(raw) <= 1024 * 1024
        case = json.loads(raw)
        validate(case)
        print(json.dumps(asyncio.run(python_case(case))))
        return
    assert args.capability == CAPABILITY and args.fixture
    raw = args.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    document = json.loads(raw)
    assert document["schema_version"] == 1
    suite = document["capabilities"][CAPABILITY]
    vectors = suite["vectors"]
    assert len(vectors) == 20 and len({v["id"] for v in vectors}) == 20
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from session_drafts_server import SessionDraftPeer

    if args.language == "rust":
        binary = args.rust_executable.resolve(strict=True)
        assert binary.is_file()
        argv = [str(binary), "--case"]
    elif args.language == "npm":
        argv = [
            "node",
            "--experimental-strip-types",
            str(ROOT / "tests/sdk-conformance/runners/session-drafts.mjs"),
            "--case",
        ]
    else:
        argv = [sys.executable, str(Path(__file__)), "--case"]
    results = []
    for vector in vectors:
        peer = SessionDraftPeer(
            suite,
            vector,
            {"rust": "rust", "npm": "npm", "python": "pip"}[args.language],
        ).start()
        try:
            observed = invoke(
                argv, {"endpoint": peer.endpoint, "suite": suite, "vector": vector}
            )
            if vector["expected_error"]:
                assert observed == {"ok": False, "error": vector["expected_error"]}
            else:
                assert observed == {"ok": True, "value": vector["expected"]}
            assert peer.failure is None and peer.counts == vector["expected_counts"], (
                "direct-session exact protocol/no extra traffic"
            )
            results.append({"id": vector["id"], "status": "passed"})
        except Exception:
            # Exact failed vector id for the driver's closed attribution; the
            # original exception still ends the run.
            results.append({"id": vector["id"], "status": "failed"})
            print(
                json.dumps(
                    {
                        "capability": CAPABILITY,
                        "language": args.language,
                        "status": "failed",
                        "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                        "results": results,
                    }
                )
            )
            raise
        finally:
            peer.close()
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": args.language,
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Session draft conformance failed", file=sys.stderr)
        raise SystemExit(1)
