# contract-test-file: infrastructure
# backend/tests/test_openai_gpt56_models.py
#
# Purpose: pins the retained GPT-5.6 Terra provider catalog entry and legacy
# request payload mapping. Sol Max was an OpenMates catalog variant, not a
# separate upstream OpenAI model, so historical synthetic routing tests keep
# covering its gpt-5.6-sol mapping with max reasoning effort.
# Spec: docs/specs/gpt-5-6-openai-model-variants/spec.yml

import asyncio
import importlib
import importlib.util
import sys
import types
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import yaml

try:
    from backend.apps.ai.llm_providers import openai_client
except ImportError:
    pytestmark = pytest.mark.skip(reason="Backend AI deps not installed")
    openai_client = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAI_PROVIDER_YAML = REPO_ROOT / "backend" / "providers" / "openai.yml"
LLM_UTILS_PATH = REPO_ROOT / "backend" / "apps" / "ai" / "utils" / "llm_utils.py"

EXPECTED_GPT56_MODELS: Dict[str, Dict[str, Any]] = {
    "gpt-5.6-luna": {
        "name": "GPT-5.6 Luna",
        "upstream_model_id": "gpt-5.6-luna",
        "input_cost": 0.20,
        "cached_input_cost": 0.02,
        "cache_write_cost": 0.25,
        "output_cost": 1.20,
        "input_tokens_per_credit": 1600,
        "output_tokens_per_credit": 275,
        "reasoning_effort": None,
    },
    "gpt-5.6-terra": {
        "name": "GPT-5.6 Terra",
        "upstream_model_id": "gpt-5.6-terra",
        "input_cost": 2.00,
        "cached_input_cost": 0.20,
        "cache_write_cost": 2.50,
        "output_cost": 12.00,
        "input_tokens_per_credit": 165,
        "output_tokens_per_credit": 25,
        "reasoning_effort": None,
    },
    "gpt-5.6-sol": {
        "name": "GPT-5.6 Sol",
        "upstream_model_id": "gpt-5.6-sol",
        "input_cost": 4.00,
        "cached_input_cost": 0.40,
        "cache_write_cost": 5.00,
        "output_cost": 20.00,
        "input_tokens_per_credit": 80,
        "output_tokens_per_credit": 15,
        "reasoning_effort": "medium",
    },
    "gpt-5.6-sol-max": {
        "name": "GPT-5.6 Sol Max",
        "upstream_model_id": "gpt-5.6-sol",
        "input_cost": 4.00,
        "cached_input_cost": 0.40,
        "cache_write_cost": 5.00,
        "output_cost": 20.00,
        "input_tokens_per_credit": 80,
        "output_tokens_per_credit": 15,
        "reasoning_effort": "max",
    },
}


