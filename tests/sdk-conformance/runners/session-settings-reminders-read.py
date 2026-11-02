#!/usr/bin/env python3
"""Actual public Python Account read; run only in isolated CI, never local product."""

# contract-test-file: tooling
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from openmates import SessionClient, SessionSettingsReadError  # noqa: E402 - import follows sys.path setup for sibling runner modules
from session_settings_reminders_server import CAPABILITY, SettingsPeer  # noqa: E402 - import follows sys.path setup for sibling runner modules

DEADLINE = 75


def session(endpoint):
    return {
        "api_url": endpoint,
        "session_id": "synthetic-settings-session",
        "cookies": {"auth_refresh_token": "fixture"},
        "ws_token": None,
        "master_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "hashed_email": "synthetic",
        "user_email_salt": "",
        "email_encryption_key": None,
        "created_at": 0,
        "paired_session_expires_at": None,
        "active_team_id": "00000000-0000-4000-8000-000000000001",
    }


def exact_json(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            exact_json(left[k], right[k]) for k in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            exact_json(a, b) for a, b in zip(left, right)
        )
    return left == right


async def run_case(item):
    peer = SettingsPeer(item, "pip").start()
    client = None
    primary = None
    try:
        client = SessionClient(
            api_url=peer.endpoint,
            app_url="https://app.example.invalid",
            enhanced_privacy=False,
            allow_private_operations=False,
        )
        if item["session"]:
            await asyncio.wait_for(client.import_session(session(peer.endpoint)), 2)
        value = error = None
        try:
            if item.get("action") in {"cancel_body", "cancel_retry"}:
                pending = asyncio.create_task(client.account.reminders())
                entered = await asyncio.to_thread(peer.ready.wait, 5)
                assert entered and peer.status()["requests"] == 1
                pending.cancel()
                peer.released.set()
                try:
                    value = await asyncio.wait_for(pending, DEADLINE)
                except asyncio.CancelledError as caught:
                    error = caught
            else:
                value = await asyncio.wait_for(client.account.reminders(), DEADLINE)
        except Exception as caught:
            error = caught
        expected = item["expected"]
        if expected["ok"]:
            assert error is None, "successful raw read"
            assert exact_json(value, expected["value"]), (
                "complete raw JSON, including scalars/null and unknown encrypted fields"
            )
            if "root_keys" in expected:
                assert type(value) is dict
                serialized = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":")
                )
                assert serialized == expected["serialized_json"], (
                    "exact public serialized JSON including root order and Unicode"
                )
                root_pairs = json.loads(serialized, object_pairs_hook=list)
                assert [key for key, _ in root_pairs] == expected["root_keys"], (
                    "actual public raw serialization retains root order"
                )
        else:
            if isinstance(error, asyncio.CancelledError):
                assert item.get("action") in {"cancel_body", "cancel_retry"}
                assert (
                    expected["error"] == "Cancelled" and expected["http_status"] is None
                )
            else:
                assert isinstance(error, SessionSettingsReadError), (
                    "actual native typed settings failure"
                )
                assert error.code == expected["error"].lower()
                assert error.http_status == expected["http_status"]
                if "message" in expected:
                    assert str(error) == expected["message"], (
                        "exact typed settings refusal message"
                    )
                if expected["http_status"] is not None:
                    assert (
                        str(error)
                        == f"Settings GET failed with HTTP {expected['http_status']}"
                    )
        observed = peer.status()
        assert observed["failure"] is None
        assert observed["requests"] == expected["requests"], (
            "exact attempts/no implicit extra retry"
        )
        if expected["wait_ms"]:
            assert len(observed["times_ns"]) == 2
            assert (
                observed["times_ns"][1] - observed["times_ns"][0]
            ) // 1_000_000 >= 61000
        if (
            item["id"]
            in {"cookie-rotation-malformed-body", "one-429-retry-cookie-preserved"}
            or item.get("action") == "cancel_body"
        ):
            exported = await asyncio.wait_for(
                client.export_session(include_secrets=True), 2
            )
            assert exported["session"]["cookies"]["auth_refresh_token"] == "rotated"
        if item["id"] in {"expired-malformed-body", "owner-denial"}:
            try:
                await asyncio.wait_for(client.export_session(include_secrets=True), 2)
            except Exception as error:
                assert getattr(error, "code", None) == "authentication"
            else:
                raise AssertionError("canonical credential revocation must persist")
        return {"id": item["id"], "status": "passed"}
    except BaseException as error:
        primary = error
        raise
    finally:
        peer.released.set()
        failures = []
        try:
            if client is not None:
                await asyncio.wait_for(client.close(), 2)
        except BaseException as error:
            failures.append(error)
        try:
            observed = peer.status()
            assert observed["failure"] is None
            assert observed["requests"] == item["expected"]["requests"]
        except BaseException as error:
            failures.append(error)
        try:
            await asyncio.to_thread(peer.close)
        except BaseException as error:
            failures.append(error)
        if failures and primary is None:
            raise failures[0]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", choices=[CAPABILITY], required=True)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    assert len(raw) <= 1024 * 1024
    suite = json.loads(raw)
    assert suite["capability"] == CAPABILITY
    assert suite["retry"] == {"only_status": 429, "max_retries": 1, "delay_ms": 61000}
    assert len(suite["cases"]) == 28, "complete shared V4 fixture required"
    assert len({x["id"] for x in suite["cases"]}) == len(suite["cases"])
    results = []
    for item in suite["cases"]:
        assert re.fullmatch(r"[a-z0-9-]{1,80}", item["id"])
        results.append(await run_case(item))
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
    try:
        asyncio.run(main())
    except BaseException:
        print("Python settings reminders conformance failed", file=sys.stderr)
        raise SystemExit(1)
