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
        self.active_task = None

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

    async def get_active_ai_task(self, _chat_id):
        return self.active_task


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
        current_user_content="Search social media for privacy AI",
        chat_has_title=True,
        mate_id="mate-1",
        client_capabilities=["project_file_jobs", "remote_command_jobs"],
        user_preferences={"language": "en"},
        recovery_task_id="recovery-inference-1",
        recovery_preflight_id="preflight-1",
        recovery_turn_id="turn-1",
        recovery_public_key="public-key-1",
        chat_key_version=4,
        preprocessing_resume_ref="server-owned-routing-ref",
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
# contract-test: tooling
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
@pytest.mark.parametrize("assistant_tail", [False, True])
# contract-test: tooling
async def test_dispatch_async_skill_continuation_sends_normal_ask_task(monkeypatch, async_skill_continuation, assistant_tail):
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    if assistant_tail:
        request.message_history.append(AIHistoryMessage(
            role="assistant", content="The tool is running.", created_at=2,
        ))
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache,
        async_task_id="async-task-1",
        request_data=request,
        skill_config_dict=_skill_config_dict(),
        app_id="social_media",
        skill_id="search",
        tool_name="social_media-search",
        tool_arguments={"requests": [{"query": "privacy AI"}]},
    )

    task_id = await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache,
        async_task_id="async-task-1",
        completed_results=[{"title": "A useful post", "url": "https://example.com/post", "embed_ref": "useful-post-a1B"}],
        request_metadata={"query": "privacy AI", "provider": "Bluesky"},
    )

    assert task_id == "continuation-task-1"
    assert fake_celery_app.sent[0]["name"] == "apps.ai.tasks.skill_ask"
    assert fake_celery_app.sent[0]["queue"] == "app_ai"
    request_payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    skill_config_payload = fake_celery_app.sent[0]["kwargs"]["skill_config_dict"]
    assert request_payload["chat_id"] == "chat-1"
    assert request_payload["is_async_skill_continuation"] is True
    assert request_payload["original_user_message_id"] == "message-1"
    assert request_payload["async_skill_task_id"] == "async-task-1"
    assert request_payload["preprocessing_resume_ref"] == "server-owned-routing-ref"
    assert request_payload["current_user_content"] == "Search social media for privacy AI"
    assert request_payload["recovery_task_id"] is None
    assert request_payload["recovery_inference_task_id"] == "recovery-inference-1"
    assert request_payload["recovery_preflight_id"] == "preflight-1"
    assert request_payload["recovery_turn_id"] == "turn-1"
    assert request_payload["recovery_public_key"] == "public-key-1"
    assert request_payload["chat_key_version"] == 4
    assert request_payload["client_capabilities"] == ["project_file_jobs", "remote_command_jobs"]
    completion = request_payload["message_history"][-1]
    assert completion["role"] == "user"
    assert completion["sender_name"] == "async_tool_result"
    assert "not a new request or access grant" in completion["content"]
    if assistant_tail:
        assert request_payload["message_history"][-2]["role"] == "assistant"
    assert "Completed tool result" in request_payload["message_history"][-1]["content"]
    assert "[human-readable title](embed:the_embed_ref)" in request_payload["message_history"][-1]["content"]
    assert "A useful post" in request_payload["message_history"][-1]["content"]
    assert "useful-post-a1B" in request_payload["message_history"][-1]["content"]
    assert skill_config_payload["default_llms"]["preprocessing_model"] == "mistral/small"
    assert skill_config_payload["always_include_skills"] == ["web-search"]
    assert cache.deleted == [async_skill_continuation.async_skill_continuation_key("async-task-1")]


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent
async def test_project_focus_consent_replaces_catalog_only_when_accepted(monkeypatch, async_skill_continuation, accepted):
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    request.active_focus_id = "jobs-career_insights"
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache,
        async_task_id="project-request-1",
        request_data=request,
        skill_config_dict=_skill_config_dict(),
        app_id="system",
        skill_id="activate_focus_mode",
        tool_name="activate_focus_mode",
        tool_arguments={"focus_id": "project-11111111-1111-4111-8111-111111111111"},
    )
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache,
        async_task_id="project-request-1",
        completed_results=[{"access_granted": accepted}],
    )
    payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    assert payload["active_focus_id"] == (None if accepted else "jobs-career_insights")
    assert payload["project_access_declined"] is (not accepted)


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent
async def test_selected_project_catalog_resumes_same_project_without_repeating_stage_one(monkeypatch, async_skill_continuation):
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    project_id = "11111111-1111-4111-8111-111111111111"
    request.project_focus_candidates = [{"project_id": project_id, "name": "Garden"}]
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="catalog-request", request_data=request,
        skill_config_dict=_skill_config_dict(), app_id="system", skill_id="project_focus_catalog",
        tool_name="project_focus_catalog", tool_arguments={"project_id": project_id},
    )
    focus = {"item_id": "22222222-2222-4222-8222-222222222222", "revision": "a" * 64,
             "title": "Debug", "description": "Service failures", "when_to_use": "Debugging"}
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="catalog-request",
        completed_results=[{"project_id": project_id, "catalog_received": True}],
        project_routing_focus_id=f"project-{project_id}",
        selected_project_focus_candidates=[{"project_id": project_id, "name": "Garden", "focuses": [focus]}],
    )
    payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    assert payload["project_routing_focus_id"] == f"project-{project_id}"
    assert payload["project_focus_candidates"][0]["focuses"] == [focus]


