# contract-test-file: infrastructure
# ruff: noqa: E402
"""
Regression tests for AI stream recovery metadata.

Saved CLI chats require final AI frames to include a sealed recovery job so the
client can persist encrypted assistant messages locally without trusting streamed
plaintext. These tests cover non-LLM fake-stream paths that bypass normal stream
aggregation.
"""

from __future__ import annotations

import asyncio
import inspect
import importlib
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

if "tiktoken" not in sys.modules:
    tiktoken_stub = types.ModuleType("tiktoken")
    tiktoken_stub.encoding_for_model = lambda *_args, **_kwargs: None
    tiktoken_stub.get_encoding = lambda *_args, **_kwargs: None
    sys.modules["tiktoken"] = tiktoken_stub

if "toon_format" not in sys.modules:
    toon_stub = types.ModuleType("toon_format")
    toon_stub.decode = lambda value: json.loads(value)
    toon_stub.encode = lambda value: json.dumps(value, ensure_ascii=False)
    sys.modules["toon_format"] = toon_stub

try:
    importlib.import_module("redis.asyncio")
except ImportError:
    pass

if "redis.asyncio" not in sys.modules:
    redis_stub = types.ModuleType("redis")
    redis_asyncio_stub = types.ModuleType("redis.asyncio")
    redis_exceptions_stub = types.ModuleType("redis.exceptions")
    redis_asyncio_stub.Redis = type("Redis", (), {})
    redis_asyncio_stub.from_url = lambda *_args, **_kwargs: None
    redis_exceptions_stub.ConnectionError = ConnectionError
    redis_stub.asyncio = redis_asyncio_stub
    redis_stub.exceptions = redis_exceptions_stub
    sys.modules["redis"] = redis_stub
    sys.modules["redis.asyncio"] = redis_asyncio_stub
    sys.modules["redis.exceptions"] = redis_exceptions_stub

_PROVIDER_STUBS = {
    "backend.apps.ai.llm_providers.mistral_client": {
        "MistralUsage": type("MistralUsage", (), {}),
        "ParsedMistralToolCall": type("ParsedMistralToolCall", (), {}),
        "UnifiedMistralResponse": type("UnifiedMistralResponse", (), {}),
    },
    "backend.apps.ai.llm_providers.google_client": {
        "GoogleUsageMetadata": type("GoogleUsageMetadata", (), {}),
        "ParsedGoogleToolCall": type("ParsedGoogleToolCall", (), {}),
        "UnifiedGoogleResponse": type("UnifiedGoogleResponse", (), {}),
        "invoke_google_chat_completions": None,
    },
    "backend.apps.ai.llm_providers.anthropic_client": {
        "AnthropicUsageMetadata": type("AnthropicUsageMetadata", (), {}),
        "ParsedAnthropicToolCall": type("ParsedAnthropicToolCall", (), {}),
        "UnifiedAnthropicResponse": type("UnifiedAnthropicResponse", (), {}),
    },
    "backend.apps.ai.llm_providers.bedrock_shared": {
        "BedrockUsageMetadata": type("BedrockUsageMetadata", (), {}),
        "ParsedBedrockToolCall": type("ParsedBedrockToolCall", (), {}),
        "UnifiedBedrockResponse": type("UnifiedBedrockResponse", (), {}),
    },
    "backend.apps.ai.llm_providers.openai_shared": {
        "OpenAIUsageMetadata": type("OpenAIUsageMetadata", (), {}),
        "ParsedOpenAIToolCall": type("ParsedOpenAIToolCall", (), {}),
        "UnifiedOpenAIResponse": type("UnifiedOpenAIResponse", (), {}),
        "_sanitize_schema_for_llm_providers": lambda schema: schema,
    },
}
for module_name, attributes in _PROVIDER_STUBS.items():
    if module_name not in sys.modules:
        # Prefer installed response models so this module cannot replace them
        # with empty classes for subsequently collected provider tests.
        try:
            importlib.import_module(module_name)
            continue
        except ImportError:
            pass
        provider_stub = types.ModuleType(module_name)
        for attr_name, attr_value in attributes.items():
            setattr(provider_stub, attr_name, attr_value)
        sys.modules[module_name] = provider_stub

try:
    from backend.apps.ai.processing.preprocessor import PreprocessingResult
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.apps.ai.tasks import stream_consumer
    from backend.apps.ai.tasks import ask_skill_task
    from backend.apps.ai.utils.main_processing_failure import main_processing_failure
    from backend.core.api.app.schemas.chat import AIHistoryMessage
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


class _StubCacheService:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish_event(self, channel: str, payload: dict) -> None:
        self.events.append((channel, payload))


class _MetadataDirectus:
    def __init__(self) -> None:
        self.chat = self
        self.updates: list[dict] = []

    async def get_chat_metadata(self, _chat_id: str) -> dict:
        return {"messages_v": 12}

    async def update_chat_fields_in_directus(self, _chat_id: str, fields: dict) -> bool:
        self.updates.append(fields)
        return True


class _RecoveryCache:
    def __init__(self) -> None:
        self.version_increments: list[tuple[str, str, str]] = []
        self.ai_messages: list[tuple[str, str, str]] = []
        self.version_sets: list[tuple[str, str, str, int]] = []
        self.events: list[tuple[str, dict]] = []

    async def increment_chat_component_version(self, user_id: str, chat_id: str, component: str) -> int:
        self.version_increments.append((user_id, chat_id, component))
        return 13

    async def add_ai_message_to_history(
        self,
        user_id: str,
        chat_id: str,
        message_json: str,
        max_history_length: int = 100,
    ) -> bool:
        self.ai_messages.append((user_id, chat_id, message_json))
        return True

    async def set_chat_version_component(self, user_id: str, chat_id: str, component: str, value: int) -> bool:
        self.version_sets.append((user_id, chat_id, component, value))
        return True

    async def save_chat_message_and_update_versions(self, **kwargs) -> dict:
        raise AssertionError("recovery tasks must not publish or version saved assistant messages")

    async def publish_event(self, channel: str, payload: dict) -> None:
        self.events.append((channel, payload))


class _PersistCache:
    def __init__(self) -> None:
        self.saved_messages: list[dict] = []
        self.events: list[tuple[str, dict]] = []

    async def save_chat_message_and_update_versions(self, **kwargs) -> dict:
        self.saved_messages.append(kwargs)
        return {"ok": True}

    async def publish_event(self, channel: str, payload: dict) -> None:
        self.events.append((channel, payload))


class _Encryption:
    async def encrypt_with_user_key(self, value: str, _key_id: str) -> tuple[str, dict]:
        return f"encrypted:{value}", {}


def test_native_replay_is_encrypted_only_in_ai_cache_and_absent_from_client_events() -> None:
    cache = _PersistCache()
    request = _ask_request()
    state = {"messages": [{"role": "assistant", "provider_transport_state": [{"thinking": "private-reasoning"}]}]}
    asyncio.run(stream_consumer._save_to_cache_and_publish(
        request, "task", "general_knowledge", 101, 2, cache, _Encryption(),
        "user-vault-key", "public answer", "test", native_cache_context=state,
    ))
    assert len(cache.saved_messages) == 1
    row = cache.saved_messages[0]["message_data"]
    assert row.encrypted_native_cache_context.startswith("encrypted:")
    assert json.loads(row.encrypted_native_cache_context.removeprefix("encrypted:")) == state
    assert "private-reasoning" not in json.dumps(cache.events)
    assert "native_cache_context" not in json.dumps(cache.events)


def test_optional_replay_encryption_failure_still_saves_and_publishes_reply() -> None:
    class ReplayEncryptionFailure(_Encryption):
        async def encrypt_with_user_key(self, value: str, key_id: str):
            if value.startswith("{"):
                raise ValueError("replay unavailable")
            return await super().encrypt_with_user_key(value, key_id)

    cache = _PersistCache()
    asyncio.run(stream_consumer._save_to_cache_and_publish(
        _ask_request(), "task", "general_knowledge", 101, 2, cache,
        ReplayEncryptionFailure(), "user-vault-key", "public answer", "test",
        native_cache_context={"messages": []},
    ))
    assert cache.saved_messages[0]["message_data"].encrypted_native_cache_context is None
    assert cache.events[0][1]["message"]["content"] == "public answer"


def test_incognito_reply_does_not_seal_provider_replay_state() -> None:
    cache = _PersistCache()
    request = _ask_request()
    request.is_incognito = True
    asyncio.run(stream_consumer._save_to_cache_and_publish(
        request, "task", "general_knowledge", 101, 2, cache, _Encryption(),
        "user-vault-key", "answer", "test", native_cache_context={"messages": []},
    ))
    assert cache.saved_messages[0]["message_data"].encrypted_native_cache_context is None


def _ask_request(message_history: list[AIHistoryMessage] | None = None) -> AskSkillRequest:
    return AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=message_history or [AIHistoryMessage(role="user", content="hello", created_at=100)],
    )


def test_assistant_response_created_at_anchors_to_triggering_user_turn() -> None:
    request_data = _ask_request([
        AIHistoryMessage(role="user", content="first", created_at=10),
        AIHistoryMessage(role="assistant", content="question", created_at=11),
        AIHistoryMessage(role="user", content="answer", created_at=200),
    ])

    created_at = stream_consumer._assistant_response_created_at(request_data, 999)
    payload = stream_consumer._create_redis_payload(
        "11111111-1111-4111-8111-111111111111",
        request_data,
        "assistant response",
        1,
    )

    assert created_at == 201
    assert payload["created_at"] == 201
    assert payload["user_message_id"] == request_data.message_id


def test_focus_activation_final_marks_pending_continuation() -> None:
    payload = stream_consumer._create_redis_payload(
        "11111111-1111-4111-8111-111111111111",
        _ask_request(),
        "focus activation embed",
        1,
        is_final=True,
        awaiting_focus_mode_continuation=True,
    )

    assert payload["awaiting_focus_mode_continuation"] is True


def test_focus_activation_does_not_seal_recovery_before_continuation() -> None:
    source = inspect.getsource(stream_consumer._consume_main_processing_stream)
    activation_block = source.split("if awaiting_focus_mode_confirmation:", maxsplit=1)[1]
    activation_block = activation_block.split(
        "return aggregated_response, False, False, [], debug_metadata",
        maxsplit=1,
    )[0]

    assert "_attach_sealed_recovery_metadata" not in activation_block


def test_focus_continuation_frames_are_marked() -> None:
    request_data = _ask_request()
    request_data.is_focus_mode_continuation = True

    payload = stream_consumer._create_redis_payload(
        "11111111-1111-4111-8111-111111111111",
        request_data,
        "continued response",
        1,
    )

    assert payload["is_focus_mode_continuation"] is True


