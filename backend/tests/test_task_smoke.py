# backend/tests/test_task_smoke.py
"""
Smoke tests for Celery task modules.

Verifies that task modules are importable, Celery tasks are properly registered,
and key constants have valid values. Catches broken imports, missing dependencies,
and configuration drift.

These tests run in CI where backend dependencies are installed.
They do NOT start a Celery broker — they only verify module-level setup.
"""

import asyncio
from contextlib import nullcontext
# contract-test-file: tooling
# Most checks validate task imports and deployment wiring; health behavior below
# carries its own product assertion mapping.
import importlib
import pytest

pytest.importorskip("celery", reason="Celery task smoke tests require backend task dependencies")


# ---------------------------------------------------------------------------
# Task modules to test: (module_path, expected_task_names, expected_constants)
# ---------------------------------------------------------------------------

TASK_MODULES = [
    {
        "module": "backend.core.api.app.tasks.storage_billing_tasks",
        "tasks": ["run_storage_billing"],
        "constants": {
            "FREE_BYTES": {"type": int, "min": 1},
            "CREDITS_PER_GB_PER_WEEK": {"type": int, "min": 1},
        },
    },
    {
        "module": "backend.core.api.app.tasks.auto_delete_tasks",
        "tasks": ["auto_delete_old_chats", "auto_delete_old_issues"],
        "constants": {
            "MAX_CHATS_PER_USER_PER_RUN": {"type": int, "min": 1},
        },
    },
    {
        "module": "backend.core.api.app.tasks.health_check_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.leaderboard_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.daily_inspiration_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.server_stats_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.usage_archive_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.user_cache_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.push_notification_task",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.persistence_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.app_analytics_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.web_analytics_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.software_update_tasks",
        "tasks": [],
        "constants": {},
    },
    {
        "module": "backend.core.api.app.tasks.user_metrics",
        "tasks": [],
        "constants": {},
    },
]


class TestTaskImports:
    """Verify all task modules are importable (catches broken import chains)."""

    @pytest.mark.parametrize(
        "module_path",
        [m["module"] for m in TASK_MODULES],
        ids=[m["module"].split(".")[-1] for m in TASK_MODULES],
    )
    def test_module_importable(self, module_path: str):
        """Each task module should import without errors."""
        mod = importlib.import_module(module_path)
        assert mod is not None


class TestTaskConstants:
    """Verify critical task constants have expected types and ranges."""

    def test_storage_billing_free_bytes(self):
        mod = importlib.import_module("backend.core.api.app.tasks.storage_billing_tasks")
        assert isinstance(mod.FREE_BYTES, int)
        assert mod.FREE_BYTES == 1_073_741_824, "FREE_BYTES should be 1 GB"

    def test_storage_billing_credits_per_gb(self):
        mod = importlib.import_module("backend.core.api.app.tasks.storage_billing_tasks")
        assert isinstance(mod.CREDITS_PER_GB_PER_WEEK, int)
        assert mod.CREDITS_PER_GB_PER_WEEK > 0

    def test_auto_delete_max_chats_per_run(self):
        mod = importlib.import_module("backend.core.api.app.tasks.auto_delete_tasks")
        assert isinstance(mod.MAX_CHATS_PER_USER_PER_RUN, int)
        assert mod.MAX_CHATS_PER_USER_PER_RUN > 0


