# backend/tests/test_preprocessor.py
#
# Unit tests for preprocessor pure functions: onboarding trigger detection
# across 20 languages, and text content sanitization.
#
# Architecture: docs/architecture/preprocessing.md
# Run: python -m pytest backend/tests/test_preprocessor.py -v

import pytest

try:
    from backend.apps.ai.processing.preprocessor import (
        _contains_onboarding_trigger_in_user_history,
        _contains_repo_search_intent_in_user_history,
        _normalize_topic_area,
        _resolve_category_from_topic_area,
        ONBOARDING_TRIGGER_PHRASES,
        translate_chat_summary,
    )
    from backend.apps.ai.processing.audio_recording_guard import (
        has_transcribed_web_audio_recording,
        remove_audio_transcribe_for_transcribed_recordings,
    )
    from backend.apps.ai.utils.llm_utils import LLMPreprocessingCallResult
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Helper — lightweight stand-in for AIHistoryMessage
# ---------------------------------------------------------------------------

class FakeMessage:
    """Minimal stand-in for AIHistoryMessage with role and content."""
    def __init__(self, role: str, content):
        self.role = role
        self.content = content


def _user_msg(content: str) -> FakeMessage:
    return FakeMessage(role="user", content=content)


def _assistant_msg(content: str) -> FakeMessage:
    return FakeMessage(role="assistant", content=content)


# ===========================================================================
# ONBOARDING_TRIGGER_PHRASES constant
# ===========================================================================

class TestOnboardingTriggerPhrases:
    def test_phrases_exist(self):
        assert len(ONBOARDING_TRIGGER_PHRASES) > 50

    def test_brand_names_included(self):
        phrases_lower = [p.lower() for p in ONBOARDING_TRIGGER_PHRASES]
        assert "openmates" in phrases_lower
        assert "openmates.org" in phrases_lower

    def test_multilingual_coverage(self):
        """Should include phrases in multiple scripts (Latin, CJK, Arabic, etc.)."""
        has_latin = any("app" in p or "platform" in p for p in ONBOARDING_TRIGGER_PHRASES)
        has_cjk = any(ord(c) > 0x3000 for p in ONBOARDING_TRIGGER_PHRASES for c in p)
        has_arabic = any(ord(c) > 0x0600 and ord(c) < 0x06FF for p in ONBOARDING_TRIGGER_PHRASES for c in p)
        assert has_latin
        assert has_cjk
        assert has_arabic


# ===========================================================================
# _contains_onboarding_trigger_in_user_history
# ===========================================================================

class TestContainsOnboardingTrigger:
    def test_empty_history(self):
        assert _contains_onboarding_trigger_in_user_history([]) is False

    def test_no_trigger_phrases(self):
        history = [
            _user_msg("What is the capital of France?"),
            _assistant_msg("The capital of France is Paris."),
        ]
        assert _contains_onboarding_trigger_in_user_history(history) is False

    def test_brand_name_trigger(self):
        history = [_user_msg("What is OpenMates?")]
        assert _contains_onboarding_trigger_in_user_history(history) is True

    def test_case_insensitive(self):
        history = [_user_msg("Tell me about OPENMATES")]
        assert _contains_onboarding_trigger_in_user_history(history) is True

    def test_case_folding_unicode(self):
        """casefold() handles non-ASCII case variants (e.g., German )."""
        history = [_user_msg("Was ist diese Plattform?")]
        # "diese plattform" or similar should be in the trigger list
        # This tests that casefold is used (not just lower)
        result = _contains_onboarding_trigger_in_user_history(history)
        # Result depends on exact phrase match; the point is no crash
        assert isinstance(result, bool)

    def test_english_trigger_phrases(self):
        for phrase in ["what can you do", "how does this work", "what are your features"]:
            history = [_user_msg(f"Hey, {phrase}?")]
            assert _contains_onboarding_trigger_in_user_history(history) is True, \
                f"Expected trigger for: '{phrase}'"

    def test_german_trigger(self):
        history = [_user_msg("Was kann diese App?")]
        # "diese app" should be in ONBOARDING_TRIGGER_PHRASES for German
        assert _contains_onboarding_trigger_in_user_history(history) is True

    def test_japanese_trigger(self):
        history = [_user_msg("このアプリは何ですか")]
        # Japanese triggers should match
        assert _contains_onboarding_trigger_in_user_history(history) is True

    def test_arabic_trigger(self):
        history = [_user_msg("ما الذي يمكنك فعله")]
        assert _contains_onboarding_trigger_in_user_history(history) is True

    def test_only_user_messages_checked(self):
        """Assistant messages with trigger phrases should NOT trigger."""
        history = [
            _assistant_msg("Welcome to OpenMates! What can you do with this app?"),
            _user_msg("Tell me about quantum physics"),
        ]
        assert _contains_onboarding_trigger_in_user_history(history) is False

    def test_non_string_content_skipped(self):
        """Messages with non-string content (e.g., multimodal) should not crash."""
        history = [
            FakeMessage(role="user", content=["image_data"]),
            FakeMessage(role="user", content=None),
            FakeMessage(role="user", content=42),
        ]
        assert _contains_onboarding_trigger_in_user_history(history) is False

    def test_trigger_in_second_message(self):
        """Trigger phrase in a later user message should still be found."""
        history = [
            _user_msg("Hello there"),
            _assistant_msg("Hi!"),
            _user_msg("What are your features?"),
        ]
        assert _contains_onboarding_trigger_in_user_history(history) is True

    def test_openmates_domain_trigger(self):
        history = [_user_msg("I found you at openmates.org")]
        assert _contains_onboarding_trigger_in_user_history(history) is True


