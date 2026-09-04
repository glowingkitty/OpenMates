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

import httpx
import pytest

from backend.core.api.app.utils.server_mode import resolve_runtime_deployment_mode
from backend.scripts.runtime_health_verifier import (
    CELERY_PROBE_CHECK_TIMEOUT_SECONDS,
    CELERY_PROBE_RESULT_TIMEOUT_SECONDS,
    BASELINE_HTTP_PROBE_ATTEMPTS,
    GLOBAL_DEADLINE_SECONDS,
    HTTP_PROBE_RETRY_DELAY_SECONDS,
    HTTP_PROBE_TIMEOUT_SECONDS,
    STRIPE_REQUEST_TIMEOUT_SECONDS,
    CheckDefinition,
    _check_object_storage,
    _check_billing_routes,
    _check_billing_workers,
    _check_billing_webhook,
    _check_vault,
    _http_get,
    _check_stripe_account_read,
    build_check_inventory,
    execute_checks,
    run_verifier,
)


def test_directus_upload_storage_preserves_bind_mount_and_drops_root_privileges() -> None:
    compose_source = (Path(__file__).parents[1] / "core/docker-compose.yml").read_text(encoding="utf-8")
    dockerfile_source = (Path(__file__).parents[1] / "core/directus/Dockerfile").read_text(encoding="utf-8")

    assert "- ./directus/uploads:/directus/uploads" in compose_source
    assert 'test: ["CMD", "su-exec", "node:node", "/usr/local/bin/openmates-directus-health"]' in compose_source
    assert "chown node:node /directus/uploads" in dockerfile_source
    assert "apk add --no-cache curl postgresql-client su-exec" in dockerfile_source
    assert "exec su-exec node:node /usr/local/bin/openmates-directus-start" in dockerfile_source


# contract-test: direct surface=cli assertions=storage-resilience.monitoring.transition-alerts,storage-resilience.monitoring.not-configured
def test_core_inventory_includes_optional_bounded_object_storage() -> None:
    mode = SimpleNamespace(billing_enabled=False)

    storage_check = next(
        check for check in build_check_inventory("core", mode)
        if check.id == "core.object_storage"
    )

    assert storage_check.required is False
    assert storage_check.timeout_seconds <= 10


# contract-test: direct surface=cli assertions=storage-resilience.monitoring.not-configured,storage-resilience.content.privacy-boundary
@pytest.mark.asyncio
async def test_object_storage_reports_not_configured_without_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.scripts.runtime_health_verifier as verifier

    class FakeStorage:
        def __init__(self, *, secrets_manager: object):
            assert secrets_manager is not None

        async def initialize(self, *, configure_buckets: bool) -> None:
            assert configure_buckets is False

        async def check_availability(self) -> str:
            return "not_configured"

    async def fake_secrets_manager() -> object:
        return object()

    monkeypatch.setattr(verifier, "_storage_service_type", lambda: FakeStorage)
    monkeypatch.setattr(verifier, "_initialized_secrets_manager", fake_secrets_manager)

    result = await execute_checks([
        CheckDefinition("core.object_storage", 1, _check_object_storage, required=False)
    ])

    assert result[0].status == "skipped"
    assert result[0].failure_class == "not_configured"
    assert result[0].sanitized_reason == "not_configured"


