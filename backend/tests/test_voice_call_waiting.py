"""Waiting state of a voice call: hold, merge into one turn, repeat, resume."""
from __future__ import annotations

import pytest

from backend.core.api.app.routes.voice_call_waiting import VoiceWaiting


class _Sent(list):
    async def __call__(self, event: dict) -> None:
        self.append(event)


# contract-test: supporting surface=rest_api assertions=video-call.waiting.spoken-intent-and-merge
@pytest.mark.asyncio
async def test_hold_then_resume_merges_one_turn_without_inference_lines() -> None:
    sent, waiting = _Sent(), VoiceWaiting()
    assert await waiting.set_active(True, send=sent, call_id="c1", pending_text="Plan a trip to my_city") is True
    assert sent[-1] == {"type": "waiting", "call_id": "c1", "active": True, "line": "waiting_start"}
    assert await waiting.route("with two stops", "none", send=sent, call_id="c1") == ("waiting", "with two stops")
    assert await waiting.route("I am back", "resume", send=sent, call_id="c1") == ("resume", "I am back")
    assert sent[-1]["line"] == "waiting_resume" and not waiting.active
    reason, text = await waiting.route("by train please", "none", send=sent, call_id="c1")
    assert reason is None and text == "Plan a trip to my_city with two stops by train please"
    assert await waiting.route("next question", "none", send=sent, call_id="c1") == (None, "next question")


# contract-test: supporting surface=rest_api assertions=video-call.waiting.spoken-intent-and-merge
@pytest.mark.asyncio
async def test_spoken_wait_intent_holds_the_utterance_and_enters_waiting() -> None:
    sent, waiting = _Sent(), VoiceWaiting()
    assert (await waiting.route("Order a pizza, one moment", "wait", send=sent, call_id="c1"))[0] == "waiting"
    assert waiting.active and waiting.held == ["Order a pizza, one moment"]


# contract-test: supporting surface=rest_api assertions=video-call.waiting.spoken-intent-and-merge
@pytest.mark.asyncio
async def test_repeat_asks_client_replay_and_never_submits() -> None:
    sent, waiting = _Sent(), VoiceWaiting()
    assert (await waiting.route("say that again", "repeat", send=sent, call_id="c1"))[0] == "repeat"
    assert sent == [{"type": "repeat_last_answer", "call_id": "c1"}]


# contract-test: supporting surface=rest_api assertions=video-call.waiting.spoken-intent-and-merge
@pytest.mark.asyncio
async def test_repeated_hold_signals_are_idempotent() -> None:
    sent, waiting = _Sent(), VoiceWaiting()
    await waiting.set_active(True, send=sent, call_id="c1")
    assert await waiting.set_active(True, send=sent, call_id="c1") is False
    assert len(sent) == 1