class _CapturingCompletions:
    def __init__(self) -> None:
        self.captured: Dict[str, Any] = {}

    async def create(self, **payload: Any) -> Any:
        self.captured = payload
        if payload.get("stream") is True:
            async def _stream() -> Any:
                yield types.SimpleNamespace(
                    choices=[
                        types.SimpleNamespace(
                            delta=types.SimpleNamespace(content="ok", tool_calls=None),
                            finish_reason="stop",
                        )
                    ],
                    usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

            return _stream()

        class _Resp:
            def model_dump(self) -> Dict[str, Any]:
                return {
                    "id": "chatcmpl-gpt56-test",
                    "model": payload.get("model"),
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "ok", "tool_calls": None},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

        return _Resp()


class _StubClient:
    def __init__(self) -> None:
        self.chat = type("C", (), {})()
        self.chat.completions = _CapturingCompletions()


class _SplitToolCallCompletions:
    async def create(self, **_payload: Any) -> Any:
        async def _stream() -> Any:
            yield types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(
                            content=None,
                            tool_calls=[
                                types.SimpleNamespace(
                                    id="call-weather",
                                    index=0,
                                    function=types.SimpleNamespace(name="get_weather", arguments=""),
                                )
                            ],
                        ),
                        finish_reason=None,
                    )
                ],
                usage=None,
            )
            yield types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(
                            content=None,
                            tool_calls=[
                                types.SimpleNamespace(
                                    id=None,
                                    index=0,
                                    function=types.SimpleNamespace(name=None, arguments='{"city":"Berlin"}'),
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        return _stream()


class _SplitToolCallClient:
    def __init__(self) -> None:
        self.chat = types.SimpleNamespace(completions=_SplitToolCallCompletions())


def _load_openai_provider() -> Dict[str, Any]:
    return yaml.safe_load(OPENAI_PROVIDER_YAML.read_text(encoding="utf-8"))


def _openai_model_by_id() -> Dict[str, Dict[str, Any]]:
    provider = _load_openai_provider()
    return {model["id"]: model for model in provider["models"] if isinstance(model, dict)}


def _provider_with_legacy_gpt56_models() -> Dict[str, Any]:
    """Exercise legacy request mapping without restoring retired catalog entries."""
    provider = _load_openai_provider()
    existing_ids = {model["id"] for model in provider["models"] if isinstance(model, dict)}
    for model_id, expected in EXPECTED_GPT56_MODELS.items():
        if model_id in existing_ids:
            continue
        provider["models"].append({
            "id": model_id,
            "default_server": "openai",
            "servers": [{"id": "openai", "model_id": expected["upstream_model_id"], "region": "US"}],
            "reasoning": model_id != "gpt-5.6-luna",
            "reasoning_effort": expected["reasoning_effort"],
        })
    return provider


def _module(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    return module


def _load_llm_utils_with_stubs(monkeypatch: pytest.MonkeyPatch, openai_provider: Any) -> Any:
    provider_configs = {
        "openai": {
            "models": [
                {
                    "id": "gpt-5.6-sol-max",
                    "default_server": "openai",
                    "servers": [{"id": "openai", "model_id": "gpt-5.6-sol", "region": "US"}],
                    "reasoning": True,
                }
            ]
        }
    }

    class _ConfigManager:
        _provider_configs = provider_configs

        def get_provider_configs(self) -> dict[str, Any]:
            return provider_configs

        def get_provider_config(self, provider_id: str) -> Optional[dict[str, Any]]:
            return provider_configs.get(provider_id)

        def get_model_pricing(self, provider_id: str, model_id: str) -> Optional[dict[str, Any]]:
            return None

    class _CacheService:
        @property
        async def client(self) -> None:
            return None

    monkeypatch.setitem(sys.modules, "dotenv", _module("dotenv", load_dotenv=lambda: None))
    monkeypatch.setitem(sys.modules, "toon_format", _module("toon_format", decode=lambda value: value, encode=lambda value: value))
    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.llm_providers.mistral_client",
        _module(
            "mistral_client",
            UnifiedMistralResponse=type("UnifiedMistralResponse", (), {}),
            MISTRAL_THINKING_STATE_KEY="mistral_thinking",
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.llm_providers.google_client",
        _module(
            "google_client",
            UnifiedGoogleResponse=type("UnifiedGoogleResponse", (), {}),
            ParsedGoogleToolCall=type("ParsedGoogleToolCall", (), {}),
            GOOGLE_THOUGHT_SIGNATURE_PROVIDER_STATE_KEY="google_thought_signature",
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.llm_providers.anthropic_client",
        _module("anthropic_client", UnifiedAnthropicResponse=type("UnifiedAnthropicResponse", (), {})),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.llm_providers.bedrock_shared",
        _module("bedrock_shared", UnifiedBedrockResponse=type("UnifiedBedrockResponse", (), {})),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.llm_providers.openai_shared",
        _module(
            "openai_shared",
            UnifiedOpenAIResponse=type("UnifiedOpenAIResponse", (), {}),
            _sanitize_schema_for_llm_providers=lambda schema: schema,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.utils.timeout_utils",
        _module(
            "timeout_utils",
            stream_with_first_chunk_timeout=lambda stream, *_args: stream,
            PREPROCESSING_TIMEOUT_SECONDS=30,
            PREPROCESSING_TOTAL_TIMEOUT_SECONDS=120,
            get_first_chunk_timeout_seconds=lambda **_kwargs: 30,
            get_inter_chunk_timeout_seconds=lambda **_kwargs: 30,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.apps.ai.utils.preprocessing_history",
        _module(
            "preprocessing_history",
            STANDARDIZED_USER_ERROR_MESSAGE="standardized error",
            normalize_preprocessing_message_history=lambda messages: messages,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.utils.secrets_manager",
        _module("secrets_manager", SecretsManager=type("SecretsManager", (), {})),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.utils.text_sanitization",
        _module(
            "text_sanitization",
            sanitize_text_payload_for_ascii_smuggling=lambda value, **_kwargs: (value, False),
            sanitize_text_simple=lambda value, **_kwargs: value,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.services.team_chat_ai_service",
        _module("team_chat_ai_service", format_sender_attributed_content=lambda *args, **_kwargs: args[0] if args else ""),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.utils.config_manager",
        _module("config_manager", config_manager=_ConfigManager()),
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache", _module("cache", CacheService=_CacheService))
    monkeypatch.setitem(
        sys.modules,
        "backend.shared.python_utils.tracing.ai_observability",
        _module("ai_observability", ai_provider_span=lambda *_args, **_kwargs: nullcontext()),
    )

    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: Optional[str] = None) -> types.ModuleType:
        if name == "backend.apps.ai.llm_providers.openai_client":
            return _module("openai_client", invoke_openai_chat_completions=openai_provider)
        if name.startswith("backend.apps.ai.llm_providers."):
            return _module(name)
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    spec = importlib.util.spec_from_file_location("gpt56_llm_utils_under_test", LLM_UTILS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gpt56_catalog_entries_define_routing_pricing_and_capabilities() -> None:
    models = _openai_model_by_id()

    assert {model_id for model_id in EXPECTED_GPT56_MODELS if model_id in models} == {"gpt-5.6-terra"}
    for model_id in ("gpt-5.6-terra",):
        expected = EXPECTED_GPT56_MODELS[model_id]
        model = models[model_id]
        assert model["name"] == expected["name"]
        assert model["country_origin"] == "US"
        assert model["for_app_skill"] == "ai.ask"
        assert model["allow_auto_select"] is True
        assert model["input_types"] == ["text", "image"]
        assert model["output_types"] == ["text"]
        assert model["default_server"] == "openai"
        assert model["servers"] == [
            {
                "id": "openai",
                "name": "OpenAI API",
                "model_id": expected["upstream_model_id"],
                "region": "US",
            }
        ]
        assert model["pricing"]["tokens"]["input"]["per_credit_unit"] == expected["input_tokens_per_credit"]
        assert model["pricing"]["tokens"]["output"]["per_credit_unit"] == expected["output_tokens_per_credit"]
        assert model["costs"]["input_per_million_token"]["price"] == expected["input_cost"]
        assert model["costs"]["cached_input_per_million_token"]["price"] == expected["cached_input_cost"]
        assert model["costs"]["cache_write_per_million_token"]["price"] == expected["cache_write_cost"]
        assert model["costs"]["output_per_million_token"]["price"] == expected["output_cost"]
        assert model["features"]["reasoning_token_support"] is True
        assert model["features"]["tool_use"] is True
        assert model["features"]["streaming"] is True
        assert model["reasoning"] is True
        assert model.get("reasoning_effort") == expected["reasoning_effort"]


def test_openai_request_model_overrides_simple_and_complex_auto_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "celery", types.SimpleNamespace(Celery=object))
    from backend.apps.ai.skills.ask_skill import AskSkill, OpenAICompletionRequest

    request = OpenAICompletionRequest(
        model="openai/gpt-5.6-luna",
        messages=[{"role": "user", "content": "Say hello"}],
        _user_id="user-1",
    )

    internal_request = asyncio.run(AskSkill._transform_openai_to_internal(object(), request))

    assert internal_request.user_preferences["default_ai_model_simple"] == "openai/gpt-5.6-luna"
    assert internal_request.user_preferences["default_ai_model_complex"] == "openai/gpt-5.6-luna"


@pytest.mark.parametrize(
    ("request_model_id", "catalog_model_id", "expected_upstream_model_id", "expected_reasoning_effort"),
    [
        ("gpt-5.6-sol", None, "gpt-5.6-sol", "medium"),
        ("gpt-5.6-sol", "gpt-5.6-sol-max", "gpt-5.6-sol", "max"),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
# contract-test: supporting surface=gui.web assertions=ai-model-routing.catalog.capability-recommendation-variants
def test_gpt56_payload_uses_catalog_upstream_model_and_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
    request_model_id: str,
    catalog_model_id: Optional[str],
    expected_upstream_model_id: str,
    expected_reasoning_effort: str,
    stream: bool,
) -> None:
    provider = _provider_with_legacy_gpt56_models()
    model_by_id = {model["id"]: model for model in provider["models"] if isinstance(model, dict)}
    stub = _StubClient()

    monkeypatch.setattr(openai_client, "_openai_direct_client", stub)
    monkeypatch.setattr(openai_client.config_manager, "get_provider_config", lambda provider_id: provider if provider_id == "openai" else None)
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda provider_id, model_id: model_by_id.get(model_id) if provider_id == "openai" else None)
    monkeypatch.setattr(
        openai_client,
        "calculate_token_breakdown",
        lambda *_a, **_k: {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
        raising=False,
    )

    async def invoke() -> None:
        response = await openai_client._invoke_openai_direct_api(
            task_id=f"t-{catalog_model_id or request_model_id}",
            model_id=request_model_id,
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=16,
            stream=stream,
            catalog_model_id=catalog_model_id,
        )
        if stream:
            chunks = [chunk async for chunk in response]
            assert chunks[0] == "ok"

    asyncio.run(invoke())

    captured = stub.chat.completions.captured
    assert captured["model"] == expected_upstream_model_id
    assert captured["reasoning_effort"] == expected_reasoning_effort
    assert "temperature" not in captured
    assert captured["max_completion_tokens"] == 16


def test_gpt56_stream_payload_uses_catalog_upstream_model_and_reasoning_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_legacy_gpt56_models()
    model_by_id = {model["id"]: model for model in provider["models"] if isinstance(model, dict)}
    stub = _StubClient()

    monkeypatch.setattr(openai_client, "_openai_direct_client", stub)
    monkeypatch.setattr(openai_client.config_manager, "get_provider_config", lambda provider_id: provider if provider_id == "openai" else None)
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda provider_id, model_id: model_by_id.get(model_id) if provider_id == "openai" else None)
    monkeypatch.setattr(
        openai_client,
        "calculate_token_breakdown",
        lambda *_a, **_k: {"user_input_tokens": 1, "system_prompt_tokens": 0},
        raising=False,
    )

    async def consume_stream() -> list[Any]:
        stream = await openai_client._invoke_openai_direct_api(
            task_id="t-stream-sol-max",
            model_id="gpt-5.6-sol",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=16,
            stream=True,
            catalog_model_id="gpt-5.6-sol-max",
        )
        chunks: list[Any] = []
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume_stream())
    captured = stub.chat.completions.captured
    assert chunks[0] == "ok"
    assert captured["model"] == "gpt-5.6-sol"
    assert captured["reasoning_effort"] == "max"
    assert "temperature" not in captured
    assert captured["max_completion_tokens"] == 16


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("model_id", ["gpt-5.6-luna", "gpt-6-luna"])
def test_chat_completion_cache_boundary_keeps_system_text_and_history(
    monkeypatch: pytest.MonkeyPatch, model_id: str, stream: bool,
) -> None:
    stub = _StubClient()
    monkeypatch.setattr(openai_client, "_openai_direct_client", stub)
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda *_args: None)
    monkeypatch.setattr(openai_client, "calculate_token_breakdown", lambda *_a, **_k: {}, raising=False)
    messages = [
        {"role": "system", "content": "stable rules\n\nclock 12:00"},
        {"role": "user", "content": "A question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Follow-up"},
    ]

    async def run() -> None:
        response = await openai_client._invoke_openai_direct_api(
            task_id="chat-cache", model_id=model_id, messages=messages,
            cacheable_system_prefix="stable rules", stream=stream,
        )
        if stream:
            async for _chunk in response:
                pass

    asyncio.run(run())
    sent = stub.chat.completions.captured["messages"]
    assert sent[0]["content"] == [
        {"type": "text", "text": "stable rules", "prompt_cache_breakpoint": {"mode": "explicit"}},
        {"type": "text", "text": "\n\nclock 12:00"},
    ]
    assert "".join(part["text"] for part in sent[0]["content"]) == messages[0]["content"]
    assert sent[1:] == messages[1:]
    assert messages[0]["content"] == "stable rules\n\nclock 12:00"


def test_cache_boundary_skips_unsupported_or_invalid_prefix() -> None:
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "question"}]
    assert openai_client._openai_cache_messages(messages, "gpt-5.4", "system") is messages
    assert openai_client._openai_cache_messages(messages, "gpt-6-luna", "missing") is messages
    assert openai_client._openai_cache_messages(messages, "gpt-6-luna", None) is messages


@pytest.mark.parametrize("stream", [False, True])
def test_gpt56_luna_tool_payload_disables_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
) -> None:
    provider = _provider_with_legacy_gpt56_models()
    model_by_id = {model["id"]: model for model in provider["models"] if isinstance(model, dict)}
    stub = _StubClient()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city.",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]

    monkeypatch.setattr(openai_client, "_openai_direct_client", stub)
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda provider_id, model_id: model_by_id.get(model_id) if provider_id == "openai" else None)
    monkeypatch.setattr(
        openai_client,
        "calculate_token_breakdown",
        lambda *_a, **_k: {"user_input_tokens": 1, "system_prompt_tokens": 0},
        raising=False,
    )

    async def invoke() -> None:
        response = await openai_client._invoke_openai_direct_api(
            task_id=f"t-luna-tools-{stream}",
            model_id="gpt-5.6-luna",
            messages=[{"role": "user", "content": "Weather in Berlin?"}],
            temperature=0.7,
            max_tokens=16,
            tools=tools,
            tool_choice="required",
            stream=stream,
            catalog_model_id="gpt-5.6-luna",
        )
        if stream:
            async for _chunk in response:
                pass

    asyncio.run(invoke())

    captured = stub.chat.completions.captured
    assert captured["reasoning_effort"] == "none"
    assert captured["tools"][0]["function"]["name"] == "get_weather"
    assert captured["tool_choice"] == "required"


def test_streamed_tool_call_deltas_keep_one_stable_call_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_client, "_openai_direct_client", _SplitToolCallClient())
    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", lambda *_args: None)
    monkeypatch.setattr(
        openai_client,
        "calculate_token_breakdown",
        lambda *_a, **_k: {"user_input_tokens": 1, "system_prompt_tokens": 0},
        raising=False,
    )

    async def consume() -> list[Any]:
        response = await openai_client._invoke_openai_direct_api(
            task_id="t-split-tool-call",
            model_id="gpt-5.6-luna",
            messages=[{"role": "user", "content": "Weather in Berlin?"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather for a city.",
                        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                    },
                }
            ],
            tool_choice="required",
            stream=True,
        )
        return [chunk async for chunk in response]

    chunks = asyncio.run(consume())
    tool_calls = [chunk for chunk in chunks if isinstance(chunk, openai_client.ParsedOpenAIToolCall)]

    assert len(tool_calls) == 1
    assert tool_calls[0].tool_call_id == "call-weather"
    assert tool_calls[0].function_name == "get_weather"
    assert tool_calls[0].function_arguments_parsed == {"city": "Berlin"}


def test_gpt56_config_lookup_errors_remain_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_config_error(_provider_id: str, _model_id: str) -> None:
        raise RuntimeError("config failed")

    monkeypatch.setattr(openai_client.config_manager, "get_model_pricing", raise_config_error)

    with pytest.raises(RuntimeError, match="config failed"):
        openai_client._get_openai_request_model_id("gpt-5.6-sol-max")


def test_openai_request_mapping_ignores_non_openai_server_model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_client.config_manager,
        "get_model_pricing",
        lambda provider_id, model_id: {
            "id": model_id,
            "default_server": "aws_bedrock",
            "servers": [
                {"id": "aws_bedrock", "model_id": "us.openai.gpt-oss-120b-1:0"},
                {"id": "openrouter", "model_id": "openai/gpt-oss-120b"},
            ],
        }
        if provider_id == "openai"
        else None,
    )

    assert openai_client._get_openai_request_model_id("openai/gpt-oss-120b") == "gpt-oss-120b"


