#!/usr/bin/env python3
# contract-test-file: tooling
"""Regression tests for dev-version advancement diagnostics.

Purpose: keep GitHub Actions version failures diagnosable without GitHub MCP.
Architecture: tests exercise pure recommendation logic and command selection.
Safety: no network calls run during these tests.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_advance_dev_version.py"
SPEC = importlib.util.spec_from_file_location("check_advance_dev_version", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_recommends_pr_based_bump_for_failed_direct_push() -> None:
    report = {
        "product_version": {"userFacing": "v0.16", "cli": {"stableBase": "0.16.0"}},
        "latest_run": {"conclusion": "failure"},
        "latest_failure_log": "GH013: Changes must be made through a pull request\nwithout workflows permission",
    }

    recommendations = module.classify_recommendation(report)

    assert any("bump_alpha_version_line.py --minor 17" in item for item in recommendations)
    assert any("PR-based" in item for item in recommendations)
    assert any(".github/workflows/**" in item for item in recommendations)


def test_github_queries_use_gh_cli(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_command_json(command: list[str]):
        commands.append(command)
        return [], ""

    monkeypatch.setattr(module, "command_json", fake_command_json)

    module.latest_merged_dev_pr()
    module.latest_workflow_runs(3)

    assert commands[0][:3] == ["gh", "pr", "list"]
    assert commands[1][:3] == ["gh", "run", "list"]
