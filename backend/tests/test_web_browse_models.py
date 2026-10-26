"""Offline provider policy and native accounting for Browse's internal helpers."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.providers.browser_models import BrowserModels, BrowserModelError


@pytest.fixture
def models(monkeypatch):
    from backend.core.api.app.utils import config_manager

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        config_manager, "BACKEND_CONFIG_FILE", str(root / "config/backend_config.yml")
    )
    monkeypatch.setattr(config_manager, "PROVIDERS_CONFIG_DIR", str(root / "providers"))
    monkeypatch.setattr(config_manager, "PROVIDER_OVERLAY_CONFIG_DIR", None)
    monkeypatch.setattr(config_manager.ConfigManager, "_instance", None)
    return BrowserModels(
        SimpleNamespace(get_secret=AsyncMock(return_value="private-test-key")),
        before_attempt=AsyncMock(return_value="call-id"),
        after_attempt=AsyncMock(),
    )


def google_fallback(monkeypatch):
    module = ModuleType("backend.apps.ai.llm_providers.google_client")
    module.invoke_google_ai_studio_chat_completions = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            usage=SimpleNamespace(
                prompt_token_count=100,
                candidates_token_count=10,
                thoughts_token_count=2,
                total_token_count=112,
                cache_read_input_tokens=0,
            ),
            direct_message_content='{"text":"Paris"}',
        )
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module.invoke_google_ai_studio_chat_completions


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.text-helper
@pytest.mark.asyncio
async def test_jev_native_usage_has_exact_two_times_browse_price_and_no_public_skill_markup(
    models,
):
    await models.account(
        call_id="call",
        model="typesafe/jev-1.14",
        host="typesafe",
        usage={
            "input_tokens": 1_000_000,
            "output_tokens": 1000,
            "cache_read_input_tokens": 0,
        },
        elapsed=0.2,
    )
    assert models.cost == Decimal("0.042")
    from backend.shared.python_schemas.web_browse import charged_credits

    assert charged_credits(models.cost) == 84
    models.after_attempt.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_primary_together_model_receives_only_bounded_field_context(
    models, monkeypatch
):
    monkeypatch.setenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true")
    fallback = google_fallback(monkeypatch)
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer private-test-key"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"text":"Paris"}'}}],
                "usage": {
                    "prompt_tokens": 300,
                    "completion_tokens": 50,
                    "total_tokens": 350,
                    "prompt_tokens_details": {"cached_tokens": 100},
                },
            },
        )

    transport(monkeypatch, handle)
    result = await models.generate(
        {"purpose": "type", "goal": "Search for Paris", "field": {"label": "Search"}}
    )
    assert result == {"text": "Paris"}
    assert requests[0]["model"] == "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    assert requests[0]["max_tokens"] == 2048
    assert models.attempts[0]["host"] == "together"
    assert models.cost == Decimal("0.0001206")
    fallback.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.private-storage-and-api
@pytest.mark.parametrize(
    "context,verified",
    [
        ({"purpose": "type", "goal": "Search for Paris"}, False),
        (
            {"purpose": "type", "goal": "Read this account", "private_account": True},
            True,
        ),
        ({"purpose": "type", "goal": "Search a medical diagnosis"}, True),
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_unverified_retention_or_ineligible_context_never_reaches_together(
    models, monkeypatch, context, verified
):
    monkeypatch.setenv(
        "WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true" if verified else "false"
    )
    fallback = google_fallback(monkeypatch)

    def forbidden(request):
        raise AssertionError("Ineligible context reached Together")

    transport(monkeypatch, forbidden)
    assert await models.generate(context) == {"text": "Paris"}
    assert fallback.await_args.kwargs["model_id"] == "gemini-3.8-flash"
    assert fallback.await_args.kwargs["thinking_level"] == "LOW"
    assert models.attempts[0]["host"] == "google_ai_studio"
    assert models.attempts[0]["usage"]["output_tokens"] == 12
    assert models.attempts[0]["usage"]["output_reasoning_tokens"] == 2


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_primary_admission_rejection_falls_back_once_with_its_own_native_usage(
    models, monkeypatch
):
    monkeypatch.setenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true")
    fallback = google_fallback(monkeypatch)
    transport(monkeypatch, lambda request: httpx.Response(429, json={"error": "quota"}))
    assert await models.generate({"purpose": "type", "goal": "Search for Paris"}) == {
        "text": "Paris"
    }
    assert len(models.attempts) == 2
    assert models.attempts[0]["cost_usd"] == "0"
    assert models.attempts[1]["model"] == "google/gemini-3.8-flash"
    fallback.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_missing_provider_usage_stops_without_free_success_or_blind_retry(
    models, monkeypatch
):
    monkeypatch.setenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true")
    fallback = google_fallback(monkeypatch)
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": '{"text":"Paris"}'}}]}
        ),
    )
    with pytest.raises(BrowserModelError, match="accounting reconciliation"):
        await models.generate({"purpose": "type", "goal": "Search for Paris"})
    assert len(models.attempts) == 1 and not models.attempts[0]["complete"]
    assert models.after_attempt.await_args.args[1]["complete"] is False
    fallback.assert_not_awaited()