def test_call_main_llm_stream_preserves_openai_catalog_model_id_after_server_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, Any] = {}

    async def openai_provider(**kwargs: Any) -> Any:
        captured.update(kwargs)

        async def stream() -> Any:
            yield "ok"

        return stream()

    llm_utils = _load_llm_utils_with_stubs(monkeypatch, openai_provider)

    async def consume_stream() -> list[Any]:
        chunks: list[Any] = []
        stream = llm_utils.call_main_llm_stream(
            task_id="task-openai-sol-max",
            model_id="openai/gpt-5.6-sol-max",
            system_prompt="system",
            message_history=[{"role": "user", "content": "hello"}],
            temperature=0.2,
            tools=None,
            tool_choice="auto",
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    assert asyncio.run(consume_stream()) == ["ok"]
    assert captured["model_id"] == "gpt-5.6-sol"
    assert captured["catalog_model_id"] == "gpt-5.6-sol-max"


def test_main_stream_attaches_frozen_route_usage_to_native_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    class OpenAIUsageMetadata:
        input_tokens = 120
        output_tokens = 8
        cache_read_input_tokens = 40
        cache_creation_input_tokens = None
        user_input_tokens = None
        system_prompt_tokens = None
        provider_request_id = "provider-request"

    emitted: list[OpenAIUsageMetadata] = []

    async def openai_provider(**_kwargs: Any) -> Any:
        async def stream() -> Any:
            for _ in range(2):
                usage = OpenAIUsageMetadata()
                emitted.append(usage)
                yield usage
            yield "ok"

        return stream()

    llm_utils = _load_llm_utils_with_stubs(monkeypatch, openai_provider)
    tariff = {
        "pricing": {"tokens": {"input": {"per_credit_unit": 100}, "output": {"per_credit_unit": 50}}},
        "cache_pricing": {"enabled": False},
        "local": True,
    }
    monkeypatch.setattr(llm_utils.config_manager, "get_model_pricing", lambda _provider, _model: tariff)

    async def consume_stream() -> list[Any]:
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="route-usage", model_id="openai/gpt-5.6-sol-max",
            system_prompt="stable\n\ndynamic", message_history=[], temperature=0.2,
        )]

    assert asyncio.run(consume_stream()) == [*emitted, "ok"]
    first = emitted[0]._normalized_llm_usage
    second = emitted[1]._normalized_llm_usage
    assert first.model_id == "openai/gpt-5.6-sol-max"
    assert first.inference_host == "openai"
    assert first.region == "US"
    assert first.attempt_id and first.attempt_id == second.attempt_id
    assert first.provider_request_id == "provider-request"
    assert (first.input_total, first.input_uncached, first.cache_read_input_tokens) == (120, 80, 40)
    assert first.tariff_snapshot["local"] is True
    tariff["pricing"]["tokens"]["input"]["per_credit_unit"] = 1
    assert first.tariff_snapshot["pricing"]["tokens"]["input"]["per_credit_unit"] == 100


