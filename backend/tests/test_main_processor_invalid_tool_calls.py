# backend/tests/test_main_processor_invalid_tool_calls.py
# Regression tests for invalid AI tool-call handling in main processing.
# Invalid LLM-emitted tools must not execute or surface as embeds, but their
# streamed tool_use blocks still need matched tool_result entries for provider
# protocol integrity across Gemini, Bedrock, OpenAI, Anthropic, and Mistral.

import asyncio
import importlib
import json
import sys
import types
from types import SimpleNamespace

toon_format_stub = types.ModuleType("toon_format")
toon_format_stub.encode = lambda value: str(value)
toon_format_stub.decode = lambda value: value
sys.modules.setdefault("toon_format", toon_format_stub)

ask_skill_stub = types.ModuleType("backend.apps.ai.skills.ask_skill")
ask_skill_stub.AskSkillRequest = object
sys.modules.setdefault("backend.apps.ai.skills.ask_skill", ask_skill_stub)

preprocessor_stub = types.ModuleType("backend.apps.ai.processing.preprocessor")
preprocessor_stub.IMAGE_CHAT_SAFE_MODEL_ID = "test-model"
preprocessor_stub.IMAGE_CHAT_SAFE_MODEL_NAME = "Test Model"
preprocessor_stub.PreprocessingResult = object
sys.modules.setdefault("backend.apps.ai.processing.preprocessor", preprocessor_stub)

mate_utils_stub = types.ModuleType("backend.apps.ai.utils.mate_utils")
mate_utils_stub.MateConfig = object
sys.modules.setdefault("backend.apps.ai.utils.mate_utils", mate_utils_stub)

llm_utils_stub = types.ModuleType("backend.apps.ai.utils.llm_utils")
llm_utils_stub.call_main_llm_stream = object
llm_utils_stub.truncate_message_history_to_token_budget = object
llm_utils_stub.AllServersFailedError = Exception
llm_utils_stub.STANDARDIZED_USER_ERROR_MESSAGE = "Model unavailable."
sys.modules.setdefault("backend.apps.ai.utils.llm_utils", llm_utils_stub)

stream_utils_stub = types.ModuleType("backend.apps.ai.utils.stream_utils")
stream_utils_stub.aggregate_paragraphs = object
sys.modules.setdefault("backend.apps.ai.utils.stream_utils", stream_utils_stub)

override_parser_stub = types.ModuleType("backend.core.api.app.utils.override_parser")
override_parser_stub.UserOverrides = object
sys.modules.setdefault("backend.core.api.app.utils.override_parser", override_parser_stub)

for module_name, symbols in {
    "backend.apps.ai.llm_providers.mistral_client": ["ParsedMistralToolCall", "MistralUsage"],
    "backend.apps.ai.llm_providers.google_client": ["GoogleUsageMetadata", "ParsedGoogleToolCall"],
    "backend.apps.ai.llm_providers.anthropic_client": ["ParsedAnthropicToolCall", "AnthropicUsageMetadata"],
    "backend.apps.ai.llm_providers.bedrock_shared": ["ParsedBedrockToolCall", "BedrockUsageMetadata"],
    "backend.apps.ai.llm_providers.openai_shared": ["ParsedOpenAIToolCall", "OpenAIUsageMetadata"],
}.items():
    module = types.ModuleType(module_name)
    for symbol in symbols:
        setattr(module, symbol, object)
    sys.modules.setdefault(module_name, module)

provider_types_stub = types.ModuleType("backend.apps.ai.llm_providers.types")
provider_types_stub.UnifiedStreamChunk = object
provider_types_stub.StreamChunkType = object
sys.modules.setdefault("backend.apps.ai.llm_providers.types", provider_types_stub)

app_metadata_stub = types.ModuleType("backend.shared.python_schemas.app_metadata_schemas")
app_metadata_stub.AppYAML = object
app_metadata_stub.AppSkillDefinition = object
sys.modules.setdefault("backend.shared.python_schemas.app_metadata_schemas", app_metadata_stub)

wikipedia_stub = types.ModuleType("backend.shared.providers.wikipedia.wikipedia_api")
wikipedia_stub.normalize_wikipedia_language = lambda language: language
sys.modules.setdefault("backend.shared.providers.wikipedia.wikipedia_api", wikipedia_stub)

secrets_stub = types.ModuleType("backend.core.api.app.utils.secrets_manager")
secrets_stub.SecretsManager = object
sys.modules.setdefault("backend.core.api.app.utils.secrets_manager", secrets_stub)

config_stub = types.ModuleType("backend.core.api.app.utils.config_manager")
config_stub.ConfigManager = object
config_stub.config_manager = SimpleNamespace(get_model_pricing=lambda *_args, **_kwargs: None)
sys.modules.setdefault("backend.core.api.app.utils.config_manager", config_stub)

directus_stub = types.ModuleType("backend.core.api.app.services.directus.directus")
directus_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus.directus", directus_stub)

cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)

encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
sys.modules.setdefault("backend.core.api.app.utils.encryption", encryption_stub)

