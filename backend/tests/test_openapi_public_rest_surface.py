# backend/tests/test_openapi_public_rest_surface.py
#
# Contract tests for the developer-facing OpenAPI surface.
# Runtime-public utilities may remain callable, but the generated REST docs must
# only advertise endpoints that are intended for developers. Client-side
# encrypted product routes stay official-client-only unless a narrow safe
# metadata endpoint is explicitly documented.

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.routes import developer_metadata_api


REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_API_PATH = REPO_ROOT / "backend/core/api/main.py"


def test_openapi_hides_runtime_only_and_encrypted_product_routes() -> None:
    main_source = MAIN_API_PATH.read_text(encoding="utf-8")

    assert "app.include_router(geocode.router, include_in_schema=False)" in main_source
    assert "app.include_router(analytics_beacon.router, include_in_schema=False)" in main_source
    assert "app.include_router(default_inspirations.router, include_in_schema=False)" in main_source
    assert "app.include_router(settings.router, include_in_schema=False)" in main_source
    assert "app.include_router(projects.router, include_in_schema=False)" in main_source
    assert "app.include_router(user_tasks.router, include_in_schema=False)" in main_source
    assert "app.include_router(user_plans.router, include_in_schema=False)" in main_source
    assert "app.include_router(ideabucket.router, include_in_schema=False)" in main_source
    assert "app.include_router(workspace_history.router, include_in_schema=False)" in main_source
    assert "app.include_router(developer_metadata_api.router, include_in_schema=True)" in main_source

    app = FastAPI()
    app.include_router(developer_metadata_api.router)
    schema = app.openapi()
    paths = set(schema["paths"])
    assert "/v1/user-tasks/metadata" in paths
    assert "/v1/user-tasks/{task_id}/metadata" in paths
    assert "/v1/user-plans/metadata" in paths
    assert "/v1/user-plans/{plan_id}/metadata" in paths

    safe_metadata_docs = {
        path: schema["paths"][path]
        for path in paths
        if path.startswith(("/v1/user-tasks", "/v1/user-plans"))
    }
    assert set(safe_metadata_docs) == {
        "/v1/user-tasks/metadata",
        "/v1/user-tasks/{task_id}/metadata",
        "/v1/user-plans/metadata",
        "/v1/user-plans/{plan_id}/metadata",
    }
    assert "encrypted_" not in json.dumps(safe_metadata_docs).lower()


class FakeUserTaskMethods:
    async def summarize_task_metadata(self, user_id: str) -> dict:
        assert user_id == "user-1"
        return {"total": 3, "by_status": {"todo": 2, "done": 1}}

    async def get_task_metadata(self, task_id: str, user_id: str) -> dict | None:
        assert task_id == "task-1"
        assert user_id == "user-1"
        return {"task_id": task_id, "status": "in_progress", "updated_at": 123, "version": 2}


class FakeUserPlanMethods:
    async def summarize_plan_metadata(self, user_id: str) -> dict:
        assert user_id == "user-1"
        return {"total": 2, "by_status": {"active": 1, "completed": 1}}

    async def get_plan_metadata(self, plan_id: str, user_id: str) -> dict | None:
        assert plan_id == "plan-1"
        assert user_id == "user-1"
        return {"plan_id": plan_id, "status": "active", "updated_at": 456, "version": 3}


def _metadata_client(api_key_metadata: dict | None = None) -> TestClient:
    app = FastAPI()
    app.state.directus_service = SimpleNamespace(
        user_task=FakeUserTaskMethods(),
        user_plan=FakeUserPlanMethods(),
    )
    app.dependency_overrides[developer_metadata_api.get_session_or_api_key_info] = lambda: {
        "user_id": "user-1",
        "api_key_hash": "hash-1",
        "api_key_metadata": api_key_metadata or {"full_access": True},
    }
    app.include_router(developer_metadata_api.router)
    return TestClient(app)


def test_safe_task_and_plan_metadata_endpoints_return_no_encrypted_payloads() -> None:
    client = _metadata_client()

    task_summary = client.get("/v1/user-tasks/metadata")
    task_item = client.get("/v1/user-tasks/task-1/metadata")
    plan_summary = client.get("/v1/user-plans/metadata")
    plan_item = client.get("/v1/user-plans/plan-1/metadata")

    assert task_summary.status_code == 200
    assert task_item.status_code == 200
    assert plan_summary.status_code == 200
    assert plan_item.status_code == 200

    payload = json.dumps([
        task_summary.json(),
        task_item.json(),
        plan_summary.json(),
        plan_item.json(),
    ]).lower()
    assert "encrypted" not in payload
    assert task_summary.json() == {"total": 3, "by_status": {"todo": 2, "done": 1}}
    assert task_item.json()["status"] == "in_progress"
    assert plan_summary.json() == {"total": 2, "by_status": {"active": 1, "completed": 1}}
    assert plan_item.json()["status"] == "active"


def test_safe_metadata_endpoints_require_specific_scopes_for_limited_api_keys() -> None:
    client = _metadata_client(api_key_metadata={"full_access": False, "scopes": {"tasks": []}})

    response = client.get("/v1/user-tasks/metadata")

    assert response.status_code == 403
    assert response.json()["detail"] == {"error": "missing_scope", "missing_scope": "task:read_metadata"}
