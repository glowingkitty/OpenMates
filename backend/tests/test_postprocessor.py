# backend/tests/test_postprocessor.py
#
# Unit tests for postprocessor pure functions: skill extraction from app
# metadata, plain suggestion sanitization, and 50/50 suggestion merging.
#
# Architecture: docs/architecture/follow_up_suggestions.md
# Run: python -m pytest backend/tests/test_postprocessor.py -v

import pytest

try:
    from backend.apps.ai.processing.postprocessor import (
        extract_available_skills,
        handle_postprocessing,
        combine_suggestion_halves,
        sanitize_plain_suggestions,
    )
    from backend.apps.ai.processing.quick_tips import (
        sanitize_quick_tip_slug,
        select_hardcoded_quick_tip_slug,
    )
    from backend.apps.ai.utils.llm_utils import LLMPreprocessingCallResult
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for AppYAML / Skill dataclasses
# ---------------------------------------------------------------------------

class FakeSkill:
    def __init__(self, id: str, stage: str = "production", internal: bool = False, preprocessor_hint: str = ""):
        self.id = id
        self.stage = stage
        self.internal = internal
        self.preprocessor_hint = preprocessor_hint


class FakeAppYAML:
    def __init__(self, skills=None):
        self.skills = skills or []


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
# sanitize_plain_suggestions / combine_suggestion_halves
# ===========================================================================

class TestPlainSuggestions:
    """Tests natural-language-only suggestion sanitization and 50/50 merging."""

    def test_plain_suggestion_kept(self):
        result = sanitize_plain_suggestions(
            ["Find upcoming drawing workshops in Berlin"], "test", "follow-up app-skill"
        )
        assert result == ["Find upcoming drawing workshops in Berlin"]

    def test_bracket_prefix_rejected(self):
        result = sanitize_plain_suggestions(
            ["[events-search] Find upcoming drawing workshops in Berlin"],
            "test",
            "follow-up app-skill",
        )
        assert result == []

    def test_skill_mention_rejected(self):
        result = sanitize_plain_suggestions(
            ["@skill:events:search Find upcoming drawing workshops in Berlin"],
            "test",
            "follow-up app-skill",
        )
        assert result == []

    def test_min_words_enforced(self):
        result = sanitize_plain_suggestions(["Short one"], "test", "follow-up general")
        assert result == []

    def test_exactly_4_words_kept(self):
        result = sanitize_plain_suggestions(["Four words body here"], "test", "follow-up general")
        assert len(result) == 1

    def test_cjk_suggestion_without_spaces_kept(self):
        result = sanitize_plain_suggestions(["搜索柏林附近的绘画工作坊"], "test", "follow-up app-skill")
        assert result == ["搜索柏林附近的绘画工作坊"]

    def test_combines_strict_50_50_in_pairs(self):
        result = combine_suggestion_halves(
            app_skill_suggestions=[
                "Find upcoming drawing workshops in Berlin",
                "Search for iPhone recording apps",
                "Compare wireless microphones for interviews",
            ],
            general_suggestions=[
                "Explain why microphones may fail",
                "List common outdoor recording mistakes",
                "Compare wired and Bluetooth tradeoffs",
            ],
            task_id="test",
            label="follow-up",
        )
        assert result == [
            "Find upcoming drawing workshops in Berlin",
            "Explain why microphones may fail",
            "Search for iPhone recording apps",
            "List common outdoor recording mistakes",
            "Compare wireless microphones for interviews",
            "Compare wired and Bluetooth tradeoffs",
        ]

    def test_combination_preserves_ratio_by_not_filling_missing_half(self):
        result = combine_suggestion_halves(
            app_skill_suggestions=["Find upcoming drawing workshops in Berlin"],
            general_suggestions=[
                "Explain why microphones may fail",
                "List common outdoor recording mistakes",
                "Compare wired and Bluetooth tradeoffs",
            ],
            task_id="test",
            label="follow-up",
        )
        assert result == [
            "Find upcoming drawing workshops in Berlin",
            "Explain why microphones may fail",
        ]


class TestQuickTips:
    def test_long_chat_selects_shorter_chats_tip(self):
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index}"}
            for index in range(11)
        ]
        assert select_hardcoded_quick_tip_slug(history) == "shorter-chats-equal-better-responses"

    def test_travel_context_selects_travel_tip(self):
        history = [
            {
                "role": "user",
                "content": "Give one concise sentence about planning food, transit, and local events for a weekend trip.",
            }
        ]
        assert select_hardcoded_quick_tip_slug(history, ["travel"]) == "travel-can-add-local-context"
        assert select_hardcoded_quick_tip_slug(history, ["web"]) is None

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
                "follow_up_app_skill_suggestions": ["Finde passende Stellenangebote in Berlin"],
                "follow_up_general_suggestions": ["Schreibe den nächsten Abschnitt weiter"],
                "new_chat_app_skill_suggestions": ["Find matching job openings in Berlin"],
                "new_chat_general_suggestions": ["Create another job application draft"],
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


@pytest.mark.anyio
async def test_handle_postprocessing_removes_disabled_fields_from_tool_schema(monkeypatch):
    captured_tool = {}

    async def fake_call_preprocessing_llm(**kwargs):
        captured_tool.update(kwargs["tool_definition"])
        return LLMPreprocessingCallResult(
            arguments={
                "new_chat_app_skill_suggestions": ["Find recent articles about learning science"],
                "new_chat_general_suggestions": ["Explain another related concept clearly"],
                "harmful_response": 0.0,
                "top_recommended_apps_for_user": [],
                "chat_summary": "A concise summary.",
                "updated_chat_title": "",
                "daily_inspiration_topic_suggestions": ["learning science", "memory techniques", "study planning"],
            }
        )

    async def fake_translate_chat_summary(task_id, summary, target_language, secrets_manager):
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

    base_tool = {
        "type": "function",
        "function": {
            "name": "postprocess",
            "parameters": {
                "type": "object",
                "properties": {
                    "follow_up_app_skill_suggestions": {"type": "array"},
                    "follow_up_general_suggestions": {"type": "array"},
                    "new_chat_app_skill_suggestions": {"type": "array"},
                    "new_chat_general_suggestions": {"type": "array"},
                    "quick_tip_slug": {"type": "string"},
                    "chat_summary": {"type": "string"},
                },
                "required": [
                    "follow_up_app_skill_suggestions",
                    "follow_up_general_suggestions",
                    "new_chat_app_skill_suggestions",
                    "new_chat_general_suggestions",
                    "quick_tip_slug",
                    "chat_summary",
                ],
            },
        },
    }

    result = await handle_postprocessing(
        task_id="test-task",
        user_message="Tell me something useful.",
        assistant_response="Here is a useful answer.",
        chat_summary="Existing summary",
        chat_tags=["learning"],
        message_history=[{"role": "user", "content": "Tell me something useful."}],
        base_instructions={"postprocess_response_tool": base_tool},
        secrets_manager=None,
        cache_service=None,
        available_app_ids=["ai"],
        follow_up_suggestions_enabled=False,
        quick_tips_enabled=False,
    )

    properties = captured_tool["function"]["parameters"]["properties"]
    required = captured_tool["function"]["parameters"]["required"]
    assert "follow_up_app_skill_suggestions" not in properties
    assert "follow_up_general_suggestions" not in properties
    assert "quick_tip_slug" not in properties
    assert "follow_up_app_skill_suggestions" not in required
    assert "follow_up_general_suggestions" not in required
    assert "quick_tip_slug" not in required
    assert result.follow_up_request_suggestions == []
    assert result.quick_tip_slugs == []
