#!/usr/bin/env python3
# contract-test-file: tooling
"""Specification bundle, registry, coverage, and approval workflow tests.

These tests exercise repository-local contract infrastructure with temporary
fixtures. They do not inspect product data or make network requests.
Architecture: docs/plans/contract-driven-development/plan.yml
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "specifications.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_specifications", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_bundle(root: Path, *, specification_id: str = "feature.web-search", assertion_id: str = "web-search.request.validated") -> Path:
    bundle = root / "features" / "web-search"
    bundle.mkdir(parents=True)
    specification = {
        "schema_version": 1,
        "id": specification_id,
        "version": 1,
        "status": "approved",
        "title": "Web Search",
        "summary": "Search the public web.",
        "scope": {"includes": ["Public search"], "excludes": ["Private pages"]},
        "models": {
            "Request": {
                "query": {
                    "type": "string",
                    "required": True,
                    "constraints": {"min_length": 2, "max_length": 400},
                }
            }
        },
        "assertions": [
            {
                "id": assertion_id,
                "type": "validation",
                "must": "Invalid requests are rejected before execution.",
            }
        ],
        "applies_to": {
            "rest_api": {"required": True},
            "cli": {"required": True},
            "sdks": {
                "required": True,
                "implementations": {"npm": {"required": True}, "pip": {"required": True}},
            },
            "gui": {
                "required": True,
                "implementations": {"web": {"required": True}, "apple": {"required": True}},
                "exceptions": [],
            },
        },
        "examples": {
            "file": "examples.yml",
            "required_groups": ["valid_inputs", "invalid_inputs", "successful_outputs", "error_outputs", "boundary_cases"],
        },
    }
    examples = {
        "schema_version": 1,
        "specification": f"{specification_id}@1",
        "valid_inputs": [{"id": "valid", "input": {"query": "OpenMates"}, "expect": {"status": "completed"}}],
        "invalid_inputs": [{"id": "blank", "input": {"query": ""}, "expect_error": {"code": "INVALID_REQUEST"}}],
        "successful_outputs": [{"id": "result", "output": {"status": "completed"}}],
        "error_outputs": [{"id": "error", "output": {"status": "provider_error"}}],
        "boundary_cases": [{"id": "minimum", "input": {"query": "AI"}, "expect": "accepted"}],
    }
    (bundle / "specification.yml").write_text(yaml.safe_dump(specification, sort_keys=False), encoding="utf-8")
    (bundle / "examples.yml").write_text(yaml.safe_dump(examples, sort_keys=False), encoding="utf-8")
    return bundle


# contract-test: tooling
def test_valid_bundle_and_registry_are_deterministic(tmp_path):
    module = load_module()
    specifications_root = tmp_path / "specifications"
    bundle = write_bundle(specifications_root)

    loaded = module.validate_bundle(bundle)
    first = module.build_registry(specifications_root)
    second = module.build_registry(specifications_root)

    assert loaded.specification_id == "feature.web-search"
    assert loaded.fingerprint
    assert first == second
    assert first["assertions"]["web-search.request.validated"]["specification"] == "feature.web-search@1"


def test_non_software_bundle_accepts_general_applicability_without_models(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path / "specifications", specification_id="operation.autumn-campaign")
    specification_path = bundle / "specification.yml"
    specification = yaml.safe_load(specification_path.read_text(encoding="utf-8"))
    specification.pop("models")
    specification["applies_to"] = {
        "markets": ["Germany", "Austria"],
        "audiences": ["Existing customers"],
        "artifacts": ["Newsletter", "Landing page"],
    }
    specification_path.write_text(yaml.safe_dump(specification, sort_keys=False), encoding="utf-8")

    loaded = module.validate_bundle(bundle)
    registry = module.build_registry(tmp_path / "specifications")
    reference = module.render_specification_reference(loaded)

    assert loaded.specification_id == "operation.autumn-campaign"
    assert registry["specifications"]["operation.autumn-campaign"]["required_applies_to"] == []
    assert "## Models" not in reference
    assert "## Assertions" in reference


def test_bundle_rejects_extra_implementation_without_required_flag(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path / "specifications")
    specification_path = bundle / "specification.yml"
    specification = yaml.safe_load(specification_path.read_text(encoding="utf-8"))
    specification["applies_to"]["sdks"]["implementations"]["rust"] = {}
    specification_path.write_text(yaml.safe_dump(specification, sort_keys=False), encoding="utf-8")

    with pytest.raises(module.SpecificationError, match=r"implementations\.rust\.required must be boolean"):
        module.validate_bundle(bundle)


# contract-test: tooling
def test_bundle_rejects_missing_required_example_group(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path / "specifications")
    examples_path = bundle / "examples.yml"
    examples = yaml.safe_load(examples_path.read_text(encoding="utf-8"))
    del examples["boundary_cases"]
    examples_path.write_text(yaml.safe_dump(examples, sort_keys=False), encoding="utf-8")

    with pytest.raises(module.SpecificationError, match="boundary_cases"):
        module.validate_bundle(bundle)


# contract-test: tooling
def test_registry_rejects_duplicate_global_assertion_ids(tmp_path):
    module = load_module()
    specifications_root = tmp_path / "specifications"
    write_bundle(specifications_root, specification_id="feature.first", assertion_id="shared.assertion")
    write_bundle(specifications_root / "other", specification_id="feature.second", assertion_id="shared.assertion")

    with pytest.raises(module.SpecificationError, match="duplicate assertion id"):
        module.build_registry(specifications_root)


# contract-test: tooling
def test_examples_change_invalidates_bundle_fingerprint(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path / "specifications")
    before = module.validate_bundle(bundle).fingerprint
    examples_path = bundle / "examples.yml"
    examples = yaml.safe_load(examples_path.read_text(encoding="utf-8"))
    examples["valid_inputs"][0]["input"]["query"] = "Updated example"
    examples_path.write_text(yaml.safe_dump(examples, sort_keys=False), encoding="utf-8")

    after = module.validate_bundle(bundle).fingerprint

    assert after != before


# contract-test: tooling
def test_session_approval_matches_exact_bundle_hash(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path / "specifications")
    approvals_path = tmp_path / "approvals.json"
    fingerprint = module.validate_bundle(bundle).fingerprint

    module.record_approval(
        approvals_path,
        session_id="d1ff",
        specification_id="feature.web-search",
        fingerprint=fingerprint,
        confirmation="explicit_user_confirmation",
        review_artifact={"fingerprint": fingerprint, "pdf_sha256": "a" * 64},
    )

    assert module.check_approval(approvals_path, "d1ff", "feature.web-search", fingerprint) is None
    assert "stale" in module.check_approval(approvals_path, "d1ff", "feature.web-search", "different-hash")
    saved = json.loads(approvals_path.read_text(encoding="utf-8"))
    assert saved["sessions"]["d1ff"]["feature.web-search"]["fingerprint"] == fingerprint


# contract-test: tooling
def test_plan_backed_batch_approval_matches_exact_bundle_hash(tmp_path):
    module = load_module()
    bundle_path = write_bundle(tmp_path / "specifications")
    bundle = module.validate_bundle(bundle_path)
    approvals_path = tmp_path / "approvals.json"
    plan = tmp_path / "docs" / "plans" / "terminology-migration" / "plan.yml"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "id": "terminology-migration",
                "status": "approved",
                "clarification": {"approved_by_user": True},
                "approvals": {
                    "specification": {"status": "approved"},
                    "plan": {"status": "approved"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    fingerprints = {bundle.specification_id: bundle.fingerprint}
    artifact = module._approved_plan_batch_review_artifact(plan, fingerprints)

    module.record_batch_approval(
        approvals_path,
        session_id="d1ff",
        approval_id="terminology-migration",
        specification_fingerprints=fingerprints,
        confirmation="explicit_user_confirmation",
        review_artifact=artifact,
    )

    assert module.check_approval(approvals_path, "d1ff", bundle.specification_id, bundle.fingerprint) is None
    assert "stale batch approval" in module.check_approval(
        approvals_path,
        "d1ff",
        bundle.specification_id,
        "different-hash",
    )
    assert "missing approval" in module.check_approval(
        approvals_path,
        "d1ff",
        "feature.other",
        "different-hash",
    )


# contract-test: tooling
def test_review_artifact_rejects_a_stale_bundle_fingerprint(tmp_path):
    module = load_module()
    bundle_path = write_bundle(tmp_path / "specifications")
    bundle = module.validate_bundle(bundle_path)
    pdf = tmp_path / "approval.pdf"
    pdf.write_bytes(b"%PDF current")
    artifact = tmp_path / "approval.json"
    artifact.write_text(
        json.dumps({
            "specification": bundle.versioned_id,
            "fingerprint": "stale-fingerprint",
            "baseline_ref": "HEAD",
            "baseline_commit": "b" * 40,
            "pdf": str(pdf),
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "highlight_policy": {
                "additions": "inline_green_plus",
                "removals": "inline_red_minus",
                "unchanged": "neutral",
                "granularity": "changed_text_only",
            },
            "approval_eligible": True,
            "publication": {"bucket": "private", "key": "contract.pdf", "sha256": f"sha256:{hashlib.sha256(pdf.read_bytes()).hexdigest()}"},
        }),
        encoding="utf-8",
    )

    with pytest.raises(module.SpecificationError, match="does not match"):
        module.validate_review_artifact(artifact, bundle)


# contract-test: tooling
def test_review_artifact_rejects_a_dry_run_publication(tmp_path):
    module = load_module()
    bundle_path = write_bundle(tmp_path / "specifications")
    bundle = module.validate_bundle(bundle_path)
    pdf = tmp_path / "approval.pdf"
    pdf.write_bytes(b"%PDF local only")
    artifact = tmp_path / "approval.json"
    artifact.write_text(
        json.dumps({
            "specification": bundle.versioned_id,
            "fingerprint": bundle.fingerprint,
            "baseline_ref": "HEAD",
            "baseline_commit": "b" * 40,
            "pdf": str(pdf),
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "highlight_policy": {
                "additions": "inline_green_plus",
                "removals": "inline_red_minus",
                "unchanged": "neutral",
                "granularity": "changed_text_only",
            },
            "approval_eligible": False,
            "publication": {"bucket": "private", "key": "dry-run-contract.pdf", "sha256": f"sha256:{hashlib.sha256(pdf.read_bytes()).hexdigest()}"},
        }),
        encoding="utf-8",
    )

    with pytest.raises(module.SpecificationError, match="privately uploaded"):
        module.validate_review_artifact(artifact, bundle)


# contract-test: tooling
def test_coverage_keeps_inventory_mapping_proof_and_surfaces_separate(tmp_path):
    module = load_module()
    specifications_root = tmp_path / "specifications"
    write_bundle(specifications_root)
    registry = module.build_registry(specifications_root)

    coverage = module.build_coverage(registry, test_index={})

    assert coverage["approved_specifications"] == 1
    assert coverage["assertions_total"] == 1
    assert coverage["assertions_with_tests"] == 0
    assert coverage["assertions_with_current_proof"] == 0
    assert coverage["surface_parity"]["rest_api"]["required"] == 1


# contract-test: tooling
def test_generate_specification_artifacts_replays_spec_evidence_files(tmp_path, monkeypatch):
    module = load_module()
    specifications_root = tmp_path / "specifications"
    write_bundle(specifications_root)
    monkeypatch.setattr(module, "_git_head", lambda _root: "head123")
    test_path = tmp_path / "tests" / "test_api.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "# contract-test: direct surface=rest_api assertions=web-search.request.validated\n"
        "def test_valid():\n"
        "    pass\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "docs" / "plans" / "example" / "evidence" / "report.json"
    report_path.parent.mkdir(parents=True)
    report = {
        "run_id": "run-1",
        "subject_commit": "head123",
        "tests": [{"path": "tests/test_api.py", "name": "test_valid", "status": "passed"}],
    }
    report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    fingerprint = module.build_registry(specifications_root)["assertions"]["web-search.request.validated"]["fingerprint"]
    (report_path.parent / "evidence.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "evidence": [
                    {
                        "assertion": "web-search.request.validated",
                        "assertion_fingerprint": fingerprint,
                        "classification": "direct",
                        "surface": "rest_api",
                        "status": "passed",
                        "subject_commit": "head123",
                        "run_id": "run-1",
                        "test_path": "tests/test_api.py",
                        "test_name": "test_valid",
                        "run_artifact": "docs/plans/example/evidence/report.json",
                        "run_artifact_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    module.generate_specification_artifacts(tmp_path, specifications_root=specifications_root)

    index = yaml.safe_load((specifications_root / "generated" / "assertion-index.yml").read_text(encoding="utf-8"))
    surface = index["assertions"]["web-search.request.validated"]["surfaces"]["rest_api"]
    assert index["assertions"]["web-search.request.validated"]["current_direct_proof"] is True
    assert surface["current_direct_proof"] is True
    assert surface["evidence_history"][0]["run_id"] == "run-1"


# contract-test: tooling
def test_generated_integrity_rejects_registry_drift(tmp_path):
    module = load_module()
    specifications_root = tmp_path / "specifications"
    write_bundle(specifications_root)
    generated = specifications_root / "generated"
    generated.mkdir()
    (generated / "registry.yml").write_text("schema_version: 1\ncontracts: {}\nassertions: {}\n", encoding="utf-8")
    (generated / "assertion-index.yml").write_text("schema_version: 1\nassertions: {}\n", encoding="utf-8")
    (generated / "coverage.yml").write_text("schema_version: 1\n", encoding="utf-8")

    errors = module.check_generated_integrity(tmp_path, specifications_root=specifications_root)

    assert any("registry.yml is stale" in error for error in errors)


# contract-test: tooling
def test_repository_test_discovery_prunes_managed_worktrees(tmp_path):
    module = load_module()
    source_test = tmp_path / "scripts" / "tests" / "test_source.py"
    worktree_test = tmp_path / ".openmates-agent-worktrees" / "agent-old" / "scripts" / "tests" / "test_copy.py"
    source_test.parent.mkdir(parents=True)
    worktree_test.parent.mkdir(parents=True)
    source_test.write_text("def test_source(): pass\n", encoding="utf-8")
    worktree_test.write_text("def test_copy(): pass\n", encoding="utf-8")

    discovered = module._repository_test_files(tmp_path)

    assert discovered == [source_test]


# contract-test: tooling
def test_evidence_preflight_rejects_stale_merged_session_worktree(monkeypatch, tmp_path):
    module = load_module()
    control_root = tmp_path / "repo"
    worktree = control_root / ".openmates-agent-worktrees" / "agent-abcd"
    sessions_dir = control_root / ".claude"
    sessions_dir.mkdir(parents=True)
    worktree.mkdir(parents=True)
    (sessions_dir / "sessions.json").write_text(
        json.dumps(
            {
                "sessions": {
                    "abcd": {
                        "worktree": {
                            "path": str(worktree),
                            "status": "merged",
                            "merged_commit": "merged123456",
                        }
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONTROL_PLANE_ROOT", control_root)
    monkeypatch.setattr(module, "_git_head", lambda _root: "stale987654")
    monkeypatch.setattr(module, "_git_dirty_files", lambda _root: [" M scripts/specifications.py"])

    error = module._merged_session_worktree_error(worktree)

    assert error is not None
    assert "stale merged session worktree abcd" in error
    assert "HEAD stale987" in error
    assert "merged commit merged123" in error
    assert "1 dirty file" in error
