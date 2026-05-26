# backend/tests/test_postprocessor.py
#
# Unit tests for postprocessor pure functions: skill/focus extraction from app
# metadata, and suggestion sanitization (prefix validation, min-word enforcement).
#
# Architecture: docs/architecture/follow_up_suggestions.md
# Run: python -m pytest backend/tests/test_postprocessor.py -v

import pytest

try:
    from backend.apps.ai.processing.postprocessor import (
        extract_available_skills,
        extract_available_focus_modes,
        handle_postprocessing,
        sanitize_suggestions,
    )
    from backend.apps.ai.processing.quick_tips import (
        sanitize_quick_tip_slug,
        select_hardcoded_quick_tip_slug,
    )
    from backend.apps.ai.utils.llm_utils import LLMPreprocessingCallResult
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for AppYAML / Skill / Focus dataclasses
# ---------------------------------------------------------------------------

class FakeSkill:
    def __init__(self, id: str, stage: str = "production", internal: bool = False, preprocessor_hint: str = ""):
        self.id = id
        self.stage = stage
        self.internal = internal
        self.preprocessor_hint = preprocessor_hint


class FakeFocus:
    def __init__(self, id: str, stage: str = "production", preprocessor_hint: str = ""):
        self.id = id
        self.stage = stage
        self.preprocessor_hint = preprocessor_hint


class FakeAppYAML:
    def __init__(self, skills=None, focuses=None):
        self.skills = skills or []
        self.focuses = focuses or []


# ===========================================================================
# extract_available_skills
# ===========================================================================

class TestExtractAvailableSkills:
    def test_empty_apps(self):
        assert extract_available_skills({}) == []

    def test_app_with_no_skills(self):
        apps = {"web": FakeAppYAML(skills=[])}
        assert extract_available_skills(apps) == []

    def test_production_skills_included(self):
        apps = {
            "web": FakeAppYAML(skills=[
                FakeSkill("search", stage="production", preprocessor_hint="Search the web"),
                FakeSkill("read", stage="production", preprocessor_hint="Read a page"),
            ])
        }
        result = extract_available_skills(apps)
        assert len(result) == 2
        assert result[0]["id"] == "web-search"
        assert result[0]["hint"] == "Search the web"
        assert result[1]["id"] == "web-read"

    def test_development_skills_excluded(self):
        apps = {
            "web": FakeAppYAML(skills=[
                FakeSkill("search", stage="production"),
                FakeSkill("beta_feature", stage="development"),
            ])
        }
        result = extract_available_skills(apps)
        assert len(result) == 1
        assert result[0]["id"] == "web-search"

    def test_internal_skills_excluded(self):
        apps = {
            "ai": FakeAppYAML(skills=[
                FakeSkill("ask", stage="production", internal=True),
                FakeSkill("generate", stage="production", internal=False),
            ])
        }
        result = extract_available_skills(apps)
        assert len(result) == 1
        assert result[0]["id"] == "ai-generate"

    def test_hint_truncated_at_150_chars(self):
        long_hint = "x" * 200
        apps = {
            "web": FakeAppYAML(skills=[
                FakeSkill("search", preprocessor_hint=long_hint),
            ])
        }
        result = extract_available_skills(apps)
        assert len(result[0]["hint"]) == 150
        assert result[0]["hint"].endswith("...")

    def test_missing_hint_defaults_to_empty(self):
        apps = {
            "web": FakeAppYAML(skills=[
                FakeSkill("search", preprocessor_hint=""),
            ])
        }
        result = extract_available_skills(apps)
        assert result[0]["hint"] == ""

    def test_multiple_apps(self):
        apps = {
            "web": FakeAppYAML(skills=[FakeSkill("search")]),
            "images": FakeAppYAML(skills=[FakeSkill("generate")]),
        }
        result = extract_available_skills(apps)
        ids = {r["id"] for r in result}
        assert "web-search" in ids
        assert "images-generate" in ids


# ===========================================================================
# extract_available_focus_modes
# ===========================================================================

