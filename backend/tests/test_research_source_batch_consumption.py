# contract-test-file: infrastructure
"""Research handoff consumes each admitted batch with the unchanged durable guard."""
import copy
import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis.aioredis
import pytest

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import ask_skill_task, stream_consumer
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError


def _id(n):
    return str(uuid.UUID(int=n, version=4))


class _Cache:
    def __init__(self):
        self.redis = fakeredis.aioredis.FakeRedis()
        self.release_active_ai_child_context = AsyncMock(return_value=True)
        self.set_active_ai_task = AsyncMock()

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        raw = await self.redis.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key, value, *, ttl):
        return await self.redis.setex(key, ttl, json.dumps(value))


class _StrictRecovery:
    """Run the unchanged Node transaction, with only its DB boundary in memory."""
    def __init__(self, request, children, research_task, final_task):
        self.calls = []
        self.seed = {
            "chats": [{"id": child, "hashed_user_id": request.user_id_hash,
                "parent_id": request.chat_id, "is_sub_chat": True,
                "child_result_delivered_at": "2030-01-01T00:00:00Z"} for child in children],
            "sub_chat_orchestrations": [{"id": request.orchestration_id,
                "hashed_user_id": request.user_id_hash, "root_chat_id": request.chat_id}],
            "sub_chat_orchestration_children": [{"child_chat_id": child,
                "orchestration_id": request.orchestration_id, "batch_id": _id(31 if i < 3 else 32),
                "state": "completed"} for i, child in enumerate(children)],
            "sub_chat_orchestration_batches": [{"id": _id(31), "parent_chat_id": request.chat_id,
                "continuation_task_id": research_task, "continuation_dispatched_at": "2030-01-01T00:00:00Z"},
                {"id": _id(32), "parent_chat_id": request.chat_id,
                "continuation_task_id": final_task, "continuation_dispatched_at": "2030-01-01T00:01:00Z"}],
        }

    async def execute(self, operation, payload):
        assert operation == "mark_child_parent_consumed"
        self.calls.append(payload)
        script = Path(__file__).parent / "fixtures/sub_chat_consumption_guard.mjs"
        result = subprocess.run(["node", str(script)], input=json.dumps({"seed": self.seed, "payload": payload}),
            capture_output=True, text=True, check=True)
        outcome = json.loads(result.stdout)
        self.seed = outcome["seed"]
        if "error" in outcome:
            raise RuntimeError(outcome["error"])
        return outcome["result"]


@pytest.fixture
async def final_research_dispatch(monkeypatch):
    cache = _Cache()
    request = AskSkillRequest(chat_id=_id(1), message_id=_id(2), user_id="test-owner",
        user_id_hash="a" * 64, root_chat_id=_id(1), root_turn_id=_id(2),
        orchestration_id=_id(3), recovery_preflight_id=_id(4), active_focus_id="web-research",
        message_history=[{"role": "user", "content": "Investigate independent explanations.", "created_at": 1}])
    children, research_task, final_task = [_id(n) for n in (10, 11, 12, 13)], _id(20), _id(21)

    def report(child):
        ref = "source-" + child
        return {"summary": "Primary report " + ref, "chat_id": child, "parent_id": request.chat_id,
            "owner_hash": request.user_id_hash, "root_chat_id": request.root_chat_id,
            "root_turn_id": request.root_turn_id, "orchestration_id": request.orchestration_id,
            "source_refs": [ref], "source_bindings": {ref: child}}

    initial = {"parent_task_id": _id(22), "parent_request_data": request.model_dump(mode="json"),
        "pending_batch_id": _id(31), "expected_sub_chat_ids": children[:3],
        "completed": {child: report(child) for child in children[:3]}}
    await cache.set(stream_consumer._sub_chat_pending_key(request.chat_id), initial, ttl=86400)
    acknowledgements = []

    class Transactions:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, payload):
            if operation == "mark_parent_continuation_dispatched":
                acknowledgements.append(payload)
                return {}
            assert operation == "claim_parent_continuation"
            initial_batch = payload["batch_id"] == _id(31)
            return {"dispatch_required": True, "root_chat_id": request.chat_id,
                "root_turn_id": request.root_turn_id,
                "research_stage": "verification_due" if initial_batch else "synthesis",
                "research_batch_id": _id(31), "verifier_batch_id": _id(32),
                "verifier_child_id": children[3], "continuation_task_id": research_task if initial_batch else final_task}

    monkeypatch.setattr(stream_consumer, "DirectusService", lambda: SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(stream_consumer, "SubChatOrchestrationService", Transactions)
    monkeypatch.setattr(stream_consumer, "create_sub_chat_records", AsyncMock(return_value={children[3]: "dispatch-token"}))
    monkeypatch.setattr(stream_consumer, "dispatch_sub_chat_task", AsyncMock(return_value=_id(23)))
    monkeypatch.setattr(stream_consumer, "_publish_to_redis", AsyncMock())
    broker = Mock(return_value=SimpleNamespace(id=final_task))
    monkeypatch.setattr(stream_consumer.celery_config.app, "send_task", broker)
    assert not await stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=cache,
        pending_context=initial, parent_chat_id=request.chat_id, durable_batch_id=_id(31), log_prefix="[test]")
    broker.assert_not_called()
    verifier = await cache.get(stream_consumer._sub_chat_pending_key(request.chat_id))
    assert verifier["research_continuation_task_id"] == research_task
    assert verifier["research_context"]["completed"] == initial["completed"]
    verifier["completed"] = {children[3]: report(children[3])}
    assert await stream_consumer._mutate_sub_chat_pending_context(cache,
        stream_consumer._sub_chat_pending_key(request.chat_id), verifier)
    assert await stream_consumer._dispatch_sub_chat_parent_continuation(cache_service=cache,
        pending_context=verifier, parent_chat_id=request.chat_id, durable_batch_id=_id(32), log_prefix="[test]")
    broker.assert_called_once()
    assert len(acknowledgements) == 2
    final = AskSkillRequest(**broker.call_args.kwargs["kwargs"]["request_data_dict"])
    authority = await cache.get(stream_consumer._sub_chat_source_authority_key(final_task))
    yield SimpleNamespace(cache=cache, request=final, authority=authority, children=children,
        research_task=research_task, final_task=final_task)
    await cache.redis.aclose()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
