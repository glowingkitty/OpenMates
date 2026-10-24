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
from backend.apps.ai.processing.model_routing import LOW_FALLBACK_MODEL, MERCURY_MODEL
from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.testing.mercury_routing_fixture import (
    GROUP, SUCCESS_PROMPT, FALLBACK_PROMPT, SUCCESS_RESPONSE, FALLBACK_RESPONSE,
    DISABLED_PROMPT, DISABLED_RESPONSE, HIGH_PROMPT, HIGH_RESPONSE,
    EXTRA_HIGH_PROMPT, EXTRA_HIGH_RESPONSE, HIGH_RECOVERY_PROMPT, HIGH_RECOVERY_RESPONSE,
    GEMINI_RETRY_PROMPT, GEMINI_RETRY_RESPONSE, CHEAP_FALLBACK_PROMPT, CHEAP_FALLBACK_RESPONSE,
    WEB_RESEARCH_PROMPT, WEB_RESEARCH_RESPONSE,
    WEB_THROTTLE_PROMPT, WEB_THROTTLE_RESPONSE,
    active, jev_response, llm_fixture,
)
from backend.apps.ai.utils.answer_recovery import ANSWER_RECOVERY_INSTRUCTION, build_answer_recovery_history
from backend.shared.providers.inception import InceptionError
from backend.shared.providers.typesafe import budget as jev_budget
from backend.shared.testing.api_response_cache import ApiResponseCache, MockCacheMiss
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
@pytest.mark.parametrize("prompt,complexity,recommendation", [
    (SUCCESS_PROMPT, "low", None), (HIGH_PROMPT, "low", "high"),
    (EXTRA_HIGH_PROMPT, "low", "extra_high"),
    (HIGH_RECOVERY_PROMPT, "medium", "extra_high"),
])
async def test_actual_jev_questions_separate_complexity_from_reasoning(replay, prompt, complexity, recommendation):
    history = [{"role": "user", "content": prompt}]
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
    assert selected["complexity"] == complexity
    assert selected["reasoning_level"] == recommendation
    assert selected["relevant_app_skills"] == []


@pytest.mark.asyncio
async def test_wrapper_delivers_typed_success_and_requires_real_failure_before_fallback(replay, tmp_path: Path):
    async def forbidden_provider(**_kwargs):
        raise AssertionError("routing fixture must never dispatch a real provider")

    wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))
    async def collect(model, prompt, task_id):
        stream = await wrapped(model_id=model, stream=True, task_id=task_id, reasoning_effort="medium",
                               thinking_level="LOW", max_tokens=16384, messages=[{"role": "user", "content": prompt}], tools=[])
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


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt,count,answer", [
    (WEB_RESEARCH_PROMPT, 1, WEB_RESEARCH_RESPONSE),
    (WEB_THROTTLE_PROMPT, 4, WEB_THROTTLE_RESPONSE),
])
async def test_web_research_replay_requires_capability_and_real_tool_result(replay, tmp_path, prompt, count, answer):
    async def forbidden_provider(**_kwargs):
        raise AssertionError("Web research replay must never dispatch a real provider")

    wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))
    model = LOW_FALLBACK_MODEL.split("/", 1)[1]
    history = [{"role": "user", "content": prompt}]
    kwargs = dict(model_id=model, stream=True, task_id="web-research-test", messages=history)
    with pytest.raises(AssertionError, match="without web search"):
        llm_fixture(f"llm/{model}", kwargs)
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    with pytest.raises(AssertionError, match="without baseline image search"):
        llm_fixture(f"llm/{model}", {**kwargs, "tools": tools})
    tools.append({"type": "function", "function": {"name": "images-search"}})
    stream = await wrapped(**kwargs, tools=tools)
    chunks = [chunk async for chunk in stream]
    assert chunks[0].function_name == "web_search"
    requests = chunks[0].function_arguments_parsed["requests"]
    assert len(requests) == count
    assert requests[0]["query"].startswith("openmates_e2e_web_fixture_ai")
    if count == 4:
        assert len({request["query"] for request in requests}) == 4
        assert all(" throttle " in request["query"] for request in requests)
    result = {"role": "tool", "tool_call_id": "web-research-search", "content": "error"}
    with pytest.raises(AssertionError, match="real search skill"):
        llm_fixture(f"llm/{model}", {**kwargs, "tools": tools, "messages": [*history, result]})
    result["content"] = "OpenMates E2E Web Fixture"
    stream = await wrapped(**{**kwargs, "messages": [*history, result]}, tools=tools)
    assert [chunk async for chunk in stream][0] == answer


