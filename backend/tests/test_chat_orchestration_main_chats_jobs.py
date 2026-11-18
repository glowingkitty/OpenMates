"""Chat orchestration jobs: claim exclusivity, expiry, re-offer, sealed payloads, link validation, user_wrote.

Plan: docs/plans/chat-orchestration-main-chats/plan.yml (T-PYTEST, job part)
Run: python3 -m pytest backend/tests/test_chat_orchestration_main_chats_jobs.py -q
"""

import asyncio
import json

import pytest

from backend.shared.python_utils import chat_orchestration_jobs as jobs

USER = "user-1"
CREATOR = "11111111-1111-4111-8111-111111111111"
SPAWNED = "22222222-2222-4222-8222-222222222222"
SECRET_TITLE = "Zebracorn quarterly plan"
SECRET_BRIEF = "Zebracorn-brief-marker"


class FakeRedis:
    def __init__(self, store, sets):
        self.store, self.sets = store, sets

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    async def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def expire(self, key, ttl):
        return True


class FakeCache:
    def __init__(self):
        self.store, self.sets, self.published = {}, {}, []
        self._redis = FakeRedis(self.store, self.sets)

    @property
    async def client(self):
        return self._redis

    async def get(self, key):
        value = self.store.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    async def set(self, key, value, ttl=None):
        self.store[key] = json.dumps(value) if isinstance(value, (dict, list, int)) else value
        return True

    async def delete(self, key):
        return self.store.pop(key, None) is not None

    async def publish_event(self, channel, event):
        self.published.append((channel, event))
        return True

    async def get_user_vault_key_id(self, user_id):
        return "vault-key-1"


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext, key_id):
        return "enc:" + plaintext[::-1], "v1"

    async def decrypt_with_user_key(self, ciphertext, key_id):
        return ciphertext[4:][::-1]


def _start_payload():
    return {"spawned_chat_id": SPAWNED, "creator_chat_id": CREATOR, "title": SECRET_TITLE,
            "brief": SECRET_BRIEF, "event_message_id": "evt-1"}


async def _start(cache):
    outcome = await jobs.enqueue_job(cache_service=cache, encryption_service=FakeEncryption(), user_id=USER,
                                     kind="start_chat", payload=_start_payload())
    return outcome.job_id


# contract-test: supporting surface=rest_api assertions=chat-orchestration.privacy.device-executed
def test_payload_is_vault_encrypted_not_plaintext_in_redis():
    cache = FakeCache()
    job_id = asyncio.run(_start(cache))
    raw = json.dumps(cache.store) + json.dumps(cache.published)
    assert SECRET_TITLE not in raw and SECRET_BRIEF not in raw
    offer = asyncio.run(jobs.build_offer(cache_service=cache, encryption_service=FakeEncryption(),
                                         user_id=USER, job_id=job_id))
    assert offer["payload"]["brief"] == SECRET_BRIEF and offer["kind"] == "start_chat"
    assert cache.published[0][1]["type"] == "chat_orchestration_job_available"


