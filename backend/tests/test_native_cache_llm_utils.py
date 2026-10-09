"""Native replay selection, reservation input, and cold supplier fallback."""

# contract-test-file: infrastructure
# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown

import asyncio
import copy
import logging

import pytest

try:
    from backend.apps.ai.llm_providers.anthropic_shared import AnthropicUsageMetadata
    from backend.apps.ai.llm_providers.native_cache_context import NativeCacheProviderOutput
    from backend.apps.ai.utils import llm_utils
except ImportError:
    pytestmark = pytest.mark.skip(reason="Backend AI dependencies are unavailable locally")
    llm_utils = None


def _tool(name, *, minimum=1):
    return {"type": "function", "function": {
        "name": name, "description": name,
        "parameters": {"type": "object", "properties": {
            "count": {"type": "integer", "minimum": minimum, "maximum": 10},
        }},
    }}


def _pricing():
    return {
        "default_server": "openai",
        "servers": [{"id": "openai", "model_id": "gpt-6-astra"}],
        "pricing": {"tokens": {
            "input": {"per_credit_unit": 100},
            "cache_read": {"per_credit_unit": 1000},
            "output": {"per_credit_unit": 10},
        }},
        "cache_pricing": {
            "enabled": True, "status": "verified_for_activation",
            "eligible_hosts": ["openai"], "write_billing": "included_in_input",
            "source_url": "https://example.com/pricing", "reviewed_on": "2026-10-01",
            "expires_on": "2099-12-31",
        },
    }


def _context():
    return {
        "model_id": "openai/gpt-6-astra", "provider_prefix": "openai",
        "server_model_id": "gpt-6-astra",
        "messages": [
            {"role": "system", "content": "stable"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "provider_transport_state": [
                {"type": "reasoning", "encrypted_content": "PRIVATE_OPAQUE_FRAME"},
                {"type": "message", "content": [{"type": "output_text", "text": "first answer"}]},
            ]},
            {"role": "user", "content": "next"},
        ],
        "baseline_tools": [_tool("base")],
        "events": [{"after_message_index": 3, "system_suffix": "current context",
                    "add_tools": [_tool("selected")]}],
    }


def _setup(monkeypatch):
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda *_: _pricing())
    monkeypatch.setattr(llm_utils.config_manager, "get_provider_config", lambda *_: {})
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config",
                        lambda *_: ("openai", "openai/gpt-6-astra"))
    monkeypatch.setattr(llm_utils, "_transform_message_history_for_llm", lambda history: history)
    monkeypatch.setattr(llm_utils, "_is_reasoning_model", lambda *_: False)

    class NoCache:
        @property
        def client(self):
            async def empty():
                return None
            return empty()

    monkeypatch.setattr(llm_utils, "CacheService", NoCache)


def _setup_anthropic(monkeypatch):
    _setup(monkeypatch)
    pricing = _pricing()
    pricing["default_server"] = "anthropic"
    pricing["servers"] = [{"id": "anthropic", "model_id": "claude-haiku-5-5"}]
    pricing["cache_pricing"]["eligible_hosts"] = ["anthropic"]
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda *_: pricing)
    monkeypatch.setattr(llm_utils, "resolve_default_server_from_provider_config",
                        lambda *_: ("anthropic", "anthropic/claude-haiku-5-5"))
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda *_: [])
    context = _context()
    context.update({
        "model_id": "anthropic/claude-haiku-5-5",
        "provider_prefix": "anthropic", "server_model_id": "claude-haiku-5-5",
    })
    context["messages"][2]["provider_transport_state"] = [
        {"type": "text", "text": "first answer"},
    ]
    return context


def test_anthropic_cache_usage_needs_complete_provider_totals_before_settlement(monkeypatch):
    context = _setup_anthropic(monkeypatch)
    seen = []

    async def provider(**_kwargs):
        async def stream():
            yield "done"
            yield NativeCacheProviderOutput(
                provider_prefix="anthropic", model_id="claude-haiku-5-5",
                output=[{"type": "text", "text": "done"}],
            )
            # The direct adapter already carries message_start totals forward
            # when the terminal delta omits these optional fields.
            yield AnthropicUsageMetadata(
                input_tokens=100, output_tokens=20, total_tokens=120,
                cache_creation_input_tokens=5, cache_read_input_tokens=100_100,
            )
        return stream()
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda *_: provider)

    async def collect():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="test", model_id="anthropic/claude-haiku-5-5",
            system_prompt="current system", message_history=[{"role": "user", "content": "next"}],
            temperature=0.2, customer_cache_pricing_enabled=True,
            native_cache_context=context,
        )]

    seen = asyncio.run(collect())
    assert seen[0] == "done"
    usage = next(item for item in seen if isinstance(item, AnthropicUsageMetadata))
    assert usage._normalized_llm_usage.input_total == 100_205
    assert isinstance(seen[-1], NativeCacheProviderOutput)


