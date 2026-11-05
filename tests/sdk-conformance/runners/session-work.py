#!/usr/bin/env python3
"""Actual PyO3 SessionClient against the shared cookie CRUD peer."""

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
from session_work_server import CAPABILITY, WorkPeer  # noqa: E402
from openmates import SessionClient, SessionClientError  # noqa: E402
from session_saved_stream import saved_stream_vector  # noqa: E402


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


async def rejected(operation, code="invalid_argument"):
    try:
        await operation
    except SessionClientError as error:
        assert error.code == code
        assert "synthetic-private-server-diagnostic" not in str(error)
    else:
        raise AssertionError("operation should reject")


async def run_vector(suite, vector):
    if vector["mode"].startswith("saved_"):
        return await saved_stream_vector(suite, vector)
    peer = WorkPeer(suite, vector, "pip").start()
    client = SessionClient(
        api_url=peer.endpoint, enhanced_privacy=False, allow_private_operations=False
    )
    try:
        await client.import_session(session(suite, peer.endpoint))
        # Explicit Personal must override the ambient Team without inheriting it.
        await client.set_team(suite["team"]["team_id"])
        before = await client.export_session(include_secrets=True)
        mode = vector["mode"]
        if mode == "crud":
            family = vector["family"]
            api = client.tasks if family == "tasks" else client.projects
            filters = (
                {"team_id": suite["team"]["team_id"]}
                if vector["team"]
                else {"personal": True}
            )
            result = await api.create(suite["input"][family], filters=filters)
            key = "task_id" if family == "tasks" else "project_id"
            name = "title" if family == "tasks" else "name"
            assert result[name] == suite["input"][family][name]
            object_id = result[key]
            rows = await api.list(filters=filters)
            assert len(rows) == 1 and rows[0][key] == object_id
            assert (await api.show(object_id, filters=filters))[name] == result[name]
            patch = {name: "Synthetic updated private text"}
            patch.update(
                {"due_at": None, "status": "in_progress"}
                if family == "tasks"
                else {"archived": True}
            )
            updated = await api.update(object_id, patch, filters=filters)
            assert updated[name] == patch[name]
            if family == "tasks":
                assert updated["due_at"] is None and updated["status"] == "in_progress"
            else:
                assert updated["archived"] is True
            assert (await api.delete(object_id, confirmed=True, filters=filters))[
                "deleted"
            ] is True
            assert await api.list(filters=filters) == []
        elif mode == "unknown":
            await rejected(
                client.tasks.create(
                    {"title": "synthetic", "model": "forbidden"},
                    filters={"personal": True},
                )
            )
            await rejected(
                client.projects.create(
                    {"name": "synthetic", "provider": "forbidden"},
                    filters={"personal": True},
                )
            )
        elif mode == "confirmation":
            for api in (client.tasks, client.projects):
                await rejected(
                    api.delete(
                        "11111111-1111-4111-8111-111111111111",
                        confirmed=False,
                        filters={"personal": True},
                    )
                )
        elif mode == "scope":
            await rejected(client.tasks.list(filters={}))
            await rejected(
                client.projects.list(
                    filters={"personal": True, "team_id": suite["team"]["team_id"]}
                )
            )
        elif mode == "policy":
            await rejected(
                client.tasks.create(
                    {"title": "Synthetic private AI Task", "assign": "openmates"},
                    filters={"personal": True},
                ),
                "forbidden",
            )
            await rejected(
                client.projects.create(
                    {"name": "Synthetic no write policy"}, filters={"personal": True}
                )
            )
        elif mode == "close":
            await client.close()
            await rejected(client.tasks.list(filters={"personal": True}), "cancelled")
            await rejected(
                client.projects.list(filters={"personal": True}), "cancelled"
            )
        elif mode == "cancel":
            assert vector["expected_first_error"] == "cancelled", (
                "canonical in-flight cancellation oracle"
            )
            first = asyncio.create_task(
                rejected(
                    client.tasks.list(filters={"personal": True}),
                    vector["expected_first_error"],
                )
            )
            # Observe early check failures without suppressing the later await.
            first.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            for _ in range(500):
                if peer.blocked:
                    break
                await asyncio.sleep(0.01)
            assert peer.blocked
            queued = asyncio.create_task(
                rejected(client.projects.list(filters={"personal": True}), "cancelled")
            )
            queued.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            await asyncio.sleep(0.03)
            client.cancel()
            peer.released.set()
            await first
            await queued
            assert await client.projects.list(filters={"personal": True}) == []
        else:
            raise AssertionError("unknown fixture mode")
        report = peer.status()
        assert report["failure"] is None
        if mode in ("crud", "cancel"):
            after = await client.export_session(include_secrets=True)
            assert after["revision"] > before["revision"]
            assert after["session"]["cookies"]["auth_refresh_token"] == report["cookie"]
        if mode == "crud":
            assert report["writes"] == 3
            for check in (
                "encrypted-private-fields",
                "scope-bound-wrapper",
                "fresh-object-key",
                "versioned-encrypted-update",
                "canonical-confirmed-delete",
                "cookie-only-identity-and-rotation",
            ):
                assert check in report["checks"]
        elif mode == "cancel":
            assert report["requests"] == 2 and report["writes"] == 0
        else:
            assert report["requests"] == 0 and report["writes"] == 0
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
    results = [await run_vector(suite, vector) for vector in suite["vectors"]]
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
