# backend/tests/test_code_run_billing_attribution.py
#
# Focused tests for Code Run worker billing metadata.
# The worker module normally imports Celery and the E2B provider at module load;
# these tests stub those integration dependencies because they only verify the
# internal billing payload assembled by _charge_run_credits().

from __future__ import annotations

import sys
import types

import pytest


class _CeleryAppStub:
    def send_task(self, *_args, **_kwargs):
        return None

    def task(self, *_args, **_kwargs):
        return lambda func: func


tasks_stub = types.ModuleType("backend.core.api.app.tasks")
tasks_stub.__path__ = []
celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")
celery_config_stub.app = _CeleryAppStub()


async def _missing_worker_cache_service():
    raise AssertionError("worker cache service is not used by this unit test")


celery_config_stub.get_worker_cache_service = _missing_worker_cache_service
sys.modules.setdefault("backend.core.api.app.tasks", tasks_stub)
sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)

secrets_manager_stub = types.ModuleType("backend.core.api.app.utils.secrets_manager")


class _SecretsManagerStub:
    async def initialize(self):
        return None

    async def aclose(self):
        return None


secrets_manager_stub.SecretsManager = _SecretsManagerStub
sys.modules.setdefault("backend.core.api.app.utils.secrets_manager", secrets_manager_stub)

e2b_runner_stub = types.ModuleType("backend.shared.providers.e2b_code_runner")
e2b_runner_stub.CodeRunCancelled = type("CodeRunCancelled", (Exception,), {})
e2b_runner_stub.CodeRunDependencyInstall = object
e2b_runner_stub.CodeRunFile = object
e2b_runner_stub.get_e2b_api_key_async = lambda *_args, **_kwargs: None
e2b_runner_stub.redact_execution_output = lambda value: value
e2b_runner_stub.run_code_in_e2b = lambda *_args, **_kwargs: None
sys.modules.setdefault("backend.shared.providers.e2b_code_runner", e2b_runner_stub)

from backend.apps.code.tasks.run_code_task import _charge_run_credits  # noqa: E402


# contract-test: supporting surface=rest_api assertions=code-run.billing.rate-limits,code-run.surface-parity
@pytest.mark.anyio
async def test_charge_run_credits_preserves_api_key_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict, headers: dict):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("backend.apps.code.tasks.run_code_task.httpx.AsyncClient", FakeAsyncClient)

    await _charge_run_credits(
        {
            "user_id": "user-1",
            "user_id_hash": "user-hash",
            "chat_id": None,
            "message_id": None,
            "target_embed_id": None,
            "target_path": "main.py",
            "files": [{"path": "main.py"}],
            "api_key_hash": "api-key-hash",
            "device_hash": "device-hash",
        },
        5,
        "execution-1",
        {"billing_phase": "completed", "charged_minutes": 1},
    )

    assert requests[0]["json"]["api_key_hash"] == "api-key-hash"
    assert requests[0]["json"]["device_hash"] == "device-hash"
    assert requests[0]["json"]["idempotency_key"].startswith("code-run:execution-1:")
