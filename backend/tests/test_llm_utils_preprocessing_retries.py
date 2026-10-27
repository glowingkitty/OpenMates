# contract-test-file: infrastructure
# backend/tests/test_llm_utils_preprocessing_retries.py
#
# Purpose: ensure bounded output-safety preprocessing controls provider retry
# behavior and caps the total fallback-chain latency.
# Architecture: specifications/architecture/app-skill-execution/specification.yml

import asyncio

import pytest

try:
    from backend.apps.ai.llm_providers.openai_shared import (
        ParsedOpenAIToolCall,
        UnifiedOpenAIResponse,
        OpenAIUsageMetadata,
    )
    from backend.apps.ai.utils import llm_utils
except ImportError as exc:
    pytest.skip(f"Backend AI dependencies not installed: {exc}", allow_module_level=True)


def _tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "expected_tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
@pytest.mark.parametrize(
    "provider_response, expected_error",
    [
        (
            UnifiedOpenAIResponse(
                task_id="test",
                model_id="primary/model",
                success=False,
                error_message="Request timeout after 25s",
            ),
            "Client call failed for preprocessing: Request timeout after 25s",
        ),
        (
            UnifiedOpenAIResponse(
                task_id="test",
                model_id="primary/model",
                success=True,
                tool_calls_made=[
                    ParsedOpenAIToolCall(
                        tool_call_id="wrong-tool",
                        function_name="unexpected_tool",
                        function_arguments_raw="{}",
                        function_arguments_parsed={},
                    )
                ],
            ),
            "Expected tool 'expected_tool' not found in tool calls.",
        ),
    ],
)
async def test_call_preprocessing_llm_disables_provider_retries(
    monkeypatch: pytest.MonkeyPatch,
    provider_response: UnifiedOpenAIResponse,
    expected_error: str,
) -> None:
    calls: list[str] = []

    async def primary_provider(**_kwargs):
        calls.append("primary")
        return provider_response

    async def unexpected_fallback(**_kwargs):
        raise AssertionError("fallback must not be called when retries are disabled")

    def provider_client(provider_prefix: str):
        if provider_prefix == "primary":
            return primary_provider
        if provider_prefix == "fallback":
            return unexpected_fallback
        raise AssertionError(f"Unexpected provider: {provider_prefix}")

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", provider_client)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model_id: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)

    result = await llm_utils.call_preprocessing_llm(
        task_id="test",
        model_id="primary/model",
        message_history=[{"role": "user", "content": "classify this"}],
        tool_definition=_tool_definition(),
        fallback_models=["fallback/model"],
        allow_retries=False,
    )

    assert calls == ["primary"]
    assert result.error_message is not None
    assert expected_error in result.error_message


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_call_preprocessing_llm_disables_groq_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    retry_options: list[int | None] = []

    async def groq_provider(*, max_retries: int | None = None, **_kwargs):
        retry_options.append(max_retries)
        return UnifiedOpenAIResponse(
            task_id="test",
            model_id="model",
            success=False,
            error_message="Request timeout after 25s",
        )

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda provider_prefix: groq_provider if provider_prefix == "groq" else None)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model_id: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)

    result = await llm_utils.call_preprocessing_llm(
        task_id="test",
        model_id="groq/model",
        message_history=[{"role": "user", "content": "classify this"}],
        tool_definition=_tool_definition(),
        allow_retries=False,
    )

    assert retry_options == [0]
    assert result.error_message == "Client call failed for preprocessing: Request timeout after 25s"


