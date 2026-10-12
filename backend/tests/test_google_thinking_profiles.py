"""Provider request contract for approved automatic Gemini reasoning profiles."""

import asyncio
import os
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
    closed = []

    async def generate_content(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(text="Answer", function_calls=None, usage_metadata=None)

    async def aclose():
        closed.append("async")

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content,
    ), aclose=aclose), close=lambda: closed.append("sync"))
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
    assert closed == ["async", "sync"]
    assert len(captured) == 1
    config = captured[0]["config"]
    assert config.thinking_config.include_thoughts is True
    actual_level = config.thinking_config.thinking_level
    assert (actual_level.value if actual_level is not None else None) == expected
    await google_client.close_google_clients_for_current_loop()


async def _key() -> str:
    return "test-key"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
async def test_google_client_reuses_only_matching_loop_and_credential(monkeypatch) -> None:
    created = []
    closed = []

    class FakeAsync:
        async def aclose(self):
            closed.append("async")

    class FakeClient:
        def __init__(self, **kwargs):
            self.aio = FakeAsync()
            created.append(kwargs["api_key"])

        def close(self):
            closed.append("sync")

    monkeypatch.setattr(google_client.genai, "Client", FakeClient)
    google_client.register_google_client_loop(asyncio.get_running_loop())
    first, first_session = await google_client._get_loop_google_client("google_ai_studio", api_key="key-one")
    reused, reused_session = await google_client._get_loop_google_client("google_ai_studio", api_key="key-one")
    rotated, rotated_session = await google_client._get_loop_google_client("google_ai_studio", api_key="key-two")
    assert reused is first and reused_session is None and first_session is None
    assert rotated is not first and rotated_session is None
    await google_client.close_google_clients_for_current_loop()
    assert created == ["key-one", "key-two"]
    assert closed.count("async") == closed.count("sync") == 2


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles
async def test_vertex_credentials_refresh_on_secret_rotation(monkeypatch) -> None:
    class Secrets:
        service_account = '{"key":"first"}'
        unavailable = False

        async def get_secret(self, *, secret_path, secret_key):
            if self.unavailable:
                raise ConnectionError("Vault unavailable")
            return {
                "service_account_json": self.service_account,
                "project_id": "project",
                "location": "global",
            }[secret_key]

    secrets = Secrets()
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""))
    monkeypatch.setattr(google_client, "_google_client_initialized", False)
    monkeypatch.setattr(google_client, "_google_credentials_fingerprint", None)
    monkeypatch.setattr(google_client, "_temp_credentials_file", None)
    monkeypatch.setattr(google_client, "_temp_credentials_files", [])
    await google_client.initialize_google_client(secrets)
    first_path = google_client._temp_credentials_file
    await google_client.initialize_google_client(secrets)
    assert google_client._temp_credentials_file == first_path
    secrets.service_account = '{"key":"rotated"}'
    await google_client.initialize_google_client(secrets)
    assert google_client._temp_credentials_file != first_path
    assert len(google_client._temp_credentials_files) == 2
    rotated_path = google_client._temp_credentials_file
    secrets.unavailable = True
    await google_client.initialize_google_client(secrets)
    assert google_client._google_client_initialized is True
    assert google_client._temp_credentials_file == rotated_path
    google_client._cleanup_google_client()
