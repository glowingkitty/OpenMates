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


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.waiting-language
def test_instant_acknowledgement_is_silent_for_unsupported_language():
    assert select_instant_acknowledgement(
        voice_profile_id="sophia", voice_profile_version=1, language="ja", seed="message-1") is None


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.skills-announcement
def test_app_use_announcement_is_localized_without_english_fallback():
    assert "apps" in build_voice_app_use_announcement("en-US", "m1").lower()
    assert "Apps" in build_voice_app_use_announcement("de", "m1")
    assert build_voice_app_use_announcement("ja", "m1") is None


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.skills-announcement
def test_recap_names_the_skills_that_ran_once_in_order():
    skills = [("web", "search"), ("news", "search"), ("web", "search")]
    assert build_skill_recap(skills, "en") == "I used web search and news search."
    assert build_skill_recap([("web", "search")], "de") == "Ich habe die Websuche verwendet."


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.waiting-language,video-call.audio.skills-announcement
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


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.waiting-language
def test_turn_language_follows_clearly_dominant_words_else_preference():
    from backend.apps.ai.assistant_speech.voice_status import detect_turn_language

    assert detect_turn_language("Bitte prüfe das gründlich", "en") == "de"
    assert detect_turn_language("Peux tu me dire comment faire", "en") == "fr"
    assert detect_turn_language("How do I make ramen?", "de") == "en"
    assert detect_turn_language("Paris", "de") == "de"
    assert detect_turn_language("", "es") == "es"


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.waiting-language
def test_short_phrases_and_accents_are_recognised_and_unknown_stays_unknown():
    from backend.apps.ai.assistant_speech.voice_status import detect_turn_language

    assert detect_turn_language("Wie spät ist es", None) == "de"
    assert detect_turn_language("¿Qué hora es?", None) == "es"
    assert detect_turn_language("Où est la gare, s'il te plaît", None) == "fr"
    assert detect_turn_language("Paris", None) is None
    assert detect_turn_language("", None) is None


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting,video-call.audio.waiting-language
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
            task_id="task-1", request_data=request(text, preference), mate=mate,
            cache_service=Cache(remembered), log_prefix="[test]",
        )
        return sent, [event["payload"]["clip_id"] for event in published]

    sent, clips = await play("Wie spät ist es", "en")
    assert sent and clips and "-de-DE-" in clips[0]
    sent, clips = await play("Hmm okay", "en", remembered="de")
    assert sent and "-de-DE-" in clips[0]
    assert await play("Hmm", None) == (False, [])


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_instant_acknowledgement_uses_only_the_answering_mates_voice(monkeypatch):
    """Before routing an unchosen Mate is unknown: no guessed (default or previous) voice plays."""
    from types import SimpleNamespace

    from backend.apps.ai.processing.preprocessor import _resolve_explicit_mate
    from backend.apps.ai.tasks import stream_consumer

    published: list[dict] = []

    async def capture(_cache, _channel, event, *_args):
        published.append(event)

    monkeypatch.setattr(stream_consumer, "_publish_to_redis", capture)
    george = SimpleNamespace(id="george_mate", category="general_knowledge",
                             voice_profile=SimpleNamespace(key="george", version=2))
    sophia = SimpleNamespace(id="sophia_mate", category="software_development",
                             voice_profile=SimpleNamespace(key="sophia", version=2))
    request = SimpleNamespace(
        voice_mode=True, auto_speak_response=True, is_external=False, is_incognito=False, mate_id=None,
        voice_call_id="call-1", current_user_content="What is the weather", message_history=[],
        user_preferences={"language": "en"}, chat_id="chat", user_id_hash="u",
    )

    # Automatic routing: nothing is explicit yet, so the pre-routing clip stays silent.
    explicit, _source = _resolve_explicit_mate([george, sophia], None, request.mate_id)
    assert explicit is None
    assert not await stream_consumer.publish_instant_voice_acknowledgement(
        task_id="task-1", request_data=request, mate=explicit, cache_service=None, log_prefix="[test]",
    )
    assert published == []

    # After routing (or for an explicitly chosen Mate) the clip is that Mate's voice.
    assert await stream_consumer.publish_instant_voice_acknowledgement(
        task_id="task-1", request_data=request, mate=sophia, cache_service=None, log_prefix="[test]",
    )
    assert published[0]["payload"]["clip_id"].startswith("sophia-en-US-")
    assert published[0]["payload"]["audio_url"].startswith("/audio/assistant-acknowledgements/sophia/")


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_new_chat_is_confirmed_in_the_neutral_system_voice_never_a_mate_voice():
    from backend.apps.ai.assistant_speech.voice_status import select_chat_start_confirmation

    english = select_chat_start_confirmation(language="en")
    assert english["clip_id"] == "system-en-US-chat_start-1"
    assert english["voice_profile_id"] == "system"
    assert english["asset_url"] == "/audio/assistant-acknowledgements/system/en-US/chat_start-1.mp3"
    assert select_chat_start_confirmation(language="de-DE")["clip_id"] == "system-de-DE-chat_start-1"
    # No recorded clip for the language: silent, never English.
    assert select_chat_start_confirmation(language="ja") is None


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
def test_only_a_chat_without_title_and_assistant_turn_has_no_mate_yet():
    from types import SimpleNamespace

    from backend.apps.ai.assistant_speech.voice_status import chat_has_no_mate_yet

    user = SimpleNamespace(role="user", content="Hallo")
    assistant = SimpleNamespace(role="assistant", content="Hi")
    assert chat_has_no_mate_yet(chat_has_title=False, message_history=[user])
    assert chat_has_no_mate_yet(chat_has_title=False, message_history=[])
    assert not chat_has_no_mate_yet(chat_has_title=True, message_history=[user])
    assert not chat_has_no_mate_yet(chat_has_title=False, message_history=[user, assistant, user])
    assert not chat_has_no_mate_yet(chat_has_title=False, message_history=[{"role": "assistant"}])