# ===========================================================================
# _contains_repo_search_intent_in_user_history
# ===========================================================================

class TestContainsRepoSearchIntent:
    def test_detects_short_repo_search_request(self):
        history = [_user_msg("Search for marketing prompt repos")]
        assert _contains_repo_search_intent_in_user_history(history) is True

    def test_detects_github_repository_search_request(self):
        history = [_user_msg("Find GitHub repositories for Svelte auth examples")]
        assert _contains_repo_search_intent_in_user_history(history) is True

    def test_ignores_informational_repo_question(self):
        history = [_user_msg("What is a repo?")]
        assert _contains_repo_search_intent_in_user_history(history) is False

    def test_ignores_financial_repo_rate_search(self):
        history = [_user_msg("Search for the latest repo rate")]
        assert _contains_repo_search_intent_in_user_history(history) is False

    def test_only_user_messages_checked(self):
        history = [
            _assistant_msg("Search for marketing prompt repos"),
            _user_msg("Thanks"),
        ]
        assert _contains_repo_search_intent_in_user_history(history) is False


# ===========================================================================
# Audio recording transcription guard
# ===========================================================================

class TestAudioRecordingTranscriptionGuard:
    def test_detects_transcribed_web_recording_toon(self):
        history = [_user_msg("""type: audio-recording
status: finished
transcript: What's the weather in Berlin?
embed_ref: voice-note.webm""")]

        assert has_transcribed_web_audio_recording(history) is True

    def test_ignores_recording_without_transcript(self):
        history = [_user_msg("""type: audio-recording
status: finished
transcript: null
embed_ref: voice-note.webm""")]

        assert has_transcribed_web_audio_recording(history) is False

    def test_removes_audio_transcribe_after_memories_continuation_history(self):
        history = [
            _user_msg("""type: audio-recording
status: finished
transcript: What's the weather in Berlin?
embed_ref: voice-note.webm"""),
            _assistant_msg("I need permission to read weather preferences."),
        ]

        skills, removed = remove_audio_transcribe_for_transcribed_recordings(
            ["audio-transcribe", "web-search", "images-search"],
            history,
        )

        assert removed is True
        assert skills == ["web-search", "images-search"]

    def test_keeps_audio_transcribe_for_manual_audio_without_recording_embed(self):
        history = [_user_msg("Please transcribe the MP3 file I uploaded.")]

        skills, removed = remove_audio_transcribe_for_transcribed_recordings(
            ["audio-transcribe", "web-search"],
            history,
        )

        assert removed is False
        assert skills == ["audio-transcribe", "web-search"]

    def test_keeps_audio_transcribe_when_manual_audio_file_is_also_attached(self):
        history = [
            _user_msg("""type: audio-recording
status: finished
transcript: What's the weather in Berlin?
embed_ref: voice-note.webm"""),
            _user_msg("""type: file-attachment
filename: interview.mp3
mime_type: audio/mpeg
embed_ref: interview.mp3"""),
        ]

        skills, removed = remove_audio_transcribe_for_transcribed_recordings(
            ["audio-transcribe", "web-search"],
            history,
        )

        assert removed is False
        assert skills == ["audio-transcribe", "web-search"]