def test_async_skill_continuation_frames_keep_operation_and_original_turn() -> None:
    request_data = _ask_request()
    request_data.is_async_skill_continuation = True
    request_data.original_user_message_id = request_data.message_id
    request_data.async_skill_task_id = "operation-1"

    payload = stream_consumer._create_redis_payload(
        "11111111-1111-4111-8111-111111111111",
        request_data,
        "continued response",
        1,
    )

    assert payload["is_async_skill_continuation"] is True
    assert payload["original_user_message_id"] == request_data.message_id
    assert payload["async_skill_task_id"] == "operation-1"


def test_interim_async_skill_response_does_not_seal_recovery() -> None:
    source = inspect.getsource(stream_consumer._consume_main_processing_stream)
    assert "not request_data.awaiting_async_skill_continuation" in source

    request_data = _ask_request()
    request_data.awaiting_async_skill_continuation = True
    payload = stream_consumer._create_redis_payload(
        "11111111-1111-4111-8111-111111111111",
        request_data,
        "waiting for executor",
        1,
        is_final=True,
    )
    assert payload["awaiting_async_skill_continuation"] is True


def test_continuation_stream_payloads_use_continuation_message_id() -> None:
    request_data = _ask_request()
    request_data.continuation_message_id = "99999999-9999-4999-8999-999999999999"

    payload = stream_consumer._create_redis_payload(
        "11111111-1111-4111-8111-111111111111",
        request_data,
        "continued response",
        1,
    )
    thinking_payload = stream_consumer._create_thinking_redis_payload(
        "11111111-1111-4111-8111-111111111111",
        request_data,
        "thinking",
    )

    assert payload["task_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["message_id"] == request_data.continuation_message_id
    assert thinking_payload["task_id"] == "11111111-1111-4111-8111-111111111111"
    assert thinking_payload["message_id"] == request_data.continuation_message_id


def test_assistant_response_created_at_follows_existing_continuation_messages() -> None:
    request_data = _ask_request([
        AIHistoryMessage(role="user", content="start", created_at=100),
        AIHistoryMessage(role="system", content="request settings", created_at=101),
        AIHistoryMessage(role="system", content="settings accepted", created_at=102),
    ])

    assert stream_consumer._assistant_response_created_at(request_data, 999) == 103


def test_persisted_ai_message_broadcast_preserves_parent_user_message_id_and_created_at() -> None:
    request_data = _ask_request()
    cache = _PersistCache()

    asyncio.run(
        stream_consumer._save_to_cache_and_publish(
            request_data=request_data,
            task_id="11111111-1111-4111-8111-111111111111",
            category="general_knowledge",
            timestamp=101,
            messages_version=2,
            cache_service=cache,
            encryption_service=_Encryption(),
            user_vault_key_id="vault-key",
            content_markdown="assistant response",
            log_prefix="test",
            model_name="test-model",
        )
    )

    assert len(cache.saved_messages) == 1
    assert len(cache.events) == 1
    _channel, event = cache.events[0]
    assert event["message"]["created_at"] == 101
    assert event["message"]["user_message_id"] == request_data.message_id


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
def test_non_recovery_metadata_update_publishes_through_cache_once() -> None:
    request_data = _ask_request()
    directus = _MetadataDirectus()
    cache = _PersistCache()
    cache.increment_chat_component_version = AsyncMock(return_value=13)

    asyncio.run(
        stream_consumer._update_chat_metadata(
            request_data=request_data,
            category="general_knowledge",
            timestamp=101,
            content_markdown="assistant response",
            content_tiptap="assistant response",
            directus_service=directus,
            cache_service=cache,
            encryption_service=_Encryption(),
            user_vault_key_id="vault-key",
            task_id="11111111-1111-4111-8111-111111111111",
            log_prefix="test",
            model_name="test-model",
        )
    )

    cache.increment_chat_component_version.assert_awaited_once_with(
        request_data.user_id, request_data.chat_id, "messages_v",
    )
    assert directus.updates[0]["messages_v"] == 13
    assert len(cache.saved_messages) == 1
    assert cache.saved_messages[0]["explicit_messages_v"] == 13
    assert len(cache.events) == 1


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
@pytest.mark.parametrize("response_kind", ["harmful", "simple"])
def test_fake_stream_includes_recovery_job_before_final_marker(monkeypatch, response_kind) -> None:
    task_id = "11111111-1111-4111-8111-111111111111"
    request_data = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="unsafe image", created_at=1)],
        recovery_task_id=task_id,
        recovery_preflight_id="55555555-5555-4555-8555-555555555555",
        recovery_turn_id="66666666-6666-4666-8666-666666666666",
        recovery_public_key="public-key",
        chat_key_version=1,
    )
    preprocessing_result = PreprocessingResult(
        can_proceed=False,
        rejection_reason="misuse_detected",
    )
    cache_service = _StubCacheService()
    cached_timestamps: list[int] = []

    async def fake_charge(*_args, **_kwargs) -> dict:
        return {"prompt_tokens": 0, "completion_tokens": 4, "total_credits": 1}

    async def fake_persist(**kwargs) -> dict:
        assert kwargs["task_id"] == task_id
        assert kwargs["content"] == "I can't help with that request."
        assert kwargs["category"] == "general_knowledge"
        return {"job_id": "77777777-7777-4777-8777-777777777777"}

    async def fake_update_metadata(*_args, **kwargs) -> None:
        cached_timestamps.append(kwargs["timestamp"])
        return None

    monkeypatch.setattr(stream_consumer, "_charge_credits", fake_charge)
    monkeypatch.setattr(stream_consumer, "_persist_sealed_recovery_job", fake_persist)
    monkeypatch.setattr(stream_consumer, "_update_chat_metadata", fake_update_metadata)
    monkeypatch.setattr(
        stream_consumer.celery_config.app,
        "AsyncResult",
        lambda _task_id: SimpleNamespace(state="PENDING"),
    )

    generate = (
        stream_consumer._generate_fake_stream_for_harmful_content
        if response_kind == "harmful"
        else stream_consumer._generate_fake_stream_for_simple_message
    )
    content_keyword = "predefined_response" if response_kind == "harmful" else "message_text"
    asyncio.run(
        generate(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            **{content_keyword: "I can't help with that request."},
            cache_service=cache_service,
            directus_service=object(),
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )
    )

    final_chunks = [
        payload
        for _channel, payload in cache_service.events
        if payload.get("is_final_chunk") is True
    ]
    assert len(final_chunks) == 1
    assert final_chunks[0]["recovery_job_id"] == "77777777-7777-4777-8777-777777777777"
    assert final_chunks[0]["recovery_protocol_version"] == 1
    assert final_chunks[0]["category"] == "general_knowledge"
    assert final_chunks[0]["created_at"] == cached_timestamps[0] == 2


def test_recovery_metadata_update_caches_ai_context_without_terminal_persistence() -> None:
    request_data = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="hello", created_at=100)],
        recovery_task_id="11111111-1111-4111-8111-111111111111",
    )
    directus = _MetadataDirectus()
    cache = _RecoveryCache()

    asyncio.run(
        stream_consumer._update_chat_metadata(
            request_data=request_data,
            category="software_development",
            timestamp=1234,
            content_markdown="assistant response",
            content_tiptap="assistant response",
            directus_service=directus,
            cache_service=cache,
            encryption_service=_Encryption(),
            user_vault_key_id="vault-key",
            task_id="11111111-1111-4111-8111-111111111111",
            log_prefix="test",
            model_name="Gemini 3.5 Flash-Lite",
            native_cache_context={"messages": [{"provider_transport_state": [{"thinking": "private"}]}]},
        )
    )

    assert cache.version_increments == []
    assert cache.version_sets == []
    assert cache.events == []
    assert len(cache.ai_messages) == 1
    cached_user_id, cached_chat_id, cached_message_json = cache.ai_messages[0]
    assert cached_user_id == request_data.user_id
    assert cached_chat_id == request_data.chat_id
    assert "encrypted:assistant response" in cached_message_json
    assert "Gemini 3.5 Flash-Lite" in cached_message_json
    cached_row = json.loads(cached_message_json)
    assert json.loads(cached_row["encrypted_native_cache_context"].removeprefix("encrypted:")) == {
        "messages": [{"provider_transport_state": [{"thinking": "private"}]}],
    }
    assert "private" not in json.dumps(cache.events)
    assert directus.updates == [{
        "last_edited_overall_timestamp": 1234,
        "last_mate_category": "software_development",
        "updated_at": directus.updates[0]["updated_at"],
    }]
    assert "messages_v" not in directus.updates[0]
    assert "last_message_timestamp" not in directus.updates[0]


def test_recovery_native_replay_encryption_failure_keeps_canonical_reply() -> None:
    class ReplayEncryptionFailure(_Encryption):
        async def encrypt_with_user_key(self, value: str, key_id: str):
            if value.startswith("{"):
                raise ValueError("replay unavailable")
            return await super().encrypt_with_user_key(value, key_id)

    request = _ask_request()
    request.recovery_task_id = "11111111-1111-4111-8111-111111111111"
    cache = _RecoveryCache()
    asyncio.run(stream_consumer._update_chat_metadata(
        request_data=request, category="general_knowledge", timestamp=1234,
        content_markdown="assistant response", content_tiptap="assistant response",
        directus_service=_MetadataDirectus(), cache_service=cache,
        encryption_service=ReplayEncryptionFailure(), user_vault_key_id="vault-key",
        task_id=request.recovery_task_id, log_prefix="test",
        native_cache_context={"messages": [{"private": "state"}]},
    ))
    assert len(cache.ai_messages) == 1
    row = json.loads(cache.ai_messages[0][2])
    assert row["encrypted_content"] == "encrypted:assistant response"
    assert row.get("encrypted_native_cache_context") is None
    assert cache.version_increments == cache.version_sets == cache.events == []


def test_recovery_native_replay_admission_failure_retries_without_optional_state() -> None:
    class ReplayRefusingCache(_RecoveryCache):
        async def add_ai_message_to_history(self, user_id, chat_id, message_json, max_history_length=100):
            self.ai_messages.append((user_id, chat_id, message_json))
            return json.loads(message_json).get("encrypted_native_cache_context") is None

    request = _ask_request()
    request.recovery_task_id = "11111111-1111-4111-8111-111111111111"
    cache = ReplayRefusingCache()
    asyncio.run(stream_consumer._update_chat_metadata(
        request_data=request, category="general_knowledge", timestamp=1234,
        content_markdown="assistant response", content_tiptap="assistant response",
        directus_service=_MetadataDirectus(), cache_service=cache,
        encryption_service=_Encryption(), user_vault_key_id="vault-key",
        task_id=request.recovery_task_id, log_prefix="test",
        native_cache_context={"messages": [{"private": "state"}]},
    ))
    assert len(cache.ai_messages) == 2
    assert json.loads(cache.ai_messages[0][2])["encrypted_native_cache_context"]
    final_row = json.loads(cache.ai_messages[1][2])
    assert final_row["encrypted_content"] == "encrypted:assistant response"
    assert final_row.get("encrypted_native_cache_context") is None
    assert cache.version_increments == cache.version_sets == cache.events == []


