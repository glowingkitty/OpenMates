# contract-test-file: infrastructure
# backend/tests/test_llm_utils_preprocessing_retries.py
#
# Purpose: ensure bounded output-safety preprocessing returns the first
# provider failure without automatic provider or same-provider retries.
# Architecture: specifications/architecture/app-skill-execution/specification.yml

import pytest

try:
    from backend.apps.ai.llm_providers.openai_shared import (
        ParsedOpenAIToolCall,
        UnifiedOpenAIResponse,
    )
    from backend.apps.ai.utils import llm_utils
except ImportError as exc:
    pytestmark = pytest.mark.skip(reason=f"Backend AI dependencies not installed: {exc}")


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
