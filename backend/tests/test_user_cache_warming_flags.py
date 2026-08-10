# backend/tests/test_user_cache_warming_flags.py
#
# Infrastructure regression tests for user cache warming handoff state.
# Chat sync can wait for a Redis primed flag while Celery warms encrypted chat
# metadata caches in the background. The temporary warming flag must never block
# future retry attempts after task completion or dispatch failure.

# contract-test-file: infrastructure

import importlib.util
from pathlib import Path
import sys
import types

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import phased_sync_handler


def _load_user_cache_tasks_module(monkeypatch):
    class _FakeCeleryApp:
        def task(self, *args, **kwargs):
            def decorator(function):
                return function

            return decorator

    stubs = {
        "backend.core.api.app.tasks.celery_config": {"app": _FakeCeleryApp()},
        "backend.core.api.app.services.directus.directus": {"DirectusService": object},
        "backend.core.api.app.services.cache": {"CacheService": object},
        "backend.core.api.app.utils.encryption": {"EncryptionService": object},
    }
    for module_name, attributes in stubs.items():
        module = types.ModuleType(module_name)
        for attribute_name, value in attributes.items():
            setattr(module, attribute_name, value)
        monkeypatch.setitem(sys.modules, module_name, module)

    module_path = Path(__file__).parents[1] / "core/api/app/tasks/user_cache_tasks.py"
    spec = importlib.util.spec_from_file_location("user_cache_tasks_flag_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_warm_user_cache_clears_warming_flag_on_success(monkeypatch) -> None:
    user_cache_tasks = _load_user_cache_tasks_module(monkeypatch)
    deleted_keys = []
    closed = []

    class FakeCache:
        async def delete(self, key):
            deleted_keys.append(key)
            return True

        async def close(self):
            closed.append(True)

    async def fake_async_warm_user_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(user_cache_tasks, "CacheService", FakeCache)
    monkeypatch.setattr(user_cache_tasks, "_async_warm_user_cache", fake_async_warm_user_cache)

    task_self = types.SimpleNamespace(request=types.SimpleNamespace(id="task-1"))

    assert user_cache_tasks.warm_user_cache(task_self, "user-1", None) is True
    assert deleted_keys == ["cache_warming_in_progress:user-1"]
    assert closed == [True]


def test_warm_user_cache_clears_warming_flag_on_failure(monkeypatch) -> None:
    user_cache_tasks = _load_user_cache_tasks_module(monkeypatch)
    deleted_keys = []
    closed = []

    class FakeCache:
        async def delete(self, key):
            deleted_keys.append(key)
            return True

        async def close(self):
            closed.append(True)

    async def fake_async_warm_user_cache(*args, **kwargs):
        raise RuntimeError("warm failed")

    monkeypatch.setattr(user_cache_tasks, "CacheService", FakeCache)
    monkeypatch.setattr(user_cache_tasks, "_async_warm_user_cache", fake_async_warm_user_cache)

    task_self = types.SimpleNamespace(request=types.SimpleNamespace(id="task-1"))

    assert user_cache_tasks.warm_user_cache(task_self, "user-1", None) is False
    assert deleted_keys == ["cache_warming_in_progress:user-1"]
    assert closed == [True]


@pytest.mark.anyio
async def test_sync_rewarm_clears_warming_flag_when_dispatch_fails(monkeypatch) -> None:
    set_keys = []
    deleted_keys = []

    class FakeCache:
        async def get(self, key):
            return None

        async def set(self, key, value, ttl=None):
            set_keys.append((key, value, ttl))
            return True

        async def delete(self, key):
            deleted_keys.append(key)
            return True

    class FakeCeleryApp:
        conf = types.SimpleNamespace(task_always_eager=False)

        def send_task(self, *args, **kwargs):
            raise RuntimeError("broker unavailable")

    fake_celery_config = types.ModuleType("backend.core.api.app.tasks.celery_config")
    fake_celery_config.app = FakeCeleryApp()
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.tasks.celery_config",
        fake_celery_config,
    )

    await phased_sync_handler._trigger_cache_rewarming_if_needed(FakeCache(), "user-1")

    assert set_keys == [("cache_warming_in_progress:user-1", "warming", 300)]
    assert deleted_keys == ["cache_warming_in_progress:user-1"]
