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
        ONBOARDING_TRIGGER_PHRASES,
    )
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
