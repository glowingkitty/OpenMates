#!/usr/bin/env python3
"""Actual PyO3 SessionClient against the shared in-process recovery fixture peer."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from recovery_server import CAPABILITY, RecoveryPeer  # noqa: E402


def session(suite, endpoint):
    account = suite["account"]
    return {
        "api_url": endpoint,
        "session_id": account["session_id"],
        "cookies": {"auth_refresh_token": account["cookie"]},
        "ws_token": None,
        "master_key": account["master_key"],
        "hashed_email": "synthetic-email-hash",
        "user_email_salt": "synthetic-salt",
        "email_encryption_key": None,
        "created_at": 1,
        "paired_session_expires_at": None,
        "active_team_id": None,
    }


def construct(suite, endpoint):
    from openmates import SessionClient

    return SessionClient(
        api_url=endpoint,
        app_url=suite["protocol"]["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=True,
    )


async def cancel_on_claim(client, peer):
    for _ in range(500):
        if peer.status()["claims"] == 1:
            client.cancel()
            return
        await asyncio.sleep(0.01)
    raise AssertionError("test lease claim timeout")


async def run_recovery(suite, vector):
    from openmates import SessionClientError

    peer = RecoveryPeer(suite, vector, "pip").start()
    client = None
    cancellation, seen = None, set()
    try:
        client = construct(suite, peer.endpoint)
        await client.import_session(session(suite, peer.endpoint))
        error_code, completed = None, None
        try:
            if vector["mode"] == "bad_digest":
                await client.list("chats")
            else:
                if vector["mode"] == "cancel":
                    cancellation = asyncio.create_task(cancel_on_claim(client, peer))
                async for event in client.stream(suite["protocol"]["input"]):
                    if event["type"] == "update":
                        seen.update(event["update"])
                    if event["type"] == "completed":
                        completed = event["chat"]
        except SessionClientError as error:
            error_code = error.code
            assert "synthetic-private-server-diagnostic" not in str(error)
        if cancellation:
            await cancellation
        assert error_code == vector["error"]
        if vector["error"]:
            assert completed is None and "Completed" not in seen
        else:
            field = (
                "canonical_content"
                if vector["mode"] == "terminal"
                else "sealed_content"
            )
            assert completed["messages"][-1]["content"] == suite["protocol"][field]
            assert suite["protocol"][field] != suite["protocol"]["transient_content"]
            assert "Completed" in seen
        if vector["reconnect"]:
            exported = await client.export_session(include_secrets=True)
            await client.close()
            client = construct(suite, peer.endpoint)
            await client.import_session(exported["session"])
            rows = await client.list("chats")
            assert len(rows) == 1
            chat = await client.open_chat(rows[0]["id"])
            assert (
                chat["messages"][-1]["content"] == suite["protocol"]["sealed_content"]
            )
        await client.close()
        for _ in range(100):
            report = peer.status()
            if "socket-closed" in report["checks"]:
                break
            await asyncio.sleep(0.01)
        assert report["failure"] is None
        assert report["persists"] == vector["expected_persists"]
        assert report["admissions"] == (0 if vector["mode"] == "bad_digest" else 1)
        assert report["claims"] == (0 if vector["mode"] == "bad_digest" else 1)
        assert report["connections"] == (2 if vector["reconnect"] else 1)
        assert set(vector["required_checks"]) <= set(report["checks"])
        return {"id": vector["id"], "status": "passed"}
    finally:
        try:
            if client:
                await client.close()
        finally:
            peer.close()


async def run(suite):
    return [await run_recovery(suite, vector) for vector in suite["vectors"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    raw = Path(args.fixture).read_bytes()
    try:
        assert args.capability == CAPABILITY
        results = asyncio.run(run(json.loads(raw)["capabilities"][CAPABILITY]))
        assert results
    except Exception:
        print("Python recovery protocol conformance failed", file=sys.stderr)
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