def test_sub_chat_continuation_uses_recovery_only_metadata_path() -> None:
    request_data = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="hello", created_at=100)],
        recovery_task_id=None,
        recovery_inference_task_id="11111111-1111-4111-8111-111111111111",
        continuation_message_id="99999999-9999-4999-8999-999999999999",
        is_sub_chat_continuation=True,
    )
    directus = _MetadataDirectus()
    cache = _RecoveryCache()

    asyncio.run(
        stream_consumer._update_chat_metadata(
            request_data=request_data,
            category="software_development",
            timestamp=1234,
            content_markdown="final synthesis",
            content_tiptap="final synthesis",
            directus_service=directus,
            cache_service=cache,
            encryption_service=_Encryption(),
            user_vault_key_id="vault-key",
            task_id="88888888-8888-4888-8888-888888888888",
            log_prefix="test",
            model_name="Gemini 3.7 Flash",
        )
    )

    assert cache.version_increments == []
    assert cache.version_sets == []
    assert cache.events == []
    assert len(cache.ai_messages) == 1
    assert json.loads(cache.ai_messages[0][2])["id"] == request_data.continuation_message_id
    assert "messages_v" not in directus.updates[0]
    assert "last_message_timestamp" not in directus.updates[0]


def test_standardized_server_error_fallback_can_be_sealed_for_recovery(monkeypatch) -> None:
    task_id = "11111111-1111-4111-8111-111111111111"
    request_data = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="hello", created_at=100)],
        recovery_task_id=task_id,
        recovery_preflight_id="55555555-5555-4555-8555-555555555555",
        recovery_turn_id="66666666-6666-4666-8666-666666666666",
        recovery_public_key="public-key",
        chat_key_version=1,
    )
    captured: dict[str, object] = {}

    def fake_build_sealed_recovery_job_data(**kwargs) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "protocol_version": 1,
            "job_id": "77777777-7777-4777-8777-777777777777",
            "sealed_payload": "sealed",
        }

    class FakeChatRecoveryService:
        def __init__(self, directus_service) -> None:
            self.directus_service = directus_service

        async def execute(self, operation: str, data: dict[str, object]) -> dict[str, object]:
            captured["operation"] = operation
            captured["directus_service"] = self.directus_service
            captured["request"] = data
            return {"job_id": data["job_id"]}

    monkeypatch.setattr(
        stream_consumer,
        "build_sealed_recovery_job_data",
        fake_build_sealed_recovery_job_data,
    )
    monkeypatch.setattr(stream_consumer, "ChatRecoveryService", FakeChatRecoveryService)

    directus_service = object()
    result = asyncio.run(
        stream_consumer._persist_sealed_recovery_job(
            directus_service=directus_service,
            request_data=request_data,
            task_id=task_id,
            content=stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE,
            category="general_knowledge",
            model_name="fallback-model",
        )
    )

    assert captured["operation"] == "create_sealed_job"
    assert captured["directus_service"] is directus_service
    assert captured["content"] == stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE
    assert captured["category"] == "general_knowledge"
    assert captured["model_name"] == "fallback-model"
    assert result == {"job_id": "77777777-7777-4777-8777-777777777777"}


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,chats.message.identity-idempotent
def test_sub_chat_parent_continuation_preserves_inference_without_reusing_execution_identity(monkeypatch) -> None:
    original_request = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="research this", created_at=100)],
        active_focus_id="web-research",
        recovery_inference_task_id="11111111-1111-4111-8111-111111111111",
        recovery_preflight_id="55555555-5555-4555-8555-555555555555",
        recovery_turn_id="66666666-6666-4666-8666-666666666666",
        recovery_public_key="public-key",
        chat_key_version=1,
        is_focus_mode_continuation=True,
        parent_id="99999999-9999-4999-8999-999999999999",
        is_sub_chat=True,
        budget_limit=250,
        budget_spent=75,
    )
    captured: dict[str, object] = {}

    def fake_send_task(*, name: str, kwargs: dict, queue: str, task_id: str | None = None):
        captured.update(name=name, kwargs=kwargs, queue=queue, task_id=task_id)
        return SimpleNamespace(id="77777777-7777-4777-8777-777777777777")

    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", fake_send_task)
    cache = SimpleNamespace(set=AsyncMock(return_value=True))

    asyncio.run(
        stream_consumer._dispatch_sub_chat_parent_continuation(
            cache_service=cache,
            pending_context={
                "parent_request_data": original_request.model_dump(mode="json"),
                "skill_config_dict": {},
                "expected_sub_chat_ids": ["child-1"],
                "completed": {"child-1": {
                    "summary": "Sourced child report",
                    "chat_id": "child-1", "parent_id": original_request.chat_id,
                    "owner_hash": original_request.user_id_hash,
                    "root_chat_id": original_request.chat_id,
                    "root_turn_id": original_request.message_id,
                    "orchestration_id": original_request.orchestration_id,
                    "source_refs": ["real.example-a1B"],
                    "source_bindings": {"real.example-a1B": "88888888-8888-4888-8888-888888888888"},
                }},
            },
            parent_chat_id=original_request.chat_id,
            log_prefix="test",
        )
    )

    request_payload = captured["kwargs"]["request_data_dict"]
    assert isinstance(captured["task_id"], str)
    assert captured["task_id"] != original_request.recovery_inference_task_id
    assert cache.set.await_args.args[0] == stream_consumer._sub_chat_source_authority_key(captured["task_id"])
    assert cache.set.await_args.args[1]["refs"] == ["real.example-a1B"]
    assert cache.set.await_args.args[1]["bindings"] == {
        "real.example-a1B": "88888888-8888-4888-8888-888888888888",
    }
    assert "source_refs" not in request_payload
    assert request_payload["recovery_task_id"] is None
    # Continuation is a new execution, but must seal its answer under the
    # original inference so an offline owner can recover the completed turn.
    assert request_payload["recovery_inference_task_id"] == original_request.recovery_inference_task_id
    continuation_request = AskSkillRequest(**request_payload)
    cache.get = AsyncMock(return_value=cache.set.await_args.args[1])
    assert asyncio.run(stream_consumer._load_sub_chat_source_authority(
        cache, captured["task_id"], continuation_request,
    )) == {"real.example-a1B"}
    assert continuation_request.resolved_recovery_inference_task_id() == original_request.recovery_inference_task_id
    assert continuation_request.is_sub_chat_continuation is True
    assert request_payload["continuation_message_id"] is None
    assert request_payload["recovery_preflight_id"] == original_request.recovery_preflight_id
    assert request_payload["recovery_turn_id"] == original_request.recovery_turn_id
    assert request_payload["recovery_public_key"] == original_request.recovery_public_key
    assert request_payload["chat_key_version"] == original_request.chat_key_version
    assert request_payload["parent_id"] == original_request.parent_id
    assert request_payload["is_sub_chat"] is True
    assert request_payload["budget_limit"] == original_request.budget_limit
    assert request_payload["budget_spent"] == original_request.budget_spent


# contract-test: supporting surface=rest_api assertions=chats.rendering.inline-entity-interaction
def test_sub_chat_web_citations_use_only_exact_child_and_task_authority() -> None:
    parent = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="research", created_at=100)],
        active_focus_id="web-research", orchestration_id="orchestration-1",
        is_sub_chat_continuation=True, recovery_consumed_child_ids=["child-1"],
    )
    child_entry = {
        "chat_id": "child-1", "parent_id": parent.chat_id,
        "owner_hash": parent.user_id_hash, "root_chat_id": parent.chat_id,
        "root_turn_id": parent.message_id, "orchestration_id": parent.orchestration_id,
        "source_refs": ["real.example-a1B"], "summary": "[Real](embed:real.example-a1B)",
        "source_bindings": {"real.example-a1B": "88888888-8888-4888-8888-888888888888"},
    }
    pending = {"expected_sub_chat_ids": ["child-1"], "completed": {"child-1": child_entry}}
    assert stream_consumer._verified_sub_chat_source_refs(pending, parent) == ["real.example-a1B"]
    assert stream_consumer._verified_sub_chat_source_bindings(pending, parent) == {
        "real.example-a1B": "88888888-8888-4888-8888-888888888888",
    }
    assert stream_consumer._verified_sub_chat_source_refs(
        {**pending, "completed": {"child-1": {**child_entry, "owner_hash": "b" * 64}}}, parent,
    ) == []
    assert stream_consumer._verified_sub_chat_source_bindings(
        {**pending, "completed": {"child-1": {**child_entry, "owner_hash": "b" * 64}}}, parent,
    ) == {}
    for field, foreign_value in (
        ("root_chat_id", "other-root"),
        ("root_turn_id", "other-turn"),
        ("orchestration_id", "other-orchestration"),
        ("parent_id", "other-parent"),
    ):
        assert stream_consumer._verified_sub_chat_source_refs(
            {**pending, "completed": {"child-1": {**child_entry, field: foreign_value}}}, parent,
        ) == []
        assert stream_consumer._verified_sub_chat_source_bindings(
            {**pending, "completed": {"child-1": {**child_entry, field: foreign_value}}}, parent,
        ) == {}
    task_id = "continuation-task"
    authority = {"task_id": task_id, "owner_hash": parent.user_id_hash,
                 "chat_id": parent.chat_id, "turn_id": parent.message_id,
                 "root_chat_id": parent.chat_id, "root_turn_id": parent.message_id,
                 "orchestration_id": parent.orchestration_id,
                 "child_ids": ["child-1"], "refs": ["real.example-a1B"],
                 "bindings": {"real.example-a1B": "88888888-8888-4888-8888-888888888888"}}
    cache = SimpleNamespace(get=AsyncMock(return_value=authority))
    trusted = asyncio.run(stream_consumer._load_sub_chat_source_authority(cache, task_id, parent))
    assert trusted == {"real.example-a1B"}
    spoofed = parent.model_copy(update={"user_id_hash": "b" * 64})
    assert asyncio.run(stream_consumer._load_sub_chat_source_authority(cache, task_id, spoofed)) is None
    assert asyncio.run(stream_consumer._load_sub_chat_source_authority(cache, "other-task", parent)) is None
    cache.get.return_value = {**authority, "bindings": {"fake.example-c2D": authority["bindings"]["real.example-a1B"]}}
    assert asyncio.run(stream_consumer._load_sub_chat_source_authority(cache, task_id, parent)) is None
    cache.get.return_value = authority
    assert asyncio.run(stream_consumer._load_sub_chat_source_authority(
        cache, task_id, parent.model_copy(update={"root_chat_id": "other-root"}),
    )) is None
    client_spoof = AskSkillRequest.model_validate({
        **parent.model_dump(mode="json"), "source_refs": ["fake.example-c2D"],
    })
    assert "source_refs" not in client_spoof.model_dump(mode="json")

    answer = "[Real](embed:real.example-a1B) and [Made up](embed:fake.example-c2D)."
    result = asyncio.run(stream_consumer._strip_invalid_inline_embed_links(
        aggregated_response=answer, tool_calls_info=None, cache_service=None,
        directus_service=None, encryption_service=None, user_vault_key_id=None,
        known_valid_refs=trusted, require_authority=True,
    ))
    assert result == "[Real](embed:real.example-a1B) and Made up."
    # Ordinary follow-ups without a new Web call or private child authority
    # still leave references to legitimate earlier history untouched.
    assert asyncio.run(stream_consumer._strip_invalid_inline_embed_links(
        aggregated_response=answer, tool_calls_info=None, cache_service=None,
        directus_service=None, encryption_service=None, user_vault_key_id=None,
    )) == answer


