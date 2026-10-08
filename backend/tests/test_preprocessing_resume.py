"""Turn and authority fences for server-owned preprocessing reuse."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import BaseModel, Field

from backend.core.api.app.schemas.chat import AIHistoryMessage


_MODULE_PATH = Path(__file__).resolve().parents[1] / "apps" / "ai" / "tasks" / "preprocessing_resume.py"
class PreprocessingResult(BaseModel):
    can_proceed: bool = False
    selected_main_llm_model_id: str | None = None
    relevant_app_skills: list[str] | None = None
    selected_app_ids: list[str] | None = Field(default=None, exclude=True)
    relevant_rules: list[dict] | None = Field(default=None, exclude=True)
    relevant_workflows: list[dict] | None = Field(default=None, exclude=True)
    raw_llm_response: dict | None = None
    title: str | None = None
    chat_summary: str | None = None
    chat_tags: list[str] | None = None
    model_selection_reason: str | None = None


@pytest.fixture
def resume(monkeypatch):
    celery = ModuleType("celery")
    celery.Celery = object
    monkeypatch.setitem(sys.modules, "celery", celery)
    celery_exceptions = ModuleType("celery.exceptions")
    celery_exceptions.Ignore = Exception
    celery_exceptions.SoftTimeLimitExceeded = TimeoutError
    monkeypatch.setitem(sys.modules, "celery.exceptions", celery_exceptions)
    celery_states = ModuleType("celery.states")
    celery_states.REVOKED = "REVOKED"
    monkeypatch.setitem(sys.modules, "celery.states", celery_states)
    preprocessor = ModuleType("backend.apps.ai.processing.preprocessor")
    preprocessor.PreprocessingResult = PreprocessingResult
    monkeypatch.setitem(sys.modules, "backend.apps.ai.processing.preprocessor", preprocessor)
    spec = importlib.util.spec_from_file_location("preprocessing_resume_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Cache:
    def __init__(self):
        self.values = {"async_skill_latest_user_turn:user-1:chat-1": "turn-1"}

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)


def _request(**changes):
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    data = dict(
        chat_id="chat-1", message_id="turn-1", user_id="user-1", user_id_hash="hash-1",
        message_history=[AIHistoryMessage(role="user", content="Find the answer", created_at=1)],
    )
    data.update(changes)
    return AskSkillRequest(**data)


def _decision():
    return PreprocessingResult(
        can_proceed=True,
        selected_main_llm_model_id="google/gemini-2.5-flash",
        relevant_app_skills=["web-search"],
        selected_app_ids=["web"],
        relevant_rules=[{"id": "private", "revision": "r1", "document": "secret rule body"}],
        relevant_workflows=[{"workflow_id": "workflow-1", "current_version_id": "v1", "body": "secret rule body"}],
        raw_llm_response={"private": "secret rule body"},
        title="Private Project name",
        chat_summary="Private Project work summary",
        chat_tags=["Private Project tag"],
        model_selection_reason="Private Project model reason",
    )


@pytest.mark.asyncio
# contract-test: tooling
async def test_internal_continuation_reuses_decisions_without_private_rule_body(resume):
    cache = _Cache()
    ref = await resume.store_preprocessing_resume(cache, _request(), _decision())
    request = _request(is_async_skill_continuation=True, preprocessing_resume_ref=ref)
    loaded = await resume.load_preprocessing_resume(cache, request)

    assert loaded is not None
    result, apps, refresh_project = loaded
    assert result.relevant_app_skills == ["web-search"]
    assert result.selected_app_ids == ["web"]
    assert result.relevant_rules == [{"id": "private", "revision": "r1"}]
    assert result.relevant_workflows == [{"workflow_id": "workflow-1", "current_version_id": "v1"}]
    assert apps == ["web"]
    assert refresh_project is False
    assert "secret rule body" not in str(cache.values)
    assert "Private Project" not in str(cache.values)
    assert result.title is None
    assert result.chat_summary is None
    assert result.chat_tags is None
    assert result.model_selection_reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"user_id": "other-user"}, {"chat_id": "other-chat"},
    {"message_id": "other-turn"}, {"team_id": "other-team"},
])
# contract-test: tooling
async def test_other_scope_cannot_reuse_decisions(resume, change):
    cache = _Cache()
    ref = await resume.store_preprocessing_resume(cache, _request(), _decision())
    request = _request(is_async_skill_continuation=True, preprocessing_resume_ref=ref, **change)
    assert await resume.load_preprocessing_resume(cache, request) is None


@pytest.mark.asyncio
# contract-test: tooling
async def test_replayed_or_client_forged_snapshot_does_not_bypass_routing(resume):
    cache = _Cache()
    ref = await resume.store_preprocessing_resume(cache, _request(), _decision())
    fresh = _request(preprocessing_resume_ref=ref)
    assert await resume.load_preprocessing_resume(cache, fresh) is None
    fake = _request(is_async_skill_continuation=True, preprocessing_resume_ref="x" * 43)
    assert await resume.load_preprocessing_resume(cache, fake) is None
    changed_message = _request(
        is_async_skill_continuation=True, preprocessing_resume_ref=ref,
        message_history=[AIHistoryMessage(role="user", content="A different request", created_at=1)],
    )
    assert await resume.load_preprocessing_resume(cache, changed_message) is None
    cache.values["async_skill_latest_user_turn:user-1:chat-1"] = "turn-2"
    old = _request(is_async_skill_continuation=True, preprocessing_resume_ref=ref)
    assert await resume.load_preprocessing_resume(cache, old) is None


@pytest.mark.asyncio
# contract-test: tooling
async def test_new_project_focus_refreshes_stage_two_using_saved_apps(resume):
    cache = _Cache()
    ref = await resume.store_preprocessing_resume(cache, _request(), _decision())
    request = _request(
        is_focus_mode_continuation=True, preprocessing_resume_ref=ref,
        active_project_focus={"project_id": "project-1"},
    )
    loaded = await resume.load_preprocessing_resume(cache, request)
    assert loaded is not None
    assert loaded[1] == ["web"]
    assert loaded[2] is True


@pytest.mark.asyncio
# contract-test: tooling
async def test_builtin_focus_continuation_keeps_existing_decisions(resume):
    cache = _Cache()
    ref = await resume.store_preprocessing_resume(cache, _request(), _decision())
    request = _request(
        is_focus_mode_continuation=True, preprocessing_resume_ref=ref,
        active_focus_id="code-debug",
    )
    loaded = await resume.load_preprocessing_resume(cache, request)
    assert loaded is not None
    assert loaded[2] is False


@pytest.mark.asyncio
# contract-test: tooling
async def test_fallback_without_jev_shortlist_keeps_all_app_routing(resume):
    cache = _Cache()
    decision = _decision()
    decision.selected_app_ids = None
    ref = await resume.store_preprocessing_resume(cache, _request(), decision)
    request = _request(is_async_skill_continuation=True, preprocessing_resume_ref=ref)
    loaded = await resume.load_preprocessing_resume(cache, request)
    assert loaded is not None
    assert loaded[0].selected_app_ids is None
    assert loaded[1] is None


@pytest.mark.asyncio
# contract-test: tooling
async def test_sub_chat_completion_event_keeps_original_source_turn(resume):
    cache = _Cache()
    ref = await resume.store_preprocessing_resume(cache, _request(), _decision())
    request = _request(
        is_sub_chat_continuation=True, preprocessing_resume_ref=ref,
        message_history=[
            AIHistoryMessage(role="user", content="Find the answer", created_at=1),
            AIHistoryMessage(role="user", sender_name="sub_chat_result",
                             content="The child completed", created_at=2),
        ],
    )
    assert await resume.load_preprocessing_resume(cache, request) is not None
