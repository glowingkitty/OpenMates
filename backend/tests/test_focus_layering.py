"""Tests for a focus layered over an always-active Project base.

feature.focus-modes@3: the Project base stays on, a more specific focus layers
on top, ending it returns to the base, the assistant never switches the base
off on its own, and colliding instructions follow a fixed precedence.
"""

from pathlib import Path

from backend.apps.ai.processing.focus_layering import (
    LAYER_PRECEDENCE_HEADER,
    build_layer_precedence_section,
    deactivate_focus_tool,
    deactivation_result,
    resolve_focus_layers,
)
from backend.shared.python_utils.focus_mode_skill_loader import load_focus_mode_from_skill_md

BACKEND = Path(__file__).resolve().parents[1]
BASE = {"focus_id": "garden-planner-base", "project_id": "p1"}


# contract-test: supporting surface=rest_api assertions=focus-modes.project-layering
def test_layers_split_base_and_layered_focus():
    assert resolve_focus_layers("garden-planner-base", BASE).base_only
    assert resolve_focus_layers(None, BASE).base_only
    layered = resolve_focus_layers("code-write_specification", BASE)
    assert layered.layered and layered.layered_focus_id == "code-write_specification"
    outside = resolve_focus_layers("web-research", None)
    assert not outside.layered and not outside.base_only


# contract-test: supporting surface=rest_api assertions=focus-modes.layer-end
def test_deactivate_tool_ends_only_the_layered_focus():
    tool = deactivate_focus_tool(resolve_focus_layers("code-write_specification", BASE), "code-write_specification")
    description = tool["function"]["description"]
    assert "Project focus stays active" in description
    result = deactivation_result(resolve_focus_layers("code-write_specification", BASE))
    assert result["previous_focus_id"] == "code-write_specification"
    assert "remains active" in result["message"]


# contract-test: supporting surface=rest_api assertions=focus-modes.layer-end
def test_project_base_goes_off_only_when_the_user_leaves_the_project():
    tool = deactivate_focus_tool(resolve_focus_layers("garden-planner-base", BASE), "garden-planner-base")
    description = tool["function"]["description"]
    assert "ONLY when the user explicitly moves the conversation away from this Project" in description
    assert "Never call it because a task finished" in description
    assert deactivate_focus_tool(resolve_focus_layers(None, None), None) is None
    plain = deactivate_focus_tool(resolve_focus_layers("web-research", None), "web-research")
    assert "return to normal assistant behavior" in plain["function"]["description"]


# contract-test: supporting surface=rest_api assertions=focus-modes.layer-precedence
def test_precedence_section_keeps_project_constraints():
    assert build_layer_precedence_section(resolve_focus_layers("garden-planner-base", BASE),
                                          first_answer_after_layering=True) is None
    section = build_layer_precedence_section(
        resolve_focus_layers("code-write_specification", BASE),
        first_answer_after_layering=False, layered_name="Write specification",
    )
    assert section.startswith(LAYER_PRECEDENCE_HEADER)
    assert "Write specification (code-write_specification)" in section
    assert "the layered focus wins" in section
    assert "never overridden by the layered focus" in section
    assert "Platform safety policy overrides both layers" in section
    assert "first answer since the layered focus started" not in section


# contract-test: supporting surface=rest_api assertions=focus-modes.override-note,focus-modes.conflict-detection
def test_first_answer_after_layering_checks_collisions_and_notes_them_once():
    section = build_layer_precedence_section(
        resolve_focus_layers("project-focus:p1:provider", BASE), first_answer_after_layering=True,
    )
    assert "Compare the two instruction sets now" in section
    assert "If nothing collides, write no such line" in section
    assert "Do not repeat this note in later answers" in section


# contract-test: supporting surface=rest_api assertions=focus-modes.project-layering,focus-modes.natural-request
def test_write_specification_is_proposed_automatically_for_new_features():
    focus = load_focus_mode_from_skill_md(
        str(BACKEND / "apps/code/focus_modes/write-specification/SKILL.md"), "code")
    assert focus["auto_activate_when_relevant"] is True
    assert "new feature" in focus["preprocessor_hint"]
    assert "bug fix" in focus["preprocessor_hint"]


# contract-test: supporting surface=rest_api assertions=focus-modes.project-layering,focus-modes.natural-request
def test_main_processor_does_not_let_the_project_base_block_proposals():
    source = (BACKEND / "apps/ai/processing/main_processor.py").read_text()
    assert "has_active_focus_mode = bool(request_data.active_focus_id or active_project_focus)" not in source
    assert "set(private_candidates) if focus_layers.base_only else set()" in source
    assert "deactivate_focus_tool(\n        focus_layers, request_data.active_focus_id)" in source