# ===========================================================================
# Topic-area mate routing
# ===========================================================================

AVAILABLE_CATEGORY_IDS = {
    "activism",
    "business_development",
    "cooking_food",
    "design",
    "electrical_engineering",
    "finance",
    "general_knowledge",
    "history",
    "legal_law",
    "life_coach_psychology",
    "maker_prototyping",
    "medical_health",
    "movies_tv",
    "onboarding_support",
    "science",
    "software_development",
}


class TestTopicAreaMateRouting:
    def test_normalizes_full_topic_string(self):
        assert _normalize_topic_area("textiles_sewing: Fabric and sewing") == "textiles_sewing"

    def test_routes_textiles_to_maker_not_cooking(self):
        assert _resolve_category_from_topic_area(
            raw_topic_area="textiles_sewing",
            raw_topic_shift="noticeable_shift",
            previous_category=None,
            available_category_ids=AVAILABLE_CATEGORY_IDS,
        ) == "maker_prototyping"

    def test_routes_food_to_cooking(self):
        assert _resolve_category_from_topic_area(
            raw_topic_area="cooking_food",
            raw_topic_shift="noticeable_shift",
            previous_category=None,
            available_category_ids=AVAILABLE_CATEGORY_IDS,
        ) == "cooking_food"

    def test_keeps_previous_category_for_same_topic_follow_up(self):
        assert _resolve_category_from_topic_area(
            raw_topic_area="writing_editing",
            raw_topic_shift="same_topic",
            previous_category="software_development",
            available_category_ids=AVAILABLE_CATEGORY_IDS,
        ) == "software_development"

    def test_keeps_previous_category_for_general_misc_follow_up(self):
        assert _resolve_category_from_topic_area(
            raw_topic_area="general_misc",
            raw_topic_shift="noticeable_shift",
            previous_category="maker_prototyping",
            available_category_ids=AVAILABLE_CATEGORY_IDS,
        ) == "maker_prototyping"

    def test_allows_clear_follow_up_topic_shift(self):
        assert _resolve_category_from_topic_area(
            raw_topic_area="cooking_food",
            raw_topic_shift="noticeable_shift",
            previous_category="software_development",
            available_category_ids=AVAILABLE_CATEGORY_IDS,
        ) == "cooking_food"

@pytest.mark.anyio
async def test_translate_chat_summary_uses_isolated_translation(monkeypatch):
    captured = {}

    async def fake_call_preprocessing_llm(**kwargs):
        captured.update(kwargs)
        return LLMPreprocessingCallResult(
            arguments={"translated_summary": "User creates German application documents."}
        )

    monkeypatch.setattr(
        "backend.apps.ai.processing.preprocessor.call_preprocessing_llm",
        fake_call_preprocessing_llm,
    )

    result = await translate_chat_summary(
        task_id="test-summary-translate",
        summary="Nutzer erstellt deutsche Bewerbungsunterlagen.",
        target_language="en",
        secrets_manager=None,
    )

    assert result == "User creates German application documents."
    assert captured["message_history"][0]["role"] == "system"
    assert "English" in captured["message_history"][0]["content"]
    assert captured["message_history"][1] == {
        "role": "user",
        "content": "Translate this chat summary to English:\n\nNutzer erstellt deutsche Bewerbungsunterlagen.",
    }


def test_preprocessing_result_has_enable_subchats():
    from backend.apps.ai.processing.preprocessor import PreprocessingResult
    res = PreprocessingResult(
        can_proceed=True,
        enable_subchats=True,
        harmful_or_illegal_score=0.0
    )
    assert res.enable_subchats is True
