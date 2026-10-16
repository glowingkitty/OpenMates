"""Existing detached skills retain explicit voice authority across hangup."""
import asyncio
import hashlib
import inspect
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis.aioredis
import pytest

from backend.apps.ai.processing import celery_helpers
from backend.apps.ai.processing import voice_async_skills as voice
from backend.apps.images.skills.generate_skill import GenerateSkill
from backend.core.api.app.services.embed_service import EmbedService
from backend.shared.python_utils.chat_recovery_context import (
    RequiredRecoveryOutputError, active_recovery_output_context,
)
from backend.shared.python_utils import voice_action_receipts as receipts
from backend.shared.python_utils.voice_call_registry import register_active_call, issue_message_id


class Cache:
    def __init__(self):
        self.redis = fakeredis.aioredis.FakeRedis()
        self.publish_event = AsyncMock()
        self.add_pending_embed = AsyncMock()

    @property
    async def client(self):
        return self.redis

    async def get_user_vault_key_id(self, owner):
        return "owner-vault"

    async def cache_required_ai_embed(self, owner_hash, chat_id, embed_id, body, **kwargs):
        await self.redis.set(f"embed:{embed_id}", body, ex=3600)
        return True


class Encryption:
    def __init__(self):
        self.values = {}

    async def encrypt_with_user_key(self, plaintext, key):
        assert key == "owner-vault"
        token = f"vault:v1:{uuid.uuid4()}"
        self.values[token] = plaintext
        return token, 1

    async def decrypt_with_user_key(self, token, key):
        assert key == "owner-vault"
        return self.values.get(token)


async def setup(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "isolated-test-binding")
    monkeypatch.setattr(celery_helpers, "record_task_owner", Mock())
    cache, encryption = Cache(), Encryption()
    binding = dict(user_id="voice-owner", user_hash=hashlib.sha256(b"voice-owner").hexdigest(),
        session_id="issued-session", chat_id="personal-chat", call_id=uuid.uuid4().hex,
        user_message_id="issued-user", assistant_message_id="issued-assistant",
        assistant_created_at=int(time.time()), operation_id=uuid.uuid4().hex, skill_index=2)
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(
        return_value={"hashed_user_id": binding["user_hash"]})),
        embed=SimpleNamespace(get_sync_embed_by_id=AsyncMock(return_value=None)))
    call = {k: binding[k] for k in ("user_id", "session_id", "chat_id", "call_id")}
    await register_active_call(cache, **call)
    for role in ("user", "assistant"):
        await issue_message_id(cache, **call, message_id=binding[f"{role}_message_id"], role=role)
    request_id = "parent-action-request"
    await receipts.admit_voice_action_receipt(cache_service=cache, directus_service=directus,
        encryption_service=encryption, binding=binding, request_id=request_id)
    service = EmbedService(cache_service=cache, directus_service=directus, encryption_service=encryption)
    calls = []
    def send_task(**options):
        calls.append(options)
        return SimpleNamespace(id=options["task_id"])
    producer = SimpleNamespace(send_task=send_task, conf=SimpleNamespace(broker_url="isolated-broker"))
    return cache, directus, encryption, binding, request_id, service, producer, calls


