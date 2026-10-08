"""Provider request contract for approved automatic Gemini reasoning profiles."""

from types import SimpleNamespace

import pytest

from backend.apps.ai.llm_providers import google_client


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["studio", "vertex"])
@pytest.mark.parametrize("model_id,level,expected", [
    ("gemini-3.8-flash", "LOW", "LOW"),
    ("gemini-3.8-flash", "MEDIUM", "MEDIUM"),
    ("gemini-3.8-flash", "HIGH", "HIGH"),
    ("gemini-3.8-flash", None, None),
    ("gemini-3.5-flash-lite", "LOW", None),
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
async def test_google_clients_send_only_supported_profile_level(
    monkeypatch, provider, model_id, level, expected,
) -> None:
    captured = []

    async def generate_content(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(text="Answer", function_calls=None, usage_metadata=None)

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content,
    )))
    monkeypatch.setattr(google_client.genai, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(google_client, "_get_google_ai_studio_api_key",
                        lambda _manager: _key())
    monkeypatch.setattr(google_client, "_google_client_initialized", True)
    monkeypatch.setattr(google_client, "calculate_token_breakdown", lambda *_args, **_kwargs: {})

    invoke = (google_client.invoke_google_ai_studio_chat_completions
              if provider == "studio" else google_client.invoke_google_chat_completions)
    response = await invoke(
        task_id="task", model_id=model_id,
        messages=[{"role": "user", "content": "hello"}],
        thinking_level=level,
    )

    assert response.success is True
    assert len(captured) == 1
    config = captured[0]["config"]
    assert config.thinking_config.include_thoughts is True
    actual_level = config.thinking_config.thinking_level
    assert (actual_level.value if actual_level is not None else None) == expected


async def _key() -> str:
    return "test-key"
