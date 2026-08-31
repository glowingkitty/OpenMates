#!/usr/bin/env python3
"""Deploy-time changed-test and exact contract approval gate tests.

All state is temporary and repository-local. The gate never reads chat text or
product data. Architecture: docs/specs/contract-driven-development/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "contracts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_contract_gate", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_sessions_module():
    path = ROOT / "scripts" / "sessions.py"
    spec = importlib.util.spec_from_file_location("openmates_sessions_contract_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_bundle(root: Path) -> Path:
    bundle = root / "contracts" / "features" / "example"
    bundle.mkdir(parents=True)
    (bundle / "contract.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "feature.example",
                "version": 1,
                "status": "approved",
                "title": "Example",
                "summary": "Example behavior.",
                "scope": {"includes": ["Example"], "excludes": ["Other"]},
                "models": {"Input": {"value": {"type": "string", "required": True}}},
                "assertions": [{"id": "example.behavior.works", "type": "behavior", "must": "Example works."}],
                "surfaces": {
                    "rest_api": {"required": True},
                    "cli": {"required": False},
                    "sdks": {"required": False, "implementations": {"npm": {"required": False}, "pip": {"required": False}}},
                    "gui": {"required": False, "implementations": {"web": {"required": False}, "apple": {"required": False}}, "exceptions": []},
                },
                "examples": {"file": "examples.yml", "required_groups": ["valid_inputs", "invalid_inputs"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (bundle / "examples.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "contract": "feature.example@1",
                "valid_inputs": [{"id": "valid", "input": {"value": "yes"}}],
                "invalid_inputs": [{"id": "invalid", "input": {"value": ""}}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return bundle


# contract-test: tooling
def test_gate_blocks_changed_unmapped_test(tmp_path):
    module = load_module()
    path = tmp_path / "tests" / "example.spec.ts"
    path.parent.mkdir()
    path.write_text("test('behavior', () => {});\n", encoding="utf-8")

    errors = module.check_changed_files(
        tmp_path,
        ["tests/example.spec.ts"],
        session_id="session",
        approvals_path=tmp_path / "approvals.json",
    )

    assert any("missing contract-test metadata" in error for error in errors)


# contract-test: tooling
def test_gate_allows_changed_infrastructure_test(tmp_path):
    module = load_module()
    path = tmp_path / "tests" / "test_runner.py"
    path.parent.mkdir()
    path.write_text("# contract-test: infrastructure\ndef test_runner():\n    pass\n", encoding="utf-8")

    assert module.check_changed_files(
        tmp_path,
        ["tests/test_runner.py"],
        session_id="session",
        approvals_path=tmp_path / "approvals.json",
    ) == []


# contract-test: tooling
def test_gate_requires_current_exact_hash_approval_for_contract_change(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path)
    approvals = tmp_path / "approvals.json"
    changed = ["contracts/features/example/contract.yml"]

    assert any("missing approval" in error for error in module.check_changed_files(tmp_path, changed, session_id="session", approvals_path=approvals))

    loaded = module.validate_bundle(bundle)
    module.record_approval(
        approvals,
        session_id="session",
        contract_id=loaded.contract_id,
        fingerprint=loaded.fingerprint,
        confirmation="explicit_user_confirmation",
        review_artifact={"fingerprint": loaded.fingerprint, "pdf_sha256": "a" * 64},
    )
    assert module.check_changed_files(tmp_path, changed, session_id="session", approvals_path=approvals) == []

    examples = yaml.safe_load((bundle / "examples.yml").read_text(encoding="utf-8"))
    examples["valid_inputs"][0]["input"]["value"] = "changed"
    (bundle / "examples.yml").write_text(yaml.safe_dump(examples, sort_keys=False), encoding="utf-8")
    assert any("stale approval" in error for error in module.check_changed_files(tmp_path, changed, session_id="session", approvals_path=approvals))


# contract-test: tooling
def test_gate_binds_approval_to_alternate_examples_filename(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path)
    contract_path = bundle / "contract.yml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["examples"]["file"] = "contract-examples.yml"
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    (bundle / "examples.yml").rename(bundle / "contract-examples.yml")
    changed = ["contracts/features/example/contract-examples.yml"]

    errors = module.check_changed_files(
        tmp_path,
        changed,
        session_id="session",
        approvals_path=tmp_path / "approvals.json",
    )

    assert any("missing approval" in error for error in errors)


# contract-test: tooling
def test_gate_verifies_changed_schema_v3_specs_against_registry(tmp_path, monkeypatch):
    module = load_module()
    spec = tmp_path / "docs" / "specs" / "example" / "spec.yml"
    spec.parent.mkdir(parents=True)
    spec.write_text("schema_version: 3\n", encoding="utf-8")
    monkeypatch.setattr(module, "verify_spec_contracts", lambda *args, **kwargs: ["unknown contract ref feature.missing@1"])
    generated = tmp_path / "contracts" / "generated"
    generated.mkdir(parents=True)
    monkeypatch.setattr(module, "check_generated_integrity", lambda *args, **kwargs: ["generated drift"])

    errors = module.check_changed_files(
        tmp_path,
        ["docs/specs/example/spec.yml"],
        session_id="session",
        approvals_path=tmp_path / "approvals.json",
    )

    assert errors == ["unknown contract ref feature.missing@1", "generated drift"]


# contract-test: tooling
def test_sessions_deploy_gate_hard_blocks_contract_failure(tmp_path, monkeypatch):
    sessions = load_sessions_module()
    script = tmp_path / "scripts" / "contracts.py"
    script.parent.mkdir()
    script.write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        sessions.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="unmapped test"),
    )

    with pytest.raises(RuntimeError, match="CONTRACT GATE FAILED"):
        sessions._run_contract_gate(
            ["tests/example.spec.ts"],
            session_id="session",
            checkout_root=tmp_path,
        )


# contract-test: tooling
def test_contract_commit_requires_searchable_trailers():
    sessions = load_sessions_module()
    files = ["contracts/features/example/contract.yml"]

    with pytest.raises(RuntimeError, match="Contracts:"):
        sessions._validate_contract_commit_message(files, "feat: add contract")

    sessions._validate_contract_commit_message(
        files,
        "feat: add contract\n\nContracts: feature.example@1\nAssertions: example.behavior.works\nSpec: example\nContract-Impact: new-contract",
    )
