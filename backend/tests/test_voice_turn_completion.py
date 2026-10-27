"""The completion classifier has one bounded decision and cannot admit a chat."""
from unittest.mock import AsyncMock, patch

import pytest

from backend.shared.providers.typesafe.models import ChoiceAnswer, DecisionResponse
from backend.shared.python_utils.voice_turn_completion import classify_voice_turn_completion

MODULE = "backend.shared.python_utils.voice_turn_completion"


def decision(choice="complete", confidence=.95):
    return DecisionResponse(model="jev", answers={"completion": ChoiceAnswer(
        type="choice", choice=choice, confidence=confidence,
        probabilities={choice: .95, "other": .05},
    )})


# contract-test: supporting surface=rest_api assertions=video-call.audio.complete-turn-admission
@pytest.mark.parametrize("text", ["Yes", "Stop", "How do I make ramen?", "Zeig mir bitte die Bilder",
                                  "Are you still listening?", "Hörst du mir noch zu?"])
async def test_only_speech_and_one_completion_question_cross_the_provider_boundary(text):
    with patch(f"{MODULE}.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(return_value=decision())
        assert await classify_voice_turn_completion(text, None) == "complete"
        request = client.return_value.evaluate.call_args.kwargs
        assert request["state"] == {"speech": text}
        assert set(request["questions"]) == {"completion"}
        assert set(request["questions"]["completion"]) == {"type", "instructions", "criteria"}
        assert set(request["questions"]["completion"]["criteria"]) == {"complete", "incomplete", "uncertain"}
        assert client.call_args.kwargs["max_retries"] == 0


# contract-test: supporting surface=rest_api assertions=video-call.audio.complete-turn-admission
@pytest.mark.parametrize("choice,confidence,expected", [
    ("complete", .5, "uncertain"), ("incomplete", .95, "incomplete"),
    ("uncertain", .95, "uncertain"), ("unrecognized", .99, "uncertain"),
])
async def test_uncertainty_never_becomes_completion(choice, confidence, expected):
    with patch(f"{MODULE}.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(return_value=decision(choice, confidence))
        assert await classify_voice_turn_completion("I was thinking about", None) == expected


# contract-test: supporting surface=rest_api assertions=video-call.audio.complete-turn-admission,video-call.privacy
async def test_provider_failure_retains_speech_without_logging_private_error(caplog):
    with patch(f"{MODULE}.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(side_effect=RuntimeError("PRIVATE transcript/provider body"))
        assert await classify_voice_turn_completion("PRIVATE", None) == "uncertain"
    assert "RuntimeError" in caplog.text
    assert "PRIVATE" not in caplog.text


# contract-test: supporting surface=rest_api assertions=video-call.audio.complete-turn-admission
@pytest.mark.parametrize("text", ["", "  ", "x" * 8001])
async def test_empty_or_oversized_text_is_not_clipped_into_a_different_request(text):
    with patch(f"{MODULE}.JevDecisionClient") as client:
        assert await classify_voice_turn_completion(text, None) == "uncertain"
        client.assert_not_called()
