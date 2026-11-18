"""Automatic interpretation of creator events: debounce, busy chat, bound call, streak, voice delivery.

Run: python3 -m pytest backend/tests/test_chat_orchestration_interpretation.py -q
"""

import asyncio
import json
import time

import pytest

from backend.shared.python_utils import chat_orchestration_interpretation as interp
from backend.shared.python_utils import server_turn_dispatch

USER = "user-1"
CHAT = "11111111-1111-4111-8111-111111111111"


class FakeRedis:
    def __init__(self):
        self.store, self.hashes, self.zsets = {}, {}, {}

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zremrangebyscore(self, key, low, high):
        members = self.zsets.get(key, {})
        for member in [m for m, score in members.items() if low <= score <= high]:
            members.pop(member)

    async def zcard(self, key):
        return len(self.zsets.get(key, {}))

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)
        self.hashes.pop(key, None)

    async def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1

    async def expire(self, key, ttl):
        return True

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key, field):
        return 1 if self.hashes.get(key, {}).pop(field, None) is not None else 0

    async def hlen(self, key):
        return len(self.hashes.get(key, {}))


class FakeCache:
    def __init__(self, busy=False):
        self._redis, self.busy, self.claimed, self.values = FakeRedis(), busy, [], {}

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    @property
    async def client(self):
        return self._redis

    async def get_user_vault_key_id(self, user_id):
        return "vault-key-1"

    async def try_claim_active_ai_task(self, chat_id, task_id, ttl=600):
        if self.busy:
            return False
        self.claimed.append(task_id)
        return True

    async def get_active_ai_task(self, chat_id):
        return "busy-task" if self.busy else None

    async def clear_active_ai_task_if_matches(self, chat_id, task_id):
        return True

    async def get_ai_messages_history(self, user_id, chat_id):
        return []

    async def get_user_timezone(self, user_id):
        return None


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext, key_id):
        return "enc:" + plaintext[::-1], "v1"

    async def decrypt_with_user_key(self, ciphertext, key_id):
        return ciphertext[4:][::-1]


class Recorder:
    def __init__(self):
        self.applied, self.scheduled = [], []
        self.refuse = False


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(interp, "_schedule", lambda user_id, chat_id, countdown, elapsed:
                        rec.scheduled.append((countdown, elapsed)))


    async def admit_and_dispatch(*, cache_service, directus_service, request):
        # Durable admission + ai.ask dispatch are covered by test_server_turn_dispatch.py.
        if rec.refuse:
            raise server_turn_dispatch.ServerTurnNotAdmitted("server turn already admitted")
        rec.applied.append({"kwargs": {"request_data_dict": request}})
        return server_turn_dispatch.server_turn_identity(
            request["user_id"], request["chat_id"], request["message_id"])
    monkeypatch.setattr(server_turn_dispatch, "admit_and_dispatch_server_turn", admit_and_dispatch)
    return rec


def _event(action, n, created_at=None):
    return {"creator_chat_id": CHAT, "spawned_chat_id": f"spawn-{n}", "action": action,
            "event_message_id": f"evt-{action}-{n}", "title": "Research", "text": "Result body",
            "created_at": created_at or 1000 + n}


def _queue(cache, event):
    return asyncio.run(interp.queue_event(cache_service=cache, encryption_service=FakeEncryption(),
                                          user_id=USER, payload=event))


def _dispatch(cache, events, voice=None):
    return asyncio.run(interp.dispatch_interpretation(
        cache_service=cache, directus_service=None, encryption_service=FakeEncryption(),
        user_id=USER, chat_id=CHAT, events=events, voice_delivery=voice))


