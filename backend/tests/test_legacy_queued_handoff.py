"""Bounded epoch-0 queue handoff checks without broker, provider, or Redis service."""

import asyncio
import hashlib
import json
import base64
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from backend.apps.ai.tasks.ask_skill_task import (
    _legacy_queued_batch_proof,
    _start_recovery_queued_follower,
    _validated_recovery_queued_member,
    _validated_queued_messages,
    _verify_legacy_batch_proof,
    resume_legacy_queued_handoff,
)
from backend.apps.ai.tasks import ask_skill_task
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.skills.ask_skill import AskSkill
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError


class _AtomicLock:
    def __init__(self, redis, name):
        self.redis = redis
        self.name = name
        self.local = SimpleNamespace(token=b"queue-admission-token")
        self.mutex = redis.locks.setdefault(name, asyncio.Lock())

    async def __aenter__(self):
        await self.mutex.acquire()
        self.redis.strings[self.name] = self.local.token
        return self

    async def __aexit__(self, *_):
        if await self.owned():
            self.redis.strings.pop(self.name, None)
        self.mutex.release()

    async def owned(self):
        return self.redis.strings.get(self.name) == self.local.token

    async def extend(self, *_args, **_kwargs):
        return await self.owned()


class _AtomicRedis:
    def __init__(self):
        self.lists = {}
        self.strings = {}
        self.hashes = {}
        self.zsets = {}
        self.locks = {}

    async def eval(self, script, key_count, *args):
        keys, values = args[:key_count], args[key_count:]
        if script == ChatCacheMixin._APPEND_QUEUED_MESSAGE_LUA:
            if values[2] and self.strings.get(keys[3]) != values[2]:
                return -1
            self.lists.setdefault(keys[0], []).append(values[0])
            return len(self.lists[keys[0]])
        if script == ChatCacheMixin._LEASE_QUEUED_PREFIX_LUA:
            queue, lease, edit_lock, edit_pause = keys
            if edit_pause in self.strings:
                return ["edit_paused"]
            if edit_lock in self.strings:
                return ["edit_busy"]
            existing = self.strings.get(lease)
            if existing:
                token, count = existing.rsplit(":", 1)
                count = int(count)
            else:
                prefix = self.lists.get(queue, [])[:int(values[0])]
                count = 0
                size = 0
                first_scope = None
                for item in prefix:
                    row = json.loads(item)
                    if count and (row.get("recovery_task_id")
                                  or json.loads(prefix[0]).get("recovery_task_id")):
                        break
                    scope = tuple(row.get(field) for field in (
                        "chat_id", "user_id", "user_id_hash", "is_incognito",
                        "is_external", "is_anonymous", "team_id", "team_id_hash",
                        "team_workspace_type", "team_object_id_hash",
                    ))
                    if first_scope is not None and scope != first_scope:
                        break
                    first_scope = scope
                    size += len(item.encode())
                    if size > int(values[3]):
                        if not count:
                            raise ValueError("oversized_queued_message")
                        break
                    count += 1
                    if row.get("recovery_task_id"):
                        break
                if not count:
                    return []
                token = values[2]
                self.strings[lease] = f"{token}:{count}"
            return [token, str(count), *self.lists[queue][:count]]
        if script == ChatCacheMixin._ACK_QUEUED_PREFIX_LUA:
            queue, lease, receipt, paused = keys
            token, count = values[:2]
            count = int(count)
            def clear_paused():
                record = self.strings.get(paused)
                if record and json.loads(record)["lease_token"] == token:
                    self.strings.pop(paused)
            if receipt in self.strings:
                clear_paused()
                return 1
            if self.strings.get(lease) != f"{token}:{count}":
                return 0
            if self.lists.get(queue, [])[:count] != list(values[2:]):
                return 0
            self.lists[queue] = self.lists[queue][count:]
            del self.strings[lease]
            self.strings[receipt] = "1"
            clear_paused()
            return 1
        if script == ChatCacheMixin._TRANSFER_ACTIVE_TASK_LUA:
            old, old_reverse, new_reverse = keys
            if self.strings.get(old) != values[0]:
                return 0
            self.strings[old] = values[1]
            self.strings.pop(old_reverse, None)
            self.strings[new_reverse] = values[3]
            return 1
        if script == ChatCacheMixin._ACTIVATE_COMPLETED_FOLLOWERS_LUA:
            active, old_reverse, new_reverse, paused, bytes_key, paused_bytes_key, lock_key = keys
            if self.strings.get(lock_key) != values[9]:
                return 0
            active_value = self.strings.get(active)
            if ((active_value != values[0] and not (values[8] == "1" and active_value is None))
                    or paused in self.strings):
                return 0
            self.strings[paused] = values[3]
            self.strings[active] = values[1]
            self.strings.pop(old_reverse, None)
            self.strings[new_reverse] = values[4]
            self.hashes.setdefault(bytes_key, {})[values[4]] = str(values[5])
            self.hashes.setdefault(paused_bytes_key, {})[values[4]] = str(values[6])
            return 1
        if script == ChatCacheMixin._STORE_PAUSED_QUEUE_HANDOFF_LUA:
            paused, active, bytes_key, paused_bytes_key, lock_key = keys
            if self.strings.get(lock_key) != values[7]:
                return 0
            if self.strings.get(active) != values[0] or paused in self.strings:
                return 0
            self.strings[paused] = values[1]
            self.hashes.setdefault(bytes_key, {})[values[3]] = str(values[4])
            self.hashes.setdefault(paused_bytes_key, {})[values[3]] = str(values[5])
            return 1
        if script == ChatCacheMixin._STORE_COMPLETED_QUEUE_CONTEXT_LUA:
            completed, active, bytes_key, completion_bytes_key, lock_key = keys
            if self.strings.get(lock_key) != values[8]:
                return 0
            if self.strings.get(active) != values[0]:
                return 0
            if self.strings.get(completed) != (values[1] or None):
                return 0
            self.strings[completed] = values[2]
            self.hashes.setdefault(bytes_key, {})[values[3]] = str(values[4])
            self.hashes.setdefault(completion_bytes_key, {})[values[3]] = str(values[5])
            return 1
        if script == ChatCacheMixin._AI_LRU_ADMIT_LUA:
            if self.strings.get(keys[0]) != values[0]:
                return 0
            for index, chat_id in enumerate(json.loads(values[4])):
                for key in keys[5 + index * 3:8 + index * 3]:
                    await self.delete(key)
                for key in keys[2:5]:
                    await self.hdel(key, chat_id)
                await self.zrem(keys[1], chat_id)
            await self.zadd(keys[1], {values[2]: values[1]})
            return 1
        if script == ChatCacheMixin._CLEAR_ACTIVE_IF_MATCHES_LUA:
            active, reverse = keys
            if self.strings.get(active) != values[0]:
                return 0
            self.strings.pop(active)
            self.strings.pop(reverse, None)
            return 1
        if script == ChatCacheMixin._COMPLETE_ACTIVE_IF_QUEUE_EMPTY_LUA:
            active, reverse, queue = keys
            if self.strings.get(active) != values[0]:
                return 2
            if self.lists.get(queue):
                return 0
            self.strings.pop(active, None)
            self.strings.pop(reverse, None)
            return 1
        raise AssertionError("Unexpected Redis script")

    async def get(self, key):
        value = self.strings.get(key)
        return value.encode() if isinstance(value, str) else value

    async def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.strings:
            return False
        self.strings[key] = value
        return True

    async def delete(self, key):
        self.strings.pop(key, None)
        self.lists.pop(key, None)

    def lock(self, name, **kwargs):
        return _AtomicLock(self, name)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = str(value)

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)

    async def strlen(self, key):
        return len(self.strings.get(key, "").encode())

    async def exists(self, key):
        return key in self.strings or bool(self.lists.get(key))

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def zrange(self, key, start, end):
        return list(self.zsets.get(key, {}))

    async def zscore(self, key, member):
        return self.zsets.get(key, {}).get(member)

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrem(self, key, member):
        self.zsets.get(key, {}).pop(member, None)

    async def smembers(self, key):
        return set()

    async def expire(self, key, ttl):
        return True


