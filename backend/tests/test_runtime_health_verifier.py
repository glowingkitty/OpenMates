"""Runtime health verifier contracts.

These tests define the no-spend, fail-closed server verification boundary used
after CLI-managed updates. The verifier is internal host tooling: it must select
self-host mode before billing secret access and finish within one global budget.
Spec: docs/specs/post-update-runtime-health-alerting/spec.yml.
"""

# contract-test-file: tooling

from __future__ import annotations

import asyncio
import builtins
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace
from types import ModuleType
import sys

import pytest

from backend.core.api.app.utils.server_mode import resolve_runtime_deployment_mode
from backend.scripts.runtime_health_verifier import (
    CELERY_PROBE_CHECK_TIMEOUT_SECONDS,
    CELERY_PROBE_RESULT_TIMEOUT_SECONDS,
    GLOBAL_DEADLINE_SECONDS,
    CheckDefinition,
    _check_billing_routes,
    _check_billing_workers,
    _check_billing_webhook,
    _check_stripe_account_read,
    build_check_inventory,
    execute_checks,
)


def test_directus_upload_storage_preserves_bind_mount_and_drops_root_privileges() -> None:
    compose_source = (Path(__file__).parents[1] / "core/docker-compose.yml").read_text(encoding="utf-8")
    dockerfile_source = (Path(__file__).parents[1] / "core/directus/Dockerfile").read_text(encoding="utf-8")

    assert "- ./directus/uploads:/directus/uploads" in compose_source
    assert 'test: ["CMD", "su-exec", "node:node", "/usr/local/bin/openmates-directus-health"]' in compose_source
    assert "chown node:node /directus/uploads" in dockerfile_source
    assert "apk add --no-cache curl postgresql-client su-exec" in dockerfile_source
    assert "exec su-exec node:node /usr/local/bin/openmates-directus-start" in dockerfile_source


