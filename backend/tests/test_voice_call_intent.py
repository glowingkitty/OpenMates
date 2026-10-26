"""Intent decisions must preserve listening cues and deliberate short stops."""
from unittest.mock import AsyncMock, patch

import pytest

from backend.shared.python_utils.voice_call_intent import (
    classify_voice_interruption, is_explicit_voice_stop, is_listener_acknowledgement,
)
from backend.shared.providers.typesafe.models import ChoiceAnswer, DecisionResponse


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
@pytest.mark.parametrize("text", ["hmm", "Okay!", "mhm, okay", "Alles klar", "d’accord", "嗯嗯"])
def test_listening_cues(text):
    assert is_listener_acknowledgement(text)


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
@pytest.mark.parametrize("text", ["Okay, but show Berlin instead", "yes, change that", "No, that's wrong"])
def test_correction_is_not_listener_cue(text):
    assert not is_listener_acknowledgement(text)


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
def test_stop_requires_whole_control_not_substring():
    assert is_explicit_voice_stop("Please stop!")
    assert is_explicit_voice_stop("Warte bitte.")
    assert not is_explicit_voice_stop("Stop by the station first")


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
@pytest.mark.asyncio
async def test_fast_stop_and_ack_do_not_call_provider():
    with patch("backend.shared.python_utils.voice_call_intent.JevDecisionClient") as client:
        assert await classify_voice_interruption("Stop", "Here are the images.", None) == "interrupt"
        assert await classify_voice_interruption("hmm okay", "Here are the images.", None) == "backchannel"
        client.assert_not_called()


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
@pytest.mark.asyncio
async def test_semantic_context_and_confidence():
    response = DecisionResponse(model="jev", answers={"intent": ChoiceAnswer(
        type="choice", choice="interrupt", confidence=.9,
        probabilities={"interrupt": .9, "backchannel": .05, "uncertain": .05},
    )})
    evaluate = AsyncMock(return_value=response)
    with patch("backend.shared.python_utils.voice_call_intent.JevDecisionClient") as client:
        client.return_value.evaluate = evaluate
        assert await classify_voice_interruption("Okay, show Berlin instead", "Here are images.", None) == "interrupt"
        assert evaluate.call_args.kwargs["state"]["user_speech"] == "Okay, show Berlin instead"
        question = evaluate.call_args.kwargs["questions"]["intent"]
        assert "choices" not in question
        assert set(question["criteria"]) == {"backchannel", "interrupt", "echo", "uncertain"}
        assert client.call_args.kwargs["max_retries"] == 0


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
@pytest.mark.asyncio
async def test_answer_to_assistant_question_is_not_blindly_ignored():
    with patch("backend.shared.python_utils.voice_call_intent.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(side_effect=RuntimeError("private provider body"))
        assert await classify_voice_interruption("yes", "Would you like another example?", None) == "uncertain"
        client.return_value.evaluate.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption,video-call.audio.spoken-rich-response
async def test_answer_to_question_before_rich_embed_is_preserved():
    from backend.shared.python_utils.voice_call_intent import assistant_question_pending

    question = 'Would you like more images?\n\n```json\n{"type":"app_skill_use","embed_id":"images"}\n```'
    assert assistant_question_pending(question)
    assert not assistant_question_pending('Here are the images.\n\n```json\n{"embed_id":"images"}\n```')
    with patch("backend.shared.python_utils.voice_call_intent.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(side_effect=RuntimeError("unavailable"))
        assert await classify_voice_interruption("yes", question, None) == "uncertain"
        client.return_value.evaluate.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
@pytest.mark.asyncio
async def test_uncertain_or_failed_decision_never_invents_intent():
    response = DecisionResponse(model="jev", answers={"intent": ChoiceAnswer(
        type="choice", choice="interrupt", confidence=.5,
        probabilities={"interrupt": .5, "backchannel": .3, "uncertain": .2},
    )})
    with patch("backend.shared.python_utils.voice_call_intent.JevDecisionClient") as client:
        client.return_value.evaluate = AsyncMock(return_value=response)
        assert await classify_voice_interruption("Actually", "Here are images.", None) == "uncertain"


@pytest.mark.parametrize('speaking,confidence,text,assistant,expected', [
    (True, .95, 'the first step is to open the guide', 'Here, the first step is to open the guide.', 'echo'),
    (False, .95, 'the first step is to open the guide', 'Here, the first step is to open the guide.', 'uncertain'),
    (True, .89, 'the first step is to open the guide', 'Here, the first step is to open the guide.', 'uncertain'),
    (True, .95, 'the first step', 'Here, the first step is to open the guide.', 'uncertain'),
    (True, .95, 'please switch to another subject now', 'Here, the first step is to open the guide.', 'uncertain'),
    (True, .95, 'the first step is to open the guide', '```text\nthe first step is to open the guide\n```', 'uncertain'),
    (True, .95, 'the first step is to open the guide', '[the guide](https://the.first.step.is.to.open.the.guide)', 'uncertain'),
])
# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
async def test_echo_requires_semantic_confidence_playback_and_multiword_prose_support(
        speaking, confidence, text, assistant, expected):
    result = DecisionResponse(model='jev', answers={'intent': ChoiceAnswer(
        type='choice', choice='echo', confidence=confidence, probabilities={'echo': confidence, 'uncertain': 1-confidence})})
    with patch('backend.shared.python_utils.voice_call_intent.JevDecisionClient') as client:
        client.return_value.evaluate = AsyncMock(return_value=result)
        assert await classify_voice_interruption(text, assistant, None, assistant_speaking=speaking) == expected
        request = client.return_value.evaluate.call_args.kwargs
        assert request['state']['assistant_speaking'] is speaking
        assert set(request['questions']['intent']) == {'type', 'instructions', 'criteria'}
        assert 'echo' in request['questions']['intent']['criteria']


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption
@pytest.mark.parametrize('text', [
    'You said the first step is to open the guide. Why?',
    'No, the first step is to open the guide, not the settings.',
    'Repeat the first step is to open the guide.',
])
async def test_matching_words_never_override_semantic_deliberate_interruption(text):
    result = DecisionResponse(model='jev', answers={'intent': ChoiceAnswer(
        type='choice', choice='interrupt', confidence=.95, probabilities={'echo': .05, 'interrupt': .95})})
    with patch('backend.shared.python_utils.voice_call_intent.JevDecisionClient') as client:
        client.return_value.evaluate = AsyncMock(return_value=result)
        assert await classify_voice_interruption(text, 'The first step is to open the guide.', None,
                                                assistant_speaking=True) == 'interrupt'
    with patch('backend.shared.python_utils.voice_call_intent.JevDecisionClient') as client:
        assert await classify_voice_interruption('Stop!', 'You can say stop.', None, assistant_speaking=True) == 'interrupt'
        client.assert_not_called()