async def dispatch_images(monkeypatch, count=1):
    env = await setup(monkeypatch)
    cache, directus, encryption, binding, request_id, service, producer, calls = env
    skill = GenerateSkill(app=SimpleNamespace(), app_id="images", skill_id="generate",
        skill_name="generate", skill_description="generate", celery_producer=producer)
    skill._current_chat_id = binding["chat_id"]
    skill._current_message_id = binding["assistant_message_id"]
    async with voice.voice_async_output_context(binding=binding, request_id=request_id,
            cache_service=cache, directus_service=directus, encryption_service=encryption,
            embed_service=service) as state:
        result = await skill.execute(requests=[{"prompt": f"Private mountain landscape {i}"}
                                               for i in range(count)], user_id=binding["user_id"])
    assert state.dispatched, result
    return env, state, result


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_real_image_skill_dispatches_sealed_exact_invocation_and_processing_embed(monkeypatch):
    env, state, result = await dispatch_images(monkeypatch)
    cache, directus, encryption, binding, _, _, _, calls = env
    call = calls[0]
    assert result["status"] == "processing"
    assert call["queue"] == "app_images"
    assert call["kwargs"] == {"voice_task_ref": call["task_id"], "user_id": binding["user_id"]}
    assert "Private mountain" not in json.dumps(call)
    kwargs, worker = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    assert set(kwargs) == {"app_id", "skill_id", "arguments"}  # Actual app task signature.
    assert kwargs["arguments"]["prompt"] == "Private mountain landscape 0"
    assert kwargs["arguments"]["user_vault_key_id"] == "owner-vault"
    assert worker.embed_id == result["embed_id"] == state.artifact_ids[0]
    cached = json.loads(await cache.redis.get(f"embed:{worker.embed_id}"))
    assert cached["status"] == "processing" and cached["message_id"] == binding["assistant_message_id"]
    assert cached["encrypted_content"].startswith("vault:v")
    for key in await cache.redis.keys("voice:action:*"):
        if await cache.redis.type(key) == b"string":
            assert b"Private mountain" not in await cache.redis.get(key)
    assert voice.voice_task_result({"status": "finished", "prompt": "private", "aes_key": "secret"}, worker) == {
        "task_id": call["task_id"], "embed_id": worker.embed_id, "status": "finished"}


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_multiple_jobs_have_immutable_child_receipts_and_continue_after_hangup(monkeypatch):
    cache, directus, encryption, binding, request_id, service, producer, calls = await setup(monkeypatch)
    skill = GenerateSkill(app=SimpleNamespace(), app_id="images", skill_id="generate",
        skill_name="generate", skill_description="generate", celery_producer=producer)
    skill._current_chat_id, skill._current_message_id = binding["chat_id"], binding["assistant_message_id"]
    async with voice.voice_async_output_context(binding=binding, request_id=request_id,
            cache_service=cache, directus_service=directus, encryption_service=encryption,
            embed_service=service) as state:
        results = [await skill.execute(requests=[{"prompt": f"Private mountain landscape {index}"}],
                       user_id=binding["user_id"]) for index in range(2)]
    assert len(state.actions) == len(calls) == 2
    assert all(result["status"] == "processing" for result in results)
    assert {result["task_id"] for result in results} == {call["task_id"] for call in calls}
    await cache.redis.delete(f"voice:call:{binding['call_id']}", f"voice:call:{binding['call_id']}:messages")
    for call in calls:
        _, context = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
            args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
            directus_service=directus, encryption_service=encryption)
        receipt = await receipts.load_voice_action_receipt(cache_service=cache,
            directus_service=directus, encryption_service=encryption, user_id=binding["user_id"],
            user_hash=binding["user_hash"], session_id=binding["session_id"], request_id=context.request_id)
        assert receipt["embed_refs"] == [context.embed_id]
        assert receipt["assistant_message_id"] == binding["assistant_message_id"]
        assert receipt["operation_id"] == call["task_id"]
        finished = json.loads(await cache.redis.get(f"embed:{context.embed_id}"))
        finished["status"] = "finished"
        finished["encrypted_content"], _ = await encryption.encrypt_with_user_key(
            "Completed private mountain landscape", "owner-vault")
        with voice.bound_voice_worker(context):
            delivered = await service.send_embed_data_to_client(
                embed_id=context.embed_id, embed_type="image", content_toon="Completed private mountain landscape",
                chat_id=binding["chat_id"], message_id=binding["assistant_message_id"],
                user_id=binding["user_id"], user_id_hash=binding["user_hash"], status="finished",
                finished_cache_data=finished, finished_cache_vault_key_id="owner-vault")
        assert delivered is True
        assert json.loads(await cache.redis.get(f"embed:{context.embed_id}"))["status"] == "finished"
        cache.add_pending_embed.assert_any_await(binding["user_id"], context.embed_id)
    assert len({action["task_id"] for action in state.actions}) == 2


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_actual_batched_image_requests_retain_one_sealed_task_and_parent_artifact(monkeypatch):
    from backend.apps.images.tasks.generate_task import generate_image_task
    env, state, result = await dispatch_images(monkeypatch, count=2)
    cache, directus, encryption, binding, _, _, _, calls = env
    assert len(calls) == len(state.actions) == len(state.artifact_ids) == 1
    call = calls[0]
    assert result == {"task_id": call["task_id"], "embed_id": state.artifact_ids[0], "status": "processing"}
    assert call["kwargs"] == {"voice_task_ref": call["task_id"], "user_id": binding["user_id"]}
    assert "Private mountain" not in json.dumps(call)
    invocation, context = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    inspect.signature(generate_image_task.run).bind(**invocation)
    arguments = invocation["arguments"]
    assert [request["prompt"] for request in arguments["requests"]] == [
        "Private mountain landscape 0", "Private mountain landscape 1"]
    assert len(arguments["requests"]) == 2
    assert arguments["embed_id"] == context.embed_id == result["embed_id"]
    assert all(request["embed_id"] == context.embed_id for request in arguments["requests"])
    assert arguments["user_vault_key_id"] == "owner-vault"
    receipt = await receipts.load_voice_action_receipt(cache_service=cache,
        directus_service=directus, encryption_service=encryption, user_id=binding["user_id"],
        user_hash=binding["user_hash"], session_id=binding["session_id"], request_id=context.request_id)
    assert receipt["embed_refs"] == [context.embed_id]
    assert receipt["assistant_message_id"] == binding["assistant_message_id"]
    assert receipt["operation_id"] == call["task_id"]
    cached = json.loads(await cache.redis.get(f"embed:{context.embed_id}"))
    assert cached["status"] == "processing"
    assert cached["encrypted_content"].startswith("vault:v")


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_authorized_voice_composite_keeps_sealed_parent_and_stable_search_children(monkeypatch):
    env, _, _ = await dispatch_images(monkeypatch)
    cache, directus, encryption, binding, _, service, _, calls = env
    call = calls[0]
    _, worker = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    cache.get_discovered_apps_metadata = AsyncMock(return_value={})
    monkeypatch.setattr(service, "_schedule_embed_persistence_fallback", Mock())
    save_individual = AsyncMock()
    save_ordinary_batch = AsyncMock(side_effect=AssertionError("Voice must not use ordinary composite recovery"))
    monkeypatch.setattr(service, "_save_completed_embed_recovery", save_individual)
    monkeypatch.setattr(service, "_save_completed_embed_recovery_batch", save_ordinary_batch)
    publish = AsyncMock(wraps=cache.redis.publish)
    monkeypatch.setattr(cache.redis, "publish", publish)
    search_results = [
        {"title": "Example A", "url": "https://example.org/a", "snippet": "Example A summary"},
        {"title": "Example B", "url": "https://example.org/b", "snippet": "Example B summary"},
    ]
    # A verified voice producer takes precedence even if an ordinary recovery
    # context is inherited by this task. Its composite must publish separately.
    ordinary = SimpleNamespace(owner_id=binding["user_id"], owner_hash=binding["user_hash"],
        target_chat_id=binding["chat_id"])
    token = active_recovery_output_context.set(ordinary)
    try:
        with voice.bound_voice_worker(worker):
            result = await service.create_embeds_from_skill_results(
                app_id="web", skill_id="search", results=search_results,
                chat_id=binding["chat_id"], message_id=binding["assistant_message_id"],
                user_id=binding["user_id"], user_id_hash=binding["user_hash"],
                user_vault_key_id="owner-vault", task_id=worker.task_id)
    finally:
        active_recovery_output_context.reset(token)

    expected_children = [str(uuid.uuid5(uuid.UUID(worker.task_id), f"embed-child:{index}"))
                         for index in range(2)]
    assert result["parent_embed_id"] == worker.embed_id
    assert result["child_embed_ids"] == expected_children
    assert json.loads(result["embed_reference"])["embed_id"] == worker.embed_id
    assert save_individual.await_count == 3
    save_ordinary_batch.assert_not_awaited()
    assert publish.await_count == 3
    published = [json.loads(entry.args[1])["payload"] for entry in publish.await_args_list]
    assert [entry["embed_id"] for entry in published] == [*expected_children, worker.embed_id]
    assert all(entry["chat_id"] == binding["chat_id"]
               and entry["message_id"] == binding["assistant_message_id"] for entry in published)
    assert [entry.get("parent_embed_id") for entry in published[:2]] == [worker.embed_id] * 2
    assert published[-1]["embed_ids"] == expected_children
    receipt = await receipts.load_voice_action_receipt(cache_service=cache,
        directus_service=directus, encryption_service=encryption, user_id=binding["user_id"],
        user_hash=binding["user_hash"], session_id=binding["session_id"], request_id=worker.request_id)
    assert receipt["embed_refs"] == [worker.embed_id]
    assert receipt["assistant_message_id"] == binding["assistant_message_id"]

    await cache.redis.delete(receipts._key("receipt", binding["user_id"], binding["session_id"], worker.request_id))
    with voice.bound_voice_worker(worker):
        with pytest.raises((RequiredRecoveryOutputError, ValueError)):
            await service.create_embeds_from_skill_results(
                app_id="web", skill_id="search", results=search_results,
                chat_id=binding["chat_id"], message_id=binding["assistant_message_id"],
                user_id=binding["user_id"], user_id_hash=binding["user_hash"],
                user_vault_key_id="owner-vault", task_id=worker.task_id)
    assert publish.await_count == 3  # Revoked receipt cannot publish another child.


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["owner", "task", "plaintext", "header", "receipt", "chat_owner"])
async def test_worker_rejects_cross_owner_tampered_or_unreceipted_jobs(monkeypatch, mutation):
    env, _, _ = await dispatch_images(monkeypatch)
    cache, directus, encryption, binding, _, _, _, calls = env
    call = calls[0]
    kwargs, headers = dict(call["kwargs"]), dict(call["headers"])
    task_name = call["name"]
    if mutation == "owner":
        kwargs["user_id"] = "other-owner"
    elif mutation == "task":
        task_name = "apps.audio.tasks.skill_speak"
    elif mutation == "plaintext":
        kwargs["arguments"] = {"prompt": "injected"}
    elif mutation == "header":
        headers[voice.VOICE_TASK_HEADER] = {"version": True, "task_id": call["task_id"]}
    elif mutation == "receipt":
        await cache.redis.delete(receipts._key("receipt", binding["user_id"], binding["session_id"],
                                             f"voice-async:{call['task_id']}"))
    elif mutation == "chat_owner":
        directus.chat.get_chat_metadata.return_value = {"hashed_user_id": "another-owner"}
    with pytest.raises((RequiredRecoveryOutputError, ValueError)):
        await voice.open_voice_task(task_name=task_name, task_id=call["task_id"], args=(),
            kwargs=kwargs, headers=headers, cache_service=cache, directus_service=directus,
            encryption_service=encryption)


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_explicit_voice_authority_never_borrows_legacy_context(monkeypatch):
    env = await setup(monkeypatch)
    cache, directus, encryption, binding, _, service, producer, calls = env
    async with voice.voice_async_output_context(binding=binding, request_id="not-admitted",
            cache_service=cache, directus_service=directus, encryption_service=encryption,
            embed_service=service):
        with pytest.raises(RequiredRecoveryOutputError):
            await celery_helpers.execute_skill_via_celery("images", "generate",
                dict(user_id=binding["user_id"], chat_id=binding["chat_id"],
                     message_id=binding["assistant_message_id"], embed_id=str(uuid.uuid4())), producer)
    assert calls == []
    assert voice.active_voice_output_context.get() is None


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_voice_completion_updates_embed_without_ordinary_text_continuation(monkeypatch):
    from backend.apps.ai.tasks import async_skill_continuation as continuation
    env, _, _ = await dispatch_images(monkeypatch)
    cache, directus, encryption, _, _, _, _, calls = env
    call = calls[0]
    _, context = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    ordinary_read = AsyncMock(side_effect=AssertionError("Voice must not read ordinary AI continuation context"))
    with voice.bound_voice_worker(context):
        assert EmbedService._finished_recovery_required()
        assert await continuation.dispatch_async_skill_continuation(
            cache_service=SimpleNamespace(get=ordinary_read), async_task_id=call["task_id"],
            completed_results=[{"embed_id": context.embed_id, "status": "finished"}]) is None
        await voice.require_voice_publication(context=context, cache_service=cache,
            directus_service=directus, encryption_service=encryption, owner_hash=context.binding["user_hash"])
    assert not EmbedService._finished_recovery_required()
    ordinary_read.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("cache_miss", [False, True])
