#!/usr/bin/env python3
"""Actual PyO3 Plans/Workflows against one synthetic protocol peer."""

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
from session_plans_workflows_server import CAPABILITY, PlansWorkflowsPeer  # noqa: E402
from openmates import SessionClient, SessionClientError  # noqa: E402


async def rejected(operation, code="invalid_argument"):
    try:
        await operation
    except SessionClientError as error:
        assert error.code == code
        assert "synthetic-private-server-diagnostic" not in str(error)
    else:
        raise AssertionError("operation must reject")


async def run_vector(suite, vector):
    peer = PlansWorkflowsPeer(suite, vector, "pip").start()
    client = SessionClient(
        api_url=peer.endpoint,
        enhanced_privacy=False,
        allow_private_operations=vector["allow_private"],
    )
    try:
        account = suite["account"]
        await client.import_session(
            {
                "api_url": peer.endpoint,
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
        )
        await client.set_team(suite["team"]["team_id"])
        before = await client.export_session(include_secrets=True)
        mode, filters = vector["mode"], {"personal": True}
        workflow, run_id = suite["workflow_id"], suite["run_id"]
        if mode == "crud":
            family = vector["family"]
            api = client.plans if family == "plans" else client.workflows
            filters = (
                {"team_id": suite["team"]["team_id"]}
                if vector["team"]
                else {"personal": True}
            )
            input = suite["input"]["plan" if family == "plans" else "workflow"]
            created = await api.create(input, filters=filters)
            name = "plan_id" if family == "plans" else "id"
            object_id = created[name]
            assert created["title"] == input["title"]
            if family == "plans":
                assert (
                    created["goal"] == input["goal"]
                    and created["user_flows"] == input["user_flows"]
                )
            else:
                assert created["slug"] == input["slug"]
                assert "encrypted_slug" not in created
            listed = await api.list(filters=filters)
            assert len(listed) == 1 and listed[0][name] == object_id
            assert (await api.show(object_id, filters=filters))["title"] == created[
                "title"
            ]
            patch = (
                {
                    "goal": "Synthetic revised private goal",
                    "planner_focus_id": None,
                    "status": "active",
                }
                if family == "plans"
                else {"title": "Synthetic revised Workflow", "enabled": False}
            )
            updated = await api.update(object_id, patch, filters=filters)
            if family == "plans":
                assert (
                    updated["goal"] == patch["goal"]
                    and updated["planner_focus_id"] is None
                )
            else:
                assert (
                    updated["title"] == patch["title"] and updated["enabled"] is False
                )
            assert (await api.delete(object_id, confirmed=True, filters=filters))[
                "deleted"
            ] is True
            assert await api.list(filters=filters) == []
        elif mode == "strict":
            await rejected(
                client.plans.create(
                    {"title": "synthetic", "goal": "private", "model": "forbidden"},
                    filters=filters,
                )
            )
            await rejected(
                client.plans.create(
                    {"title": "synthetic", "goal": "private", "linked_project_ids": []},
                    filters=filters,
                )
            )
            await rejected(
                client.workflows.run(
                    workflow,
                    {"idempotency_key": "intent", "provider": "forbidden"},
                    filters=filters,
                )
            )
            await rejected(
                client.workflows.wait(
                    workflow, run_id, {"timeout_ms": 0}, filters=filters
                )
            )
            bad = {
                "title": "invalid",
                "graph": {
                    "nodes": [{"id": "start", "type": "manual_trigger"}],
                    "edges": [{"from": "start", "to": "absent"}],
                },
            }
            await rejected(client.workflows.create(bad, filters=filters))
        elif mode == "scope":
            team = {"team_id": suite["team"]["team_id"]}
            await rejected(
                client.plans.create(suite["input"]["plan"], filters=team),
                "unavailable",
            )
            await rejected(
                client.workflows.run(workflow, suite["input"]["run"], filters=team),
                "unavailable",
            )
            await rejected(client.plans.list(filters={}))
            await rejected(client.workflows.list(filters={"personal": True, **team}))
        elif mode == "consent":
            await rejected(
                client.workflows.create(suite["input"]["workflow"], filters=filters),
                "forbidden",
            )
            await rejected(
                client.workflows.run(workflow, suite["input"]["run"], filters=filters),
                "forbidden",
            )
        elif mode == "confirmation":
            for api in (client.plans, client.workflows):
                await rejected(api.delete(workflow, confirmed=False, filters=filters))
        else:
            if mode == "http_error":
                await rejected(
                    client.workflows.run(
                        workflow, suite["input"]["run"], filters=filters
                    ),
                    "forbidden",
                )
            else:
                accepted = await client.workflows.run(
                    workflow, suite["input"]["run"], filters=filters
                )
                assert accepted["id"] == run_id and accepted["status"] == "queued"
                options = {
                    "timeout_ms": 5000,
                    "poll_interval_ms": 10,
                    "sync_interval_ms": 10,
                }
                if mode == "timeout":
                    options.update(timeout_ms=30, poll_interval_ms=1000)
                if mode in ("cancel", "local_cancel"):
                    options["poll_interval_ms"] = 10000
                    waiting = asyncio.ensure_future(
                        client.workflows.wait(
                            workflow, run_id, options, filters=filters
                        )
                    )
                    for _ in range(500):
                        if peer.polls:
                            break
                        await asyncio.sleep(0.01)
                    assert peer.polls == 1
                    await asyncio.sleep(0.05)
                    if mode == "local_cancel":
                        client.cancel()
                        await rejected(waiting, "cancelled")
                        assert peer.cancel_posts == 0
                    else:
                        requests = peer.requests
                        await rejected(
                            client.workflows.cancel_run(
                                workflow,
                                run_id,
                                filters={"team_id": suite["team"]["team_id"]},
                            ),
                            "unavailable",
                        )
                        assert not waiting.done()
                        assert peer.requests == requests and peer.cancel_posts == 0
                        unrelated = asyncio.ensure_future(
                            client.plans.list(filters=filters)
                        )
                        await asyncio.sleep(0.02)
                        cancelling = asyncio.ensure_future(
                            client.workflows.cancel_run(
                                workflow, run_id, filters=filters
                            )
                        )
                        await rejected(waiting, "cancelled")
                        assert await unrelated == []
                        assert (await cancelling)["status"] == "cancellation_requested"
                        assert (
                            await client.workflows.run_detail(
                                workflow, run_id, filters=filters
                            )
                        )["status"] == "cancelled"
                elif mode == "run":
                    completed = await client.workflows.wait(
                        workflow, run_id, options, filters=filters
                    )
                    assert completed["status"] == "completed"
                    assert (
                        completed["output_summary"]["deliveries"]["end"]["status"]
                        == "acknowledged"
                    )
                else:
                    await rejected(
                        client.workflows.wait(
                            workflow, run_id, options, filters=filters
                        ),
                        "forbidden" if mode == "bad_identity" else "invalid_argument",
                    )
        report = peer.status()
        assert report["failure"] is None
        if mode in ("strict", "scope", "consent", "confirmation"):
            assert report["requests"] == report["writes"] == report["run_posts"] == 0
        else:
            after = await client.export_session(include_secrets=True)
            assert after["revision"] > before["revision"]
            assert after["session"]["cookies"]["auth_refresh_token"] == report["cookie"]
            assert "cookie-only-identity-and-rotation" in report["checks"]
            if mode == "crud":
                assert report["writes"] == 3 and report["run_posts"] == 0
                checks = (
                    (
                        "encrypted-plan-private-fields",
                        "plan-master-project-wrappers",
                        "typed-flow-roundtrip",
                    )
                    if vector["family"] == "plans"
                    else (
                        "canonical-server-visible-definition",
                        "encrypted-workflow-slug",
                        "opaque-variable-names-preserved",
                    )
                )
                assert set(checks) <= set(report["checks"])
            else:
                assert report["run_posts"] == 1 and report["cancel_posts"] == int(
                    mode == "cancel"
                )
                assert {"stable-run-idempotency", "no-invented-routing"} <= set(
                    report["checks"]
                )
                if mode in ("failed", "bad_identity"):
                    assert report["polls"] == 1
                if mode == "run":
                    assert report["polls"] == 2
                if mode == "http_error":
                    assert report["polls"] == 0
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
