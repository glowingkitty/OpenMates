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