class _Cache(ChatCacheMixin):
    TOP_N_MESSAGES_COUNT = 3
    CHAT_MESSAGES_TTL = 3600

    def __init__(self):
        self.redis = _AtomicRedis()

    @property
    def client(self):
        async def get():
            return self.redis
        return get()


class _FakeVault:
    def __init__(self, *, cache_service):
        pass

    async def encrypt_with_user_key(self, plaintext, key_id):
        return "vault:v1:" + base64.b64encode(plaintext.encode()).decode(), "v1"

    async def decrypt_with_user_key(self, ciphertext, key_id):
        return base64.b64decode(ciphertext.removeprefix("vault:v1:")).decode()


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_two_first_sends_claim_one_active_chat_before_dispatch():
    cache = _Cache()
    first, second = await asyncio.gather(
        cache.try_claim_active_ai_task("chat", "first-task"),
        cache.try_claim_active_ai_task("chat", "second-task"),
    )
    assert (first, second) in ((True, False), (False, True))
    winner = await cache.get_active_ai_task("chat")
    follower = "second-task" if winner == "first-task" else "first-task"
    assert winner != follower
    assert await cache.queue_message("chat", {"message_id": "follower"}, expected_active_task_id=winner)
    assert await cache.has_queued_messages("chat")
    assert not await cache.try_claim_active_ai_task("chat", "parallel-task")


