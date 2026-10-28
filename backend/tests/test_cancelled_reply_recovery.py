"""Cancellation retains the encrypted completion receipt needed by a follow-up."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.tasks import ask_skill_task, stream_consumer
from backend.shared.python_utils.chat_completion_recovery import derive_recovery_keypair, open_recovery_envelope
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError


def request():
    owner = "11111111-1111-4111-8111-111111111111"
    chat = "22222222-2222-4222-8222-222222222222"
    private, public = derive_recovery_keypair("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", chat, 1)
    return AskSkillRequest(
        user_id=owner, user_id_hash=hashlib.sha256(owner.encode()).hexdigest(),
        chat_id=chat, message_id="user-message", message_history=[],
        recovery_task_id="66666666-6666-4666-8666-666666666666",
        recovery_preflight_id="77777777-7777-4777-8777-777777777777",
        recovery_turn_id="33333333-3333-4333-8333-333333333333",
        recovery_public_key=public, chat_key_version=1,
    ), private


def services(monkeypatch, receipt_status="not_found"):
    events = []
    directus = SimpleNamespace(chat=SimpleNamespace(
        get_sealed_job_receipt=AsyncMock(return_value={"status": receipt_status, "job_id": "existing-job"})), close=AsyncMock())
    async def publish(channel, payload):
        events.append(("publish", payload))
        return True
    cache = SimpleNamespace(publish_event=AsyncMock(side_effect=publish), close=AsyncMock())
    class Recovery:
        def __init__(self, _): pass
        async def execute(self, operation, data):
            events.append((operation, data))
            return {"job_id": data.get("job_id"), "state": "AVAILABLE"}
    monkeypatch.setattr(ask_skill_task, "DirectusService", lambda: directus)
    monkeypatch.setattr(ask_skill_task, "CacheService", lambda: cache)
    monkeypatch.setattr(ask_skill_task, "ChatRecoveryService", Recovery)
    monkeypatch.setattr(stream_consumer, "ChatRecoveryService", Recovery)
    return directus, cache, events


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [None, "The partial reply already shown to its owner."])
# contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.completion.recovery-takeover,chat-processing-feedback.turn-lifecycle
async def test_cancel_seals_rendered_partial_or_empty_reply_before_failure(monkeypatch, partial):
    turn, private = request()
    directus, cache, events = services(monkeypatch)
    if partial is not None:
        stream_consumer._create_redis_payload(turn.recovery_task_id, turn, partial, 4, model_name="model")
        assert "_recovery_stream_checkpoint" not in turn.model_dump()
    await ask_skill_task._mark_recovery_inference_failed(turn, turn.recovery_task_id, "user_cancelled")
    assert [name for name, _ in events] == ["create_sealed_job", "publish", "mark_inference_failed"]
    sealed = events[0][1]
    if partial:
        assert partial not in json.dumps(sealed)
    recovered = json.loads(open_recovery_envelope(
        json.loads(sealed["sealed_payload"]), recovery_private_key=private,
        owner_id=turn.user_id, chat_id=turn.chat_id, turn_id=turn.recovery_turn_id,
        job_id=sealed["job_id"], assistant_message_id=turn.recovery_task_id, key_version=1,
    ))
    assert recovered["content"] == (partial or "")
    final = events[1][1]
    assert final["recovery_job_id"] == sealed["job_id"]
    assert final["interrupted_by_revocation"] and final["is_final_chunk"]
    assert final["sequence"] == (5 if partial is not None else 1)
    cache.close.assert_awaited_once()
    directus.close.assert_awaited_once()


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
async def test_stop_after_sealing_reannounces_existing_job_without_replacing_it(monkeypatch):
    turn, _ = request()
    _, cache, events = services(monkeypatch, "found")
    await ask_skill_task._mark_recovery_inference_failed(turn, turn.recovery_task_id, "user_cancelled")
    assert [name for name, _ in events] == ["publish", "mark_inference_failed"]
    assert events[0][1]["recovery_job_id"] == "existing-job"
    assert events[0][1]["is_final_chunk"] is True
    cache.publish_event.assert_awaited_once()


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
async def test_cancel_preserves_observed_thinking_only_inside_owner_envelope(monkeypatch):
    turn, private = request()
    _, _, events = services(monkeypatch)
    task_id = turn.recovery_task_id
    stream_consumer._create_thinking_redis_payload(task_id, turn, "First thought. ")
    stream_consumer._create_thinking_redis_payload(task_id, turn, "Second thought.")
    stream_consumer._create_thinking_redis_payload(
        task_id, turn, "", is_complete=True, signature="opaque-signature", total_tokens=8,
    )
    assert "_recovery_thinking_checkpoint" not in turn.model_dump()
    await ask_skill_task._mark_recovery_inference_failed(turn, task_id, "user_cancelled")
    sealed = events[0][1]
    assert "First thought" not in json.dumps(sealed)
    recovered = json.loads(open_recovery_envelope(
        json.loads(sealed["sealed_payload"]), recovery_private_key=private,
        owner_id=turn.user_id, chat_id=turn.chat_id, turn_id=turn.recovery_turn_id,
        job_id=sealed["job_id"], assistant_message_id=task_id, key_version=1,
    ))
    assert recovered["thinking_content"] == "First thought. Second thought."
    assert recovered["thinking_signature"] == "opaque-signature"
    assert recovered["thinking_token_count"] == 8


@pytest.mark.asyncio
# contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
async def test_mismatched_checkpoint_cannot_seal_or_terminalize_another_delivery(monkeypatch):
    turn, _ = request()
    services(monkeypatch)
    object.__setattr__(turn, "_recovery_stream_checkpoint", {"task_id": "another-task"})
    with pytest.raises(RequiredRecoveryOutputError, match="another delivery"):
        await ask_skill_task._mark_recovery_inference_failed(turn, turn.recovery_task_id, "user_cancelled")


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,state,expected", [
    ("1", "PROGRESS", True), (None, "PROGRESS", False), (None, "REVOKED", True),
])
# contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
async def test_stop_intent_precedes_celery_revoked_state(monkeypatch, intent, state, expected):
    turn, _ = request()
    cache = SimpleNamespace(get=AsyncMock(return_value=intent), close=AsyncMock())
    monkeypatch.setattr(ask_skill_task, "CacheService", lambda: cache)
    result = Mock(return_value=SimpleNamespace(state=state))
    monkeypatch.setattr(ask_skill_task.celery_config.app, "AsyncResult", result)
    assert await ask_skill_task._was_task_cancelled(turn, turn.recovery_task_id) is expected
    cache.get.assert_awaited_once_with(
        f"ai_task_cancel_requested:{turn.user_id}:{turn.chat_id}:{turn.recovery_task_id}",
    )
    cache.close.assert_awaited_once()
    if intent:
        result.assert_not_called()