@pytest.mark.parametrize("usage", [
    None,
    AnthropicUsageMetadata(
        input_tokens=100, output_tokens=20, total_tokens=120,
        cache_creation_input_tokens=5, cache_read_input_tokens=None,
    ),
    AnthropicUsageMetadata(
        input_tokens=100, output_tokens=20, total_tokens=120,
        cache_creation_input_tokens=None, cache_read_input_tokens=100_100,
    ),
])
def test_anthropic_cache_usage_missing_totals_fails_attempt_before_billing(monkeypatch, usage):
    context = _setup_anthropic(monkeypatch)
    async def provider(**_kwargs):
        async def stream():
            yield "done"
            yield NativeCacheProviderOutput(
                provider_prefix="anthropic", model_id="claude-haiku-5-5",
                output=[{"type": "text", "text": "done"}],
            )
            if usage is not None:
                yield usage
        return stream()
    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda *_: provider)

    async def collect():
        seen = []
        with pytest.raises(llm_utils.AllServersFailedError):
            async for chunk in llm_utils.call_main_llm_stream(
                task_id="test", model_id="anthropic/claude-haiku-5-5",
                system_prompt="current system", message_history=[{"role": "user", "content": "next"}],
                temperature=0.2, customer_cache_pricing_enabled=True,
                native_cache_context=context, recoverable_attempt=True,
            ):
                seen.append(chunk)
        return seen

    assert asyncio.run(collect()) == ["done"]


def test_prepare_native_context_preserves_replay_and_quotes_selected_schemas(monkeypatch):
    _setup(monkeypatch)
    context = _context()
    original = copy.deepcopy(context)
    prepared = llm_utils.prepare_native_cache_context(
        context, logical_model_id="openai/gpt-6-astra",
        customer_cache_pricing_enabled=True,
    )
    assert prepared is not None
    assert context == original
    assert prepared["messages"] == context["messages"]
    assert "minimum" not in prepared["baseline_tools"][0]["function"]["parameters"]["properties"]["count"]
    assert "maximum" not in prepared["events"][0]["add_tools"][0]["function"]["parameters"]["properties"]["count"]
    system, messages, tools = llm_utils.native_cache_quote_payload(prepared, "openai")
    assert system == ""
    assert tools[0]["name"] == "base"
    assert messages[-1]["type"] == "additional_tools"
    assert messages[-1]["tools"][0]["name"] == "selected"
    assert any("PRIVATE_OPAQUE_FRAME" in str(item) for item in messages)


def test_anthropic_quote_contains_inline_changes_and_private_replay(monkeypatch):
    pricing = _pricing()
    pricing["default_server"] = "anthropic"
    pricing["servers"] = [{"id": "anthropic", "model_id": "claude-sonnet-5-5"}]
    pricing["cache_pricing"]["eligible_hosts"] = ["anthropic"]
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda *_: pricing)
    context = _context()
    context.update({
        "model_id": "anthropic/claude-sonnet-5-5",
        "provider_prefix": "anthropic", "server_model_id": "claude-sonnet-5-5",
    })
    context["messages"][2]["provider_transport_state"] = [
        {"type": "thinking", "thinking": "PRIVATE_THINKING", "signature": "opaque"},
        {"type": "text", "text": "first answer"},
    ]
    prepared = llm_utils.prepare_native_cache_context(
        context, logical_model_id="anthropic/claude-sonnet-5-5",
        customer_cache_pricing_enabled=True,
    )
    assert prepared is not None
    system, messages, tools = llm_utils.native_cache_quote_payload(prepared, "anthropic")
    assert system == "stable"
    assert [entry["name"] for entry in tools] == ["base"]
    assert messages[1]["content"] == context["messages"][2]["provider_transport_state"]
    assert messages[-1]["content"][1]["type"] == "tool_addition"
    assert messages[-1]["content"][1]["tool"]["definition"]["name"] == "selected"


def test_anthropic_tool_free_followup_keeps_private_replay_without_baseline(monkeypatch):
    context = _setup_anthropic(monkeypatch)
    context["baseline_tools"] = []
    context["events"] = []
    original_messages = copy.deepcopy(context["messages"])
    prepared = llm_utils.prepare_native_cache_context(
        context, logical_model_id="anthropic/claude-haiku-5-5",
        customer_cache_pricing_enabled=True,
    )
    assert prepared is not None
    assert prepared["messages"] == original_messages
    system, messages, tools = llm_utils.native_cache_quote_payload(prepared, "anthropic")
    assert system == "stable"
    assert tools == []
    assert messages[1]["content"] == [{"type": "text", "text": "first answer"}]
    assert messages[-1]["content"] == "next"


