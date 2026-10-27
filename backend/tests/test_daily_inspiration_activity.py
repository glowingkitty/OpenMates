"""Activity gates execute real task functions with no services or paid providers."""

import ast
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from backend.shared.python_utils.e2e_user_detection import is_non_production_e2e_user_profile


NOW = 200_000
USER_ID = "activity-test-user"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def task_functions(monkeypatch):
    """Avoid Celery's service graph while compiling the unchanged task functions."""
    monkeypatch.setattr(time, "time", lambda: NOW)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    source = ROOT / "backend/core/api/app/tasks/daily_inspiration_tasks.py"
    names = {
        "_is_first_run_done", "_load_inspiration_user_profile",
        "_should_skip_e2e_inspiration_user", "trigger_first_run_inspirations",
        "_generate_daily_inspirations_async",
    }
    nodes = [node for node in ast.parse(source.read_text()).body
             if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    namespace = {
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        "BaseServiceTask": Any, "logger": logging.getLogger(__name__),
        "time": time, "asyncio": SimpleNamespace(sleep=AsyncMock()),
        "DAILY_VIDEO_COUNT": 3, "_FIRST_RUN_FLAG_KEY_PREFIX": "daily_inspiration_first_run_done:",
        "is_non_production_e2e_user_profile": is_non_production_e2e_user_profile,
        "generate_and_deliver_inspirations_for_user": AsyncMock(return_value=True),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


class CacheDouble:
    """Only the activity/cache boundary is mocked; generation is a paid-call spy."""

    def __init__(self, paid_data, views=1, done=False, e2e=False):
        self.redis = SimpleNamespace(
            scan=AsyncMock(return_value=(0, [f"daily_inspiration_last_paid_request:{USER_ID}".encode()])),
            get=AsyncMock(return_value="1" if done else None),
        )
        self.get_client = AsyncMock(return_value=self.redis)
        self.get_inspiration_paid_request_data = AsyncMock(return_value=paid_data)
        self.get_viewed_inspiration_count = AsyncMock(return_value=views)
        self.get_user_by_id = AsyncMock(return_value={
            "email": "openmates-e2e@example.invalid" if e2e else "person@example.invalid",
        })

    @property
    def client(self):
        return self.get_client()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "age,views,e2e,expected",
    [
        (None, 1, False, False),
        (86401, 1, False, False),
        (86400, 1, False, False),
        (10, 0, False, False),
        (86399, 1, False, True),
        (10, 1, True, False),
    ],
    ids=["missing", "stale", "exact-24h", "zero-views", "eligible", "e2e"],
)
# contract-test: supporting surface=rest_api assertions=daily-inspiration.personalized-priority
async def test_scheduled_generation_requires_recent_activity_and_views(task_functions, age, views, e2e, expected):
    paid_data = None if age is None else {"last_paid_request_timestamp": NOW - age, "language": "de"}
    cache = CacheDouble(paid_data, views=views, e2e=e2e)
    task = SimpleNamespace(
        initialize_services=AsyncMock(), _cache_service=cache,
        _secrets_manager=object(), _directus_service=None,
    )
    result = await task_functions["_generate_daily_inspirations_async"](task)
    generate = task_functions["generate_and_deliver_inspirations_for_user"]
    assert result["processed"] == int(expected)
    assert result["skipped"] == int(not expected)
    assert result["errors"] == 0
    if expected:
        generate.assert_awaited_once()
        assert generate.await_args.kwargs["user_id"] == USER_ID
        assert generate.await_args.kwargs["language"] == "de"
    else:
        generate.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=daily-inspiration.personalized-priority
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "age,done,e2e,expected",
    [(10, False, False, True), (86399, False, False, True),
     (86400, False, False, False), (86401, False, False, False),
     (None, False, False, False), (10, True, False, False), (10, False, True, False)],
    ids=["recent-no-views", "recent-boundary", "exact-24h", "stale", "no-activity", "already-done", "e2e"],
)
async def test_first_run_requires_recent_activity_but_not_views(task_functions, age, done, e2e, expected):
    paid_data = None if age is None else {"last_paid_request_timestamp": NOW - age}
    cache = CacheDouble(paid_data, views=0, done=done, e2e=e2e)
    await task_functions["trigger_first_run_inspirations"](USER_ID, cache, object())
    generate = task_functions["generate_and_deliver_inspirations_for_user"]
    if expected:
        generate.assert_awaited_once()
    else:
        generate.assert_not_awaited()
    cache.get_viewed_inspiration_count.assert_not_awaited()
    if done:
        cache.get_inspiration_paid_request_data.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=daily-inspiration.personalized-priority
@pytest.mark.asyncio
async def test_first_run_activity_cache_failure_skips_generation(task_functions):
    cache = CacheDouble(None)
    cache.get_inspiration_paid_request_data.side_effect = ConnectionError("Cache unavailable")
    await task_functions["trigger_first_run_inspirations"](USER_ID, cache, object())
    task_functions["generate_and_deliver_inspirations_for_user"].assert_not_awaited()