def test_main_stream_forwards_cache_hints_only_to_direct_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(**_kwargs: Any) -> Any:
        async def stream() -> Any:
            yield "ok"
        return stream()

    llm_utils = _load_llm_utils_with_stubs(monkeypatch, provider)
    captured: dict[str, dict[str, Any]] = {}
    cache_policy = {
        "enabled": True, "eligible_hosts": ["anthropic", "aws_bedrock", "openai"],
        "status": "verified_for_activation", "source_url": "https://example.com/pricing",
        "reviewed_on": "2026-10-01", "expires_on": "2099-12-31",
    }
    monkeypatch.setattr(
        llm_utils.config_manager, "get_model_pricing",
        lambda _provider, _model: {"cache_pricing": cache_policy},
    )

    async def capture(**kwargs: Any) -> Any:
        captured[kwargs["task_id"]] = kwargs
        return await provider(**kwargs)

    monkeypatch.setattr(llm_utils, "_get_provider_client", lambda _server: capture)

    async def consume(host: str) -> None:
        result = [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id=host, model_id=f"{host}/test-model", system_prompt="stable\n\ndynamic",
            message_history=[], temperature=0.2, cacheable_system_prefix="stable",
            prompt_cache_key="opaque-conversation-key",
            customer_cache_pricing_enabled=True,
        )]
        assert result == ["ok"]

    async def run() -> None:
        for host in ("anthropic", "aws_bedrock", "openai", "mistral", "openrouter"):
            await consume(host)

    asyncio.run(run())
    for host in ("anthropic", "aws_bedrock", "openai"):
        assert captured[host]["cacheable_system_prefix"] == "stable"
        assert "prompt_cache_key" not in captured[host]
    assert captured["mistral"]["prompt_cache_key"] == "opaque-conversation-key"
    assert "cacheable_system_prefix" not in captured["mistral"]
    assert "cacheable_system_prefix" not in captured["openrouter"]
    assert "prompt_cache_key" not in captured["openrouter"]

    # Disabled or ineligible tariffs cannot request a new paid cache checkpoint.
    cache_policy["enabled"] = False
    asyncio.run(consume("anthropic"))
    assert "cacheable_system_prefix" not in captured["anthropic"]
    asyncio.run(consume("openai"))
    assert "cacheable_system_prefix" not in captured["openai"]
    cache_policy.update({"enabled": True, "eligible_hosts": ["anthropic"]})
    asyncio.run(consume("aws_bedrock"))
    assert "cacheable_system_prefix" not in captured["aws_bedrock"]


