#!/usr/bin/env python3
"""Actual PyO3 one-page reads against a shared synthetic owned HTTP peer.

Public fixture credentials only; no CLI or installed profile is discovered.
Every expected failure and response/call bound is asserted independently.
The peer starts only when this managed executable is explicitly run.
No raw exception, response, key or session data is emitted on failure.
"""

from __future__ import annotations
import argparse
import asyncio
import copy
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from message_window_server import CAPABILITY, MessageWindowPeer  # noqa:E402


def exact(actual, expected):
    assert type(actual) is type(expected)
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key, value in expected.items():
            exact(actual[key], value)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for value, reference in zip(actual, expected):
            exact(value, reference)
    else:
        assert actual == expected


def assert_window(suite, vector, result, expected_scope=None):
    expected = copy.deepcopy(vector["expected_public_paging"])
    expected["chat"]["messages"] = copy.deepcopy(vector["expected_messages"])
    scope = expected_scope
    for name in ("startCursor", "endCursor", "oversizedMessageCursor"):
        if expected[name] is None:
            assert result[name] is None
            continue
        actual = result[name]
        assert type(actual) is dict and actual.keys() == {
            "chatId",
            "scope",
            "createdAt",
            "messageId",
        }
        assert actual["chatId"] == suite["protocol"]["chat_id"]
        assert type(actual["scope"]) is str and re.fullmatch(
            r"[0-9a-f]{64}", actual["scope"]
        )
        if scope is None:
            scope = actual["scope"]
        else:
            assert actual["scope"] == scope
        expected[name]["chatId"] = suite["protocol"]["chat_id"]
        expected[name]["scope"] = scope
    exact(result, expected)
    assert result["payloadBytes"] <= suite["protocol"]["page_max_bytes"]


async def run_vector(suite, vector):
    from openmates import SessionClient, SessionClientError

    allow_private_operations = vector.get(
        "allow_private_operations", suite["allow_private_operations"]
    )
    assert type(allow_private_operations) is bool
    peer = MessageWindowPeer(suite, vector, "pip").start()
    client = SessionClient(
        api_url=peer.endpoint,
        app_url=suite["protocol"]["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=allow_private_operations,
    )
    try:
        if vector["mode"] != "noauth":
            await client.import_session(
                dict(
                    api_url=peer.endpoint,
                    session_id=suite["account"]["session_id"],
                    cookies={"auth_refresh_token": suite["account"]["cookie"]},
                    ws_token=None,
                    master_key=suite["account"]["master_key"],
                    hashed_email="synthetic",
                    user_email_salt="synthetic",
                    email_encryption_key=None,
                    created_at=1,
                    paired_session_expires_at=None,
                    active_team_id=None,
                )
            )
        identity = suite["protocol"]["chat_id"]
        options = copy.deepcopy(vector["options"])
        expected_scope = None
        if vector.get("preflight"):
            first = await client.chat_message_window(identity, vector["preflight"])
            assert_window(
                suite, next(v for v in suite["vectors"] if v["mode"] == "latest"), first
            )
            expected_scope = first["startCursor"]["scope"]
            options.update(
                direction="after" if vector["mode"] == "after" else "before",
                cursor=copy.deepcopy(first["startCursor"]),
            )
            assert options["cursor"]["scope"]
            if vector["mode"] == "forbidden_context":
                options["cursor"]["chatId"] = "99999999-9999-4999-8999-999999999999"
            if vector["mode"] == "wrong_scope":
                options["cursor"]["scope"] = "0" * 64
        if vector["mode"] == "partial_cache":
            assert (await client.open_chat(identity))["messages"] == vector[
                "expected_cached_messages"
            ]
        result, error_code = None, None
        try:
            if vector["mode"] == "cancel":
                pending = asyncio.create_task(
                    client.chat_message_window(identity, options)
                )
                observed = False
                for _ in range(500):
                    if peer.status()["metadata"] == 1:
                        observed = True
                        break
                    await asyncio.sleep(0.005)
                assert observed
                client.cancel()
                code, _ = peer.plan(
                    "POST", "/__test/control", {}, {"action": "release"}
                )
                assert code == 200
                result = await pending
            else:
                result = await client.chat_message_window(identity, options)
        except SessionClientError as error:
            error_code = error.code
        assert error_code == vector["expected_error"]
        if vector["expected_error"] is None:
            assert_window(suite, vector, result, expected_scope)
        else:
            assert result is None
        if vector["mode"] == "partial_cache":
            assert (await client.open_chat(identity))["messages"] == vector[
                "expected_cached_messages"
            ]
        report = peer.status()
        assert report["failure"] is None
        assert (
            report["metadata"] == vector["expected_metadata_requests"]
            and report["window"] == vector["expected_window_requests"]
        )
        assert report["identity"] == "pip" and set(vector["expected_checks"]) <= set(
            report["checks"]
        )
        return {
            "id": vector["id"],
            "status": "passed",
            "checks": vector["expected_checks"],
        }
    finally:
        try:
            await client.close()
        finally:
            peer.close()


async def run(suite):
    return [await asyncio.wait_for(run_vector(suite, v), 15) for v in suite["vectors"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args()
    try:
        assert args.capability == CAPABILITY
        raw = Path(args.fixture).read_bytes()
        suite = json.loads(raw)["capabilities"][CAPABILITY]
        results = asyncio.run(run(suite))
    except Exception:
        print("Python one-page library conformance failed", file=sys.stderr)
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