def test_native_route_uses_configured_direct_model_alias(monkeypatch):
    pricing = _pricing()
    pricing["servers"][0]["model_id"] = "gpt-6-astra-2026-09-04"
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda *_: pricing)
    context = _context()
    context["server_model_id"] = "gpt-6-astra-2026-09-04"
    assert llm_utils.native_cache_route("openai/gpt-6-astra") == (
        "openai", "gpt-6-astra-2026-09-04",
    )
    assert llm_utils.prepare_native_cache_context(
        context, logical_model_id="openai/gpt-6-astra",
        customer_cache_pricing_enabled=True,
    ) is not None


@pytest.mark.parametrize("change", [
    {"customer_cache_pricing_enabled": False},
    {"server_model_id": "gpt-6-luna"},
    {"provider_prefix": "openrouter"},
])
def test_prepare_native_context_fails_closed_on_scope_or_route(monkeypatch, change):
    _setup(monkeypatch)
    options = {"customer_cache_pricing_enabled": True, **change}
    assert llm_utils.prepare_native_cache_context(
        _context(), logical_model_id="openai/gpt-6-astra",
        **options,
    ) is None


def test_native_success_forwards_private_output_without_logging_it(monkeypatch, caplog):
    _setup(monkeypatch)
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda *_: [])
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)
        async def stream():
            yield "done"
            yield NativeCacheProviderOutput(provider_prefix="openai", model_id="gpt-6-astra", output=[
                {"type": "reasoning", "encrypted_content": "PRIVATE_OPAQUE_FRAME"},
            ])
        return stream()

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda *_: provider)

    async def collect():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="test", model_id="openai/gpt-6-astra", system_prompt="current system",
            message_history=[{"role": "user", "content": "next"}], temperature=0.2,
            customer_cache_pricing_enabled=True, native_cache_context=_context(),
        )]

    with caplog.at_level(logging.DEBUG):
        chunks = asyncio.run(collect())
    assert chunks[0] == "done"
    assert isinstance(chunks[1], NativeCacheProviderOutput)
    assert calls[0]["messages"] == _context()["messages"]
    assert calls[0]["native_cache_context"]["events"][0]["add_tools"][0]["function"]["name"] == "selected"
    assert "PRIVATE_OPAQUE_FRAME" not in caplog.text


def test_empty_native_output_falls_back_with_cold_history(monkeypatch, caplog):
    _setup(monkeypatch)
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config",
                        lambda *_: ["openrouter/openai/gpt-6-astra"])
    calls = []

    async def direct(**kwargs):
        calls.append(("direct", kwargs))
        async def stream():
            yield NativeCacheProviderOutput(provider_prefix="openai", model_id="gpt-6-astra", output=[
                {"type": "reasoning", "encrypted_content": "PRIVATE_OPAQUE_FRAME"},
            ])
        return stream()

    async def fallback(**kwargs):
        calls.append(("fallback", kwargs))
        async def stream():
            yield "recovered"
        return stream()

    monkeypatch.setattr(llm_utils, "_get_provider_client",
                        lambda prefix: direct if prefix == "openai" else fallback)

    async def collect():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="test", model_id="openai/gpt-6-astra", system_prompt="current system",
            message_history=[{"role": "user", "content": "next"}], temperature=0.2,
            customer_cache_pricing_enabled=True, native_cache_context=_context(),
        )]

    with caplog.at_level(logging.DEBUG):
        chunks = asyncio.run(collect())
    assert chunks == ["recovered"]
    assert "native_cache_context" in calls[0][1]
    assert "native_cache_context" not in calls[1][1]
    assert calls[1][1]["messages"] == [
        {"role": "system", "content": "current system"},
        {"role": "user", "content": "next"},
    ]
    assert "PRIVATE_OPAQUE_FRAME" not in caplog.text


def test_native_provider_error_keeps_payload_out_of_logs_and_uses_cold_fallback(monkeypatch, caplog):
    _setup(monkeypatch)
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config",
                        lambda *_: ["openrouter/openai/gpt-6-astra"])
    calls = []

    async def direct(**kwargs):
        calls.append(kwargs)
        raise ValueError("429 PRIVATE_OPAQUE_FRAME")

    async def fallback(**kwargs):
        calls.append(kwargs)
        async def stream():
            yield "recovered"
        return stream()

    monkeypatch.setattr(llm_utils, "_get_provider_client",
                        lambda prefix: direct if prefix == "openai" else fallback)

    async def collect():
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="test", model_id="openai/gpt-6-astra", system_prompt="current system",
            message_history=[{"role": "user", "content": "next"}], temperature=0.2,
            customer_cache_pricing_enabled=True, native_cache_context=_context(),
        )]

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(collect()) == ["recovered"]
    assert "native_cache_context" in calls[0]
    assert "native_cache_context" not in calls[1]
    assert "PRIVATE_OPAQUE_FRAME" not in caplog.text
