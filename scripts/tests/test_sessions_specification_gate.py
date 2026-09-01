#!/usr/bin/env python3
# contract-test-file: tooling
"""Deploy-time changed-test and exact Specification approval gate tests.

All state is temporary and repository-local. The gate never reads chat text or
product data. Architecture: docs/plans/contract-driven-development/plan.yml
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "specifications.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_specification_gate", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_sessions_module():
    path = ROOT / "scripts" / "sessions.py"
    spec = importlib.util.spec_from_file_location("openmates_sessions_specification_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_bundle(root: Path) -> Path:
    bundle = root / "specifications" / "features" / "example"
    bundle.mkdir(parents=True)
    (bundle / "specification.yml").write_text(
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
                "applies_to": {
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
                "specification": "feature.example@1",
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
def test_gate_requires_current_exact_hash_approval_for_specification_change(tmp_path):
    module = load_module()
    bundle = write_bundle(tmp_path)
    approvals = tmp_path / "approvals.json"
    changed = ["specifications/features/example/specification.yml"]

    assert any("missing approval" in error for error in module.check_changed_files(tmp_path, changed, session_id="session", approvals_path=approvals))

    loaded = module.validate_bundle(bundle)
    module.record_approval(
        approvals,
        session_id="session",
        specification_id=loaded.specification_id,
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
    specification_path = bundle / "specification.yml"
    specification = yaml.safe_load(specification_path.read_text(encoding="utf-8"))
    specification["examples"]["file"] = "specification-examples.yml"
    specification_path.write_text(yaml.safe_dump(specification, sort_keys=False), encoding="utf-8")
    (bundle / "examples.yml").rename(bundle / "specification-examples.yml")
    changed = ["specifications/features/example/specification-examples.yml"]

    errors = module.check_changed_files(
        tmp_path,
        changed,
        session_id="session",
        approvals_path=tmp_path / "approvals.json",
    )

    assert any("missing approval" in error for error in errors)


# contract-test: tooling
def test_gate_verifies_changed_schema_v3_plans_against_registry(tmp_path, monkeypatch):
    module = load_module()
    spec = tmp_path / "docs" / "plans" / "example" / "plan.yml"
    spec.parent.mkdir(parents=True)
    spec.write_text("schema_version: 3\n", encoding="utf-8")
    monkeypatch.setattr(module, "verify_plan_specifications", lambda *args, **kwargs: ["unknown Specification ref feature.missing@1"])
    generated = tmp_path / "specifications" / "generated"
    generated.mkdir(parents=True)
    monkeypatch.setattr(module, "check_generated_integrity", lambda *args, **kwargs: ["generated drift"])

    errors = module.check_changed_files(
        tmp_path,
        ["docs/plans/example/plan.yml"],
        session_id="session",
        approvals_path=tmp_path / "approvals.json",
    )

    assert errors == ["unknown Specification ref feature.missing@1", "generated drift"]


# contract-test: tooling
def test_sessions_deploy_gate_hard_blocks_specification_failure(tmp_path, monkeypatch):
    sessions = load_sessions_module()
    script = tmp_path / "scripts" / "specifications.py"
    script.parent.mkdir()
    script.write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        sessions.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="unmapped test"),
    )

    with pytest.raises(RuntimeError, match="SPECIFICATION GATE FAILED"):
        sessions._run_specification_gate(
            ["tests/example.spec.ts"],
            session_id="session",
            checkout_root=tmp_path,
        )


# contract-test: tooling
def test_sessions_deploy_gate_scales_timeout_for_large_migrations(tmp_path, monkeypatch):
    sessions = load_sessions_module()
    script = tmp_path / "scripts" / "specifications.py"
    script.parent.mkdir()
    script.write_text("# fixture\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sessions.subprocess, "run", fake_run)

    sessions._run_specification_gate(
        [f"docs/plans/example-{index}/plan.yml" for index in range(80)],
        session_id="session",
        checkout_root=tmp_path,
    )

    assert calls[-1]["timeout"] > 60
    assert calls[-1]["timeout"] <= sessions.SPECIFICATION_GATE_MAX_TIMEOUT_SECONDS


# contract-test: tooling
def test_sessions_deploy_gate_reports_specification_timeout_cleanly(tmp_path, monkeypatch):
    sessions = load_sessions_module()
    script = tmp_path / "scripts" / "specifications.py"
    script.parent.mkdir()
    script.write_text("# fixture\n", encoding="utf-8")

    def fake_run(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="specifications.py check-changed", timeout=kwargs["timeout"])

    monkeypatch.setattr(sessions.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="SPECIFICATION GATE TIMEOUT"):
        sessions._run_specification_gate(
            ["docs/plans/example/plan.yml"],
            session_id="session",
            checkout_root=tmp_path,
        )


# contract-test: tooling
def test_specification_commit_requires_searchable_trailers():
    sessions = load_sessions_module()
    files = ["specifications/features/example/specification.yml"]

    with pytest.raises(RuntimeError, match="Specifications:"):
        sessions._validate_specification_commit_message(files, "feat: add Specification")

    sessions._validate_specification_commit_message(
        files,
        "feat: add Specification\n\nSpecifications: feature.example@1\nAssertions: example.behavior.works\nPlan: example\nSpecification-Impact: new-specification",
    )


def test_deploy_commit_preflight_builds_safe_repeatable_trailers():
    sessions = load_sessions_module()
    args = SimpleNamespace(
        title="feat: add Specification",
        message=None,
        trailer=[
            "Specifications: feature.example@1",
            "Assertions: example.behavior.works",
            "Plan: example",
            "Specification-Impact: new-specification",
        ],
    )

    message = sessions._preflight_deploy_commit_message(
        args,
        {},
        ["specifications/features/example/specification.yml"],
    )

    assert message.endswith("\n".join(args.trailer))


def test_deploy_commit_preflight_rejects_missing_or_multiline_trailers():
    sessions = load_sessions_module()
    files = ["specifications/features/example/specification.yml"]

    with pytest.raises(RuntimeError, match="repeatable one-line arguments"):
        sessions._preflight_deploy_commit_message(
            SimpleNamespace(title="feat: add Specification", message=None, trailer=[]),
            {},
            files,
        )

    with pytest.raises(RuntimeError, match="one non-empty line"):
        sessions._preflight_deploy_commit_message(
            SimpleNamespace(
                title="feat: add Specification",
                message=None,
                trailer=["Specifications: feature.example@1\nAssertions: example.behavior.works"],
            ),
            {},
            files,
        )


def test_specification_approval_pdf_uses_current_tooling_with_session_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    checkout = tmp_path / "agent-abcd"
    checkout.mkdir()
    calls = []
    old_root = tmp_path / "control"
    fake = SimpleNamespace(
        REPO_ROOT=old_root,
        specifications=SimpleNamespace(REPO_ROOT=old_root),
        main=lambda argv: calls.append(argv) or 0,
    )
    import scripts as scripts_package

    monkeypatch.setattr(scripts_package, "specification_approval_pdf", fake, raising=False)
    monkeypatch.setitem(sys.modules, "scripts.specification_approval_pdf", fake)
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {"sessions": {"abcd": {"worktree": {"path": str(checkout)}}}},
    )

    sessions.cmd_specification(
        SimpleNamespace(
            specification_action="approval-pdf",
            session="abcd",
            bundle="specifications/features/example",
            baseline_ref="HEAD",
            new_specification=True,
            no_upload=True,
            dry_run_upload=False,
            json=True,
        )
    )

    assert calls == [[
        str(checkout / "specifications/features/example"),
        "--baseline-ref",
        "HEAD",
        "--new-specification",
        "--no-upload",
        "--json",
    ]]
    assert fake.REPO_ROOT == old_root
    assert fake.specifications.REPO_ROOT == old_root