class TestExtractAvailableFocusModes:
    def test_empty_apps(self):
        assert extract_available_focus_modes({}) == []

    def test_production_focuses_included(self):
        apps = {
            "jobs": FakeAppYAML(focuses=[
                FakeFocus("career_insights", stage="production", preprocessor_hint="Career help"),
            ])
        }
        result = extract_available_focus_modes(apps)
        assert len(result) == 1
        assert result[0]["id"] == "jobs-career_insights"
        assert result[0]["hint"] == "Career help"

    def test_non_production_excluded(self):
        apps = {
            "jobs": FakeAppYAML(focuses=[
                FakeFocus("career_insights", stage="production"),
                FakeFocus("beta_mode", stage="development"),
            ])
        }
        result = extract_available_focus_modes(apps)
        assert len(result) == 1

    def test_hint_truncated(self):
        long_hint = "y" * 200
        apps = {
            "jobs": FakeAppYAML(focuses=[
                FakeFocus("career", preprocessor_hint=long_hint),
            ])
        }
        result = extract_available_focus_modes(apps)
        assert len(result[0]["hint"]) == 150
        assert result[0]["hint"].endswith("...")

    def test_app_with_no_focuses(self):
        apps = {"web": FakeAppYAML(focuses=[])}
        assert extract_available_focus_modes(apps) == []


# ===========================================================================
# sanitize_suggestions
# ===========================================================================