class TestBaseServiceTask:
    """Verify BaseServiceTask class hierarchy and contract."""

    def test_inherits_from_celery_task(self):
        from celery import Task
        from backend.core.api.app.tasks.base_task import BaseServiceTask
        assert issubclass(BaseServiceTask, Task)

    def test_has_initialize_services_method(self):
        import asyncio
        from backend.core.api.app.tasks.base_task import BaseServiceTask
        assert hasattr(BaseServiceTask, "initialize_services")
        assert asyncio.iscoroutinefunction(BaseServiceTask.initialize_services)

    def test_has_cleanup_services_method(self):
        import asyncio
        from backend.core.api.app.tasks.base_task import BaseServiceTask
        assert hasattr(BaseServiceTask, "cleanup_services")
        assert asyncio.iscoroutinefunction(BaseServiceTask.cleanup_services)

    def test_service_properties_defined(self):
        from backend.core.api.app.tasks.base_task import BaseServiceTask
        expected_properties = [
            "directus_service",
            "encryption_service",
            "s3_service",
            "cache_service",
            "secrets_manager",
            "translation_service",
            "payment_service",
        ]
        for prop_name in expected_properties:
            assert hasattr(BaseServiceTask, prop_name), f"Missing property: {prop_name}"

    def test_drops_stale_loop_bound_services(self):
        import asyncio
        from backend.core.api.app.tasks.base_task import BaseServiceTask

        stale_loop = asyncio.new_event_loop()
        current_loop = asyncio.new_event_loop()
        task = BaseServiceTask()
        marker = object()
        try:
            task._service_loop = stale_loop
            task._cache_service = marker
            task._directus_service = marker
            task._secrets_manager = marker
            task._encryption_service = marker

            task._drop_loop_bound_services_for_new_loop(current_loop)

            assert task._service_loop is current_loop
            assert task._cache_service is None
            assert task._directus_service is None
            assert task._secrets_manager is None
            assert task._encryption_service is None
        finally:
            stale_loop.close()
            current_loop.close()


class TestCeleryConfig:
    """Verify Celery app configuration."""

    def test_celery_app_exists(self):
        from backend.core.api.app.tasks.celery_config import app
        assert app is not None
        assert app.main == "backend.core.api.app.tasks.celery_config" or app.main is not None

    def test_ai_response_notification_email_task_registered(self):
        from backend.core.api.app.tasks.celery_config import app
        import backend.core.api.app.tasks.email_tasks  # noqa: F401

        assert "app.tasks.email_tasks.ai_response_notification_email_task.send_ai_response_notification" in app.tasks