@pytest.mark.anyio
async def test_concrete_server_fallback_is_not_resolved_back_to_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    resolution_calls: list[str] = []

    async def primary_provider(**kwargs):
        calls.append(("primary", kwargs["model_id"]))
        return UnifiedOpenAIResponse(
            task_id="test",
            model_id=kwargs["model_id"],
            success=False,
            error_message="Request timeout",
        )

    async def vertex_provider(**kwargs):
        calls.append(("vertex", kwargs["model_id"]))
        return UnifiedOpenAIResponse(
            task_id="test",
            model_id=kwargs["model_id"],
            success=True,
            tool_calls_made=[
                ParsedOpenAIToolCall(
                    tool_call_id="valid",
                    function_name="expected_tool",
                    function_arguments_raw="{}",
                    function_arguments_parsed={},
                )
            ],
        )

    def resolve(model_id: str):
        resolution_calls.append(model_id)
        return "primary_server", "primary_server/resolved-model"

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setitem(llm_utils.PROVIDER_CLIENT_REGISTRY, "google", vertex_provider)
    monkeypatch.setattr(
        llm_utils,
        "_get_provider_client",
        lambda prefix: primary_provider if prefix == "primary_server" else vertex_provider,
    )
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", resolve)
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)

    result = await llm_utils.call_preprocessing_llm(
        task_id="test",
        model_id="logical/model",
        message_history=[{"role": "user", "content": "classify this"}],
        tool_definition=_tool_definition(),
        fallback_models=["google/gemini-model"],
    )

    assert resolution_calls == ["logical/model"]
    assert calls == [("primary", "resolved-model"), ("vertex", "gemini-model")]
    assert result.arguments == {}


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_call_preprocessing_llm_forwards_reasoning_effort_only_to_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    reasoning_efforts: list[str | None] = []

    async def groq_provider(*, reasoning_effort: str | None = None, **_kwargs):
        reasoning_efforts.append(reasoning_effort)
        return UnifiedOpenAIResponse(
            task_id="test",
            model_id="model",
            success=False,
            error_message="Request timeout after 25s",
        )

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda provider_prefix: groq_provider if provider_prefix == "groq" else None)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model_id: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)

    await llm_utils.call_preprocessing_llm(
        task_id="test",
        model_id="groq/model",
        message_history=[{"role": "user", "content": "classify this"}],
        tool_definition=_tool_definition(),
        allow_retries=False,
        reasoning_effort="low",
    )

    assert reasoning_efforts == ["low"]


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_call_preprocessing_llm_keeps_reasoning_effort_out_of_other_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def primary_provider(**kwargs):
        assert "reasoning_effort" not in kwargs
        return UnifiedOpenAIResponse(
            task_id="test",
            model_id="model",
            success=False,
            error_message="Request timeout after 25s",
        )

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda provider_prefix: primary_provider if provider_prefix == "primary" else None)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model_id: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)

    result = await llm_utils.call_preprocessing_llm(
        task_id="test",
        model_id="primary/model",
        message_history=[{"role": "user", "content": "classify this"}],
        tool_definition=_tool_definition(),
        allow_retries=False,
        reasoning_effort="low",
    )

    assert result.error_message == "Client call failed for preprocessing: Request timeout after 25s"


