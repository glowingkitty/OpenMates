"""Fail-closed synthetic capacity replay and direct compression dispatch tests."""

import json
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
    assert child["response"]["type"] == "mixed_stream"
    assert child["response"]["chunks"][0] == {"kind": "text", "value": "Synthetic child storage result."}
    assert child["response"]["chunks"][-1]["class"] == "GoogleUsageMetadata"
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
    assert completed["response"]["type"] == "mixed_stream"


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
    assert response["response"]["type"] == "mixed_stream"
    assert response["response"]["chunks"][0]["value"].startswith("Synthetic child result")
    assert response["response"]["chunks"][-1]["class"] == "GoogleUsageMetadata"


@pytest.mark.parametrize("scenario,tools,expected_first", [
    ("recovery_embed", [], "text"),
    ("recovery_diff", [], "text"),
    ("tool", [{"function": {"name": "math-calculate"}}], "pydantic"),
    ("child", [{"function": {"name": "start_sub_chats"}}], "pydantic"),
])
# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_successful_main_replay_reports_one_billable_usage_event(scenario, tools, expected_first) -> None:
    fixture = generate_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": f"STORAGE_CAPACITY_SCENARIO:{scenario}"}],
        "tools": tools,
    })
    chunks = fixture["response"]["chunks"]
    assert fixture["response"]["type"] == "mixed_stream"
    assert chunks[0]["kind"] == expected_first
    assert len(chunks) == 2
    assert chunks[1]["class"] == "GoogleUsageMetadata"
    assert chunks[1]["value"]["prompt_token_count"] == 100
    assert chunks[1]["value"]["candidates_token_count"] == 40
    assert chunks[1]["value"]["total_token_count"] == 140


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
        main_chunks = [chunk async for chunk in main]
        tool = await wrapped(
            model="gemini-3.5-flash-lite",
            messages=[{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:tool"}],
            tools=[{"function": {"name": "math-calculate"}}], stream=True,
        )
        tool_chunks = [chunk async for chunk in tool]
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()
    assert main_chunks[0].startswith("Synthetic storage response")
    assert type(main_chunks[-1]).__name__ in {"GoogleUsageMetadata", "OpenAIUsageMetadata"}
    assert (getattr(main_chunks[-1], "prompt_token_count", None)
            or getattr(main_chunks[-1], "input_tokens", None)) == 100
    assert (getattr(main_chunks[-1], "candidates_token_count", None)
            or getattr(main_chunks[-1], "output_tokens", None)) == 40
    assert tool_chunks[0].function_name == "math-calculate"
    assert type(tool_chunks[-1]) is type(main_chunks[-1])
    assert receipt["cache_hits"] == 3
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
        if request.url.path in {"/internal/billing/charge", "/internal/billing/team/charge"}:
            payload = json.loads(request.content) if request.content else {}
            return httpx.Response(200, json={
                "state": "committed", "charge_id": payload.get("idempotency_key"),
                "charged_credits": 1, "requested_credits": payload.get("credits"),
            }, request=request)
        return httpx.Response(204, request=request)

    def fake_sync(_transport, request):
        dispatched.append(str(request.url))
        return httpx.Response(204, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_sync)
    activate_mock_mode("mock", "storage_capacity_v1", task_id="synthetic-capacity-task")
    try:
        mock_context._install_httpx_transport_guard()
        billing_urls = [
            "http://api:8000/internal/billing/reserve",
            "http://api:8000/internal/billing/team/reserve",
            "http://api:8000/internal/billing/reservation/release",
            "http://api:8000/internal/billing/reservation/record-intent",
            "http://api:8000/internal/billing/charge",
            "http://api:8000/internal/billing/team/charge",
        ]
        allowed = await httpx.AsyncHTTPTransport.handle_async_request(
            object(), httpx.Request("GET", "http://cms:8055/items/chats"),
        )
        assert allowed.status_code == 204
        vault = await httpx.AsyncHTTPTransport.handle_async_request(
            object(), httpx.Request("GET", "http://vault:8200/v1/kv/data/providers/openrouter"),
        )
        assert vault.status_code == 204
        for url in billing_urls:
            response = await httpx.AsyncHTTPTransport.handle_async_request(
                object(), httpx.Request("POST", url),
            )
            assert response.status_code == (200 if url.endswith("/charge") else 204)
        sync_response = httpx.HTTPTransport.handle_request(
            object(), httpx.Request("POST", billing_urls[0]),
        )
        assert sync_response.status_code == 204
        from backend.apps.ai.tasks import stream_consumer
        monkeypatch.setattr(stream_consumer, "INTERNAL_API_BASE_URL", "http://api:8000")
        request_data = SimpleNamespace(
            root_chat_id=None, chat_id="disposable-chat", root_turn_id=None,
            orchestration_id=None, sub_chat_depth=0, user_id="disposable-user",
            user_id_hash="disposable-owner-hash", api_key_hash=None, device_hash=None,
            team_id=None, benchmark_metadata=None,
        )
        settlement = await stream_consumer._charge_credits(
            "synthetic-capacity-task", request_data, 1,
            {"input_tokens": 100, "output_tokens": 40}, "[isolated-capacity-test]",
        )
        assert settlement["settlement_state"] == "settled"
        assert settlement["total_credits"] == 1
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
        blocked_billing = (
            ("GET", billing_urls[0]),
            ("DELETE", billing_urls[2]),
            ("GET", billing_urls[4]),
            ("POST", "http://api:8000/internal/billing/reserve/extra"),
            ("POST", "http://api:8000/internal/billing/reserve?override=1"),
            ("POST", "http://api:8000/internal/billing/reservation/record-intent?override=1"),
            ("POST", "http://api:8000/internal/billing/charge?override=1"),
            ("POST", "http://api.evil:8000/internal/billing/reserve"),
            ("POST", "http://api.evil:8000/internal/billing/reservation/record-intent"),
            ("POST", "http://api.evil:8000/internal/billing/charge"),
            ("POST", "http://api:8000@evil.example/internal/billing/reserve"),
            ("POST", "https://api:8000/internal/billing/reserve"),
        )
        for method, url in blocked_billing:
            with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
                await httpx.AsyncHTTPTransport.handle_async_request(
                    object(), httpx.Request(method, url),
                )
        monkeypatch.setenv("OPENMATES_CI_ISOLATED", "0")
        for method, url in (
            ("GET", "http://cms:8055/items/chats"),
            ("GET", "http://vault:8200/v1/auth/token/lookup-self"),
            ("POST", billing_urls[0]),
        ):
            with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
                await httpx.AsyncHTTPTransport.handle_async_request(
                    object(), httpx.Request(method, url),
                )
        receipt = get_live_mock_receipt()
    finally:
        deactivate_mock_mode()
    assert dispatched == [
        "http://cms:8055/items/chats",
        "http://vault:8200/v1/kv/data/providers/openrouter",
        *billing_urls,
        billing_urls[0],
        billing_urls[4],
    ]
    assert receipt["blocked_provider_calls"] == 21
    assert receipt["real_provider_calls"] == 0


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=storage.validation.synthetic-capacity
async def test_capacity_billing_transport_keeps_receipt_origin_and_redirect_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aiohttp = pytest.importorskip("aiohttp")
    requests = pytest.importorskip("requests")
    for key, value in {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "MOCK_EXTERNAL_APIS": "true",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
        "CMS_URL": "http://cms:8055",
        "VAULT_URL": "http://vault:8200",
        "INTERNAL_API_BASE_URL": "http://api:8000",
        "SERVER_ENVIRONMENT": "development",
    }.items():
        monkeypatch.setenv(key, value)
    billing_url = "http://api:8000/internal/billing/reserve"

    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        assert not mock_context._allow_isolated_capacity_internal(billing_url, "POST")
    finally:
        deactivate_mock_mode()

    activate_mock_mode("mock", "storage_capacity_v1", task_id="synthetic-capacity-task")
    try:
        assert mock_context._allow_isolated_capacity_internal(billing_url, "POST")
        monkeypatch.setenv("INTERNAL_API_BASE_URL", "http://api.evil:8000")
        assert not mock_context._allow_isolated_capacity_internal(billing_url, "POST")
        monkeypatch.setenv("INTERNAL_API_BASE_URL", "http://api:8000")

        async def fake_aiohttp_request(_session, _method, _url, **kwargs):
            return kwargs

        def fake_requests_request(_session, _method, _url, **kwargs):
            return kwargs

        def fake_requests_send(_session, _request, **kwargs):
            return kwargs

        monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_aiohttp_request)
        monkeypatch.setattr(requests.sessions.Session, "request", fake_requests_request)
        monkeypatch.setattr(requests.sessions.Session, "send", fake_requests_send)
        mock_context._install_aiohttp_request_guard()
        mock_context._install_requests_request_guard()

        aiohttp_options = await aiohttp.ClientSession._request(
            object(), "POST", billing_url, allow_redirects=True,
        )
        assert aiohttp_options["allow_redirects"] is False
        requests_options = requests.sessions.Session.request(
            object(), "POST", billing_url, allow_redirects=True,
        )
        assert requests_options["allow_redirects"] is False
        prepared = requests.Request("POST", billing_url).prepare()
        send_options = requests.sessions.Session.send(
            object(), prepared, allow_redirects=True,
        )
        assert send_options["allow_redirects"] is False
        with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
            await aiohttp.ClientSession._request(
                object(), "POST", "http://api.evil:8000/internal/billing/reserve",
            )
        with pytest.raises(DailyAITestBudgetExceeded, match="raw HTTP provider dispatch"):
            requests.sessions.Session.send(
                object(), requests.Request("POST", "https://provider.example/reserve").prepare(),
            )
    finally:
        deactivate_mock_mode()
