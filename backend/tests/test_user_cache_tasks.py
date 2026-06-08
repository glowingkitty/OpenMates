# backend/tests/test_user_cache_tasks.py
#
# Regression coverage for cache warming helpers.
# Chat sync depends on user cache warming setting Redis primed flags.
# Old Directus rows can contain null version metadata; cache warming must log
# those rows and continue so users are not trapped in an endless sync-pending
# state while their chats still exist server-side.

import importlib.util
from pathlib import Path
import sys
import types


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
    spec = importlib.util.spec_from_file_location("user_cache_tasks_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cached_chat_versions_from_details_normalizes_null_versions(monkeypatch) -> None:
    user_cache_tasks = _load_user_cache_tasks_module(monkeypatch)
    chat_data = {"messages_v": None, "title_v": None}
    warnings = []

    monkeypatch.setattr(
        user_cache_tasks.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message % args),
    )

    versions = user_cache_tasks._cached_chat_versions_from_details(
        chat_data,
        user_id="user-1",
        chat_id="chat-1",
    )

    assert versions.messages_v == 0
    assert versions.title_v == 0
    assert any("[CACHE_WARMING_DATA_REPAIR]" in warning for warning in warnings)
    assert any("chat-1" in warning for warning in warnings)


def test_cached_chat_versions_from_details_keeps_valid_versions(monkeypatch) -> None:
    user_cache_tasks = _load_user_cache_tasks_module(monkeypatch)
    chat_data = {"messages_v": 4, "title_v": 2}

    versions = user_cache_tasks._cached_chat_versions_from_details(
        chat_data,
        user_id="user-1",
        chat_id="chat-1",
    )

    assert versions.messages_v == 4
    assert versions.title_v == 2


def test_effective_chat_timestamp_tolerates_nullable_directus_fields(monkeypatch) -> None:
    user_cache_tasks = _load_user_cache_tasks_module(monkeypatch)

    timestamp = user_cache_tasks._effective_chat_timestamp(
        {
            "last_edited_overall_timestamp": None,
            "updated_at": 20,
            "created_at": None,
        },
        draft_updated_at=None,
    )

    assert timestamp == 20


def test_effective_chat_timestamp_uses_draft_when_newer(monkeypatch) -> None:
    user_cache_tasks = _load_user_cache_tasks_module(monkeypatch)

    timestamp = user_cache_tasks._effective_chat_timestamp(
        {
            "last_edited_overall_timestamp": None,
            "updated_at": 20,
            "created_at": 10,
        },
        draft_updated_at=30,
    )

    assert timestamp == 30
