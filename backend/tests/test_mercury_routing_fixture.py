"""Check the signed automatic-routing replay's boundaries and provider packets.

No provider requests are made. Real Jev question construction and the ordinary
cached provider wrapper validate classification and typed packet restoration.
Browser proof of the complete fallback remains in mercury3-model-picker.spec.ts.
"""
# contract-test-file: infrastructure
from pathlib import Path

import pytest

from backend.apps.ai.processing.jev_preprocessing import (
    decide_app_and_project_routing_with_jev, decide_preprocessing_with_jev,
)
from backend.apps.ai.processing.model_routing import LOW_FALLBACK_MODEL
from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.testing.mercury_routing_fixture import (
    GROUP, SUCCESS_PROMPT, FALLBACK_PROMPT, SUCCESS_RESPONSE, FALLBACK_RESPONSE,
    DISABLED_PROMPT, DISABLED_RESPONSE,
    active, jev_response, llm_fixture,
)
from backend.shared.providers.inception import InceptionError
from backend.shared.providers.typesafe import budget as jev_budget
from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.mock_context import (
    _LiveMockReceiptState, _allow_isolated_capacity_internal, live_mock_receipt_var,
    mock_group_var, mock_mode_var,
)


@pytest.fixture
def replay(monkeypatch):
    jev_budget._encodings()
    for key, value in {"SERVER_ENVIRONMENT": "development", "MOCK_EXTERNAL_APIS": "true",
                       "CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_AI_FIXTURES": "1"}.items():
        monkeypatch.setenv(key, value)
    mode = mock_mode_var.set("mock")
    group = mock_group_var.set(GROUP)
    try:
        yield
    finally:
        mock_group_var.reset(group)
        mock_mode_var.reset(mode)


@pytest.mark.parametrize("key,value", [
    ("SERVER_ENVIRONMENT", "production"), ("SERVER_ENVIRONMENT", "prod"),
    ("MOCK_EXTERNAL_APIS", "false"), ("CI", "false"),
    ("OPENMATES_CI_ISOLATED", "0"), ("OPENMATES_CI_AI_FIXTURES", "0"),
])
def test_fixture_is_inert_outside_isolated_replay(replay, monkeypatch, key, value):
    assert active()
    monkeypatch.setenv(key, value)
    assert not active()
    assert llm_fixture("llm/mercury-3", {
        "model_id": "mercury-3", "task_id": "gate-test",
        "messages": [{"role": "user", "content": FALLBACK_PROMPT}],
    }) is None


@pytest.mark.asyncio
async def test_actual_jev_questions_classify_low_without_skill_or_project(replay):
    history = [{"role": "user", "content": SUCCESS_PROMPT}]
    routing = await decide_app_and_project_routing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        available_apps=["web", "shopping"], available_skills=[], available_focus_modes=[],
        topic_areas=["general_misc"], is_first_message=True,
    )
    assert routing["selected_app_ids"] == []
    selected = await decide_preprocessing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        topic_areas=["general_misc"], available_skills=[], available_focus_modes=[],
        available_settings_and_memories={}, recent_skill_activity=[], conversation_summary=None,
        previous_category=None, is_first_message=True, available_apps=["web", "shopping"],
        selected_app_ids=[], early_decisions=routing["early_decisions"],
    )
    assert selected["complexity"] == "low"
    assert selected["relevant_app_skills"] == []


@pytest.mark.asyncio
async def test_wrapper_delivers_typed_success_and_requires_real_failure_before_fallback(replay, tmp_path: Path):
    async def forbidden_provider(**_kwargs):
        raise AssertionError("routing fixture must never dispatch a real provider")

    wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))
    async def collect(model, prompt, task_id):
        stream = await wrapped(model_id=model, stream=True, task_id=task_id, reasoning_effort="low",
                               messages=[{"role": "user", "content": prompt}], tools=[])
        return [chunk async for chunk in stream]

    success = await collect("mercury-3", SUCCESS_PROMPT, "success-task")
    assert success[0] == SUCCESS_RESPONSE
    assert success[1].input_tokens == 100
    fallback = LOW_FALLBACK_MODEL.split("/", 1)[1]
    kwargs = {"model_id": fallback, "stream": True, "task_id": "fallback-task",
              "messages": [{"role": "user", "content": FALLBACK_PROMPT}]}
    assert llm_fixture(f"llm/{fallback}", kwargs) is None
    with pytest.raises(InceptionError, match="503"):
        await collect("mercury-3", FALLBACK_PROMPT, "fallback-task")
    assert llm_fixture(f"llm/{fallback}", {**kwargs, "task_id": "unrelated-task"}) is None
    recovered = await collect(fallback, FALLBACK_PROMPT, "fallback-task")
    assert recovered[0] == FALLBACK_RESPONSE
    assert recovered[1].prompt_token_count == 100
    assert llm_fixture(f"llm/{fallback}", kwargs) is None


def test_unrelated_or_changed_classifier_request_is_rejected(replay):
    question = {"complexity": {"type": "choice", "criteria": {"medium": "Moderate"}}}
    assert jev_response({"user_message": SUCCESS_PROMPT}, question, "jev-1.13") is None
    assert jev_response({"user_message": "unrelated request"}, question, "jev-1.13") is None
    token = mock_group_var.set("unrelated")
    try:
        assert not active()
    finally:
        mock_group_var.reset(token)


def test_disabled_model_path_forbids_mercury_and_admits_native_gemini(replay):
    kwargs = {"model_id": "mercury-3", "stream": True, "task_id": "disabled-task",
              "reasoning_effort": "low", "messages": [{"role": "user", "content": DISABLED_PROMPT}]}
    with pytest.raises(AssertionError, match="disabled Mercury"):
        llm_fixture("llm/mercury-3", kwargs)
    fallback = LOW_FALLBACK_MODEL.split("/", 1)[1]
    packet = llm_fixture(f"llm/{fallback}", {**kwargs, "model_id": fallback})
    assert packet["response"]["chunks"][0]["value"] == DISABLED_RESPONSE


def test_isolated_internal_allowlist_never_permits_provider_http(replay, monkeypatch):
    monkeypatch.setenv("CMS_URL", "http://cms:8055")
    monkeypatch.setenv("VAULT_URL", "http://vault:8200")
    for key in ("S3_ENDPOINT_URL", "OPENMATES_STORAGE_CAPACITY_FIXTURES", "HTTPS_PROXY"):
        monkeypatch.delenv(key, raising=False)
    receipt = live_mock_receipt_var.set(_LiveMockReceiptState(mode="mock", run_id=None, task_id="routing-test"))
    try:
        assert _allow_isolated_capacity_internal("http://cms:8055/items/users", "GET")
        assert _allow_isolated_capacity_internal("http://vault:8200/v1/auth/token/lookup-self", "GET")
        assert _allow_isolated_capacity_internal("http://api:8000/internal/billing/reserve", "POST")
        assert not _allow_isolated_capacity_internal("https://api.inceptionlabs.ai/v1/chat/completions", "POST")
        assert not _allow_isolated_capacity_internal("http://api:8000/v1/apps/ai/ask", "POST")
    finally:
        live_mock_receipt_var.reset(receipt)