@pytest.mark.asyncio
@pytest.mark.parametrize("append_during_empty_lease", [False, True])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_failed_active_task_transfers_accepted_follower_before_clearing_fence(
    monkeypatch, append_during_empty_lease,
):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    from backend.apps.ai.processing import queued_steering
    monkeypatch.setattr(queued_steering, "reconcile_queued_revision_quarantine", AsyncMock(return_value=True))
    cache = _Cache()
    cache.get_user_vault_key_id = AsyncMock(return_value="owner-vault-key")
    assert await cache.try_claim_active_ai_task("chat", "failed-task")
    if append_during_empty_lease:
        original_lease = cache.lease_queued_message_prefix
        first_lease = True

        async def raced_lease(chat_id, *, limit):
            nonlocal first_lease
            if first_lease:
                first_lease = False
                assert await cache.queue_message(
                    "chat", _member("follower", "Follow-up"),
                    expected_active_task_id="failed-task",
                )
                return None
            return await original_lease(chat_id, limit=limit)

        cache.lease_queued_message_prefix = raced_lease
    else:
        assert await cache.queue_message(
            "chat", _member("follower", "Follow-up"), expected_active_task_id="failed-task",
        )
    previous = AskSkillRequest(**_member("old", "Original"))
    previous.legacy_cutover_task_id = "first-admission"
    resumed = []

    async def fake_resume(**kwargs):
        resumed.append(kwargs)
        return await cache.get_active_ai_task("chat")

    monkeypatch.setattr(ask_skill_task, "resume_legacy_queued_handoff", fake_resume)
    assert await ask_skill_task._handoff_queued_after_task_failure(
        previous, {}, "failed-task", cache, SimpleNamespace(chat=SimpleNamespace()),
    )
    child_id = await cache.get_active_ai_task("chat")
    assert child_id != "failed-task"
    assert resumed[0]["actor_user_id"] == "owner"
    sealed = await cache.get_paused_queue_handoff("chat")
    assert sealed["vault_key_id"] == "owner-vault-key"
    opened = await ask_skill_task._open_legacy_queue_handoff(sealed, cache)
    assert opened["request_data_dict"]["message_id"] == "follower"
    assert opened["legacy_batch_proof"]["celery_task_id"] == child_id


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.access.scoped,chat-queued-followups.admission.synced
async def test_completed_team_batch_hands_next_follower_to_own_actor_and_vault_key(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    team_scope = {"team_id": "team", "team_id_hash": "team-hash"}
    prior_member = {**_member("b-turn", "B asks", user_id="member-b"), **team_scope}
    previous_cache = _Cache()
    await previous_cache.queue_message("chat", prior_member)
    prior_lease = await previous_cache.lease_queued_message_prefix("chat", limit=20)
    prior_request = AskSkillRequest(**prior_member)
    prior_proof = _legacy_queued_batch_proof(prior_request, prior_lease, ["b-turn"])
    prior_request.legacy_cutover_task_id = prior_proof["task_identity"]
    prior_task_id = prior_proof["celery_task_id"]

    cache = _Cache()
    await cache.try_claim_active_ai_task("chat", prior_task_id)
    assert await cache.queue_message(
        "chat", {**_member("c-turn", "C follows", user_id="member-c"), **team_scope},
        expected_active_task_id=prior_task_id,
    )
    context = {
        "task_id": prior_task_id, "chat_id": "chat", "owner_id": "member-b",
        "hashed_team_id": "team-hash", "assistant_response": "B answer",
        "request_data_dict": prior_request.model_dump(), "skill_config_dict": {},
        "legacy_batch_proof": prior_proof,
    }
    vault = _FakeVault(cache_service=cache)
    ciphertext, _ = await vault.encrypt_with_user_key(json.dumps(context), "member-b-key")
    cache.get_completed_queue_context = AsyncMock(return_value={
        "task_id": prior_task_id, "vault_key_id": "member-b-key", "ciphertext": ciphertext,
    })
    cache.get_user_vault_key_id = AsyncMock(return_value="member-c-key")
    captured = {}

    async def activate(user_id, chat_id, old_id, next_id, sealed, **kwargs):
        captured.update(user_id=user_id, next_id=next_id, sealed=sealed)
        return True

    cache.activate_completed_queue_followers = activate
    async def resume(**kwargs):
        captured["resume_actor"] = kwargs["actor_user_id"]
        return captured["next_id"]
    monkeypatch.setattr(ask_skill_task, "resume_legacy_queued_handoff", resume)
    directus = SimpleNamespace(team=SimpleNamespace(require_team_role=AsyncMock()))
    result = await ask_skill_task._advance_completed_legacy_followers(
        cache_service=cache, directus_service=directus,
        chat_id="chat", task_id=prior_task_id,
        actor_user_id="member-b", hashed_team_id="team-hash", completed_verified=True,
    )
    assert result == captured["next_id"]
    assert captured["user_id"] == captured["resume_actor"] == "member-c"
    assert captured["sealed"]["vault_key_id"] == "member-c-key"
    handoff = await ask_skill_task._open_legacy_queue_handoff(captured["sealed"], cache)
    assert handoff["owner_id"] == "member-c"
    assert handoff["request_data_dict"]["user_id"] == "member-c"
    assert [item["content"] for item in handoff["request_data_dict"]["message_history"]][-2:] == [
        "B answer", "C follows",
    ]


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_failed_incognito_task_terminalizes_volatile_followers():
    cache = _Cache()
    cache.publish_event = AsyncMock()
    assert await cache.try_claim_active_ai_task("chat", "volatile-task")
    follower = {**_member("incognito-follower", "Follow-up"), "is_incognito": True}
    assert await cache.queue_message(
        "chat", follower, expected_active_task_id="volatile-task",
    )
    request = AskSkillRequest(**{**_member("incognito-first", "First"), "is_incognito": True})
    assert await ask_skill_task._terminalize_volatile_followers_after_failure(
        request, "volatile-task", cache,
    )
    assert await cache.get_active_ai_task("chat") is None
    assert not await cache.has_queued_messages("chat")
    event = cache.publish_event.await_args.args[1]
    assert event["event_for_client"] == "queued_handoff_paused"
    assert event["payload"]["message_id"] == "incognito-follower"
    assert event["payload"]["retryable"] is False


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_provisional_claim_admission_failure_pauses_follower_before_release():
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _settle_failed_first_claim,
    )
    cache = _Cache()
    assert await cache.try_claim_active_ai_task("chat", "provisional-task")
    assert await cache.queue_message(
        "chat", _member("follower", "Follow-up"),
        expected_active_task_id="provisional-task",
    )
    pause = AsyncMock(return_value={"status": "paused", "messages_v": 2})
    manager = SimpleNamespace(
        broadcast_to_user=AsyncMock(), send_personal_message=AsyncMock(),
    )
    assert await _settle_failed_first_claim(
        cache_service=cache,
        directus_service=SimpleNamespace(chat=SimpleNamespace(mark_queued_message_paused=pause)),
        manager=manager, chat_id="chat", task_id="provisional-task",
        device_fingerprint_hash="device", known_not_dispatched=True,
    )
    pause.assert_awaited_once()
    assert await cache.get_active_ai_task("chat") is None
    assert not await cache.has_queued_messages("chat")
    event = manager.broadcast_to_user.await_args.args[0]
    assert event["type"] == "queued_handoff_paused"
    assert event["payload"]["message_id"] == "follower"
    assert event["payload"]["reason_code"] == "dispatch_failed"


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_ambiguous_broker_failure_keeps_provisional_claim_and_follower():
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        _settle_failed_first_claim,
    )
    cache = _Cache()
    assert await cache.try_claim_active_ai_task("chat", "provisional-task")
    assert await cache.queue_message(
        "chat", _member("follower", "Follow-up"),
        expected_active_task_id="provisional-task",
    )
    assert not await _settle_failed_first_claim(
        cache_service=cache, directus_service=SimpleNamespace(),
        manager=SimpleNamespace(), chat_id="chat", task_id="provisional-task",
        device_fingerprint_hash="device", known_not_dispatched=False,
    )
    assert await cache.get_active_ai_task("chat") == "provisional-task"
    assert await cache.has_queued_messages("chat")

def _member(message_id, content, *, user_id="owner", chat_id="chat"):
    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "user_id_hash": hashlib.sha256(user_id.encode()).hexdigest(),
        "is_incognito": False,
        "is_external": False,
        "is_anonymous": False,
        "team_id": None,
        "team_id_hash": None,
        "team_workspace_type": "chat",
        "team_object_id_hash": None,
        "message_history": [{"role": "user", "message_id": message_id,
                             "content": content, "created_at": 1}],
    }


