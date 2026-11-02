#!/usr/bin/env python3
"""AUTHORED UNRUN direct Cookie adapters; explicit synthetic fixture only."""

import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = "work.project-workflow-file-sync.v1"


def validate(case):
    url = urlsplit(case["endpoint"])
    assert (
        url.scheme == "http"
        and url.hostname == "127.0.0.1"
        and url.port
        and not url.username
        and not url.password
        and not url.path
        and not url.query
        and not url.fragment
    )
    assert (
        case["suite"]["account"]["cookie"] == "synthetic-cookie"
        and case["suite"]["account"]["session_id"] == "synthetic-session"
    )


def session(s, endpoint):
    return dict(
        api_url=endpoint,
        session_id=s["account"]["session_id"],
        cookies={"auth_refresh_token": s["account"]["cookie"]},
        ws_token=None,
        master_key=s["account"]["master_key"],
        hashed_email=s["account"]["hashed_email"],
        user_email_salt="",
        email_encryption_key=None,
        created_at=1,
        paired_session_expires_at=None,
        active_team_id=None,
    )


def control(endpoint, release=False):
    request = Request(
        endpoint + ("/__test/release" if release else "/__test/status"),
        data=b"{}" if release else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=2) as response:
        return json.load(response)


async def python_case(case):
    validate(case)
    sys.path.insert(0, str(ROOT / "packages/openmates-python"))
    from openmates import SessionClient, SessionClientError

    s, v = case["suite"], case["vector"]
    client = SessionClient(
        api_url=case["endpoint"],
        app_url=s["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=v.get("mode") != "policy-denied",
    )
    try:
        if v.get("mode") != "noauth":
            credentials = session(s, case["endpoint"])
            if v.get("mode") == "wrong-master":
                credentials["master_key"] = (
                    "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="
                )
            await client.import_session(credentials)
        filters = {
            "personal": True,
            **({"team_id": s["team_id"]} if v.get("mode") == "bad-scope" else {}),
        }
        operation = asyncio.create_task(
            client.projects.sync_workflow_files(
                s["workflow_id"],
                s["expected_version"],
                options={"approved_paths": v.get("approved_paths", [s["path"]])},
                filters=filters,
            )
        )
        if v.get("mode") == "cancel-held":
            deadline = time.monotonic() + 5
            while not (await asyncio.to_thread(control, case["endpoint"]))["blocked"]:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.02)
            client.cancel()
            await asyncio.to_thread(control, case["endpoint"], True)
        try:
            return {"ok": True, "value": await operation}
        except SessionClientError as error:
            return {"ok": False, "error": error.code}
    finally:
        await client.close()


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
        print(json.dumps(asyncio.run(python_case(json.loads(raw)))))
        return
    assert a.capability == CAPABILITY and a.fixture
    raw = a.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    assert (
        len(suite["vectors"]) == 23 and len({v["id"] for v in suite["vectors"]}) == 23
    )
    sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
    from session_workflow_files_peer import WorkflowFilesPeer

    # Reuse the exact maintained reservation/bounded-output/TERM/KILL/reap case
    # owner, not a new product subprocess path. No CLI or installed state.
    spec = importlib.util.spec_from_file_location(
        "workflow_case_owner",
        ROOT / "tests/sdk-conformance/runners/session-embed-share.py",
    )
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    for kind in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(kind, owner.cancel_owner)
    if a.language == "rust":
        binary = a.rust_executable.resolve(strict=True)
        assert binary.is_file()
        argv = [str(binary), "--case"]
    elif a.language == "npm":
        argv = [
            "node",
            str(ROOT / "tests/sdk-conformance/runners/workflow-file-sync.mjs"),
            "--case",
        ]
    else:
        argv = [sys.executable, str(Path(__file__)), "--case"]
    results = []
    for vector in suite["vectors"]:
        assert not owner.OWNER_CANCELLED
        peer = WorkflowFilesPeer(
            suite, vector, {"rust": "rust", "npm": "npm", "python": "pip"}[a.language]
        ).start()
        try:
            observed = owner.invoke(
                argv, {"endpoint": peer.endpoint, "suite": suite, "vector": vector}
            )
            peer.check(observed)
            results.append({"id": vector["id"], "status": "passed"})
        finally:
            peer.close()
    assert not owner.OWNER_CANCELLED
    print(
        json.dumps(
            {
                "capability": CAPABILITY,
                "language": a.language,
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "status": "passed",
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()
