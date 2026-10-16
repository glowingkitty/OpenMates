# contract-test-file: infrastructure
"""Tests for explicit @plan and planner focus routing.

Plans V1 uses the existing focus-mode system but gives users a shorter @plan
trigger and a generic fallback planner when no app-specific planner matches.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing.plan_focus_routing import route_plan_focus
from backend.core.api.app.utils.override_parser import parse_overrides


def _run_production_plan_focus_guard(
    *,
    explicit_focus: bool,
    active_focus_id: str | None = None,
    active_project_focus: bool = False,
    relevant_focus_modes: list[str] | None = None,
) -> str | None:
    """Execute the real task guard without importing the Celery task module."""
    task_path = Path(__file__).resolve().parents[1] / "apps/ai/tasks/ask_skill_task.py"
    module = ast.parse(task_path.read_text())
    guard = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "user_overrides"
        and any(
            isinstance(child, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "plan_route" for target in child.targets)
            for child in node.body
        )
    )
    request_data = SimpleNamespace(
        active_focus_id=active_focus_id,
        active_project_focus=active_project_focus,
    )
    intro = (
        "I am a fiction writer looking to become a software developer. "
        "Do not create Tasks or save memories."
    )
    user_overrides = parse_overrides(
        f"@focus:jobs:career_insights {intro}" if explicit_focus else intro
    )
    if explicit_focus:
        assert user_overrides.focus_modes == [("jobs", "career_insights")]
    namespace = {
        "user_overrides": user_overrides,
        "discovered_apps_metadata": {
            "code": SimpleNamespace(focuses=[SimpleNamespace(id="project_planner")]),
        },
        "preprocessing_result": SimpleNamespace(
            user_requested_focus_only=explicit_focus,
            relevant_focus_modes=(
                relevant_focus_modes if relevant_focus_modes is not None else ["jobs-career_insights"]
            ),
        ),
        "request_data": request_data,
        "route_plan_focus": route_plan_focus,
        "logger": SimpleNamespace(info=lambda *_: None),
        "task_id": "test",
    }
    exec(compile(ast.Module(body=[guard], type_ignores=[]), str(task_path), "exec"), namespace)
    return request_data.active_focus_id


def test_parse_plan_override_cleans_message() -> None:
    overrides = parse_overrides("@plan Help me plan a workshop")

    assert overrides.plan_requested is True
    assert overrides.cleaned_message == "Help me plan a workshop"


def test_explicit_plan_routes_coding_request_to_code_project_planner() -> None:
    route = route_plan_focus(
        "Help me plan and implement password-protected shared chats",
        plan_requested=True,
        available_focus_modes={"code-project_planner", "openmates-plan"},
    )

    assert route.active_focus_id == "code-project_planner"
    assert route.reason == "matched_code_planner"


def test_explicit_plan_routes_generic_request_to_openmates_plan() -> None:
    route = route_plan_focus(
        "Help me plan a 60-person community workshop in Berlin",
        plan_requested=True,
        available_focus_modes={"code-project_planner", "openmates-plan"},
    )

    assert route.active_focus_id == "openmates-plan"
    assert route.reason == "generic_plan_fallback"


def test_natural_language_can_auto_detect_complex_planning() -> None:
    route = route_plan_focus(
        "Plan a research project with tasks, sources, acceptance criteria, and verification steps",
        plan_requested=False,
        available_focus_modes={"openmates-plan"},
    )

    assert route.should_plan is True
    assert route.active_focus_id == "openmates-plan"


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
@pytest.mark.parametrize(
    ("explicit_focus", "active_focus_id", "active_project_focus", "relevant_focus_modes", "expected_focus_id"),
    [
        (True, None, False, ["jobs-career_insights"], None),
        (False, None, False, [], "code-project_planner"),
        (False, None, True, [], None),
        (False, None, False, ["project-existing"], None),
        (False, "jobs-career_insights", False, [], "jobs-career_insights"),
    ],
    ids=["explicit-career", "automatic-plan", "active-project", "project-catalog", "existing-focus"],
)
def test_task_plan_route_preserves_focus_precedence(
    explicit_focus: bool,
    active_focus_id: str | None,
    active_project_focus: bool,
    relevant_focus_modes: list[str],
    expected_focus_id: str | None,
) -> None:
    assert _run_production_plan_focus_guard(
        explicit_focus=explicit_focus,
        active_focus_id=active_focus_id,
        active_project_focus=active_project_focus,
        relevant_focus_modes=relevant_focus_modes,
    ) == expected_focus_id
