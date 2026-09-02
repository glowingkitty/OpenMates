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
APPROVED_API_KEY_DEVICE_HASH = "approved-device"


def _request(method: str, path: str, headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers=headers or {})


# contract-test: supporting surface=rest_api assertions=sdk.auth.approved-api-key-device
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


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_limited_workflow_api_keys_need_read_write_and_execute_scopes() -> None:
    api_key_info = {
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"workflows": ["workflow:read", "workflow:create", "workflow:write"]},
        }
    }

    _enforce_api_key_route_policy(_request("GET", "/v1/workflows"), api_key_info)
    _enforce_api_key_route_policy(_request("POST", "/v1/workflows"), api_key_info)

    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(_request("POST", "/v1/workflows/workflow-1/run"), api_key_info)

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "workflow:execute"}


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_user_task_and_plan_content_routes_reject_developer_api_keys() -> None:
    api_key_info = {"api_key_metadata": {"full_access": True}}

    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(_request("GET", "/v1/user-tasks/task-1"), api_key_info)
    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "developer_api_access_not_classified"}

    with pytest.raises(HTTPException) as forged_sdk_exc:
        _enforce_api_key_route_policy(_request("GET", "/v1/user-tasks/task-1", {"x-openmates-sdk": "npm"}), api_key_info)
    assert forged_sdk_exc.value.status_code == 403
    assert forged_sdk_exc.value.detail == {"error": "developer_api_access_not_classified"}

    approved_device_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {"full_access": True},
    }
    _enforce_api_key_route_policy(
        _request("GET", "/v1/user-tasks/task-1", {"x-openmates-sdk": "npm"}),
        approved_device_info,
    )

    approved_scoped_device_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {"full_access": True, "scopes": {"tasks": ["task:read"]}},
    }
    _enforce_api_key_route_policy(
        _request("GET", "/v1/user-tasks/task-1", {"x-openmates-sdk": "npm"}),
        approved_scoped_device_info,
    )

    _enforce_api_key_route_policy(_request("GET", "/v1/user-tasks/task-1/metadata"), api_key_info)
    _enforce_api_key_route_policy(_request("GET", "/v1/user-plans/plan-1/metadata"), api_key_info)


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_approved_api_key_device_can_use_encrypted_task_and_plan_routes_with_scopes() -> None:
    headers = {"x-openmates-sdk": "npm"}
    api_key_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {
            "full_access": False,
            "scopes": {
                "tasks": ["task:read", "task:create", "task:write"],
                "plans": ["plan:read", "plan:create", "plan:write"],
            },
        }
    }

    _enforce_api_key_route_policy(_request("GET", "/v1/user-tasks", headers), api_key_info)
    _enforce_api_key_route_policy(_request("POST", "/v1/user-tasks", headers), api_key_info)
    _enforce_api_key_route_policy(_request("GET", "/v1/user-plans", headers), api_key_info)
    _enforce_api_key_route_policy(_request("PATCH", "/v1/user-plans/plan-1", headers), api_key_info)

    limited_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {"full_access": False, "scopes": {"plans": ["plan:read"]}},
    }
    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(_request("POST", "/v1/user-plans", headers), limited_info)
    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "plan:create"}


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_approved_api_key_device_project_crud_requires_project_scopes() -> None:
    headers = {"x-openmates-sdk": "npm"}
    api_key_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"projects": ["project:read", "project:create", "project:write"]},
        }
    }

    _enforce_api_key_route_policy(_request("GET", "/v1/projects", headers), api_key_info)
    _enforce_api_key_route_policy(_request("PATCH", "/v1/projects/project-1", headers), api_key_info)

    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(
            _request("POST", "/v1/projects", headers),
            {
                "device_hash": APPROVED_API_KEY_DEVICE_HASH,
                "api_key_metadata": {"full_access": False, "scopes": {"projects": ["project:read"]}},
            },
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "project:create"}


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_create_only_product_scopes_do_not_grant_read_or_modify_access() -> None:
    headers = {"x-openmates-sdk": "npm"}
    api_key_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {
            "full_access": False,
            "scopes": {
                "tasks": ["task:create"],
                "plans": ["plan:create"],
                "projects": ["project:create"],
                "workflows": ["workflow:create"],
            },
        }
    }

    _enforce_api_key_route_policy(_request("POST", "/v1/user-tasks", headers), api_key_info)
    _enforce_api_key_route_policy(_request("POST", "/v1/user-plans", headers), api_key_info)
    _enforce_api_key_route_policy(_request("POST", "/v1/projects", headers), api_key_info)
    _enforce_api_key_route_policy(_request("POST", "/v1/workflows", headers), api_key_info)

    with pytest.raises(HTTPException) as task_read_exc:
        _enforce_api_key_route_policy(_request("GET", "/v1/user-tasks", headers), api_key_info)
    assert task_read_exc.value.detail == {"error": "missing_scope", "missing_scope": "task:read"}

    with pytest.raises(HTTPException) as plan_write_exc:
        _enforce_api_key_route_policy(_request("PATCH", "/v1/user-plans/plan-1", headers), api_key_info)
    assert plan_write_exc.value.detail == {"error": "missing_scope", "missing_scope": "plan:write"}

    with pytest.raises(HTTPException) as project_write_exc:
        _enforce_api_key_route_policy(_request("PATCH", "/v1/projects/project-1", headers), api_key_info)
    assert project_write_exc.value.detail == {"error": "missing_scope", "missing_scope": "project:write"}

    with pytest.raises(HTTPException) as workflow_execute_exc:
        _enforce_api_key_route_policy(_request("POST", "/v1/workflows/workflow-1/run", headers), api_key_info)
    assert workflow_execute_exc.value.detail == {"error": "missing_scope", "missing_scope": "workflow:execute"}

    with pytest.raises(HTTPException) as unapproved_exc:
        _enforce_api_key_route_policy(
            _request("POST", "/v1/projects", headers),
            {"api_key_metadata": api_key_info["api_key_metadata"]},
        )
    assert unapproved_exc.value.detail == {"error": "developer_api_access_not_classified"}


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_full_access_approved_device_bypasses_supported_product_scope_checks() -> None:
    api_key_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {"full_access": True, "scopes": {}},
    }

    for method, path in (
        ("GET", "/v1/user-tasks/task-1"),
        ("POST", "/v1/user-tasks"),
        ("PATCH", "/v1/user-plans/plan-1"),
        ("GET", "/v1/projects/project-1"),
        ("POST", "/v1/workflows/workflow-1/run"),
    ):
        _enforce_api_key_route_policy(_request(method, path), api_key_info)


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_unmapped_api_key_routes_fail_closed_except_app_routes() -> None:
    api_key_info = {
        "device_hash": APPROVED_API_KEY_DEVICE_HASH,
        "api_key_metadata": {"full_access": False, "scopes": {}},
    }

    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(_request("GET", "/v1/users/user-1/profile-image"), api_key_info)
    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "developer_api_access_not_classified"}

    _enforce_api_key_route_policy(_request("POST", "/v1/apps/web/skills/search"), api_key_info)

    with pytest.raises(HTTPException) as full_access_exc:
        _enforce_api_key_route_policy(
            _request("GET", "/v1/users/user-1/profile-image"),
            {**api_key_info, "api_key_metadata": {"full_access": True}},
        )
    assert full_access_exc.value.status_code == 403
    assert full_access_exc.value.detail == {"error": "developer_api_access_not_classified"}


# contract-test: supporting surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_project_remote_source_routes_remain_session_only() -> None:
    projects_source = (Path(__file__).resolve().parents[2] / "backend/core/api/app/routes/projects.py").read_text(encoding="utf-8")
    assert "async def list_projects(" in projects_source
    assert "async def create_project(" in projects_source
    assert projects_source.count("Depends(get_current_user_or_api_key)") >= 5
    for function_name in (
        "list_project_sources",
        "create_project_source",
        "delete_project_source",
        "create_project_remote_access_request",
        "get_project_remote_access_request_result",
    ):
        function_source = projects_source.split(f"async def {function_name}(", 1)[1].split(") ->", 1)[0]
        assert "Depends(get_current_user)" in function_source