# contract-test: supporting surface=rest_api assertions=chats.rendering.inline-entity-interaction
def test_parent_keeps_child_authority_and_own_graph_artifact_before_stripping() -> None:
    parent_id = "11111111-1111-4111-8111-111111111111"
    child_id = "22222222-2222-4222-8222-222222222222"
    current_code_ref = "code-output-yJi"
    nodes = {
        parent_id: SimpleNamespace(decoded={"embed_ids": [child_id]}),
        child_id: SimpleNamespace(decoded={"embed_ref": current_code_ref, "status": "finished"}),
    }

    async def get_node(embed_id):
        return nodes.get(embed_id)

    answer = (
        "[Saved child source](embed:early.example-a1B) and "
        f"[New code artifact](embed:{current_code_ref}) and "
        "[Unsupported source](embed:invented.example-c2D)."
    )
    validated: set[str] = set()
    kwargs = dict(
        aggregated_response=answer,
        tool_calls_info=[{"app_id": "code", "skill_id": "run", "embed_id": parent_id}],
        directus_service=None, user_vault_key_id="owner-vault-key",
        known_valid_refs={"early.example-a1B"}, require_authority=True,
    )
    result = asyncio.run(stream_consumer._strip_invalid_inline_embed_links(
        **kwargs, cache_service=SimpleNamespace(), encryption_service=SimpleNamespace(),
        embed_graph=SimpleNamespace(get=get_node), validated_refs_out=validated,
    ))
    assert result == (
        f"[Saved child source](embed:early.example-a1B) and "
        f"[New code artifact](embed:{current_code_ref}) and Unsupported source."
    )
    assert validated == {"early.example-a1B", current_code_ref}

    # A cache miss cannot turn an unverified citation into a link.
    missing = asyncio.run(stream_consumer._strip_invalid_inline_embed_links(
        **kwargs, cache_service=None, encryption_service=None,
    ))
    assert missing == "[Saved child source](embed:early.example-a1B) and New code artifact and Unsupported source."


# contract-test: supporting surface=rest_api assertions=storage.validation.synthetic-capacity
def test_capacity_parent_continuation_preserves_signed_replay(monkeypatch) -> None:
    from backend.shared.testing.mock_context import (
        activate_mock_mode, deactivate_mock_mode, detect_live_marker,
    )

    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    monkeypatch.setenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "disposable-unit-secret")
    request = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(
            role="user", content="STORAGE_CAPACITY_SCENARIO:child", created_at=100,
        )],
    )
    request.live_mock_mode = "mock"
    request.live_mock_group = "storage_capacity_v1"

    class PendingCache:
        payload = None
        source_authority = None

        async def set(self, key, payload, *, ttl):
            assert ttl == stream_consumer.SUB_CHAT_PENDING_TTL_SECONDS
            if key.startswith(stream_consumer.SUB_CHAT_SOURCE_AUTHORITY_PREFIX):
                self.source_authority = payload
            else:
                self.payload = payload
            return True

    cache = PendingCache()
    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        asyncio.run(stream_consumer._store_sub_chat_pending_context(
            cache_service=cache, parent_request_data=request, parent_task_id="parent-task",
            sub_chats=[{"id": "child-1"}], report_trigger="all",
            skill_config_dict={}, log_prefix="test",
        ))
    finally:
        deactivate_mock_mode()
    assert detect_live_marker(cache.payload["capacity_replay_marker"], request.user_id)

    sent = {}

    def fake_send_task(*, name, kwargs, queue, task_id=None):
        sent.update(name=name, kwargs=kwargs, queue=queue)
        return SimpleNamespace(id="continuation-task")

    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", fake_send_task)
    cache.payload["completed"] = {"child-1": {"summary": "Synthetic child result"}}
    asyncio.run(stream_consumer._dispatch_sub_chat_parent_continuation(
        cache_service=cache, pending_context=cache.payload,
        parent_chat_id=request.chat_id, log_prefix="test",
    ))
    content = sent["kwargs"]["request_data_dict"]["message_history"][-1]["content"]
    assert detect_live_marker(content, request.user_id).group_id == "storage_capacity_v1"

    cache.payload.pop("capacity_replay_marker")
    with pytest.raises(RuntimeError, match="no isolated replay context"):
        asyncio.run(stream_consumer._dispatch_sub_chat_parent_continuation(
            cache_service=cache, pending_context=cache.payload,
            parent_chat_id=request.chat_id, log_prefix="test",
        ))


def test_persist_sealed_recovery_job_skips_continuation_without_recovery_identity(monkeypatch) -> None:
    request_data = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="research this", created_at=100)],
        is_sub_chat_continuation=True,
        recovery_preflight_id="55555555-5555-4555-8555-555555555555",
        recovery_turn_id="66666666-6666-4666-8666-666666666666",
        recovery_public_key="public-key",
        chat_key_version=1,
    )

    def fail_build_sealed_recovery_job_data(*_args, **_kwargs):
        raise AssertionError("continuations without recovery identity must not build sealed jobs")

    class FailChatRecoveryService:
        def __init__(self, _directus_service) -> None:
            raise AssertionError("continuations without recovery identity must not create recovery service")

    monkeypatch.setattr(
        stream_consumer,
        "build_sealed_recovery_job_data",
        fail_build_sealed_recovery_job_data,
    )
    monkeypatch.setattr(stream_consumer, "ChatRecoveryService", FailChatRecoveryService)

    result = asyncio.run(
        stream_consumer._persist_sealed_recovery_job(
            directus_service=object(),
            request_data=request_data,
            task_id="77777777-7777-4777-8777-777777777777",
            content="parent continuation response",
            category="general_knowledge",
            model_name="fallback-model",
        )
    )

    assert result is None


def test_awaiting_nested_sub_chat_does_not_report_provisional_completion() -> None:
    assert stream_consumer._sub_chat_completion_summary(
        explicit_summary="premature report",
        aggregated_response="provisional batch status",
        awaiting_sub_chats_completion=True,
    ) is None
    assert stream_consumer._sub_chat_completion_summary(
        explicit_summary="final child report",
        aggregated_response="fallback response",
        awaiting_sub_chats_completion=False,
    ) == "final child report"
    assert stream_consumer._sub_chat_completion_summary(
        explicit_summary="[Unsupported](embed:invented.example-c2D)",
        aggregated_response="Saved result after source validation.",
        awaiting_sub_chats_completion=False,
        prefer_final_response=True,
    ) == "Saved result after source validation."


def test_sub_chat_completion_is_recorded_before_billing_error_is_reraised() -> None:
    source = inspect.getsource(stream_consumer._consume_main_processing_stream)

    completion_index = source.rindex("await _record_sub_chat_completion_and_maybe_continue_parent(")
    billing_reraise_index = source.rindex("if billing_error:")

    assert completion_index < billing_reraise_index


# contract-test: supporting surface=rest_api assertions=billing.credits.retryable-completion-safe
def test_finalized_response_only_reraises_non_deferred_billing_error() -> None:
    source = inspect.getsource(stream_consumer._consume_main_processing_stream)
    final_marker_index = source.rindex("is_final=True")
    billing_reraise_index = source.rindex("if billing_error:")

    assert final_marker_index < billing_reraise_index
    finalization_block = source[final_marker_index:]
    assert "Retryable conflicts return successfully" in finalization_block
    assert "Re-raising non-deferred billing error" in finalization_block
    assert "raise billing_error" in finalization_block


def test_sub_chat_continuation_failure_marks_original_inference(monkeypatch) -> None:
    request_data = AskSkillRequest(
        chat_id="22222222-2222-4222-8222-222222222222",
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="44444444-4444-4444-8444-444444444444",
        user_id_hash="a" * 64,
        message_history=[AIHistoryMessage(role="user", content="research this", created_at=100)],
        recovery_inference_task_id="11111111-1111-4111-8111-111111111111",
        is_sub_chat_continuation=True,
    )
    captured: dict[str, object] = {}

    class FakeDirectusService:
        async def close(self) -> None:
            return None

    class FakeChatRecoveryService:
        def __init__(self, _directus_service) -> None:
            pass

        async def execute(self, operation: str, data: dict[str, object]) -> dict[str, object]:
            captured.update(operation=operation, data=data)
            return {"failed": True}

    monkeypatch.setattr(ask_skill_task, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", FakeChatRecoveryService)

    asyncio.run(
        ask_skill_task._mark_recovery_inference_failed(
            request_data,
            "88888888-8888-4888-8888-888888888888",
            "runtime_error",
        )
    )

    assert captured["operation"] == "mark_inference_failed"
    assert captured["data"]["inference_task_id"] == request_data.recovery_inference_task_id


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
@pytest.mark.parametrize("marker,reason", [
    ("__awaiting_app_settings_memories_permission__", "permission_required"),
    ("__awaiting_connected_account_permission__", "connected_account_required"),
])
def test_permission_pause_before_debug_metadata_does_not_fail_turn(monkeypatch, marker, reason):
    async def paused_stream(**kwargs):
        yield {marker: True, "request_id": "request-1"}

    monkeypatch.setattr(stream_consumer, "handle_main_processing", paused_stream)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    request = AskSkillRequest(chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1", message_history=[], is_incognito=True)
    result = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request, preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=None, encryption_service=None, user_vault_key_id=None,
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=None,
    ))
    assert result[:4] == ("", False, False, [])
    assert result[4]["user_task_blocked_reason_code"] == reason


