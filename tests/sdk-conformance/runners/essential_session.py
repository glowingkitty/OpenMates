"""PRIVATE UNRUN actual PyO3/SessionClient shared-vector driver, no product calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
from selected_recovery import selected_recovery
from startup_sync import startup_sync
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
from openmates import SessionClient, SessionClientError  # noqa: E402 - explicit test-source path above


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


async def request(endpoint, route):
    def read():
        with urlopen(endpoint + route, timeout=2) as response:
            return json.load(response)

    return await asyncio.wait_for(asyncio.to_thread(read), 3)


async def wait(endpoint, condition):
    for _ in range(100):
        result = await request(endpoint, "/__test/status")
        if condition(result):
            return result
        await asyncio.sleep(0.01)
    raise AssertionError("bounded peer condition")


def session(suite, endpoint):
    return {
        "api_url": endpoint,
        "session_id": suite["account"]["session_id"],
        "cookies": {"auth_refresh_token": suite["account"]["cookie"]},
        "ws_token": None,
        "master_key": suite["account"]["master_key"],
        "hashed_email": "synthetic-email-hash",
        "user_email_salt": "synthetic-salt",
        "email_encryption_key": None,
        "created_at": 1,
        "paired_session_expires_at": None,
        "active_team_id": None,
    }


async def client(suite, endpoint):
    value = SessionClient(
        api_url=endpoint,
        app_url=suite["protocol"]["app_origin"],
        enhanced_privacy=False,
        allow_private_operations=True,
    )
    await value.import_session(session(suite, endpoint))
    return value


def durable(path, raw):
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


class Store:
    def __init__(self, directory):
        self.directory = directory
        self.pointer = directory / "current"

    async def generation(self, scope):
        return (
            json.loads(self.pointer.read_bytes())["version"]
            if self.pointer.exists()
            else None
        )

    async def compare_and_swap(self, value):
        # Synchronous filesystem critical section: two actual SDK clients share
        # this fixture CAS; no await splits version check and durable pointer.
        current = (
            json.loads(self.pointer.read_bytes())["version"]
            if self.pointer.exists()
            else None
        )
        if current != value["expected_version"]:
            return {"stored": False}
        target = self.directory / value["next_version"]
        target.mkdir(mode=0o700)
        durable(target / "checkpoint", value["checkpoint_json"].encode("utf8"))
        durable(target / "credentials", value["credentials_json"].encode("utf8"))
        fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        next_file = self.directory / "next"
        durable(
            next_file,
            json.dumps(
                {"version": value["next_version"], "scope": value["scope"]}
            ).encode(),
        )
        next_file.replace(self.pointer)
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return {
            "stored": True,
            "ciphertext_sha256": digest((target / "checkpoint").read_bytes()),
            "credential_revision": value["credential_revision"],
        }


async def refused(operation, codes):
    try:
        await operation
    except SessionClientError as error:
        assert error.code in codes
        return
    raise AssertionError("expected typed SDK refusal")


async def run_vector(capability, suite, vector, fixture):
    peer = await asyncio.create_subprocess_exec(
        os.environ.get("OPENMATES_SDK_CONFORMANCE_PYTHON", "python3"),
        str(
            ROOT
            / (
                "tests/sdk-conformance/startup_sync_server.py"
                if capability == "session.initial-startup-sync.v1"
                else "tests/sdk-conformance/essential_session_server.py"
            )
        ),
        "--fixture",
        str(fixture),
        "--capability",
        capability,
        "--vector",
        vector["id"],
        "--identity",
        "pip",
        stdout=asyncio.subprocess.PIPE,
        stderr=None,  # inherited: the driver projects only class and tracked frames
    )
    first = second = monitor = None
    try:
        ready = json.loads(await asyncio.wait_for(peer.stdout.readline(), 5))
        endpoint = ready["endpoint"]
        assert endpoint.startswith("http://127.0.0.1:")
        first = await client(suite, endpoint)
        with tempfile.TemporaryDirectory(
            prefix="openmates-essential-conformance-"
        ) as temporary:
            directory = Path(temporary)
            mode = vector["mode"]
            if mode.startswith("startup_"):
                await startup_sync(
                    first,
                    lambda: client(suite, endpoint),
                    lambda: first.import_session(session(suite, endpoint)),
                    vector,
                    endpoint,
                    request=request,
                    wait=wait,
                    refused=refused,
                )
            elif mode.startswith("selected_"):
                await selected_recovery(
                    first,
                    suite,
                    vector,
                    endpoint,
                    directory,
                    request=request,
                    wait=wait,
                    refused=refused,
                    durable=durable,
                    digest=digest,
                )
            elif mode.startswith("monitor"):
                monitor = await first.watch_chats()
                if mode == "monitor_read_cancel":
                    await anext(monitor)
                    await monitor.refresh_and_publish(
                        Store(directory), include_secrets=True
                    )
                    pending = asyncio.create_task(anext(monitor))
                    await asyncio.sleep(0.02)
                    await monitor.close()
                    await refused(pending, {"cancelled"})
                    monitor = await first.watch_chats()
                    await request(endpoint, "/__test/control?action=burst")
                await anext(monitor)
                if mode == "monitor_phase1b_context":
                    await refused(
                        monitor.stage_refresh(include_secrets=True), {"forbidden"}
                    )
                    assert not (directory / "checkpoint").exists()
                elif mode == "monitor_denial":
                    await request(endpoint, "/__test/control?action=deny")
                    await refused(
                        monitor.stage_refresh(
                            include_secrets=True,
                            selected_chat_id=suite["protocol"]["initial_chat_id"],
                        ),
                        {"forbidden"},
                    )
                    denial = monitor.access_denial()
                    assert (
                        denial["reason"] == "chat_unavailable"
                        and denial["chat_id"] == suite["protocol"]["initial_chat_id"]
                    )
                    assert not (directory / "checkpoint").exists()
                elif mode == "monitor_store_failure":

                    class FailedStore:
                        async def generation(self, scope):
                            return None

                        async def compare_and_swap(self, value):
                            raise OSError("synthetic-store-write-failed")

                    try:
                        await monitor.refresh_and_publish(
                            FailedStore(), include_secrets=True
                        )
                    except OSError as error:
                        assert str(error) == "synthetic-store-write-failed"
                    else:
                        raise AssertionError("store failure must not publish")
                    await anext(monitor)
                    result = await monitor.refresh_and_publish(
                        Store(directory), include_secrets=True
                    )
                    assert isinstance(result["items"], list)
                elif mode == "monitor_revoke":
                    await request(endpoint, "/__test/control?action=burst")
                    await request(endpoint, "/__test/control?action=revoke")
                    await wait(
                        endpoint, lambda status: status["monitor_disconnects"] >= 1
                    )
                    await refused(
                        monitor.stage_refresh(include_secrets=True),
                        {"cancelled", "forbidden"},
                    )
                elif mode == "monitor_data_changed":
                    stage = await monitor.stage_refresh(include_secrets=True)
                    durable(
                        directory / "checkpoint",
                        stage["checkpoint_json"].encode("utf8"),
                    )
                    durable(
                        directory / "credentials",
                        stage["credentials_json"].encode("utf8"),
                    )
                    await request(endpoint, "/__test/control?action=advance")
                    await first.list("chats")
                    await refused(
                        monitor.commit_refresh(
                            stage["id"],
                            {
                                "ciphertext_sha256": digest(
                                    (directory / "checkpoint").read_bytes()
                                ),
                                "credential_revision": stage["credential_revision"],
                            },
                        ),
                        {"cancelled"},
                    )
                elif mode == "monitor_cas":
                    storage = Store(directory)
                    started = asyncio.Event()
                    proceed = asyncio.Event()

                    class DelayedStore:
                        async def generation(self, scope):
                            return await storage.generation(scope)

                        async def compare_and_swap(self, value):
                            started.set()
                            await proceed.wait()
                            return await storage.compare_and_swap(value)

                    pending = asyncio.create_task(
                        monitor.refresh_and_publish(
                            DelayedStore(), include_secrets=True
                        )
                    )
                    await asyncio.wait_for(started.wait(), 2)
                    await request(endpoint, "/__test/control?action=advance")
                    await first.list("chats")
                    second = await client(suite, endpoint)
                    fresh = await second.watch_chats()
                    await anext(fresh)
                    result = await fresh.refresh_and_publish(
                        storage, include_secrets=True
                    )
                    assert isinstance(result["items"], list)
                    before = storage.pointer.read_bytes()
                    proceed.set()
                    await refused(pending, {"conflict"})
                    assert storage.pointer.read_bytes() == before
                    await fresh.close()
                else:
                    stage = await monitor.stage_refresh(include_secrets=True)
                    if mode.startswith("monitor_phase1b"):
                        snapshot = json.loads(stage["checkpoint_json"])
                        chat_id = suite["protocol"]["initial_chat_id"]
                        window = snapshot["sync_message_windows"][chat_id]
                        assert len(window["messages"]) == 2
                        assert window["server_message_count"] == 5
                        assert window["has_more_before"] is True
                        assert chat_id not in snapshot["history"]
                        assert "history_complete" not in window
                        for message in window["messages"]:
                            assert message["chat_id"] == chat_id
                            assert isinstance(message["encrypted_content"], str)
                            assert "content" not in message
                        if mode in (
                            "monitor_phase1b_metadata_coverage",
                            "monitor_phase1b_metadata_responses",
                        ):
                            parents = [chat_id] + [
                                f"30000000-0000-4000-8000-{index:012}"
                                for index in range(1, 25)
                            ]
                            child = "60000000-0000-4000-8000-000000000000"
                            expected = parents + [child]
                            if mode == "monitor_phase1b_metadata_responses":
                                expected += [
                                    "70000000-0000-4000-8000-000000000001",
                                    "70000000-0000-4000-8000-000000000002",
                                ]
                                assert (
                                    "80000000-0000-4000-8000-000000000001"
                                    not in snapshot["chats"]
                                )
                                assert "older_metadata_pages" not in snapshot
                                assert (
                                    snapshot["chats"][expected[-1]]["parent_id"]
                                    == expected[-2]
                                )
                                assert (
                                    snapshot["chats"][expected[-1]]["is_sub_chat"]
                                    is True
                                )
                                assert all(
                                    chat not in snapshot["history"]
                                    for chat in expected[-2:]
                                )
                            assert set(snapshot["chats"]) == set(expected)
                            assert snapshot["chat_arrival_order_v1"]["ids"] == expected
                            assert set(snapshot["sync_message_windows"]) == set(
                                parents[:20]
                            )
                            assert snapshot["chats"][child]["parent_id"] == chat_id
                            assert snapshot["chats"][child]["is_sub_chat"] is True
                            assert child not in snapshot["history"]
                            for index, chat in enumerate(expected):
                                row = snapshot["chats"][chat]
                                assert row["id"] == chat
                                assert isinstance(row["encrypted_title"], str)
                                assert row["pinned"] is (
                                    index < 25
                                    and index % 2 == 0
                                    or mode == "monitor_phase1b_metadata_responses"
                                    and index == 26
                                )
                                assert row["opaqueUserMetadata"] == {
                                    "linkedProjectIds": ["雪", "😀"],
                                    "camelCase": {"sourceId": "preserve-verbatim"},
                                }
                    assert (
                        "camelCase" in stage["checkpoint_json"]
                        and "雪" in stage["checkpoint_json"]
                    )
                    durable(
                        directory / "checkpoint",
                        (
                            stage["checkpoint_json"]
                            + (" " if mode == "monitor_byte" else "")
                        ).encode("utf8"),
                    )
                    durable(
                        directory / "credentials",
                        stage["credentials_json"].encode("utf8"),
                    )
                    receipt = {
                        "ciphertext_sha256": digest(
                            (directory / "checkpoint").read_bytes()
                        ),
                        "credential_revision": stage["credential_revision"],
                    }
                    if mode == "monitor_byte":
                        await refused(
                            monitor.commit_refresh(stage["id"], receipt), {"conflict"}
                        )
                    else:
                        assert isinstance(
                            (await monitor.commit_refresh(stage["id"], receipt))[
                                "items"
                            ],
                            list,
                        )
                        assert (
                            receipt["ciphertext_sha256"] == stage["ciphertext_sha256"]
                        )
                await monitor.close()
            else:
                await refused(first.completion_recovery.jobs(), {"unavailable"})
                await first.completion_recovery.enable(True)
                if mode != "disabled":
                    jobs = await first.completion_recovery.jobs()
                    assert len(jobs) == 1
                    if mode == "main_legacy_created_at":
                        staged = await first.completion_recovery.stage(jobs[0]["id"])
                        assert staged["kind"] == "ready"
                        needle = (
                            ',"created_at":'
                            + str(vector["created_at"])
                            + '},"encrypted_candidate"'
                        )
                        assert staged["checkpoint_json"].count(needle) == 1
                        legacy = staged["checkpoint_json"].replace(
                            needle, '},"encrypted_candidate"'
                        )
                        assert "created_at" not in json.loads(legacy)["job"]
                        durable(directory / "legacy-checkpoint", legacy.encode("utf8"))
                        await first.close()
                        await asyncio.sleep(1.2)
                        first = await client(suite, endpoint)
                        await first.completion_recovery.enable(True)
                        authentic = await first.completion_recovery.jobs()
                        assert authentic[0]["job"]["created_at"] == vector["created_at"]
                        resumed = await first.completion_recovery.resume(
                            (directory / "legacy-checkpoint").read_text()
                        )
                        assert (
                            resumed["kind"] == "ready"
                            and resumed["checkpoint_json"] == legacy
                        )
                        receipt = await first.completion_recovery.commit(
                            resumed["id"],
                            {
                                "checkpoint_sha256": digest(
                                    (directory / "legacy-checkpoint").read_bytes()
                                )
                            },
                        )
                        assert receipt["state"] == "TERMINAL"
                    elif mode == "main_cancel":
                        pending = asyncio.create_task(
                            first.completion_recovery.stage(jobs[0]["id"])
                        )
                        await wait(endpoint, lambda status: status["claims"] == 1)
                        first.cancel()
                        await refused(pending, {"cancelled"})
                    else:
                        stage = await first.completion_recovery.stage(jobs[0]["id"])
                        assert stage["kind"] == "ready"
                        if mode == "main_created_at":
                            assert (
                                json.loads(stage["checkpoint_json"])[
                                    "encrypted_candidate"
                                ]["created_at"]
                                == vector["created_at"]
                            )
                        durable(
                            directory / "checkpoint",
                            (
                                stage["checkpoint_json"]
                                + (" " if mode == "main_byte" else "")
                            ).encode("utf8"),
                        )
                        assert (await request(endpoint, "/__test/status"))[
                            "persists"
                        ] == 0
                        if mode == "main_owner":
                            before = (await request(endpoint, "/__test/status"))[
                                "claims"
                            ]
                            forged = stage["checkpoint_json"].replace(
                                suite["account"]["owner_id"],
                                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                            )
                            await refused(
                                first.completion_recovery.resume(forged), {"forbidden"}
                            )
                            assert (await request(endpoint, "/__test/status"))[
                                "claims"
                            ] == before
                        if mode == "main_expiry":
                            await asyncio.sleep(2.3)
                        if mode == "main_reset":
                            await first.import_session(session(suite, endpoint))
                        commit = first.completion_recovery.commit(
                            stage["id"],
                            {
                                "checkpoint_sha256": digest(
                                    (directory / "checkpoint").read_bytes()
                                )
                            },
                        )
                        if mode == "main_owner":
                            commit.close()
                        elif mode in {"main_byte", "main_reset", "main_expiry"}:
                            await refused(commit, {"conflict", "cancelled"})
                        elif mode == "main_cas_exhausted":
                            await refused(commit, {"conflict"})
                        elif mode == "main_lost_ack":
                            await refused(commit, {"offline"})
                            await first.close()
                            first = await client(suite, endpoint)
                            await first.completion_recovery.enable(True)
                            recovered = await first.completion_recovery.resume(
                                (directory / "checkpoint").read_text()
                            )
                            assert (
                                recovered["kind"] == "canonical"
                                and recovered["receipt"]["assistant_message_id"]
                                == suite["protocol"]["assistant_id"]
                            )
                        else:
                            receipt = await commit
                            assert (
                                receipt["state"] == "TERMINAL"
                                and receipt["assistant_message_id"]
                                == suite["protocol"]["assistant_id"]
                            )
            if second:
                await second.close()
            await first.close()
            status = await request(endpoint, "/__test/status")
            assert status["failure"] is None and status["admissions"] == 0
            if mode == "main_legacy_created_at":
                assert status["claims"] == 2
            if mode.startswith("main_cas_"):
                assert status["persist_attempts"] == 4 and status["claims"] == 1
            assert status["persists"] == (
                1
                if mode
                in {
                    "main",
                    "main_lost_ack",
                    "selected_main",
                    "main_created_at",
                    "main_cas_retry",
                    "main_legacy_created_at",
                }
                else 0
            )
        return {"id": vector["id"], "status": "passed"}
    finally:
        if first:
            first.cancel()
        if second:
            second.cancel()
        try:
            if monitor:
                await asyncio.wait_for(monitor.close(), 2)
            if second:
                await asyncio.wait_for(second.close(), 2)
            if first:
                await asyncio.wait_for(first.close(), 2)
        finally:
            if peer.returncode is None:
                peer.terminate()
                try:
                    await asyncio.wait_for(peer.wait(), 2)
                except asyncio.TimeoutError:
                    peer.kill()
                    await peer.wait()


async def main(capability):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", required=True)
    parser.add_argument("--fixture", required=True, type=Path)
    args = parser.parse_args()
    assert args.capability == capability
    raw = args.fixture.read_bytes()
    suite = json.loads(raw)["capabilities"][capability]
    results = [
        await asyncio.wait_for(run_vector(capability, suite, vector, args.fixture), 15)
        for vector in suite["vectors"]
    ]
    print(
        json.dumps(
            {
                "capability": capability,
                "language": "python",
                "status": "passed",
                "fixtureSha256": digest(raw),
                "results": results,
            }
        )
    )
