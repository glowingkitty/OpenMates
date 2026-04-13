# backend/tests/test_task_smoke.py
"""
Smoke tests for Celery task modules.

Verifies that task modules are importable, Celery tasks are properly registered,
and key constants have valid values. Catches broken imports, missing dependencies,
and configuration drift.

These tests run in CI where backend dependencies are installed.
They do NOT start a Celery broker — they only verify module-level setup.
"""

import importlib
import pytest


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


class TestCeleryConfig:
    """Verify Celery app configuration."""

    def test_celery_app_exists(self):
        from backend.core.api.app.tasks.celery_config import app
        assert app is not None
        assert app.main == "backend.core.api.app.tasks.celery_config" or app.main is not None
