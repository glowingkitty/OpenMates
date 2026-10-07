# contract-test-file: infrastructure
"""Cache customer tariffs admit standalone chats without repricing workflows."""

from types import SimpleNamespace

import pytest

from backend.apps.ai.llm_providers.anthropic_shared import AnthropicUsageMetadata
from backend.apps.ai.processing import main_processor
from backend.apps.ai.utils import llm_utils
from backend.shared.python_utils.billing_utils import select_customer_context_band


def _request(**overrides):
    fields = {
        "is_anonymous": False, "is_external": False,
        "is_sub_chat": False, "is_sub_chat_continuation": False,
        "parent_id": None, "orchestration_id": None, "sub_chat_depth": 0,
        "user_preferences": {},
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _anthropic_pricing():
    return {
        "default_server": "anthropic",
        "features": {"max_output_tokens": 1000},
        "pricing": {"tokens": {
            "input": {"per_credit_unit": 1000},
            "cache_read": {"per_credit_unit": 5000},
            "cache_write": {"per_credit_unit": 100},
            "output": {"per_credit_unit": 100},
        }},
        "cache_pricing": {
            "enabled": True, "status": "verified_for_activation",
            "eligible_hosts": ["anthropic"], "write_billing": "separate",
            "source_url": "https://example.com/pricing",
            "reviewed_on": "2026-10-01", "expires_on": "2099-12-31",
        },
    }


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("excluded", [
    {"is_anonymous": True},
    {"is_external": True},
    {"is_sub_chat": True},
    {"is_sub_chat_continuation": True},
    {"parent_id": "parent-chat"},
    {"orchestration_id": "orchestration"},
    {"sub_chat_depth": 1},
    {"user_preferences": {"workflow_ai": True}},
    {"user_preferences": {"workflow_budget": {"signed": True}}},
    {"user_preferences": {"workflow_credit_allowance": 10}},
])
def test_only_standalone_authenticated_chats_enter_cache_customer_tariff(excluded):
    assert main_processor._normal_chat_cache_pricing_scope(_request())
    assert main_processor._normal_chat_cache_pricing_scope(_request(**excluded)) is False
    assert main_processor._normal_chat_cache_pricing_scope(
        _request(user_preferences={"workflow_presentation_sources": ["weather-forecast"]})
    )


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
def test_excluded_quote_uses_legacy_rates_and_does_not_mutate_catalog(monkeypatch):
    pricing = _anthropic_pricing()
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)
    kwargs = {
        "model_id": "anthropic/model", "system_prompt": "system",
        "message_history": [{"role": "user", "content": "long chat " * 100}],
        "tools": None, "output_token_limit": 100,
        "inference_host": "anthropic",
    }
    active_quote = main_processor._quote_ai_iteration_credits(**kwargs)
    legacy_quote = main_processor._quote_ai_iteration_credits(
        **kwargs, customer_cache_pricing_enabled=False,
    )
    assert active_quote > legacy_quote
    assert pricing["cache_pricing"]["enabled"] is True


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
def test_excluded_openai_quote_disables_context_band(monkeypatch):
    pricing = {
        "default_server": "openai", "features": {"max_output_tokens": 1000},
        "pricing": {
            "tokens": {"input": {"per_credit_unit": 1000}, "output": {"per_credit_unit": 100}},
            "context_bands": {"over_272k": {
                "min_input_tokens": 272001, "eligible_hosts": ["openai"],
                "tokens": {"input": {"per_credit_unit": 500}, "output": {"per_credit_unit": 66}},
            }},
        },
        "cache_pricing": {
            "enabled": True, "status": "verified_for_activation",
            "eligible_hosts": ["openai"], "write_billing": "included_in_input",
            "source_url": "https://example.com/pricing",
            "reviewed_on": "2026-10-01", "expires_on": "2099-12-31",
        },
        "supplier_cost_profiles": {"openai": {"context_bands": {"over_272k": {
            "input": 2, "output": 2,
        }}}},
    }
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args: pricing)
    kwargs = {
        "model_id": "openai/model", "system_prompt": "x" * 273000,
        "message_history": [], "tools": None, "output_token_limit": 100,
        "inference_host": "openai",
    }
    active = main_processor._quote_ai_iteration_credits(**kwargs)
    legacy = main_processor._quote_ai_iteration_credits(
        **kwargs, customer_cache_pricing_enabled=False,
    )
    assert active > legacy
    frozen_legacy = llm_utils._snapshot_for_customer_scope(pricing, cache_pricing_enabled=False)
    assert frozen_legacy["cache_pricing"]["enabled"] is False
    assert select_customer_context_band(
        model_pricing_details=frozen_legacy, inference_host="openai", input_total=273000,
    )[0] is None


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.asyncio
@pytest.mark.parametrize("cache_enabled", [False, True, None])
async def test_excluded_provider_attempt_has_legacy_snapshot_and_no_paid_checkpoint(monkeypatch, cache_enabled):
    pricing = _anthropic_pricing()
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)

        async def stream():
            yield "answer"
            yield AnthropicUsageMetadata(
                input_tokens=100, output_tokens=20, total_tokens=120,
                cache_read_input_tokens=50, cache_creation_input_tokens=10,
            )

        return stream()

    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda *_args: pricing)
    monkeypatch.setattr(llm_utils.config_manager, "get_provider_config", lambda *_args: {})
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda *_args: provider)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config", lambda *_args: ("anthropic", "anthropic/model"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda *_args: [])
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda *_args: False)
    scope_arg = {} if cache_enabled is None else {"customer_cache_pricing_enabled": cache_enabled}
    chunks = [chunk async for chunk in llm_utils.call_main_llm_stream(
        task_id="scope-gate", model_id="anthropic/model",
        system_prompt="Stable instructions\n\nFresh context",
        cacheable_system_prefix="Stable instructions",
        message_history=[{"role": "user", "content": "hello"}], temperature=0.2,
        **scope_arg,
    )]
    assert chunks[0] == "answer"
    assert isinstance(chunks[1], AnthropicUsageMetadata)
    frozen = chunks[1]._normalized_llm_usage.tariff_snapshot
    assert frozen["cache_pricing"]["enabled"] is (cache_enabled is True)
    assert ("cacheable_system_prefix" in calls[0]) is (cache_enabled is True)
    assert pricing["cache_pricing"]["enabled"] is True
