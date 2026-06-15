# backend/tests/test_apps_api.py
#
# Focused tests for custom app-skill routes registered by apps_api.py. These
# verify route wiring and auth/dependency integration without starting external
# providers or Celery tasks.

from __future__ import annotations

import base64
import importlib
import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _StubLimiter:
    def limit(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator


limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _StubLimiter()
sys.modules.setdefault("backend.core.api.app.services.limiter", limiter_stub)

googleapiclient_stub = types.ModuleType("googleapiclient")
googleapiclient_discovery_stub = types.ModuleType("googleapiclient.discovery")
googleapiclient_errors_stub = types.ModuleType("googleapiclient.errors")
googleapiclient_discovery_stub.build = lambda *_args, **_kwargs: None
googleapiclient_errors_stub.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapiclient_stub)
sys.modules.setdefault("googleapiclient.discovery", googleapiclient_discovery_stub)
sys.modules.setdefault("googleapiclient.errors", googleapiclient_errors_stub)

tasks_stub = types.ModuleType("backend.core.api.app.tasks")
tasks_stub.__path__ = []
celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")
celery_config_stub.app = types.SimpleNamespace(send_task=lambda *_args, **_kwargs: None)
sys.modules.setdefault("backend.core.api.app.tasks", tasks_stub)
sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)

cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)
sys.modules.setdefault("backend.core.api.app.services.directus", directus_stub)
sys.modules.setdefault("backend.core.api.app.utils.encryption", encryption_stub)


class CodeRunDirectFile(BaseModel):
    path: str
    content_base64: str
    language: str = ""
    is_target: bool = False


class CodeRunAppSkillRunItem(BaseModel):
    mode: str = "direct"
    entry_path: str | None = None
    files: list[CodeRunDirectFile] = Field(default_factory=list)
    chat_id: str | None = None
    target_embed_id: str | None = None
    selected_embed_ids: list[str] | None = None
    dependency_installs: list[object] = Field(default_factory=list)
    enable_internet: bool = True


class CodeRunAppSkillRequest(BaseModel):
    requests: list[CodeRunAppSkillRunItem]


class CodeRunClientFile(BaseModel):
    embed_id: str
    code: str
    language: str = ""
    filename: str
    is_target: bool = False


class CodeRunAppSkillResult(BaseModel):
    execution_id: str
    status: str
    target_filename: str
    files: list[str]
    credits_per_minute: int = 5
    persisted_output: bool = False
    stream_path: str
    status_path: str


class CodeRunAppSkillResponseData(BaseModel):
    results: list[CodeRunAppSkillResult]


class CodeRunAppSkillResponse(BaseModel):
    success: bool = True
    data: CodeRunAppSkillResponseData


class CodeRunStartResponse(BaseModel):
    execution_id: str
    status: str
    target_filename: str
    files: list[str]
    credits_per_minute: int = 5


def collect_direct_code_run_files(item: CodeRunAppSkillRunItem):
    target_path = item.entry_path or (item.files[0].path if item.files else "main.py")
    return [file.model_dump() for file in item.files], target_path


async def start_code_run_execution(**_kwargs):
    raise AssertionError("test must patch start_code_run_execution")


async def _collect_code_files(*_args, **_kwargs):
    return [], "main.py"


async def _get_embed_metadata(*_args, **_kwargs):
    return {}


code_execution = types.ModuleType("backend.core.api.app.routes.code_execution")
code_execution.CODE_RUN_START_RATE_LIMIT = "10/minute"
code_execution.RUN_CREDITS_PER_MINUTE = 5
code_execution.CodeRunAppSkillRequest = CodeRunAppSkillRequest
code_execution.CodeRunAppSkillResponse = CodeRunAppSkillResponse
code_execution.CodeRunAppSkillResponseData = CodeRunAppSkillResponseData
code_execution.CodeRunAppSkillResult = CodeRunAppSkillResult
code_execution.CodeRunClientFile = CodeRunClientFile
code_execution.CodeRunStartResponse = CodeRunStartResponse
code_execution.collect_direct_code_run_files = collect_direct_code_run_files
code_execution._collect_code_files = _collect_code_files
code_execution._get_embed_metadata = _get_embed_metadata
code_execution.start_code_run_execution = start_code_run_execution
sys.modules.setdefault("backend.core.api.app.routes.code_execution", code_execution)

User = importlib.import_module("backend.core.api.app.models.user").User
apps_api = importlib.import_module("backend.core.api.app.routes.apps_api")
get_current_user_or_api_key = importlib.import_module(
    "backend.core.api.app.routes.auth_routes.auth_dependencies"
).get_current_user_or_api_key


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
