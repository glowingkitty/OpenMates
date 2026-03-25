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
        sanitize_suggestions,
    )
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