# contract-test: direct surface=cli assertions=storage-resilience.monitoring.transition-alerts,storage-resilience.content.privacy-boundary
@pytest.mark.asyncio
async def test_object_storage_failure_is_sanitized_and_does_not_fail_core(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.scripts.runtime_health_verifier as verifier

    class FakeStorage:
        def __init__(self, *, secrets_manager: object):
            assert secrets_manager is not None

        async def initialize(self, *, configure_buckets: bool) -> None:
            assert configure_buckets is False

        async def check_availability(self) -> str:
            return "unavailable"

    async def fake_secrets_manager() -> object:
        return object()

    monkeypatch.setattr(verifier, "_storage_service_type", lambda: FakeStorage)
    monkeypatch.setattr(verifier, "_initialized_secrets_manager", fake_secrets_manager)
    async def passing_baseline() -> None:
        return None

    monkeypatch.setattr(verifier, "build_check_inventory", lambda _role, _mode: [
        CheckDefinition("compose.required_services", 1),
        CheckDefinition("core.object_storage", 1, required=False)
    ])
    monkeypatch.setattr(verifier, "_runtime_runners", lambda _role: {
        "compose.required_services": passing_baseline,
        "core.object_storage": _check_object_storage,
    })

    result = await run_verifier("core")

    assert result["status"] == "passed"
    storage_result = next(check for check in result["checks"] if check["id"] == "core.object_storage")
    assert storage_result["status"] == "failed"
    assert storage_result["failure_class"] == "storage_unavailable"
    assert storage_result["sanitized_reason"] == "check_failed"


@pytest.mark.asyncio
async def test_billing_route_discovery_probes_a_private_live_route(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []
    observed_timeouts: list[int] = []

    class FakeResponse:
        status_code = 401

        def raise_for_status(self) -> None:
            raise AssertionError("accepted private billing status must not raise")

    class FakeClient:
        def __init__(self, *, timeout: int, follow_redirects: bool):
            observed_timeouts.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            return FakeResponse()

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(verifier.httpx, "AsyncClient", FakeClient)

    await _check_billing_routes()

    assert requested_urls == ["http://localhost:8000/v1/payments/subscription"]
    assert observed_timeouts == [HTTP_PROBE_TIMEOUT_SECONDS]


@pytest.mark.asyncio
@pytest.mark.parametrize("probe_error", [httpx.ReadTimeout("synthetic timeout"), httpx.ConnectError("synthetic connect error")])
async def test_http_probe_retries_one_transient_transport_error(monkeypatch: pytest.MonkeyPatch, probe_error: httpx.TransportError) -> None:
    requested_urls: list[str] = []
    observed_timeouts: list[int] = []
    observed_sleeps: list[float] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *, timeout: int, follow_redirects: bool):
            observed_timeouts.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            if len(requested_urls) == 1:
                raise probe_error
            return FakeResponse()

    async def fake_sleep(delay: float) -> None:
        observed_sleeps.append(delay)

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(verifier.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(verifier.asyncio, "sleep", fake_sleep)

    await _http_get("http://localhost:8000/v1/health", attempts=2)

    assert requested_urls == ["http://localhost:8000/v1/health", "http://localhost:8000/v1/health"]
    assert observed_timeouts == [HTTP_PROBE_TIMEOUT_SECONDS, HTTP_PROBE_TIMEOUT_SECONDS]
    assert observed_sleeps == [HTTP_PROBE_RETRY_DELAY_SECONDS]


@pytest.mark.asyncio
async def test_http_probe_enforces_total_attempt_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowClient:
        def __init__(self, **_kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url: str):
            await asyncio.sleep(60)

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(verifier, "HTTP_PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(verifier.httpx, "AsyncClient", SlowClient)

    with pytest.raises(TimeoutError):
        await verifier._http_get("http://localhost:8000/v1/health")


@pytest.mark.asyncio
async def test_http_probe_retries_outer_total_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []
    observed_sleeps: list[float] = []
    original_sleep = asyncio.sleep

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    class SlowThenFastClient:
        def __init__(self, **_kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            if len(requested_urls) == 1:
                await original_sleep(60)
            return FakeResponse()

    async def fake_sleep(delay: float) -> None:
        observed_sleeps.append(delay)

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(verifier, "HTTP_PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(verifier.httpx, "AsyncClient", SlowThenFastClient)
    monkeypatch.setattr(verifier.asyncio, "sleep", fake_sleep)

    await verifier._http_get("http://localhost:8000/v1/health", attempts=2)

    assert requested_urls == ["http://localhost:8000/v1/health", "http://localhost:8000/v1/health"]
    assert observed_sleeps == [HTTP_PROBE_RETRY_DELAY_SECONDS]


@pytest.mark.asyncio
async def test_vault_probe_retries_transient_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        status_code = 429

        def raise_for_status(self) -> None:
            raise AssertionError("accepted Vault standby status must not raise")

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            requested_urls.append(url)
            if len(requested_urls) == 1:
                raise httpx.ConnectError("synthetic connect error")
            return FakeResponse()

    async def fake_sleep(_delay: float) -> None:
        return None

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setenv("VAULT_URL", "http://vault.local:8200")
    monkeypatch.setattr(verifier.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(verifier.asyncio, "sleep", fake_sleep)

    await _check_vault()

    assert requested_urls == ["http://vault.local:8200/v1/sys/health", "http://vault.local:8200/v1/sys/health"]


@pytest.mark.asyncio
async def test_vault_probe_rejects_unaccepted_redirect_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 302

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **_kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url: str):
            return FakeResponse()

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(verifier.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="unexpected_http_status"):
        await _check_vault()


@pytest.mark.asyncio
async def test_stripe_account_check_uses_bounded_direct_http(monkeypatch: pytest.MonkeyPatch) -> None:
    requests_seen: list[tuple[str, dict[str, str]]] = []
    observed_timeouts: list[int] = []
    original_import = builtins.__import__

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *, timeout: int, follow_redirects: bool):
            observed_timeouts.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str, *, headers: dict[str, str]):
            requests_seen.append((url, headers))
            return FakeResponse()

    def reject_stripe_import(name: str, *args, **kwargs):
        if name == "stripe":
            raise AssertionError("runtime health should not mutate or import Stripe SDK globals")
        return original_import(name, *args, **kwargs)

    class FakeSecretsManager:
        async def get_secret(self, *_args, **_kwargs):
            return "synthetic-key"

    async def initialized_secrets_manager():
        return FakeSecretsManager()

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(builtins, "__import__", reject_stripe_import)
    monkeypatch.setattr(verifier.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(verifier, "_initialized_secrets_manager", initialized_secrets_manager)

    await _check_stripe_account_read()

    assert observed_timeouts == [10]
    assert requests_seen == [("https://api.stripe.com/v1/account", {"Authorization": "Bearer synthetic-key"})]


@pytest.mark.asyncio
async def test_stripe_account_check_enforces_total_request_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowClient:
        def __init__(self, **_kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url: str, *, headers: dict[str, str]):
            await asyncio.sleep(60)

    class FakeSecretsManager:
        async def get_secret(self, *_args, **_kwargs):
            return "synthetic-key"

    async def initialized_secrets_manager():
        return FakeSecretsManager()

    import backend.scripts.runtime_health_verifier as verifier

    monkeypatch.setattr(verifier, "STRIPE_REQUEST_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(verifier.httpx, "AsyncClient", SlowClient)
    monkeypatch.setattr(verifier, "_initialized_secrets_manager", initialized_secrets_manager)

    with pytest.raises(TimeoutError):
        await _check_stripe_account_read()

    assert STRIPE_REQUEST_TIMEOUT_SECONDS < 15


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
    assert HTTP_PROBE_TIMEOUT_SECONDS * BASELINE_HTTP_PROBE_ATTEMPTS + HTTP_PROBE_RETRY_DELAY_SECONDS < core_checks["http.role_health"].timeout_seconds


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
        def __init__(self, *, timeout: int, follow_redirects: bool):
            calls.append(("timeout", timeout))
            calls.append(("follow_redirects", follow_redirects))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            calls.append("close")
            return None

        async def get(self, url: str, *, headers: dict[str, str]):
            calls.append(("get", url, headers))

            class FakeResponse:
                def raise_for_status(self) -> None:
                    calls.append("raise_for_status")

            return FakeResponse()

    class FakeSecretsManager:
        async def initialize(self) -> bool:
            calls.append("initialize")
            return True

        async def get_secret(self, secret_path: str, secret_key: str, log_missing: bool = True) -> str:
            calls.append((secret_path, secret_key, log_missing))
            return "sk_test_runtime_health"

    monkeypatch.setattr(verifier.httpx, "AsyncClient", FakeRequestsClient)
    monkeypatch.setattr(secrets_module, "SecretsManager", FakeSecretsManager)
    monkeypatch.setattr(verifier, "resolve_runtime_deployment_mode", lambda: SimpleNamespace(environment="production"))

    await _check_stripe_account_read()

    assert "initialize" in calls
    assert ("kv/data/providers/stripe", "production_secret_key", True) in calls
    assert ("timeout", 10) in calls
    assert ("follow_redirects", False) in calls
    assert ("get", "https://api.stripe.com/v1/account", {"Authorization": "Bearer sk_test_runtime_health"}) in calls
    assert "raise_for_status" in calls
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
