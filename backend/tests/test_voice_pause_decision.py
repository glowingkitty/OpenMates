"""Pause decision: verdict, intent and wait mapping with a fake model."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.shared.providers.transcript_correction_accounting import (
    CorrectionAccountingError, correction_accountant,
)
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


# contract-test: supporting surface=gui.web assertions=video-call.audio.localized-waiting,video-call.audio.waiting-language
async def test_feedback_uses_the_same_transcript_only_decision():
    answers = response().answers | {"feedback": answer("working"), "feedback_language": answer("de")}
    with patch(f"{MODULE}.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(return_value=DecisionResponse(model="jev", answers=answers))
        decision = await vpd.classify_voice_pause("Schreib mir eine Einladung.", None, with_feedback=True)
        call = client.return_value.evaluate.call_args.kwargs
    assert call["state"] == {"speech": "Schreib mir eine Einladung."}
    assert set(call["questions"]) == {"verdict", "intent", "feedback", "feedback_language"}
    assert (decision.feedback, decision.feedback_language) == ("working", "de")
    result = vpd.parse_pause_decision(answers | {"feedback_language": answer("other")})
    assert result.feedback_language is None


# contract-test: supporting surface=gui.web assertions=video-call.audio.localized-waiting
def test_feedback_switch_requires_capable_web_call_and_allows_disabling(monkeypatch):
    monkeypatch.delenv("VOICE_CALL_INSTANT_FEEDBACK", raising=False)
    assert vpd.instant_feedback_enabled({"instant_feedback": True})
    assert not vpd.instant_feedback_enabled({})
    monkeypatch.setenv("VOICE_CALL_INSTANT_FEEDBACK", "0")
    assert not vpd.instant_feedback_enabled({"instant_feedback": True})


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


# contract-test: supporting surface=rest_api assertions=video-call.guest-calls,billing.anonymous.hard-capped-provider-metering
async def test_guest_hold_check_requires_admission_and_settles_only_one_attempt():
    operation = AsyncMock()
    meter = AsyncMock()
    meter.reserve_correction.return_value = operation
    binding = correction_accountant.set(meter)
    try:
        with patch(f"{MODULE}.JevDecisionClient") as client:
            async def evaluate(**_):
                assert meter.reserve_correction.await_count == 1
                client.call_args.kwargs["accounting"].append({"input_tokens": 100, "output_tokens": 0})
                return response("wait", "wait")

            client.return_value.evaluate = evaluate
            assert (await vpd.classify_metered_voice_pause("Give me a second.", None)).intent == "wait"
            operation.settle.assert_awaited_once_with(100, 0)
            assert client.call_count == 1 and client.call_args.kwargs["max_retries"] == 0
            assert not client.call_args.kwargs["allow_gemini"]

            meter.reserve_correction.side_effect = RuntimeError("denied")
            with pytest.raises(CorrectionAccountingError):
                await vpd.classify_metered_voice_pause("Give me a second.", None)
            assert client.call_count == 1
    finally:
        correction_accountant.reset(binding)


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


# contract-test: supporting surface=gui.web assertions=video-call.audio.pause-verdict,video-call.audio.intentional-interruption
async def test_playback_control_uses_same_bounded_decision_only_when_requested():
    result = response("finished", "pause_playback")
    assert vpd.parse_pause_decision(result.answers).intent == "none"
    with patch(f"{MODULE}.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(return_value=result)
        decision = await vpd.classify_voice_pause("give me a second", None, playback_control=True)
        request = client.return_value.evaluate.call_args.kwargs
    assert "pause_playback" in request["questions"]["intent"]["criteria"]
    assert set(request["questions"]) == {"verdict", "intent"}
    assert decision.intent == "pause_playback"
