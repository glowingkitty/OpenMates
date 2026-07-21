#!/usr/bin/env python3
"""Tests for deterministic dev version advancement after main PR merges.

The GitHub workflow must keep dev on the next alpha train after a release PR is
merged to main, using the repository's canonical bump script rather than custom
version replacement logic.
"""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "advance-dev-version.yml"


def test_advance_dev_version_workflow_runs_after_merged_main_pr() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    pull_request = workflow[True]["pull_request"]
    assert pull_request["branches"] == ["main"]
    assert pull_request["types"] == ["closed"]
    assert workflow["permissions"] == {"contents": "write"}
    assert workflow["jobs"]["advance"]["if"] == "github.event.pull_request.merged == true"


def test_advance_dev_version_workflow_uses_canonical_bump_script() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "shared/config/product_version.json" in text
    assert "minor + 1" in text
    assert "scripts/bump_alpha_version_line.py --minor" in text
    assert "git push origin HEAD:dev" in text
    assert "git diff --quiet" in text
