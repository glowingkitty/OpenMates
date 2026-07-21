# backend/tests/test_workflows_routes_security.py
#
# Focused security contracts for /v1/workflows route shells.
# These tests avoid full app startup so optional runtime dependencies do not hide
# route-level authorization and rate-limit regressions.

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.auth_routes.auth_dependencies import _enforce_api_key_route_policy


WORKFLOWS_PATH = Path(__file__).resolve().parents[2] / "backend/core/api/app/routes/workflows.py"


def _request(method: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def test_workflow_routes_have_explicit_slowapi_limits() -> None:
    lines = WORKFLOWS_PATH.read_text(encoding="utf-8").splitlines()
    missing_limits: list[str] = []

    for index, line in enumerate(lines):
        if not line.startswith("@router."):
            continue
        next_non_empty = next((candidate.strip() for candidate in lines[index + 1:] if candidate.strip()), "")
        if not next_non_empty.startswith("@limiter.limit("):
            missing_limits.append(f"line {index + 1}: {line.strip()}")

    assert missing_limits == []


def test_limited_workflow_api_keys_need_read_write_and_execute_scopes() -> None:
    api_key_info = {
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"workflows": ["workflow:read", "workflow:write"]},
        }
    }

    _enforce_api_key_route_policy(_request("GET", "/v1/workflows"), api_key_info)
    _enforce_api_key_route_policy(_request("POST", "/v1/workflows"), api_key_info)

    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(_request("POST", "/v1/workflows/workflow-1/run"), api_key_info)

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "workflow:execute"}


def test_user_task_and_plan_content_routes_reject_developer_api_keys() -> None:
    api_key_info = {"api_key_metadata": {"full_access": True}}

    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(_request("GET", "/v1/user-tasks/task-1"), api_key_info)
    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "developer_api_access_not_classified"}

    _enforce_api_key_route_policy(_request("GET", "/v1/user-tasks/task-1/metadata"), api_key_info)
    _enforce_api_key_route_policy(_request("GET", "/v1/user-plans/plan-1/metadata"), api_key_info)