# contract-test: supporting surface=cli assertions=app-skills.assistant.same-turn-completion,app-skills.assistant.complete-result-barrier
def test_same_turn_pause_publishes_nonfinal_wait_frame_and_checkpoints_sequence(monkeypatch):
    from backend.apps.ai.tasks import same_turn_skill_barrier
    from backend.shared.python_utils import recent_work_summary_client

    checkpoint = {"jobs": [{"task_id": "producer-1", "tool_call_id": "call-1",
                            "app_id": "images", "skill_id": "generate", "request_count": 1}]}

    async def paused_stream(**_kwargs):
        yield "The image is processing."
        yield {"__same_turn_skill_pause__": True, "checkpoint": checkpoint,
               "batch_id": "batch-1", "task_ids": ["producer-1"]}

    published = []
    sealed = {}

    async def publish(_cache, _channel, payload, *_args):
        published.append(payload)

    async def seal(fields, **_kwargs):
        sealed.update(fields)
        return {"agentic_context_ref": "sealed-private-ref"}

    async def register(_cache, **_kwargs):
        return None

    async def arm(_cache, _batch_id):
        return None

    monkeypatch.setattr(stream_consumer, "handle_main_processing", paused_stream)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", publish)
    monkeypatch.setattr(recent_work_summary_client, "seal_private_context_payload", seal)
    monkeypatch.setattr(same_turn_skill_barrier, "register_barrier", register)
    monkeypatch.setattr(same_turn_skill_barrier, "arm_barrier", arm)
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    request = AskSkillRequest(
        chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="hash-1", message_history=[], is_incognito=True,
    )
    result = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request,
        preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=None, encryption_service=None,
        user_vault_key_id=None, all_mates_configs=[], discovered_apps_metadata={},
        cache_service=SimpleNamespace(),
    ))
    assert result[4]["same_turn_skill_paused"] is True
    assert not any(row["is_final_chunk"] for row in published)
    waiting = [row for row in published if row.get("waiting_for_skill_completion")]
    assert len(waiting) == 1
    assert waiting[0]["full_content_so_far"] == result[0]
    assert waiting[0]["user_message_id"] == "message-1"
    assert waiting[0]["awaiting_async_skill_continuation"] is True
    assert waiting[0]["skill_deadline_at"] > 0
    assert waiting[0]["sequence"] == 2
    from backend.apps.ai.tasks.same_turn_skill_barrier import unpack_private_checkpoint
    _, saved_checkpoint = unpack_private_checkpoint(sealed["same_turn_request"])
    assert saved_checkpoint["published_stream_chunk_count"] == 2
    assert saved_checkpoint["published_stream_content"] == result[0]


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
def test_memory_continuation_seals_under_original_inference_identity():
    request = AskSkillRequest(chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1", message_history=[], is_app_settings_memories_continuation=True, recovery_inference_task_id="original-task-1")
    assert request.resolved_recovery_inference_task_id() == "original-task-1"
    request.is_app_settings_memories_continuation = False
    assert request.resolved_recovery_inference_task_id() is None


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_initial_child_resolves_dispatched_inference_identity_for_assistant_and_summary():
    request = AskSkillRequest(
        chat_id="child-chat-1", message_id="child-prompt-1",
        user_id="user-1", user_id_hash="hash-1", message_history=[],
        is_sub_chat=True, recovery_preflight_id="parent-preflight-1",
        recovery_inference_task_id="stable-child-task-1",
    )
    assert request.resolved_recovery_inference_task_id() == "stable-child-task-1"
    assert stream_consumer._recovery_inference_task_id(request) == "stable-child-task-1"

    request.recovery_preflight_id = None
    assert request.resolved_recovery_inference_task_id() is None
    request.recovery_preflight_id = "parent-preflight-1"
    request.is_sub_chat = False
    assert request.resolved_recovery_inference_task_id() is None


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
@pytest.mark.parametrize("failure_reason", ["provider_exhausted", "anonymous_usage_limit"])
def test_partial_text_followed_by_terminal_failure_is_failed_and_not_billed(monkeypatch, failure_reason):
    from backend.shared.python_utils.chat_failure_notifications import terminal_class

    async def failed_stream(**kwargs):
        yield "A partial answer that must not make the turn look successful."
        yield stream_consumer.MistralUsage(
            prompt_tokens=20,
            completion_tokens=2,
            total_tokens=22,
        )
        yield main_processing_failure(failure_reason)

    billing = AsyncMock(return_value={"total_credits": 22})
    aggregate_log = Mock()
    publish = AsyncMock()
    monkeypatch.setattr(stream_consumer, "handle_main_processing", failed_stream)
    monkeypatch.setattr(stream_consumer, "_handle_normal_billing", billing)
    monkeypatch.setattr(stream_consumer, "log_main_llm_stream_aggregated_output", aggregate_log)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", publish)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    request = AskSkillRequest(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="hash-1",
        message_history=[],
        is_incognito=True,
        is_anonymous=failure_reason == "anonymous_usage_limit",
    )

    result = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request, preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=None, encryption_service=None, user_vault_key_id=None,
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=SimpleNamespace(),
    ))

    assert result[0].startswith("A partial answer that must not make the turn look successful.")
    assert result[0].endswith(stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE)
    assert result[4]["main_processing_failure_reason"] == failure_reason
    billing.assert_not_awaited()
    assert aggregate_log.call_args.kwargs["error_message"] == f"Main processing failed: {failure_reason}."
    final_payloads = [
        call.args[2]
        for call in publish.await_args_list
        if call.args[2].get("is_final_chunk")
    ]
    assert len(final_payloads) == 1
    assert final_payloads[0]["full_content_so_far"] == result[0]
    assert final_payloads[0].get("total_credits") is None
    if failure_reason == "anonymous_usage_limit":
        assert final_payloads[0]["error"] is True
        assert final_payloads[0]["failure_reason"] == "anonymous_usage_limit"
    else:
        assert "failure_reason" not in final_payloads[0]
    assert terminal_class(
        {"main_processing_output": result[0]},
        stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE,
    ) == "failed_during_main"


# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
def test_app_skill_output_followed_by_stream_exception_is_failed_and_not_billed(monkeypatch):
    from backend.shared.python_utils.chat_failure_notifications import terminal_class

    app_skill_reference = (
        '```json\n{"type":"app_skill_use","embed_id":"search-result-1",'
        '"app_id":"web","skill_id":"search"}\n```\n\n'
    )

    async def failed_stream(**kwargs):
        yield app_skill_reference
        yield stream_consumer.MistralUsage(
            prompt_tokens=20,
            completion_tokens=2,
            total_tokens=22,
        )
        raise RuntimeError("upstream stream failed after completed app output")

    billing = AsyncMock(return_value={"total_credits": 22})
    aggregate_log = Mock()
    publish = AsyncMock()
    monkeypatch.setattr(stream_consumer, "handle_main_processing", failed_stream)
    monkeypatch.setattr(stream_consumer, "_handle_normal_billing", billing)
    monkeypatch.setattr(stream_consumer, "log_main_llm_stream_aggregated_output", aggregate_log)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", publish)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    request = AskSkillRequest(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="hash-1",
        message_history=[],
        is_incognito=True,
    )

    result = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request, preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=None, encryption_service=None, user_vault_key_id=None,
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=SimpleNamespace(),
    ))

    assert app_skill_reference.strip() in result[0]
    assert result[0].endswith(stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE)
    assert result[0].count(stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE) == 1
    assert result[4]["main_processing_failure_reason"] == "stream_error"
    billing.assert_not_awaited()
    assert aggregate_log.call_args.kwargs["error_message"] == "Main processing failed: stream_error."
    final_payloads = [
        call.args[2]
        for call in publish.await_args_list
        if call.args[2].get("is_final_chunk")
    ]
    assert len(final_payloads) == 1
    assert final_payloads[0]["full_content_so_far"] == result[0]
    assert final_payloads[0]["full_content_so_far"].endswith(
        stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE
    )
    assert final_payloads[0].get("total_credits") is None
    assert terminal_class(
        {"main_processing_output": result[0]},
        stream_consumer.STANDARDIZED_USER_ERROR_MESSAGE,
    ) == "failed_during_main"


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
def test_normal_text_with_usage_remains_successful_and_billable(monkeypatch):
    async def successful_stream(**kwargs):
        yield "Complete answer."
        yield stream_consumer.MistralUsage(
            prompt_tokens=20,
            completion_tokens=2,
            total_tokens=22,
        )

    billing = AsyncMock(return_value={"total_credits": 22})
    aggregate_log = Mock()
    monkeypatch.setattr(stream_consumer, "handle_main_processing", successful_stream)
    monkeypatch.setattr(stream_consumer, "_handle_normal_billing", billing)
    monkeypatch.setattr(stream_consumer, "log_main_llm_stream_aggregated_output", aggregate_log)
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    request = AskSkillRequest(
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="hash-1",
        message_history=[],
        is_incognito=True,
    )

    result = asyncio.run(stream_consumer._consume_main_processing_stream(
        task_id="task-1", request_data=request, preprocessing_result=PreprocessingResult(can_proceed=True),
        base_instructions={}, directus_service=None, encryption_service=None, user_vault_key_id=None,
        all_mates_configs=[], discovered_apps_metadata={}, cache_service=None,
    ))

    assert result[0] == "Complete answer."
    billing.assert_awaited_once()
    assert aggregate_log.call_args.kwargs["error_message"] is None


