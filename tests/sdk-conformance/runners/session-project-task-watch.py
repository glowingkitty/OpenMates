#!/usr/bin/env python3
"""Actual PyO3 public watch facade; shared deterministic loopback fixture."""

# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import inspect
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from session_project_task_watch_server import CAPABILITY, WatchPeer  # noqa: E402
from openmates import SessionClient, SessionClientError  # noqa: E402
from openmates.sdk import OpenMates  # noqa: E402

DEADLINE = 10


def session(suite, endpoint):
    return {
        "api_url": endpoint,
        "session_id": suite["account"]["session_id"],
        "cookies": {"auth_refresh_token": suite["account"]["cookie"]},
        "ws_token": "synthetic-watch-ws",
        "master_key": suite["account"]["master_key"],
        "hashed_email": "synthetic-email-hash",
        "user_email_salt": "synthetic-salt",
        "email_encryption_key": None,
        "created_at": 1,
        "paired_session_expires_at": None,
        "active_team_id": None,
    }


def request(endpoint, operation):
    data = json.dumps(operation).encode()
    with urlopen(
        Request(
            endpoint + "/__test/control",
            data=data,
            headers={"Content-Type": "application/json"},
        ),
        timeout=DEADLINE,
    ) as response:
        result = json.load(response)
    assert result["failure"] is None, "fixture rejected transport"
    return result


async def rejected(future, codes=None):
    try:
        value = future() if callable(future) else future
        if inspect.isawaitable(value):
            await asyncio.wait_for(value, DEADLINE)
    except Exception as error:
        assert not isinstance(error, TimeoutError), "rejection deadline"
        if codes:
            if "project_task_watch_unavailable" not in codes:
                assert isinstance(error, SessionClientError), (
                    "native typed SessionClientError"
                )
            assert getattr(error, "code", None) in codes, "typed refusal"
            if "project_task_watch_unavailable" in codes:
                assert (
                    getattr(error, "reason", None)
                    == "PROJECT_TASK_WATCH_REQUIRES_COOKIE_SESSION"
                )
        return
    raise AssertionError("operation unexpectedly accepted")


