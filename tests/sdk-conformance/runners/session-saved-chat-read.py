#!/usr/bin/env python3
"""Actual PyO3 bounded saved-read reads against a shared synthetic owned HTTP peer.

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
from saved_chat_read_server import CAPABILITY, SavedChatReadPeer as MessageWindowPeer  # noqa:E402


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


async def assert_full_read(client, suite, vector, identity, peer):
    from openmates import SessionClientError
    from openmates.session_client import _failure

    result, error_code = None, None
    try:
        if vector["full_action"] == "inflight_cancel":
            pending = asyncio.create_task(client.open_chat(identity))
            observed = False
            for _ in range(500):
                if peer.status()["metadata"] == 1:
                    observed = True
                    break
                await asyncio.sleep(0.005)
            assert observed
            client.cancel()
            code, _ = peer.plan("POST", "/__test/control", {}, {"action": "release"})
            assert code == 200
            result = await pending
        else:
            result = await client.open_chat(identity)
    except SessionClientError as error:
        error_code = error.code
    assert error_code == vector["expected_error"]
    if error_code is not None:
        assert result is None
        return
    exact(result, vector["full_expected"])
    # A genuine opaque PyO3 object has crossed the native future/GIL queue.
    # Sync finish below is the production PyString allocation, never a double.
    action = vector.get("foreign_final")
    if action:
        output = await client._native.open_chat_prepare(identity)
        try:
            if action == "permitted":
                exact(json.loads(output.release_json()), vector["full_expected"])
            elif action == "cancel":
                client.cancel()
            elif action == "owner":
                await client.import_session(
                    dict(
                        api_url=peer.endpoint,
                        session_id=suite["account"]["session_id"] + "-replacement",
                        cookies={"auth_refresh_token": suite["account"]["cookie"]},
                        ws_token=None,
                        master_key=suite["account"]["master_key"],
                        hashed_email="other-synthetic-owner",
                        user_email_salt="synthetic",
                        email_encryption_key=None,
                        created_at=1,
                        paired_session_expires_at=None,
                        active_team_id=None,
                    )
                )
            elif action == "successor":
                # B holds the actual HTTP/client lane while queued A is refused.
                pending = asyncio.create_task(client.open_chat(identity))
                observed = False
                for _ in range(500):
                    if peer.status()["metadata"] == 3:
                        observed = True
                        break
                    await asyncio.sleep(0.005)
                assert observed
                try:
                    output.release_json()
                except Exception as error:
                    assert _failure(error).code == "conflict"
                else:
                    raise AssertionError("contended native full read released")
                code, _ = peer.plan(
                    "POST", "/__test/control", {}, {"action": "release"}
                )
                assert code == 200
                exact(await pending, vector["full_expected"])
                assert "successor-barrier-released" in peer.status()["checks"]
            else:
                assert action == "discard"
                output.discard()
            try:
                output.release_json()
            except Exception as error:
                assert _failure(error).code == "cancelled"
            else:
                raise AssertionError("stale native full read released")
        finally:
            output.discard()


async def assert_details_read(client, suite, vector, identity, peer):
    from openmates import SessionClientError

    expected = copy.deepcopy(vector["expected_details"])
    if "expected_draft_utf16" in vector:
        expected["chat"]["draftPreview"] = "".join(
            chr(unit) for unit in vector["expected_draft_utf16"]
        )
    if "expected_pii_utf16" in vector:
        raw = vector["expected_pii_utf16"]
        expected["messages"][raw["index"]]["piiMappings"] = [
            "".join(chr(unit) for unit in raw["units"])
        ]
    if "semantic_pii" in vector:
        semantic = vector["semantic_pii"]
        expected["messages"][semantic["message_index"]]["piiMappings"] = json.loads(
            semantic["sdk_json"]
        )
    from openmates.session_client import _failure

    result, error_code = None, None
    try:
        if vector["details_action"] == "inflight_cancel":
            pending = asyncio.create_task(
                client.chat_details(identity, vector["details_options"])
            )
            observed = False
            for _ in range(500):
                if peer.status()[vector.get("cancel_barrier", "metadata")] == 1:
                    observed = True
                    break
                await asyncio.sleep(0.005)
            assert observed
            client.cancel()
            code, _ = peer.plan("POST", "/__test/control", {}, {"action": "release"})
            assert code == 200
            result = await pending
        else:
            result = await client.chat_details(identity, vector["details_options"])
    except SessionClientError as error:
        error_code = error.code
    assert error_code == vector["expected_error"]
    if error_code is not None:
        assert result is None
        return
    exact(result, expected)
    if "semantic_pii" in vector:
        import math

        def signs(actual, reference):
            if isinstance(reference, float) and reference == 0.0:
                assert math.copysign(1.0, actual) == math.copysign(1.0, reference)
            elif isinstance(reference, list):
                for value, item in zip(actual, reference):
                    signs(value, item)
            elif isinstance(reference, dict):
                assert list(actual) == list(reference)
                for key in reference:
                    signs(actual[key], reference[key])

        index = vector["semantic_pii"]["message_index"]
        signs(
            result["messages"][index]["piiMappings"],
            expected["messages"][index]["piiMappings"],
        )

    # A genuine opaque PyO3 object has crossed the native future/GIL queue.
    # Sync finish below is the production PyString allocation, never a double.
    action = vector.get("foreign_final")
    if action:
        output = await client._native.chat_details_prepare(
            identity, json.dumps(vector["details_options"])
        )
        try:
            if action == "permitted":
                exact(json.loads(output.release_json()), expected)
            elif action == "cancel":
                client.cancel()
            elif action == "owner":
                await client.import_session(
                    dict(
                        api_url=peer.endpoint,
                        session_id=suite["account"]["session_id"] + "-replacement",
                        cookies={"auth_refresh_token": suite["account"]["cookie"]},
                        ws_token=None,
                        master_key=suite["account"]["master_key"],
                        hashed_email="other-synthetic-owner",
                        user_email_salt="synthetic",
                        email_encryption_key=None,
                        created_at=1,
                        paired_session_expires_at=None,
                        active_team_id=None,
                    )
                )
            elif action == "successor":
                # B holds the actual HTTP/client lane while queued A is refused.
                pending = asyncio.create_task(
                    client.chat_details(identity, vector["details_options"])
                )
                observed = False
                for _ in range(500):
                    if peer.status()["metadata"] == 3:
                        observed = True
                        break
                    await asyncio.sleep(0.005)
                assert observed
                try:
                    output.release_json()
                except Exception as error:
                    assert _failure(error).code == "conflict"
                else:
                    raise AssertionError("contended native full read released")
                code, _ = peer.plan(
                    "POST", "/__test/control", {}, {"action": "release"}
                )
                assert code == 200
                exact(await pending, expected)
                assert "successor-barrier-released" in peer.status()["checks"]
            else:
                assert action == "discard"
                output.discard()
            try:
                output.release_json()
            except Exception as error:
                assert _failure(error).code == "cancelled"
            else:
                raise AssertionError("stale native full read released")
        finally:
            output.discard()


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
        if (
            vector["mode"] != "noauth"
            and vector.get("full_action") != "noauth"
            and vector.get("details_action") != "noauth"
        ):
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
                    active_team_id=vector.get("team_id"),
                )
            )
        identity = suite["protocol"]["chat_id"]
        if vector["mode"] == "details":
            await assert_details_read(client, suite, vector, identity, peer)
            report = peer.status()
            assert report["failure"] is None and report["identity"] == "pip"
            assert report["consumed"] == len(vector["requests"])
            assert report["metadata"] == vector["expected_metadata_requests"]
            assert report["window"] == vector["expected_window_requests"]
            assert report["exact"] == vector["expected_exact_requests"]
            assert report["details_embeds"] == vector["expected_embed_requests"]
            assert set(vector["expected_checks"]) <= set(report["checks"])
            return {
                "id": vector["id"],
                "status": "passed",
                "checks": vector["expected_checks"],
                "detailsBoundary": vector.get(
                    "foreign_final", vector["details_action"]
                ),
            }
        if vector["mode"] == "full":
            await assert_full_read(client, suite, vector, identity, peer)
            report = peer.status()
            assert report["failure"] is None and report["identity"] == "pip"
            assert report["consumed"] == len(vector["requests"])
            assert report["metadata"] == vector["expected_metadata_requests"]
            assert report["window"] == vector["expected_window_requests"]
            assert report["exact"] == vector["expected_exact_requests"]
            assert set(vector["expected_checks"]) <= set(report["checks"])
            return {
                "id": vector["id"],
                "status": "passed",
                "checks": vector["expected_checks"],
                "fullReadBoundary": vector.get("foreign_final", vector["full_action"]),
            }
        options = copy.deepcopy(vector["options"])
        expected_scope = None
        if "preflight" in vector:
            first = await client.saved_chat_read(identity, vector["preflight"])
            assert_window(
                suite,
                {
                    "expected_public_paging": vector["preflight_expected"],
                    "expected_messages": vector["preflight_expected"]["chat"][
                        "messages"
                    ],
                },
                first,
            )
            expected_scope = first["startCursor"]["scope"]
            options["after" if vector["mode"] == "after" else "before"] = copy.deepcopy(
                first["startCursor"]
            )
            assert options["after" if vector["mode"] == "after" else "before"]["scope"]
            if vector["mode"] == "forbidden_context":
                options["before"]["chatId"] = "99999999-9999-4999-8999-999999999999"
            if vector["mode"] == "wrong_scope":
                options["before"]["scope"] = "0" * 64
        if vector["mode"] == "partial_cache":
            assert (await client.open_chat(identity))["messages"] == vector[
                "expected_cached_messages"
            ]
        result, error_code = None, None
        try:
            if vector["mode"] == "cancel":
                pending = asyncio.create_task(client.saved_chat_read(identity, options))
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
                result = await client.saved_chat_read(identity, options)
        except SessionClientError as error:
            error_code = error.code
        assert error_code == vector["expected_error"]
        if vector["expected_error"] is None:
            assert_window(suite, vector, result, expected_scope)
            if vector["mode"] == "exact":
                selector = copy.deepcopy(result["oversizedMessageCursor"])
                if vector.get("exactCursorMutation") == "scope":
                    selector["scope"] = "0" * 64
                if vector.get("exactCursorMutation") == "chat":
                    selector["chatId"] = "99999999-9999-4999-8999-999999999999"
                selected = None
                exact_error = None
                try:
                    operation = client.saved_chat_exact_message(
                        identity, {"cursor": selector, "contentMode": "stored"}
                    )
                    if vector.get("exactAction") == "cancel":
                        pending = asyncio.create_task(operation)
                        observed = False
                        for _ in range(500):
                            if peer.status()["metadata"] == 2:
                                observed = True
                                break
                            await asyncio.sleep(0.005)
                        assert observed
                        client.cancel()
                        code, _ = peer.plan(
                            "POST", "/__test/control", {}, {"action": "release"}
                        )
                        assert code == 200
                        selected = await pending
                    else:
                        selected = await operation
                except SessionClientError as error:
                    exact_error = error.code
                assert exact_error == vector.get("exact_expected_error")
                if exact_error is None:
                    exact(selected, vector["exact_expected"])
                else:
                    assert selected is None
        else:
            assert result is None
        if vector["mode"] == "partial_cache":
            assert (await client.open_chat(identity))["messages"] == vector[
                "expected_cached_messages"
            ]
        report = peer.status()
        assert report["exact"] == vector["expected_exact_requests"]
        assert report["consumed"] == len(vector["requests"])
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
        print("Python bounded saved-read library conformance failed", file=sys.stderr)
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