# contract-test: direct surface=cli assertions=chat-processing-feedback.turn-lifecycle
@pytest.mark.parametrize("visible_text", [True, False])
def test_sealed_metadata_barrier_waits_after_internal_frames_before_visible_or_terminal(monkeypatch, visible_text):
    """Exercise the actual consumer with a delayed metadata seal and fake provider."""
    events = []
    internal_consumed = asyncio.Event()
    provider_release = asyncio.Event()
    seal_started = asyncio.Event()
    seal_release = asyncio.Event()

    async def processing_stream(**_kwargs):
        yield {"__debug_metadata__": True, "system_prompt_char_count": 0}
        internal_consumed.set()
        await provider_release.wait()
        if visible_text:
            yield "Visible answer."
            yield stream_consumer.MistralUsage(
                prompt_tokens=20, completion_tokens=2, total_tokens=22,
            )

    async def sealed_metadata_notice():
        events.append("seal_started")
        seal_started.set()
        await seal_release.wait()
        events.append("sealed")

    async def publish(_cache, _channel, payload, *_args):
        events.append(("publish", payload))

    monkeypatch.setattr(stream_consumer, "handle_main_processing", processing_stream)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", publish)
    monkeypatch.setattr(stream_consumer, "_handle_normal_billing", AsyncMock(return_value={"total_credits": 22}))
    monkeypatch.setattr(stream_consumer, "log_main_llm_stream_aggregated_output", Mock())
    monkeypatch.setattr(stream_consumer.celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
    request = AskSkillRequest(
        chat_id="chat-1", message_id="message-1", user_id="user-1", user_id_hash="hash-1",
        message_history=[], is_incognito=True,
    )

    async def check():
        consumer = asyncio.create_task(stream_consumer._consume_main_processing_stream(
            task_id="task-1", request_data=request,
            preprocessing_result=PreprocessingResult(can_proceed=True),
            base_instructions={}, directus_service=None, encryption_service=None,
            user_vault_key_id=None, all_mates_configs=[], discovered_apps_metadata={},
            cache_service=SimpleNamespace(), before_first_chunk_publish=sealed_metadata_notice,
        ))
        await asyncio.wait_for(internal_consumed.wait(), 1)
        assert not seal_started.is_set(), "internal setup frames must leave metadata/provider overlap open"
        provider_release.set()
        await asyncio.wait_for(seal_started.wait(), 1)
        assert not consumer.done()
        assert not any(isinstance(event, tuple) and event[0] == "publish" for event in events)
        seal_release.set()
        result = await asyncio.wait_for(consumer, 2)
        assert events.count("sealed") == 1
        first_publish = next(i for i, event in enumerate(events) if isinstance(event, tuple) and event[0] == "publish")
        assert events.index("sealed") < first_publish
        if visible_text:
            assert result[0] == "Visible answer."
        else:
            assert result[0], "zero-chunk path must publish its terminal fallback after the seal"

    asyncio.run(check())


def _verifier_test_context():
    request = AskSkillRequest(chat_id="11111111-1111-4111-8111-111111111111",
        message_id="22222222-2222-4222-8222-222222222222", user_id="user", user_id_hash="owner",
        message_history=[AIHistoryMessage(role="user", content="Compare competing explanations", created_at=100)],
        orchestration_id="33333333-3333-4333-8333-333333333333",
        root_chat_id="11111111-1111-4111-8111-111111111111",
        root_turn_id="22222222-2222-4222-8222-222222222222", active_focus_id="web-research")
    context = {"parent_request_data": request.model_dump(mode="json"), "parent_task_id": "parent-task",
        "expected_sub_chat_ids": ["research-child"], "completed": {"research-child": {
            "summary": "Provisional allegation: https://agency.example/complaint. Period 2021-2023.",
            "chat_id": "research-child", "parent_id": request.chat_id, "owner_hash": request.user_id_hash,
            "root_chat_id": request.root_chat_id, "root_turn_id": request.root_turn_id,
            "orchestration_id": request.orchestration_id}}}
    return request, context


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_prompt_contains_primary_urls_not_final_instruction():
    request, context = _verifier_test_context()
    assert stream_consumer._successful_research_reports(context, request)
    context["completed"]["research-child"]["owner_hash"] = "wrong-owner"
    assert not stream_consumer._successful_research_reports(context, request)
    context["completed"]["research-child"]["owner_hash"] = request.user_id_hash
    prompt = stream_consumer._research_verifier_prompt(context)
    assert "https://agency.example/complaint" in prompt
    assert "web-search and web-read" in prompt
    assert "court-approved" in prompt and "period" in prompt
    assert "FINAL ANSWER TASK" not in prompt and "Return the final answer only" not in prompt
    context["completed"]["research-child"]["failed"] = True
    assert not stream_consumer._successful_research_reports(context)


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_dispatch_stages_context_before_paid_work(monkeypatch):
    request, context = _verifier_test_context()
    claim = {"research_stage": "verification_due", "root_chat_id": request.chat_id, "root_turn_id": request.root_turn_id, "verifier_child_id": "verifier-child",
        "verifier_batch_id": "verifier-batch", "batch_id": "initial-batch", "continuation_task_id": "claim-task"}
    order = []
    stored = {}
    async def prepare(**kwargs):
        order.append("durable")
        assert kwargs["verification_claim"] is claim
        assert kwargs["spawned_sub_chats"][0]["id"] == "verifier-child"
        return {"verifier-child": "signed-token"}
    async def set_context(key, value, **kwargs):
        stored[key] = value
        order.append("private-context")
        return True
    async def dispatch(**kwargs):
        order.append("dispatch")
        assert order[:2] == ["durable", "private-context"]
        assert kwargs["dispatch_token"] == "signed-token"
        return "stable-task"
    monkeypatch.setattr(stream_consumer, "create_sub_chat_records", prepare)
    monkeypatch.setattr(stream_consumer, "dispatch_sub_chat_task", dispatch)
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", AsyncMock())
    cache = SimpleNamespace(get=AsyncMock(return_value=None), set=set_context, set_active_ai_task=AsyncMock())
    asyncio.run(stream_consumer._dispatch_research_verifier(cache_service=cache, directus_service=object(),
        original_request=request, pending_context=context, claim=claim, log_prefix="[test]"))
    pending = stored[stream_consumer._sub_chat_pending_key(request.chat_id)]
    assert pending["research_context"] is context
    assert pending["expected_sub_chat_ids"] == ["verifier-child"]
    # A retry after the child already started must reuse paid work.
    claim["research_stage"] = "verification_running"
    claim["verifier_child_state"] = "running"
    cache.get = AsyncMock(return_value=pending)
    asyncio.run(stream_consumer._dispatch_research_verifier(cache_service=cache, directus_service=object(),
        original_request=request, pending_context=context, claim=claim, log_prefix="[test]"))
    assert order.count("dispatch") == 1


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_claim_dispatches_child_without_parent_inference(monkeypatch):
    request, context = _verifier_test_context()
    claim = {"research_stage": "verification_due", "root_chat_id": request.chat_id, "root_turn_id": request.root_turn_id, "dispatch_required": True, "continuation_task_id": "claim-task"}
    service = SimpleNamespace(execute=AsyncMock(return_value=claim))
    directus = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: directus)
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", lambda _: service)
    verifier = AsyncMock()
    monkeypatch.setattr(stream_consumer, "_dispatch_research_verifier", verifier)
    parent_dispatch = Mock(side_effect=AssertionError("No parent inference before verifier report"))
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", parent_dispatch)
    dispatched = asyncio.run(stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=object(),
        pending_context=context, parent_chat_id=request.chat_id, durable_batch_id="initial-batch", log_prefix="[test]"))
    assert dispatched is False
    verifier.assert_awaited_once()
    assert [call.args[0] for call in service.execute.await_args_list] == ["claim_parent_continuation", "mark_parent_continuation_dispatched"]


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_failure_is_honest_and_synthesis_qualifies_claims():
    _, context = _verifier_test_context()
    context["research_stage"] = "failed"
    prompt = stream_consumer._build_sub_chat_completion_context(context)
    assert "did not complete successfully" in prompt
    assert "never claim completed verification" in prompt
    context["research_stage"] = "synthesis"
    prompt = stream_consumer._build_sub_chat_completion_context(context)
    assert "Check the three research reports against primary sources yourself" in prompt
    assert "Only present claims as confirmed where the sources directly support" in prompt
    assert "independent verifier report below" not in prompt
    context["research_context"] = {"expected_sub_chat_ids": [], "completed": {}}
    prompt = stream_consumer._build_sub_chat_completion_context(context)
    assert "Only treat claims as confirmed where the verifier directly supports" in prompt
    assert "Short Answer and Bottom Line" in prompt
    assert "proposed settlement is not a court-approved judgment" in prompt


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_duplicate_initial_claim_retains_pending_context(monkeypatch):
    request, context = _verifier_test_context()
    service = SimpleNamespace(execute=AsyncMock(return_value={"research_stage": "verification_running", "root_chat_id": request.chat_id, "root_turn_id": request.root_turn_id,
        "dispatch_required": False, "research_batch_id": "initial-batch"}))
    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", lambda _: service)
    assert asyncio.run(stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=object(),
        pending_context=context, parent_chat_id=request.chat_id, durable_batch_id="initial-batch", log_prefix="[test]")) is False


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_dispatch_failure_yields_qualified_terminal_answer(monkeypatch):
    request, context = _verifier_test_context()
    service = SimpleNamespace(execute=AsyncMock(return_value={"research_stage": "verification_due", "root_chat_id": request.chat_id, "root_turn_id": request.root_turn_id,
        "dispatch_required": True, "continuation_task_id": "claim-task"}))
    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", lambda _: service)
    monkeypatch.setattr(stream_consumer, "_dispatch_research_verifier", AsyncMock(side_effect=RuntimeError("budget unavailable")))
    sent = []
    def send(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(id=kwargs["task_id"])
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", send)
    cache = SimpleNamespace(set=AsyncMock(return_value=True))
    assert asyncio.run(stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=cache,
        pending_context=context, parent_chat_id=request.chat_id, durable_batch_id="initial-batch", log_prefix="[test]")) is True
    payload = sent[0]["kwargs"]["request_data_dict"]
    assert payload["is_sub_chat_continuation"] is True
    assert "verification did not complete successfully" in payload["message_history"][-1]["content"]
    assert [call.args[0] for call in service.execute.await_args_list] == [
        "claim_parent_continuation", "fail_research_verification", "mark_parent_continuation_dispatched"]


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_ack_failure_preserves_running_work(monkeypatch):
    request, context = _verifier_test_context()
    async def execute(operation, payload):
        if operation == "claim_parent_continuation":
            return {"research_stage": "verification_due", "root_chat_id": request.chat_id, "root_turn_id": request.root_turn_id, "dispatch_required": True, "continuation_task_id": "claim-task"}
        assert operation == "mark_parent_continuation_dispatched"
        raise RuntimeError("ack unavailable")
    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", lambda _: SimpleNamespace(execute=execute))
    monkeypatch.setattr(stream_consumer, "_dispatch_research_verifier", AsyncMock())
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", Mock(side_effect=AssertionError("Premature final")))
    assert asyncio.run(stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=object(),
        pending_context=context, parent_chat_id=request.chat_id, durable_batch_id="initial-batch", log_prefix="[test]")) is False


