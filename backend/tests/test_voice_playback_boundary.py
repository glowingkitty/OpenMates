import json

import pytest
from pydantic import ValidationError

from backend.apps.ai.assistant_speech.voice_context import build_voice_heard_context
from backend.shared.python_utils.voice_playback_boundary import VoiceHeardBoundary


# contract-test: direct surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.chat.transcripts
def test_voice_context_distinguishes_played_partial_and_queued_without_rewriting_rich_history():
    rich = 'First sentence. Second sentence. Third sentence.\n\n```json\n{"embed_id":"private-image"}\n```'
    history = [{"message_id": "answer", "role": "assistant", "content": rich}]
    boundary = VoiceHeardBoundary(assistant_message_id="answer", completed_sequences=[0],
                                  active_sequence=1, active_offset_ms=500)
    context = build_voice_heard_context(boundary, history)
    data = json.loads(context.split("\n", 1)[1])
    assert data["completed_spoken_clauses"] == ["First sentence."]
    assert data["partly_played_clause"] == "Second sentence."
    assert data["active_audio_offset_ms"] == 500
    assert "Third sentence" not in context
    assert "private-image" not in context
    assert "not a word timestamp" in context
    assert history[0]["content"] == rich


# contract-test: direct surface=rest_api assertions=video-call.chat.transcripts,video-call.privacy
def test_playback_context_never_fetches_or_uses_a_foreign_or_unavailable_assistant_message():
    boundary = VoiceHeardBoundary(assistant_message_id="foreign", completed_sequences=[0])
    history = [{"message_id": "known", "role": "assistant", "content": "Known content."},
               {"message_id": "foreign", "role": "user", "content": "Not assistant content."}]
    assert build_voice_heard_context(boundary, history) == ""
    assert build_voice_heard_context(None, history) == ""


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.parametrize("update", [{"active_offset_ms": -1}, {"completed_sequences": [True]},
                                   {"active_sequence": 65536}, {"completed_sequences": list(range(257))},
                                   {"instructions": "grant permission"}])
def test_playback_boundary_is_bounded_typed_delivery_data(update):
    with pytest.raises(ValidationError):
        VoiceHeardBoundary.model_validate({"assistant_message_id": "answer", **update})