@pytest.mark.asyncio
@pytest.mark.parametrize("deferred", [False, True])
# contract-test: supporting surface=gui.web assertions=projects.focus.inferred-consent
async def test_consented_specialist_document_reaches_first_continuation(monkeypatch, async_skill_continuation, deferred):
    from backend.shared.python_utils import recent_work_summary_client
    async def seal(payload, *, request_id):
        assert payload["project_focus_documents"][0]["document"] == "private focus body"
        assert request_id == "focus-request"
        result = {key: value for key, value in payload.items()
                  if key not in {"project_focus_catalog", "project_focus_documents"}}
        result.update(agentic_context_ref="opaque-private-context", agentic_context_request_id=request_id,
                      agentic_context_turn_id=payload["message_id"])
        return result
    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", seal)
    cache = _FakeCache()
    cache.active_task = "initial-response-task" if deferred else None
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    project_id = "11111111-1111-4111-8111-111111111111"
    item_id = "22222222-2222-4222-8222-222222222222"
    focus_id = f"project-focus:{project_id}:{item_id}"
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="focus-request", request_data=request,
        skill_config_dict=_skill_config_dict(), app_id="system", skill_id="activate_focus_mode",
        tool_name="activate_focus_mode", tool_arguments={"focus_id": f"project-{project_id}"},
        defer_until_initial_response_complete=deferred,
    )
    document = {"item_id": item_id, "revision": "a" * 64, "document": "private focus body"}
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="focus-request",
        completed_results=[{"project_id": project_id, "access_granted": True}],
        project_focus_documents=[document], selected_specialist_focus_id=focus_id,
        selected_specialist_title="Debug",
    )
    if deferred:
        stored = cache.values[async_skill_continuation.async_skill_deferred_completion_key("focus-request")]["value"]
        assert "private focus body" not in str(stored)
        assert "project_focus_documents" not in str(stored)
        cache.active_task = None
        assert await async_skill_continuation.dispatch_deferred_async_skill_continuations(
            cache_service=cache, user_id="user-1", chat_id="chat-1",
        ) == ["continuation-task-1"]
    payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    assert payload["active_focus_id"] == focus_id
    assert payload["agentic_context_ref"] == "opaque-private-context"
    assert "project_focus_catalog" not in payload
    assert "project_focus_documents" not in payload
    assert "private focus body" not in str(payload)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