def test_main_stream_preserves_failed_server_usage_before_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class OpenAIUsageMetadata:
        input_tokens = 30
        output_tokens = 2
        cache_read_input_tokens = 0

    class MistralUsage:
        prompt_tokens = 40
        completion_tokens = 6
        cache_read_input_tokens = 0

    async def unused_provider(**_kwargs: Any) -> Any:
        raise AssertionError("Provider dispatch should use the selected route")

    llm_utils = _load_llm_utils_with_stubs(monkeypatch, unused_provider)
    monkeypatch.setattr(llm_utils, "resolve_fallback_servers_from_provider_config", lambda _model: ["mistral/fallback"])

    async def primary(**_kwargs: Any) -> Any:
        async def stream() -> Any:
            yield OpenAIUsageMetadata()
            yield "[ERROR 503 provider failed]"
        return stream()

    async def fallback(**_kwargs: Any) -> Any:
        async def stream() -> Any:
            yield "recovered"
            yield MistralUsage()
        return stream()

    monkeypatch.setattr(
        llm_utils, "_get_provider_client",
        lambda server: primary if server == "openai" else fallback,
    )

    async def consume() -> list[Any]:
        return [chunk async for chunk in llm_utils.call_main_llm_stream(
            task_id="failed-server-usage", model_id="openai/gpt-5.6-sol-max",
            system_prompt="system", message_history=[], temperature=0.2,
        )]

    chunks = asyncio.run(consume())
    assert [type(chunk).__name__ if not isinstance(chunk, str) else chunk for chunk in chunks] == [
        "OpenAIUsageMetadata", "recovered", "MistralUsage",
    ]
    first = chunks[0]._normalized_llm_usage
    second = chunks[2]._normalized_llm_usage
    assert first.model_id == second.model_id == "openai/gpt-5.6-sol-max"
    assert (first.inference_host, second.inference_host) == ("openai", "mistral")
    assert first.attempt_id != second.attempt_id