def _request():
    return SimpleNamespace(**_member("old", "old content"),
                           legacy_cutover_task_id=None)


def _recovery_member(message_id, content):
    from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment

    member = _member(message_id, content)
    inference_request = {"message": {"message_id": message_id, "content": content}}
    member.update({
        "current_user_content": content,
        "recovery_task_id": f"task-{message_id}",
        "recovery_preflight_id": f"preflight-{message_id}",
        "recovery_outbox_id": f"outbox-{message_id}",
        "recovery_inference_request": inference_request,
        "recovery_inference_commitment": build_inference_commitment(inference_request),
    })
    return member


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_epoch_one_followers_dispatch_singleton_same_ids_with_verified_answer(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    from backend.apps.ai.processing import queued_steering
    monkeypatch.setattr(queued_steering, "reconcile_queued_revision_quarantine", AsyncMock(return_value=True))
    cache = _Cache()
    cache.get_user_vault_key_id = AsyncMock(return_value="owner-key")
    cache.mark_sync_message_processing = AsyncMock(return_value=True)
    receipt = {"status": "found", "job_id": "sealed-job", "preflight_id": "preflight-A",
               "sealed_payload_digest": "digest"}
    started = AsyncMock(return_value={"status": "started", "messages_v": 8})
    getter = AsyncMock(return_value=receipt)
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_sealed_job_receipt=getter, mark_queued_message_started=started,
    ))
    outbox_calls = []

    class Recovery:
        def __init__(self, service):
            pass

        async def execute(self, operation, payload):
            outbox_calls.append((operation, payload["inference_task_id"]))
            return {"state": "DISPATCHED"}

    broker_calls = []

    def send_task(*, task_id, kwargs, **unused):
        broker_calls.append((task_id, kwargs))
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(ask_skill_task.celery_config.app, "send_task", send_task)
    assert await cache.try_claim_active_ai_task("chat", "task-A")
    for prior_id, next_id, answer in (("A", "B", "Answer A"), ("B", "C", "Answer B")):
        assert await cache.queue_message("chat", _recovery_member(next_id, f"Question {next_id}"),
                                         expected_active_task_id=f"task-{prior_id}")
        lease = await cache.lease_queued_message_prefix("chat", limit=20)
        assert len(lease["messages"]) == 1
        prior = AskSkillRequest.model_validate(_recovery_member(prior_id, f"Question {prior_id}"))
        await _start_recovery_queued_follower(
            prior_request=prior, prior_task_id=f"task-{prior_id}",
            queued_lease=lease, assistant_response=answer,
            skill_config_dict={}, cache_service=cache, directus_service=directus,
        )
        assert broker_calls[-1][0] == f"task-{next_id}"
        history = broker_calls[-1][1]["request_data_dict"]["message_history"]
        assert history[-2]["content"] == answer
        assert history[-1]["message_id"] == next_id
        assert await cache.get_active_ai_task("chat") == f"task-{next_id}"
        receipt = {**receipt, "preflight_id": f"preflight-{next_id}"}
        getter.return_value = receipt
    assert [task for _, task in outbox_calls] == ["task-B", "task-C"]
    assert started.await_count == 2
    assert not await cache.has_queued_messages("chat")


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_epoch_one_queue_rejects_changed_committed_request(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    member = _recovery_member("B", "Question B")
    member["recovery_inference_request"]["message"]["content"] = "Swapped"
    with pytest.raises(RequiredRecoveryOutputError, match="changed"):
        _validated_recovery_queued_member({"messages": [member], "raw_messages": [json.dumps(member)]})


@pytest.mark.anyio
@pytest.mark.parametrize("failure_point", ["save_missing", "receipt_changed"])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_epoch_one_follower_stays_held_without_exact_predecessor_receipt(
    monkeypatch, failure_point,
):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    from backend.apps.ai.processing import queued_steering
    monkeypatch.setattr(queued_steering, "reconcile_queued_revision_quarantine", AsyncMock(return_value=True))
    cache = _Cache()
    cache.get_user_vault_key_id = AsyncMock(return_value="owner-key")
    assert await cache.try_claim_active_ai_task("chat", "task-A")
    assert await cache.queue_message("chat", _recovery_member("B", "Question B"),
                                     expected_active_task_id="task-A")
    lease = await cache.lease_queued_message_prefix("chat", limit=20)
    valid = {"status": "found", "job_id": "job-A", "preflight_id": "preflight-A",
             "sealed_payload_digest": "digest-A"}
    changed = {**valid, "job_id": "swapped-job"}
    getter = AsyncMock(side_effect=([{"status": "not_found"}]
                                    if failure_point == "save_missing" else [valid, changed]))
    started = AsyncMock(return_value={"status": "started", "messages_v": 8})
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_sealed_job_receipt=getter, mark_queued_message_started=started,
    ))
    broker = AsyncMock()
    monkeypatch.setattr(ask_skill_task.celery_config.app, "send_task", broker)
    with pytest.raises(RequiredRecoveryOutputError, match="output|receipt"):
        await _start_recovery_queued_follower(
            prior_request=AskSkillRequest.model_validate(_recovery_member("A", "Question A")),
            prior_task_id="task-A", queued_lease=lease,
            assistant_response="Answer A", skill_config_dict={},
            cache_service=cache, directus_service=directus,
        )
    assert await cache.has_queued_messages("chat")
    started.assert_not_awaited()
    broker.assert_not_called()


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
@pytest.mark.parametrize("transformed", [False, True])
async def test_epoch_one_worker_claim_closes_own_prefix_before_parent_ack(monkeypatch, transformed):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    cache = _Cache()
    assert await cache.try_claim_active_ai_task("chat", "task-B")
    member = _recovery_member("B", "Question B")
    if transformed:
        from backend.shared.python_utils.native_cache_history import canonical_content_sha256
        from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment
        marker = "<<<TEST_LIVE_MOCK:storage_capacity_v1>>>"
        member["message_history"][-1].update(content="Question B " + marker,
            native_cache_canonical_content_sha256=canonical_content_sha256("Question B"))
        member["recovery_inference_request"]["test_mock_marker"] = marker
        member["recovery_inference_commitment"] = build_inference_commitment(member["recovery_inference_request"])
    assert await cache.queue_message("chat", member, expected_active_task_id="task-B")
    request = AskSkillRequest.model_validate(member)
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_queued_revision_state=AsyncMock(return_value={
            "status": "found", "queue_dispatch_status": "processing",
            "recovery_task_id": "task-B", "recovery_preflight_id": "preflight-B",
            "inference_commitment": member["recovery_inference_commitment"],
        }),
    ))
    outbox = []

    class Recovery:
        def __init__(self, service):
            pass

        async def execute(self, operation, payload):
            outbox.append((operation, payload["inference_task_id"]))
            return {"state": "DISPATCHED"}

    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", Recovery)
    assert await ask_skill_task._ack_running_recovery_queue_prefix(
        request, "task-B", cache, directus,
    )
    assert outbox == [("mark_outbox_dispatched", "task-B")]
    assert not await cache.has_queued_messages("chat")


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_epoch_one_parent_accepts_verified_worker_ack_race():
    request = AskSkillRequest.model_validate(_recovery_member("B", "Question B"))
    durable = SimpleNamespace(chat=SimpleNamespace(
        get_queued_revision_state=AsyncMock(return_value={
            "status": "found", "queue_dispatch_status": "processing",
            "recovery_task_id": "task-B", "recovery_preflight_id": "preflight-B",
            "recovery_preflight_state": "RUNNING", "recovery_outbox_state": "DISPATCHED",
        }),
    ))
    assert await ask_skill_task._recovery_follower_already_running(durable, request)
    durable.chat.get_queued_revision_state.return_value["recovery_outbox_state"] = "HELD"
    assert not await ask_skill_task._recovery_follower_already_running(durable, request)


