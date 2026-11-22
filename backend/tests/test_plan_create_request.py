"""Plan create request (openmates.plan_create_request v1): publish and result validation."""
import json
import time
import uuid

import pytest

from backend.core.api.app.services.plan_create_request_service import (
    PLAN_CREATE_EVENT, handle_plan_create_result, outbound_plan_create_event,
    plan_create_record_key, publish_plan_create_request,
)

PLAN = "11111111-1111-4111-8111-111111111111"


class _Redis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, message):
        self.published.append((channel, json.loads(message)))


class _Cache:
    def __init__(self):
        self.values = {}
        self._redis = _Redis()

    @property
    def client(self):
        async def _get():
            return self._redis
        return _get()

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        return self.values.pop(key, None) is not None


class _Manager:
    def can_execute_plan_create(self, user_id, device):
        return device == "capable"


def _action():
    rid = f"plan-create-request-{uuid.uuid4()}"
    return {
        "contract": "openmates.plan_create_request", "version": 1, "request_id": rid, "action": "create",
        "plan_id": PLAN, "title": "Example plan", "summary": "", "goal": "", "specification_ref": None,
        "assumptions": [{"assumption_id": "a-1", "text": "Example", "required_before": "implementation"}],
        "chat_id": "chat", "message_id": "turn", "notification_queued": False,
    }


async def _published(cache, user="owner"):
    action = _action()
    assert await publish_plan_create_request(cache_service=cache, user_id=user, action=action)
    return action


def _report(action, **over):
    return {"request_id": action["request_id"], "status": "created", "plan_id": PLAN, **over}


# contract-test: supporting surface=rest_api assertions=plans.assistant.created-plan-saved
@pytest.mark.asyncio
async def test_event_published_with_payload_for_capable_connection():
    cache = _Cache()
    action = await _published(cache)
    channel, message = cache._redis.published[0]
    assert channel == "user_cache_events:owner" and message["event_type"] == PLAN_CREATE_EVENT
    outbound = outbound_plan_create_event(message["payload"])
    assert outbound["pending_client_action"]["plan_id"] == PLAN
    assert outbound["pending_client_action"]["notification_queued"] is True
    assert action["expires_at"] > time.time()
    assert outbound_plan_create_event({**message["payload"], "request_id": "bad"}) is None


# contract-test: supporting surface=rest_api assertions=plans.assistant.created-plan-saved
@pytest.mark.asyncio
async def test_result_accepted_for_owner_and_record_cleared():
    cache, manager = _Cache(), _Manager()
    action = await _published(cache)
    assert not await handle_plan_create_result(manager=manager, cache_service=cache, user_id="owner",
                                               device_fingerprint_hash="other", payload=_report(action))
    assert await handle_plan_create_result(manager=manager, cache_service=cache, user_id="owner",
                                           device_fingerprint_hash="capable", payload=_report(action))
    assert plan_create_record_key("owner", action["request_id"]) not in cache.values


# contract-test: supporting surface=rest_api assertions=plans.assistant.created-plan-saved
@pytest.mark.asyncio
async def test_result_refused_for_another_user_or_plan():
    cache, manager = _Cache(), _Manager()
    action = await _published(cache)
    assert not await handle_plan_create_result(manager=manager, cache_service=cache, user_id="intruder",
                                               device_fingerprint_hash="capable", payload=_report(action))
    assert not await handle_plan_create_result(manager=manager, cache_service=cache, user_id="owner",
                                               device_fingerprint_hash="capable",
                                               payload=_report(action, plan_id="other-plan"))
    assert plan_create_record_key("owner", action["request_id"]) in cache.values


# contract-test: supporting surface=rest_api assertions=plans.assistant.created-plan-saved
@pytest.mark.asyncio
async def test_expired_result_is_ignored():
    cache, manager = _Cache(), _Manager()
    action = await _published(cache)
    cache.values[plan_create_record_key("owner", action["request_id"])]["expires_at"] = time.time() - 1
    assert not await handle_plan_create_result(manager=manager, cache_service=cache, user_id="owner",
                                               device_fingerprint_hash="capable", payload=_report(action))