# contract-test: supporting surface=rest_api assertions=chat-orchestration.privacy.device-executed
def test_claim_is_exclusive_and_result_only_from_claimant():
    async def run():
        cache, enc = FakeCache(), FakeEncryption()
        job_id = await _start(cache)
        assert await jobs.claim_job(cache_service=cache, user_id=USER, device_hash="a", job_id=job_id) == (True, "granted")
        assert await jobs.claim_job(cache_service=cache, user_id=USER, device_hash="b", job_id=job_id) == (False, "already_claimed")
        other = await jobs.record_job_result(cache_service=cache, encryption_service=enc, user_id=USER,
                                             device_hash="b", job_id=job_id, ok=True)
        assert other == (False, "not_claimed_by_device")
        ok = await jobs.record_job_result(cache_service=cache, encryption_service=enc, user_id=USER,
                                          device_hash="a", job_id=job_id, ok=True)
        assert ok == (True, "accepted")
        state = await jobs.get_spawn_state(cache_service=cache, encryption_service=enc, user_id=USER,
                                           spawned_chat_id=SPAWNED)
        assert state["state"] == "working" and state["title"] == SECRET_TITLE
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chat-orchestration.privacy.device-executed
def test_unclaimed_read_job_expires_with_device_offline_and_late_claim_fails():
    async def run():
        cache, enc = FakeCache(), FakeEncryption()
        outcome = await jobs.enqueue_job(cache_service=cache, encryption_service=enc, user_id=USER, kind="read_chat",
                                         payload={"spawned_chat_id": SPAWNED, "creator_chat_id": CREATOR, "limit": 5},
                                         wait_claim_s=0.05)
        assert (outcome.state, outcome.error_code) == ("expired", "device_offline")
        late = await jobs.claim_job(cache_service=cache, user_id=USER, device_hash="a", job_id=outcome.job_id)
        assert late == (False, "job_expired")
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chat-orchestration.privacy.device-executed
def test_unclaimed_start_job_stays_pending_and_is_reoffered():
    async def run():
        cache, enc = FakeCache(), FakeEncryption()
        outcome = await jobs.enqueue_job(cache_service=cache, encryption_service=enc, user_id=USER, kind="start_chat",
                                         payload=_start_payload(), wait_claim_s=0.05)
        assert outcome.state == "pending"
        offers = await jobs.list_pending_offers(cache_service=cache, encryption_service=enc, user_id=USER)
        assert [offer["job_id"] for offer in offers] == [outcome.job_id]
        await jobs.claim_job(cache_service=cache, user_id=USER, device_hash="a", job_id=outcome.job_id)
        assert await jobs.list_pending_offers(cache_service=cache, encryption_service=enc, user_id=USER) == []
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chat-orchestration.privacy.device-executed,chat-orchestration.skills.list-read-send
def test_read_job_result_round_trip_is_sealed():
    async def run():
        cache, enc = FakeCache(), FakeEncryption()

        async def device():
            while not cache.published:
                await asyncio.sleep(0.01)
            job_id = cache.published[0][1]["job_id"]
            await jobs.claim_job(cache_service=cache, user_id=USER, device_hash="a", job_id=job_id)
            await jobs.record_job_result(cache_service=cache, encryption_service=enc, user_id=USER, device_hash="a",
                                         job_id=job_id, ok=True,
                                         result={"messages": [{"role": "user", "content": "Zebracorn-read"}]})
        task = asyncio.create_task(device())
        outcome = await jobs.enqueue_job(cache_service=cache, encryption_service=enc, user_id=USER, kind="read_chat",
                                         payload={"spawned_chat_id": SPAWNED, "creator_chat_id": CREATOR, "limit": 5},
                                         wait_claim_s=2, wait_result_s=2)
        await task
        assert outcome.state == "done" and outcome.result["messages"][0]["content"] == "Zebracorn-read"
        assert "Zebracorn-read" not in json.dumps(cache.store)
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chat-orchestration.spawn.main-chat-is-normal
def test_metadata_link_validation_rejects_mismatched_job():
    async def run():
        cache = FakeCache()
        job_id = await _start(cache)
        ok = dict(cache_service=cache, user_id=USER, chat_id=SPAWNED, creator_chat_id=CREATOR, job_id=job_id)
        assert await jobs.verified_creator_link(**ok)
        assert not await jobs.verified_creator_link(**{**ok, "chat_id": "other-chat"})
        assert not await jobs.verified_creator_link(**{**ok, "creator_chat_id": "other-creator"})
        assert not await jobs.verified_creator_link(**{**ok, "user_id": "user-2"})
        assert not await jobs.verified_creator_link(**{**ok, "job_id": "missing"})
        read = await jobs.enqueue_job(cache_service=cache, encryption_service=FakeEncryption(), user_id=USER,
                                      kind="read_chat", payload={"spawned_chat_id": SPAWNED, "creator_chat_id": CREATOR})
        assert not await jobs.verified_creator_link(**{**ok, "job_id": read.job_id})
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chat-orchestration.user-awareness.no-talking-over
def test_user_typed_message_emits_user_wrote_and_guard_creator_sent_does_not():
    async def run():
        cache, enc = FakeCache(), FakeEncryption()
        start_id = await _start(cache)
        await jobs.claim_job(cache_service=cache, user_id=USER, device_hash="a", job_id=start_id)
        common = dict(cache_service=cache, encryption_service=enc, user_id=USER, chat_id=SPAWNED)
        assert await jobs.classify_chat_message(**common, message_id="m-1", job_id=start_id) == CREATOR
        assert not await jobs.is_user_active(cache_service=cache, spawned_chat_id=SPAWNED)
        before = len(cache.published)
        assert await jobs.classify_chat_message(**common, message_id="m-2", job_id=None) == CREATOR
        assert await jobs.is_user_active(cache_service=cache, spawned_chat_id=SPAWNED)
        assert len(cache.published) == before + 1
        pending = await jobs.list_pending_offers(cache_service=cache, encryption_service=enc, user_id=USER)
        wrote = [o for o in pending if o["payload"].get("action") == "user_wrote"]
        assert wrote and wrote[0]["payload"]["event_message_id"] == jobs.event_message_id(CREATOR, SPAWNED, "user_wrote", "m-2")
        assert wrote[0]["payload"]["title"] == SECRET_TITLE
        unlinked = await jobs.classify_chat_message(**{**common, "chat_id": "plain-chat"}, message_id="m-3", job_id=None)
        assert unlinked is None
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chat-orchestration.user-awareness.no-talking-over
def test_client_job_id_is_read_from_the_message_payload_the_web_client_sends():
    """The brief arrives with orchestration_job_id inside ``message``; reading only the envelope
    classified every brief as user-typed (dev proof run 8)."""
    message = {"message_id": "m-1", "orchestration_job_id": "job-1"}
    assert jobs.client_orchestration_job_id({"chat_id": SPAWNED, "message": message}, message) == "job-1"
    assert jobs.client_orchestration_job_id({"orchestration_job_id": "job-2"}, {"message_id": "m"}) == "job-2"
    assert jobs.client_orchestration_job_id({}, {"orchestration_job_id": ""}) is None
    assert jobs.client_orchestration_job_id(None, None) is None