async def test_retry_after_finished_output_cannot_repeat_provider_work(monkeypatch, cache_miss):
    env, _, _ = await dispatch_images(monkeypatch)
    cache, directus, encryption, binding, _, _, _, calls = env
    call = calls[0]
    _, context = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    finished = json.loads(await cache.redis.get(f"embed:{context.embed_id}"))
    finished["status"] = "finished"
    if cache_miss:
        await cache.redis.delete(f"embed:{context.embed_id}")
        directus.embed.get_sync_embed_by_id.return_value = finished
    else:
        await cache.redis.set(f"embed:{context.embed_id}", json.dumps(finished))
    with pytest.raises(RequiredRecoveryOutputError, match="canonical completed"):
        await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
            args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
            directus_service=directus, encryption_service=encryption)
    assert directus.embed.get_sync_embed_by_id.await_count == int(cache_miss)


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["placeholder", "sealed_task"])
async def test_predispatch_failures_release_child_admission_capacity(monkeypatch, failure):
    cache, directus, encryption, binding, request_id, service, producer, calls = await setup(monkeypatch)
    task_id = str(uuid.uuid4())
    if failure == "placeholder":
        monkeypatch.setattr(service, "create_processing_embed_placeholder", AsyncMock(return_value=None))
    else:
        real_set = cache.redis.set
        async def set_value(key, *args, **kwargs):
            if key == receipts._key("task", binding["user_id"], task_id):
                raise ConnectionError("isolated task storage outage")
            return await real_set(key, *args, **kwargs)
        monkeypatch.setattr(cache.redis, "set", set_value)
    async with voice.voice_async_output_context(binding=binding, request_id=request_id,
            cache_service=cache, directus_service=directus, encryption_service=encryption,
            embed_service=service):
        with pytest.raises((RequiredRecoveryOutputError, ConnectionError)):
            await voice.dispatch_voice_embed_task(producer, task_name="apps.images.tasks.skill_generate",
                queue="app_images", task_uuid=task_id, kwargs=dict(app_id="images", skill_id="generate",
                    arguments=dict(user_id=binding["user_id"], chat_id=binding["chat_id"],
                        message_id=binding["assistant_message_id"], embed_id=str(uuid.uuid4()))))
    assert calls == []
    assert not await cache.redis.exists(receipts._key("permit", binding["user_id"], binding["session_id"],
                                                    f"voice-async:{task_id}"))
    assert await cache.redis.zcard(receipts._key("slots", binding["user_id"], binding["session_id"])) == 1


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["user_id", "chat_id", "message_id", "embed_id"])
async def test_actual_output_identity_is_fenced_before_websocket_publication(monkeypatch, field):
    env, _, _ = await dispatch_images(monkeypatch)
    cache, directus, encryption, binding, _, service, _, calls = env
    call = calls[0]
    _, context = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    output = dict(embed_id=context.embed_id, embed_type="image", content_toon="private",
        chat_id=binding["chat_id"], message_id=binding["assistant_message_id"],
        user_id=binding["user_id"], user_id_hash=binding["user_hash"], status="finished")
    output[field] = str(uuid.uuid4())
    with voice.bound_voice_worker(context):
        with pytest.raises(RequiredRecoveryOutputError, match="output identity"):
            await service.send_embed_data_to_client(**output)


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_existing_remotion_skill_keeps_actual_worker_signature_and_vault_field(monkeypatch):
    from backend.apps.videos.skills.create_skill import CreateSkill
    from backend.apps.videos.tasks.render_remotion_task import render_remotion_task
    cache, directus, encryption, binding, request_id, service, producer, calls = await setup(monkeypatch)
    skill = CreateSkill(app=SimpleNamespace(), app_id="videos", skill_id="create",
        skill_name="create", skill_description="create", celery_producer=producer)
    skill._current_chat_id, skill._current_message_id = binding["chat_id"], binding["assistant_message_id"]
    async with voice.voice_async_output_context(binding=binding, request_id=request_id,
            cache_service=cache, directus_service=directus, encryption_service=encryption,
            embed_service=service) as state:
        result = await skill.execute(source="export const Scene = () => <div>Private title</div>",
            filename="demo.mp4", user_id=binding["user_id"], user_vault_key_id="untrusted-key")
    assert state.dispatched and result["status"] == "rendering"
    call = calls[0]
    invocation, context = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    inspect.signature(render_remotion_task.run).bind(**invocation)
    assert set(invocation) == {"arguments"}
    assert invocation["arguments"]["vault_key_id"] == "owner-vault"
    assert context.embed_id == result["embed_id"]
    assert "Private title" not in json.dumps(call)
    output = json.loads(await cache.redis.get(f"embed:{context.embed_id}"))
    assert output["status"] == "processing"


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_individual_job_cancellation_fences_paid_work_while_speech_cancel_does_not(monkeypatch):
    from backend.apps.ai.processing.voice_call_broker import transport_key
    env, _, _ = await dispatch_images(monkeypatch)
    cache, directus, encryption, binding, _, _, _, calls = env
    call = calls[0]
    await cache.redis.set(transport_key(binding["operation_id"], "cancel"), "cancelled")
    await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"], args=(),
        kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    await cache.redis.set(f"cancelled_skill:{call['task_id']}", "cancelled")
    with pytest.raises(RequiredRecoveryOutputError, match="individually cancelled"):
        await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"], args=(),
            kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
            directus_service=directus, encryption_service=encryption)


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_cancellation_prevents_new_subdispatch_and_reservation(monkeypatch):
    from backend.apps.ai.processing.voice_call_broker import transport_key
    cache, directus, encryption, binding, request_id, service, producer, calls = await setup(monkeypatch)
    await cache.redis.set(transport_key(binding["operation_id"], "cancel"), "cancelled")
    async with voice.voice_async_output_context(binding=binding, request_id=request_id,
            cache_service=cache, directus_service=directus, encryption_service=encryption,
            embed_service=service):
        with pytest.raises(asyncio.CancelledError):
            await voice.dispatch_voice_embed_task(producer, task_name="apps.images.tasks.skill_generate",
                queue="app_images", kwargs=dict(app_id="images", skill_id="generate", arguments=dict(
                    user_id=binding["user_id"], chat_id=binding["chat_id"],
                    message_id=binding["assistant_message_id"], embed_id=str(uuid.uuid4()))))
    assert calls == []
    assert await cache.redis.zcard(receipts._key("slots", binding["user_id"], binding["session_id"])) == 1


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_worker_body_and_retries_keep_original_opaque_request(monkeypatch):
    from backend.core.api.app.tasks.base_task import DedupedTask
    from celery.exceptions import Retry
    from backend.apps.images.tasks.generate_task import generate_image_task
    env, _, _ = await dispatch_images(monkeypatch)
    cache, directus, encryption, _, _, _, _, calls = env
    call = calls[0]
    invocation, context = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    inspect.signature(generate_image_task.run).bind(**invocation)
    provider = Mock(return_value={"status": "finished", "private_prompt": "private"})
    class Worker(DedupedTask):
        name = "apps.images.tasks.skill_generate"
        def run(self, app_id, skill_id, arguments):
            assert self.request.kwargs == call["kwargs"]
            return provider(arguments)
    def check_worker():
        Worker.bind(generate_image_task.app)
        task = Worker()
        task.push_request(id=call["task_id"], args=(), kwargs=call["kwargs"], headers=call["headers"])
        monkeypatch.setattr(task, "_open_voice_invocation", AsyncMock(return_value=(invocation, context)))
        try:
            result = task._call_with_output_producer((), call["kwargs"])
            assert result == {"status": "finished", "embed_id": context.embed_id, "task_id": context.task_id}
            signature = task.signature_from_request()
            assert signature.kwargs == call["kwargs"]
            provider.side_effect = Retry(exc=RuntimeError("private SDK body"), when=1, sig=signature)
            with pytest.raises(Retry) as retried:
                task._call_with_output_producer((), call["kwargs"])
            assert retried.value.sig.kwargs == call["kwargs"]
            assert "private SDK body" not in str(retried.value)
        finally:
            task.pop_request()
    await asyncio.to_thread(check_worker)


