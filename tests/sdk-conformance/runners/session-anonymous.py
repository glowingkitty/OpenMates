#!/usr/bin/env python3
"""Actual PyO3 anonymous public stream with signed and unsigned synthetic clients."""

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
from session_anonymous_server import AnonymousPeer, CAPABILITY  # noqa:E402
from openmates import SessionClient, SessionClientError  # noqa:E402


async def rejected(operation, code):
    try:
        await operation
    except SessionClientError as error:
        assert error.code == code
        assert "synthetic-private-server-diagnostic" not in str(error)
    else:
        raise AssertionError("anonymous request must reject")


def outcome(value, suite):
    assert value["status"] == "completed" and value["assistant"] == suite["text"]
    assert value["chatId"].startswith("anonymous-")
    assert value["followUpSuggestions"] == ["Synthetic follow-up"]
    for key in (
        "pendingTaskUpdateJobs",
        "taskEvents",
        "subChatEvents",
        "appSettingsMemoryRequests",
    ):
        assert value[key] == []
    assert value["chat"]["id"] == value["chatId"]
    assert len(value["chat"]["messages"]) == 2
    assert value["userMessageId"] == value["chat"]["messages"][0]["id"]
    assert value["userMessageId"].startswith("anonymous-message-")
    assert value["chat"]["messages"][0]["content"] == suite["text"]
    assert value["chat"]["messages"][1]["content"] == suite["text"]


async def run_vector(suite, vector):
    peer = AnonymousPeer(suite, vector, "pip").start()
    client = SessionClient(
        api_url=peer.endpoint,
        app_url="https://app.example.invalid",
        enhanced_privacy=False,
        allow_private_operations=vector["allow_private"],
    )
    try:
        before = None
        if vector["signed"]:
            a = suite["account"]
            await client.import_session(
                {
                    "api_url": peer.endpoint,
                    "session_id": a["session_id"],
                    "cookies": {"auth_refresh_token": a["cookie"]},
                    "ws_token": None,
                    "master_key": a["master_key"],
                    "hashed_email": "synthetic-email",
                    "user_email_salt": "synthetic-salt",
                    "email_encryption_key": None,
                    "created_at": 1,
                    "paired_session_expires_at": None,
                    "active_team_id": None,
                }
            )
            before = await client.export_session(include_secrets=True)
        mode = vector["mode"]

        def call():
            return client.send_anonymous(suite["anonymous_id"], suite["text"])

        if mode == "sse":
            for repetition in range(vector["repetitions"]):
                if repetition:
                    outcome(await call(), suite)
                else:
                    seen = set()
                    async for event in client.stream_anonymous(
                        suite["anonymous_id"], suite["text"]
                    ):
                        if event["type"] == "update":
                            seen.update(event["update"])
                        else:
                            outcome(event["outcome"], suite)
                    assert {"Started", "Submitted", "Content", "Completed"} <= seen
                    assert "Admitted" not in seen and "Consent" not in seen
        elif mode == "cancel":
            stream = client.stream_anonymous(suite["anonymous_id"], suite["text"])
            saw_content = False
            async for event in stream:
                if event["type"] == "update" and "Content" in event["update"]:
                    saw_content = True
                    break
            assert saw_content
            await stream.aclose()
            peer.release.set()
            outcome(await call(), suite)
        elif mode == "preflight":
            for identifier in ("", "invalid id", "x" * 129):
                await rejected(
                    client.send_anonymous(identifier, suite["text"]), "invalid_argument"
                )
            for options in (
                {"model": "forbidden"},
                {"project_id": "11111111-1111-4111-8111-111111111111"},
                {"response_timeout_ms": 0},
            ):
                await rejected(
                    client.send_anonymous(
                        suite["anonymous_id"], suite["text"], options=options
                    ),
                    "invalid_argument",
                )
        else:
            await rejected(
                call(),
                {
                    "budget": "signup_required",
                    "redirect": "forbidden",
                    "malformed": "protocol",
                    "policy": "forbidden",
                    "private": "protocol",
                }[mode],
            )
        if vector["signed"]:
            assert await client.export_session(include_secrets=True) == before
        else:
            await rejected(
                client.export_session(include_secrets=True), "authentication"
            )
        report = peer.status()
        assert report["failure"] is None and report["redirects"] == 0
        if mode in ("preflight", "policy"):
            assert report["status_gets"] == report["posts"] == 0
        else:
            expected = 2 if mode == "cancel" else vector["repetitions"]
            assert report["status_gets"] == expected
            assert report["posts"] == (
                0 if mode in ("budget", "redirect") else expected
            )
            assert "public-headers-without-account-identity" in report["checks"]
            if report["posts"]:
                assert {
                    "local-pii-redaction",
                    "empty-history-fresh-ephemeral-identities",
                    "no-routing-or-durable-capabilities",
                } <= set(report["checks"])
                assert len(report["chat_ids"]) == expected
        return {"id": vector["id"], "status": "passed"}
    finally:
        await client.close()
        peer.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    assert args.capability == CAPABILITY
    raw = Path(args.fixture).read_bytes()
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    results = [await run_vector(suite, v) for v in suite["vectors"]]
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
    asyncio.run(main())