# contract-test: direct surface=rest_api assertions=video-call.audio.localized-waiting
async def test_chat_start_confirmation_is_the_single_clip_of_the_turn(monkeypatch):
    """The system clip plays at once; after routing no second (Mate) clip follows."""
    from types import SimpleNamespace

    from backend.apps.ai.tasks import stream_consumer

    published: list[dict] = []

    async def capture(_cache, _channel, event, *_args):
        published.append(event)

    monkeypatch.setattr(stream_consumer, "_publish_to_redis", capture)

    def request(**overrides):
        values = dict(
            voice_mode=True, auto_speak_response=True, is_external=False, is_incognito=False, mate_id=None,
            voice_call_id=None, current_user_content="Wie spät ist es", message_history=[],
            user_preferences={"language": "en"}, chat_id="chat", user_id_hash="u", continuation_message_id=None,
        )
        return SimpleNamespace(**(values | overrides))

    assert await stream_consumer.publish_chat_start_voice_confirmation(
        task_id="task-new-chat", request_data=request(), cache_service=None, log_prefix="[test]",
    )
    assert [event["payload"]["clip_id"] for event in published] == ["system-de-DE-chat_start-1"]
    assert published[0]["payload"]["audio_url"].startswith("/audio/assistant-acknowledgements/system/")
    # The speech setup after routing finds the turn already confirmed.
    assert stream_consumer._INSTANT_ACK_SENT.pop("task-new-chat", 0) is None

    published.clear()
    # Typed (non-call) turns, incognito and unknown languages stay silent.
    for silent in (request(voice_mode=False), request(is_incognito=True),
                   request(current_user_content="Paris", user_preferences={})):
        assert not await stream_consumer.publish_chat_start_voice_confirmation(
            task_id="task-silent", request_data=silent, cache_service=None, log_prefix="[test]",
        )
    assert published == []