def test_disabled_model_path_forbids_mercury_and_admits_native_gemini(replay):
    kwargs = {"model_id": "mercury-3", "stream": True, "task_id": "disabled-task",
              "reasoning_effort": "medium", "thinking_level": "LOW", "messages": [{"role": "user", "content": DISABLED_PROMPT}]}
    with pytest.raises(AssertionError, match="disabled Mercury"):
        llm_fixture("llm/mercury-3", kwargs)
    fallback = LOW_FALLBACK_MODEL.split("/", 1)[1]
    packet = llm_fixture(f"llm/{fallback}", {**kwargs, "model_id": fallback})
    assert packet["response"]["chunks"][0]["value"] == DISABLED_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt,expected", [
    (GEMINI_RETRY_PROMPT, GEMINI_RETRY_RESPONSE),
    (CHEAP_FALLBACK_PROMPT, CHEAP_FALLBACK_RESPONSE),
    (HIGH_RECOVERY_PROMPT, HIGH_RECOVERY_RESPONSE),
])
async def test_recovery_fixture_handles_actual_published_prefix_history(replay, tmp_path: Path, prompt, expected):
    async def forbidden_provider(**_kwargs):
        raise AssertionError("Recovery replay must never dispatch a real provider")

    wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))
    task_id = f"recovery-{prompt}"
    messages = [{"role": "user", "content": prompt}]

    async def collect(model, history):
        high = prompt == HIGH_RECOVERY_PROMPT
        stream = await wrapped(model_id=model, stream=True, task_id=task_id,
                               reasoning_effort="high" if high else "medium",
                               thinking_level="HIGH" if high else "MEDIUM",
                               max_tokens=32768 if high else 16384, messages=history, tools=[], tool_choice="none")
        return [chunk async for chunk in stream]

    gemini = LOW_FALLBACK_MODEL.split("/", 1)[1]
    initial = await collect(gemini, messages)
    assert initial[0].startswith("Verified prefix.")
    history = [{"role": "system", "content": ANSWER_RECOVERY_INSTRUCTION},
               *build_answer_recovery_history(messages, prompt, max_tokens=1000,
                                              published_prefix="Verified prefix.")]
    with pytest.raises(MockCacheMiss):
        await collect(gemini, [*history, {"role": "user", "content": "An unrelated later request"}])
    retried = await collect(gemini, history)
    if prompt == GEMINI_RETRY_PROMPT:
        assert retried[0] == expected
    else:
        assert "```toon" in retried[0]
        recovered = await collect(MERCURY_MODEL.split("/", 1)[1], history)
        assert recovered[0] == expected


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


@pytest.mark.asyncio
async def test_low_complexity_high_recommendation_and_extra_high_fallback(replay, tmp_path: Path):
    async def forbidden_provider(**_kwargs):
        raise AssertionError("Reasoning replay must never dispatch a real provider")

    wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))

    async def collect(model, prompt, task_id, **policy):
        stream = await wrapped(model_id=model, stream=True, task_id=task_id,
                               messages=[{"role": "user", "content": prompt}], tools=[], **policy)
        return [chunk async for chunk in stream]

    success = await collect("mercury-3", HIGH_PROMPT, "high-task", reasoning_effort="high", max_tokens=32768)
    assert success[0] == HIGH_RESPONSE
    with pytest.raises(InceptionError, match="503"):
        await collect("mercury-3", EXTRA_HIGH_PROMPT, "extra-high-task",
                      reasoning_effort="high", max_tokens=32768)
    recovered = await collect(LOW_FALLBACK_MODEL.split("/", 1)[1], EXTRA_HIGH_PROMPT,
                              "extra-high-task", thinking_level="HIGH")
    assert recovered[0] == EXTRA_HIGH_RESPONSE


@pytest.mark.parametrize("policy", [
    {"reasoning_effort": "low", "max_tokens": 8192},
    {"reasoning_effort": "medium", "max_tokens": 32768},
    {"reasoning_effort": "high", "max_tokens": 32768},
])
def test_default_medium_fixture_rejects_changed_provider_policy(replay, policy):
    with pytest.raises(AssertionError, match="Mercury must use"):
        llm_fixture("llm/mercury-3", {
            "model_id": "mercury-3", "stream": True, "task_id": "wrong-policy",
            "messages": [{"role": "user", "content": SUCCESS_PROMPT}], **policy,
        })


@pytest.mark.parametrize("group", ["web_search_web", "web_search_zero_results"])
@pytest.mark.parametrize("key,value", [
    ("SERVER_ENVIRONMENT", "production"), ("SERVER_ENVIRONMENT", "prod"),
    ("MOCK_EXTERNAL_APIS", "false"), ("CI", "false"),
    ("OPENMATES_CI_ISOLATED", "0"), ("OPENMATES_CI_AI_FIXTURES", "0"),
])
def test_legacy_web_groups_preserve_all_isolation_guards(replay, monkeypatch, group, key, value):
    token = mock_group_var.set(group)
    try:
        assert active()
        monkeypatch.setenv(key, value)
        assert not active()
    finally:
        mock_group_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("group", ["web_search_web", "web_search_zero_results"])
