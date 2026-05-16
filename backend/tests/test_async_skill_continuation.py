# backend/tests/test_async_skill_continuation.py
#
# Unit tests for generic async skill continuation context.
# Long-running skills use this path after their worker task finishes so completed
# results can be interpreted by the normal AI ask pipeline instead of app-specific
# canned follow-up text.

import sys
import importlib.util
import time
from pathlib import Path
from types import ModuleType

import pytest

from backend.core.api.app.schemas.chat import AIHistoryMessage  # noqa: E402

_MODULE_PATH = Path(__file__).resolve().parents[1] / "apps" / "ai" / "tasks" / "async_skill_continuation.py"


@pytest.fixture
def async_skill_continuation(monkeypatch):
    celery_stub = ModuleType("celery")
    celery_stub.Celery = object
    monkeypatch.setitem(sys.modules, "celery", celery_stub)

    celery_exceptions_stub = ModuleType("celery.exceptions")
    celery_exceptions_stub.Ignore = Exception
    celery_exceptions_stub.SoftTimeLimitExceeded = TimeoutError
    monkeypatch.setitem(sys.modules, "celery.exceptions", celery_exceptions_stub)

    celery_states_stub = ModuleType("celery.states")
    celery_states_stub.REVOKED = "REVOKED"
    monkeypatch.setitem(sys.modules, "celery.states", celery_states_stub)

    spec = importlib.util.spec_from_file_location("async_skill_continuation_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeCache:
    def __init__(self):
        self.values = {}
        self.deleted = []

    async def set(self, key, value, ttl=None):
        self.values[key] = {"value": value, "ttl": ttl}
        return True

    async def get(self, key):
        entry = self.values.get(key)
        return entry["value"] if entry else None

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)
        return True


class _FakeTaskSignature:
    id = "continuation-task-1"


class _FakeCeleryApp:
    def __init__(self):
        self.sent = []

    def send_task(self, name, kwargs, queue):
        self.sent.append({"name": name, "kwargs": kwargs, "queue": queue})
        return _FakeTaskSignature()


def _request():
    from backend.apps.ai.skills.ask_skill import AskSkillRequest

    return AskSkillRequest(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="hash-1",
        message_history=[
            AIHistoryMessage(role="user", content="Search social media for privacy AI", created_at=1),
        ],
        chat_has_title=True,
        mate_id="mate-1",
        user_preferences={"language": "en"},
    )


def _skill_config_dict():
    return {
        "enable_auto_model_selection": False,
        "default_llms": {
            "preprocessing_model": "mistral/small",
            "main_processing_simple": "google/gemini-flash",
            "main_processing_complex": "google/gemini-pro",
        },
        "preprocessing_thresholds": {
            "harmful_content_score": 7,
            "misuse_risk_score": 7,
        },
        "always_include_skills": ["web-search"],
    }


@pytest.mark.asyncio
async def test_cache_async_skill_continuation_context_stores_original_request(async_skill_continuation):
    cache = _FakeCache()

    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache,
        async_task_id="async-task-1",
        request_data=_request(),
        skill_config_dict=_skill_config_dict(),
        app_id="social_media",
        skill_id="search",
        tool_name="social_media-search",
        tool_arguments={"requests": [{"query": "privacy AI"}]},
    )

    key = async_skill_continuation.async_skill_continuation_key("async-task-1")
    assert cache.values[key]["ttl"] == async_skill_continuation.ASYNC_SKILL_CONTINUATION_TTL_SECONDS
    assert cache.values[key]["value"]["request_data"]["chat_id"] == "chat-1"
    assert cache.values[key]["value"]["skill_config_dict"]["default_llms"]["preprocessing_model"] == "mistral/small"
    assert cache.values[key]["value"]["tool_name"] == "social_media-search"


@pytest.mark.asyncio
async def test_dispatch_async_skill_continuation_sends_normal_ask_task(monkeypatch, async_skill_continuation):
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache,
        async_task_id="async-task-1",
        request_data=_request(),
        skill_config_dict=_skill_config_dict(),
        app_id="social_media",
        skill_id="search",
        tool_name="social_media-search",
        tool_arguments={"requests": [{"query": "privacy AI"}]},
    )

    task_id = await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache,
        async_task_id="async-task-1",
        completed_results=[{"title": "A useful post", "url": "https://example.com/post"}],
        request_metadata={"query": "privacy AI", "provider": "bluesky_public"},
    )

    assert task_id == "continuation-task-1"
    assert fake_celery_app.sent[0]["name"] == "apps.ai.tasks.skill_ask"
    assert fake_celery_app.sent[0]["queue"] == "app_ai"
    request_payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    skill_config_payload = fake_celery_app.sent[0]["kwargs"]["skill_config_dict"]
    assert request_payload["chat_id"] == "chat-1"
    assert request_payload["message_history"][-1]["role"] == "system"
    assert "Completed tool result" in request_payload["message_history"][-1]["content"]
    assert "A useful post" in request_payload["message_history"][-1]["content"]
    assert skill_config_payload["default_llms"]["preprocessing_model"] == "mistral/small"
    assert skill_config_payload["always_include_skills"] == ["web-search"]
    assert cache.deleted == [async_skill_continuation.async_skill_continuation_key("async-task-1")]


@pytest.mark.asyncio
async def test_dispatch_async_skill_continuation_caches_inline_wait_result(monkeypatch, async_skill_continuation):
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache,
        async_task_id="async-task-1",
        request_data=_request(),
        skill_config_dict=_skill_config_dict(),
        app_id="social_media",
        skill_id="search",
        tool_name="social_media-search",
        tool_arguments={"requests": [{"query": "privacy AI"}]},
        inline_wait_deadline=time.time() + 10,
    )

    task_id = await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache,
        async_task_id="async-task-1",
        completed_results=[{"title": "A useful post", "url": "https://example.com/post"}],
        request_metadata={"query": "privacy AI", "provider": "bluesky_public"},
    )

    assert task_id is None
    assert fake_celery_app.sent == []
    completion_key = async_skill_continuation.async_skill_completion_key("async-task-1")
    assert cache.values[completion_key]["value"]["results"][0]["title"] == "A useful post"

    completion = await async_skill_continuation.wait_for_async_skill_completion(
        cache_service=cache,
        async_task_ids=["async-task-1"],
        timeout_seconds=0.1,
    )

    assert completion["results"][0]["title"] == "A useful post"
    assert async_skill_continuation.async_skill_completion_key("async-task-1") not in cache.values
    assert async_skill_continuation.async_skill_continuation_key("async-task-1") not in cache.values
