"""Diagram Design type routing, pinned resource, and provenance contracts."""

# contract-test-file: infrastructure

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from backend.apps.ai.processing import jev_preprocessing
from backend.apps.ai.processing.rule_context import eligible_rule_catalog
from backend.apps.diagrams.diagram_guidance import (
    diagram_guidance_prompt, diagram_type_metadata, selected_diagram_memories,
)
from backend.shared.providers.typesafe.models import DecisionResponse


_VENDOR = Path(__file__).resolve().parents[1] / "apps" / "diagrams" / "vendor" / "diagram_design"


# contract-test: supporting surface=rest_api assertions=app-memories.definition.context-documents
def test_vendor_manifest_pins_all_runtime_resources_and_audit_inventory() -> None:
    manifest = json.loads((_VENDOR / "manifest.json").read_text())
    audit = json.loads((_VENDOR / "audit.json").read_text())
    rows = [*manifest["types"], *manifest["common"]]
    assert len(manifest["types"]) == 44
    assert audit["inventory"]["total_verified_resources"] == len(rows)
    assert audit["verification"]["forbidden_network_or_shell_directives_found"] is False
    assert audit["verification"]["prompt_authority_override_or_exfiltration_patterns_found"] is False
    for row in rows:
        path = _VENDOR / row.get("reference", row.get("path"))
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["runtime_sha256"]


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.transparency.loaded-set
def test_all_44_types_have_short_memories_and_complete_selected_references() -> None:
    catalogue = diagram_type_metadata()
    assert len(catalogue) == len({row["id"] for row in catalogue}) == 44
    assert all(len(row["description"]) < 160 for row in catalogue)
    assert eligible_rule_catalog(eligible_app_ids=["diagrams"]) == []

    selected = diagram_guidance_prompt(["type-line"])
    source = (_VENDOR / "references" / "type-line.md").read_text()
    assert source in selected
    assert (_VENDOR / "references" / "primitives-core.md").read_text() in selected
    assert (_VENDOR / "templates" / "template.html").read_text() in selected
    assert (_VENDOR / "templates" / "template-dark.html").read_text() not in selected
    dark = diagram_guidance_prompt(["type-line"], variant="minimal_dark")
    assert (_VENDOR / "templates" / "template-dark.html").read_text() in dark
    assert "data-om-component" in selected and "data-om-edge" in selected
    assert "static nested inline SVG icons are allowed" in selected
    assert "Do not use foreignObject or external images" in selected
    sequence = diagram_guidance_prompt(["type-sequence"], variant="minimal_dark")
    assert "data-om-owner=\"participant-node-id\"" in sequence
    assert "message endpoint heights remain fixed" in sequence
    assert "including Q curves and a arcs" in selected
    assert "correct dangling references" in selected
    assert "Use orthogonal M/H/V path segments" not in selected
    assert diagram_guidance_prompt(["../private", "type-unknown"]) == ""

    receipt = selected_diagram_memories(["type-line"])
    manifest = json.loads((_VENDOR / "manifest.json").read_text())
    expected = next(row["runtime_sha256"] for row in manifest["types"] if row["id"] == "type-line")
    assert len(receipt) == 1
    assert receipt[0].id == "app:diagrams:type-line"
    assert receipt[0].revision == expected
    assert len(receipt[0].body) < 300


# contract-test: supporting surface=rest_api assertions=app-memories.definition.context-documents
def test_selected_template_declares_a_whole_document_artboard() -> None:
    for variant, template_name in (
        ("minimal_light", "template.html"),
        ("minimal_dark", "template-dark.html"),
        ("full_editorial", "template-full.html"),
    ):
        template = (_VENDOR / "templates" / template_name).read_text()
        root = re.search(r'<html\b[^>]*data-om-render-width="(\d+)"[^>]*data-om-render-height="(\d+)"[^>]*data-om-background="(#[0-9a-fA-F]{6})"', template)
        paper = re.search(r'--color-paper:\s*(#[0-9a-fA-F]{6})', template)
        svg = re.search(r'<svg\b[^>]*data-om-diagram="\[diagram-kind\]"[^>]*viewBox="[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)"', template)
        assert root is not None and paper is not None and svg is not None
        width, height = map(int, root.groups()[:2])
        assert root.group(3).lower() == paper.group(1).lower()
        svg_width, svg_height = map(float, svg.groups())
        assert 200 <= width <= 4096 and 200 <= height <= 4096
        assert width >= svg_width and height >= svg_height + 200
        prompt = diagram_guidance_prompt(["type-architecture"], variant=variant)
        assert "Whole-document artboard contract" in prompt
        assert "entire HTML body" in prompt
        assert "data-om-background" in prompt
        assert "resolved opaque six-digit #RRGGBB" in prompt
        assert "do not use var(), currentColor, a named color, or transparency" in prompt
        assert template in prompt


# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped
@pytest.mark.asyncio
async def test_jev_stage_two_sees_all_type_memories_and_selects_full_guide_id(monkeypatch) -> None:
    seen = {}

    async def evaluate(**kwargs):
        questions = kwargs["questions"]
        seen["primary_criteria"] = questions["diagram_primary_type"]["criteria"]
        seen["secondary_criteria"] = questions["diagram_secondary_type"]["criteria"]
        answers = {}
        for key, question in questions.items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.96 if key == "diagram_guidance_relevant" else 0.0}
            else:
                first = next(iter(question["criteria"]))
                answers[key] = {"type": "choice", "choice": first, "confidence": 0.99,
                                "probabilities": {name: float(name == first)
                                                  for name in question["criteria"]}}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None,
        message_history=[{"role": "user", "content": "Draw my system architecture"}],
        topic_areas=["software_development: Software engineering"],
        available_skills=[], available_focus_modes=[], available_settings_and_memories=None,
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=True, available_apps=["diagrams"], selected_app_ids=["diagrams"],
    )
    assert len(seen["primary_criteria"]) == 44
    assert set(seen["secondary_criteria"]) == {"none", *seen["primary_criteria"]}
    assert all(len(description) < 200 for description in seen["primary_criteria"].values())
    assert result["relevant_diagram_types"] == ["type-architecture"]
    assert result["relevant_diagram_variant"] == "minimal_light"


@pytest.mark.parametrize(("history", "relevant"), [
    ([{"role": "user", "content": "Compare a tiered planner, researcher and coder architecture."}], True),
    ([{"role": "user", "content": "How does our order approval process flow between teams?"}], True),
    ([{"role": "user", "content": "Discuss the architecture of a planner and workers."},
      {"role": "assistant", "content": "The planner assigns bounded work."},
      {"role": "user", "content": "What about nested workers? Answer in prose only."}], True),
    ([{"role": "user", "content": "What is the capital of Peru?"}], False),
])
# contract-test: supporting surface=rest_api assertions=app-memories.selection.source-scoped,app-memories.precedence.obligations
@pytest.mark.asyncio
async def test_discussion_routes_optional_public_guides_without_skills_or_private_memories(
    monkeypatch, history, relevant,
) -> None:
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        answers = {}
        for key, question in kwargs["questions"].items():
            if question["type"] == "noul":
                candidate = question["instructions"]
                app_id = candidate.get("candidate_id") if isinstance(candidate, dict) else None
                selected = relevant and (app_id in {"diagrams", "mindmaps"}
                    or key in {"diagram_guidance_relevant", "needs_detailed_context"})
                answers[key] = {"type": "noul", "noul": float(selected)}
            else:
                criteria = question["criteria"]
                preferred = {"diagram_primary_type": "type-architecture",
                             "diagram_secondary_type": "none", "diagram_tertiary_type": "none",
                             "diagram_variant": "minimal_light", "topic_shift": "same_topic"}.get(key)
                chosen = preferred if preferred in criteria else next(iter(criteria))
                answers[key] = {"type": "choice", "choice": chosen, "confidence": 1.0,
                                "probabilities": {option: float(option == chosen) for option in criteria}}
        return DecisionResponse.model_validate({"model": "jev", "answers": answers, "usage": {}})

    monkeypatch.setattr(jev_preprocessing, "_evaluate_preprocessing_questions", evaluate)
    result = await jev_preprocessing.decide_preprocessing_with_jev(
        model_id="jev", secrets_manager=None, message_history=history,
        topic_areas=["software_development: Software", "general_misc: General"],
        available_skills=[], available_focus_modes=[], available_settings_and_memories={},
        recent_skill_activity=[], conversation_summary=None, previous_category=None,
        is_first_message=len(history) == 1, available_apps=["diagrams", "mindmaps", "web"],
    )
    assert calls[0]["state"]["messages"] == history
    assert result["selected_app_ids"] == (["diagrams", "mindmaps"] if relevant else [])
    assert result["relevant_diagram_types"] == (["type-architecture"] if relevant else [])
    assert result["relevant_app_skills"] == []
    assert result["load_app_settings_and_memories"] == []
    assert result["relevant_focus_modes"] == []
    assert result["relevant_workflows"] == []
    if relevant:
        prompt = diagram_guidance_prompt(result["relevant_diagram_types"])
        assert (_VENDOR / "references/type-architecture.md").read_text() in prompt
        assert "you decide whether a visual helps" in prompt
        assert "explicit prose-only request must be respected" in prompt
        assert len(selected_diagram_memories(result["relevant_diagram_types"])) == 1


# contract-test: supporting surface=rest_api assertions=app-memories.precedence.obligations
def test_both_native_protocols_preserve_optional_visuals_and_explicit_only_mermaid() -> None:
    root = Path(__file__).resolve().parents[1] / "apps"
    for app_id in ("diagrams", "mindmaps"):
        app = yaml.safe_load((root / app_id / "app.yml").read_text())
        instruction = " ".join(app["instructions"][0]["instruction"].split())
        assert "prose alone is fine" in instruction.lower()
        assert "does not require creating" in instruction
        assert "Respect explicit prose-only requests" in instruction
        assert "Use Mermaid source only when the user explicitly asks" in instruction
    catalogue = jev_preprocessing._app_catalogue(["diagrams", "mindmaps"], [], [])
    assert all("even without a visual request" in entry for entry in catalogue)
