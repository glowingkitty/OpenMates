#!/usr/bin/env python3
"""Guard the Specification and Plan terminology migration.

These tests verify the repository-owned workflow vocabulary and path layout.
They deliberately leave generic Playwright specs and API/legal contracts alone.
The migration must preserve every durable bundle and executable Plan one-to-one.
No product data, network service, or private fixture is used here.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]


# contract-test-file: tooling


def test_specification_bundle_layout_replaces_contract_bundle_layout() -> None:
    specifications_root = ROOT / "specifications"

    assert specifications_root.is_dir()
    assert not (ROOT / "contracts").exists()
    assert len(list(specifications_root.glob("**/specification.yml"))) >= 40
    assert not list(specifications_root.glob("**/contract.yml"))
    assert (specifications_root / "schema" / "specification.schema.yml").is_file()
    assert (specifications_root / "generated" / "registry.yml").is_file()


def test_executable_plan_layout_replaces_full_spec_layout() -> None:
    plans_root = ROOT / "docs" / "plans"

    assert plans_root.is_dir()
    assert not any(path.is_file() for path in (ROOT / "docs" / "specs").glob("**/*"))
    assert len(list(plans_root.glob("*/plan.yml"))) >= 100
    assert not list(plans_root.glob("**/spec.yml"))


def test_legacy_paths_map_one_to_one_from_integration_baseline() -> None:
    def baseline_paths(prefix: str) -> set[str]:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", prefix],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return {line for line in result.stdout.splitlines() if line}

    legacy_specifications = baseline_paths("contracts")
    legacy_plans = baseline_paths("docs/specs")
    if not legacy_specifications and not legacy_plans:
        return

    expected_specifications = {
        path.replace("contracts/features/contracts/", "specifications/features/specifications/", 1)
        .replace("contracts/", "specifications/", 1)
        .replace("/contract.yml", "/specification.yml")
        .replace("/contract.schema.yml", "/specification.schema.yml")
        for path in legacy_specifications
    }
    expected_plans = {
        path.replace("docs/specs/", "docs/plans/", 1).replace("/spec.yml", "/plan.yml")
        for path in legacy_plans
    }
    expected_plans.add("docs/plans/specification-plan-terminology-migration/plan.yml")
    actual_specifications = {
        str(path.relative_to(ROOT)) for path in (ROOT / "specifications").glob("**/*") if path.is_file()
    }
    actual_plans = {
        str(path.relative_to(ROOT)) for path in (ROOT / "docs" / "plans").glob("**/*") if path.is_file()
    }

    assert actual_specifications == expected_specifications
    assert actual_plans == expected_plans


def test_plan_internal_schema_uses_plan_terms() -> None:
    for plan_path in (ROOT / "docs" / "plans").glob("*/plan.yml"):
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert "implementation_plan" not in plan, plan_path
        approvals = plan.get("approvals")
        if isinstance(approvals, dict):
            assert "product_contract" not in approvals, plan_path
            assert "implementation_plan" not in approvals, plan_path
        notes = plan.get("implementation_notes")
        if isinstance(notes, dict):
            assert "spec_path" not in notes, plan_path


def test_workflow_tools_and_canonical_skills_use_new_names() -> None:
    required_paths = [
        "scripts/specifications.py",
        "scripts/plan_validate.py",
        "scripts/plan_verify.py",
        ".claude/skills/define-specification/SKILL.md",
        ".claude/skills/create-plan/SKILL.md",
        ".claude/skills/tasks-from-plan/SKILL.md",
        ".claude/skills/verify-plan/SKILL.md",
        ".claude/skills/backfill-specification/SKILL.md",
        ".claude/agents/specification-verifier.md",
    ]
    removed_paths = [
        "scripts/contracts.py",
        "scripts/spec_validate.py",
        "scripts/spec_verify.py",
        ".claude/skills/define-contract/SKILL.md",
        ".claude/skills/specify/SKILL.md",
        ".claude/skills/plan-from-spec/SKILL.md",
        ".claude/skills/tasks-from-spec/SKILL.md",
        ".claude/skills/verify-spec/SKILL.md",
        ".claude/skills/backfill-contract/SKILL.md",
        ".claude/agents/contract-verifier.md",
    ]

    assert all((ROOT / path).exists() for path in required_paths)
    assert all(not (ROOT / path).exists() for path in removed_paths)


def test_specification_approval_workflow_targets_current_files() -> None:
    workflow = (ROOT / ".github" / "workflows" / "specification-approval-pdf.yml").read_text(encoding="utf-8")

    assert "test_specifications_workflow.py" in workflow
    assert "specification-approval-pdf.yml" in workflow
    assert "SPECIFICATION_PDF_RENDER_REQUIRED" in workflow
    assert "test_contracts_workflow.py" not in workflow
    assert "contract-approval-pdf.yml" not in workflow
    assert "CONTRACT_PDF_RENDER_REQUIRED" not in workflow


def test_generic_playwright_spec_and_provider_contract_terms_remain() -> None:
    assert next((ROOT / "frontend" / "apps" / "web_app" / "tests").glob("*.spec.ts"), None)
    assert (ROOT / "backend" / "tests" / "provider_contracts").is_dir()