class TestSanitizeSuggestions:
    """Tests for the suggestion prefix validator and MIN_BODY_WORDS enforcer."""

    VALID_SKILLS = {"web-search", "web-read", "images-generate"}
    VALID_FOCUSES = {"jobs-career_insights"}
    VALID_MEMORIES = {"ai-chat_history"}
    VALID_APPS = {"ai", "web", "images", "jobs"}

    def test_valid_skill_prefix_kept(self):
        suggestions = ["[web-search] Find the latest Python docs"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert result == ["[web-search] Find the latest Python docs"]

    def test_valid_app_only_prefix_kept(self):
        suggestions = ["[ai] Explain quantum computing in simple terms"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert result == ["[ai] Explain quantum computing in simple terms"]

    def test_invalid_prefix_replaced_with_ai_fallback(self):
        suggestions = ["[fake-skill] Explain quantum computing in detail"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert len(result) == 1
        assert result[0].startswith("[ai] ")
        assert "Explain quantum computing" in result[0]

    def test_no_prefix_gets_ai_prepended(self):
        suggestions = ["Explain quantum computing in simple terms"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert result == ["[ai] Explain quantum computing in simple terms"]

    def test_min_body_words_enforced_with_prefix(self):
        """Suggestions with <4 words in body (after prefix) are dropped."""
        suggestions = ["[ai] Too short"]  # 2 words
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert result == []

    def test_min_body_words_enforced_without_prefix(self):
        suggestions = ["Short one"]  # 2 words, no prefix
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert result == []

    def test_exactly_4_words_kept(self):
        suggestions = ["[ai] Four words body here"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert len(result) == 1

    def test_empty_suggestions_dropped(self):
        suggestions = ["", "   ", None, 42]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert result == []

    def test_memory_prefix_blocked_when_not_allowed(self):
        suggestions = ["[ai-chat_history] Recall what we discussed about Python"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, allow_memory_prefixes=False, task_id="test",
            valid_app_ids=self.VALID_APPS,
        )
        # Memory prefix is not in skill/focus/app sets, should be replaced with [ai]
        assert len(result) == 1
        assert result[0].startswith("[ai] ")

    def test_memory_prefix_allowed_when_flag_set(self):
        suggestions = ["[ai-chat_history] Recall what we discussed about Python"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, allow_memory_prefixes=True, task_id="test",
            valid_app_ids=self.VALID_APPS,
        )
        assert result == ["[ai-chat_history] Recall what we discussed about Python"]

    def test_focus_prefix_kept(self):
        suggestions = ["[jobs-career_insights] Help me prepare for interviews"]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert result == ["[jobs-career_insights] Help me prepare for interviews"]

    def test_mixed_valid_and_invalid(self):
        suggestions = [
            "[web-search] Find the latest Python release notes",  # valid
            "[hallucinated-skill] Do something cool and fun",     # invalid prefix
            "No prefix but enough words here",                     # no prefix
            "[ai] Short",                                          # too short
        ]
        result = sanitize_suggestions(
            suggestions, self.VALID_SKILLS, self.VALID_FOCUSES,
            self.VALID_MEMORIES, False, "test", self.VALID_APPS,
        )
        assert len(result) == 3
        assert result[0] == "[web-search] Find the latest Python release notes"
        assert result[1].startswith("[ai] Do something cool")
        assert result[2] == "[ai] No prefix but enough words here"


class TestQuickTips:
    def test_long_chat_selects_shorter_chats_tip(self):
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index}"}
            for index in range(11)
        ]
        assert select_hardcoded_quick_tip_slug(history) == "shorter-chats-equal-better-responses"

    def test_unknown_llm_slug_is_dropped(self):
        class Logger:
            def warning(self, *args, **kwargs):
                pass

        assert sanitize_quick_tip_slug("made-up-tip", ["web"], "test", Logger()) == ""

    def test_app_specific_slug_requires_available_app(self):
        class Logger:
            def warning(self, *args, **kwargs):
                pass

        assert sanitize_quick_tip_slug("travel-can-add-local-context", ["web"], "test", Logger()) == ""
        assert sanitize_quick_tip_slug("travel-can-add-local-context", ["travel"], "test", Logger()) == "travel-can-add-local-context"


@pytest.mark.anyio
async def test_postprocessing_translates_metadata_even_when_output_language_matches_ui(monkeypatch):
    """German-heavy history can produce German metadata even if output_language is misdetected as English."""

    async def fake_call_preprocessing_llm(**kwargs):
        return LLMPreprocessingCallResult(
            arguments={
                "follow_up_request_suggestions": ["[ai] Schreibe den nächsten Abschnitt"],
                "new_chat_request_suggestions": ["[ai] Create another job application draft"],
                "harmful_response": 0.0,
                "top_recommended_apps_for_user": ["ai"],
                "chat_summary": "Nutzer erstellt deutsche Bewerbungsunterlagen.",
                "updated_chat_title": "Bewerbungsunterlagen erstellen",
                "daily_inspiration_topic_suggestions": ["job applications", "cover letters", "career planning"],
                "quick_tip_slug": "",
            }
        )

    translations = []

    async def fake_translate_chat_summary(task_id, summary, target_language, secrets_manager):
        translations.append((summary, target_language))
        if summary == "Nutzer erstellt deutsche Bewerbungsunterlagen.":
            return "User creates German job application documents."
        if summary == "Bewerbungsunterlagen erstellen":
            return "Create Application Documents"
        return summary

    async def fake_translate_new_chat_suggestions(**kwargs):
        return kwargs["suggestions"]

    monkeypatch.setattr(
        "backend.apps.ai.processing.postprocessor.call_preprocessing_llm",
        fake_call_preprocessing_llm,
    )
    monkeypatch.setattr(
        "backend.apps.ai.processing.postprocessor.translate_chat_summary",
        fake_translate_chat_summary,
    )
    monkeypatch.setattr(
        "backend.apps.ai.processing.postprocessor.translate_new_chat_suggestions",
        fake_translate_new_chat_suggestions,
    )
    result = await handle_postprocessing(
        task_id="test-task",
        user_message="Please adjust the application letter.",
        assistant_response="Here is the updated section.",
        chat_summary="Existing summary",
        chat_tags=["jobs"],
        message_history=[
            {"role": "user", "content": "Bitte erstelle Bewerbungsunterlagen."},
            {"role": "assistant", "content": "Gerne, ich erstelle sie."},
        ],
        base_instructions={"postprocess_response_tool": {"type": "function", "function": {"name": "postprocess"}}},
        secrets_manager=None,
        cache_service=None,
        available_app_ids=["ai"],
        output_language="en",
        user_system_language="en",
        current_chat_title="Application Letter",
    )

    assert result.chat_summary == "User creates German job application documents."
    assert result.updated_chat_title == "Create Application Documents"
    assert translations == [
        ("Nutzer erstellt deutsche Bewerbungsunterlagen.", "en"),
        ("Bewerbungsunterlagen erstellen", "en"),
    ]
