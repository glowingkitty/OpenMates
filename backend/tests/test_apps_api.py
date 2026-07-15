# backend/tests/test_apps_api.py
#
# Focused tests for custom app-skill routes registered by apps_api.py. These
# verify route wiring and auth/dependency integration without starting external
# providers or Celery tasks.

from __future__ import annotations

import base64
import hashlib
import importlib
import inspect
import re
import sys
import types

import pytest
from fastapi import FastAPI, HTTPException, Response
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
sys.modules.setdefault("regex", re)


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

User = importlib.import_module("backend.core.api.app.models.user").User
apps_api = importlib.import_module("backend.core.api.app.routes.apps_api")
get_current_user_or_api_key = importlib.import_module(
    "backend.core.api.app.routes.auth_routes.auth_dependencies"
).get_current_user_or_api_key

for module_name, stub in (
    ("backend.core.api.app.services.limiter", limiter_stub),
    ("googleapiclient", googleapiclient_stub),
    ("googleapiclient.discovery", googleapiclient_discovery_stub),
    ("googleapiclient.errors", googleapiclient_errors_stub),
    ("backend.core.api.app.tasks", tasks_stub),
    ("backend.core.api.app.tasks.celery_config", celery_config_stub),
    ("backend.core.api.app.services.cache", cache_stub),
    ("backend.core.api.app.services.directus", directus_stub),
    ("backend.core.api.app.utils.encryption", encryption_stub),
):
    if sys.modules.get(module_name) is stub:
        sys.modules.pop(module_name)


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


