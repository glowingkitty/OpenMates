"""Fail-closed synthetic capacity replay and direct compression dispatch tests."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.apps.ai.testing.capacity_fixtures import generate_fixture
from backend.apps.ai.sub_chat_orchestration import signed_capacity_child_prompt, signed_capacity_replay_marker
from backend.apps.ai.testing.caching_llm_wrapper import replay_capacity_direct_provider, wrap_provider_with_cache
from backend.shared.testing.api_response_cache import ApiResponseCache, MockCacheMiss
from backend.shared.testing.mock_context import (
    DailyAITestBudgetExceeded, activate_mock_mode, deactivate_mock_mode,
    get_live_mock_receipt,
    detect_live_marker,
)
from backend.shared.testing import mock_context


COMPRESS_MESSAGES = [
    {"role": "system", "content": "You are a conversation compression assistant. Your task is to create a structured summary."},
    {"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:round synthetic detail"},
]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
async def test_capacity_compression_replays_without_provider_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", "true")
    monkeypatch.setattr("backend.shared.testing.api_response_cache.get_shared_cache", lambda: ApiResponseCache(root=tmp_path))
    calls = 0

    async def real_provider(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Provider dispatch must be impossible")

    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        response = await replay_capacity_direct_provider(
            real_provider, model_id="gemini-3.5-flash-lite", messages=COMPRESS_MESSAGES, stream=False,
        )
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()

    assert response.success is True
    assert response.direct_message_content.startswith("## Conversation History Summary")
    assert receipt["cache_hits"] == 1
    assert receipt["real_provider_calls"] == 0
    assert calls == 0


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
async def test_uncovered_capacity_compression_fails_before_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", "true")
    monkeypatch.setattr("backend.shared.testing.api_response_cache.get_shared_cache", lambda: ApiResponseCache(root=tmp_path))
    calls = 0

    async def real_provider(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Provider dispatch must be impossible")

    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        with pytest.raises(MockCacheMiss):
            await replay_capacity_direct_provider(
                real_provider, model_id="gemini-3.5-flash-lite",
                messages=[{"role": "system", "content": "uncovered phase"}], stream=False,
            )
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()
    assert calls == 0
    assert receipt["cache_misses"] == 1
    assert receipt["blocked_provider_calls"] == 1
    assert receipt["real_provider_calls"] == 0


# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_capacity_group_rejects_record_and_real_modes() -> None:
    for mode in ("record", "real"):
        with pytest.raises(DailyAITestBudgetExceeded, match="replay-only"):
            activate_mock_mode(mode, "storage_capacity_v1")
    deactivate_mock_mode()


# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_child_marker_is_signed_only_from_active_capacity_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "disposable-unit-secret")
    request = SimpleNamespace(user_id="disposable-user", live_mock_mode="mock", live_mock_group="storage_capacity_v1")
    prompt = "STORAGE_CAPACITY_SCENARIO:child_worker"
    assert signed_capacity_child_prompt(prompt, request) == prompt
    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        signed = signed_capacity_child_prompt(prompt, request)
    finally:
        deactivate_mock_mode()
    assert detect_live_marker(signed, request.user_id) is not None
    assert detect_live_marker(signed, "other-user") is None


# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_pending_continuation_marker_is_bound_to_original_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "disposable-unit-secret")
    request = SimpleNamespace(user_id="disposable-user", live_mock_mode="mock", live_mock_group="storage_capacity_v1")
    assert signed_capacity_replay_marker(request, ttl_seconds=3600) is None
    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        marker = signed_capacity_replay_marker(request, ttl_seconds=3600)
    finally:
        deactivate_mock_mode()
    assert marker is not None
    assert detect_live_marker(marker, request.user_id).group_id == "storage_capacity_v1"
    assert detect_live_marker(marker, "other-user") is None


# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_generated_fixture_requires_known_phase_and_scenario() -> None:
    assert generate_fixture("llm/gemini-3.5-flash-lite", {"messages": [{"role": "user", "content": "unmarked"}]}) is None
    fixture = generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:tool"}],
        "tools": [{"function": {"name": "analyze_request_properties"}}],
    })
    call = fixture["response"]["chunks"][0]["value"]
    assert call["function_name"] == "analyze_request_properties"
    assert call["function_arguments_parsed"]["relevant_app_skills"] == ["math-calculate"]
    assert generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:child"}],
    }) is None


# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_generated_child_dispatch_and_completion_are_separate_phases() -> None:
    tools = [{"function": {"name": "start_sub_chats"}}]
    messages = [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:child"}]
    proposed = generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite", "messages": messages, "tools": tools,
    })
    call = proposed["response"]["chunks"][0]["value"]
    assert call["function_name"] == "start_sub_chats"
    assert "STORAGE_CAPACITY_SCENARIO:child_worker" in call["function_arguments_parsed"]["sub_chats"][0]["prompt"]
    assert "TEST_LIVE_MOCK" not in call["function_arguments_parsed"]["sub_chats"][0]["prompt"]
    child = generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": call["function_arguments_parsed"]["sub_chats"][0]["prompt"]}],
        "tools": [],
    })
    assert child["response"] == {
        "type": "stream", "body": "Synthetic child storage result.",
    }
    assert generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:child_unknown"}],
        "tools": [],
    }) is None
    completed = generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [*messages, {"role": "tool", "content": '{"status":"spawned"}'},
                     {"role": "system", "content": "Synthetic child storage result."}],
        "tools": tools,
    })
    assert completed["response"]["type"] == "stream"


# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_generated_parent_continuation_has_final_answer_without_child_redispatch() -> None:
    response = generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [
            {"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:child"},
            {"role": "user", "content": (
                "FINAL ANSWER TASK: The waited sub-chats have completed.\n"
                "Original user request: STORAGE_CAPACITY_SCENARIO:child\n"
                "Synthetic child storage result."
            )},
        ],
        "tools": [{"function": {"name": "start_sub_chats"}}],
    })
    assert response["response"]["type"] == "stream"
    assert response["response"]["body"].startswith("Synthetic child result")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
async def test_generated_preprocess_and_stream_keep_provider_unreached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", "true")
    calls = 0

    async def provider(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Synthetic replay must not dispatch")

    wrapped = wrap_provider_with_cache(provider, ApiResponseCache(root=tmp_path))
    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        prompt = [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:round"}]
        preprocess = await wrapped(model="gemini-3.5-flash-lite", messages=prompt,
                                   tools=[{"function": {"name": "analyze_request_properties"}}], stream=True)
        chunks = [chunk async for chunk in preprocess]
        assert chunks[0].function_name == "analyze_request_properties"
        main = await wrapped(model="gemini-3.5-flash-lite", messages=prompt, stream=True)
        answer = "".join([chunk async for chunk in main])
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()
    assert answer.startswith("Synthetic storage response")
    assert receipt["cache_hits"] == 2
    assert receipt["cache_misses"] == 0
    assert calls == 0


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=storage.validation.synthetic-capacity
async def test_actual_gemini_nonstream_preprocessing_replays_and_unknowns_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", "true")
    calls = 0

    async def provider(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Provider dispatch must be impossible")

    wrapped = wrap_provider_with_cache(provider, ApiResponseCache(root=tmp_path))
    prompt = [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:round synthetic detail"}]
    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        response = await wrapped(
            model_id="gemini-3.5-flash-lite", messages=prompt,
            tools=[{"function": {"name": "analyze_request_properties"}}],
            tool_choice="required", stream=False,
        )
        assert response.success is True
        assert response.tool_calls_made[0].function_name == "analyze_request_properties"
        assert response.tool_calls_made[0].function_arguments_parsed["title"] == "Synthetic Storage Capacity Chat"
        postprocess = await wrapped(
            model_id="gemini-3.5-flash-lite",
            messages=[
                {"role": "system", "content": "Generate suggestions and metadata after the answer."},
                {"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:round synthetic detail"},
                {"role": "assistant", "content": "Synthetic storage response."},
            ],
            tools=[{"function": {"name": "generate_suggestions_and_metadata"}}],
            tool_choice="required", stream=False,
        )
        assert postprocess.success is True
        assert postprocess.tool_calls_made[0].function_name == "generate_suggestions_and_metadata"
        assert postprocess.tool_calls_made[0].function_arguments_parsed["chat_summary"].startswith(
            "Synthetic storage response"
        )
        with pytest.raises(MockCacheMiss):
            await wrapped(
                model_id="gemini-3.5-flash-lite", messages=prompt,
                tools=[{"function": {"name": "unknown_tool"}}],
                tool_choice="required", stream=False,
            )
        with pytest.raises(MockCacheMiss):
            await wrapped(
                model_id="unlisted-gemini-model", messages=prompt,
                tools=[{"function": {"name": "analyze_request_properties"}}],
                tool_choice="required", stream=False,
            )
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()
    assert calls == 0
    assert receipt["cache_hits"] == 2
    assert receipt["cache_misses"] == 2
    assert receipt["blocked_provider_calls"] == 2
    assert receipt["real_provider_calls"] == 0


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=storage.validation.synthetic-capacity
async def test_signed_isolated_capacity_allows_only_exact_internal_http_transports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "MOCK_EXTERNAL_APIS": "true",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
        "CMS_URL": "http://cms:8055",
        "VAULT_URL": "http://vault:8200",
        "SERVER_ENVIRONMENT": "development",
    }.items():
        monkeypatch.setenv(key, value)
    dispatched: list[str] = []

    async def fake_async(_transport, request):
        dispatched.append(str(request.url))
        return httpx.Response(204, request=request)

    def fake_sync(_transport, request):
        dispatched.append(str(request.url))
        return httpx.Response(204, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_sync)
    activate_mock_mode("mock", "storage_capacity_v1", task_id="synthetic-capacity-task")
    try:
        mock_context._install_httpx_transport_guard()
        allowed = await httpx.AsyncHTTPTransport.handle_async_request(
            object(), httpx.Request("GET", "http://cms:8055/items/chats"),
        )
        assert allowed.status_code == 204
        vault = await httpx.AsyncHTTPTransport.handle_async_request(
            object(), httpx.Request("GET", "http://vault:8200/v1/kv/data/providers/openrouter"),
        )
        assert vault.status_code == 204
        with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
            await httpx.AsyncHTTPTransport.handle_async_request(
                object(), httpx.Request("GET", "https://generativelanguage.googleapis.com/v1/models"),
            )
        with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
            await httpx.AsyncHTTPTransport.handle_async_request(
                object(), httpx.Request("GET", "http://cms.example.com:8055/items/chats"),
            )
        for url in (
            "http://vault.example.com:8200/v1/kv/data/providers/openrouter",
            "http://vault:8200@evil.example/v1/kv/data/providers/openrouter",
            "http://vault:8200/not-v1/kv/data/providers/openrouter",
            "https://vault:8200/v1/kv/data/providers/openrouter",
        ):
            with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
                await httpx.AsyncHTTPTransport.handle_async_request(
                    object(), httpx.Request("GET", url),
                )
        monkeypatch.setenv("OPENMATES_CI_ISOLATED", "0")
        for url in ("http://cms:8055/items/chats", "http://vault:8200/v1/auth/token/lookup-self"):
            with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
                await httpx.AsyncHTTPTransport.handle_async_request(
                    object(), httpx.Request("GET", url),
                )
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()
    assert dispatched == [
        "http://cms:8055/items/chats",
        "http://vault:8200/v1/kv/data/providers/openrouter",
    ]
    assert receipt["blocked_provider_calls"] == 8
    assert receipt["real_provider_calls"] == 0
