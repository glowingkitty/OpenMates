# contract-test-file: infrastructure
# backend/tests/test_groq_client_retry_config.py
#
# Purpose: ensure bounded preprocessing can disable Groq SDK retries per request
# without changing the shared client's normal inference retry configuration.
# Architecture: specifications/architecture/app-skill-execution/specification.yml

from types import SimpleNamespace

import pytest

try:
    from backend.apps.ai.llm_providers import groq_client
except ImportError as exc:
    pytestmark = pytest.mark.skip(reason=f"Backend AI dependencies not installed: {exc}")


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
@pytest.mark.parametrize("reasoning_effort", ["low", "medium", "high"])
async def test_invoke_groq_uses_per_request_no_retry_client(
    monkeypatch: pytest.MonkeyPatch,
    reasoning_effort: str,
) -> None:
    with_options_calls: list[int] = []
    request_calls: list[dict] = []

    class CompletionClient:
        class Chat:
            class Completions:
                async def create(self, **kwargs):
                    request_calls.append(kwargs)
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="ok"))],
                        usage=None,
                    )

            completions = Completions()

        chat = Chat()

    class SharedClient:
        chat = CompletionClient.Chat()

        def with_options(self, *, max_retries: int):
            with_options_calls.append(max_retries)
            return CompletionClient()

    monkeypatch.setattr(groq_client, "_groq_client_initialized", True)
    monkeypatch.setattr(groq_client, "_groq_direct_client", SharedClient())

    result = await groq_client.invoke_groq_chat_completions(
        task_id="test",
        model_id="model",
        messages=[{"role": "user", "content": "classify this"}],
        max_retries=0,
        reasoning_effort=reasoning_effort,
    )

    assert with_options_calls == [0]
    assert request_calls == [{"model": "model", "messages": [{"role": "user", "content": "classify this"}], "temperature": 0.7, "stream": False, "reasoning_effort": reasoning_effort}]
    assert result.success is True


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_invoke_groq_keeps_normal_request_retry_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    with_options_calls: list[int] = []

    class Completions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None, content="ok"))],
                usage=None,
            )

    class SharedClient:
        chat = SimpleNamespace(completions=Completions())

        def with_options(self, *, max_retries: int):
            with_options_calls.append(max_retries)
            raise AssertionError("normal inference must use the shared client")

    monkeypatch.setattr(groq_client, "_groq_client_initialized", True)
    monkeypatch.setattr(groq_client, "_groq_direct_client", SharedClient())

    result = await groq_client.invoke_groq_chat_completions(
        task_id="test",
        model_id="model",
        messages=[{"role": "user", "content": "classify this"}],
    )

    assert with_options_calls == []
    assert result.success is True


# contract-test: supporting surface=rest_api assertions=app-skills.output.bounded-failure
@pytest.mark.anyio
async def test_invoke_groq_rejects_invalid_reasoning_effort_before_sdk_call(monkeypatch: pytest.MonkeyPatch) -> None:
    class Completions:
        async def create(self, **_kwargs):
            raise AssertionError("invalid reasoning effort must not reach the SDK")

    class SharedClient:
        chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(groq_client, "_groq_client_initialized", True)
    monkeypatch.setattr(groq_client, "_groq_direct_client", SharedClient())

    with pytest.raises(ValueError, match="reasoning_effort"):
        await groq_client.invoke_groq_chat_completions(
            task_id="test",
            model_id="model",
            messages=[{"role": "user", "content": "classify this"}],
            reasoning_effort="minimal",
        )
