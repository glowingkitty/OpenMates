"""Independent replies keep the foreground, protected turn and billing identities separate."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from cryptography.exceptions import InvalidTag

from backend.apps.ai.skills.ask_skill import AskSkillDefaultConfig, AskSkillRequest
from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
from backend.shared.python_utils.ai_task_cancellation import cancellation_scope_key
from backend.shared.python_utils.chat_completion_recovery import derive_recovery_keypair, open_recovery_envelope
from backend.shared.python_utils.independent_chat_reply import (
    independent_reply_is_active,
    release_independent_reply,
    reserve_independent_reply,
    verify_independent_reply,
)


def _message(message_id, role, content, created_at):
    return AIHistoryMessage(
        message_id=message_id, role=role, sender_name=role, content=content, created_at=created_at,
    )


@pytest.fixture
def question():
    chat_id, source_id, task_id, turn_id, preflight_id = (str(uuid4()) for _ in range(5))
    content = "What does the cache flag do?"
    owner = str(uuid4())
    return AskSkillRequest(
        user_id=owner, user_id_hash=hashlib.sha256(owner.encode()).hexdigest(),
        chat_id=chat_id, message_id="question", recovery_task_id=task_id,
        recovery_turn_id=turn_id, recovery_preflight_id=preflight_id,
        recovery_public_key="public", chat_key_version=1,
        active_input_parallel_source=source_id, active_input_parallel_source_message="foreground-user",
        chat_has_title=True, current_user_content=content,
        active_project_focus={"project_id": "attached-project"},
        message_history=[
            _message("old", "user", "Define the cache flag.", 1),
            _message("definition", "assistant", "The cache flag reuses completed build output.", 2),
            _message("foreground-user", "user", "Build the application now.", 3),
            _message(source_id, "assistant", "Unfinished artifact draft.", 4),
            _message("question", "user", content, 5),
        ],
    )


def _claim(request):
    return {
        "claimed": True, "state": "RUNNING", "inference_task_id": request.recovery_task_id,
        "chat_id": request.chat_id, "hashed_user_id": request.user_id_hash,
        "preflight_id": request.recovery_preflight_id, "turn_id": request.recovery_turn_id,
    }


class RedisCache(ChatCacheMixin):
    def __init__(self, redis):
        self.redis = redis

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        result = await self.redis.get(key)
        if not result:
            return None
        try:
            return json.loads(result)
        except ValueError:
            return result.decode()


async def _mark_foreground(cache, request):
    assert await cache.try_claim_active_ai_task(request.chat_id, request.active_input_parallel_source)
    await cache.redis.set(
        f"async_skill_latest_user_turn:{request.user_id}:{request.chat_id}",
        request.active_input_parallel_source_message,
    )
    await cache.redis.set(
        cancellation_scope_key(request.chat_id, request.active_input_parallel_source),
        json.dumps({
            "user_id": request.user_id, "chat_id": request.chat_id,
            "task_id": request.active_input_parallel_source,
            "user_message_id": request.active_input_parallel_source_message,
        }),
    )


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work,chat-queued-followups.access.scoped
@pytest.mark.asyncio
async def test_one_exact_parallel_claim_preserves_the_foreground_and_queue(question):
    async with FakeRedis() as redis:
        cache = RedisCache(redis)
        await _mark_foreground(cache, question)
        wrong_source = question.model_copy(update={"active_input_parallel_source_message": "wrong-source"})
        assert await reserve_independent_reply(cache, wrong_source) == 0
        assert await reserve_independent_reply(cache, question) == 1
        assert await reserve_independent_reply(cache, question) == 2
        new_delivery = question.model_copy(update={"recovery_task_id": str(uuid4())})
        assert await reserve_independent_reply(cache, new_delivery) == 0
        assert await cache.get_chat_id_for_task(question.recovery_task_id) == question.chat_id
        assert await verify_independent_reply(cache, question, question.recovery_task_id, _claim(question))
        assert not await verify_independent_reply(
            cache, question, question.recovery_task_id, {**_claim(question), "turn_id": str(uuid4())},
        )
        assert not await independent_reply_is_active(
            cache, user_id="other", chat_id=question.chat_id, task_id=question.recovery_task_id,
        )
        marker = "queuing must stay unchanged"
        await redis.set(cache._get_chat_queue_key(question.chat_id), marker)
        assert not await release_independent_reply(cache, user_id=question.user_id, chat_id=question.chat_id, task_id="other")
        assert await release_independent_reply(
            cache, user_id=question.user_id, chat_id=question.chat_id, task_id=question.recovery_task_id,
        )
        assert await redis.get(cache._get_chat_queue_key(question.chat_id)) == marker.encode()
        assert await cache.get_active_ai_task(question.chat_id) == question.active_input_parallel_source


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work
@pytest.mark.asyncio
async def test_canonical_worker_answers_from_completed_history_while_foreground_is_streaming(monkeypatch, question):
    from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata
    from backend.apps.ai.processing import answer_safety, main_processor, preprocessor
    from backend.apps.ai.tasks import ask_skill_task, stream_consumer
    from backend.apps.ai.tasks.stage_one_task import eligible_for_routing_lane
    from backend.core.api.app.services import client_context_continuation
    from backend.core.api.app.tasks import celery_config
    from backend.shared.python_utils import voice_call_admission

    foreground = question.active_input_parallel_source
    foreground_streaming = asyncio.Event()
    allow_foreground_finish = asyncio.Event()
    reply = "The cache flag reuses completed build output."
    private_key, public_key = derive_recovery_keypair(
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", question.chat_id, question.chat_key_version,
    )
    question.recovery_public_key = public_key
    sealed_jobs = {}

    async def create_job(operation, data):
        assert operation == "create_sealed_job"
        assert data["inference_task_id"] not in sealed_jobs
        sealed_jobs[data["inference_task_id"]] = data
        return {"job_id": data["job_id"]}

    billing = AsyncMock(return_value={})
    queue_ack = AsyncMock()
    finish_safety = AsyncMock(return_value=(None, 0))
    reserve_provider = AsyncMock(return_value=512)
    saved_history = AsyncMock()
    provider_questions = []
    provider_answer = asyncio.Event()
    preprocessing = preprocessor.PreprocessingResult(
        can_proceed=True, category="software_development", selected_mate_id="programmer",
        selected_main_llm_model_id="openai/test-model", llm_response_temp=0.4,
    )
    available_mates = [SimpleNamespace(
        id="programmer", category="software_development", voice_profile=SimpleNamespace(key="programmer", version=1),
    )]

    async def preprocess(**kwargs):
        request = kwargs["request_data"]
        assert request.active_project_focus == {"project_id": "attached-project"}
        assert [message.message_id for message in request.message_history] == ["old", "definition", "question"]
        return preprocessing

    async def provider(**kwargs):
        assert foreground_streaming.is_set() and not allow_foreground_finish.is_set()
        assert kwargs["tool_choice"] == "none" and kwargs["tools"] is None
        provider_questions.append(kwargs["message_history"])
        limit = await kwargs["pre_dispatch_admission"]("openai/test-model", kwargs["max_tokens"])
        assert limit == 512
        # Plain source must never be promoted to an application or code embed.
        yield reply + "\n\n```html\n<html>example</html>\n```"
        yield OpenAIUsageMetadata(input_tokens=37, output_tokens=17, total_tokens=54)
        provider_answer.set()

    actual_main = main_processor.handle_main_processing

    async def main(*args, **kwargs):
        task_id = kwargs["task_id"]
        if task_id == foreground:
            yield "The application is building.\n\n"
            await allow_foreground_finish.wait()
            yield " It is ready."
            return
        async for chunk in actual_main(*args, **kwargs):
            yield chunk

    async with FakeRedis() as redis:
        cache = RedisCache(redis)
        async def put(key, value, ttl):
            return await redis.set(key, json.dumps(value), ex=ttl)

        cache.set = put
        cache.get_user_by_id = AsyncMock(return_value={"vault_key_id": "vault", "encrypted_credit_balance": "encrypted"})
        cache.get_discovered_apps_metadata = AsyncMock(return_value={"ai": SimpleNamespace(skills=[])})
        cache.get_chat_list_item_data = AsyncMock(return_value=None)
        async def publish(channel, payload):
            if (channel == f"chat_stream::{question.chat_id}" and payload.get("task_id") == foreground
                    and payload.get("is_final_chunk") is False):
                foreground_streaming.set()

        cache.cache_debug_request_entry = AsyncMock()
        cache.publish_event = AsyncMock(side_effect=publish)
        cache.lease_queued_message_prefix = AsyncMock(side_effect=AssertionError("Independent reply drained the queue"))
        await _mark_foreground(cache, question)
        assert await reserve_independent_reply(cache, question) == 1
        assert not eligible_for_routing_lane(question.model_dump())

        monkeypatch.setattr(celery_config, "get_worker_cache_service", AsyncMock(return_value=cache))
        monkeypatch.setattr(celery_config.app, "AsyncResult", lambda _: SimpleNamespace(state="STARTED"))
        monkeypatch.setattr(celery_config, "config_manager", SimpleNamespace(
            get_provider_config=lambda _: {"provider": "openai"}, get_model_pricing=lambda *_: {"input": 1, "output": 1},
        ))
        monkeypatch.setattr(ask_skill_task, "SecretsManager", lambda: SimpleNamespace(initialize=AsyncMock()))
        monkeypatch.setattr(ask_skill_task, "EncryptionService", lambda **_: object())
        monkeypatch.setattr(ask_skill_task, "DirectusService", lambda **_: object())
        durable = AsyncMock(return_value=_claim(question))
        monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", lambda _: SimpleNamespace(execute=durable))
        monkeypatch.setattr(ask_skill_task, "_ack_running_recovery_queue_prefix", queue_ack)
        monkeypatch.setattr(ask_skill_task, "load_validated_base_instructions", AsyncMock(return_value={}))
        monkeypatch.setattr(ask_skill_task, "_load_available_mates", AsyncMock(return_value=available_mates))
        monkeypatch.setattr(ask_skill_task, "handle_preprocessing", AsyncMock(side_effect=preprocess))
        monkeypatch.setattr(ask_skill_task, "handle_postprocessing", AsyncMock(side_effect=AssertionError("Shared metadata")))
        monkeypatch.setattr(ask_skill_task, "_publish_project_authoring_availability", AsyncMock())
        monkeypatch.setattr(main_processor, "validate_required_answer_instructions", lambda _: None)
        monkeypatch.setattr(main_processor, "call_main_llm_stream", provider)
        monkeypatch.setattr(main_processor, "_fit_personal_chat_output_token_limit", reserve_provider)
        monkeypatch.setattr(stream_consumer, "handle_main_processing", main)
        monkeypatch.setattr(stream_consumer, "ChatRecoveryService",
                            lambda _: SimpleNamespace(execute=create_job))
        monkeypatch.setattr(stream_consumer, "_update_chat_metadata", saved_history)
        monkeypatch.setattr(stream_consumer, "_handle_normal_billing", billing)
        monkeypatch.setattr(stream_consumer, "mint_response_summary_completion", AsyncMock())
        create_code = AsyncMock(side_effect=AssertionError("A read-only reply created an artifact"))
        monkeypatch.setattr(stream_consumer, "_create_application_artifact_embed_reference", create_code)
        monkeypatch.setattr(voice_call_admission, "require_active_voice_dispatch", AsyncMock())
        monkeypatch.setattr(client_context_continuation, "await_client_context_phase", AsyncMock())
        monkeypatch.setattr(answer_safety, "decide_finished_answer", finish_safety)

        foreground_request = question.model_copy(update={
            "message_id": "foreground-user", "recovery_task_id": foreground,
            "recovery_turn_id": str(uuid4()), "recovery_preflight_id": str(uuid4()),
            "active_input_parallel_source": None,
            "active_input_parallel_source_message": None,
            "current_user_content": "Build the application now.",
        })
        original = asyncio.create_task(stream_consumer._consume_main_processing_stream(
            task_id=foreground, request_data=foreground_request, preprocessing_result=preprocessing,
            base_instructions={}, directus_service=object(), encryption_service=object(), user_vault_key_id="vault",
            all_mates_configs=available_mates, discovered_apps_metadata={}, cache_service=cache,
        ))
        try:
            await asyncio.wait_for(foreground_streaming.wait(), timeout=2)
            result = await ask_skill_task._async_process_ai_skill_ask_task(
                question.recovery_task_id, question, AskSkillDefaultConfig(),
            )
            assert result["main_processing_output"].startswith(reply)
            assert not original.done() and provider_answer.is_set()
            assert await cache.get_active_ai_task(question.chat_id) == foreground
        finally:
            allow_foreground_finish.set()
            await original

        assert [row["content"] for row in provider_questions[0]] == [
            "Define the cache flag.", reply, "What does the cache flag do?",
        ]
        assert not await independent_reply_is_active(
            cache, user_id=question.user_id, chat_id=question.chat_id, task_id=question.recovery_task_id,
        )
        queue_ack.assert_not_awaited()
        cache.lease_queued_message_prefix.assert_not_awaited()
        create_code.assert_not_awaited()
        finish_safety.assert_awaited_once()
        billing.assert_awaited_once()
        assert billing.await_args.args[3] == question.recovery_task_id
        assert billing.await_args.kwargs["usage_by_model"][0]["input_tokens"] == 37
        assert set(sealed_jobs) == {foreground, question.recovery_task_id}
        assert {call.kwargs["task_id"] for call in saved_history.await_args_list} == {foreground, question.recovery_task_id}
        assert reply not in json.dumps(sealed_jobs)
        for request, expected in ((foreground_request, "The application is building."),
                                  (question, reply)):
            job = sealed_jobs[request.recovery_task_id]
            assert job["preflight_id"] == request.recovery_preflight_id
            envelope = json.loads(job["sealed_payload"])
            scope = {
                "recovery_private_key": private_key, "owner_id": question.user_id,
                "chat_id": question.chat_id, "turn_id": request.recovery_turn_id,
                "job_id": job["job_id"], "assistant_message_id": request.recovery_task_id,
                "key_version": question.chat_key_version,
            }
            assert json.loads(open_recovery_envelope(envelope, **scope))["content"].startswith(expected)
            with pytest.raises(InvalidTag):
                open_recovery_envelope(envelope, **dict(scope, turn_id=str(uuid4())))
        final_frames = [call.args[1] for call in cache.publish_event.await_args_list if call.args[1].get("is_final_chunk")]
        assert [frame["user_message_id"] for frame in final_frames] == ["question", "foreground-user"]
        assert final_frames[0]["independent_reply"] is True
        assert "independent_reply" not in final_frames[1]


# contract-test: supporting surface=rest_api assertions=chat-queued-followups.routing.active-work
@pytest.mark.asyncio
async def test_parallel_answer_uses_normal_model_recovery_before_any_visible_text(monkeypatch, question):
    from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata
    from backend.apps.ai.processing import main_processor, preprocessor

    google = "google/primary"
    secondary = main_processor.MERCURY_MODEL
    calls = []

    async def provider(**kwargs):
        model_id = kwargs["model_id"]
        calls.append(model_id)
        assert kwargs["tools"] is None and kwargs["tool_choice"] == "none"
        await kwargs["pre_dispatch_admission"](model_id, kwargs["max_tokens"])
        if model_id == google:
            yield OpenAIUsageMetadata(input_tokens=7, output_tokens=0, total_tokens=7)
            raise main_processor.AllServersFailedError(model_id, ["google"], "temporarily unavailable")
        yield "The cache flag reuses completed build output."
        yield OpenAIUsageMetadata(input_tokens=9, output_tokens=5, total_tokens=14)

    wallet = AsyncMock(return_value=512)
    monkeypatch.setattr(main_processor, "call_main_llm_stream", provider)
    monkeypatch.setattr(main_processor, "_fit_personal_chat_output_token_limit", wallet)
    monkeypatch.setattr(main_processor, "automatic_model_allowed_servers", lambda *_: {"approved-server"})
    question.message_history = [question.message_history[-1]]
    preprocessing = preprocessor.PreprocessingResult(
        can_proceed=True, selected_main_llm_model_id=google, selected_secondary_model_id=secondary,
    )
    events = [item async for item in main_processor._stream_independent_answer(
        task_id=question.recovery_task_id, request=question, preprocessing=preprocessing,
        base_instructions={}, secrets=None, cache=None, directus=object(), encryption=object(),
        on_reasoning_dispatch=None,
    )]
    assert calls == [google, secondary]
    assert wallet.await_count == 2
    assert events[0] == "The cache flag reuses completed build output."
    assert events[1]["successful_model_id"] == secondary
    assert events[1]["total_input_tokens"] == 16
    assert events[1]["tool_inference_iterations"] == 0