translations_stub = types.ModuleType("backend.core.api.app.services.translations")
translations_stub.TranslationService = object
sys.modules.setdefault("backend.core.api.app.services.translations", translations_stub)

tool_generator_stub = types.ModuleType("backend.apps.ai.processing.tool_generator")
tool_generator_stub.generate_tools_from_apps = object
sys.modules.setdefault("backend.apps.ai.processing.tool_generator", tool_generator_stub)

audio_guard_stub = types.ModuleType("backend.apps.ai.processing.audio_recording_guard")
audio_guard_stub.AUDIO_TRANSCRIBE_SKILL_ID = "audio-transcribe"
audio_guard_stub.has_transcribed_web_audio_recording = lambda *_args, **_kwargs: False
sys.modules.setdefault("backend.apps.ai.processing.audio_recording_guard", audio_guard_stub)

sub_chat_stub = types.ModuleType("backend.apps.ai.sub_chat_orchestration")
for symbol in [
    "count_direct_sub_chats",
    "create_and_dispatch_sub_chats",
    "create_sub_chat_records",
    "dispatch_sub_chat_task",
    "expand_sub_chat_requests",
    "get_sub_chat_context_policy",
    "get_sub_chat_execution_mode",
    "store_pending_sub_chat_confirmation",
    "validate_sub_chat_capacity",
]:
    setattr(sub_chat_stub, symbol, object)
sub_chat_stub.MAX_AUTO_SUB_CHATS_PER_TURN = 3
sub_chat_stub.MAX_DIRECT_SUB_CHATS_PER_PARENT = 3
sys.modules.setdefault("backend.apps.ai.sub_chat_orchestration", sub_chat_stub)

skill_executor_stub = types.ModuleType("backend.apps.ai.processing.skill_executor")
skill_executor_stub.execute_skill_with_multiple_requests = object
skill_executor_stub.SkillCancelledException = Exception
skill_executor_stub.generate_skill_task_id = lambda: "skill-task-id"
skill_executor_stub.DEFAULT_SKILL_TIMEOUT = 30
sys.modules.setdefault("backend.apps.ai.processing.skill_executor", skill_executor_stub)

billing_stub = types.ModuleType("backend.shared.python_utils.billing_utils")
billing_stub.calculate_total_credits = lambda *_args, **_kwargs: 0
billing_stub.MINIMUM_CREDITS_CHARGED = 1
sys.modules.setdefault("backend.shared.python_utils.billing_utils", billing_stub)

main_processor = importlib.import_module("backend.apps.ai.processing.main_processor")
INVALID_TOOL_FALLBACK_MESSAGE = main_processor.INVALID_TOOL_FALLBACK_MESSAGE
INVALID_TOOL_RESULT_REASON = main_processor.INVALID_TOOL_RESULT_REASON
_append_tool_call_turn_to_history = main_processor._append_tool_call_turn_to_history
_get_skill_execution_args = main_processor._get_skill_execution_args
_has_diffable_embeds_for_prompt = main_processor._has_diffable_embeds_for_prompt


def test_invalid_tool_calls_are_hidden_protocol_bookkeeping() -> None:
    history = []
    valid_tool = SimpleNamespace(
        tool_call_id="valid-call",
        function_name="web-search",
        function_arguments_raw='{"query":"gamescom dates"}',
        thought_signature="valid-signature",
    )
    invalid_tool = SimpleNamespace(
        tool_call_id="invalid-call",
        function_name="travel-search_flights",
        function_arguments_raw='{"from":"BER"}',
        thought_signature="invalid-signature",
    )
    rejection_message = {
        "tool_call_id": invalid_tool.tool_call_id,
        "role": "tool",
        "name": invalid_tool.function_name,
        "content": json.dumps({"status": "rejected", "reason": INVALID_TOOL_RESULT_REASON}),
    }

    _append_tool_call_turn_to_history(
        history,
        tool_calls=[valid_tool],
        rejected_tool_calls=[(invalid_tool, rejection_message)],
        assistant_content="",
    )

    assert len(history) == 2
    assistant_message = history[0]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"] is None
    assert [call["id"] for call in assistant_message["tool_calls"]] == ["valid-call", "invalid-call"]
    assert assistant_message["tool_calls"][0]["thought_signature"] == "valid-signature"
    assert assistant_message["tool_calls"][1]["thought_signature"] == "invalid-signature"

    tool_result = history[1]
    result_payload = json.loads(tool_result["content"])
    assert tool_result["tool_call_id"] == "invalid-call"
    assert result_payload["status"] == "rejected"
    assert "travel-search_flights" not in result_payload["reason"]
    assert "unavailable internal tools" in result_payload["reason"]


def test_invalid_tool_fallback_message_does_not_name_internal_tools() -> None:
    assert "travel-search_flights" not in INVALID_TOOL_FALLBACK_MESSAGE
    assert "tool" not in INVALID_TOOL_FALLBACK_MESSAGE.lower()


