#!/usr/bin/env python3
"""Real dev-server Workflow readiness REST contract.

Access: existing first-party/developer API-key Workflow surface; auth required.
Writes use the route's existing 20/minute limit; readiness checks add no credit.
Workflow graphs are Automation Vault content, so this probe never prints them.
It uses a test API key or paired CLI session and deletes its created Workflow.
Spec: feature.workflows@2.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests


API_URL = os.getenv("OPENMATES_API_URL", "https://api.dev.openmates.org").rstrip("/")
API_KEY = os.getenv("OPENMATES_REAL_DEV_API_KEY") or os.getenv("OPENMATES_API_KEY")
CLI_SESSION_PATH = Path(os.getenv("OPENMATES_CLI_SESSION_PATH", "~/.openmates/session.json")).expanduser()
REQUEST_TIMEOUT_SECONDS = 60
INVALID_ENABLE_STATUSES = {400, 409, 422}
ACCEPTED_RUN_STATUSES = {"accepted", "queued"}


def _response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Workflow readiness probe returned non-JSON HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Workflow readiness probe returned invalid HTTP {response.status_code} payload")
    return payload


def _require_ok(response: requests.Response, operation: str) -> dict[str, Any]:
    payload = _response_json(response)
    if not response.ok:
        raise RuntimeError(f"{operation} failed with HTTP {response.status_code}")
    return payload


def _authenticated_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    if API_KEY:
        session.headers["Authorization"] = f"Bearer {API_KEY}"
        return session
    if not CLI_SESSION_PATH.is_file():
        raise RuntimeError("Set a test API key or create the normal paired CLI test-account session")
    payload = json.loads(CLI_SESSION_PATH.read_text(encoding="utf-8"))
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    refresh_token = cookies.get("auth_refresh_token") if isinstance(cookies, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("The paired CLI test-account session has no refresh token")
    session.cookies.set("auth_refresh_token", refresh_token)
    session.headers.update({
        "User-Agent": "OpenMates CLI/0.1 (workflow-readiness-rest-proof)",
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": "cli:workflow-readiness-rest-proof",
    })
    return session


def _blank_graph() -> dict[str, Any]:
    return {"version": 1, "trigger_node_id": None, "nodes": [], "edges": []}


def _schedule_graph(effect: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}}},
            effect,
        ],
        "edges": [{"from": "trigger", "to": effect["id"]}],
    }


def _runs(session: requests.Session, workflow_id: str) -> list[dict[str, Any]]:
    runs = _require_ok(session.get(f"{API_URL}/v1/workflows/{workflow_id}/runs", timeout=REQUEST_TIMEOUT_SECONDS), "list runs").get("runs")
    if not isinstance(runs, list) or not all(isinstance(item, dict) for item in runs):
        raise RuntimeError("Workflow run list returned invalid payload")
    return runs


def _require_invalid_enable(session: requests.Session, workflow_id: str, stage: str) -> None:
    response = session.post(f"{API_URL}/v1/workflows/{workflow_id}/enable", timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code not in INVALID_ENABLE_STATUSES:
        raise RuntimeError(f"{stage} enable returned HTTP {response.status_code}, expected validation failure")
    _response_json(response)
    if _runs(session, workflow_id):
        raise RuntimeError(f"{stage} validation failure created a Workflow run")


def _check_task_projections(session: requests.Session, workflow_id: str) -> str:
    response = session.get(f"{API_URL}/v1/user-tasks", timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code in {401, 403}:
        return "skipped_surface_auth"
    payload = _require_ok(response, "list task projections")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(item, dict) for item in tasks):
        raise RuntimeError("User task projection list returned invalid payload")
    projections = [item for item in tasks if item.get("workflow_id") == workflow_id]
    if not projections:
        raise RuntimeError("Enabled Workflow did not expose a task projection")
    if not all(item.get("read_only") is True for item in projections):
        raise RuntimeError("Workflow task projection was not read-only")
    return "asserted"


# contract-test: direct surface=rest_api assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible,tasks.workflow-projections.read-only
def test_workflow_readiness_real_dev() -> None:
    unauthorized = requests.get(f"{API_URL}/v1/workflows", timeout=REQUEST_TIMEOUT_SECONDS)
    if unauthorized.status_code != 401:
        raise RuntimeError(f"Unauthenticated Workflow list returned HTTP {unauthorized.status_code}, expected 401")

    session = _authenticated_session()
    workflow_id = ""
    task_projection_result = "not_checked"
    try:
        created = _require_ok(
            session.post(
                f"{API_URL}/v1/workflows",
                json={"title": "Workflow readiness REST proof", "enabled": False, "graph": _blank_graph()},
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            "create blank workflow",
        ).get("workflow")
        if not isinstance(created, dict) or not isinstance(created.get("id"), str):
            raise RuntimeError("Workflow create did not return an id")
        workflow_id = created["id"]
        if created.get("enabled") is not False or created.get("graph", {}).get("nodes") != []:
            raise RuntimeError("Blank Workflow was not persisted disabled with zero nodes")

        _require_invalid_enable(session, workflow_id, "blank Workflow")
        _require_ok(
            session.patch(
                f"{API_URL}/v1/workflows/{workflow_id}",
                json={"graph": _schedule_graph({"id": "end", "type": "end", "config": {}})},
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            "patch non-effect workflow",
        )
        _require_invalid_enable(session, workflow_id, "non-effect Workflow")
        _require_ok(
            session.patch(
                f"{API_URL}/v1/workflows/{workflow_id}",
                json={"graph": _schedule_graph({"id": "notify", "type": "send_notification", "config": {"title": "Readiness", "body": "Ready"}})},
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            "patch ready workflow",
        )
        enabled = _require_ok(session.post(f"{API_URL}/v1/workflows/{workflow_id}/enable", timeout=REQUEST_TIMEOUT_SECONDS), "enable ready workflow").get("workflow")
        if not isinstance(enabled, dict) or enabled.get("enabled") is not True:
            raise RuntimeError("Ready Workflow did not enable")

        idempotency_key = f"workflow-readiness-{uuid4()}"
        first_run = _require_ok(
            session.post(
                f"{API_URL}/v1/workflows/{workflow_id}/run",
                json={"mode": "manual"},
                headers={"Idempotency-Key": idempotency_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            "start manual run",
        ).get("run")
        if not isinstance(first_run, dict) or first_run.get("status") not in ACCEPTED_RUN_STATUSES or not isinstance(first_run.get("id"), str):
            raise RuntimeError("Manual Workflow run was not accepted or queued")
        repeated_run = _require_ok(
            session.post(
                f"{API_URL}/v1/workflows/{workflow_id}/run",
                json={"mode": "manual"},
                headers={"Idempotency-Key": idempotency_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            "repeat manual run",
        ).get("run")
        if not isinstance(repeated_run, dict) or repeated_run.get("id") != first_run["id"]:
            raise RuntimeError("Repeated idempotency key did not return the accepted Workflow run")
        runs = _runs(session, workflow_id)
        if len(runs) != 1 or runs[0].get("id") != first_run["id"]:
            raise RuntimeError("Workflow run list did not contain exactly one accepted run")
        task_projection_result = _check_task_projections(session, workflow_id)
        print(json.dumps({"status": "passed", "task_projections": task_projection_result, "workflow_runs": len(runs)}, sort_keys=True))
    finally:
        if workflow_id:
            _require_ok(session.delete(f"{API_URL}/v1/workflows/{workflow_id}", timeout=REQUEST_TIMEOUT_SECONDS), "delete workflow")


def main() -> int:
    test_workflow_readiness_real_dev()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