# contract-test: supporting surface=rest_api assertions=chat-orchestration.report.creator-skill,chat-orchestration.status.automatic
def test_api_ask_request_schema_keeps_the_creator_link_for_the_ai_task():
    """The API request schema must carry creator_chat_id to the AI task; without the field
    pydantic dropped it and spawned chats got no report skill context or finished event."""
    from backend.apps.ai.skills.ask_skill import AskSkillRequest as AiAskSkillRequest
    from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest as ApiAskSkillRequest

    assert "creator_chat_id" in ApiAskSkillRequest.model_fields
    assert "creator_chat_id" in AiAskSkillRequest.model_fields
    orchestration_fields = {"parent_id", "is_sub_chat", "creator_chat_id", "budget_limit", "budget_spent"}
    assert orchestration_fields <= set(ApiAskSkillRequest.model_fields) & set(AiAskSkillRequest.model_fields)


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.creator-system-events
def test_event_message_id_is_deterministic_and_error_codes_validated():
    assert jobs.event_message_id("c", "s", "report", "x") == jobs.event_message_id("c", "s", "report", "x")
    assert jobs.event_message_id("c", "s", "report", "x") != jobs.event_message_id("c", "s", "report", "y")
    with pytest.raises(ValueError):
        jobs.OrchestrationError("not-a-code")
    assert jobs.OrchestrationError("device_offline").code == "device_offline"
