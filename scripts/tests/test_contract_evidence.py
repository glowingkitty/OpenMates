#!/usr/bin/env python3
"""Assertion fingerprint and current evidence validation tests.

Fixtures prove precise invalidation and surface accounting without running
product tests. Architecture: docs/specs/contract-driven-development/spec.yml
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "contracts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_contract_evidence", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def registry() -> dict:
    return {
        "assertions": {
            "feature.valid": {"contract": "feature.example@1", "fingerprint": "valid-hash", "required_surfaces": ["rest_api"]},
            "feature.other": {"contract": "feature.example@1", "fingerprint": "other-hash", "required_surfaces": ["rest_api"]},
        }
    }


def evidence_index() -> dict:
    return {
        "schema_version": 1,
        "assertions": {
            "feature.valid": {
                "contract": "feature.example@1",
                "fingerprint": "valid-hash",
                "direct_tests": [{"path": "tests/test_api.py", "line": 1, "name": "test_valid", "surface": "rest_api"}],
                "supporting_tests": [{"path": "tests/test_api.py", "line": 2, "name": "test_support", "surface": "rest_api"}],
                "tests": [{"path": "tests/test_api.py", "line": 1, "name": "test_valid", "surface": "rest_api"}],
                "surfaces": {
                    "rest_api": {
                        "direct_tests": [{"path": "tests/test_api.py", "line": 1, "name": "test_valid", "surface": "rest_api"}],
                        "supporting_tests": [{"path": "tests/test_api.py", "line": 2, "name": "test_support", "surface": "rest_api"}],
                    }
                },
                "current_direct_proof": False,
            },
            "feature.other": {
                "contract": "feature.example@1",
                "fingerprint": "other-hash",
                "direct_tests": [],
                "supporting_tests": [],
                "tests": [],
                "surfaces": {},
                "current_direct_proof": False,
            },
        },
    }


# contract-test: tooling
def test_matching_direct_evidence_marks_assertion_and_surface_current():
    module = load_module()
    evidence = [
        {
            "assertion": "feature.valid",
            "assertion_fingerprint": "valid-hash",
            "classification": "direct",
            "surface": "rest_api",
            "status": "passed",
            "subject_commit": "abc1234",
            "run_id": "run-1",
        }
    ]

    result, errors = module.apply_evidence(registry(), evidence_index(), evidence)

    assert errors == []
    assert result["assertions"]["feature.valid"]["current_direct_proof"] is True
    assert result["assertions"]["feature.valid"]["surfaces"]["rest_api"]["current_direct_proof"] is True


# contract-test: tooling
def test_stale_fingerprint_remains_history_but_not_current_proof():
    module = load_module()
    evidence = [
        {
            "assertion": "feature.valid",
            "assertion_fingerprint": "old-hash",
            "classification": "direct",
            "surface": "rest_api",
            "status": "passed",
            "subject_commit": "abc1234",
            "run_id": "run-old",
        }
    ]

    result, errors = module.apply_evidence(registry(), evidence_index(), evidence)

    assert errors == []
    assert result["assertions"]["feature.valid"]["current_direct_proof"] is False
    assert result["assertions"]["feature.valid"]["evidence_history"][0]["run_id"] == "run-old"


# contract-test: tooling
def test_supporting_evidence_never_satisfies_direct_proof():
    module = load_module()
    evidence = [
        {
            "assertion": "feature.valid",
            "assertion_fingerprint": "valid-hash",
            "classification": "supporting",
            "surface": "rest_api",
            "status": "passed",
            "subject_commit": "abc1234",
            "run_id": "run-support",
        }
    ]

    result, errors = module.apply_evidence(registry(), evidence_index(), evidence)

    assert errors == []
    assert result["assertions"]["feature.valid"]["current_direct_proof"] is False


# contract-test: tooling
def test_verified_contract_proof_requires_each_declared_surface():
    module = load_module()
    index = evidence_index()
    index["assertions"]["feature.valid"]["surfaces"]["rest_api"]["current_direct_proof"] = True

    assert module.check_required_proof(registry(), index, {"feature.valid"}) == []

    index["assertions"]["feature.valid"]["surfaces"]["rest_api"]["current_direct_proof"] = False
    errors = module.check_required_proof(registry(), index, {"feature.valid"})
    assert errors == ["feature.valid lacks current direct proof on required surface rest_api"]


# contract-test: tooling
def test_current_evidence_requires_mapped_test_hashed_report_and_subject_commit(tmp_path):
    module = load_module()
    report = {
        "run_id": "run-1",
        "subject_commit": "abc1234",
        "tests": [{"path": "tests/test_api.py", "name": "test_valid", "status": "passed"}],
    }
    report_path = tmp_path / "run.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    evidence = [{
        "assertion": "feature.valid",
        "assertion_fingerprint": "valid-hash",
        "classification": "direct",
        "surface": "rest_api",
        "status": "passed",
        "subject_commit": "abc1234",
        "run_id": "run-1",
        "test_path": "tests/test_api.py",
        "test_name": "test_valid",
        "run_artifact": "run.json",
        "run_artifact_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }]

    result, errors = module.apply_evidence(
        registry(), evidence_index(), evidence, repo_root=tmp_path, expected_subject_commit="abc1234"
    )
    assert errors == []
    assert result["assertions"]["feature.valid"]["current_direct_proof"] is True

    evidence[0]["subject_commit"] = "stale"
    _, errors = module.apply_evidence(
        registry(), evidence_index(), evidence, repo_root=tmp_path, expected_subject_commit="abc1234"
    )
    assert any("tested subject commit" in error for error in errors)


# contract-test: tooling
def test_current_evidence_allows_metadata_only_followup_commit(tmp_path, monkeypatch):
    module = load_module()
    report = {
        "run_id": "run-1",
        "subject_commit": "tested",
        "tests": [{"path": "tests/test_api.py", "name": "test_valid", "status": "passed"}],
    }
    report_path = tmp_path / "run.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    evidence = [{
        "assertion": "feature.valid",
        "assertion_fingerprint": "valid-hash",
        "classification": "direct",
        "surface": "rest_api",
        "status": "passed",
        "subject_commit": "tested",
        "run_id": "run-1",
        "test_path": "tests/test_api.py",
        "test_name": "test_valid",
        "run_artifact": "run.json",
        "run_artifact_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }]
    monkeypatch.setattr(
        module,
        "_metadata_only_evidence_paths_since",
        lambda *_args: [
            "contracts/generated/assertion-index.yml",
            "docs/specs/example/spec.yml",
            "docs/specs/example/evidence/run.json",
            "tests/test_api.py",
        ],
    )
    monkeypatch.setattr(module, "_is_contract_test_metadata_only_change", lambda *_args: True)

    result, errors = module.apply_evidence(
        registry(), evidence_index(), evidence, repo_root=tmp_path, expected_subject_commit="head"
    )

    assert errors == []
    assert result["assertions"]["feature.valid"]["current_direct_proof"] is True


# contract-test: tooling
def test_current_evidence_allows_contract_tooling_followup_commit(tmp_path, monkeypatch):
    module = load_module()
    report = {
        "run_id": "run-1",
        "subject_commit": "tested",
        "tests": [{"path": "tests/test_api.py", "name": "test_valid", "status": "passed"}],
    }
    report_path = tmp_path / "run.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    evidence = [{
        "assertion": "feature.valid",
        "assertion_fingerprint": "valid-hash",
        "classification": "direct",
        "surface": "rest_api",
        "status": "passed",
        "subject_commit": "tested",
        "run_id": "run-1",
        "test_path": "tests/test_api.py",
        "test_name": "test_valid",
        "run_artifact": "run.json",
        "run_artifact_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }]
    monkeypatch.setattr(
        module,
        "_metadata_only_evidence_paths_since",
        lambda *_args: [
            "scripts/contracts.py",
            "scripts/spec_verify.py",
            "scripts/tests/test_contract_evidence.py",
            "scripts/tests/test_contracts_workflow.py",
            "scripts/tests/test_spec_demonstration_workflow.py",
            "docs/specs/example/evidence/run.yml",
            "contracts/generated/assertion-index.yml",
        ],
    )

    result, errors = module.apply_evidence(
        registry(), evidence_index(), evidence, repo_root=tmp_path, expected_subject_commit="head"
    )

    assert errors == []
    assert result["assertions"]["feature.valid"]["current_direct_proof"] is True


# contract-test: tooling
def test_current_evidence_rejects_stale_product_commit(tmp_path, monkeypatch):
    module = load_module()
    report = {
        "run_id": "run-1",
        "subject_commit": "tested",
        "tests": [{"path": "tests/test_api.py", "name": "test_valid", "status": "passed"}],
    }
    report_path = tmp_path / "run.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    evidence = [{
        "assertion": "feature.valid",
        "assertion_fingerprint": "valid-hash",
        "classification": "direct",
        "surface": "rest_api",
        "status": "passed",
        "subject_commit": "tested",
        "run_id": "run-1",
        "test_path": "tests/test_api.py",
        "test_name": "test_valid",
        "run_artifact": "run.json",
        "run_artifact_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }]
    monkeypatch.setattr(module, "_metadata_only_evidence_paths_since", lambda *_args: ["backend/app.py"])

    _, errors = module.apply_evidence(
        registry(), evidence_index(), evidence, repo_root=tmp_path, expected_subject_commit="head"
    )

    assert any("tested subject commit" in error for error in errors)
