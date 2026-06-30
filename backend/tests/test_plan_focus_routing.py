"""Tests for explicit @plan and planner focus routing.

Plans V1 uses the existing focus-mode system but gives users a shorter @plan
trigger and a generic fallback planner when no app-specific planner matches.
"""

from backend.apps.ai.processing.plan_focus_routing import route_plan_focus
from backend.core.api.app.utils.override_parser import parse_overrides


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