class Scenario:
    def __init__(self, suite, vector, endpoint, client):
        self.suite, self.vector, self.endpoint, self.client = (
            suite,
            vector,
            endpoint,
            client,
        )
        self.scope = (
            {"team_id": suite["team"]["team_id"]}
            if vector.get("team")
            else {"personal": True}
        )
        self.watches, self.snapshots, self.saved_receipts = {}, {}, {}
        self.bindings = {}
        self.directory = tempfile.TemporaryDirectory(prefix="sdk-watch-durable-")

    async def raw_control(self, op, **fields):
        return await asyncio.to_thread(request, self.endpoint, {"op": op, **fields})

    async def bind(self, name):
        binding = self.bindings[name]
        report = await self.raw_control("beacon", key="subscriptions", minimum=0)
        if binding.get("generation") in report["active_generations"]:
            return binding["generation"]
        after = binding.get("generation", binding["after"])
        report = await self.raw_control(
            "bind_watch", watch=name, after=after, source_id=self.suite["source_id"]
        )
        assert (
            report["source_id"] == self.suite["source_id"]
            and report["project_id"] == self.suite["project_id"]
        )
        assert type(report["generation"]) is int and report["generation"] > after
        binding["generation"] = report["generation"]
        return report["generation"]

    async def bind_pending(self):
        for name, binding in list(self.bindings.items()):
            if "generation" not in binding:
                await self.bind(name)

    async def control(self, op, **fields):
        if "watch" in fields:
            name = fields["watch"]
            if op in ("closed", "late_force_logout"):
                assert "generation" in self.bindings[name], (
                    "observed prior connection generation required"
                )
                generation = self.bindings[name]["generation"]
            else:
                generation = await self.bind(name)
            fields["generation"] = generation
        return await self.raw_control(op, **fields)

    async def open(self, name, checkpoint=None):
        # Complete previous admission before another indistinguishable canonical
        # subscription may arrive. No test labels enter SDK requests/WS frames.
        await self.bind_pending()
        report = await self.raw_control("beacon", key="subscriptions", minimum=0)
        self.watches[name] = await self.client.projects.watch_tasks(
            self.suite["project_id"],
            source_id=self.suite["source_id"],
            filters=self.scope,
            checkpoint=checkpoint,
        )
        self.bindings[name] = {"after": report["subscriptions"]}

    async def event(self, name, target, terminal=False):
        for _ in range(32):
            try:
                value = await asyncio.wait_for(anext(self.watches[name]), DEADLINE)
            except Exception as error:
                if (terminal or target == "refused") and getattr(
                    error, "code", None
                ) in ("cancelled", "forbidden", "expired"):
                    if "generation" not in self.bindings.get(name, {}):
                        self.bindings.pop(name, None)
                    return {"kind": "state", "state": "closed"}
                raise
            assert value["kind"] in ("snapshot", "state")
            if terminal:
                # No plaintext is allowed to escape a revoked queued publication.
                assert value["kind"] != "snapshot", (
                    "stale plaintext after terminal control"
                )
                if value.get("state") in ("revoked", "expired", "closed", "failed"):
                    if "generation" not in self.bindings.get(name, {}):
                        self.bindings.pop(name, None)
                    return value
            elif (
                target == "refused"
                and value["kind"] == "state"
                and value.get("state")
                in ("reconnecting", "failed", "revoked", "expired", "closed")
            ):
                return value
            elif value["kind"] == target or value.get("state") == target:
                return value
            else:
                assert value.get("state") not in (
                    "revoked",
                    "expired",
                    "closed",
                    "failed",
                ), "unexpected terminal watch"
        raise AssertionError("bounded state transitions")

    def durable(self, name):
        checkpoint = self.snapshots[name]["checkpoint"]
        path = Path(self.directory.name) / (name + ".json")
        raw = json.dumps(checkpoint, sort_keys=True).encode()
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                assert written > 0, "checkpoint full write"
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(self.directory.name, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        assert json.loads(path.read_bytes()) == checkpoint

    def snapshot(self, name, value, count, cursor):
        assert value["cursor"] == cursor and len(value["tasks"]) == count
        scope = value["scope"]
        assert scope == {
            "api_url": self.endpoint,
            "account_id": self.suite["owner_id"],
            "workspace": {"team": self.suite["team"]["team_id"]}
            if self.vector.get("team")
            else "personal",
            "project_id": self.suite["project_id"],
            "source_id": self.suite["source_id"],
        }
        rows = value["tasks"]
        ids = [r["task_id"] for r in rows]
        assert len(set(ids)) == count
        expected = (
            set(range(2, 23)) if cursor == "epoch:2" else set(range(1, count + 1))
        )
        assert {int(value.replace("-", ""), 16) for value in ids} == expected, (
            "exact replacement/removal inventory"
        )
        for row in rows:
            index = int(row["task_id"].replace("-", ""), 16) - 1
            assert row["task"]["title"] == f"Synthetic watch Task {index}"
            assert row["task"]["description"] == "Synthetic private description"
        assert "encrypted_title" not in json.dumps([r["task"] for r in rows])
        assert value["checkpoint"]["cursor"] == cursor
        assert value["checkpoint"]["scope"] == scope
        assert len(value["checkpoint"]["tasks"]) == count
        assert all(
            r["opaque_fixture_metadata"] == {"preserved": True}
            for r in value["checkpoint"]["tasks"]
        )
        assert "Synthetic watch Task" not in json.dumps(value["checkpoint"])
        self.snapshots[name] = value

    async def execute(self, step):
        op, name = step["op"], step.get("watch", "a")
        if op == "open":
            cp = (
                copy.deepcopy(self.snapshots[step["checkpoint"]]["checkpoint"])
                if "checkpoint" in step
                else None
            )
            await self.open(name, cp)
        elif op in (
            "send",
            "beacon",
            "closed",
            "drop",
            "revoke",
            "force_logout",
            "late_force_logout",
            "ttl_elapsed",
            "hold_upgrade",
            "release_upgrade",
            "deny_source",
            "rotate",
            "idle_flood",
        ):
            await self.control(op, **{k: v for k, v in step.items() if k != "op"})
        elif op == "multipart_snapshot":
            pending = asyncio.create_task(self.event(name, "snapshot"))
            try:
                await asyncio.wait_for(asyncio.shield(pending), 0.1)
            except TimeoutError:
                pass  # Bounded negative read; actual next remains live.
            else:
                raise AssertionError("partial multipart publication")
            await self.control("send", watch=name, kind="final")
            value = await asyncio.wait_for(pending, DEADLINE)
            self.snapshot(name, value, step["count"], step["cursor"])
        elif op == "reject_current_commit":
            await rejected(
                self.watches[name].commit(self.snapshots[name]["receipt"]), {"conflict"}
            )
        elif op == "snapshot":
            value = await self.event(name, "snapshot")
            self.snapshot(name, value, step["count"], step["cursor"])
        elif op == "state":
            value = await self.event(name, step["state"])
            assert (
                value["state"] == step["state"]
                and value["cursor"] == self.snapshots[name]["receipt"]["cursor"]
            )
        elif op == "terminal":
            await self.event(name, "", terminal=True)
        elif op == "commit":
            self.durable(name)
            await self.watches[name].commit(self.snapshots[name]["receipt"])
        elif op == "reject_commit":
            correct = self.snapshots[name]["receipt"]
            for bad in (
                {**correct, "batch_id": "wrong"},
                {**correct, "cursor": "epoch:999"},
            ):
                await rejected(self.watches[name].commit(bad), {"conflict"})
        elif op == "reject_expired_commit":
            await rejected(
                self.watches[name].commit(self.snapshots[name]["receipt"]),
                {"expired", "cancelled", "conflict"},
            )
        elif op == "set_team":
            await self.bind_pending()
            await self.client.set_team(self.suite["team"]["team_id"])
        elif op == "close_client":
            await self.bind_pending()
            await self.client.close()
        elif op == "save_receipt":
            self.saved_receipts[name] = copy.deepcopy(self.snapshots[name]["receipt"])
        elif op == "reject_saved_commit":
            await rejected(
                self.watches[name].commit(self.saved_receipts[name]), {"conflict"}
            )
        elif op == "assert_resume":
            report = await self.control("beacon", key="subscriptions", minimum=1)
            assert report["resumes"][-1] == step["cursor"]
        elif op == "ordinary_read":
            assert (
                await asyncio.wait_for(
                    self.client.projects.list(filters=self.scope), DEADLINE
                )
                == []
            )
        elif op == "close":
            await self.watches[name].close()
            if "generation" not in self.bindings.get(name, {}):
                self.bindings.pop(name, None)
        elif op == "iterator_close":
            async with self.watches[name]:
                pass
            try:
                await asyncio.wait_for(anext(self.watches[name]), DEADLINE)
            except StopAsyncIteration:
                pass
            else:
                raise AssertionError("closed iterator must stop iteration")
        elif op == "close_pending":
            pending = asyncio.create_task(anext(self.watches[name]))
            await self.execute({"op": "ordinary_read"})
            await self.watches[name].close()
            try:
                value = await asyncio.wait_for(pending, DEADLINE)
                assert value["kind"] == "state" and value["state"] == "closed"
            except StopAsyncIteration:
                pass
        elif op == "reset":
            await self.bind_pending()
            await self.client.import_session(session(self.suite, self.endpoint))
        elif op == "assert_session":
            exported = await self.client.export_session(include_secrets=True)
            assert (
                exported["session"]["session_id"] == self.suite["account"]["session_id"]
            )
        elif op == "assert_logged_out":
            await rejected(
                self.client.export_session(include_secrets=True), {"authentication"}
            )
        elif op == "assert_rotation":
            exported = await self.client.export_session(include_secrets=True)
            assert (
                exported["session"]["cookies"]["auth_refresh_token"]
                == "synthetic-watch-rotated"
            )
        elif op == "tampered_checkpoint":
            for mutate in ("source", "ciphertext"):
                cp = copy.deepcopy(self.snapshots["a"]["checkpoint"])
                if mutate == "source":
                    cp["scope"]["source_id"] = "foreign-source"
                else:
                    cp["tasks"][0]["encrypted_title"] = "invalid-ciphertext"
                await self.open("bad", cp)
                await self.event("bad", "", terminal=True)
        elif op == "negative_scope":
            for corruption in ("owner", "project", "team", "ciphertext", "expired"):
                await self.open("a")
                minimum = self._next_subscription()
                await self.control("beacon", key="subscriptions", minimum=minimum)
                await self.control("send", watch="a", kind="bad-" + corruption)
                await self.event("a", "refused")
                await self.watches["a"].close()
                await self.control("closed", watch="a")
        elif op == "cap":
            for i in range(16):
                await self.open(str(i))
            await self.control("beacon", key="subscriptions", minimum=16)
            await rejected(self.open("excess"), {"conflict"})
            await self.watches["0"].close()
            await self.open("replacement")
        elif op == "busy_finish":
            await self.control("hold_list")
            operation = asyncio.create_task(
                self.client.projects.list(filters=self.scope)
            )
            await self.control("beacon", key="list_entered", minimum=1)
            await self.control("send", watch="a", kind="baseline")
            # Reconnecting notification is the actor's observable25ms finish-admission beacon.
            await self.event("a", "reconnecting")
            await self.control("release_list")
            assert await asyncio.wait_for(operation, DEADLINE) == []
        elif op == "commit_flood_close":
            # One awaited typed conflict observes actual native admission. The
            # concurrent batch below does not claim every call fills cap4.
            await rejected(
                self.watches[name].commit({"batch_id": "wrong", "cursor": "epoch:999"}),
                {"conflict"},
            )
            operations = [
                asyncio.create_task(
                    self.watches[name].commit(
                        {"batch_id": "wrong", "cursor": "epoch:999"}
                    )
                )
                for _ in range(32)
            ]
            await self.execute({"op": "ordinary_read"})
            await self.watches[name].close()
            outcomes = await asyncio.wait_for(
                asyncio.gather(*operations, return_exceptions=True), DEADLINE
            )
            assert all(
                isinstance(x, SessionClientError)
                and x.code in ("conflict", "cancelled")
                for x in outcomes
            ), "typed concurrent commit/close outcomes"
            await self.execute({"op": "ordinary_read"})
        elif op == "api_key_refusal":
            api = OpenMates(
                api_key="sk-api-syntheticwatch",
                api_url=self.endpoint,
                device_id="synthetic-watch-device",
            )
            try:
                await rejected(
                    lambda: api.projects.watch_tasks(
                        self.suite["project_id"],
                        source_id=self.suite["source_id"],
                        filters={"personal": True},
                    ),
                    {"project_task_watch_unavailable"},
                )
            finally:
                pass  # API-key facade owns no native session or transport lifetime.
        else:
            raise AssertionError("unrecognized fixed fixture action")

    def _next_subscription(self):
        self._subscriptions = getattr(self, "_subscriptions", 0) + 1
        return self._subscriptions

    async def close(self):
        for watch in self.watches.values():
            await watch.close()
        self.directory.cleanup()


async def run_vector(suite, vector):
    peer = WatchPeer(suite, vector, "pip").start()
    client = None
    scenario = None
    primary_error = None
    try:
        client = SessionClient(
            api_url=peer.endpoint,
            app_url="https://app.example.invalid",
            enhanced_privacy=False,
            allow_private_operations=False,
        )
        scenario = Scenario(suite, vector, peer.endpoint, client)
        await client.import_session(session(suite, peer.endpoint))
        for step in vector["steps"]:
            await asyncio.wait_for(scenario.execute(step), DEADLINE + 2)
        report = peer.status()
        assert report["failure"] is None and report["client_messages"] == 0
        if vector["id"] == "api-key-refusal-before-transport":
            assert report["requests"] == report["upgrades"] == 0
        return {"id": vector["id"], "status": "passed"}
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_failures = []
        for stage, resource in (
            ("scenario", scenario),
            ("client", client),
            ("peer", peer),
        ):
            if resource is None:
                continue
            try:
                if stage == "peer":
                    await asyncio.to_thread(resource.close)
                else:
                    await resource.close()
            except BaseException as error:
                cleanup_failures.append((stage, error))
        if cleanup_failures:
            # A cleanup failure never turns a failed scenario into success or
            # replaces its primary exception. Notes contain fixed stages only.
            failure = (
                primary_error if primary_error is not None else cleanup_failures[0][1]
            )
            for stage, _error in cleanup_failures:
                failure.add_note(f"watch fixture cleanup also failed: {stage}")
            if primary_error is None:
                raise failure


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", choices=[CAPABILITY], required=True)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    suite = json.loads(raw)["capabilities"][CAPABILITY]
    results = []
    for vector in suite["vectors"]:
        results.append(await run_vector(suite, vector))
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