# contract-test: supporting surface=rest_api assertions=video-call.chat.skill-integration,video-call.privacy
@pytest.mark.asyncio
async def test_actual_audio_skill_uses_shared_music_queue_and_worker_signature(monkeypatch):
    from backend.apps.audio.skills.generate_skill import GenerateSkill as AudioGenerateSkill, AudioGenerateRequest
    from backend.apps.audio.tasks.generate_task import generate_audio_task
    cache, directus, encryption, binding, request_id, service, producer, calls = await setup(monkeypatch)
    skill = AudioGenerateSkill(app=SimpleNamespace(), app_id="audio", skill_id="generate",
        skill_name="generate", skill_description="generate", celery_producer=producer)
    skill._current_chat_id, skill._current_message_id = binding["chat_id"], binding["assistant_message_id"]
    async with voice.voice_async_output_context(binding=binding, request_id=request_id,
            cache_service=cache, directus_service=directus, encryption_service=encryption,
            embed_service=service):
        result = await skill.execute(AudioGenerateRequest(requests=[{"prompt": "Soft private rain"}]),
            user_id=binding["user_id"])
    assert result["status"] == "processing"
    call = calls[0]
    assert call["queue"] == "app_music"
    invocation, _ = await voice.open_voice_task(task_name=call["name"], task_id=call["task_id"],
        args=(), kwargs=call["kwargs"], headers=call["headers"], cache_service=cache,
        directus_service=directus, encryption_service=encryption)
    inspect.signature(generate_audio_task.run).bind(**invocation)
    assert invocation["arguments"]["prompt"] == "Soft private rain"
    assert "Soft private rain" not in json.dumps(call)