class TestAppHealthChecks:
    # contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
    def test_provider_probe_prefers_configured_available_model_over_cheaper_catalog_entry(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks
        from types import SimpleNamespace

        monkeypatch.setattr(health_check_tasks, "config_manager", SimpleNamespace(
            get_provider_configs=lambda: {"models": {"models": [
                {"id": "dedicated-only", "servers": [{"id": "together"}],
                 "costs": {"input_per_million_token": {"price": 0.95}}},
                {"id": "available", "servers": [{"id": "together", "health_check_preferred": True}],
                 "costs": {"input_per_million_token": {"price": 2.10}}},
            ]}},
        ))
        assert health_check_tasks._get_cheapest_model_for_server("together") == "models/available"

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
    def test_groq_health_probe_selects_configured_model(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks
        from types import SimpleNamespace

        monkeypatch.setattr(health_check_tasks, "config_manager", SimpleNamespace(
            get_provider_configs=lambda: {"openai": {"models": [
                {"id": "gpt-oss-safeguard-20b", "servers": [{"id": "groq"}],
                 "costs": {"input_per_million_token": {"price": 0.075}}},
            ]}},
        ))
        assert health_check_tasks._get_cheapest_model_for_server("groq") == "openai/gpt-oss-safeguard-20b"

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
    def test_groq_health_probe_calls_selected_server_and_model(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks
        from types import SimpleNamespace

        calls = []

        async def client(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(success=True)

        def get_client(server):
            assert server == "groq"
            return client

        monkeypatch.setattr(health_check_tasks, "_get_provider_client", get_client)
        monkeypatch.setattr(health_check_tasks, "config_manager", SimpleNamespace(
            get_provider_configs=lambda: {"openai": {"models": [
                {"id": "gpt-oss-safeguard-20b", "default_server": "openrouter", "servers": [
                    {"id": "groq", "model_id": "openai/gpt-oss-safeguard-20b"},
                    {"id": "openrouter", "model_id": "another-model"},
                ]},
            ]}},
        ))
        success, error, elapsed = asyncio.run(health_check_tasks._check_provider_via_test_request(
            "groq", "openai/gpt-oss-safeguard-20b", object(),
        ))
        assert success is True and error is None and elapsed is not None
        assert calls[0]["model_id"] == "openai/gpt-oss-safeguard-20b"
        assert calls[0]["stream"] is False

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.providers.current-availability
    def test_provider_consecutive_failures_survive_cache_and_reset_on_recovery(self, monkeypatch):
        import json
        from backend.core.api.app.tasks import health_check_tasks

        stored = {}

        class Cache:
            @property
            async def client(self):
                return self

            async def get(self, key):
                return stored.get(key)

            async def set(self, key, value, **kwargs):
                stored[key] = value

            async def close(self):
                pass

        class Secrets:
            async def initialize(self):
                return True

            async def close(self):
                pass

        results = iter([(False, "Request timeout", 1.0)] * 3 + [(True, None, 1.0)])

        async def probe(*args):
            return next(results)

        async def record(**kwargs):
            pass

        monkeypatch.setattr(health_check_tasks, "CacheService", Cache)
        monkeypatch.setattr(health_check_tasks, "SecretsManager", Secrets)
        monkeypatch.setattr(health_check_tasks, "_get_cheapest_model_for_server", lambda server: "openai/test")
        monkeypatch.setattr(health_check_tasks, "_check_provider_via_test_request", probe)
        monkeypatch.setattr(health_check_tasks, "_record_health_event_if_changed", record)
        for count, status in [(1, "healthy"), (2, "healthy"), (3, "unhealthy"), (0, "healthy")]:
            data = asyncio.run(health_check_tasks._check_provider_health("groq"))
            assert data["status"] == status
            assert json.loads(stored["health_check:provider:groq"])["consecutive_failures"] == count

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.billing.no-spend-readiness
    def test_payment_route_probe_uses_authenticated_health_endpoint(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks
        import httpx

        monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-service-token")

        def handler(request):
            assert str(request.url) == "http://api:8000/internal/health/payments"
            assert request.headers["X-Internal-Service-Token"] == "test-service-token"
            return httpx.Response(200, json={"routes_registered": True})

        client_type = httpx.AsyncClient
        monkeypatch.setattr(health_check_tasks.httpx, "AsyncClient", lambda **kwargs: client_type(
            transport=httpx.MockTransport(handler), **kwargs,
        ))
        assert asyncio.run(health_check_tasks._stripe_payment_route_registered()) is True

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_worker_queue_names_follow_task_config(self):
        from backend.core.api.app.tasks.health_check_tasks import _get_app_worker_queue_names

        assert _get_app_worker_queue_names("models3d") == {"app_images"}
        assert _get_app_worker_queue_names("social_media") == {"app_social_media"}
        assert _get_app_worker_queue_names("videos") == {"app_videos"}
        assert _get_app_worker_queue_names("unknown_app") == {"app_unknown_app"}

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_worker_health_uses_shared_active_queue_snapshot(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks

        def fail_if_broadcasting():
            raise AssertionError("health checks should reuse the run-level worker queue snapshot")

        monkeypatch.setattr(health_check_tasks, "_inspect_active_worker_queues", fail_if_broadcasting)

        healthy, error = asyncio.run(
            health_check_tasks._check_app_worker_health(
                "videos",
                active_workers={"celery@worker": [{"name": "app_videos"}]},
            )
        )

        assert healthy is True
        assert error is None

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_worker_queue_inspection_waits_for_app_workers(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks
        from backend.core.api.app.tasks import celery_config

        observed = {}
        connections = []

        def fresh_connection():
            connection = object()
            connections.append(connection)
            return nullcontext(connection)

        monkeypatch.setattr(celery_config.app, "connection_for_write", fresh_connection)

        class FakeControl:
            def __init__(self, *, app):
                assert app is celery_config.app
                observed.setdefault("controls", []).append(self)

            def broadcast(self, command, *, reply, timeout, connection):
                assert command == "active_queues"
                assert reply is True
                assert connection is connections[-1]
                observed["timeout"] = timeout
                return [{"celery@app-worker": [{"name": "app_videos"}]}]

        monkeypatch.setattr("celery.app.control.Control", FakeControl)

        assert health_check_tasks._inspect_active_worker_queues() == {
            "celery@app-worker": [{"name": "app_videos"}]
        }
        assert observed["timeout"] == health_check_tasks.CELERY_WORKER_INSPECT_TIMEOUT_SECONDS
        health_check_tasks._inspect_active_worker_queues()
        assert len(observed["controls"]) == 2
        assert observed["controls"][0] is not observed["controls"][1]
        assert len(connections) == 2
        assert connections[0] is not connections[1]

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_empty_shared_snapshot_does_not_trigger_per_app_broadcasts(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks

        def fail_if_broadcasting():
            raise AssertionError("an empty run-level snapshot must still be reused")

        monkeypatch.setattr(health_check_tasks, "_inspect_active_worker_queues", fail_if_broadcasting)
        assert asyncio.run(health_check_tasks._check_app_worker_health("videos", active_workers={})) == (
            False, "No active Celery workers found",
        )

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_missing_app_queue_is_reported_as_no_worker(self):
        from backend.core.api.app.tasks import health_check_tasks

        assert asyncio.run(health_check_tasks._check_app_worker_health(
            "videos", active_workers={"celery@core-worker": [{"name": "health_check"}]},
        )) == (False, "no_worker")

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_worker_queue_inspection_retries_and_merges_partial_replies(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks

        snapshots = iter([
            {"celery@task-worker": [{"name": "health_check"}]},
            {"celery@app-worker": [{"name": "app_videos"}]},
        ])
        monkeypatch.setattr(
            health_check_tasks,
            "_inspect_active_worker_queues",
            lambda: next(snapshots),
        )

        active_workers = asyncio.run(
            health_check_tasks._inspect_active_worker_queues_with_retry(["videos"])
        )

        assert active_workers == {
            "celery@task-worker": [{"name": "health_check"}],
            "celery@app-worker": [{"name": "app_videos"}],
        }

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_worker_queue_inspection_reports_incomplete_empty_first_reply(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks

        warnings = []
        monkeypatch.setattr(health_check_tasks.logger, "warning", lambda message, *args: warnings.append(message % args))
        snapshots = iter([
            {},
            {"celery@core-worker": [{"name": "health_check"}]},
        ])
        monkeypatch.setattr(health_check_tasks, "_inspect_active_worker_queues", lambda: next(snapshots))

        active_workers = asyncio.run(
            health_check_tasks._inspect_active_worker_queues_with_retry(["videos"])
        )

        assert active_workers == {"celery@core-worker": [{"name": "health_check"}]}
        assert any("remained incomplete after retry; missing queues ['app_videos']" in warning for warning in warnings)

    # contract-test: supporting surface=rest_api assertions=operational-monitoring.alerts.actionable-low-noise
    def test_worker_queue_retry_keeps_earlier_nonempty_reply(self, monkeypatch):
        from backend.core.api.app.tasks import health_check_tasks

        snapshots = iter([
            {"celery@app-worker": [{"name": "app_videos"}]},
            {"celery@app-worker": [], "celery@other": [{"name": "app_music"}]},
        ])
        monkeypatch.setattr(health_check_tasks, "_inspect_active_worker_queues", lambda: next(snapshots))

        active_workers = asyncio.run(
            health_check_tasks._inspect_active_worker_queues_with_retry(["videos", "music"])
        )

        assert health_check_tasks._active_queue_names(active_workers) == {"app_videos", "app_music"}


class TestLeaderboardCache:
    def test_cached_leaderboard_accepts_deserialized_mapping(self, monkeypatch):
        from backend.core.api.app.tasks import leaderboard_tasks

        expected = {"rankings": [{"model": "example"}]}

        class FakeCacheService:
            async def get(self, key):
                assert key == leaderboard_tasks.LEADERBOARD_CACHE_KEY
                return expected

            async def close(self):
                return None

        monkeypatch.setattr(leaderboard_tasks, "CacheService", FakeCacheService)

        assert asyncio.run(leaderboard_tasks._get_cached_leaderboard_async()) == expected
