"""Pause decision: verdict, intent and wait mapping with a fake model."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.shared.providers.typesafe.models import ChoiceAnswer, DecisionResponse
from backend.shared.python_utils import voice_pause_decision as vpd

MODULE = "backend.shared.python_utils.voice_pause_decision"


def answer(choice, confidence=.95):
    return ChoiceAnswer(type="choice", choice=choice, confidence=confidence, probabilities={choice: confidence})


def response(verdict="finished", intent="none", vc=.95, ic=.95):
    return DecisionResponse(model="jev", answers={"verdict": answer(verdict, vc), "intent": answer(intent, ic)})


# contract-test: supporting surface=rest_api assertions=video-call.audio.pause-verdict
@pytest.mark.parametrize("verdict,seconds,legacy", [
    ("finished", .5, "complete"), ("still_thinking", 2.0, "incomplete"),
    ("unsure", 6.0, "uncertain"), ("wait", None, "uncertain"),
])
async def test_verdict_maps_to_wait_and_one_call_carries_both_questions(verdict, seconds, legacy):
    with patch(f"{MODULE}.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(return_value=response(verdict, "repeat"))
        decision = await vpd.classify_voice_pause("say that again", None)
        request = client.return_value.evaluate.call_args.kwargs
    assert (decision.verdict, decision.intent, decision.wait_seconds) == (verdict, "repeat", seconds)
    assert decision.completion == legacy
    assert request["state"] == {"speech": "say that again"}
    assert set(request["questions"]) == {"verdict", "intent"}
    assert set(request["questions"]["verdict"]["criteria"]) == set(vpd.VERDICTS)
    assert set(request["questions"]["intent"]["criteria"]) == set(vpd.INTENTS)


# contract-test: supporting surface=rest_api assertions=video-call.audio.pause-verdict
@pytest.mark.parametrize("intent", ["none", "wait", "resume", "repeat"])
def test_every_intent_parses(intent):
    assert vpd.parse_pause_decision(response("finished", intent).answers).intent == intent


# contract-test: supporting surface=rest_api assertions=video-call.audio.pause-verdict
def test_low_confidence_and_unknown_choices_degrade_safely():
    low = vpd.parse_pause_decision(response("finished", "wait", .3, .3).answers)
    assert (low.verdict, low.intent) == ("unsure", "none")
    unknown = vpd.parse_pause_decision(response("bogus", "bogus").answers)
    assert (unknown.verdict, unknown.intent) == ("unsure", "none")
    assert vpd.parse_pause_decision({}).verdict == "unsure"


# contract-test: supporting surface=rest_api assertions=video-call.audio.pause-verdict
async def test_provider_failure_and_timeout_fail_open_without_private_text(caplog):
    with patch(f"{MODULE}.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(side_effect=RuntimeError("PRIVATE"))
        failed = await vpd.classify_voice_pause("PRIVATE", None)

        async def slow(**_):
            await asyncio.sleep(1)
        client.return_value.evaluate = slow
        timed_out = await vpd.classify_voice_pause("hello", None, timeout=.05)
    assert failed.verdict == timed_out.verdict == "unavailable"
    assert failed.wait_seconds == .5 and failed.intent == "none"
    assert "PRIVATE" not in caplog.text


# contract-test: supporting surface=rest_api assertions=video-call.audio.pause-verdict
@pytest.mark.parametrize("text", ["", "  ", "x" * 8001])
async def test_empty_or_oversized_text_is_unsure_without_a_call(text):
    with patch(f"{MODULE}.JevDecisionClient") as client:
        assert (await vpd.classify_voice_pause(text, None)).verdict == "unsure"
        client.assert_not_called()


# contract-test: supporting surface=rest_api assertions=video-call.audio.pause-verdict
def test_provider_list_is_configuration(monkeypatch):
    monkeypatch.setenv(vpd.PROVIDERS_ENV, "openrouter")
    assert vpd.configured_providers() == ["openrouter"]
    monkeypatch.setenv(vpd.PROVIDERS_ENV, "nope")
    with pytest.raises(ValueError):
        vpd.configured_providers()
    monkeypatch.delenv(vpd.PROVIDERS_ENV)
    assert set(vpd.configured_providers()) == set(vpd.PROVIDER_SETTINGS)


# contract-test: supporting surface=rest_api assertions=video-call.audio.pause-verdict
def test_fixture_hold_string_is_a_wait_decision_without_deadline_and_still_thinking_is_two_seconds():
    hold = vpd.as_pause_decision("hold")
    assert (hold.verdict, hold.intent, hold.wait_seconds) == ("wait", "none", None)
    thinking = vpd.as_pause_decision("incomplete")
    assert (thinking.verdict, thinking.wait_seconds) == ("still_thinking", 2.0)