@pytest.mark.anyio
# contract-test: infrastructure
async def test_prefix_ack_preserves_concurrent_followers_and_retry_identity():
    cache = _Cache()
    for message_id in ("first", "second"):
        assert await cache.queue_message("chat", _member(message_id, message_id))
    lease = await cache.lease_queued_message_prefix("chat", limit=2)
    assert [item["message_id"] for item in lease["messages"]] == ["first", "second"]
    assert await cache.queue_message("chat", _member("later", "later"))
    retry = await cache.lease_queued_message_prefix("chat", limit=2)
    assert retry == lease
    queue_key = cache._get_chat_queue_key("chat")
    assert len(cache.redis.lists[queue_key]) == 3
    assert await cache.acknowledge_queued_message_prefix("chat", lease)
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[queue_key]] == ["later"]
    assert await cache.acknowledge_queued_message_prefix("chat", lease)


@pytest.mark.anyio
# contract-test: infrastructure
async def test_prefix_ack_rejects_wrong_bytes_and_old_task_cannot_clear_new_marker():
    cache = _Cache()
    await cache.queue_message("chat", _member("first", "content"))
    lease = await cache.lease_queued_message_prefix("chat")
    bad = {**lease, "raw_messages": [lease["raw_messages"][0] + " "]}
    assert not await cache.acknowledge_queued_message_prefix("chat", bad)
    assert len(cache.redis.lists[cache._get_chat_queue_key("chat")]) == 1
    cache.redis.strings[cache._get_active_task_key("chat")] = "old"
    assert await cache.transfer_active_ai_task("chat", "old", "new")
    assert not await cache.clear_active_ai_task_if_matches("chat", "old")
    assert cache.redis.strings[cache._get_active_task_key("chat")] == "new"
    assert await cache.complete_active_ai_task_if_queue_empty("chat", "old") == 2
    assert await cache.complete_active_ai_task_if_queue_empty("chat", "new") == 0
    assert await cache.acknowledge_queued_message_prefix("chat", lease)
    assert await cache.complete_active_ai_task_if_queue_empty("chat", "new") == 1
    assert cache._get_active_task_key("chat") not in cache.redis.strings


@pytest.mark.anyio
# contract-test: infrastructure
async def test_vault_completion_context_is_measured_and_rejected_over_budget(monkeypatch):
    cache = _Cache()
    cache.redis.strings[cache._get_active_task_key("chat")] = "task-one"
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "180")
    monkeypatch.setenv("AI_USER_CONTEXT_MAX_BYTES", "180")
    assert await cache.store_completed_queue_context(
        "owner", "chat", "task-one", "vault-key", "vault:v1:sealed",
    )
    stored = cache.redis.strings[cache._get_completed_queue_context_key("chat")]
    assert json.loads(stored)["ciphertext"] == "vault:v1:sealed"
    assert int(cache.redis.hashes[cache._get_ai_cache_bytes_key("owner")]["chat"]) == len(stored.encode())
    assert await cache._ai_context_bytes(cache.redis, "owner", "chat") == len(stored.encode())
    cache.redis.strings[cache._get_active_task_key("chat")] = "task-two"
    with pytest.raises(RuntimeError, match="budget"):
        await cache.store_completed_queue_context(
            "owner", "chat", "task-two", "vault-key", "vault:v1:" + "x" * 200,
        )
    assert cache.redis.strings[cache._get_completed_queue_context_key("chat")] == stored


@pytest.mark.anyio
# contract-test: infrastructure
async def test_vault_paused_handoff_refuses_unmeasured_extra_context(monkeypatch):
    cache = _Cache()
    cache.redis.strings[cache._get_active_task_key("chat")] = "old-task"
    monkeypatch.setenv("AI_CONTEXT_MAX_BYTES", "128")
    sealed = {
        "task_id": "new-task", "lease_token": "lease",
        "vault_key_id": "user-key", "ciphertext": "vault:v1:" + "x" * 200,
    }
    with pytest.raises(RuntimeError, match="Vault ciphertext"):
        await cache.store_paused_queue_handoff(
            "owner", "chat", "old-task", {**sealed, "request_data_dict": {"content": "secret"}},
        )
    with pytest.raises(RuntimeError, match="budget"):
        await cache.store_paused_queue_handoff("owner", "chat", "old-task", sealed)
    assert await cache.get_paused_queue_handoff("chat") is None
    assert await cache.get_active_ai_task("chat") == "old-task"


