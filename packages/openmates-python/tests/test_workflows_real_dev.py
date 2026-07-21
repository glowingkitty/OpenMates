"""Real dev-server pip SDK Workflow test.

Purpose: prove the public Python SDK can create, enable, step-test, run,
inspect, and delete a Workflow against https://api.dev.openmates.org using
API-key auth. Skips unless OPENMATES_REAL_DEV_API_KEY or OPENMATES_API_KEY is set.
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
def test_pip_sdk_real_dev_workflow_execution():
    client = OpenMates(api_key=API_KEY, api_url=API_URL)
    workflow_id = ""
    try:
        capabilities = load_capabilities_or_skip(client)
        assert any(item.get("id") == "math.calculate" and item.get("enabled") is True for item in capabilities)

        source = workflow_yaml(f"pip SDK real workflow {int(time.time())}")
        validation = client.workflows.validate_yaml(source)
        assert validation["draft_valid"] is True
        assert validation["enable_ready"] is True

        created = client.workflows.create_from_yaml(source)
        workflow_id = created["workflow"]["id"]
        assert workflow_id

        step_run = client.workflows.step_test(workflow_id, "math", input_data={"expression": "2 + 2"}, confirmed=True)
        assert step_run["trigger_type"] == "step_test"
        assert step_run["node_runs"][0]["status"] == "completed"

        enabled = client.workflows.enable(workflow_id)
        assert enabled["enabled"] is True

        run = client.workflows.run(workflow_id, idempotency_key=f"pip-sdk-{int(time.time())}", mode="test")
        detail = wait_for_run(client, workflow_id, run["id"])
        assert any(item.get("node_id") == "math" and item.get("status") == "completed" for item in detail.get("node_runs", []))
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


def workflow_yaml(title: str) -> str:
    return f"""
title: {title!r}
start_when:
  manual: {{}}
steps:
  - id: math
    use_app_skill: math.calculate
    input:
      expression: 2 + 2
"""


def load_capabilities_or_skip(client: OpenMates) -> list[dict]:
    try:
        return client.workflows.capabilities()
    except OpenMatesApiError as exc:
        if exc.status_code == 403 and "New device detected" in str(exc.data):
            pytest.skip("API key is valid but this SDK device is awaiting approval in Settings > Developers > Devices")
        raise


def wait_for_run(client: OpenMates, workflow_id: str, run_id: str) -> dict:
    deadline = time.time() + 120
    last_run = {}
    while time.time() < deadline:
        last_run = client.workflows.run_detail(workflow_id, run_id)
        if last_run.get("status") in {"completed", "failed", "cancelled"}:
            return last_run
        time.sleep(3)
    raise AssertionError(f"Workflow run did not finish: {last_run}")
