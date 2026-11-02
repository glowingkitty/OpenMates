#!/usr/bin/env python3
"""PRIVATE UNRUN: actual PyO3 source authoring against independent synthetic peer."""

# contract-test-file: tooling
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import inspect
import json
import re
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from openmates import OpenMates, SessionClient, SessionClientError, RustApiKeyClient, RustApiKeyClientError  # noqa: E402
from session_project_sources_server import CAPABILITY, SourcesPeer, exact_json_equal  # noqa: E402

DEADLINE = 12


def session(suite, endpoint):
    return {
        "api_url": endpoint,
        "session_id": suite["account"]["session_id"],
        "cookies": {"auth_refresh_token": suite["account"]["cookie"]},
        "ws_token": None,
        "master_key": suite["account"]["master_key"],
        "hashed_email": "synthetic-source-email",
        "user_email_salt": "synthetic-salt",
        "email_encryption_key": None,
        "created_at": 1,
        "paired_session_expires_at": None,
        "active_team_id": None,
    }


def control(endpoint, command=None):
    request = Request(
        endpoint + ("/__test/control" if command else "/__test/status"),
        data=json.dumps(command).encode() if command else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=DEADLINE) as response:
        report = json.load(response)
    assert report["failure"] is None, "synthetic source peer refused transport"
    return report


async def refused(operation, code, api_key=False):
    try:
        value = operation() if callable(operation) else operation
        if inspect.isawaitable(value):
            await asyncio.wait_for(value, DEADLINE)
    except Exception as error:
        assert not isinstance(error, TimeoutError), "operation rejection deadline"
        assert getattr(error, "code", None) == code, "exact typed source error"
        if api_key:
            assert (
                getattr(error, "reason", None)
                == "PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION"
            )
        else:
            assert isinstance(error, SessionClientError), (
                "actual native typed source error"
            )
        return
    raise AssertionError("source operation unexpectedly accepted")


def expected_source(suite, case):
    if case["operation"] == "create":
        return case["input"]
    return {
        **copy.deepcopy(suite["seed"]),
        "source_id": case["source_id"],
        **case["input"],
    }


async def read_refused(operation, code, api_key):
    try:
        value = operation() if callable(operation) else operation
        await asyncio.wait_for(value, DEADLINE)
    except Exception as error:
        assert not isinstance(error, TimeoutError), "read rejection deadline"
        assert getattr(error, "code", None) == code, "exact typed read error"
        assert isinstance(error, RustApiKeyClientError if api_key else SessionClientError)
        return
    raise AssertionError("source read unexpectedly accepted")