@pytest.mark.asyncio
async def test_billing_route_discovery_probes_a_private_live_route(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        status_code = 401

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            return FakeResponse()

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(verifier.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    await _check_billing_routes()

    assert requested_urls == ["http://localhost:8000/v1/payments/subscription"]


@pytest.mark.asyncio
async def test_stripe_account_check_imports_sdk_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    event_loop_thread = threading.get_ident()
    stripe_import_threads: list[int] = []
    request_timeouts: list[int] = []
    closed_clients: list[bool] = []
    original_import = builtins.__import__

    class FakeRequestsClient:
        def __init__(self, *, timeout: int):
            request_timeouts.append(timeout)

        def close(self):
            closed_clients.append(True)

    fake_stripe = SimpleNamespace(
        Account=SimpleNamespace(retrieve=lambda: None),
        RequestsClient=FakeRequestsClient,
        api_key=None,
        default_http_client=None,
    )

    def tracking_import(name: str, *args, **kwargs):
        if name == "stripe":
            stripe_import_threads.append(threading.get_ident())
            return fake_stripe
        return original_import(name, *args, **kwargs)

    class FakeSecretsManager:
        async def get_secret(self, *_args, **_kwargs):
            return "synthetic-key"

    async def initialized_secrets_manager():
        return FakeSecretsManager()

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(builtins, "__import__", tracking_import)
    monkeypatch.setattr(verifier, "_initialized_secrets_manager", initialized_secrets_manager)

    await _check_stripe_account_read()

    assert stripe_import_threads
    assert all(thread_id != event_loop_thread for thread_id in stripe_import_threads)
    assert request_timeouts == [10]
    assert closed_clients == [True]


@pytest.mark.asyncio
async def test_secrets_manager_resolution_runs_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    event_loop_thread = threading.get_ident()
    secrets_import_threads: list[int] = []
    original_import = builtins.__import__

    class FakeSecretsManager:
        async def initialize(self):
            return True

    def tracking_import(name: str, *args, **kwargs):
        if name == "backend.core.api.app.utils.secrets_manager":
            secrets_import_threads.append(threading.get_ident())
            return SimpleNamespace(SecretsManager=FakeSecretsManager)
        return original_import(name, *args, **kwargs)

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    await verifier._initialized_secrets_manager()

    assert secrets_import_threads
    assert all(thread_id != event_loop_thread for thread_id in secrets_import_threads)


@pytest.mark.asyncio
async def test_billing_worker_discovery_resolves_celery_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    event_loop_thread = threading.get_ident()
    app_access_threads: list[int] = []
    fake_inspect = SimpleNamespace(registered=lambda: {"worker": ["billing.process_payment"]})
    fake_app = SimpleNamespace(control=SimpleNamespace(inspect=lambda **_kwargs: fake_inspect))

    class TrackingCeleryModule(ModuleType):
        def __getattr__(self, name: str):
            if name == "app":
                app_access_threads.append(threading.get_ident())
                return fake_app
            raise AttributeError(name)

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.tasks.celery_config",
        TrackingCeleryModule("backend.core.api.app.tasks.celery_config"),
    )

    await _check_billing_workers()

    assert app_access_threads
    assert all(thread_id != event_loop_thread for thread_id in app_access_threads)


@pytest.mark.parametrize(
    ("env", "status"),
    [
        ({}, "missing"),
        ({"OPENMATES_DEPLOYMENT_MODE": "cloud"}, "malformed"),
        ({"OPENMATES_DEPLOYMENT_MODE": "OFFICIAL_CLOUD"}, "malformed"),
        (
            {
                "OPENMATES_DEPLOYMENT_MODE": "official_cloud",
                "OPENMATES_CLOUD_OVERLAY_ENABLED": "false",
            },
            "conflicting",
        ),
    ],
)
def test_unknown_or_conflicting_mode_fails_closed(env: dict[str, str], status: str) -> None:
    result = resolve_runtime_deployment_mode(
        env=env,
        allowed_domain="example.org",
        hosting_domain="api.example.org",
        overlay_importable=True,
    )

    assert result.effective_mode == "self_host"
    assert result.status == status
    assert result.billing_enabled is False


def test_official_cloud_requires_all_local_witnesses() -> None:
    result = resolve_runtime_deployment_mode(
        env={
            "OPENMATES_DEPLOYMENT_MODE": "official_cloud",
            "OPENMATES_CLOUD_OVERLAY_ENABLED": "true",
            "OPENMATES_CLOUD_OVERLAY_PACKAGE": "OpenMatesCloud",
            "SERVER_ENVIRONMENT": "production",
        },
        allowed_domain="example.org",
        hosting_domain="api.example.org",
        overlay_importable=True,
    )

    assert result.effective_mode == "official_cloud"
    assert result.environment == "production"
    assert result.status == "valid"
    assert result.billing_enabled is True

    checks = {check.id: check for check in build_check_inventory("core", result)}
    assert checks["billing.workers_registered"].timeout_seconds == CELERY_PROBE_CHECK_TIMEOUT_SECONDS


def test_self_host_inventory_never_contains_billing_checks() -> None:
    mode = resolve_runtime_deployment_mode(
        env={"OPENMATES_DEPLOYMENT_MODE": "self_host"},
        allowed_domain=None,
        hosting_domain=None,
        overlay_importable=False,
    )

    ids = {check.id for check in build_check_inventory("core", mode)}

    assert "core.chat_plumbing" in ids
    assert not any(check_id.startswith("billing.") for check_id in ids)


def test_role_inventory_is_stable_and_bounded() -> None:
    mode = resolve_runtime_deployment_mode(
        env={"OPENMATES_DEPLOYMENT_MODE": "self_host"},
        allowed_domain=None,
        hosting_domain=None,
        overlay_importable=False,
    )

    expected = {
        "core": {"compose.required_services", "http.role_health", "core.database", "core.cache", "core.vault", "core.worker_queue", "core.scheduler_freshness", "core.chat_plumbing"},
        "upload": {"compose.required_services", "http.role_health", "core.vault", "upload.antivirus"},
        "preview": {"compose.required_services", "http.role_health", "preview.renderer"},
    }

    for role, required_ids in expected.items():
        checks = build_check_inventory(role, mode)
        assert required_ids <= {check.id for check in checks}
        assert all(0 < check.timeout_seconds <= GLOBAL_DEADLINE_SECONDS for check in checks)

    core_checks = {check.id: check for check in build_check_inventory("core", mode)}
    assert core_checks["core.scheduler_freshness"].timeout_seconds == CELERY_PROBE_CHECK_TIMEOUT_SECONDS
    assert core_checks["core.scheduler_freshness"].timeout_seconds > CELERY_PROBE_RESULT_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_global_deadline_identifies_and_cancels_unfinished_checks() -> None:
    cleanup_ran = asyncio.Event()

    async def hangs() -> None:
        try:
            await asyncio.sleep(60)
        finally:
            cleanup_ran.set()

    results = await execute_checks(
        [CheckDefinition(id="core.chat_plumbing", timeout_seconds=60, runner=hangs)],
        global_deadline_seconds=0.01,
    )

    assert results[0].status == "failed"
    assert results[0].failure_class == "timeout"
    assert cleanup_ran.is_set()


def test_verifier_source_has_no_paid_provider_path() -> None:
    import backend.scripts.runtime_health_verifier as verifier

    forbidden = {
        "check_all_providers",
        "_get_provider_client",
        "ask_skill",
        "PaymentIntent.create",
        "Checkout.Session.create",
    }
    source = verifier.__loader__.get_source(verifier.__name__)  # type: ignore[union-attr]

    assert source is not None
    assert all(marker not in source for marker in forbidden)


def test_chat_plumbing_uses_a_distinct_provider_free_transport_probe() -> None:
    import backend.scripts.runtime_health_verifier as verifier

    verifier_source = verifier.__loader__.get_source(verifier.__name__)  # type: ignore[union-attr]
    task_source = (Path(__file__).parents[1] / "apps/ai/tasks/runtime_health_probe_task.py").read_text(encoding="utf-8")

    assert verifier_source is not None
    assert 'task_name = "runtime_health.chat_plumbing_probe"' in verifier_source
    assert 'task_name = "runtime_health.worker_probe"' in verifier_source
    assert "runtime_health:chat_plumbing:" in task_source
    assert "client.delete(key)" in task_source


def test_chat_plumbing_task_round_trips_and_cleans_up_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    values: dict[str, str] = {}

    class FakeApp:
        def task(self, *, name: str):
            calls.append(("task", name))
            return lambda function: function

    class FakeRedisClient:
        def set(self, key: str, value: str, *, ex: int) -> None:
            calls.append(("set", key, value, ex))
            values[key] = value

        def get(self, key: str) -> str | None:
            calls.append(("get", key))
            return values.get(key)

        def delete(self, key: str) -> None:
            calls.append(("delete", key))
            values.pop(key, None)

        def close(self) -> None:
            calls.append(("close",))

    fake_redis_module = SimpleNamespace(Redis=SimpleNamespace(from_url=lambda *args, **kwargs: FakeRedisClient()))
    fake_celery_module = SimpleNamespace(app=FakeApp())
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", fake_celery_module)

    path = Path(__file__).parents[1] / "apps/ai/tasks/runtime_health_probe_task.py"
    spec = importlib.util.spec_from_file_location("runtime_health_probe_task_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.runtime_health_chat_plumbing_probe("probe-1")

    key = "runtime_health:chat_plumbing:probe-1"
    assert result["transport"] == "redis"
    assert result["cleanup_status"] == "completed"
    assert ("set", key, "probe-1", 30) in calls
    assert ("delete", key) in calls
    assert ("close",) in calls
    assert values == {}


@pytest.mark.asyncio
async def test_chat_plumbing_verifier_rejects_malformed_probe_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.scripts.runtime_health_verifier as verifier

    class FakeResult:
        def get(self, **_kwargs):
            return {"probe_id": "wrong", "transport": "redis", "cleanup_status": "completed"}

        def forget(self) -> None:
            return None

    fake_app = SimpleNamespace(send_task=lambda *args, **kwargs: FakeResult())
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.tasks.celery_config",
        SimpleNamespace(app=fake_app),
    )

    with pytest.raises(RuntimeError, match="chat_plumbing_probe_mismatch"):
        await verifier._check_chat_plumbing()


@pytest.mark.asyncio
async def test_stripe_account_read_initializes_vault_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.scripts.runtime_health_verifier as verifier
    from backend.core.api.app.utils import secrets_manager as secrets_module

    calls: list[object] = []

    class FakeRequestsClient:
        def __init__(self, *, timeout: int):
            calls.append(("timeout", timeout))

        def close(self) -> None:
            calls.append("close")

    fake_stripe = SimpleNamespace(api_key=None, default_http_client=None, RequestsClient=FakeRequestsClient)

    class FakeAccount:
        @staticmethod
        def retrieve() -> None:
            calls.append(("retrieve", fake_stripe.api_key))

    fake_stripe.Account = FakeAccount

    class FakeSecretsManager:
        async def initialize(self) -> bool:
            calls.append("initialize")
            return True

        async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True) -> str:
            calls.append((secret_path, secret_key, log_missing))
            return "sk_test_runtime_health"

    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)
    monkeypatch.setattr(secrets_module, "SecretsManager", FakeSecretsManager)
    monkeypatch.setattr(verifier, "resolve_runtime_deployment_mode", lambda: SimpleNamespace(environment="production"))

    await _check_stripe_account_read()

    assert "initialize" in calls
    assert ("kv/data/providers/stripe", "production_secret_key", True) in calls
    assert ("timeout", 10) in calls
    assert ("retrieve", "sk_test_runtime_health") in calls
    assert "close" in calls


@pytest.mark.asyncio
async def test_billing_webhook_uses_environment_specific_vault_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.scripts.runtime_health_verifier as verifier
    from backend.core.api.app.utils import secrets_manager as secrets_module

    calls: list[object] = []

    class FakeSecretsManager:
        async def initialize(self) -> bool:
            calls.append("initialize")
            return True

        async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True) -> str:
            calls.append((secret_path, secret_key, log_missing))
            return "whsec_test_runtime_health"

    monkeypatch.setattr(secrets_module, "SecretsManager", FakeSecretsManager)
    monkeypatch.setattr(verifier, "resolve_runtime_deployment_mode", lambda: SimpleNamespace(environment="production"))

    await _check_billing_webhook()

    assert "initialize" in calls
    assert ("kv/data/providers/stripe", "production_webhook_secret", False) in calls