@pytest.mark.anyio
# contract-test: infrastructure
async def test_legacy_batch_proof_is_exact_and_mixed_scope_fails(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    cache = _Cache()
    await cache.queue_message("chat", _member("one", "one"))
    await cache.queue_message("chat", _member("two", "two"))
    lease = await cache.lease_queued_message_prefix("chat", limit=20)
    request = _request()
    ids, contents = _validated_queued_messages(request, lease)
    assert ids == ["one", "two"] and contents == ["one", "two"]
    proof = _legacy_queued_batch_proof(request, lease, ids)
    request.message_id = "one"
    request.legacy_cutover_task_id = proof["task_identity"]
    assert _verify_legacy_batch_proof(proof, request, proof["celery_task_id"]) == proof
    altered = {**proof, "members": [*proof["members"]]}
    altered["members"][1] = {**altered["members"][1], "payload_commitment": "0" * 64}
    with pytest.raises(RequiredRecoveryOutputError):
        _verify_legacy_batch_proof(altered, request, proof["celery_task_id"])
    mixed = {**lease, "messages": [lease["messages"][0], _member("two", "two", user_id="other")]}
    with pytest.raises(RequiredRecoveryOutputError):
        _validated_queued_messages(_request(), mixed)


@pytest.mark.anyio
# contract-test: infrastructure
async def test_broker_failure_keeps_exact_batch_ahead_of_fresh_input(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    cache = _Cache()
    cache.mark_sync_message_processing = AsyncMock(return_value=True)
    durable = SimpleNamespace(chat=SimpleNamespace(mark_queued_message_started=AsyncMock(
        return_value={"status": "started", "messages_v": 2},
    )))
    await cache.queue_message("chat", _member("first", "first"))
    lease = await cache.lease_queued_message_prefix("chat", limit=20)
    request = AskSkillRequest(**_member("first", "first"))
    proof = _legacy_queued_batch_proof(request, lease, ["first"])
    request.legacy_cutover_task_id = proof["task_identity"]
    request.root_user_message_id = "first"
    task_id = proof["celery_task_id"]
    handoff = {
        "task_id": task_id, "chat_id": "chat", "owner_id": "owner",
        "hashed_team_id": None, "request_data_dict": request.model_dump(),
        "skill_config_dict": {}, "legacy_batch_proof": proof,
        "lease": {"token": lease["token"], "raw_messages": lease["raw_messages"]},
    }
    cache.redis.strings[cache._get_active_task_key("chat")] = "old"
    sealed = await ask_skill_task._seal_legacy_queue_handoff(
        handoff, vault_key_id="test-user-key", cache_service=cache,
    )
    await cache.store_paused_queue_handoff("owner", "chat", "old", sealed)
    assert await cache.transfer_active_ai_task("chat", "old", task_id)

    calls = []

    class Recovery:
        def __init__(self, service):
            pass

        async def execute(self, operation, payload):
            calls.append((operation, payload["task_identity"]))
            return {
                "status": "PREPARED", "task_identity": proof["task_identity"],
                "execution_claimed": False,
            }

    broker_ids = []

    def send_task(*, task_id, **kwargs):
        broker_ids.append(task_id)
        if len(broker_ids) == 1:
            raise RuntimeError("broker unavailable")
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(ask_skill_task.celery_config.app, "send_task", send_task)
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=durable, chat_id="chat",
            actor_user_id="owner", hashed_team_id=None,
        )
    assert await cache.queue_message("chat", _member("fresh", "fresh"))
    assert await cache.get_active_ai_task("chat") == task_id
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["first", "fresh"]
    with pytest.raises(RequiredRecoveryOutputError, match="scope"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=durable, chat_id="chat",
            actor_user_id="other", hashed_team_id=None,
        )
    assert broker_ids == [task_id]
    resumed_id = await resume_legacy_queued_handoff(
        cache_service=cache, directus_service=durable, chat_id="chat",
        actor_user_id="owner", hashed_team_id=None,
    )
    assert resumed_id == task_id
    assert broker_ids == [task_id, task_id]
    assert [item[0] for item in calls] == ["prepare_legacy_batch", "prepare_legacy_batch"]
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["fresh"]
    assert await cache.get_paused_queue_handoff("chat") is None


@pytest.mark.anyio
@pytest.mark.parametrize("durable_status", ["CLAIMED", "COMPLETED"])
# contract-test: infrastructure
async def test_claimed_batch_reconciles_lost_prefix_ack_without_broker_replay(
    monkeypatch, durable_status,
):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setattr(ask_skill_task, "EncryptionService", _FakeVault)
    cache = _Cache()
    cache.mark_sync_message_processing = AsyncMock(return_value=True)
    durable = SimpleNamespace(chat=SimpleNamespace(mark_queued_message_started=AsyncMock(
        return_value={"status": "started", "messages_v": 2},
    )))
    await cache.queue_message("chat", _member("first", "first"))
    lease = await cache.lease_queued_message_prefix("chat", limit=20)
    request = AskSkillRequest(**_member("first", "first"))
    proof = _legacy_queued_batch_proof(request, lease, ["first"])
    request.legacy_cutover_task_id = proof["task_identity"]
    request.root_user_message_id = "first"
    task_id = proof["celery_task_id"]
    handoff = {
        "task_id": task_id, "chat_id": "chat", "owner_id": "owner",
        "hashed_team_id": None, "request_data_dict": request.model_dump(),
        "skill_config_dict": {}, "legacy_batch_proof": proof,
        "lease": {"token": lease["token"], "raw_messages": lease["raw_messages"]},
    }
    cache.redis.strings[cache._get_active_task_key("chat")] = task_id
    sealed = await ask_skill_task._seal_legacy_queue_handoff(
        handoff, vault_key_id="test-user-key", cache_service=cache,
    )
    await cache.store_paused_queue_handoff("owner", "chat", task_id, sealed)
    paused_bytes = cache.redis.strings[cache._get_paused_queue_handoff_key("chat")]
    assert "request_data_dict" not in paused_bytes
    assert "first assistant response" not in paused_bytes
    if durable_status == "COMPLETED":
        completion_plaintext = {
            "task_id": task_id, "chat_id": "chat", "owner_id": "owner",
            "hashed_team_id": None, "request_data_dict": request.model_dump(),
            "skill_config_dict": {}, "legacy_batch_proof": proof,
            "assistant_response": "first assistant response",
        }
        completion_ciphertext, _ = await _FakeVault(cache_service=cache).encrypt_with_user_key(
            json.dumps(completion_plaintext), "test-user-key",
        )
        await cache.store_completed_queue_context(
            "owner", "chat", task_id, "test-user-key", completion_ciphertext,
        )
        completion_bytes = cache.redis.strings[cache._get_completed_queue_context_key("chat")]
        assert "first assistant response" not in completion_bytes
        assert await cache._ai_context_bytes(cache.redis, "owner", "chat") == (
            len(paused_bytes.encode()) + len(completion_bytes.encode())
        )

    class Recovery:
        calls = 0

        def __init__(self, service):
            pass

        async def execute(self, operation, payload):
            assert operation == "prepare_legacy_batch"
            if payload != proof:
                assert durable_status == "COMPLETED"
                assert payload["first_message_id"] == "follower"
                return {
                    "task_identity": payload["task_identity"],
                    "status": "PREPARED", "execution_claimed": False,
                }
            Recovery.calls += 1
            if Recovery.calls == 1:
                return {
                    "task_identity": proof["task_identity"],
                    "status": "PREPARED", "execution_claimed": False,
                }
            return {
                "task_identity": proof["task_identity"],
                "status": durable_status, "execution_claimed": True,
                "idempotent": Recovery.calls > 2,
            }

    broker_ids = []
    broker_kwargs = []

    def send_task(*, task_id, **kwargs):
        broker_ids.append(task_id)
        broker_kwargs.append(kwargs)
        return SimpleNamespace(id=task_id)

    original_ack = cache.acknowledge_queued_message_prefix
    ack_calls = 0

    async def lost_ack(chat_id, queued_lease):
        nonlocal ack_calls
        ack_calls += 1
        if ack_calls == 1:
            return False
        return await original_ack(chat_id, queued_lease)

    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(ask_skill_task.celery_config.app, "send_task", send_task)
    monkeypatch.setattr(cache, "acknowledge_queued_message_prefix", lost_ack)
    with pytest.raises(RequiredRecoveryOutputError, match="prefix ACK failed"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=durable, chat_id="chat",
            actor_user_id="owner", hashed_team_id=None,
        )
    assert broker_ids == [task_id]
    await cache.queue_message("chat", _member("follower", "follower"))
    with pytest.raises(RequiredRecoveryOutputError, match="claim is unverified"):
        await resume_legacy_queued_handoff(
            cache_service=cache, directus_service=durable, chat_id="chat",
            actor_user_id="owner", hashed_team_id=None,
        )
    assert broker_ids == [task_id]
    assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["first", "follower"]
    if durable_status == "COMPLETED":
        original_activate = cache.activate_completed_queue_followers
        activation_calls = 0

        async def interrupted_activation(*args, **kwargs):
            nonlocal activation_calls
            activation_calls += 1
            if activation_calls == 1:
                raise RuntimeError("Redis transfer interrupted")
            return await original_activate(*args, **kwargs)

        monkeypatch.setattr(cache, "activate_completed_queue_followers", interrupted_activation)
        with pytest.raises(RuntimeError, match="transfer interrupted"):
            await resume_legacy_queued_handoff(
                cache_service=cache, directus_service=durable, chat_id="chat",
                actor_user_id="owner", hashed_team_id=None,
            )
        assert await cache.get_active_ai_task("chat") == task_id
        assert await cache.get_paused_queue_handoff("chat") is None
        assert broker_ids == [task_id]
        assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["follower"]
        # The old marker may expire before an authenticated retry. The durable
        # completed proof still allows exactly one atomic new follower owner.
        cache.redis.strings.pop(cache._get_active_task_key("chat"))
    resumed_id = await resume_legacy_queued_handoff(
        cache_service=cache, directus_service=durable, chat_id="chat",
        actor_user_id="owner", hashed_team_id=None,
    )
    assert Recovery.calls == (4 if durable_status == "COMPLETED" else 3)
    if durable_status == "COMPLETED":
        assert len(broker_ids) == 2 and broker_ids[0] == task_id
        assert broker_ids[1] != task_id
        assert resumed_id == broker_ids[1]
        next_request = broker_kwargs[1]["kwargs"]["request_data_dict"]
        assert next_request["message_id"] == "follower"
        assert any(
            item["role"] == "assistant" and item["content"] == "first assistant response"
            for item in next_request["message_history"]
        )
        assert cache.redis.lists[cache._get_chat_queue_key("chat")] == []
        assert await cache.get_active_ai_task("chat") == broker_ids[1]
    else:
        assert resumed_id == task_id
        assert broker_ids == [task_id]
        assert [json.loads(item)["message_id"] for item in cache.redis.lists[cache._get_chat_queue_key("chat")]] == ["follower"]
        assert await cache.get_active_ai_task("chat") == task_id
    assert await cache.get_paused_queue_handoff("chat") is None


@pytest.mark.anyio
# contract-test: infrastructure
async def test_ordinary_exact_broker_retry_reuses_binding_and_changed_config_holds(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    import backend.core.api.app.services.chat_recovery_service as recovery_module
    import backend.core.api.app.services.directus as directus_module

    task_id = hashlib.sha256(b"owner:chat:first").hexdigest()
    request = AskSkillRequest(**_member("first", "first"), legacy_cutover_task_id=task_id)
    skill = AskSkill.__new__(AskSkill)
    skill.parsed_default_config = None
    skill.celery_producer = object()
    skill.skill_name = "ask"
    bindings = []
    broker_ids = []

    class Directus:
        async def close(self):
            pass

    class Recovery:
        def __init__(self, service):
            pass

        async def execute(self, operation, data):
            assert operation == "bind_ordinary_legacy_dispatch"
            assert data["broker_task_id"] == task_id
            binding = data["dispatch_binding"]
            if bindings and binding != bindings[0]:
                raise ChatRecoveryProtocolError(409, "legacy_dispatch_binding_mismatch")
            bindings.append(binding)
            return {"bound": True, "idempotent": len(bindings) > 1,
                    "enqueue_allowed": True}

    def publish(*, task_id, **kwargs):
        broker_ids.append(task_id)
        if len(broker_ids) == 1:
            raise RuntimeError("broker unavailable")
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(directus_module, "DirectusService", Directus)
    monkeypatch.setattr(recovery_module, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(ask_skill_task.process_ai_skill_ask_task, "apply_async", publish)
    monkeypatch.setattr(ask_skill_task, "notify_chat_failure", AsyncMock())
    import backend.apps.ai.skills.ask_skill as ask_module
    monkeypatch.setattr(ask_module, "notify_chat_failure", AsyncMock())

    with pytest.raises(Exception, match="Failed to initiate AI processing"):
        await skill._handle_internal_request(request)
    response = await skill._handle_internal_request(request)
    assert response.task_id == task_id
    assert len(bindings) == 2 and bindings[0] == bindings[1]
    assert broker_ids == [task_id, task_id]
    skill.parsed_default_config = SimpleNamespace(model_dump=lambda: {"changed": True})
    with pytest.raises(ChatRecoveryProtocolError):
        await skill._handle_internal_request(request)
    assert broker_ids == [task_id, task_id]


@pytest.mark.parametrize("transformed", ["signed-marker", "resolved-embed"])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
def test_recovery_queue_accepts_server_transformed_history_bound_to_committed_raw_turn(monkeypatch, transformed):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    from backend.shared.python_utils.native_cache_history import canonical_content_sha256
    from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment
    raw = "Question B" if transformed == "signed-marker" else "Read embed_ref:fixture-document"
    member = _recovery_member("B", raw)
    latest = member["message_history"][-1]
    latest["native_cache_canonical_content_sha256"] = canonical_content_sha256(raw)
    if transformed == "signed-marker":
        marker = "<<<TEST_LIVE_MOCK:storage_capacity_v1>>>"
        member["recovery_inference_request"]["test_mock_marker"] = marker
        latest["content"] = raw + " " + marker
    else:
        latest["content"] = "Read authorized resolved document body"
    member["recovery_inference_commitment"] = build_inference_commitment(member["recovery_inference_request"])
    request = _validated_recovery_queued_member({"messages": [member], "raw_messages": [json.dumps(member)]})
    assert request.current_user_content == raw
    assert request.message_history[-1].content == latest["content"]



@pytest.mark.parametrize("mutation", ["plain-content", "digest", "missing-digest", "raw-content", "raw-and-history", "message-id", "marker"])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
def test_recovery_queue_transformed_history_rejects_changed_binding(monkeypatch, mutation):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    from backend.shared.python_utils.native_cache_history import canonical_content_sha256
    from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment
    member = _recovery_member("B", "Question B")
    marker = "<<<TEST_LIVE_MOCK:storage_capacity_v1>>>"
    latest = member["message_history"][-1]
    latest.update(content="Question B " + marker,
                  native_cache_canonical_content_sha256=canonical_content_sha256("Question B"))
    member["recovery_inference_request"]["test_mock_marker"] = marker
    member["recovery_inference_commitment"] = build_inference_commitment(member["recovery_inference_request"])
    if mutation == "plain-content":
        latest.update(content="different plaintext", native_cache_canonical_content_sha256=None)
    elif mutation == "digest":
        latest["native_cache_canonical_content_sha256"] = canonical_content_sha256("another turn")
    elif mutation == "missing-digest":
        latest.pop("native_cache_canonical_content_sha256")
    elif mutation == "raw-content":
        member["current_user_content"] = "swapped raw turn"
        latest["native_cache_canonical_content_sha256"] = canonical_content_sha256("swapped raw turn")
    elif mutation == "raw-and-history":
        member["current_user_content"] = "swapped raw turn"
        latest["content"] = "swapped raw turn"
    elif mutation == "message-id":
        latest["message_id"] = "other-turn"
    else:
        latest["content"] = "Question B <<<TEST_LIVE_MOCK:other_marker>>>"
    with pytest.raises(RequiredRecoveryOutputError, match="changed"):
        _validated_recovery_queued_member({"messages": [member], "raw_messages": [json.dumps(member)]})


@pytest.mark.anyio
@pytest.mark.parametrize("durable_commitment", [None, "stale-admitted-commitment"])
# contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced
async def test_worker_prefix_rejects_missing_or_changed_immutable_admission(monkeypatch, durable_commitment):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "queue-test-secret-which-is-at-least-32-bytes")
    cache = _Cache()
    assert await cache.try_claim_active_ai_task("chat", "task-B")
    member = _recovery_member("B", "Question B")
    assert await cache.queue_message("chat", member, expected_active_task_id="task-B")
    request = AskSkillRequest.model_validate(member)
    directus = SimpleNamespace(chat=SimpleNamespace(get_queued_revision_state=AsyncMock(return_value={
        "status": "found", "queue_dispatch_status": "processing", "recovery_task_id": "task-B",
        "recovery_preflight_id": "preflight-B", "inference_commitment": durable_commitment,
    })))
    recovery = AsyncMock()
    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", recovery)
    with pytest.raises(RequiredRecoveryOutputError, match="durable start receipt"):
        await ask_skill_task._ack_running_recovery_queue_prefix(request, "task-B", cache, directus)
    recovery.assert_not_called()
    assert await cache.has_queued_messages("chat")