def test_skill_execution_uses_placeholder_normalized_args() -> None:
    parsed_args = {
        "requests": [
            {"id": "search_aethos", "query": "aethos"},
            {"id": "search_foresight", "query": "foresight"},
        ]
    }
    placeholder_args = {
        "requests": [
            {"id": 1, "query": "aethos"},
            {"id": 2, "query": "foresight"},
        ]
    }

    assert _get_skill_execution_args(
        parsed_args,
        {"multiple": True, "parsed_args": placeholder_args},
    ) is placeholder_args


def test_skill_execution_falls_back_to_fresh_args_without_placeholder_args() -> None:
    parsed_args = {"requests": [{"id": "search_aethos", "query": "aethos"}]}

    assert _get_skill_execution_args(parsed_args, {"multiple": True}) is parsed_args


def test_diff_prompt_uses_resolved_embed_file_path_index() -> None:
    request = SimpleNamespace(
        message_history=[SimpleNamespace(role="user", content="Please edit the previous artifact.")],
        embed_file_path_index={"average.py-AbC": "embed-1"},
    )

    assert asyncio.run(_has_diffable_embeds_for_prompt(request)) is True


def test_diff_prompt_accepts_compact_toon_type_marker() -> None:
    request = SimpleNamespace(
        message_history=[SimpleNamespace(role="assistant", content="```toon\ntype:code\nembed_ref: average.py-AbC\n```")],
        embed_file_path_index=None,
    )

    assert asyncio.run(_has_diffable_embeds_for_prompt(request)) is True


def test_diff_prompt_accepts_pcb_schematic_type_marker() -> None:
    request = SimpleNamespace(
        message_history=[
            SimpleNamespace(
                role="assistant",
                content="```toon\ntype:pcb_schematic\nembed_ref: regulator.ato-AbC\n```",
            )
        ],
        embed_file_path_index=None,
    )

    assert asyncio.run(_has_diffable_embeds_for_prompt(request)) is True


def test_diff_prompt_uses_cached_chat_embed_metadata() -> None:
    class CacheServiceStub:
        async def get_chat_embed_ids(self, chat_id: str) -> list[str]:
            assert chat_id == "chat-1"
            return ["embed-1"]

        async def get_embed_from_cache(self, embed_id: str) -> dict[str, str]:
            assert embed_id == "embed-1"
            return {"type": "code"}

    request = SimpleNamespace(
        chat_id="chat-1",
        message_history=[SimpleNamespace(role="user", content="Please edit the previous artifact.")],
        embed_file_path_index=None,
    )

    assert asyncio.run(_has_diffable_embeds_for_prompt(request, cache_service=CacheServiceStub())) is True


def test_diff_prompt_uses_content_catalog_diff_editable_metadata() -> None:
    class CacheServiceStub:
        async def get_chat_embed_ids(self, chat_id: str) -> list[str]:
            assert chat_id == "chat-1"
            return ["embed-1"]

        async def get_embed_from_cache(self, embed_id: str) -> dict[str, str]:
            assert embed_id == "embed-1"
            return {"type": "future_source_embed"}

        async def get_discovered_apps_metadata(self) -> dict[str, SimpleNamespace]:
            return {
                "future_app": SimpleNamespace(
                    embed_types=[
                        SimpleNamespace(
                            id="source",
                            backend_type="future_source_embed",
                            frontend_type="future-source-embed",
                            content_catalog={
                                "enabled": True,
                                "content_type_id": "future_source",
                                "diff_editable": True,
                            },
                        )
                    ]
                )
            }

    request = SimpleNamespace(
        chat_id="chat-1",
        message_history=[SimpleNamespace(role="user", content="Please edit the previous artifact.")],
        embed_file_path_index=None,
    )

    assert asyncio.run(_has_diffable_embeds_for_prompt(request, cache_service=CacheServiceStub())) is True


def test_diff_prompt_uses_directus_file_path_metadata_when_cache_misses() -> None:
    class CacheServiceStub:
        async def get_chat_embed_ids(self, chat_id: str) -> list[str]:
            assert chat_id == "chat-1"
            return []

    class EmbedMethodsStub:
        async def get_embeds_by_hashed_chat_id(self, hashed_chat_id: str) -> list[dict[str, str]]:
            assert hashed_chat_id
            return [{"file_path": "average.py"}]

    request = SimpleNamespace(
        chat_id="chat-1",
        message_history=[SimpleNamespace(role="user", content="Please edit the previous artifact.")],
        embed_file_path_index=None,
    )
    directus_service = SimpleNamespace(embed=EmbedMethodsStub())

    assert asyncio.run(
        _has_diffable_embeds_for_prompt(
            request,
            cache_service=CacheServiceStub(),
            directus_service=directus_service,
        )
    ) is True


def test_diff_prompt_skips_when_no_prior_embed_reference_exists() -> None:
    request = SimpleNamespace(
        message_history=[SimpleNamespace(role="user", content="Write a brand new helper function.")],
        embed_file_path_index=None,
    )

    assert asyncio.run(_has_diffable_embeds_for_prompt(request)) is False
