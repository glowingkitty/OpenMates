# backend/tests/test_code_run_app_skill.py
#
# Contract tests for the Code Run app-skill API entrypoint. These tests keep
# direct CLI/API runs separate from chat-bound embed persistence and verify that
# backend validation treats source code as inert data before E2B execution.

from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _find_spec_or_none(name: str):
    try:
        return importlib.util.find_spec(name)
    except ValueError:
        return None


if _find_spec_or_none("toon_format") is None:
    toon_format_stub = types.ModuleType("toon_format")
    toon_format_stub.__spec__ = importlib.machinery.ModuleSpec("toon_format", loader=None)

    def _stub_encode(value: dict) -> str:
        return "\n".join(f"{key}: {item}" for key, item in value.items())

    def _stub_decode(value: str) -> dict:
        decoded: dict[str, str] = {}
        for line in value.splitlines():
            key, _, item = line.partition(": ")
            if key:
                decoded[key] = item
        return decoded

    toon_format_stub.encode = _stub_encode
    toon_format_stub.decode = _stub_decode
    sys.modules.setdefault("toon_format", toon_format_stub)

if _find_spec_or_none("celery") is None:
    tasks_stub = types.ModuleType("backend.core.api.app.tasks")
    tasks_stub.__path__ = [str(Path(__file__).resolve().parents[1] / "core/api/app/tasks")]
    celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")

    class _CeleryAppStub:
        def send_task(self, *_args, **_kwargs):
            return None

        def task(self, *_args, **_kwargs):
            return lambda func: func

    async def _missing_worker_cache_service():
        raise AssertionError("worker cache service is not used by these unit tests")

    celery_config_stub.app = _CeleryAppStub()
    celery_config_stub.get_worker_cache_service = _missing_worker_cache_service
    sys.modules.setdefault("backend.core.api.app.tasks", tasks_stub)
    sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)

if _find_spec_or_none("redis") is None:
    redis_stub = types.ModuleType("redis")
    redis_asyncio_stub = types.ModuleType("redis.asyncio")
    redis_stub.__spec__ = importlib.machinery.ModuleSpec("redis", loader=None)
    redis_asyncio_stub.__spec__ = importlib.machinery.ModuleSpec("redis.asyncio", loader=None)

    class _RedisStub:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("real Redis is not used by these unit tests")

    redis_asyncio_stub.Redis = _RedisStub
    redis_stub.asyncio = redis_asyncio_stub
    redis_stub.exceptions = SimpleNamespace(
        ConnectionError=ConnectionError,
        TimeoutError=TimeoutError,
        RedisError=Exception,
    )
    sys.modules.setdefault("redis", redis_stub)
    sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

if _find_spec_or_none("aiohttp") is None:
    aiohttp_stub = types.ModuleType("aiohttp")
    aiohttp_stub.ClientSession = object
    sys.modules.setdefault("aiohttp", aiohttp_stub)

sys.modules.setdefault("regex", re)
googleapiclient_stub = types.ModuleType("googleapiclient")
googleapiclient_discovery_stub = types.ModuleType("googleapiclient.discovery")
googleapiclient_errors_stub = types.ModuleType("googleapiclient.errors")
googleapiclient_discovery_stub.build = lambda *_args, **_kwargs: None
googleapiclient_errors_stub.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapiclient_stub)
sys.modules.setdefault("googleapiclient.discovery", googleapiclient_discovery_stub)
sys.modules.setdefault("googleapiclient.errors", googleapiclient_errors_stub)

if _find_spec_or_none("slowapi") is None:
    slowapi_stub = types.ModuleType("slowapi")
    slowapi_util_stub = types.ModuleType("slowapi.util")

    class _LimiterStub:
        def __init__(self, *_args, **_kwargs):
            pass

        def limit(self, *_args, **_kwargs):
            return lambda func: func

    slowapi_stub.Limiter = _LimiterStub
    slowapi_util_stub.get_remote_address = lambda request: "127.0.0.1"
    sys.modules.setdefault("slowapi", slowapi_stub)
    sys.modules.setdefault("slowapi.util", slowapi_util_stub)

from backend.core.api.app.models.user import User  # noqa: E402
from backend.core.api.app.routes import code_execution  # noqa: E402


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


