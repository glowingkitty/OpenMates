"""Tests for planner focus selection.

Planner focus modes are ordinary preprocessing candidates offered through the
normal activate_focus_mode countdown. There is no keyword auto-activation
(issue BMKRJ). Only explicit @plan activates a planner immediately, like an
@focus mention.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from backend.apps.ai.processing.plan_focus_routing import (
    CODE_PLAN_FOCUS_ID,
    GENERIC_PLAN_FOCUS_ID,
    PLANNER_FOCUS_IDS,
    has_active_app_focus,
    select_explicit_plan_focus,
)
from backend.core.api.app.utils.override_parser import UserOverrides, parse_overrides

BACKEND = Path(__file__).resolve().parents[1]
ALL_PLANNERS = {GENERIC_PLAN_FOCUS_ID, CODE_PLAN_FOCUS_ID, "jobs-career_insights"}


def _function_from(path: Path, name: str, namespace: dict):
    module = ast.parse(path.read_text())
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def _run_preprocessor_plan_override(
    message: str,
    *,
    llm_focus_modes: list[str],
    user_requested_focus_only: bool = False,
    active_focus_id: str | None = None,
    active_project_focus: dict | None = None,
) -> tuple[list[str], bool]:
    """Execute the real preprocessor @plan block without importing the preprocessor."""
    path = BACKEND / "apps/ai/processing/preprocessor.py"
    module = ast.parse(path.read_text())
    block = next(
        node for node in ast.walk(module)
        if isinstance(node, ast.If) and "plan_requested" in ast.unparse(node.test)
        and "user_requested_focus_only" in ast.unparse(node.test)
    )
    namespace = {
        "user_overrides": parse_overrides(message),
        "user_requested_focus_only": user_requested_focus_only,
        "request_data": SimpleNamespace(active_focus_id=active_focus_id,
                                        active_project_focus=active_project_focus),
        "has_active_app_focus": has_active_app_focus,
        "validated_relevant_focus_modes": list(llm_focus_modes),
        "available_focus_mode_ids": sorted(ALL_PLANNERS),
        "select_explicit_plan_focus": select_explicit_plan_focus,
        "logger": SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
        "log_prefix": "test",
    }
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["validated_relevant_focus_modes"], namespace["user_requested_focus_only"]


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_parse_plan_override_cleans_message() -> None:
    overrides = parse_overrides("@plan Help me plan a workshop")

    assert overrides.plan_requested is True
    assert overrides.cleaned_message == "Help me plan a workshop"


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_explicit_plan_prefers_planner_ranked_by_preprocessing() -> None:
    assert select_explicit_plan_focus(
        ["jobs-career_insights", CODE_PLAN_FOCUS_ID], ALL_PLANNERS,
    ) == CODE_PLAN_FOCUS_ID


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_explicit_plan_falls_back_to_generic_planner() -> None:
    assert select_explicit_plan_focus(["jobs-career_insights"], ALL_PLANNERS) == GENERIC_PLAN_FOCUS_ID
    assert select_explicit_plan_focus([], {"jobs-career_insights"}) is None


@pytest.mark.parametrize(
    ("message", "llm_focus_modes", "expected"),
    [
        ("@plan Erstelle mir einen Plan für den Umzug nach München", [], GENERIC_PLAN_FOCUS_ID),
        ("@plan Plan the API migration with tests", [CODE_PLAN_FOCUS_ID], CODE_PLAN_FOCUS_ID),
    ],
)
# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_explicit_plan_becomes_an_explicit_focus_request(
    message: str, llm_focus_modes: list[str], expected: str,
) -> None:
    assert _run_preprocessor_plan_override(message, llm_focus_modes=llm_focus_modes) == ([expected], True)


@pytest.mark.parametrize(
    "message",
    [
        # Issue BMKRJ: "doesn't plan to" silently activated openmates-plan.
        "Has not looked for any investment and doesn't plan to do so, but focuses on bootstrapping.",
        "Please plan my move to Lisbon next spring.",
        "Erstelle mir einen Plan für den Umzug nach München im März",
    ],
)
# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_natural_language_never_activates_planner_without_at_plan(message: str) -> None:
    # Without @plan, a preprocessing candidate stays a candidate: it is offered via
    # the normal activate_focus_mode countdown, never activated here.
    assert _run_preprocessor_plan_override(message, llm_focus_modes=[GENERIC_PLAN_FOCUS_ID]) == (
        [GENERIC_PLAN_FOCUS_ID], False,
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_explicit_plan_does_not_override_explicit_or_active_focus() -> None:
    assert _run_preprocessor_plan_override(
        "@plan @focus:jobs:career_insights Next steps",
        llm_focus_modes=["jobs-career_insights"], user_requested_focus_only=True,
    ) == (["jobs-career_insights"], True)
    assert _run_preprocessor_plan_override(
        "@plan a launch", llm_focus_modes=[], active_focus_id="jobs-career_insights",
    ) == ([], False)


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_main_processor_trusts_planner_only_for_at_plan() -> None:
    trusted = _function_from(
        BACKEND / "apps/ai/processing/main_processor.py", "_trusted_focus_override",
        {"UserOverrides": UserOverrides, "PLANNER_FOCUS_IDS": PLANNER_FOCUS_IDS},
    )
    assert trusted(parse_overrides("@plan a launch"), GENERIC_PLAN_FOCUS_ID) is True
    assert trusted(parse_overrides("@plan a launch"), "jobs-career_insights") is False
    assert trusted(parse_overrides("Please plan a launch"), GENERIC_PLAN_FOCUS_ID) is False
    assert trusted(parse_overrides("@focus:jobs:career_insights hi"), "jobs-career_insights") is True


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_task_no_longer_sets_planner_focus_silently() -> None:
    source = (BACKEND / "apps/ai/tasks/ask_skill_task.py").read_text()
    assert "plan_focus_routing" not in source
    assert "PLAN_ROUTING" not in source


@pytest.mark.parametrize(("app_id", "focus_id"), [("openmates", "plan"), ("code", "project_planner")])
# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_planners_are_ordinary_preprocessing_candidates(app_id: str, focus_id: str) -> None:
    app = yaml.safe_load((BACKEND / f"apps/{app_id}/app.yml").read_text())
    focus = next(row for row in app["focuses"] if row["id"] == focus_id)
    assert not focus.get("auto_activate_when_relevant")
    hint = " ".join(focus["preprocessor_hint"].split())
    assert "explicitly asks" in hint and "any language" in hint and "incidentally" in hint


# contract-test: supporting surface=rest_api assertions=focus-modes.activation
def test_stage_one_catalogue_shows_planner_relevance_hint() -> None:
    from backend.apps.ai.processing import jev_preprocessing

    app = yaml.safe_load((BACKEND / "apps/openmates/app.yml").read_text())
    hint = " ".join(next(row for row in app["focuses"] if row["id"] == "plan")["preprocessor_hint"].split())
    catalogue = jev_preprocessing._app_catalogue(
        ["openmates"], ["openmates-get-docs: Read OpenMates documentation."], [f"openmates-plan: {hint}"],
    )
    assert "plan focus: Select only when the latest message, in any language, explicitly asks the assistant to create" in catalogue[0]
    assert "task breakdown" in catalogue[0]


PROJECT_BASE = {"project_id": "proj-1", "focus_id": "71cf5c30-0000-4000-8000-000000000001"}


def _main_processor_override_gate(**request: object) -> bool:
    """Evaluate the real explicit-focus gate of main processing for one request."""
    module = ast.parse((BACKEND / "apps/ai/processing/main_processor.py").read_text())
    assign = next(
        node for node in ast.walk(module)
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "has_active_focus_mode"
        and "has_active_app_focus" in ast.unparse(node.value)
    )
    gate = next(
        node for node in ast.walk(module)
        if isinstance(node, ast.If) and "user_requested_focus_only and relevant_focus_modes" in ast.unparse(node.test)
        and "_trusted_focus_override" in ast.unparse(node.test)
    )
    namespace = {
        "request_data": SimpleNamespace(**{"active_focus_id": None, "active_project_focus": None, **request}),
        "has_active_app_focus": has_active_app_focus,
        "user_requested_focus_only": True,
        "relevant_focus_modes": ["code-write_specification"],
        "project_candidates": {},
        "user_overrides": parse_overrides("@focus:code:write_specification Write the spec"),
        "_trusted_focus_override": _function_from(
            BACKEND / "apps/ai/processing/main_processor.py", "_trusted_focus_override",
            {"UserOverrides": UserOverrides, "PLANNER_FOCUS_IDS": PLANNER_FOCUS_IDS},
        ),
    }
    exec(compile(ast.Module(body=[assign], type_ignores=[]), "gate", "exec"), namespace)
    return bool(eval(compile(ast.Expression(gate.test), "gate", "eval"), namespace))


# contract-test: supporting surface=rest_api assertions=focus-modes.project-specialist-composition
def test_a_project_base_focus_is_not_an_active_app_focus() -> None:
    base_id = PROJECT_BASE["focus_id"]
    assert has_active_app_focus(SimpleNamespace(active_focus_id=None, active_project_focus=PROJECT_BASE)) is False
    assert has_active_app_focus(SimpleNamespace(active_focus_id=base_id, active_project_focus=PROJECT_BASE)) is False
    assert has_active_app_focus(SimpleNamespace(
        active_focus_id="code-write_specification", active_project_focus=PROJECT_BASE)) is True
    assert has_active_app_focus(SimpleNamespace(active_focus_id="jobs-career_insights", active_project_focus=None)) is True
    # A stale base id without a current Project binding still blocks, as before.
    assert has_active_app_focus(SimpleNamespace(active_focus_id=base_id, active_project_focus=None)) is True


# contract-test: supporting surface=rest_api assertions=focus-modes.project-specialist-composition
def test_an_explicit_focus_mention_activates_over_an_active_project_focus() -> None:
    assert _main_processor_override_gate(active_project_focus=PROJECT_BASE) is True
    assert _main_processor_override_gate(
        active_focus_id=PROJECT_BASE["focus_id"], active_project_focus=PROJECT_BASE) is True
    # An app focus that is already active still keeps its normal path.
    assert _main_processor_override_gate(
        active_focus_id="jobs-career_insights", active_project_focus=PROJECT_BASE) is False
    assert _main_processor_override_gate(active_focus_id="jobs-career_insights") is False


# contract-test: supporting surface=rest_api assertions=focus-modes.project-specialist-composition
def test_explicit_plan_resolves_a_planner_in_a_project_chat() -> None:
    assert _run_preprocessor_plan_override(
        "@plan the garden app", llm_focus_modes=[CODE_PLAN_FOCUS_ID],
        active_focus_id=PROJECT_BASE["focus_id"], active_project_focus=PROJECT_BASE,
    ) == ([CODE_PLAN_FOCUS_ID], True)