class _AtomicPendingCache:
    """Existing fakeredis[lua] executes the actual production CAS script in memory."""
    def __init__(self, initial=None):
        import fakeredis.aioredis
        self.redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        self.initial = initial or {}
        self.ready = False
        self.read_paused, self.resume_read = asyncio.Event(), asyncio.Event()
        self.pause_task = self.pause_key = None

    @property
    async def client(self):
        if not self.ready:
            if self.initial:
                await self.redis.mset({key: json.dumps(value) for key, value in self.initial.items()})
            self.ready = True
        return self.redis

    async def get(self, key):
        raw = await (await self.client).get(key)
        value = json.loads(raw) if raw is not None else None
        task = asyncio.current_task()
        if task and task.get_name() == self.pause_task and key == self.pause_key:
            self.read_paused.set()
            await asyncio.wait_for(self.resume_read.wait(), timeout=3)
        return value

    async def set(self, key, value, **kwargs):
        return bool(await (await self.client).setex(key,
            kwargs.get("ttl", stream_consumer.SUB_CHAT_PENDING_TTL_SECONDS), json.dumps(value)))

    async def delete(self, key):
        return bool(await (await self.client).delete(key))

    async def set_active_ai_task(self, *_args):
        return True


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_research_verifier_pending_cas_merges_siblings_and_fences_stale_delete():
    async def run():
        key = "pending"
        cache = _AtomicPendingCache({key: {"pending_batch_id": "research", "completed": {}}})
        a, b = await cache.get(key), await cache.get(key)
        a["completed"], b["completed"] = {"a": {"summary": "A"}}, {"b": {"summary": "B"}}
        assert await stream_consumer._mutate_sub_chat_pending_context(cache, key, a)
        assert await stream_consumer._mutate_sub_chat_pending_context(cache, key, b)
        assert set(b["completed"]) == {"a", "b"}
        verifier = {"pending_batch_id": "verifier", "completed": {}}
        assert await stream_consumer._mutate_sub_chat_pending_context(cache, key, b, action="replace", replacement=verifier)
        assert not await stream_consumer._mutate_sub_chat_pending_context(cache, key, a)
        assert not await stream_consumer._mutate_sub_chat_pending_context(cache, key, a, action="delete")
        verifier["completed"]["verifier-child"] = {"summary": "Verified"}
        assert await stream_consumer._mutate_sub_chat_pending_context(cache, key, verifier)
        replay = {"pending_batch_id": "verifier", "completed": {}}
        assert await stream_consumer._mutate_sub_chat_pending_context(cache, key, b, action="replace", replacement=replay)
        assert replay["completed"]["verifier-child"]["summary"] == "Verified"
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_research_verifier_delayed_initial_callback_cannot_clobber_verifier_or_duplicate_synthesis(monkeypatch):
    async def run():
        request, initial = _verifier_test_context()
        children = ["angle-a", "angle-b", "angle-c"]
        initial.update(pending_batch_id="research-batch", expected_sub_chat_ids=children, completed={})
        key = stream_consumer._sub_chat_pending_key(request.chat_id)
        cache = _AtomicPendingCache({key: initial})
        for child in children:
            await cache.set(f"sub_chat_completion:{request.chat_id}:{child}", {
                "summary": f"Evidence for {child}: https://primary.example/{child}",
                "chat_id": child, "parent_id": request.chat_id, "owner_hash": request.user_id_hash,
                "root_chat_id": request.root_chat_id, "root_turn_id": request.root_turn_id,
                "orchestration_id": request.orchestration_id})
        cache.pause_task, cache.pause_key = "stale-angle-a", key
        claims = {"research_ack": False, "synthesis_ack": False}
        binding = {"root_chat_id": request.chat_id, "root_turn_id": request.root_turn_id}
        async def execute(operation, payload):
            if operation == "transition_child":
                return {"batch_complete": True, "batch_id": "verifier-batch" if payload["child_chat_id"] == "verifier-child" else "research-batch"}
            if operation == "claim_parent_continuation":
                if payload["batch_id"] == "research-batch":
                    return {**binding, "research_stage": "verification_due", "dispatch_required": not claims["research_ack"],
                        "batch_id": "research-batch", "research_batch_id": "research-batch", "continuation_task_id": "verification-claim",
                        "verifier_batch_id": "verifier-batch", "verifier_child_id": "verifier-child"}
                return {**binding, "research_stage": "synthesis", "dispatch_required": not claims["synthesis_ack"],
                    "batch_id": "verifier-batch", "research_batch_id": "research-batch", "continuation_task_id": "synthesis-task"}
            assert operation == "mark_parent_continuation_dispatched"
            claims["research_ack" if payload["batch_id"] == "research-batch" else "synthesis_ack"] = True
            return {}
        monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
        monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", lambda _: SimpleNamespace(execute=execute))
        monkeypatch.setattr(stream_consumer, "_publish_to_redis", AsyncMock())
        async def prepare(**kwargs):
            return {"verifier-child": "dispatch-token"}
        prompts, synthesis = [], []
        async def child_dispatch(**kwargs):
            prompts.append(kwargs["sub_chat"]["prompt"])
            return "stable-verifier-task"
        monkeypatch.setattr(stream_consumer, "create_sub_chat_records", prepare)
        monkeypatch.setattr(stream_consumer, "dispatch_sub_chat_task", child_dispatch)
        def send(**kwargs):
            synthesis.append(kwargs)
            return SimpleNamespace(id=kwargs["task_id"])
        monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", send)
        async def complete(child):
            child_request = request.model_copy(update={"chat_id": child, "parent_id": request.chat_id,
                "is_sub_chat": True, "sub_chat_depth": 1})
            await stream_consumer._record_sub_chat_completion_and_maybe_continue_parent(
                cache_service=cache, request_data=child_request, task_id=f"task-{child}",
                summary=f"Evidence for {child}: https://primary.example/{child}", log_prefix="[race]")
        stale = asyncio.create_task(complete("angle-a"), name="stale-angle-a")
        await asyncio.wait_for(cache.read_paused.wait(), timeout=3)
        await complete("angle-b")
        assert (await cache.get(key))["pending_batch_id"] == "verifier-batch"
        cache.resume_read.set()
        await asyncio.wait_for(stale, timeout=3)
        assert (await cache.get(key))["expected_sub_chat_ids"] == ["verifier-child"]
        assert len(prompts) == 1 and all(f"https://primary.example/{child}" in prompts[0] for child in children)
        assert not synthesis
        await complete("verifier-child")
        await complete("verifier-child")
        assert len(synthesis) == 1
        payload = synthesis[0]["kwargs"]["request_data_dict"]
        assert set(payload["recovery_consumed_child_ids"]) == {*children, "verifier-child"}
        assert "independent verifier report" in payload["message_history"][-1]["content"]
        assert await cache.get(key) is None
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_research_verifier_pending_cas_retries_conflict_without_losing_reports(monkeypatch):
    async def run():
        key = "pending"
        cache = _AtomicPendingCache({key: {"pending_batch_id": "research", "completed": {}, "user_preferences": {}}})
        a, b = await cache.get(key), await cache.get(key)
        a["completed"], b["completed"] = {"a": {"summary": "A"}}, {"b": {"summary": "B"}}
        read, resume = asyncio.Event(), asyncio.Event()
        original_get, original_eval = cache.redis.get, cache.redis.eval
        paused, eval_calls = False, 0
        async def gated_get(*args, **kwargs):
            nonlocal paused
            raw = await original_get(*args, **kwargs)
            if asyncio.current_task().get_name() == "cas-a" and not paused:
                paused = True
                read.set()
                await asyncio.wait_for(resume.wait(), timeout=3)
            return raw
        async def counted_eval(*args):
            nonlocal eval_calls
            eval_calls += 1
            return await original_eval(*args)
        monkeypatch.setattr(cache.redis, "get", gated_get)
        monkeypatch.setattr(cache.redis, "eval", counted_eval)
        task = asyncio.create_task(stream_consumer._mutate_sub_chat_pending_context(cache, key, a), name="cas-a")
        await asyncio.wait_for(read.wait(), timeout=3)
        assert await stream_consumer._mutate_sub_chat_pending_context(cache, key, b)
        resume.set()
        assert await asyncio.wait_for(task, timeout=3)
        state = await cache.get(key)
        assert set(state["completed"]) == {"a", "b"}
        assert state["user_preferences"] == {}
        assert eval_calls == 3  # B succeeds, A conflicts, A merges and succeeds.
        monkeypatch.setattr(cache.redis, "eval", AsyncMock(return_value=0))
        with pytest.raises(RuntimeError, match="bounded CAS contention"):
            await stream_consumer._mutate_sub_chat_pending_context(cache, key, a)
        assert cache.redis.eval.await_count == stream_consumer.SUB_CHAT_PENDING_CAS_MAX_ATTEMPTS
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_research_verifier_embed_only_three_reports_resolve_scoped_urls_and_exclude_wrong_scope(monkeypatch):
    import hashlib
    import uuid
    monkeypatch.setattr("toon_format.decode", json.loads)
    async def run():
        request, context = _verifier_test_context()
        context["expected_sub_chat_ids"] = [f"child-{n}" for n in range(3)]
        context["completed"] = {}
        metadata, decrypted, fallback_queries = {}, [], []
        fallback = {}
        async def cached(embed_id):
            return metadata.get(embed_id)
        async def read(collection, *, params, no_cache):
            assert collection == "embeds" and no_cache is True
            fallback_queries.append(params)
            row = fallback.get(params["filter[embed_id][_eq]"])
            return [{field: row[field] for field in params["fields"].split(",") if field in row}] if row else []
        async def decrypt(ciphertext, vault_key):
            assert vault_key == "owner-vault"
            decrypted.append(ciphertext)
            return ciphertext
        cache = SimpleNamespace(get_embed_from_cache=cached)
        directus = SimpleNamespace(get_items=read)
        encryption = SimpleNamespace(decrypt_with_user_key=decrypt)
        good_urls, excluded_urls = [], []
        for n, child in enumerate(context["expected_sub_chat_ids"]):
            child_request = request.model_copy(update={"chat_id": child, "message_id": f"child-turn-{n}",
                "parent_id": request.chat_id, "is_sub_chat": True, "sub_chat_depth": 1})
            ref, embed_id = f"primary.example-r{n}", str(uuid.UUID(int=n + 1, version=4))
            url = f"https://primary.example.org/documents/{n}"
            good_urls.append(url)
            # Actual cached child_embed_data uses website, without app_id/skill_id.
            content = json.dumps({"embed_ref": ref, "app_id": "web", "skill_id": "search", "url": url})
            # Field names mirror EmbedService's child_embed_data constructor; its
            # encrypted_content is a Vault working copy despite encryption_mode=client.
            row = {"embed_id": embed_id, "type": "website", "chat_id": child,
                "message_id": child_request.message_id,
                "hashed_chat_id": hashlib.sha256(child.encode()).hexdigest(),
                "hashed_message_id": hashlib.sha256(child_request.message_id.encode()).hexdigest(),
                "hashed_task_id": hashlib.sha256(f"skill-task-{n}".encode()).hexdigest(),
                "status": "finished", "hashed_user_id": request.user_id_hash,
                "is_private": False, "is_shared": False, "encryption_mode": "client",
                "parent_embed_id": str(uuid.UUID(int=n + 30, version=4)),
                "text_length_chars": len(content), "created_at": 100, "updated_at": 100,
                "encrypted_content": content}
            assert "app_id" not in row and "skill_id" not in row
            metadata[embed_id] = row
            bindings = {ref: embed_id}
            summary = f"Claim {n}: [Primary document](embed:{ref}); [[wiki:unresolved{n}]]."
            if n == 0:
                missing_id = str(uuid.UUID(int=20, version=4))
                # Actual durable body is client-key ciphertext; metadata fallback is
                # scoped, but must never be treated as a Vault-decryptable copy.
                fallback[missing_id] = {key: value for key, value in row.items() if key != "type"} | {
                    "embed_id": missing_id, "app_id": "web", "encrypted_content": "client-key-ciphertext"}
                bindings["db-miss.example-m0"] = missing_id
                summary += " [Expired working copy](embed:db-miss.example-m0)"
                for index, changes in enumerate([{"hashed_user_id": "another-owner"},
                        {"hashed_message_id": "another-turn"}, {"type": "email"}, {"app_id": "finance"}]):
                    bad_ref = f"excluded.example-b{index}"
                    bad_id = str(uuid.UUID(int=index + 10, version=4))
                    bad_url = f"https://excluded.example.org/private/{index}"
                    excluded_urls.append(bad_url)
                    metadata[bad_id] = {**row, **changes, "embed_id": bad_id,
                        "encrypted_content": json.dumps({"embed_ref": bad_ref, "app_id": "web", "skill_id": "search", "url": bad_url})}
                    bindings[bad_ref] = bad_id
                    summary += f" [Unresolved](embed:{bad_ref})"
            urls = await stream_consumer._scoped_child_source_urls(
                request_data=child_request, source_bindings=bindings, cache_service=cache,
                directus_service=directus, encryption_service=encryption,
                user_vault_key_id="owner-vault", log_prefix="[source-url-test]")
            assert urls == {ref: url}
            context["completed"][child] = {"summary": summary, "chat_id": child,
                "parent_id": request.chat_id, "owner_hash": request.user_id_hash,
                "root_chat_id": request.root_chat_id, "root_turn_id": request.root_turn_id,
                "orchestration_id": request.orchestration_id,
                "source_refs": list(bindings), "source_bindings": bindings, "source_urls": urls}
        assert all("http" not in entry["summary"] for entry in context["completed"].values())
        prompt = stream_consumer._research_verifier_prompt(context)
        assert all(f"Claim {n}:" in prompt for n in range(3))
        assert all(url in prompt for url in good_urls)
        assert all(url not in prompt for url in excluded_urls)
        assert all(f"excluded.example-b{n}: UNRESOLVED" in prompt for n in range(4))
        assert all(f"unresolved{n}: UNRESOLVED" in prompt for n in range(3))
        assert "db-miss.example-m0: UNRESOLVED" in prompt
        assert "run your own primary-source search" in prompt
        assert len(decrypted) == 3
        assert len(fallback_queries) == 1
        params = fallback_queries[0]
        assert params["filter[hashed_user_id][_eq]"] == request.user_id_hash
        assert params["filter[hashed_chat_id][_eq]"] == hashlib.sha256(b"child-0").hexdigest()
        assert params["filter[hashed_message_id][_eq]"] == hashlib.sha256(b"child-turn-0").hexdigest()
        assert "encrypted_content" not in params["fields"]
        assert stream_consumer._research_source_url("http://127.0.0.1/private") is None
        assert stream_consumer._research_source_url("file:///private") is None
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
@pytest.mark.parametrize("failed", [False, True])
def test_deep_research_three_reports_resume_parent_once_without_verifier(monkeypatch, failed):
    request, context = _verifier_test_context()
    template = context["completed"]["research-child"]
    children = ["research-a", "research-b", "research-c"]
    context["expected_sub_chat_ids"] = children
    context["completed"] = {child: {**template, "chat_id": child} for child in children}
    if failed:
        context["completed"][children[-1]]["failed"] = True
    acknowledged = False

    async def execute(operation, payload):
        nonlocal acknowledged
        if operation == "claim_parent_continuation":
            return {"research_stage": "failed" if failed else "synthesis", "root_chat_id": request.chat_id,
                "root_turn_id": request.root_turn_id, "research_batch_id": "initial-batch", "verifier_batch_id": None,
                "dispatch_required": not acknowledged, "continuation_task_id": "parent-synthesis-task"}
        assert operation == "mark_parent_continuation_dispatched"
        assert payload["batch_id"] == "initial-batch"
        acknowledged = True
        return {}

    service = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", lambda _: service)
    verifier = AsyncMock(side_effect=AssertionError("New research must use the existing parent for source checks"))
    monkeypatch.setattr(stream_consumer, "_dispatch_research_verifier", verifier)
    sent = []
    def send(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(id=kwargs["task_id"])
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", send)
    cache = SimpleNamespace(set=AsyncMock(return_value=True))

    async def complete_twice():
        for _ in range(2):
            assert await stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=cache,
                pending_context=context, parent_chat_id=request.chat_id, durable_batch_id="initial-batch", log_prefix="[test]")
    asyncio.run(complete_twice())
    verifier.assert_not_awaited()
    assert len(sent) == 1
    assert sent[0]["task_id"] == "parent-synthesis-task"
    payload = sent[0]["kwargs"]["request_data_dict"]
    assert payload["active_focus_id"] == "web-research"
    assert payload["is_sub_chat_continuation"] is True
    expected_consumed = children[:-1] if failed else children
    assert payload["recovery_consumed_child_ids"] == expected_consumed
    authority = cache.set.await_args.args[1]
    assert authority["consumption_task_ids"] == {child: "parent-synthesis-task" for child in expected_consumed}
    prompt = payload["message_history"][-1]["content"]
    if failed:
        assert "did not complete successfully" in prompt
        assert "never claim completed verification" in prompt
        assert context["research_stage"] == "failed"
    else:
        assert "primary sources yourself" in prompt
        assert "independent verifier report below" not in prompt


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,app-skills.execution.registered-validated
@pytest.mark.parametrize("invalid", [None, "owner_hash", "root_turn_id", "failed", "cancelled"])
def test_parent_synthesis_source_inventory_uses_only_scoped_successful_child_urls(invalid):
    request, context = _verifier_test_context()
    context["research_stage"] = "synthesis"
    entry = context["completed"]["research-child"]
    entry.update(source_refs=["primary"], source_bindings={"primary": "44444444-4444-4444-8444-444444444444"},
        source_urls={"primary": "https://agency.example/primary", "unbound": "https://excluded.example/other"})
    if invalid:
        entry[invalid] = True if invalid in {"failed", "cancelled"} else "wrong-scope"
    prompt = stream_consumer._build_sub_chat_completion_context(context)
    assert ("https://agency.example/primary" in prompt) == (invalid is None)
    assert "https://excluded.example/other" not in prompt
    if invalid is None:
        assert "locations only, not proof" in prompt
        assert "If reading fails, state the limitation" in prompt


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.parametrize("is_child", [False, True])
@pytest.mark.parametrize("with_thinking", [False, True])
def test_recovery_assistant_thinking_is_owner_sealed(monkeypatch, is_child, with_thinking):
    from backend.shared.python_utils.chat_completion_recovery import (
        derive_recovery_keypair, open_recovery_envelope, open_recovery_output,
    )

    root_id = "22222222-2222-4222-8222-222222222222"
    task_id = "66666666-6666-4666-8666-666666666666"
    private_key, public_key = derive_recovery_keypair(
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", root_id, 7,
    )
    request = AskSkillRequest(
        chat_id="99999999-9999-4999-8999-999999999999" if is_child else root_id,
        root_chat_id=root_id, is_sub_chat=is_child,
        message_id="33333333-3333-4333-8333-333333333333",
        user_id="11111111-1111-4111-8111-111111111111", user_id_hash="a" * 64,
        message_history=[], recovery_task_id=task_id,
        recovery_preflight_id="77777777-7777-4777-8777-777777777777",
        recovery_turn_id="33333333-3333-4333-8333-333333333333",
        recovery_public_key=public_key, chat_key_version=7,
    )
    captured = {}

    class RecoveryService:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, data):
            assert operation == "create_sealed_job"
            captured.update(data)
            return {"job_id": data["job_id"]}

        async def save_sealed_output(self, data, **_kwargs):
            captured.update(data)
            return {"record_id": data["record_id"]}

    monkeypatch.setattr(stream_consumer, "ChatRecoveryService", RecoveryService)
    fields = {
        "thinking_content": "Private reasoning — exact text\n",
        "thinking_signature": "private-signature",
        "thinking_token_count": 0,
        "thinking_duration_seconds": 0.0,
    } if with_thinking else {}
    asyncio.run(stream_consumer._persist_sealed_recovery_job(
        directus_service=object(), request_data=request, task_id=task_id,
        content="Answer", category="general_knowledge", model_name="model-a",
        cache_service=SimpleNamespace(mark_ai_context_pending_persistence=AsyncMock(return_value=True)),
        **fields,
    ))
    assert "Private reasoning" not in json.dumps(captured)
    assert "private-signature" not in json.dumps(captured)
    envelope = json.loads(captured["sealed_payload"])
    common = dict(recovery_private_key=private_key, owner_id=request.user_id,
                  turn_id=request.recovery_turn_id, key_version=7)
    if is_child:
        payload = json.loads(open_recovery_output(
            envelope, **common, root_chat_id=root_id, target_chat_id=request.chat_id,
            record_id=captured["record_id"], subject_id=captured["subject_id"],
            output_kind="message", output_version=captured["output_version"],
        ))["content"]
        assert payload["role"] == "assistant"
    else:
        payload = json.loads(open_recovery_envelope(
            envelope, **common, chat_id=root_id, job_id=captured["job_id"],
            assistant_message_id=task_id,
        ))
    assert payload["content"] == "Answer"
    assert payload["model_name"] == "model-a"
    if with_thinking:
        assert {name: payload[name] for name in fields} == fields
        assert payload["has_thinking"] is True
    else:
        assert not any(name.startswith("thinking_") or name == "has_thinking" for name in payload)
