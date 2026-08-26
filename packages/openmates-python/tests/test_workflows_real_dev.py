"""Real dev-server pip SDK Workflow readiness test.

Purpose: prove the public Python SDK can create a blank draft, reject premature
activation, enable a ready graph, run it, inspect it, and delete it on dev.
Run: OPENMATES_API_URL=https://api.dev.openmates.org python3 -m pytest packages/openmates-python/tests/test_workflows_real_dev.py
"""

from __future__ import annotations

import os
import time

import pytest

from openmates import OpenMates, OpenMatesApiError


API_URL = os.getenv("OPENMATES_API_URL", "https://api.dev.openmates.org")
API_KEY = os.getenv("OPENMATES_REAL_DEV_API_KEY") or os.getenv("OPENMATES_API_KEY")


@pytest.mark.skipif(not API_KEY, reason="Set OPENMATES_REAL_DEV_API_KEY or OPENMATES_API_KEY to run real dev SDK workflow tests")
# contract-test: direct surface=sdks.pip assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible,workflows-ui.identity.automatic-category-icon,workflows.surface.semantic-parity,sdk.surface.semantic-parity
def test_pip_sdk_real_dev_workflow_execution():
    client = OpenMates(api_key=API_KEY, api_url=API_URL)
    workflow_id = ""
    try:
        created = client.workflows.create(
            title=f"pip SDK readiness workflow {int(time.time())}",
            graph=blank_graph(),
            enabled=False,
        )
        workflow_id = created["id"]
        assert workflow_id
        assert created["graph"]["trigger_node_id"] is None
        assert created["graph"]["nodes"] == []
        assert isinstance(created.get("category"), str)
        assert isinstance(created.get("icon"), str)

        with pytest.raises(OpenMatesApiError) as exc_info:
            client.workflows.enable(workflow_id)
        assert exc_info.value.status_code in {400, 409, 422}
        client.workflows.update(workflow_id, graph=ready_graph())

        listed = next(item for item in client.workflows.list() if item["id"] == workflow_id)
        fetched = client.workflows.get(workflow_id)
        assert listed["category"] == created["category"]
        assert listed["icon"] == created["icon"]
        assert fetched["category"] == created["category"]
        assert fetched["icon"] == created["icon"]

        enabled = client.workflows.enable(workflow_id)
        assert enabled["enabled"] is True

        run = client.workflows.run(workflow_id, idempotency_key=f"pip-sdk-{int(time.time())}", mode="test")
        detail = wait_for_run(client, workflow_id, run["id"])
        assert any(item.get("node_id") == "notify" and item.get("status") == "completed" for item in detail.get("node_runs", []))
    finally:
        if workflow_id:
            try:
                client.workflows.disable(workflow_id)
            except Exception:
                pass
            try:
                client.workflows.delete(workflow_id, confirmed=True)
            except Exception:
                pass


def blank_graph() -> dict:
    return {"version": 1, "trigger_node_id": None, "nodes": [], "edges": []}


def ready_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}}},
            {"id": "notify", "type": "send_notification", "config": {"title": "SDK readiness", "body": "Ready"}},
        ],
        "edges": [{"from": "trigger", "to": "notify"}],
    }


def wait_for_run(client: OpenMates, workflow_id: str, run_id: str) -> dict:
    deadline = time.time() + 120
    last_run = {}
    while time.time() < deadline:
        last_run = client.workflows.run_detail(workflow_id, run_id)
        if last_run.get("status") in {"completed", "failed", "cancelled"}:
            return last_run
        time.sleep(3)
    raise AssertionError(f"Workflow run did not finish: {last_run}")