# contract-test: supporting surface=rest_api assertions=chat-request-safety.confirm-before-block
@pytest.mark.anyio
async def test_call_preprocessing_llm_forwards_explicit_safety_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    temperatures: list[float | None] = []

    async def primary_provider(*, temperature: float | None = None, **_kwargs):
        temperatures.append(temperature)
        return UnifiedOpenAIResponse(
            task_id="test",
            model_id="model",
            success=False,
            error_message="Request timeout after 25s",
        )

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda provider_prefix: primary_provider if provider_prefix == "primary" else None)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model_id: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)

    await llm_utils.call_preprocessing_llm(
        task_id="test",
        model_id="primary/model",
        message_history=[{"role": "user", "content": "classify this"}],
        tool_definition=_tool_definition(),
        allow_retries=False,
        temperature=0.0,
    )

    assert temperatures == [0.0]


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_call_preprocessing_llm_rejects_invalid_reasoning_effort_before_provider_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_utils,
        "_get_provider_client",
        lambda _provider_prefix: (_ for _ in ()).throw(AssertionError("invalid reasoning effort must not reach a provider")),
    )

    with pytest.raises(ValueError, match="reasoning_effort"):
        await llm_utils.call_preprocessing_llm(
            task_id="test",
            model_id="groq/model",
            message_history=[{"role": "user", "content": "classify this"}],
            tool_definition=_tool_definition(),
            reasoning_effort="minimal",
        )


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_call_preprocessing_llm_stops_when_total_retry_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def slow_provider(**_kwargs):
        calls.append("provider")
        await asyncio.sleep(1)
        raise AssertionError("provider call should be cancelled by preprocessing timeout")

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _provider_prefix: slow_provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model_id: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TOTAL_TIMEOUT_SECONDS", 0.025, raising=False)

    result = await llm_utils.call_preprocessing_llm(
        task_id="test",
        model_id="primary/model",
        message_history=[{"role": "user", "content": "classify this"}],
        tool_definition=_tool_definition(),
        fallback_models=["fallback-one/model", "fallback-two/model"],
    )

    assert calls == ["provider", "provider", "provider"]
    assert result.error_message is not None
    assert "Preprocessing retry budget exhausted" in result.error_message


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.missing-output-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("case", ["success", "disabled", "exhausted", "deadline"])
async def test_missing_preprocessing_output_uses_bounded_fallback(monkeypatch, case):
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs["model_id"])
        if case == "deadline":
            # Advance the existing monotonic retry clock without a wall-clock wait.
            clock[0] += llm_utils.PREPROCESSING_TOTAL_TIMEOUT_SECONDS + 1
        if len(calls) == 2 and case == "success":
            return UnifiedOpenAIResponse(
                task_id="test", model_id="fallback/model", success=True,
                tool_calls_made=[ParsedOpenAIToolCall(
                    tool_call_id="valid", function_name="expected_tool",
                    function_arguments_raw="{}", function_arguments_parsed={},
                )],
            )
        return UnifiedOpenAIResponse(task_id="test", model_id="model", success=True)

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    clock = [0.0]
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)
    if case == "deadline":
        monkeypatch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])

    result = await llm_utils.call_preprocessing_llm(
        task_id="test", model_id="primary/primary-model",
        message_history=[{"role": "user", "content": "Shorten the client email"}],
        tool_definition=_tool_definition(), fallback_models=["fallback/fallback-model"],
        allow_retries=case != "disabled",
    )
    assert calls == (["primary-model"] if case in {"disabled", "deadline"} else ["primary-model", "fallback-model"])
    if case == "success":
        assert result.arguments == {}
        assert result.error_message is None
    else:
        assert result.arguments is None
        assert result.error_message
        if case == "deadline":
            assert "Preprocessing retry budget exhausted" in result.error_message


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preprocessing.missing-output-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("allow_retries,total_budget,expected_timeouts", [
    (True, 45.0, [15.0, 15.0, 15.0]),
    (False, 45.0, [25.0]),
    (True, 0.0, [25.0, 25.0, 25.0]),
])
async def test_preprocessing_reserves_budget_for_remaining_configured_providers(
    monkeypatch, allow_retries, total_budget, expected_timeouts,
):
    """Two slow providers must not starve a healthy configured final fallback."""
    clock = [0.0]
    calls = []
    allocated_timeouts = []

    async def provider(**kwargs):
        calls.append(kwargs["model_id"])
        return UnifiedOpenAIResponse(
            task_id="test", model_id=kwargs["model_id"], success=True,
            tool_calls_made=[ParsedOpenAIToolCall(
                tool_call_id="valid", function_name="expected_tool",
                function_arguments_raw="{}", function_arguments_parsed={},
            )],
        )

    async def simulated_wait_for(awaitable, timeout):
        allocated_timeouts.append(timeout)
        response = await awaitable
        if len(calls) < 3:
            clock[0] += timeout
            raise asyncio.TimeoutError
        return response

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: (None, None))
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TIMEOUT_SECONDS", 25.0)
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TOTAL_TIMEOUT_SECONDS", total_budget)
    monkeypatch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])
    monkeypatch.setattr(llm_utils.asyncio, "wait_for", simulated_wait_for)

    result = await llm_utils.call_preprocessing_llm(
        task_id="test", model_id="primary/primary-model",
        message_history=[{"role": "user", "content": "Shorten the email"}],
        tool_definition=_tool_definition(),
        fallback_models=["fallback/second-model", "fallback/final-model"],
        allow_retries=allow_retries,
    )
    assert allocated_timeouts == expected_timeouts
    if allow_retries:
        assert calls == ["primary-model", "second-model", "final-model"]
        assert result.arguments == {} and result.error_message is None
    else:
        assert calls == ["primary-model"]
        assert result.arguments is None
        assert result.error_message == "Request timeout after 25s"
    if total_budget > 0:
        assert clock[0] < total_budget


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.anyio
@pytest.mark.parametrize("counts, expected", [
    ({"prompt_token_count": 100, "candidates_token_count": 20, "total_token_count": 150}, (100, 50)),
    ({"prompt_token_count": 100}, (100, None)),
])
async def test_auxiliary_usage_reports_actual_google_counts_and_caps_output(monkeypatch, counts, expected):
    from backend.apps.ai.llm_providers.google_client import UnifiedGoogleResponse, GoogleUsageMetadata, ParsedGoogleToolCall
    calls = []
    usage_events = []

    async def provider(**kwargs):
        calls.append(kwargs)
        return UnifiedGoogleResponse(task_id="guest-budget", model_id="model", success=True, usage=GoogleUsageMetadata(**counts), tool_calls_made=[ParsedGoogleToolCall(tool_call_id="call", function_name="expected_tool", function_arguments_raw="{}", function_arguments_parsed={})])

    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _provider: provider)
    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _model: (None, None))
    result = await llm_utils.call_preprocessing_llm(
        task_id="guest-budget", model_id="google/model", message_history=[{"role": "user", "content": "Hallo"}],
        tool_definition=_tool_definition(), fallback_models=[], usage_callback=usage_events.append, max_output_tokens=2048,
    )
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 2048
    assert len(usage_events) == 1
    assert (result.usage_telemetry["input_tokens"], result.usage_telemetry["output_tokens"]) == expected
    assert usage_events[0]["model_id"] == "google/model"