async def test_research_final_consumes_original_and_verifier_batches_before_one_provider(monkeypatch, final_research_dispatch):
    case = final_research_dispatch
    strict = _StrictRecovery(case.request, case.children, case.research_task, case.final_task)
    # Reproduce the real failure against the unchanged guard, not a mirrored check.
    with pytest.raises(RuntimeError, match="child_parent_not_consumed"):
        await strict.execute("mark_child_parent_consumed", {"protocol_version": 1,
            "hashed_user_id": case.request.user_id_hash, "child_chat_id": case.children[0],
            "root_chat_id": case.request.root_chat_id, "continuation_task_id": case.final_task})
    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", lambda _directus: strict)
    provider = AsyncMock()
    await ask_skill_task._consume_sub_chat_recovery_children(case.request, case.final_task, case.cache, object())
    await provider()
    provider.assert_awaited_once()
    assert case.authority["consumption_task_ids"] == {
        **{child: case.research_task for child in case.children[:3]}, case.children[3]: case.final_task}
    assert all(row.get("child_parent_consumed_at") for row in strict.seed["chats"])
    assert case.cache.release_active_ai_child_context.await_count == 4
    refs = await stream_consumer._load_sub_chat_source_authority(case.cache, case.final_task, case.request)
    assert refs == {"source-" + child for child in case.children}


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("owner_hash", "other-owner"), ("root_turn_id", _id(99)),
    ("task_id", _id(99)), ("child_ids", [_id(99)]), ("consumption_task_ids", {_id(99): _id(20)})])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
async def test_research_consumption_rejects_wrong_private_scope_before_release(monkeypatch, final_research_dispatch, field, value):
    case = final_research_dispatch
    authority = copy.deepcopy(case.authority)
    authority[field] = value
    await case.cache.set(stream_consumer._sub_chat_source_authority_key(case.final_task), authority, ttl=86400)
    recovery = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", lambda _directus: recovery)
    with pytest.raises(RequiredRecoveryOutputError, match="trusted child consumption authority"):
        await ask_skill_task._consume_sub_chat_recovery_children(case.request, case.final_task, case.cache, object())
    recovery.execute.assert_not_awaited()
    case.cache.release_active_ai_child_context.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
async def test_partial_research_consumption_preserves_all_working_contexts(monkeypatch, final_research_dispatch):
    case = final_research_dispatch
    strict = _StrictRecovery(case.request, case.children, case.research_task, case.final_task)
    strict.seed["chats"][1]["child_result_delivered_at"] = None
    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", lambda _directus: strict)
    provider = AsyncMock()
    with pytest.raises(RuntimeError, match="child_parent_not_consumed"):
        await ask_skill_task._consume_sub_chat_recovery_children(case.request, case.final_task, case.cache, object())
        await provider()
    provider.assert_not_awaited()
    case.cache.release_active_ai_child_context.assert_not_awaited()
    assert any(row.get("child_parent_consumed_at") for row in strict.seed["chats"])
