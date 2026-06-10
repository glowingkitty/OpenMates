# backend/tests/test_apps_api.py
#
# Focused tests for custom app-skill routes registered by apps_api.py. These
# verify route wiring and auth/dependency integration without starting external
# providers or Celery tasks.

from __future__ import annotations

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.models.user import User
from backend.core.api.app.routes import apps_api, code_execution
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def test_code_run_app_skill_route_starts_direct_run(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_start_code_run_execution(**kwargs):
        captured.update(kwargs)
        return code_execution.CodeRunStartResponse(
            execution_id="exec-1",
            status="queued",
            target_filename="main.py",
            files=["main.py"],
        )

    user = User(id="user-1", username="alice", vault_key_id="vault-1", credits=10)
    app = FastAPI()
    app.dependency_overrides[get_current_user_or_api_key] = lambda: user
    app.dependency_overrides[apps_api.get_cache_service] = lambda: object()
    app.dependency_overrides[apps_api.get_directus_service] = lambda: object()
    app.dependency_overrides[apps_api.get_encryption_service] = lambda: object()

    monkeypatch.setattr(code_execution, "start_code_run_execution", fake_start_code_run_execution)
    apps_api._register_code_custom_routes(app, "code")

    response = TestClient(app).post(
        "/v1/apps/code/skills/run",
        json={
            "requests": [{
                "entry_path": "main.py",
                "files": [{"path": "main.py", "content_base64": _b64("print('ok')\n"), "language": "python"}],
            }]
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "results": [{
                "execution_id": "exec-1",
                "status": "queued",
                "target_filename": "main.py",
                "files": ["main.py"],
                "credits_per_minute": code_execution.RUN_CREDITS_PER_MINUTE,
                "persisted_output": False,
                "stream_path": "/v1/code/run/exec-1/stream",
                "status_path": "/v1/code/run/exec-1",
            }]
        },
    }
    assert captured["current_user"] is user
    assert captured["chat_id"] is None
    assert captured["target_embed_id"] is None
    assert captured["target_path"] == "main.py"
    assert captured["enable_internet"] is True
