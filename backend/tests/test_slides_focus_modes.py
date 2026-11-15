"""The two Slides focus modes parse, are registered and carry their contract phases."""
from pathlib import Path

import yaml
import pytest

from backend.shared.python_schemas.app_metadata_schemas import AppFocusDefinition
from backend.shared.python_utils.focus_mode_skill_loader import load_focus_mode_from_skill_md

ROOT = Path(__file__).resolve().parents[2]
SLIDES = ROOT / "backend/apps/slides"
MODES = {
    "design_template": (
        "design-template",
        ["purpose_and_brand", "design_choice", "refine", "save"],
    ),
    "plan_presentation": (
        "plan-presentation",
        ["goal_and_audience", "story", "outline", "template", "slides", "review"],
    ),
}


def load(focus_id):
    directory, _ = MODES[focus_id]
    raw = load_focus_mode_from_skill_md(str(SLIDES / "focus_modes" / directory / "SKILL.md"), "slides")
    return AppFocusDefinition(**raw)


# contract-test: supporting surface=rest_api assertions=slides.focus.template-designer,slides.focus.presentation-planner,focus-modes.phases
@pytest.mark.parametrize("focus_id", MODES)
def test_phases_parse_in_contract_order(focus_id):
    focus = load(focus_id)
    assert [phase.id for phase in focus.phases] == MODES[focus_id][1]


# contract-test: supporting surface=rest_api assertions=slides.focus.template-designer,slides.focus.presentation-planner,focus-modes.phases
def test_planner_outline_needs_explicit_user_confirmation():
    outline = next(p for p in load("plan_presentation").phases if p.id == "outline")
    assert any(r.type == "user_confirmation" for r in outline.requirements)


# contract-test: supporting surface=rest_api assertions=slides.focus.template-designer,slides.focus.presentation-planner,focus-modes.phases
def test_designer_choice_and_refine_are_user_confirmed():
    phases = {p.id: p for p in load("design_template").phases}
    for phase_id in ("design_choice", "refine"):
        assert any(r.type == "user_confirmation" for r in phases[phase_id].requirements)


# contract-test: supporting surface=rest_api assertions=slides.focus.template-designer,slides.focus.presentation-planner,focus-modes.phases
@pytest.mark.parametrize("focus_id", MODES)
def test_registered_in_app_yml_with_translation_sources(focus_id):
    app = yaml.safe_load((SLIDES / "app.yml").read_text())
    entry = next(f for f in app["focus_modes"] if f["id"] == focus_id)
    assert entry["name_translation_key"] == f"slides.{focus_id}"
    assert entry["preprocessor_hint"].strip()
    sources = ROOT / "frontend/packages/ui/src/i18n/sources"
    names = yaml.safe_load((sources / "app_focus_modes/slides.yml").read_text())
    assert focus_id in names and f"{focus_id}.description" in names
    detail = yaml.safe_load((sources / f"focus_modes/slides_{focus_id}.yml").read_text())
    assert {"process", "how_to_use", "systemprompt"} <= set(detail)


# contract-test: supporting surface=rest_api assertions=slides.focus.template-designer,slides.focus.presentation-planner,focus-modes.phases
def test_routing_hints_cover_the_example_requests():
    app = yaml.safe_load((SLIDES / "app.yml").read_text())
    hints = {f["id"]: f["preprocessor_hint"] for f in app["focus_modes"]}
    assert "hackathon" in hints["plan_presentation"]
    assert "slide template" in hints["design_template"]
