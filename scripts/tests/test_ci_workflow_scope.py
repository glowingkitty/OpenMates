"""Keep package workflow path filters aligned with scripts/ci_impact.py.

Purpose: prevent drift between declarative GitHub triggers and classifier rules.
Scope: parses local workflow YAML only; no remote CI operations are invoked.
Privacy: assertions inspect only public repository metadata.
Run: python3 -m pytest scripts/tests/test_ci_workflow_scope.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_impact():
    spec = importlib.util.spec_from_file_location("ci_impact_scope", ROOT / "scripts" / "ci_impact.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_impact_scope"] = module
    spec.loader.exec_module(module)
    return module


def workflow_triggers(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("on", data.get(True))


def test_package_workflows_match_canonical_impact_patterns() -> None:
    impact = load_impact()
    for workflow, target in (("publish-cli.yml", "cli"), ("publish-python-sdk.yml", "python")):
        triggers = workflow_triggers(ROOT / ".github" / "workflows" / workflow)
        expected = list(impact.workflow_path_patterns(target))
        assert triggers["push"]["paths"] == expected
        assert triggers["pull_request"]["paths"] == expected
        assert triggers["workflow_dispatch"] == {}


def test_package_workflows_exclude_apple_only_paths() -> None:
    impact = load_impact()
    apple_path = "apple/OpenMates/Sources/App/OpenMatesApp.swift"

    assert impact.classify_paths([apple_path]).cli_package is False
    assert impact.classify_paths([apple_path]).python_package is False