# contract-test: supporting surface=rest_api assertions=billing.models.immutable-attempt-tariffs,billing.models.verified-host-prices
@pytest.mark.asyncio
async def test_preprocessing_freezes_each_model_host_tariff_before_response(monkeypatch):
    calls = []
    price_lookups = []
    pricing = {
        "pricing": {"tokens": {"input": {"per_credit_unit": 1000},
                                 "output": {"per_credit_unit": 100}}},
        "costs": {"input_per_million_token": {"price": 1.0},
                  "output_per_million_token": {"price": 2.0}},
        "active_temporary_price": {"id": "intro"},
    }

    def get_pricing(provider, model, *, inference_host, region):
        price_lookups.append((provider, model, inference_host, region))
        pricing["costs"]["output_per_million_token"]["price"] = 2.0 if model == "primary" else 4.0
        return pricing

    def client(host):
        async def invoke(**kwargs):
            calls.append((host, kwargs["model_id"]))
            assert price_lookups[-1][2] == host
            # Simulate a config reload while the response is in flight.
            pricing["costs"]["output_per_million_token"]["price"] = 99.0
            return UnifiedOpenAIResponse(
                task_id="task", model_id=kwargs["model_id"], success=host == "openai",
                error_message="503 unavailable" if host != "openai" else None,
                usage=OpenAIUsageMetadata(input_tokens=100, output_tokens=10, total_tokens=110),
                tool_calls_made=[ParsedOpenAIToolCall(
                    tool_call_id="expected", function_name="expected_tool",
                    function_arguments_raw="{}", function_arguments_parsed={},
                )] if host == "openai" else None,
            )
        return invoke

    monkeypatch.setattr(llm_utils, "_get_provider_client", client)
    monkeypatch.setattr(llm_utils, "PROVIDER_CLIENT_REGISTRY", {"mistral": client, "openai": client})
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", get_pricing)
    monkeypatch.setattr(llm_utils, "_configured_server_region", lambda *_args: "global")
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config",
                        lambda _: ("mistral", "mistral/primary"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _: [])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    telemetry = []
    result = await llm_utils.call_preprocessing_llm(
        task_id="task", model_id="mistral/primary",
        message_history=[{"role": "user", "content": "hello"}],
        tool_definition=_tool_definition(), fallback_models=["openai/fallback"],
        usage_callback=telemetry.append,
    )
    assert result.arguments == {}
    assert calls == [("mistral", "primary"), ("openai", "fallback")]
    assert price_lookups == [("mistral", "primary", "mistral", "global"),
                             ("openai", "fallback", "openai", "global")]
    assert [entry["tariff_snapshot"]["costs"]["output_per_million_token"]["price"]
            for entry in telemetry] == [2.0, 4.0]
    assert [entry["supplier_cost_usd"] for entry in telemetry] == pytest.approx([0.00012, 0.00014])


