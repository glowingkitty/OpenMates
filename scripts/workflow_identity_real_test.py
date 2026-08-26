#!/usr/bin/env python3
"""Real dev-server Workflow identity REST contract.

This probe verifies unauthorized rejection and authenticated create, list,
detail, and update behavior against the actual OpenMates API. It uses an
environment-provided test API key, never prints it, and deletes its Workflow.
Spec: docs/specs/workflows-ui-contract/spec.yml.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import requests


API_URL = os.getenv("OPENMATES_API_URL", "https://api.dev.openmates.org").rstrip("/")
API_KEY = os.getenv("OPENMATES_REAL_DEV_API_KEY") or os.getenv("OPENMATES_API_KEY")
CLI_SESSION_PATH = Path(os.getenv("OPENMATES_CLI_SESSION_PATH", "~/.openmates/session.json")).expanduser()
REQUEST_TIMEOUT_SECONDS = 60


def _response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Workflow REST probe returned non-JSON HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Workflow REST probe returned invalid HTTP {response.status_code} payload")
    return payload


def _require_ok(response: requests.Response, operation: str) -> dict[str, Any]:
    payload = _response_json(response)
    if not response.ok:
        raise RuntimeError(f"{operation} failed with HTTP {response.status_code}: {payload}")
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
        "User-Agent": "OpenMates CLI/0.1 (workflow-identity-rest-proof)",
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": "cli:workflow-identity-rest-proof",
    })
    return session


# contract-test: direct surface=rest_api assertions=workflows-ui.identity.automatic-category-icon
def test_workflow_identity_real_dev() -> None:
    unauthorized = requests.get(f"{API_URL}/v1/workflows", timeout=REQUEST_TIMEOUT_SECONDS)
    if unauthorized.status_code != 401:
        raise RuntimeError(f"Unauthenticated Workflow list returned HTTP {unauthorized.status_code}, expected 401")

    session = _authenticated_session()
    workflow_id = ""
    try:
        created_payload = _require_ok(
            session.post(
                f"{API_URL}/v1/workflows",
                json={
                    "title": f"Workflow identity REST proof {int(time.time())}",
                    "category": "software_development",
                    "icon": "code",
                    "enabled": False,
                    "graph": {
                        "version": 1,
                        "trigger_node_id": "manual",
                        "nodes": [{"id": "manual", "type": "manual_trigger", "config": {}}],
                        "edges": [],
                    },
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            "create",
        )
        created = created_payload["workflow"]
        workflow_id = str(created["id"])
        assert created["category"] == "software_development"
        assert created["icon"] == "code"
        assert created["enabled"] is False

        listed = _require_ok(session.get(f"{API_URL}/v1/workflows", timeout=REQUEST_TIMEOUT_SECONDS), "list")["workflows"]
        listed_workflow = next(item for item in listed if item["id"] == workflow_id)
        assert listed_workflow["category"] == "software_development"
        assert listed_workflow["icon"] == "code"

        detailed = _require_ok(session.get(f"{API_URL}/v1/workflows/{workflow_id}", timeout=REQUEST_TIMEOUT_SECONDS), "detail")["workflow"]
        assert detailed["category"] == "software_development"
        assert detailed["icon"] == "code"

        updated = _require_ok(
            session.patch(
                f"{API_URL}/v1/workflows/{workflow_id}",
                json={"category": "finance", "icon": "dollar-sign"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            ),
            "update",
        )["workflow"]
        assert updated["category"] == "finance"
        assert updated["icon"] == "dollar-sign"

        print(json.dumps({"status": "passed", "unauthorized_status": 401, "workflow_id": workflow_id}, sort_keys=True))
    finally:
        if workflow_id:
            session.delete(f"{API_URL}/v1/workflows/{workflow_id}", timeout=REQUEST_TIMEOUT_SECONDS)


def main() -> int:
    test_workflow_identity_real_dev()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
