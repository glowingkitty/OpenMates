"""Tests for age-tiered Learning Mode teaching and the collaborative-building toggle.

Collaborative building loosens only the code and app guardrails. Every test
here either proves that loosening or proves what stays locked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.apps.ai.assistant_speech.voice_context import (
    VOICE_LEARNING_FOCUS_INSTRUCTION_KEY,
    build_voice_learning_focus_instruction,
)
from backend.apps.ai.utils.mate_utils import load_mates_config, select_mate_system_prompt
from backend.shared.python_utils.learning_mode import (
    AGE_GROUP_10_12,
    AGE_GROUP_13_15,
    AGE_GROUP_16_18,
    AGE_GROUP_ADULT,
    AGE_GROUP_RUBRIC,
    AGE_GROUP_UNDER_10,
    LEARNING_MODE_COLLABORATIVE_CODE_MAX_LINES,
    LEARNING_MODE_COLLABORATIVE_PROMPT_MARKER,
    LEARNING_MODE_GLOBAL_PROMPT_MARKER,
    MAX_FAILED_DEACTIVATION_ATTEMPTS,
    VALID_AGE_GROUPS,
    LearningModeError,
    activate_learning_mode_policy,
    apply_learning_mode_cap_to_embed_result,
    apply_learning_mode_policy_to_skill_result,
    build_anonymous_request_learning_mode_context,
    build_learning_mode_context,
    build_learning_mode_global_prompt,
    filter_learning_mode_suggestions,
    is_collaborative_build_enabled,
    is_learning_mode_blocked_skill,
    learning_mode_context_from_preferences,
    set_collaborative_build_policy,
    should_disable_learning_mode_application_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MATES_DIR = REPO_ROOT / "backend/apps/ai/mates"
PASSCODE = "family-pin-123"
NOW = 1_800_000_000


def _policy(age_group: str, collaborative: bool | None = None) -> dict:
    return activate_learning_mode_policy(
        PASSCODE, age_group, now=NOW, collaborative_build=collaborative
    )


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-toggle
@pytest.mark.parametrize("age_group", sorted(VALID_AGE_GROUPS - {AGE_GROUP_UNDER_10}))
def test_activation_defaults_collaborative_on_from_age_ten(age_group: str) -> None:
    assert _policy(age_group)["learning_mode_collaborative_build"] is True
    assert _policy(age_group, False)["learning_mode_collaborative_build"] is False


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-toggle
def test_under_ten_is_always_teach_first_even_when_requested() -> None:
    assert _policy(AGE_GROUP_UNDER_10)["learning_mode_collaborative_build"] is False
    assert _policy(AGE_GROUP_UNDER_10, True)["learning_mode_collaborative_build"] is False


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-toggle
def test_accounts_that_predate_the_toggle_stay_strict() -> None:
    legacy = {"learning_mode_enabled": True, "learning_mode_age_group": AGE_GROUP_13_15}
    context = build_learning_mode_context(legacy)
    assert context["collaborative_build"] is False
    assert not is_collaborative_build_enabled(context)
    # A stored True under 10 can never become effective.
    under_ten = {**_policy(AGE_GROUP_UNDER_10), "learning_mode_collaborative_build": True}
    assert build_learning_mode_context(under_ten)["collaborative_build"] is False


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-toggle
def test_turning_collaborative_off_needs_no_passcode() -> None:
    updated = set_collaborative_build_policy(
        _policy(AGE_GROUP_13_15), enabled=False, passcode=None, now=NOW
    )
    assert updated["learning_mode_collaborative_build"] is False


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-toggle
def test_turning_collaborative_on_needs_the_passcode_and_shares_the_lockout() -> None:
    policy = set_collaborative_build_policy(
        _policy(AGE_GROUP_13_15, False), enabled=True, passcode=PASSCODE, now=NOW
    )
    assert policy["learning_mode_collaborative_build"] is True

    strict = _policy(AGE_GROUP_13_15, False)
    for attempt in range(1, MAX_FAILED_DEACTIVATION_ATTEMPTS + 1):
        with pytest.raises(LearningModeError) as exc_info:
            set_collaborative_build_policy(strict, enabled=True, passcode="wrong", now=NOW + attempt)
        assert exc_info.value.reason == "wrong_passcode"
        strict = exc_info.value.updated_policy
    assert strict["learning_mode_collaborative_build"] is False
    assert strict["learning_mode_deactivation_blocked_until"] is not None

    with pytest.raises(LearningModeError) as exc_info:
        set_collaborative_build_policy(strict, enabled=True, passcode=PASSCODE, now=NOW + 10)
    assert exc_info.value.reason == "blocked"


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-toggle
def test_collaborative_toggle_rejects_under_ten_and_inactive_learning_mode() -> None:
    with pytest.raises(LearningModeError) as exc_info:
        set_collaborative_build_policy(
            _policy(AGE_GROUP_UNDER_10), enabled=True, passcode=PASSCODE, now=NOW
        )
    assert exc_info.value.reason == "age_not_supported"
    with pytest.raises(LearningModeError) as exc_info:
        set_collaborative_build_policy({}, enabled=False, passcode=None, now=NOW)
    assert exc_info.value.reason == "learning_mode_inactive"


# contract-test: supporting surface=rest_api assertions=learning-mode.anonymous-client-side
def test_anonymous_context_accepts_only_the_three_teaching_fields() -> None:
    context = build_anonymous_request_learning_mode_context(
        {
            "enabled": True,
            "age_group": AGE_GROUP_13_15,
            "collaborative_build": True,
            "passcode": "never-sent",
            "passcode_hash": "never-sent",
        }
    )
    assert context == {
        "enabled": True,
        "age_group": AGE_GROUP_13_15,
        "collaborative_build": True,
        "source": "anonymous_session",
    }
    under_ten = build_anonymous_request_learning_mode_context(
        {"enabled": True, "age_group": AGE_GROUP_UNDER_10, "collaborative_build": True}
    )
    assert under_ten["collaborative_build"] is False


# contract-test: supporting surface=rest_api assertions=learning-mode.age-rubric
@pytest.mark.parametrize("age_group", sorted(VALID_AGE_GROUPS))
def test_every_age_group_prompt_carries_its_rubric(age_group: str) -> None:
    prompt = build_learning_mode_global_prompt(age_group)
    assert LEARNING_MODE_GLOBAL_PROMPT_MARKER in prompt
    for key in ("reading", "terms", "analogies", "tone", "questions", "check_in"):
        assert AGE_GROUP_RUBRIC[age_group][key] in prompt


# contract-test: supporting surface=rest_api assertions=learning-mode.age-rubric
def test_rubric_questions_per_turn_grow_with_age() -> None:
    assert "exactly one" in AGE_GROUP_RUBRIC[AGE_GROUP_UNDER_10]["questions"]
    assert "at most one" in AGE_GROUP_RUBRIC[AGE_GROUP_10_12]["questions"]
    assert "at most two" in AGE_GROUP_RUBRIC[AGE_GROUP_16_18]["questions"]
    assert "emoji" not in AGE_GROUP_RUBRIC[AGE_GROUP_ADULT]["tone"].replace("no emojis", "")


# contract-test: supporting surface=rest_api assertions=learning-mode.term-definitions
def test_term_definitions_use_wiki_links_except_for_the_youngest() -> None:
    for age_group in (AGE_GROUP_10_12, AGE_GROUP_13_15, AGE_GROUP_16_18, AGE_GROUP_ADULT):
        prompt = build_learning_mode_global_prompt(age_group)
        assert "[term](wiki:Article_Title)" in prompt
        assert "first time" in prompt
        assert "Never define or link the same term again" in prompt
    young = build_learning_mode_global_prompt(AGE_GROUP_UNDER_10)
    assert "wiki:Article_Title" not in young
    assert "avoid jargon" in young


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-building
def test_strict_prompt_keeps_teach_first_and_collaborative_prompt_replaces_it() -> None:
    strict = build_learning_mode_global_prompt(AGE_GROUP_13_15)
    assert "Do not generate complete projects" in strict
    assert LEARNING_MODE_COLLABORATIVE_PROMPT_MARKER not in strict

    collaborative = build_learning_mode_global_prompt(AGE_GROUP_13_15, collaborative_build=True)
    assert LEARNING_MODE_COLLABORATIVE_PROMPT_MARKER in collaborative
    assert "Do not generate complete projects" not in collaborative
    for required in (
        "at most 2-3 questions",
        "Diagrams app",
        "previewed right in the chat",
        "own project or a graded",
        "published or shared publicly",
        "read the error message together",
    ):
        assert required in collaborative
    # Still locked while building together.
    assert "answers to unanswered practice exercises are never given" in collaborative
    assert "calculation results stay hidden" in collaborative


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-building
def test_collaborative_prompt_is_never_applied_under_ten() -> None:
    prompt = build_learning_mode_global_prompt(AGE_GROUP_UNDER_10, collaborative_build=True)
    assert LEARNING_MODE_COLLABORATIVE_PROMPT_MARKER not in prompt


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-building
def test_collaborative_guardrails_loosen_code_and_apps_only() -> None:
    strict = {"enabled": True, "age_group": AGE_GROUP_13_15, "collaborative_build": False}
    collaborative = {"enabled": True, "age_group": AGE_GROUP_13_15, "collaborative_build": True}
    code = "\n".join(f"line {n}" for n in range(1, 251))

    strict_result = apply_learning_mode_cap_to_embed_result("code", {"code": code}, strict)
    assert strict_result["code"].count("\n") == 39
    collaborative_result = apply_learning_mode_cap_to_embed_result("code", {"code": code}, collaborative)
    assert collaborative_result["code"] == code
    assert collaborative_result["learning_mode_shortened"] is False
    too_long = "\n".join("x" for _ in range(LEARNING_MODE_COLLABORATIVE_CODE_MAX_LINES + 50))
    assert apply_learning_mode_cap_to_embed_result("code", {"code": too_long}, collaborative)[
        "shown_line_count"
    ] == LEARNING_MODE_COLLABORATIVE_CODE_MAX_LINES

    assert should_disable_learning_mode_application_artifact(strict) is True
    assert should_disable_learning_mode_application_artifact(collaborative) is False
    assert should_disable_learning_mode_application_artifact({"enabled": False}) is False

    document = "\n".join(f"para {n}" for n in range(200))
    capped_document = apply_learning_mode_cap_to_embed_result("document", {"content": document}, collaborative)
    assert capped_document["shown_line_count"] == 80  # documents stay capped
    sheet = "\n".join(",".join("c" for _ in range(3)) for _ in range(50))
    capped_sheet = apply_learning_mode_cap_to_embed_result("sheet", {"csv": sheet}, collaborative)
    assert capped_sheet["shown_line_count"] == 12  # sheets stay capped


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-building
def test_math_results_and_answer_key_chips_stay_locked_in_collaborative_mode() -> None:
    collaborative = {"enabled": True, "age_group": AGE_GROUP_13_15, "collaborative_build": True}
    assert is_learning_mode_blocked_skill("math", "calculate") is True
    hidden = apply_learning_mode_policy_to_skill_result(
        "math", "calculate", {"result": "5", "steps": ["a"]}, collaborative
    )
    assert "result" not in hidden and hidden["learning_mode_tool_result_hidden"] is True

    suggestions = [
        "Build an app for my quiz game",
        "Create the app step by step",
        "Show the full solution",
        "Generate an image of the answer",
        "Write the document for me",
        "What is a variable?",
    ]
    assert filter_learning_mode_suggestions(suggestions) == ["What is a variable?"]
    assert filter_learning_mode_suggestions(suggestions, collaborative_build=True) == [
        "Build an app for my quiz game",
        "Create the app step by step",
        "What is a variable?",
    ]


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-building
def test_preferences_context_carries_the_collaborative_flag() -> None:
    context = learning_mode_context_from_preferences(
        {"learning_mode": {"enabled": True, "age_group": AGE_GROUP_16_18, "collaborative_build": True}}
    )
    assert context == {"enabled": True, "age_group": AGE_GROUP_16_18, "collaborative_build": True}
    assert learning_mode_context_from_preferences(
        {"learning_mode": {"enabled": True, "age_group": AGE_GROUP_UNDER_10, "collaborative_build": True}}
    )["collaborative_build"] is False


# contract-test: supporting surface=rest_api assertions=learning-mode.collaborative-building
def test_build_capable_mates_have_a_collaborative_variant_and_others_fall_back() -> None:
    mates = {mate.category: mate for mate in load_mates_config(str(MATES_DIR))}
    for category in ("software_development", "maker_prototyping", "electrical_engineering", "design"):
        mate = mates[category]
        assert mate.collaborative_build_system_prompt
        strict = select_mate_system_prompt(mate, voice_mode=False, learning_mode=True)
        collaborative = select_mate_system_prompt(
            mate, voice_mode=False, learning_mode=True, collaborative_build=True
        )
        assert strict == mate.learning_mode_system_prompt
        assert collaborative == mate.collaborative_build_system_prompt
        voice = select_mate_system_prompt(
            mate, voice_mode=True, learning_mode=True, collaborative_build=True
        )
        assert mate.collaborative_build_system_prompt in voice
        assert mate.voice_learning_mode_system_prompt in voice
    science = mates["science"]
    assert science.collaborative_build_system_prompt is None
    assert select_mate_system_prompt(
        science, voice_mode=False, learning_mode=True, collaborative_build=True
    ) == science.learning_mode_system_prompt
    # Collaborative selection never leaks outside Learning Mode.
    software = mates["software_development"]
    assert select_mate_system_prompt(
        software, voice_mode=False, learning_mode=False, collaborative_build=True
    ) == software.default_system_prompt


# contract-test: supporting surface=rest_api assertions=learning-mode.voice-delivery
def test_voice_learning_focus_instruction_only_for_voice_with_learning_or_focus() -> None:
    cached: dict = {}
    assert build_voice_learning_focus_instruction(
        cached, voice_mode=False, learning_mode_active=True, focus_active=True
    ) == ""
    assert build_voice_learning_focus_instruction(
        cached, voice_mode=True, learning_mode_active=False, focus_active=False
    ) == ""
    for learning, focus in ((True, False), (False, True), (True, True)):
        text = build_voice_learning_focus_instruction(
            cached, voice_mode=True, learning_mode_active=learning, focus_active=focus
        )
        assert "one question at a time" in text
        assert "Never read link syntax" in text
        assert "Never read code" in text
        assert "counts as the learner's attempt" in text
        assert "reading lists, option identifiers" in text
    # A live base-instruction bundle takes precedence over the file fallback.
    assert build_voice_learning_focus_instruction(
        {VOICE_LEARNING_FOCUS_INSTRUCTION_KEY: "bundle text"},
        voice_mode=True, learning_mode_active=True, focus_active=False,
    ) == "bundle text"


# contract-test: supporting surface=rest_api assertions=learning-mode.anonymous-client-side
def test_anonymous_route_never_forwards_the_raw_client_learning_mode_payload() -> None:
    """Every anonymous AI step must see the sanitized context, never client input."""
    source = (
        Path(__file__).resolve().parents[1] / "core/api/app/routes/anonymous.py"
    ).read_text()
    assert "learning_mode_context=payload.learning_mode" not in source
    assert "learning_mode_context=build_anonymous_request_learning_mode_context(" in source


_WIKI_LABEL_CASES = [
    ("Photosynthese", "Photosynthese", True),
    ("Zelle", "Zelle (Biologie)", True),
    ("größe", "Größe", True),
    ("Éclair", "Éclair", True),
    ("光合作用", "光合作用", True),
    ("Zellen", "Zelle (Biologie)", False),
    ("", "Photosynthese", False),
]


# contract-test: supporting surface=rest_api assertions=learning-mode.term-definitions
@pytest.mark.parametrize(("label", "canonical", "expected"), _WIKI_LABEL_CASES)
def test_wiki_term_labels_match_translated_article_titles(label: str, canonical: str, expected: bool) -> None:
    from backend.shared.providers.wikipedia.learning import wiki_label_matches

    assert wiki_label_matches(label, canonical) is expected
