#!/usr/bin/env python3
"""Actual PyO3 SessionClient against the shared encrypted Project links peer."""

# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
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
from session_project_items_server import CAPABILITY, ProjectItemsPeer  # noqa: E402
from openmates import SessionClient, SessionClientError  # noqa: E402


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
    peer = ProjectItemsPeer(suite, vector, "pip").start()
    client = SessionClient(
        api_url=peer.endpoint,
        app_url=peer.endpoint,
        enhanced_privacy=False,
        allow_private_operations=False,
    )
    try:
        await client.import_session(session(suite, peer.endpoint))
        # Explicit Personal must override the ambient Team without inheriting it.
        await client.set_team(suite["team"]["team_id"])
        before = await client.export_session(include_secrets=True)
        mode = vector["mode"]
        filters = (
            {"team_id": suite["team"]["team_id"]}
            if vector.get("team")
            else {"personal": True}
        )
        object_id = suite["project_id"]
        unlink = {
            "item_type": vector.get("item_type", "chat"),
            "target_id": suite["target_id"],
            "confirmed": True,
        }
        if mode == "projection":
            assert (
                await client.projects.items(object_id, filters=filters)
                == suite["expected"]
            )
        elif mode in ("unlink", "noop"):
            result = await client.projects.unlink_item(
                object_id, unlink, filters=filters
            )
            assert result == {
                "project_id": object_id,
                "target_id": suite["target_id"],
                "deleted": mode != "noop",
                "deleted_count": 0 if mode == "noop" else 1,
            }
        elif mode == "confirmation":
            for bad in (False, "true", 1, None):
                await rejected(
                    client.projects.unlink_item(
                        object_id, {**unlink, "confirmed": bad}, filters=filters
                    )
                )
            for patch in (
                {"item_type": "upload"},
                {"unexpected": True},
                {"target_id": ""},
            ):
                await rejected(
                    client.projects.unlink_item(
                        object_id, {**unlink, **patch}, filters=filters
                    )
                )
        elif mode == "scope":
            await rejected(client.projects.items(object_id, filters={}))
            await rejected(
                client.projects.unlink_item(
                    object_id,
                    unlink,
                    filters={"personal": True, "team_id": suite["team"]["team_id"]},
                )
            )
            await rejected(
                client.projects.items(
                    object_id, filters={"personal": True, "unexpected": True}
                )
            )
        elif mode == "tamper":
            await rejected(
                client.projects.items(object_id, filters=filters), "forbidden"
            )
        elif mode in ("permission", "receipt"):
            await rejected(
                client.projects.unlink_item(object_id, unlink, filters=filters),
                "forbidden" if mode == "permission" else "protocol",
            )
        elif mode == "cancel":
            first = asyncio.ensure_future(
                client.projects.items(object_id, filters=filters)
            )
            for _ in range(500):
                if peer.blocked:
                    break
                await asyncio.sleep(0.01)
            assert peer.blocked
            queued = asyncio.ensure_future(
                client.projects.unlink_item(object_id, unlink, filters=filters)
            )
            await asyncio.sleep(0.03)
            client.cancel()
            peer.released.set()
            await rejected(first, "cancelled")
            await rejected(queued, "cancelled")
            assert (
                await client.projects.items(object_id, filters=filters)
                == suite["expected"]
            )
        else:
            raise AssertionError("unknown fixture mode")
        report = peer.status()
        assert report["failure"] is None
        assert report["targets"] == [
            item["target_id"] for item in suite["expected"]["items"]
        ]
        assert report["writes"] == (1 if mode in ("unlink", "noop", "receipt") else 0)
        assert report["deleted_links"] == (1 if mode == "unlink" else 0)
        if mode in ("confirmation", "scope"):
            assert report["requests"] == 0
        else:
            after = await client.export_session(include_secrets=True)
            assert after["revision"] > before["revision"]
            assert after["session"]["cookies"]["auth_refresh_token"] == report["cookie"]
            expected_requests = (2 if vector.get("team") else 1) + (
                1 if mode in ("unlink", "noop", "receipt", "cancel") else 0
            )
            assert report["requests"] == expected_requests, (
                "no retry or underlying-object deletion"
            )
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