async def test_specialist_seal_failure_keeps_all_private_context_off_celery(monkeypatch, async_skill_continuation):
    from backend.shared.python_utils import recent_work_summary_client
    from backend.shared.python_utils.recent_work_summary_cache import PRIVATE_CONTEXT_FIELDS

    private_values = {field: [{"secret": f"private-{field}"}] for field in PRIVATE_CONTEXT_FIELDS}

    async def restore(payload):
        return {**payload, **private_values}

    async def fail_seal(payload, *, request_id):
        assert request_id == "focus-request"
        assert payload["project_focus_documents"][0]["document"] == "private focus body"
        assert all(field in payload for field in PRIVATE_CONTEXT_FIELDS)
        raise RuntimeError("private handoff unavailable")

    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", restore)
    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", fail_seal)
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    request.agentic_context_ref = "prior-opaque-context"
    request.agentic_context_request_id = "prior-request"
    request.agentic_context_turn_id = request.message_id
    project_id = "11111111-1111-4111-8111-111111111111"
    item_id = "22222222-2222-4222-8222-222222222222"
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="focus-request", request_data=request,
        skill_config_dict=_skill_config_dict(), app_id="system", skill_id="activate_focus_mode",
        tool_name="activate_focus_mode", tool_arguments={"focus_id": f"project-{project_id}"},
    )
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="focus-request",
        completed_results=[{"project_id": project_id, "access_granted": True}],
        project_focus_documents=[{"item_id": item_id, "revision": "a" * 64,
                                  "document": "private focus body"}],
        selected_specialist_focus_id=f"project-focus:{project_id}:{item_id}",
    )
    payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    assert payload["agentic_context_ref"] == "prior-opaque-context"
    assert payload["agentic_context_request_id"] == "prior-request"
    assert payload["active_focus_id"] is None
    assert all(field not in payload for field in PRIVATE_CONTEXT_FIELDS)
    assert "private focus body" not in str(payload)
    assert all(f"private-{field}" not in str(payload) for field in PRIVATE_CONTEXT_FIELDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("deferred", [False, True])
# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy,projects.focus.inferred-consent
async def test_project_file_result_is_opaque_before_redis_or_celery(monkeypatch, async_skill_continuation, deferred):
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.shared.python_utils import recent_work_summary_client
    from backend.shared.python_utils.recent_work_summary_client import (
        PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER, restore_async_tool_completion_message,
    )

    sealed_fields = {}

    async def seal(payload, *, request_id):
        assert request_id == "project-read-1"
        sealed_fields["async_tool_history"] = payload["async_tool_history"]
        assert "PRIVATE README CONTENT" in sealed_fields["async_tool_history"][-1]["content"]
        return {key: value for key, value in payload.items()
                if key != "async_tool_history"} | {
            "agentic_context_ref": "opaque-project-result",
            "agentic_context_request_id": request_id,
            "agentic_context_turn_id": payload["message_id"],
        }

    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", seal)
    cache = _FakeCache()
    cache.active_task = "initial-response-task" if deferred else None
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    project_id = "11111111-1111-4111-8111-111111111111"
    request.active_project_focus = {"project_id": project_id}
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="project-read-1", request_data=request,
        skill_config_dict=_skill_config_dict(), app_id="system", skill_id="project_read_text",
        tool_name="project_read_text", tool_arguments={"path": "README.md"},
        defer_until_initial_response_complete=deferred,
    )
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="project-read-1",
        completed_results=[{"status": "completed", "content": "PRIVATE README CONTENT"}],
    )
    if deferred:
        stored = cache.values[async_skill_continuation.async_skill_deferred_completion_key("project-read-1")]["value"]
        assert "PRIVATE README CONTENT" not in str(stored)
        assert "completed_results" not in stored
        cache.active_task = None
        assert await async_skill_continuation.dispatch_deferred_async_skill_continuations(
            cache_service=cache, user_id="user-1", chat_id="chat-1",
        ) == ["continuation-task-1"]
    payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    assert payload["agentic_context_ref"] == "opaque-project-result"
    assert payload["message_history"][-1]["content"] == PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER
    assert "PRIVATE README CONTENT" not in str(fake_celery_app.sent)
    worker_request = AskSkillRequest(**payload)
    restore_async_tool_completion_message(worker_request, sealed_fields)
    assert "PRIVATE README CONTENT" in worker_request.message_history[-1].content
    wrong_task = AskSkillRequest(**payload)
    restore_async_tool_completion_message(wrong_task, {
        "async_tool_history": [{**sealed_fields["async_tool_history"][-1], "index": 0}],
    })
    assert wrong_task.message_history[-1].content == PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
