"""Task-owned typing lifecycle guards for two-stage preprocessing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.tasks import ask_skill_task


class EventCache:
    def __init__(self):
        self.events = []

    async def publish_event(self, channel, event):
        self.events.append((channel, event))


def _lifecycle():
    cache = EventCache()
    request = SimpleNamespace(
        user_id="user", user_id_hash="hash", chat_id="chat",
        message_id="message", is_external=False,
    )
    return cache, ask_skill_task.EarlyTypingLifecycle(cache, request, "task")


@pytest.mark.anyio
# contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.early-resolution,chat-processing-feedback.selected-mate-identity
async def test_stage_one_typing_and_stage_two_metadata_have_distinct_events():
    cache, lifecycle = _lifecycle()
    start = {"type": "ai_processing_started_event", "event_for_client": "ai_typing_started",
             "category": "software_development", "model_name": "Selected model"}
    assert await lifecycle.publish_stage_one(start)
    assert not await lifecycle.publish_stage_one(start)
    job = {"job_id": "sealed-job", "ciphertext": "sealed"}
    await lifecycle.finish_preprocessing(can_proceed=True, late_payload={**start, "title": "late"},
                                         metadata_recovery_job=job)
    assert [event["event_for_client"] for _, event in cache.events
            if "event_for_client" in event] == ["ai_typing_started"]
    assert cache.events[1][1] == {
        "type": "chat_metadata_recovery_available",
        "user_id_hash": "hash", "metadata_recovery_job": job,
    }


@pytest.mark.anyio
# contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selected-mate-identity
async def test_rejected_preprocessing_ends_early_typing_once():
    cache, lifecycle = _lifecycle()
    await lifecycle.publish_stage_one({"type": "ai_processing_started_event",
                                       "event_for_client": "ai_typing_started"})
    await lifecycle.finish_preprocessing(can_proceed=False)
    await lifecycle.fail()
    assert [event["event_for_client"] for _, event in cache.events] == [
        "ai_typing_started", "ai_typing_ended",
    ]
    assert cache.events[-1][1]["user_message_id"] == "message"


@pytest.mark.anyio
# contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selected-mate-identity
async def test_unexpected_task_failure_cleanup_publishes_terminal_event(monkeypatch):
    cache, _ = _lifecycle()
    cache.clear_active_ai_task_if_matches = AsyncMock(return_value=True)
    monkeypatch.setattr(ask_skill_task, "_cleanup_processing_embeds_on_task_failure",
                        AsyncMock(return_value=0))
    from backend.apps.ai.tasks import async_skill_continuation
    monkeypatch.setattr(async_skill_continuation, "dispatch_deferred_async_skill_continuations",
                        AsyncMock())
    await ask_skill_task._cleanup_on_task_failure(
        task_id="task", chat_id="chat", message_id="message",
        user_id="user", user_id_hash="hash", user_vault_key_id="vault",
        error_message="preprocessing failed", cache_service=cache,
    )
    assert [event["event_for_client"] for _, event in cache.events] == ["ai_typing_ended"]
    assert "terminal_failure_code" not in cache.events[0][1]


@pytest.mark.anyio
# contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
async def test_context_failure_publishes_one_task_correlated_terminal_marker(monkeypatch):
    cache, _ = _lifecycle()
    cache.clear_active_ai_task_if_matches = AsyncMock(return_value=True)
    monkeypatch.setattr(ask_skill_task, "_cleanup_processing_embeds_on_task_failure",
                        AsyncMock(return_value=0))
    from backend.apps.ai.tasks import async_skill_continuation
    monkeypatch.setattr(async_skill_continuation, "dispatch_deferred_async_skill_continuations",
                        AsyncMock())

    await ask_skill_task._cleanup_on_task_failure(
        task_id="task", chat_id="chat", message_id="message",
        user_id="user", user_id_hash="hash", user_vault_key_id="vault",
        error_message="private context detail", cache_service=cache,
        terminal_failure_code="client_context_unavailable",
    )

    assert len(cache.events) == 1
    assert cache.events[0][1]["task_id"] == "task"
    assert cache.events[0][1]["user_message_id"] == "message"
    assert cache.events[0][1]["terminal_failure_code"] == "client_context_unavailable"
    assert "private context detail" not in repr(cache.events)
    cache.clear_active_ai_task_if_matches.assert_awaited_once_with("chat", "task")


@pytest.mark.anyio
# contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
async def test_stale_context_failure_cannot_terminalize_newer_task(monkeypatch):
    cache, _ = _lifecycle()
    cache.clear_active_ai_task_if_matches = AsyncMock(return_value=False)
    monkeypatch.setattr(ask_skill_task, "_cleanup_processing_embeds_on_task_failure",
                        AsyncMock(return_value=0))

    await ask_skill_task._cleanup_on_task_failure(
        task_id="old-task", chat_id="chat", message_id="old-message",
        user_id="user", user_id_hash="hash", user_vault_key_id="vault",
        error_message="context failed", cache_service=cache,
        terminal_failure_code="client_context_unavailable",
    )

    assert len(cache.events) == 1
    assert cache.events[0][1]["task_id"] == "old-task"
    assert "terminal_failure_code" not in cache.events[0][1]
