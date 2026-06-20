"""Regression tests for Learning Mode prompt and artifact contracts."""

from __future__ import annotations

from pathlib import Path

from backend.apps.ai.utils.mate_utils import load_mates_config
from backend.shared.python_utils.learning_mode import (
    AGE_GROUP_16_18,
    LEARNING_MODE_GLOBAL_PROMPT_MARKER,
    apply_learning_mode_cap_to_embed_result,
    apply_learning_mode_policy_to_skill_result,
    build_learning_mode_system_prompt,
    cap_learning_mode_lines,
    filter_learning_mode_suggestions,
    is_learning_mode_blocked_skill,
    should_disable_learning_mode_application_artifact,
)


def test_every_mate_has_explicit_learning_mode_prompt_variant() -> None:
    mates = load_mates_config("backend/apps/ai/mates")

    assert mates
    missing = [mate.id for mate in mates if not mate.learning_mode_system_prompt.strip()]
    assert missing == []


def test_learning_mode_prompt_uses_mate_variant_and_global_instruction() -> None:
    mates = load_mates_config("backend/apps/ai/mates")
    sophia = next(mate for mate in mates if mate.category == "software_development")

    prompt = build_learning_mode_system_prompt(
        mate_prompt=sophia.default_system_prompt,
        learning_mode_mate_prompt=sophia.learning_mode_system_prompt,
        age_group=AGE_GROUP_16_18,
    )

    assert sophia.learning_mode_system_prompt in prompt
    assert LEARNING_MODE_GLOBAL_PROMPT_MARKER in prompt
    assert "16-18" in prompt
    assert sophia.default_system_prompt not in prompt


def test_learning_mode_code_lines_are_capped_with_metadata() -> None:
    code = "\n".join(f"line {line}" for line in range(1, 81))

    capped, metadata = cap_learning_mode_lines(code, max_lines=40)

    assert capped.splitlines() == [f"line {line}" for line in range(1, 41)]
    assert metadata == {
        "learning_mode_shortened": True,
        "original_line_count": 80,
        "shown_line_count": 40,
    }


def test_learning_mode_caps_app_skill_code_child_embed_results() -> None:
    code = "\n".join(f"line {line}" for line in range(1, 81))

    result = apply_learning_mode_cap_to_embed_result(
        "code",
        {"type": "code", "code": code, "line_count": 80, "embed_ref": "example.py-abc123"},
        {"enabled": True, "age_group": "13_15"},
    )

    assert result["code"].splitlines() == [f"line {line}" for line in range(1, 41)]
    assert result["line_count"] == 40
    assert result["learning_mode_shortened"] is True
    assert result["original_line_count"] == 80
    assert result["shown_line_count"] == 40
    assert result["embed_ref"] == "example.py-abc123"


def test_learning_mode_filters_artifact_bypass_suggestions() -> None:
    suggestions = [
        "Generate an image with the answer key for 3(x - 4) = 2x + 10",
        "Explain the distributive property in more detail",
        "Create a step-by-step solution image for the equation",
        "Show me another example of a linear equation",
        "Calculate the solution to 3(x - 4) = 2x + 10",
        "Find the solution to this system of equations",
        "Calculate the roots of this polynomial",
    ]

    assert filter_learning_mode_suggestions(suggestions) == [
        "Explain the distributive property in more detail",
        "Show me another example of a linear equation",
    ]


def test_learning_mode_hides_complete_math_tool_results() -> None:
    result = apply_learning_mode_policy_to_skill_result(
        "math",
        "calculate",
        {
            "title": "Solving 3(x - 4) = 2x + 10",
            "expression": "solve(3*(x - 4) = 2*x + 10, x)",
            "result": "x = 22",
            "result_latex": "x = 22",
            "result_numeric": 22.0,
            "result_str": "x = 22",
            "steps": [{"description": "Solution", "latex": "x = 22"}],
            "embed_ref": "solving-3-x-abc123",
        },
        {"enabled": True, "age_group": "13_15"},
    )

    assert "result" not in result
    assert "result_latex" not in result
    assert "result_numeric" not in result
    assert "result_str" not in result
    assert "steps" not in result
    assert result["learning_mode_tool_result_hidden"] is True
    assert result["embed_ref"] == "solving-3-x-abc123"


def test_learning_mode_blocks_math_calculate_skill() -> None:
    assert is_learning_mode_blocked_skill("math", "calculate") is True
    assert is_learning_mode_blocked_skill("math", "convert") is False
    assert is_learning_mode_blocked_skill("web", "search") is False


def test_learning_mode_short_line_content_is_not_marked_shortened() -> None:
    content = "short\nexample"

    capped, metadata = cap_learning_mode_lines(content, max_lines=40)

    assert capped == content
    assert metadata == {
        "learning_mode_shortened": False,
        "original_line_count": 2,
        "shown_line_count": 2,
    }


def test_application_artifacts_are_disabled_in_learning_mode() -> None:
    assert should_disable_learning_mode_application_artifact({"enabled": True}) is True
    assert should_disable_learning_mode_application_artifact({"enabled": False}) is False
    assert should_disable_learning_mode_application_artifact(None) is False


def test_learning_mode_spec_exists() -> None:
    assert Path("docs/specs/learning-mode/spec.yml").is_file()
