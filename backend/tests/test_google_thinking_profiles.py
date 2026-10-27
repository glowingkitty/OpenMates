"""Provider request contract for approved automatic Gemini reasoning profiles."""

import asyncio
import os
from types import SimpleNamespace

import pytest

from backend.apps.ai.llm_providers import google_client


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["studio", "vertex"])
@pytest.mark.parametrize("model_id,level,expected", [
    ("gemini-4-argon", None, "MEDIUM"),
    ("gemini-4-argon", "LOW", "LOW"),
    ("gemini-4-argon", "MEDIUM", "MEDIUM"),
    ("gemini-4-argon", "HIGH", "HIGH"),
    ("gemini-3.8-flash", "LOW", "LOW"),
    ("gemini-3.8-flash", "MEDIUM", "MEDIUM"),
    ("gemini-3.8-flash", "HIGH", "HIGH"),
    ("gemini-3.8-flash", None, None),
    ("gemini-3.5-flash-lite", "LOW", None),
])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.defaults.google-tier-profiles,billing.models.active-price-consistency
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
    if model_id == "gemini-4-argon":
        request_config = config.model_dump(exclude_unset=True)
        assert "temperature" not in request_config
        assert "top_p" not in request_config
        assert "top_k" not in request_config
        assert config.max_output_tokens == 65_536
    await google_client.close_google_clients_for_current_loop()


async def _key() -> str:
    return "test-key"


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.budgets-and-stop,ai-model-routing.defaults.google-tier-profiles
@pytest.mark.asyncio
async def test_google_browser_transport_bounds_do_not_change_ordinary_chat_defaults(monkeypatch):
    captured = []

    async def generate_content(**kwargs):
        captured.append(kwargs["config"])
        return SimpleNamespace(text="Answer", function_calls=None, usage_metadata=None)

    async def aclose():
        pass

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content), aclose=aclose), close=lambda: None)
    monkeypatch.setattr(google_client.genai, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(google_client, "_get_google_ai_studio_api_key", lambda _manager: _key())
    monkeypatch.setattr(google_client, "calculate_token_breakdown", lambda *_args, **_kwargs: {})
    for bounds in ({}, {"request_attempts": 1, "request_timeout_seconds": 20}):
        response = await google_client.invoke_google_ai_studio_chat_completions(
            task_id="test", model_id="gemini-3.8-flash", messages=[{"role":"user", "content":"hello"}], **bounds,
        )
        assert response.success
    assert captured[0].http_options is None
    assert captured[1].http_options.retry_options.attempts == 1
    assert captured[1].http_options.timeout == 20_000


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


@pytest.mark.parametrize("requested,expected", [(1_024, 1_024), (65_536, 65_536), (262_144, 65_536)])
@pytest.mark.parametrize("provider", ["studio", "vertex"])
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
async def test_argon_regular_stream_caps_output_without_background(monkeypatch, requested, expected, provider):
    captured = []

    async def generate_content_stream(**kwargs):
        captured.append(kwargs)

        async def chunks():
            yield SimpleNamespace(candidates=None, usage_metadata=None)

        return chunks()

    async def close():
        pass

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content_stream=generate_content_stream,
    ), aclose=close), close=lambda: None)

    async def get_client(*_args, **_kwargs):
        return client, None

    monkeypatch.setattr(google_client, "_get_loop_google_client", get_client)
    monkeypatch.setattr(google_client, "_get_google_ai_studio_api_key", lambda _manager: _key())
    monkeypatch.setattr(google_client, "_google_client_initialized", True)
    monkeypatch.setattr(google_client, "calculate_token_breakdown", lambda *_args, **_kwargs: {})
    invoke = (google_client.invoke_google_ai_studio_chat_completions if provider == "studio"
              else google_client.invoke_google_chat_completions)
    stream = await invoke(task_id="task", model_id="gemini-4-argon",
                          messages=[{"role": "user", "content": "hello"}],
                          stream=True, max_tokens=requested, temperature=0.1)
    _ = [chunk async for chunk in stream]
    assert len(captured) == 1
    assert captured[0]["config"].max_output_tokens == expected
    assert "temperature" not in captured[0]["config"].model_dump(exclude_unset=True)


@pytest.mark.parametrize("model_id,bill_reasoning,expected_output", [
    ("google/gemini-4-argon", True, 15),
    ("google/gemini-3.8-flash", False, 10),
])
# contract-test: supporting surface=rest_api assertions=billing.models.immutable-attempt-tariffs,billing.models.active-price-consistency
def test_argon_charges_thoughts_with_pending_cache_without_changing_legacy_google(
    model_id, bill_reasoning, expected_output,
):
    from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
    from backend.shared.python_schemas.llm_usage import normalize_provider_usage
    from backend.shared.python_utils.billing_utils import snapshot_model_tariff

    tariff = snapshot_model_tariff({
        "pricing": {"tokens": {"input": {"per_credit_unit": 1000},
                                 "output": {"per_credit_unit": 1}}},
        "cache_pricing": {"enabled": False, "status": "proposed_pending_provider_evidence"},
        "bill_reasoning_tokens": bill_reasoning,
    })
    bucket = normalize_provider_usage(
        {"prompt_token_count": 1, "candidates_token_count": 10,
         "thoughts_token_count": 5, "cached_content_token_count": 0},
        model_id=model_id, provider_kind="google", inference_host="google_ai_studio",
        tariff_snapshot=tariff,
    ).to_bucket()

    def forbid_repricing(*_args):
        raise AssertionError("Frozen attempt must not be repriced")

    receipt = build_model_usage_breakdown([bucket], forbid_repricing)
    assert receipt["output_tokens"] == expected_output
    assert receipt["credits_charged"] == expected_output


@pytest.mark.parametrize("thoughts,total,expected_thoughts,source", [
    (None, 25, 5, "provider_reported"),
    (None, 20, 0, "provider_reported"),
    (None, None, None, "estimated"),
    (None, 19, None, "estimated"),
    (5, 24, 5, "estimated"),
    (5, 25, 5, "provider_reported"),
])
# contract-test: supporting surface=rest_api assertions=billing.models.immutable-attempt-tariffs,billing.models.active-price-consistency
def test_argon_reconciles_missing_thoughts_and_marks_inconsistent_usage(
    thoughts, total, expected_thoughts, source,
):
    from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
    from backend.shared.python_schemas.llm_usage import normalize_provider_usage
    from backend.shared.python_utils.billing_utils import snapshot_model_tariff

    tariff = snapshot_model_tariff({
        "pricing": {"tokens": {"input": {"per_credit_unit": 1000},
                                 "output": {"per_credit_unit": 1}}},
        "costs": {"input": {"price": 2, "per": 1000000},
                  "output": {"price": 10, "per": 1000000}},
        "bill_reasoning_tokens": True,
    })
    normalized = normalize_provider_usage(
        {"prompt_token_count": 10, "candidates_token_count": 10,
         "thoughts_token_count": thoughts, "total_token_count": total},
        model_id="google/gemini-4-argon", provider_kind="google",
        inference_host="google_ai_studio", tariff_snapshot=tariff,
    )
    assert normalized.output_reasoning_tokens == expected_thoughts
    assert normalized.output_billable == 10 + (expected_thoughts or 0)
    assert normalized.usage_source == source
    receipt = build_model_usage_breakdown([normalized.to_bucket()], lambda *_args: None)
    assert receipt["output_tokens"] == normalized.output_billable
    assert receipt["usage_source"] == source