@pytest.mark.asyncio
async def test_session_or_api_key_auth_preserves_device_approval_errors(monkeypatch) -> None:
    api_key_auth_module = importlib.import_module("backend.core.api.app.utils.api_key_auth")

    class FakeApiKeyAuthService:
        async def authenticate_api_key(self, api_key, request):
            assert api_key == "sk-api-test"
            raise api_key_auth_module.DeviceNotApprovedError("New device detected")

    monkeypatch.setattr(
        api_key_auth_module,
        "get_api_key_auth_service",
        lambda _request: FakeApiKeyAuthService(),
    )

    request = types.SimpleNamespace(headers={"Authorization": "Bearer sk-api-test"})

    with pytest.raises(HTTPException) as exc:
        await apps_api.get_session_or_api_key_info(
            request=request,
            response=Response(),
            cache_service=object(),
            directus_service=object(),
            refresh_token=None,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "New device detected"


@pytest.mark.asyncio
async def test_session_auth_tags_apple_client_with_device_hash(monkeypatch) -> None:
    user = User(id="user-apple", username="alice", vault_key_id="vault-1", credits=10)

    async def fake_get_current_user(**_kwargs):
        return user

    monkeypatch.setattr(apps_api, "get_current_user", fake_get_current_user)

    request = types.SimpleNamespace(
        headers={
            "User-Agent": "OpenMates-Apple/1.2.3",
            "X-OpenMates-Client": "ios",
            "X-OpenMates-Bundle-ID": "org.openmates.app",
        }
    )

    result = await apps_api.get_session_or_api_key_info(
        request=request,
        response=Response(),
        cache_service=object(),
        directus_service=object(),
        refresh_token="session-token",
    )

    expected_hash = hashlib.sha256("user-apple:ios:org.openmates.app".encode()).hexdigest()
    assert result["user_id"] == "user-apple"
    assert result["api_key_hash"] is None
    assert result["device_hash"] == f"apple-ios:{expected_hash}"
    assert result["is_cli"] is False


@pytest.mark.asyncio
async def test_usage_summaries_use_apple_device_identifier(monkeypatch) -> None:
    usage_module = importlib.import_module("backend.core.api.app.services.directus.usage")
    usage = usage_module.UsageMethods(sdk=object(), encryption_service=object())
    monthly_calls: list[dict[str, object]] = []
    daily_calls: list[dict[str, object]] = []

    async def fake_update_summary(**kwargs):
        monthly_calls.append(kwargs)

    async def fake_update_daily_summary(**kwargs):
        daily_calls.append(kwargs)

    monkeypatch.setattr(usage, "_update_summary", fake_update_summary)
    monkeypatch.setattr(usage, "_update_daily_summary", fake_update_daily_summary)
    usage.sdk = types.SimpleNamespace(cache=types.SimpleNamespace(delete=lambda *_args, **_kwargs: None))

    async def fake_cache_delete(*_args, **_kwargs):
        return None

    usage.sdk.cache.delete = fake_cache_delete
    device_hash = "apple-ios:" + "a" * 64

    await usage._update_monthly_summaries(
        user_id_hash="user-hash",
        timestamp=1_720_000_000,
        credits_charged=2,
        chat_id=None,
        app_id="events",
        api_key_hash=None,
        device_hash=device_hash,
    )
    await usage._update_daily_summaries(
        user_id_hash="user-hash",
        timestamp=1_720_000_000,
        credits_charged=2,
        chat_id=None,
        app_id="events",
        api_key_hash=None,
        device_hash=device_hash,
    )

    assert any(call["identifier_value"] == device_hash for call in monthly_calls)
    assert any(call["identifier_value"] == device_hash for call in daily_calls)


@pytest.mark.asyncio
async def test_usage_details_filter_apple_device_identifier() -> None:
    usage_module = importlib.import_module("backend.core.api.app.services.directus.usage")
    captured_params: dict[str, object] = {}
    device_hash = "apple-ios:" + "b" * 64

    class FakeSDK:
        async def get_items(self, collection_name, params, no_cache=False):
            if collection_name == "usage_monthly_api_key_summaries":
                return [{"id": "summary-1", "is_archived": False, "archive_s3_key": None}]
            captured_params.update(params)
            return []

    usage = usage_module.UsageMethods(sdk=FakeSDK(), encryption_service=object())

    entries = await usage.get_usage_entries_for_summary(
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        summary_type="api_key",
        identifier=device_hash,
        year_month="2024-07",
    )

    assert entries == []
    assert captured_params["filter"]["device_hash"] == {"_eq": device_hash}
    assert "api_key_hash" not in captured_params["filter"]


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
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.code_execution", code_execution)
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


def test_models3d_custom_route_resolves_only_the_callers_uploaded_image(monkeypatch) -> None:
    captured: dict[str, object] = {}
    user = User(id="user-1", username="alice", vault_key_id="vault-1", credits=10)
    expected_user_hash = hashlib.sha256(user.id.encode()).hexdigest()
    user_info = {
        "user_id": user.id,
        "api_key_encrypted_name": "",
        "api_key_hash": "api-key-hash",
        "api_key_metadata": {"allowed_app_skills": ["models3d.generate"]},
        "device_hash": None,
    }

    class FakeCache:
        async def get_user_vault_key_id(self, user_id):
            assert user_id == user.id
            return "vault-1"

        async def get_embed_from_cache(self, embed_id):
            assert embed_id == "embed-chair"
            return {
                "embed_id": embed_id,
                "user_id": user.id,
                "vault_wrapped_aes_key": "wrapped-aes-key",
                "aes_nonce": "nonce-b64",
                "aes_key": "plaintext-must-not-forward",
                "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
            }

    class FakeEmbedService:
        called = False

        async def get_embed_by_id(self, embed_id):
            self.called = True
            assert embed_id == "embed-chair"
            return {"embed_id": embed_id, "hashed_user_id": expected_user_hash}

    async def fake_call_app_skill(**kwargs):
        captured.update(kwargs)
        return {"task_id": "task-model-1", "status": "processing"}

    async def fake_require_api_key_budget_for_charge(directus_service, *, user_info, requested_credits):
        captured["budget"] = {
            "directus_service": directus_service,
            "user_info": user_info,
            "requested_credits": requested_credits,
        }

    fake_embed_service = FakeEmbedService()
    app = FastAPI()
    app.dependency_overrides[apps_api.get_session_or_api_key_info] = lambda: user_info
    app.dependency_overrides[apps_api.get_cache_service] = lambda: FakeCache()
    app.dependency_overrides[apps_api.get_directus_service] = lambda: types.SimpleNamespace(embed=fake_embed_service)
    monkeypatch.setattr(apps_api, "call_app_skill", fake_call_app_skill)
    monkeypatch.setattr(apps_api, "require_api_key_budget_for_charge", fake_require_api_key_budget_for_charge)
    apps_api._register_models3d_custom_routes(app, "models3d")
    route = next(route for route in app.routes if route.path == "/v1/apps/models3d/skills/generate")
    assert "request" in inspect.signature(route.endpoint).parameters

    response = TestClient(app).post(
        "/v1/apps/models3d/skills/generate",
        json={"image_embed_refs": ["embed-chair"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"task_id": "task-model-1", "status": "processing"},
        "error": None,
        "credits_charged": None,
    }
    assert captured["input_data"] == {
        "image_embed_refs": ["embed-chair"],
        "_file_path_index": {"embed-chair": "embed-chair"},
        "_user_vault_key_id": "vault-1",
        "input_embed_records": {
            "embed-chair": {
                "embed_id": "embed-chair",
                "vault_wrapped_aes_key": "wrapped-aes-key",
                "aes_nonce": "nonce-b64",
                "files": {"original": {"s3_key": "inputs/chair.png", "format": "png"}},
            }
        },
    }
    assert "plaintext-must-not-forward" not in str(captured["input_data"])
    assert captured["enforce_rest_exposure_policy"] is False
    assert captured["user_info"] is user_info
    assert captured["budget"]["user_info"] is user_info
    assert captured["budget"]["requested_credits"] == 25
    assert fake_embed_service.called is False
