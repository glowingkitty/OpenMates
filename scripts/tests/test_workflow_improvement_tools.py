"""Regression tests for deterministic workflow-improvement helper scripts.

Purpose: keep workflow helper behavior covered without remote services.
Scope: static scans, YAML evidence mutation, and readiness row generation.
Safety: no Playwright dispatch, no Vercel calls, and no production data access.
Run: python3 -m pytest scripts/tests/test_workflow_improvement_tools.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_e2e_flake_audit_flags_raw_wait(tmp_path):
    audit = load_script("audit_e2e_flake_patterns")
    spec_path = tmp_path / "chat-flow.spec.ts"
    spec_path.write_text("await page.waitForTimeout(1000);\n", encoding="utf-8")

    findings = audit.scan_source(spec_path)

    assert len(findings) == 1
    assert findings[0].kind == "raw-wait"


def test_spec_evidence_records_verification(tmp_path, monkeypatch):
    spec_evidence = load_script("spec_evidence")
    spec_path = tmp_path / "spec.yml"
    spec_path.write_text(
        yaml.safe_dump({
            "id": "example",
            "verifications": [{"id": "V-1", "status": "pending", "evidence": {}}],
        }, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(spec_evidence, "current_git_sha", lambda: "abc123def")

    args = type("Args", (), {
        "spec": spec_path,
        "status": "passed",
        "command": "python3 -m pytest example.py",
        "run_id": "local:green",
        "subject_commit": "",
        "timestamp": "2026-07-19T00:00:00Z",
        "verification_id": "V-1",
        "test_id": "",
        "phase": "green",
    })()
    spec_evidence.record(args)

    data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    evidence = data["verifications"][0]["evidence"]
    assert data["verifications"][0]["status"] == "passed"
    assert evidence["subject_commit"] == "abc123def"
    assert evidence["command"] == "python3 -m pytest example.py"


def test_feature_readiness_workflows_returns_cross_surface_rows():
    readiness = load_script("feature_readiness")

    rows = readiness.workflows_readiness()

    surfaces = {row.surface for row in rows}
    assert {"backend API", "CLI", "npm SDK", "pip SDK", "web UI", "web E2E", "Apple parity", "spec evidence"} <= surfaces
