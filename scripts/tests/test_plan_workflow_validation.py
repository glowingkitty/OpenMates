#!/usr/bin/env python3
"""Test goal-first and strict executable Plan validation.

Plans may contain only a goal. Repository-governed implementation work can opt
into the strict profile that retains scenarios, evidence, Tasks, and handoff.
Optional sections are validated when present but are never implied globally.
Fixtures use public placeholder values and no product or network state.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "plan_validate.py"


# contract-test-file: tooling


def load_plan_validator():
    spec = importlib.util.spec_from_file_location("openmates_plan_validate", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_plan_verifier():
    validator = load_plan_validator()
    previous = sys.modules.get("plan_validate")
    sys.modules["plan_validate"] = validator
    try:
        spec = importlib.util.spec_from_file_location("openmates_plan_verify", ROOT / "scripts" / "plan_verify.py")
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            del sys.modules["plan_validate"]
        else:
            sys.modules["plan_validate"] = previous


def write_plan(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "plan.yml"
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return path


def test_goal_only_plan_is_valid(tmp_path: Path) -> None:
    validator = load_plan_validator()
    plan = write_plan(
        tmp_path,
        {
            "id": "birthday-dinner",
            "title": "Birthday dinner",
            "status": "draft",
            "goal": "Organize a birthday dinner for twelve guests.",
        },
    )

    loaded = validator.validate_plan(plan)

    assert loaded["goal"].startswith("Organize")


def test_plan_validator_exposes_only_plan_named_public_api() -> None:
    validator = load_plan_validator()

    assert hasattr(validator, "PlanError")
    assert not hasattr(validator, "SpecError")
    assert not hasattr(validator, "validate_spec")


def test_goal_only_plan_does_not_gain_implicit_completion_gates(tmp_path: Path) -> None:
    validator = load_plan_validator()
    plan = write_plan(
        tmp_path,
        {
            "id": "campaign",
            "title": "Campaign",
            "status": "draft",
            "goal": "Launch the autumn campaign.",
        },
    )

    loaded = validator.validate_plan(plan)

    assert "assumptions" not in loaded
    assert "tasks" not in loaded
    assert "tests" not in loaded
    assert "acceptance_criteria" not in loaded
    assert "learnings" not in loaded


def test_goal_only_plan_has_no_implicit_completion_verification(tmp_path: Path) -> None:
    verifier = load_plan_verifier()
    plan = write_plan(
        tmp_path,
        {
            "id": "campaign",
            "title": "Campaign",
            "status": "draft",
            "goal": "Launch the autumn campaign.",
        },
    )

    assert verifier.verify_plan(plan, require_red=True, require_green=True) == []


def test_schema_v3_evidence_enforces_provenance() -> None:
    verifier = load_plan_verifier()

    failures = verifier._evidence_contract_failures(
        {"schema_version": 3},
        record_id="T-1",
        phase="green_phase",
        evidence={"status": "passed"},
        automated=True,
    )

    assert "T-1: green_phase evidence missing timestamp" in failures
    assert "T-1: green_phase evidence missing command" in failures
    assert "T-1: green_phase evidence missing run_id" in failures
    assert "T-1: green_phase evidence missing subject_commit" in failures


def test_strict_plan_does_not_require_optional_implementation_notes(tmp_path: Path) -> None:
    validator = load_plan_validator()
    source = ROOT / "docs" / "plans" / "specification-plan-terminology-migration" / "plan.yml"
    plan_data = yaml.safe_load(source.read_text(encoding="utf-8"))
    plan_data.pop("implementation_notes")

    validator.validate_plan(write_plan(tmp_path, plan_data))


def test_implementation_notes_plan_path_matches_canonical_plan(tmp_path: Path) -> None:
    validator = load_plan_validator()
    source = ROOT / "docs" / "plans" / "specification-plan-terminology-migration" / "plan.yml"
    plan_data = yaml.safe_load(source.read_text(encoding="utf-8"))
    plan_data["implementation_notes"]["plan_path"] = "docs/plans/stale-name/plan.yml"
    plan = write_plan(tmp_path, plan_data)

    with pytest.raises(validator.PlanError, match="implementation_notes.plan_path must be"):
        validator.validate_plan(plan)


def test_strict_plan_requires_full_implementation_ledger(tmp_path: Path) -> None:
    validator = load_plan_validator()
    plan = write_plan(
        tmp_path,
        {
            "schema_version": 3,
            "profile": "strict",
            "id": "governed-change",
            "title": "Governed change",
            "status": "approved",
            "goal": "Implement an approved Specification.",
        },
    )

    with pytest.raises(validator.PlanError, match="scope"):
        validator.validate_plan(plan)
