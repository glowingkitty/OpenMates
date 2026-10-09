# contract-test-file: infrastructure
"""Automatic summary admission, provider usage, and durable settlement bridge."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import hashlib

import httpx
import pytest

from backend.apps.ai.processing import chat_compressor, summary_billing
from backend.apps.ai.llm_providers import cerebras_client
from backend.apps.ai.tasks import ask_skill_task


pytestmark = pytest.mark.asyncio


def _request(*, team_id=None):
    user_id = "11111111-1111-4111-8111-111111111111"
    return SimpleNamespace(
        is_anonymous=False, orchestration_id=None, team_id=team_id,
        user_id=user_id, user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
        chat_id="test-chat", message_id="test-message",
        root_chat_id=None, root_turn_id=None, sub_chat_depth=0,
        api_key_hash=None, device_hash=None, is_incognito=False,
        team_workspace_type="chat", team_object_id_hash=None,
        resolved_recovery_inference_task_id=lambda: None,
    )


def _pricing():
    return {
        "pricing": {"tokens": {
            "input": {"per_credit_unit": 1000},
            "output": {"per_credit_unit": 100},
        }},
        "features": {"max_output_tokens": 65536},
    }


def _history():
    return [
        {"role": "user", "content": "Hello " * 1500, "created_at": index + 1,
         "message_id": f"m-{index}"}
        for index in range(20)
    ]


def _google_response(*, success=True, usage=True):
    return SimpleNamespace(
        success=success,
        direct_message_content="## Summary\nUseful history" if success else None,
        error_message="supplier failed" if not success else None,
        model_id="gemini-3.5-flash-lite",
        usage=(SimpleNamespace(
            prompt_token_count=500, candidates_token_count=40,
            thoughts_token_count=60, total_token_count=600,
        ) if usage else None),
    )


def _cerebras_response(*, success=True):
    usage = SimpleNamespace(input_tokens=600, output_tokens=30)
    usage._cerebras_reported_usage_complete = True
    return SimpleNamespace(
        success=success,
        direct_message_content="## Summary\nFallback history" if success else None,
        error_message="supplier failed" if not success else None,
        model_id="gpt-oss-120b",
        usage=usage,
    )


@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setattr(
        summary_billing.celery_config.config_manager, "get_model_pricing",
        lambda *_args: _pricing(),
    )


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_summary_reserves_before_provider_and_counts_google_thoughts(monkeypatch, priced):
    events = []

    async def post(_endpoint, payload):
        events.append("reserve")
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "created": True}

    async def google(**_kwargs):
        events.append("provider")
        return _google_response()

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.google_client.invoke_google_ai_studio_chat_completions", google,
    )
    operation = summary_billing.SummaryBillingOperation(task_id="task-1", request_data=_request())
    result = await chat_compressor.compress_chat_history(
        _history(), "task-1", MagicMock(), compression_threshold=1,
        billing_operation=operation,
    )
    assert events == ["reserve", "provider"]
    assert result.was_compressed
    assert result.usage_attempts[0]["output_tokens"] == 100
    assert result.usage_attempts[0]["output_reasoning_tokens"] == 60
    assert result.usage_attempts[0]["tariff_snapshot"]["pricing_version"]


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("response,exception", [
    ("budget", summary_billing.SummaryBillingLimitError),
    ("duplicate", summary_billing.SummaryBillingDuplicateError),
])
async def test_summary_denial_or_existing_hold_never_dispatches(monkeypatch, priced, response, exception):
    called = False

    async def post(_endpoint, payload):
        if response == "budget":
            request = httpx.Request("POST", "https://example.invalid/reserve")
            raise httpx.HTTPStatusError(
                "budget", request=request,
                response=httpx.Response(402, request=request),
            )
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "created": False}

    async def google(**_kwargs):
        nonlocal called
        called = True
        return _google_response()

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.google_client.invoke_google_ai_studio_chat_completions", google,
    )
    operation = summary_billing.SummaryBillingOperation(task_id="task-1", request_data=_request())
    with pytest.raises(exception):
        await chat_compressor.compress_chat_history(
            _history(), "task-1", MagicMock(), compression_threshold=1,
            billing_operation=operation,
        )
    assert not called


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_summary_fallback_tops_up_and_items_are_reported_once(monkeypatch, priced):
    events = []

    async def post(_endpoint, payload):
        events.append(("reserve", payload["quoted_credits"]))
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"],
                "created": len(events) == 1}

    async def google(**_kwargs):
        events.append(("google", None))
        return _google_response(success=False)

    async def cerebras(**_kwargs):
        events.append(("cerebras", None))
        return _cerebras_response()

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.google_client.invoke_google_ai_studio_chat_completions", google,
    )
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.cerebras_wrapper.invoke_cerebras_chat_completions", cerebras,
    )
    operation = summary_billing.SummaryBillingOperation(task_id="task-2", request_data=_request())
    result = await chat_compressor.compress_chat_history(
        _history(), "task-2", MagicMock(), compression_threshold=1,
        billing_operation=operation,
    )
    assert result.was_compressed
    assert [event[0] for event in events] == ["reserve", "google", "reserve", "cerebras"]
    assert {bucket["attempt_id"] for bucket in result.usage_attempts} == {"google:1", "cerebras:2"}
    assert [bucket["inference_host"] for bucket in result.usage_attempts] == ["google_ai_studio", "cerebras"]
    assert operation.receipt()["output_tokens"] == 130


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_summary_missing_usage_keeps_hold_and_does_not_try_fallback(monkeypatch, priced):
    fallback_called = False

    async def post(_endpoint, payload):
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "created": True}

    async def google(**_kwargs):
        return _google_response(success=False, usage=False)

    async def cerebras(**_kwargs):
        nonlocal fallback_called
        fallback_called = True
        return _cerebras_response()

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.google_client.invoke_google_ai_studio_chat_completions", google,
    )
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.cerebras_wrapper.invoke_cerebras_chat_completions", cerebras,
    )
    operation = summary_billing.SummaryBillingOperation(task_id="task-3", request_data=_request())
    with pytest.raises(summary_billing.SummaryBillingAmbiguousError):
        await chat_compressor.compress_chat_history(
            _history(), "task-3", MagicMock(), compression_threshold=1,
            billing_operation=operation,
        )
    assert operation.hold_active
    assert not fallback_called


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_summary_missing_google_thoughts_requires_reconciled_total(monkeypatch, priced):
    async def post(_endpoint, payload):
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "created": True}

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    operation = summary_billing.SummaryBillingOperation(task_id="task-unknown-output", request_data=_request())
    await operation.admit(
        model_id="google/gemini-3.5-flash-lite", host="google_ai_studio",
        system_prompt="system", messages=[{"role": "user", "content": "history"}],
        max_tokens=20_000, attempt_id="google:1",
    )
    uncertain = _google_response()
    uncertain.usage.thoughts_token_count = None
    with pytest.raises(summary_billing.SummaryBillingAmbiguousError):
        operation.observe(uncertain, attempt_id="google:1")
    assert operation.hold_active and operation.buckets == []
    certain_zero = _google_response()
    certain_zero.usage.thoughts_token_count = None
    certain_zero.usage.total_token_count = 540
    operation.observe(certain_zero, attempt_id="google:1")
    assert operation.buckets[0]["output_tokens"] == 40


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_failed_summary_releases_hold_without_customer_charge(monkeypatch, priced):
    endpoints = []

    async def post(endpoint, payload):
        endpoints.append(endpoint)
        if endpoint.endswith("/reserve"):
            return {"state": "reserved", "charge_id": payload["idempotency_key"],
                    "quoted_credits": payload["quoted_credits"],
                    "created": endpoints.count(endpoint) == 1}
        return {"state": "released", "charge_id": payload["idempotency_key"]}

    async def google(**_kwargs):
        return _google_response(success=False)

    async def cerebras(**_kwargs):
        return _cerebras_response(success=False)

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.google_client.invoke_google_ai_studio_chat_completions", google,
    )
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.cerebras_wrapper.invoke_cerebras_chat_completions", cerebras,
    )
    operation = summary_billing.SummaryBillingOperation(task_id="task-3", request_data=_request())
    result = await chat_compressor.compress_chat_history(
        _history(), "task-3", MagicMock(), compression_threshold=1,
        billing_operation=operation,
    )
    assert not result.was_compressed
    assert len(result.usage_attempts) == 2
    await operation.release_failed()
    assert not operation.hold_active
    assert endpoints[-1] == "internal/billing/reservation/release"
    assert not any(endpoint.endswith("/charge") for endpoint in endpoints)


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_unknown_cerebras_model_is_rejected_before_fallback_dispatch(monkeypatch, priced):
    fallback_called = False

    async def post(_endpoint, payload):
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "created": True}

    async def google(**_kwargs):
        return _google_response(success=False)

    async def cerebras(**_kwargs):
        nonlocal fallback_called
        fallback_called = True
        return _cerebras_response()

    monkeypatch.setattr(chat_compressor, "CEREBRAS_COMPRESSION_FALLBACK_MODEL_ID", "unknown-model")
    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.google_client.invoke_google_ai_studio_chat_completions", google,
    )
    monkeypatch.setattr(
        "backend.apps.ai.llm_providers.cerebras_wrapper.invoke_cerebras_chat_completions", cerebras,
    )
    operation = summary_billing.SummaryBillingOperation(task_id="task-3", request_data=_request())
    with pytest.raises(summary_billing.SummaryBillingUnsupportedFallbackError):
        await chat_compressor.compress_chat_history(
            _history(), "task-3", MagicMock(), compression_threshold=1,
            billing_operation=operation,
        )
    assert len(operation.buckets) == 1
    assert not fallback_called


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_summary_intent_precedes_charge_with_same_identity_and_pending_receipt(monkeypatch, priced):
    calls = []

    async def post(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint.endswith("/reserve"):
            return {"state": "reserved", "charge_id": payload["idempotency_key"],
                    "quoted_credits": payload["quoted_credits"], "created": True}
        if endpoint.endswith("/record-intent"):
            return {"state": "response_recorded", "charge_id": payload["charge_id"]}
        return {"state": "committed", "charge_id": payload["idempotency_key"]}

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    operation = summary_billing.SummaryBillingOperation(task_id="task-4", request_data=_request())
    await operation.admit(
        model_id="google/gemini-3.5-flash-lite", host="google_ai_studio",
        system_prompt="system", messages=[{"role": "user", "content": "history"}],
        max_tokens=20_000, attempt_id="google:1",
    )
    operation.observe(_google_response(), attempt_id="google:1")
    receipt = await operation.record_intent(summary_message_id="summary-id")
    await operation.settle(receipt=receipt)
    assert [path for path, _ in calls] == [
        "internal/billing/reserve", "internal/billing/reservation/record-intent",
        "internal/billing/charge",
    ]
    assert calls[1][1]["llm_usage_breakdown"]["settlement_state"] == "pending"
    assert calls[1][1]["llm_usage_breakdown"]["entries"][0]["purpose"] == "summary"
    assert calls[0][1]["idempotency_key"] == calls[1][1]["charge_id"] == calls[2][1]["idempotency_key"]
    assert calls[2][1]["usage_details"]["reservation_required"] is True


def _task_request():
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.schemas.chat import AIHistoryMessage

    return AskSkillRequest(
        message_history=[AIHistoryMessage(
            role="user", content="history", created_at=1,
            message_id="source-id",
        )],
        user_id="user-id", user_id_hash="user-hash",
        chat_id="chat-id", message_id="message-id",
    )


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("failure", [None, "intent", "checkpoint"])
async def test_summary_task_records_intent_before_checkpoint_then_settles(monkeypatch, failure):
    events = []

    async def admin_threshold(*_args):
        return 1

    async def compression(**kwargs):
        assert kwargs["billing_operation"] is not None
        events.append("provider")
        return chat_compressor.CompressionResult(
            was_compressed=True, summary_content="## Summary\nText",
            compressed_up_to_timestamp=1, compressed_up_to_message_id="source-id",
        )

    class Billing:
        intent_recorded = False

        def __init__(self, **_kwargs):
            pass

        async def record_intent(self, *, summary_message_id):
            events.append("intent")
            if failure == "intent":
                raise summary_billing.SummaryBillingAmbiguousError("core unavailable")
            self.intent_recorded = True
            return {"credits_charged": 1}

        async def settle(self, *, receipt):
            assert receipt["credits_charged"] == 1
            events.append("settle")

    class Cache:
        async def publish_event(self, *_args):
            pass

        async def set_ai_messages_history(self, **_kwargs):
            events.append("checkpoint")
            if failure == "checkpoint":
                raise RuntimeError("cache unavailable")

    class Encryption:
        async def encrypt_with_user_key(self, *_args):
            return "ciphertext", None

    monkeypatch.setattr(ask_skill_task, "get_admin_compression_threshold", admin_threshold)
    monkeypatch.setattr(ask_skill_task, "model_compression_threshold", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(ask_skill_task, "should_compress", lambda *_args: True)
    monkeypatch.setattr(ask_skill_task, "selected_main_cache_tariff_active", lambda *_args: True)
    monkeypatch.setattr(ask_skill_task, "SummaryBillingOperation", Billing)
    monkeypatch.setattr(ask_skill_task, "compress_chat_history", compression)
    kwargs = dict(
        task_id="task-5", request_data=_task_request(), selected_model_id="google/model",
        cache_service=Cache(), encryption_service=Encryption(),
        user_vault_key_id="key", secrets_manager=MagicMock(),
    )
    if failure is not None:
        with pytest.raises(ask_skill_task.RecoveryCheckpointPersistenceError):
            await ask_skill_task._compress_for_selected_model(**kwargs)
        assert events == (["provider", "intent"] if failure == "intent" else
                          ["provider", "intent", "checkpoint"])
    else:
        assert await ask_skill_task._compress_for_selected_model(**kwargs)
        assert events == ["provider", "intent", "checkpoint", "settle"]


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("excluded", [
    {"user_preferences": {"workflow_ai": True, "workflow_credit_allowance": 10}},
    {"is_sub_chat": True, "orchestration_id": "tree-1"},
])
async def test_workflow_and_subchat_compression_stays_bundled(monkeypatch, excluded):
    request = _task_request()
    for name, value in excluded.items():
        setattr(request, name, value)

    async def admin_threshold(*_args):
        return 1

    async def compression(**kwargs):
        assert "billing_operation" not in kwargs
        return chat_compressor.CompressionResult(was_compressed=False)

    class Cache:
        async def publish_event(self, *_args):
            pass

    monkeypatch.setattr(ask_skill_task, "get_admin_compression_threshold", admin_threshold)
    monkeypatch.setattr(ask_skill_task, "model_compression_threshold", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(ask_skill_task, "should_compress", lambda *_args: True)
    monkeypatch.setattr(ask_skill_task, "selected_main_cache_tariff_active", lambda *_args: True)
    monkeypatch.setattr(ask_skill_task, "SummaryBillingOperation", lambda **_kwargs: pytest.fail("summary hold created"))
    monkeypatch.setattr(ask_skill_task, "compress_chat_history", compression)
    assert not await ask_skill_task._compress_for_selected_model(
        task_id="excluded-task", request_data=request, selected_model_id="google/model",
        cache_service=Cache(), encryption_service=MagicMock(),
        user_vault_key_id="key", secrets_manager=MagicMock(),
    )


@pytest.mark.parametrize("retain_placeholder", [False, True])
# contract-test: supporting surface=rest_api assertions=projects.focus.custom-catalog-privacy
async def test_compression_keeps_private_project_file_text_only_in_answer_memory(monkeypatch, retain_placeholder):
    from backend.core.api.app.schemas.chat import AIHistoryMessage
    from backend.shared.python_utils.recent_work_summary_client import (
        PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER, restore_async_tool_completion_message,
    )

    request = _task_request()
    request.is_async_skill_continuation = True
    request.async_skill_task_id = "read-1"
    request.message_history.append(AIHistoryMessage(
        role="user", sender_name="async_tool_result", message_id="read-1",
        content=PRIVATE_ASYNC_TOOL_RESULT_PLACEHOLDER, created_at=2,
    ))
    restore_async_tool_completion_message(request, {"async_tool_history": [{
        "index": 1, "project_id": "11111111-1111-4111-8111-111111111111",
        "content": "SECRET README CONTENT @ai-model:gpt-5.4",
    }]})
    assert "SECRET README CONTENT" in request.message_history[-1].content

    async def compression(**kwargs):
        assert "SECRET README CONTENT" not in str(kwargs["message_history"])
        recent = [kwargs["message_history"][-1]] if retain_placeholder else []
        return chat_compressor.CompressionResult(
            was_compressed=True, summary_content="Summary without file bodies",
            compressed_up_to_timestamp=1, compressed_up_to_message_id="source-id",
            recent_messages=recent,
        )

    class Cache:
        stored = None

        async def publish_event(self, *_args):
            pass

        async def set_ai_messages_history(self, **kwargs):
            self.stored = kwargs["encrypted_messages_json_list"]

    class Encryption:
        plaintexts = []

        async def encrypt_with_user_key(self, plaintext, *_args):
            self.plaintexts.append(plaintext)
            return "ciphertext", None

    cache, encryption = Cache(), Encryption()
    async def admin_threshold(*_args):
        return 1

    monkeypatch.setattr(ask_skill_task, "get_admin_compression_threshold", admin_threshold)
    monkeypatch.setattr(ask_skill_task, "model_compression_threshold", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(ask_skill_task, "should_compress", lambda *_args: True)
    monkeypatch.setattr(ask_skill_task, "selected_main_cache_tariff_active", lambda *_args: False)
    monkeypatch.setattr(ask_skill_task, "compress_chat_history", compression)
    assert await ask_skill_task._compress_for_selected_model(
        task_id="task-private-read", request_data=request, selected_model_id="google/model",
        cache_service=cache, encryption_service=encryption,
        user_vault_key_id="key", secrets_manager=MagicMock(),
    )
    assert "SECRET README CONTENT" not in str(cache.stored)
    assert "SECRET README CONTENT" not in str(encryption.plaintexts)
    assert "SECRET README CONTENT" in request.message_history[-1].content
    assert request.message_history[-1].sender_name == "async_tool_result"
    assert request.message_history[-1].message_id == "read-1"
    assert "SECRET README CONTENT" not in str(request.model_dump(mode="json"))


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
async def test_summary_team_charge_accepts_existing_team_ack_shape(monkeypatch, priced):
    calls = []

    async def post(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint.endswith("/reserve"):
            return {"state": "reserved", "charge_id": payload["idempotency_key"],
                    "quoted_credits": payload["quoted_credits"], "created": True}
        if endpoint.endswith("/record-intent"):
            return {"state": "response_recorded", "charge_id": payload["charge_id"]}
        return {"state": "committed", "charged_credits": payload["credits"]}

    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    operation = summary_billing.SummaryBillingOperation(
        task_id="team-task", request_data=_request(team_id="22222222-2222-4222-8222-222222222222"),
    )
    await operation.admit(
        model_id="google/gemini-3.5-flash-lite", host="google_ai_studio",
        system_prompt="system", messages=[{"role": "user", "content": "history"}],
        max_tokens=20_000, attempt_id="google:1",
    )
    operation.observe(_google_response(), attempt_id="google:1")
    receipt = await operation.record_intent(summary_message_id="summary-id")
    assert (await operation.settle(receipt=receipt))["state"] == "committed"
    assert calls[1][1]["user_id"] == "11111111-1111-4111-8111-111111111111"
    assert calls[1][1]["team_id"] == "22222222-2222-4222-8222-222222222222"
    assert "actor_user_id" not in calls[1][1]
    assert calls[2][1]["actor_user_id"] == "11111111-1111-4111-8111-111111111111"


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("raw_usage,complete", [
    ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, True),
    ({"prompt_tokens": 4, "completion_tokens": 2}, True),
    (None, False),
    ({"prompt_tokens": 4}, False),
    ({"completion_tokens": 2}, False),
    ({"prompt_tokens": -1, "completion_tokens": 2}, False),
    ({"prompt_tokens": True, "completion_tokens": 2}, False),
    ({"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 7}, False),
    ({"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": False}, False),
])
async def test_cerebras_raw_usage_marker_controls_summary_billing(monkeypatch, priced, raw_usage, complete):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "summary"}}], "usage": raw_usage}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, *_args, **_kwargs):
            return Response()

    async def post(_endpoint, payload):
        return {"state": "reserved", "charge_id": payload["idempotency_key"],
                "quoted_credits": payload["quoted_credits"], "created": True}

    monkeypatch.setattr(cerebras_client.httpx, "AsyncClient", Client)
    monkeypatch.setattr(cerebras_client, "calculate_token_breakdown", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(summary_billing.SummaryBillingOperation, "_post", staticmethod(post))
    response = await cerebras_client._send_cerebras_request(
        "raw-usage", "gpt-oss-120b", {"messages": []}, {},
    )
    assert response.success
    assert getattr(response.usage, "_cerebras_reported_usage_complete", None) is complete
    operation = summary_billing.SummaryBillingOperation(task_id="raw-usage", request_data=_request())
    await operation.admit(
        model_id="openai/gpt-oss-120b", host="cerebras", system_prompt="system",
        messages=[{"role": "user", "content": "history"}],
        max_tokens=20_000, attempt_id="cerebras:1",
    )
    if complete:
        operation.observe(response, attempt_id="cerebras:1")
        assert operation.buckets[0]["input_tokens"] == raw_usage["prompt_tokens"]
        assert operation.buckets[0]["output_tokens"] == raw_usage["completion_tokens"]
    else:
        with pytest.raises(summary_billing.SummaryBillingAmbiguousError):
            operation.observe(response, attempt_id="cerebras:1")
        assert operation.hold_active and operation.buckets == []


# contract-test: supporting surface=rest_api assertions=billing.usage.receipt-token-breakdown
def test_payment_disabled_keeps_separate_summary_tariff_inactive(monkeypatch, priced):
    from backend.core.api.app.utils import server_mode

    manager = summary_billing.celery_config.config_manager
    pricing = _pricing()
    pricing["default_server"] = "google_ai_studio"
    pricing["cache_pricing"] = {
        "enabled": True, "status": "verified_for_activation",
        "eligible_hosts": ["google_ai_studio"],
        "write_billing": "included_in_input",
        "source_url": "https://example.com/pricing", "reviewed_on": "2026-10-01",
        "expires_on": "2099-12-31",
    }
    monkeypatch.setattr(manager, "get_model_pricing", lambda *_args: pricing)
    monkeypatch.setattr(server_mode, "is_payment_enabled", lambda: False)
    assert not summary_billing.selected_main_cache_tariff_active("google/model")
