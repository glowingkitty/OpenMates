"""Tests for deterministic CI changed-path classification.

Purpose: verify package and web decisions use one canonical path contract.
Scope: pure local classification; no GitHub Actions, builds, or network calls.
Privacy: fixtures contain repository paths only.
Run: python3 -m pytest scripts/tests/test_ci_impact.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_impact():
    spec = importlib.util.spec_from_file_location("ci_impact", ROOT / "scripts" / "ci_impact.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_impact"] = module
    spec.loader.exec_module(module)
    return module


def test_docs_only_change_skips_packages_but_rebuilds_web_docs() -> None:
    impact = load_impact().classify_paths(["docs/contributing/guides/testing.md"])

    assert impact.cli_package is False
    assert impact.python_package is False
    assert impact.web is True


def test_package_and_shared_contract_paths_classify_deterministically() -> None:
    classifier = load_impact().classify_paths

    assert classifier(["frontend/packages/openmates-cli/src/cli.ts"]).cli_package is True
    assert classifier(["packages/openmates-python/openmates/sdk.py"]).python_package is True
    shared = classifier(["backend/apps/health/app.yml"])
    assert shared.cli_package is True
    assert shared.python_package is True
    assert shared.web is True


def test_apple_only_path_has_no_package_or_web_impact() -> None:
    impact = load_impact().classify_paths(["apple/OpenMates/Sources/App/OpenMatesApp.swift"])

    assert impact.cli_package is False
    assert impact.python_package is False
    assert impact.web is False