# contract-test: direct surface=rest_api assertions=code-run.request.validated,code-run.output.direct-transient
def test_direct_code_run_files_validate_entry_and_internet_default() -> None:
    request = code_execution.CodeRunAppSkillRequest.model_validate({
        "requests": [{
            "entry_path": "main.py",
            "files": [{"path": "main.py", "content_base64": _b64("print('ok')\n"), "language": "python"}],
        }]
    })

    files, target_path = code_execution.collect_direct_code_run_files(request.requests[0])

    assert target_path == "main.py"
    assert request.requests[0].enable_internet is True
    assert files == [{
        "path": "main.py",
        "content_base64": _b64("print('ok')\n"),
        "content": "print('ok')\n",
        "language": "python",
        "is_target": True,
        "mime_type": "text/plain",
    }]


# contract-test: direct surface=rest_api assertions=code-run.request.validated
@pytest.mark.parametrize("bad_path", ["/tmp/main.py", "../main.py", "src/../../main.py", "C:/tmp/main.py", "~/main.py"])
def test_direct_code_run_rejects_unsafe_paths(bad_path: str) -> None:
    item = code_execution.CodeRunAppSkillRunItem.model_validate({
        "entry_path": bad_path,
        "files": [{"path": bad_path, "content_base64": _b64("print('x')"), "language": "python"}],
    })

    with pytest.raises(HTTPException) as exc:
        code_execution.collect_direct_code_run_files(item)

    assert exc.value.status_code == 400


# contract-test: direct surface=rest_api assertions=code-run.request.validated
def test_direct_code_run_rejects_backend_url_fetch_fields() -> None:
    with pytest.raises(ValueError):
        code_execution.CodeRunAppSkillRunItem.model_validate({
            "entry_path": "main.py",
            "url": "https://raw.githubusercontent.com/org/repo/main/main.py",
            "files": [],
        })


# contract-test: direct surface=rest_api assertions=code-run.request.validated
def test_direct_code_run_rejects_unsafe_dependency_manifest() -> None:
    item = code_execution.CodeRunAppSkillRunItem.model_validate({
        "entry_path": "main.py",
        "files": [
            {"path": "main.py", "content_base64": _b64("print('x')"), "language": "python"},
            {"path": "requirements.txt", "content_base64": _b64("git+https://example.com/repo.git\n")},
        ],
    })

    with pytest.raises(HTTPException) as exc:
        code_execution.collect_direct_code_run_files(item)

    assert exc.value.status_code == 400
    assert "requirements.txt" in str(exc.value.detail)


class _AwaitableValue:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _inner():
            return self.value

        return _inner().__await__()


# contract-test: direct surface=rest_api assertions=code-run.output.direct-transient,code-run.request.validated
@pytest.mark.anyio
async def test_start_direct_code_run_does_not_require_chat_or_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_tasks: list[tuple[str, list[object], str]] = []

    async def fake_create_execution_record(_cache_service, execution_id: str, data: dict) -> None:
        assert data["target_embed_id"] is None
        assert data["target_filename"] == "main.py"

    async def fake_add_active_run(_client, _active_key: str, _execution_id: str) -> bool:
        return True

    async def fake_reserve_provider(_client, _execution_id: str) -> str | None:
        return None

    monkeypatch.setattr(code_execution, "_create_execution_record", fake_create_execution_record)
    monkeypatch.setattr(code_execution, "_try_add_active_run", fake_add_active_run)
    monkeypatch.setattr(code_execution, "_try_reserve_provider_run", fake_reserve_provider)
    monkeypatch.setattr(code_execution.uuid, "uuid4", lambda: "execution-1")
    monkeypatch.setattr(
        code_execution.celery_app,
        "send_task",
        lambda name, args, queue: sent_tasks.append((name, args, queue)),
    )

    fake_client = SimpleNamespace(srem=lambda *_args: None)
    cache_service = SimpleNamespace(client=_AwaitableValue(fake_client))
    user = User(id="user-1", username="alice", vault_key_id="vault-1", credits=10)

    response = await code_execution.start_code_run_execution(
        current_user=user,
        cache_service=cache_service,
        files=[{"path": "main.py", "content_base64": _b64("print('ok')"), "language": "python", "is_target": True}],
        target_path="main.py",
        enable_internet=True,
        chat_id=None,
        target_embed_id=None,
        message_id=None,
        dependency_installs=[],
    )

    assert response.execution_id == "execution-1"
    assert response.target_filename == "main.py"
    assert sent_tasks[0][0] == "code.run_execution"
    payload = sent_tasks[0][1][1]
    assert payload["chat_id"] is None
    assert payload["target_embed_id"] is None
    assert payload["enable_internet"] is True