@pytest.fixture
def single_attempt_provider_setup(monkeypatch):
    """Keep timeout tests offline and independent of provider health/cache state."""
    class CacheServiceWithoutClient:
        @property
        async def client(self):
            return None

    monkeypatch.setattr(llm_utils, "CacheService", CacheServiceWithoutClient)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda _: (None, None))
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TIMEOUT_SECONDS", .01)
    monkeypatch.setattr(llm_utils, "PREPROCESSING_TOTAL_TIMEOUT_SECONDS", .02)


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("override,success", [(None, False), (.2, True), (30, True)])
async def test_explicit_single_attempt_allowance_survives_ordinary_caps(
    monkeypatch, single_attempt_provider_setup, override, success,
):
    calls = []

    async def slow_provider(**kwargs):
        calls.append(kwargs["model_id"])
        await asyncio.sleep(.04)  # Exceeds both scaled ordinary 5s/12s caps.
        return UnifiedOpenAIResponse(
            task_id="test", model_id="model", success=True,
            tool_calls_made=[ParsedOpenAIToolCall(
                tool_call_id="valid", function_name="expected_tool",
                function_arguments_raw="{}", function_arguments_parsed={},
            )],
        )

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: slow_provider)
    options = {} if override is None else {"single_attempt_timeout_seconds": override}
    result = await llm_utils.call_preprocessing_llm(
        task_id="test", model_id="primary/model", message_history=[],
        tool_definition=_tool_definition(), fallback_models=["fallback/model"],
        allow_retries=False, **options,
    )
    assert calls == ["model"]
    assert (result.arguments == {} and result.error_message is None) is success
    if not success:
        assert "timeout" in result.error_message.lower()


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("slow_health", [False, True])
async def test_single_attempt_deadline_bounds_provider_and_health_setup(
    monkeypatch, single_attempt_provider_setup, slow_health,
):
    cancellations = []

    async def blocked():
        try:
            await asyncio.sleep(10)
        finally:
            cancellations.append(True)

    async def slow_provider(**_kwargs):
        await blocked()
        raise AssertionError("must be cancelled")

    class SlowCacheService:
        @property
        async def client(self):
            await blocked()
            return None

    if slow_health:
        monkeypatch.setattr(llm_utils, "CacheService", SlowCacheService)
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _: slow_provider)
    # Independent test guard fails if the inner deadline stops enforcing its cap.
    result = await asyncio.wait_for(llm_utils.call_preprocessing_llm(
        task_id="test", model_id="primary/model", message_history=[],
        tool_definition=_tool_definition(), allow_retries=False,
        single_attempt_timeout_seconds=.03,
    ), timeout=.5)
    assert cancellations == [True]
    assert result.arguments is None
    assert "budget exhausted after 0.03s" in result.error_message


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), -float("inf"), 30.01, "30", [], {}])
async def test_single_attempt_timeout_rejects_invalid_values_before_provider_lookup(monkeypatch, value):
    monkeypatch.setattr(
        llm_utils, "_get_provider_client",
        lambda _: (_ for _ in ()).throw(AssertionError("invalid override reached provider")),
    )
    with pytest.raises(ValueError, match="single_attempt_timeout_seconds"):
        await llm_utils.call_preprocessing_llm(
            task_id="test", model_id="primary/model", message_history=[],
            tool_definition=_tool_definition(), allow_retries=False,
            single_attempt_timeout_seconds=value,
        )


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("retry_options", [{}, {"allow_retries": True}])
async def test_single_attempt_timeout_rejects_retry_enabled_override(retry_options):
    with pytest.raises(ValueError, match="allow_retries=False"):
        await llm_utils.call_preprocessing_llm(
            task_id="test", model_id="primary/model", message_history=[],
            tool_definition=_tool_definition(), single_attempt_timeout_seconds=30,
            **retry_options,
        )