async def run_vector(suite, vector):
    peer = SourcesPeer(suite, vector, "pip").start()
    client = None
    read_api = None
    primary = None
    try:
        if vector["mode"] == "read-api-key":
            read_api = RustApiKeyClient(api_key="sk-api-syntheticsources", api_url=peer.endpoint,
                device_id="synthetic-source-device", enhanced_privacy=False, allow_private_operations=True)
        else:
            client = SessionClient(api_url=peer.endpoint, app_url="https://app.example.invalid",
                enhanced_privacy=False, allow_private_operations=False)
            imported = session(suite, peer.endpoint)
            if vector["mode"] == "read-unrelated-master":
                imported["master_key"] = "KioqKioqKioqKioqKioqKioqKioqKioqKioqKioqKio="
            if vector["mode"] in {"expired", "read-expired"}:
                imported["paired_session_expires_at"] = time.time_ns() // 1_000_000 + 2000
            await client.import_session(imported)
            await client.set_team(suite["team"]["team_id"])
            if vector["mode"] in {"expired", "read-expired"}:
                await asyncio.to_thread(control, peer.endpoint,
                    {"op": "await_expiry", "deadline_ms": imported["paired_session_expires_at"]})
        filters = (
            {"team_id": suite["team"]["team_id"]}
            if vector.get("team")
            else {"personal": True}
        )
        api = (
            OpenMates(
                api_key="sk-api-syntheticsources",
                api_url=peer.endpoint,
                device_id="synthetic-source-device",
            )
            if vector["mode"] == "api-key"
            else None
        )
        for index, case in enumerate(vector["cases"]):
            await asyncio.to_thread(
                control, peer.endpoint, {"op": "case", "index": index}
            )
            before = peer.status()
            service = api.projects if api is not None else client.projects if client is not None else None
            is_read = case["operation"] in {"list-raw", "list-names"}

            async def operation():
                if case["operation"] == "list-raw":
                    value = (read_api.list_project_sources_raw(suite["project_id"], filters=filters)
                             if read_api is not None else service.list_sources_raw(suite["project_id"], filters=filters))
                elif case["operation"] == "list-names":
                    value = service.list_sources_decoded_names(suite["project_id"], filters=filters)
                elif case["operation"] == "create":
                    value = service.create_source(
                        suite["project_id"], case["input"], filters=filters
                    )
                else:
                    value = service.update_source_capabilities(
                        suite["project_id"],
                        case["source_id"],
                        case["input"],
                        filters=filters,
                    )
                return await value if inspect.isawaitable(value) else value

            if is_read:
                if vector["mode"] == "read-cancel" and index == 0:
                    pending = asyncio.create_task(operation())
                    await asyncio.to_thread(control, peer.endpoint, {"op": "entered"})
                    client.cancel()
                    await asyncio.to_thread(control, peer.endpoint, {"op": "release"})
                    await read_refused(pending, "cancelled", False)
                elif case["expected_error"]:
                    await read_refused(operation, case["expected_error"], read_api is not None)
                else:
                    if not exact_json_equal(await asyncio.wait_for(operation(), DEADLINE), case["expected"]):
                        raise AssertionError("exact raw rows or name-only DTO with unknown metadata")
            elif vector["mode"] == "api-key":
                await refused(operation, "project_source_authoring_unavailable", True)
            elif vector["mode"] == "cancel" and index == 0:
                pending = asyncio.create_task(operation())
                await asyncio.to_thread(control, peer.endpoint, {"op": "entered"})
                client.cancel()
                await asyncio.to_thread(control, peer.endpoint, {"op": "release"})
                await refused(pending, "cancelled")
            elif case["expected_error"]:
                await refused(operation, case["expected_error"])
            else:
                assert exact_json_equal(
                    await asyncio.wait_for(operation(), DEADLINE),
                    expected_source(suite, case),
                ), "full exact source DTO/metadata"
            after = peer.status()
            assert after["failure"] is None
            assert after["mutation_attempts"] - before["mutation_attempts"] == (
                0 if api is not None else case["expected_mutation_attempts"]
            ), "exact attempts, no retry"
            if is_read:
                for field, expected in [("source_reads", case["expected_read_attempts"]),
                                        ("project_reads", case["expected_project_attempts"]),
                                        ("team_reads", case["expected_team_attempts"])]:
                    assert after[field] - before[field] == expected, "exact read attempts/no extra resolve"
                if read_api is not None:
                    assert after["project_reads"] - before["project_reads"] == 0
                    assert after["team_reads"] - before["team_reads"] == 0
            if case["zero_transport"]:
                assert after["requests"] == before["requests"], (
                    "refuse before transport"
                )
            if after["requests"] > before["requests"] and read_api is None:
                exported = await client.export_session(include_secrets=True)
                assert (
                    exported["session"]["active_team_id"] == suite["team"]["team_id"]
                ), "source operation never changes selected Team"
                assert (
                    exported["session"]["cookies"]["auth_refresh_token"]
                    == after["cookie"]
                ), "retain latest final cookie on rejection/cancellation"
        return {"id": vector["id"], "status": "passed"}
    except BaseException as error:
        primary = error
        raise
    finally:
        # Unblock only this synthetic peer before waiting for credential-completing close.
        peer.released.set()
        failures = []
        for name, resource in (("client", client), ("api_key", read_api), ("peer", peer)):
            if resource is None:
                continue
            try:
                if name == "api_key":
                    resource.close()
                elif name == "peer":
                    await asyncio.to_thread(resource.close)
                else:
                    await asyncio.wait_for(resource.close(), DEADLINE)
            except BaseException as error:
                failures.append((name, error))
        if failures:
            failure = primary if primary is not None else failures[0][1]
            for name, _ in failures:
                failure.add_note(f"source fixture cleanup also failed: {name}")
            if primary is None:
                raise failure


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", choices=[CAPABILITY], required=True)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    assert suite["vectors"] and len({v["id"] for v in suite["vectors"]}) == len(
        suite["vectors"]
    )
    results = []
    for vector in suite["vectors"]:
        try:
            assert vector["cases"]
            results.append(await run_vector(suite, vector))
        except Exception as error:
            label = (
                vector["id"]
                if re.fullmatch(r"[a-z0-9-]{1,80}", vector["id"])
                else "invalid"
            )
            code = getattr(error, "code", type(error).__name__)
            code = (
                code
                if isinstance(code, str) and re.fullmatch(r"[a-zA-Z_0-9]{1,80}", code)
                else "unknown"
            )
            sys.stderr.write(f"source_case_failed:{label}:{code}\n")
            raise
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
    except Exception:
        sys.stderr.write("Python source conformance failed\n")
        raise SystemExit(1) from None
