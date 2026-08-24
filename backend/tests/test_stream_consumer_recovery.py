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
import json
import sys
import types
from types import SimpleNamespace

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
        provider_stub = types.ModuleType(module_name)
        for attr_name, attr_value in attributes.items():
            setattr(provider_stub, attr_name, attr_value)
        sys.modules[module_name] = provider_stub

try:
    from backend.apps.ai.processing.preprocessor import PreprocessingResult
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.apps.ai.tasks import stream_consumer
    from backend.apps.ai.tasks import ask_skill_task
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


def test_harmful_fake_stream_includes_recovery_job_before_final_marker(monkeypatch) -> None:
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

    async def fake_charge(*_args, **_kwargs) -> dict:
        return {"prompt_tokens": 0, "completion_tokens": 4, "total_credits": 1}

    async def fake_persist(**kwargs) -> dict:
        assert kwargs["task_id"] == task_id
        assert kwargs["content"] == "I can't help with that request."
        assert kwargs["category"] == "general_knowledge"
        return {"job_id": "77777777-7777-4777-8777-777777777777"}

    async def fake_update_metadata(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(stream_consumer, "_charge_credits", fake_charge)
    monkeypatch.setattr(stream_consumer, "_persist_sealed_recovery_job", fake_persist)
    monkeypatch.setattr(stream_consumer, "_update_chat_metadata", fake_update_metadata)
    monkeypatch.setattr(
        stream_consumer.celery_config.app,
        "AsyncResult",
        lambda _task_id: SimpleNamespace(state="PENDING"),
    )

    asyncio.run(
        stream_consumer._generate_fake_stream_for_harmful_content(
            task_id=task_id,
            request_data=request_data,
            preprocessing_result=preprocessing_result,
            predefined_response="I can't help with that request.",
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
    assert directus.updates == [{
        "last_edited_overall_timestamp": 1234,
        "last_mate_category": "software_development",
        "updated_at": directus.updates[0]["updated_at"],
    }]
    assert "messages_v" not in directus.updates[0]
    assert "last_message_timestamp" not in directus.updates[0]


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


def test_sub_chat_parent_continuation_does_not_inherit_recovery_identity(monkeypatch) -> None:
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

    asyncio.run(
        stream_consumer._dispatch_sub_chat_parent_continuation(
            pending_context={
                "parent_request_data": original_request.model_dump(mode="json"),
                "skill_config_dict": {},
                "expected_sub_chat_ids": ["child-1"],
                "completed": {"child-1": {"summary": "Sourced child report"}},
            },
            parent_chat_id=original_request.chat_id,
            log_prefix="test",
        )
    )

    request_payload = captured["kwargs"]["request_data_dict"]
    assert captured["task_id"] is None
    assert request_payload["recovery_task_id"] is None
    assert request_payload["recovery_inference_task_id"] is None
    assert request_payload["continuation_message_id"] is None
    assert request_payload["recovery_preflight_id"] == original_request.recovery_preflight_id
    assert request_payload["recovery_turn_id"] == original_request.recovery_turn_id
    assert request_payload["recovery_public_key"] == original_request.recovery_public_key
    assert request_payload["chat_key_version"] == original_request.chat_key_version
    assert request_payload["parent_id"] == original_request.parent_id
    assert request_payload["is_sub_chat"] is True
    assert request_payload["budget_limit"] == original_request.budget_limit
    assert request_payload["budget_spent"] == original_request.budget_spent


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