def _claim(cache):
    return asyncio.run(interp.claim_events(cache_service=cache, encryption_service=FakeEncryption(),
                                           user_id=USER, chat_id=CHAT))


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_started_and_user_wrote_are_ignored(recorder):
    cache = FakeCache()
    assert _queue(cache, _event("started", 1)) is False
    assert _queue(cache, _event("user_wrote", 2)) is False
    assert _claim(cache) == [] and recorder.scheduled == []


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_close_events_combine_into_one_turn_anchored_on_last(recorder):
    run_dispatcher = interp.run_dispatcher
    cache = FakeCache()
    assert _queue(cache, _event("report", 1)) and _queue(cache, _event("finished", 2))
    assert _queue(cache, _event("finished", 2)) is False  # deduped
    assert len(recorder.scheduled) == 1  # scheduled once
    cache._redis.store[interp._k("meta", USER, CHAT)] = json.dumps(
        {"first": time.time() - 20, "last": time.time() - 20})
    outcome = asyncio.run(run_dispatcher(USER, CHAT, 0, cache_service=cache, directus_service=None,
                                         encryption_service=FakeEncryption(), reschedule=lambda *a: None))
    assert outcome == "dispatched" and len(recorder.applied) == 1
    request = recorder.applied[0]["kwargs"]["request_data_dict"]
    assert request["message_id"] == "evt-finished-2" and request["chat_has_title"] is True
    last = request["message_history"][-1]
    assert last["role"] == "user" and last["content"].count("[Spawned chat event]") == 2
    assert "voice_mode" not in request


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_turn_identity_is_the_durable_admission_identity(recorder):
    cache = FakeCache()
    task_id = _dispatch(cache, [_event("report", 1), _event("finished", 2)])
    assert task_id == server_turn_dispatch.server_turn_identity(USER, CHAT, "evt-finished-2")


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_refused_admission_frees_the_chat_and_does_not_retry(recorder):
    cache = FakeCache()
    cleared = []

    async def clear(chat_id, task_id):
        cleared.append(task_id)
        return True
    cache.clear_active_ai_task_if_matches = clear
    recorder.refuse = True
    assert _dispatch(cache, [_event("report", 1)]) is None
    assert recorder.applied == [] and _claim(cache) == []
    assert cleared == cache.claimed and len(cleared) == 1


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_busy_chat_requeues_without_dispatch(recorder):
    cache = FakeCache(busy=True)
    events = [_event("report", 1)]
    assert _dispatch(cache, events) is None
    assert recorder.applied == []
    assert [e["event_message_id"] for e in _claim(cache)] == ["evt-report-1"]


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_bound_call_owns_dispatch(recorder):
    run_dispatcher = interp.run_dispatcher
    cache = FakeCache()
    _queue(cache, _event("report", 1))
    asyncio.run(interp.bind_call(cache_service=cache, user_id=USER, chat_id=CHAT, call_id="call-1", ttl_seconds=60))
    cache._redis.store[interp._k("meta", USER, CHAT)] = json.dumps({"first": 0, "last": 0})
    assert asyncio.run(interp.pending_due(cache_service=cache, user_id=USER, chat_id=CHAT)) is True
    outcome = asyncio.run(run_dispatcher(USER, CHAT, 0, cache_service=cache, directus_service=None,
                                         encryption_service=FakeEncryption(), reschedule=lambda *a: None))
    assert outcome == "stopped" and recorder.applied == []
    assert len(_claim(cache)) == 1  # still claimable by the call


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_streak_limit_then_user_message_resets(recorder):
    cache = FakeCache()
    for n in range(interp.MAX_AUTOMATIC_STREAK):
        assert _queue(cache, _event("report", n)) is True
        assert _dispatch(cache, _claim(cache)) is not None
    assert _queue(cache, _event("report", 99)) is False
    asyncio.run(interp.reset_streak(cache_service=cache, user_id=USER, chat_id=CHAT))
    assert _queue(cache, _event("report", 100)) is True


# contract-test: supporting surface=rest_api assertions=chat-orchestration.events.automatic-interpretation
def test_voice_delivery_is_merged(recorder):
    cache = FakeCache()
    voice = {"voice_mode": True, "voice_call_id": "call-1", "voice_turn_id": "evt-report-1",
             "voice_heard_boundary": None, "auto_speak_response": True, "ignored": 1}
    assert _dispatch(cache, [_event("report", 1)], voice) is not None
    request = recorder.applied[0]["kwargs"]["request_data_dict"]
    assert request["voice_mode"] is True and request["voice_call_id"] == "call-1"
    assert request["auto_speak_response"] is True and "ignored" not in request


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.loop-limits
def test_hourly_cap_stops_interpretation_even_with_user_input_between(recorder):
    cache = FakeCache()
    for n in range(interp.MAX_AUTOMATIC_PER_HOUR):
        assert _queue(cache, _event("report", n)) is True
        assert _dispatch(cache, _claim(cache)) is not None
        asyncio.run(interp.reset_streak(cache_service=cache, user_id=USER, chat_id=CHAT))
    assert _queue(cache, _event("report", 999)) is False
    # Older than an hour: the window slides and interpretation resumes.
    window = cache._redis.zsets[interp._k("hourly", USER, CHAT)]
    for member in window:
        window[member] -= interp.HOUR_SECONDS + 1
    assert _queue(cache, _event("report", 1000)) is True


# contract-test: supporting surface=rest_api assertions=chat-orchestration.safety.user-requested-writes-only
def test_automatic_turn_is_recorded_as_automatic_origin(recorder):
    from backend.shared.python_utils import chat_orchestration_safety as safety
    cache = FakeCache()
    assert _dispatch(cache, [_event("report", 1)]) is not None
    origin = asyncio.run(safety.get_turn_origin(cache_service=cache, user_id=USER, chat_id=CHAT,
                                                message_id="evt-report-1"))
    assert origin["origin"] == "automatic"