async def test_legacy_web_group_classification_accepts_only_its_visible_prompt(replay, group):
    from backend.apps.ai.testing.mercury_routing_fixture import LEGACY_WEB_PROMPTS
    token = mock_group_var.set(group)
    try:
        question = {"complexity": {"type": "choice", "criteria": {"low": "Simple", "medium": "Moderate"}}}
        for other_group, prompt in LEGACY_WEB_PROMPTS.items():
            response = jev_response({"user_message": prompt}, question, "jev-1.13")
            if other_group == group:
                assert response.answers["complexity"].choice == "medium"
            else:
                assert response is None
        assert jev_response({"user_message": SUCCESS_PROMPT}, question, "jev-1.13") is None
        history = [{"role": "user", "content": LEGACY_WEB_PROMPTS[group]}]
        routing = await decide_app_and_project_routing_with_jev(
            model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
            available_apps=["web", "shopping"], available_skills=[], available_focus_modes=[],
            topic_areas=["general_misc"], is_first_message=True,
        )
        assert routing["selected_app_ids"] == []
    finally:
        mock_group_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("group", ["web_search_web", "web_search_zero_results"])
@pytest.mark.parametrize("model", ["mercury-3", "gemini-3.8-flash", "gemini-4-argon"])
async def test_legacy_web_automatic_packets_consume_real_search_skill(replay, tmp_path, group, model):
    from toon_format import encode
    from backend.apps.ai.testing.mercury_routing_fixture import (
        LEGACY_WEB_PROMPTS, LEGACY_WEB_RESPONSE, LEGACY_ZERO_RESPONSE,
    )
    from backend.apps.web.skills.search_skill import SearchSkill
    from backend.shared.python_utils.app_skill_output_safety import central_app_skill_dispatch

    async def forbidden_provider(**_kwargs):
        raise AssertionError("Legacy web replay must never dispatch a real LLM provider")

    token = mock_group_var.set(group)
    try:
        wrapped = wrap_provider_with_cache(forbidden_provider, ApiResponseCache(root=tmp_path))
        history = [{"role": "user", "content": LEGACY_WEB_PROMPTS[group]}]
        kwargs = dict(model_id=model, stream=True, task_id=f"legacy-{group}-{model}", messages=history)
        assert llm_fixture(f"llm/{model}", {**kwargs, "task_id": None}) is None
        with pytest.raises(AssertionError, match="without web search"):
            llm_fixture(f"llm/{model}", kwargs)
        tools = [{"type": "function", "function": {"name": "web-search"}}]
        with pytest.raises(AssertionError, match="without baseline image search"):
            llm_fixture(f"llm/{model}", {**kwargs, "tools": tools})
        tools.append({"type": "function", "function": {"name": "images_search"}})
        stream = await wrapped(**kwargs, tools=tools)
        chunks = [chunk async for chunk in stream]
        call = chunks[0]
        assert type(call).__name__ == "ParsedOpenAIToolCall"
        assert call.function_name == "web-search"
        expected = ({"query": "openmates_e2e_web_fixture_ai", "count": 2} if group == "web_search_web"
                    else {"query": "xyznonexistentproduct123456 lokale API MQTT"})
        assert call.function_arguments_parsed == {"requests": [expected]}
        unrelated = {"role": "tool", "tool_call_id": "unrelated", "content": "OpenMates E2E Web Fixture"}
        with pytest.raises(AssertionError, match="matching real search"):
            llm_fixture(f"llm/{model}", {**kwargs, "tools": tools, "messages": [*history, unrelated]})
        skill = SearchSkill(app=None, app_id="web", skill_id="search", skill_name="Search the web",
                            skill_description="Find web results.")
        with central_app_skill_dispatch():
            response = await skill.execute(requests=call.function_arguments_parsed["requests"], secrets_manager=object())
        assert response.error is None
        results = [result for request in response.results for result in request["results"]]
        assert len(results) == (2 if group == "web_search_web" else 0)
        # Match main_processor's normalization before provider inference, including
        # source metadata and hints which must not affect empty-result recognition.
        payload = {"results": results, "count": len(results), "embed_ref_hint": "Use readable display text."}
        result = {"role": "tool", "tool_call_id": call.tool_call_id, "content": encode(payload)}
        stream = await wrapped(**{**kwargs, "messages": [*history, result]}, tools=tools)
        assert [chunk async for chunk in stream][0] == (LEGACY_WEB_RESPONSE if results else LEGACY_ZERO_RESPONSE)
        for bad in ({"error": "provider failed", "results": [], "count": 0},
                    {"results": [], "count": 1}, {"results": []}, {"message": "no results"}):
            with pytest.raises(AssertionError):
                llm_fixture(f"llm/{model}", {**kwargs, "tools": tools,
                    "messages": [*history, {**result, "content": encode(bad)}]})
        metadata = await wrapped(model_id=model, stream=False, task_id=kwargs["task_id"], messages=history,
                                 tools=[{"type": "function", "function": {"name": "generate_suggestions_and_metadata"}}],
                                 tool_choice="required")
        assert type(metadata).__name__ == "UnifiedOpenAIResponse"
        assert metadata.success
        assert metadata.tool_calls_made[0].function_arguments_parsed["updated_chat_title"] == "Web search results"
    finally:
        mock_group_var.reset(token)
