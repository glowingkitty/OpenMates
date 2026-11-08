"""Call status lines: instant acknowledgement, app-use announcement and skill recap."""
import asyncio

import pytest

from backend.apps.ai.assistant_speech.streaming import ImmutableSpeechBoundaryTracker
from backend.apps.ai.assistant_speech.voice_status import (
    build_skill_recap, build_voice_app_use_announcement, select_instant_acknowledgement,
)


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_instant_acknowledgement_is_prerecorded_and_varies_per_turn():
    clips = {
        select_instant_acknowledgement(
            voice_profile_id="sophia", voice_profile_version=1, language="en", seed=f"message-{index}",
        )["clip_id"]
        for index in range(40)
    }
    assert len(clips) > 1
    assert all(clip.startswith("sophia-en-US-") for clip in clips)


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_instant_acknowledgement_is_silent_for_unsupported_language():
    assert select_instant_acknowledgement(
        voice_profile_id="sophia", voice_profile_version=1, language="ja", seed="message-1") is None


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_app_use_announcement_is_localized_without_english_fallback():
    assert "apps" in build_voice_app_use_announcement("en-US", "m1").lower()
    assert "Apps" in build_voice_app_use_announcement("de", "m1")
    assert build_voice_app_use_announcement("ja", "m1") is None


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_recap_names_the_skills_that_ran_once_in_order():
    skills = [("web", "search"), ("news", "search"), ("web", "search")]
    assert build_skill_recap(skills, "en") == "I used web search and news search."
    assert build_skill_recap([("web", "search")], "de") == "Ich habe die Websuche verwendet."


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_recap_stays_generic_for_an_unnamed_skill_and_silent_for_unknown_language():
    assert build_skill_recap([("web", "search"), ("fitness", "plan")], "en") == "I used a few apps."
    assert build_skill_recap([("web", "search")], "ja") is None
    assert build_skill_recap([], "en") is None


# contract-test: direct surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.asyncio
async def test_status_lines_are_ordered_with_the_answer_but_not_answer_segments():
    spoken: list[tuple[str, int]] = []

    async def dispatch(segment):
        spoken.append((segment["kind"], segment["sequence"]))

    tracker = ImmutableSpeechBoundaryTracker(
        metadata={"chat_id": "c", "assistant_message_id": "a", "source_version": 1, "voice_mode": True,
                  "voice_call_id": "call"},
        dispatch_speech=dispatch,
    )
    tracker.observe("First sentence here. ")
    tracker.dispatch_status_utterance("I used web search.")
    tracker.observe("First sentence here. Second sentence here. ")
    await tracker.wait_for_handoff()
    await asyncio.sleep(0)

    assert spoken[0][0] == "voice_prose_clause"
    assert ("voice_status", -2) in spoken
    answer_sequences = [sequence for kind, sequence in spoken if kind == "voice_prose_clause"]
    assert answer_sequences == list(range(len(answer_sequences)))
    assert spoken.index(("voice_status", -2)) > 0


# contract-test: direct surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.asyncio
async def test_status_lines_are_dropped_outside_calls():
    spoken = []

    async def dispatch(segment):
        spoken.append(segment)

    tracker = ImmutableSpeechBoundaryTracker(
        metadata={"chat_id": "c", "assistant_message_id": "a", "source_version": 1}, dispatch_speech=dispatch,
    )
    tracker.dispatch_status_utterance("I used web search.")
    await tracker.wait_for_handoff()
    assert spoken == []


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_turn_language_follows_clearly_dominant_words_else_preference():
    from backend.apps.ai.assistant_speech.voice_status import detect_turn_language

    assert detect_turn_language("Bitte prüfe das gründlich", "en") == "de"
    assert detect_turn_language("Peux tu me dire comment faire", "en") == "fr"
    assert detect_turn_language("How do I make ramen?", "de") == "en"
    assert detect_turn_language("Paris", "de") == "de"
    assert detect_turn_language("", "es") == "es"


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_short_phrases_and_accents_are_recognised_and_unknown_stays_unknown():
    from backend.apps.ai.assistant_speech.voice_status import detect_turn_language

    assert detect_turn_language("Wie spät ist es", None) == "de"
    assert detect_turn_language("¿Qué hora es?", None) == "es"
    assert detect_turn_language("Où est la gare, s'il te plaît", None) == "fr"
    assert detect_turn_language("Paris", None) is None
    assert detect_turn_language("", None) is None


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_instant_acknowledgement_follows_call_language_and_is_silent_when_unknown(monkeypatch):
    from types import SimpleNamespace

    from backend.apps.ai.tasks import stream_consumer

    published: list[dict] = []

    async def capture(_cache, _channel, event, *_args):
        published.append(event)

    class Cache:
        def __init__(self, remembered):
            self.remembered = remembered

        async def get(self, key):
            return self.remembered if key.startswith("voice_call_last_language:") else None

    monkeypatch.setattr(stream_consumer, "_publish_to_redis", capture)
    mate = SimpleNamespace(id="mate", category="general_knowledge",
                           voice_profile=SimpleNamespace(key="sophia", version=1))

    def request(text, preference):
        return SimpleNamespace(
            voice_mode=True, auto_speak_response=True, is_external=False, is_incognito=False, mate_id=None,
            voice_call_id="call-1", current_user_content=text, message_history=[],
            user_preferences={"language": preference} if preference else {}, chat_id="chat", user_id_hash="u",
            assistant_response_source_revision=1, voice_turn_id="t",
        )

    async def play(text, preference, remembered=None):
        published.clear()
        sent = await stream_consumer.publish_instant_voice_acknowledgement(
            task_id="task-1", request_data=request(text, preference), all_mates_configs=[mate],
            cache_service=Cache(remembered), log_prefix="[test]",
        )
        return sent, [event["payload"]["clip_id"] for event in published]

    sent, clips = await play("Wie spät ist es", "en")
    assert sent and clips and "-de-DE-" in clips[0]
    sent, clips = await play("Hmm okay", "en", remembered="de")
    assert sent and "-de-DE-" in clips[0]
    assert await play("Hmm", None) == (False, [])