async def test_project_file_seal_failure_never_queues_contents(monkeypatch, async_skill_continuation):
    from backend.shared.python_utils import recent_work_summary_client
    from backend.shared.python_utils.recent_work_summary_client import PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER

    async def fail_seal(payload, *, request_id):
        assert "PRIVATE README CONTENT" in payload["async_tool_history"][-1]["content"]
        raise RuntimeError("private IPC unavailable")

    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", fail_seal)
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    request.active_project_focus = {"project_id": "11111111-1111-4111-8111-111111111111"}
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="project-read-1", request_data=request,
        skill_config_dict=_skill_config_dict(), app_id="system", skill_id="project_read_text",
        tool_name="project_read_text", tool_arguments={"path": "README.md"},
    )
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="project-read-1",
        completed_results=[{"status": "completed", "content": "PRIVATE README CONTENT"}],
    )
    payload = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    assert payload["message_history"][-1]["content"] == PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER
    assert "PRIVATE README CONTENT" not in str(fake_celery_app.sent)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
async def test_inline_project_file_result_uses_opaque_cache_handoff(monkeypatch, async_skill_continuation):
    from backend.shared.python_utils import recent_work_summary_client

    private_payload = {}

    async def seal(payload, *, request_id):
        assert request_id == "project-read-1"
        private_payload.update(payload["async_tool_completion"])
        return {"agentic_context_ref": "opaque-inline-result"}

    async def restore(payload):
        assert payload["agentic_context_ref"] == "opaque-inline-result"
        assert payload["agentic_context_request_id"] == "project-read-1"
        return {"async_tool_completion": private_payload}

    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", seal)
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", restore)
    cache = _FakeCache()
    request = _request()
    request.active_project_focus = {"project_id": "11111111-1111-4111-8111-111111111111"}
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="project-read-1", request_data=request,
        skill_config_dict=_skill_config_dict(), app_id="system", skill_id="project_read_text",
        tool_name="project_read_text", tool_arguments={"path": "README.md"},
        inline_wait_deadline=time.time() + 30,
    )
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="project-read-1",
        completed_results=[{"status": "completed", "content": "PRIVATE README CONTENT"}],
    )
    stored = cache.values[async_skill_continuation.async_skill_completion_key("project-read-1")]["value"]
    assert "PRIVATE README CONTENT" not in str(stored)
    assert stored["agentic_context_ref"] == "opaque-inline-result"
    restored = await async_skill_continuation.wait_for_async_skill_completion(
        cache_service=cache, async_task_ids=["project-read-1"], timeout_seconds=1,
    )
    assert restored["results"][0]["content"] == "PRIVATE README CONTENT"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
async def test_restored_project_file_history_stays_opaque_across_next_tool(monkeypatch, async_skill_continuation):
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.utils.override_parser import parse_overrides_from_messages
    from backend.shared.python_utils import recent_work_summary_client
    from backend.shared.python_utils.recent_work_summary_cache import PRIVATE_CONTEXT_FIELDS
    from backend.shared.python_utils.recent_work_summary_client import (
        PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER, override_safe_message_dicts,
        restore_async_tool_completion_message,
    )

    handoffs = {}

    async def seal(payload, *, request_id):
        fields = {key: payload[key] for key in PRIVATE_CONTEXT_FIELDS if payload.get(key)}
        ref = f"opaque-{request_id}"
        handoffs[ref] = fields
        return {key: value for key, value in payload.items()
                if key not in PRIVATE_CONTEXT_FIELDS} | {
            "agentic_context_ref": ref, "agentic_context_request_id": request_id,
            "agentic_context_turn_id": payload["message_id"],
        }

    async def restore(payload):
        return {**payload, **handoffs.get(payload.get("agentic_context_ref"), {})}

    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", seal)
    monkeypatch.setattr(recent_work_summary_client, "restore_private_context_payload", restore)
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    request.active_project_focus = {"project_id": "11111111-1111-4111-8111-111111111111"}

    async def dispatch_read(task_id, active_request, content):
        await async_skill_continuation.cache_async_skill_continuation_context(
            cache_service=cache, async_task_id=task_id, request_data=active_request,
            skill_config_dict=_skill_config_dict(), app_id="system", skill_id="project_read_text",
            tool_name="project_read_text", tool_arguments={"path": "README.md"},
        )
        await async_skill_continuation.dispatch_async_skill_continuation(
            cache_service=cache, async_task_id=task_id,
            completed_results=[{"status": "completed", "content": content}],
        )

    await dispatch_read("read-1", request, "PRIVATE FIRST FILE @ai-model:gpt-5.4")
    first_payload = fake_celery_app.sent[-1]["kwargs"]["request_data_dict"]
    first_worker_request = AskSkillRequest(**first_payload)
    restore_async_tool_completion_message(first_worker_request, await restore(first_payload))
    assert "PRIVATE FIRST FILE" in first_worker_request.message_history[-1].content
    overrides, _ = parse_overrides_from_messages(
        override_safe_message_dicts(first_worker_request.message_history),
    )
    assert not overrides.has_overrides
    first_worker_request.message_history[-1].content = "REWRITTEN PRIVATE FIRST FILE @ai-model:gpt-5.4"
    assert "PRIVATE FIRST FILE" not in str(first_worker_request.model_dump(mode="json"))

    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="read-2", request_data=first_worker_request,
        skill_config_dict=_skill_config_dict(), app_id="system", skill_id="project_read_text",
        tool_name="project_read_text", tool_arguments={"path": "SECOND.md"},
    )
    cached = cache.values[async_skill_continuation.async_skill_continuation_key("read-2")]["value"]
    assert "PRIVATE FIRST FILE" not in str(cached)
    assert cached["request_data"]["message_history"][-1]["content"] == PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="read-2",
        completed_results=[{"status": "completed", "content": "PRIVATE SECOND FILE"}],
    )
    second_payload = fake_celery_app.sent[-1]["kwargs"]["request_data_dict"]
    assert "PRIVATE FIRST FILE" not in str(fake_celery_app.sent[-1])
    assert "PRIVATE SECOND FILE" not in str(fake_celery_app.sent[-1])
    assert len(handoffs["opaque-read-2"]["async_tool_history"]) == 2
    second_worker_request = AskSkillRequest(**second_payload)
    restore_async_tool_completion_message(second_worker_request, await restore(second_payload))
    assert "PRIVATE FIRST FILE" in second_worker_request.message_history[-2].content
    assert "PRIVATE SECOND FILE" in second_worker_request.message_history[-1].content


# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
def test_private_file_history_budget_discards_old_bodies_first(async_skill_continuation):
    entries = [
        {"index": index, "project_id": "11111111-1111-4111-8111-111111111111",
         "content": f"FILE-{index}-" + ("x" * 75_000)}
        for index in range(3)
    ]
    payload = {"async_tool_history": entries}
    async_skill_continuation._fit_private_async_tool_history(
        payload, frozenset({"async_tool_history"}),
    )
    assert len(payload["async_tool_history"]) == 2
    assert [entry["index"] for entry in payload["async_tool_history"]] == [1, 2]
    assert "FILE-0-" not in str(payload)
    oversized = {"async_tool_history": [{"index": 0, "project_id": entries[-1]["project_id"],
                                           "content": "CURRENT-" + "x" * 190_000}]}
    with pytest.raises(RuntimeError, match="exceeds transient handoff budget"):
        async_skill_continuation._fit_private_async_tool_history(
            oversized, frozenset({"async_tool_history"}),
        )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
async def test_base_project_instruction_is_metadata_only_in_continuation_queues(monkeypatch, async_skill_continuation):
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    request = _request()
    request.active_project_focus = {
        "project_id": "11111111-1111-4111-8111-111111111111",
        "focus_id": "project-11111111-1111-4111-8111-111111111111",
        "activation_id": "activation-1", "instruction": "PRIVATE BASE PROJECT INSTRUCTION",
        "nested_private_body": {"content": "PRIVATE BASE PROJECT INSTRUCTION"},
    }
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache, async_task_id="ordinary-async-1", request_data=request,
        skill_config_dict=_skill_config_dict(), app_id="social_media", skill_id="search",
        tool_name="social_media-search", tool_arguments={},
    )
    cached = cache.values[async_skill_continuation.async_skill_continuation_key("ordinary-async-1")]["value"]
    assert "PRIVATE BASE PROJECT INSTRUCTION" not in str(cached)
    assert cached["request_data"]["active_project_focus"] == {
        "project_id": "11111111-1111-4111-8111-111111111111",
        "focus_id": "project-11111111-1111-4111-8111-111111111111",
        "activation_id": "activation-1",
    }
    await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache, async_task_id="ordinary-async-1", completed_results=[{"status": "completed"}],
    )
    queued = fake_celery_app.sent[0]["kwargs"]["request_data_dict"]
    assert "PRIVATE BASE PROJECT INSTRUCTION" not in str(fake_celery_app.sent)
    assert queued["active_project_focus"]["activation_id"] == "activation-1"


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_async_embed_instruction_omits_results_view_for_non_visual_skill(async_skill_continuation):
    message = async_skill_continuation._build_completed_tool_result_message(
        context={
            "app_id": "news",
            "skill_id": "search",
            "tool_name": "news-search",
            "tool_arguments": {"requests": [{"query": "AI news"}]},
        },
        completed_results=[{"title": "AI news", "embed_ref": "news-ref-123"}],
        result_status="finished",
        request_metadata={"query": "AI news"},
    )

    assert "[human-readable title](embed:the_embed_ref)" in message
    assert "```embeds_results_view" not in message


# contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
def test_async_embed_instruction_includes_results_view_for_visual_skill(async_skill_continuation):
    message = async_skill_continuation._build_completed_tool_result_message(
        context={
            "app_id": "maps",
            "skill_id": "search",
            "tool_name": "maps-search",
            "tool_arguments": {"requests": [{"query": "cafes near me"}]},
        },
        completed_results=[{"title": "Cafe", "embed_ref": "cafe-ref-123", "location_latitude": 52.5, "location_longitude": 13.4}],
        result_status="finished",
        request_metadata={"query": "cafes near me"},
    )

    assert "[human-readable title](embed:the_embed_ref)" in message
    assert "```embeds_results_view" in message


@pytest.mark.asyncio
# contract-test: tooling
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
        request_metadata={"query": "privacy AI", "provider": "Bluesky"},
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


@pytest.mark.asyncio
# contract-test: tooling
async def test_current_turn_fence_discards_stale_continuation(monkeypatch, async_skill_continuation):
    cache = _FakeCache()
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache,
        async_task_id="async-task-1",
        request_data=_request(),
        skill_config_dict=_skill_config_dict(),
        app_id="system",
        skill_id="project_read_text",
        tool_name="project_read_text",
        tool_arguments={"path": "README.md"},
        requires_current_turn=True,
    )
    await cache.set(
        async_skill_continuation.async_skill_latest_user_turn_key("user-1", "chat-1"),
        "message-2",
    )
    result = await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache,
        async_task_id="async-task-1",
        completed_results=[{"content": "stale"}],
    )
    assert result is None
    assert fake_celery_app.sent == []
    assert async_skill_continuation.async_skill_continuation_key("async-task-1") not in cache.values


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=code-run.execution.wait-or-continue
async def test_continue_mode_defers_completion_until_initial_response_finishes(monkeypatch, async_skill_continuation):
    cache = _FakeCache()
    cache.active_task = "initial-response-task"
    fake_celery_app = _FakeCeleryApp()
    monkeypatch.setattr(async_skill_continuation, "celery_app", fake_celery_app)
    await async_skill_continuation.cache_async_skill_continuation_context(
        cache_service=cache,
        async_task_id="remote-command-1",
        request_data=_request(),
        skill_config_dict=_skill_config_dict(),
        app_id="code",
        skill_id="run",
        tool_name="code-run",
        tool_arguments={"target": "remote_source", "wait_for_completion": False},
        requires_current_turn=True,
        defer_until_initial_response_complete=True,
    )
    await cache.set(
        async_skill_continuation.async_skill_latest_user_turn_key("user-1", "chat-1"),
        "message-1",
    )
    assert await async_skill_continuation.dispatch_async_skill_continuation(
        cache_service=cache,
        async_task_id="remote-command-1",
        completed_results=[{"status": "succeeded", "output": "done"}],
    ) is None
    assert fake_celery_app.sent == []

    # The original ask can reach its drain while its active marker still exists.
    # The completion must remain available for the drain after queue handoff.
    assert await async_skill_continuation.dispatch_deferred_async_skill_continuations(
        cache_service=cache, user_id="user-1", chat_id="chat-1"
    ) == []
    assert async_skill_continuation.async_skill_deferred_completion_key("remote-command-1") in cache.values
    assert async_skill_continuation.async_skill_deferred_index_key("user-1", "chat-1") in cache.values

    cache.active_task = None
    dispatched = await async_skill_continuation.dispatch_deferred_async_skill_continuations(
        cache_service=cache, user_id="user-1", chat_id="chat-1"
    )
    assert dispatched == ["continuation-task-1"]
    assert len(fake_celery_app.sent) == 1
