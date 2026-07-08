#!/usr/bin/env python3
"""Regression tests for Vercel ignored-build dependency preflight."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vercel_ignore_build.py"


def load_vercel_ignore_module():
    spec = importlib.util.spec_from_file_location("openmates_vercel_ignore_build", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dependabot_npm_branch_with_node22_requirement_is_ignored_on_node20():
    guard = load_vercel_ignore_module()

    lockfile_text = """
  '@vscode/test-electron@3.0.0':
    resolution: {integrity: sha512-example}
    engines: {node: '>=22'}
"""

    ignore, incompatible = guard.should_ignore_build(
        "dependabot/npm_and_yarn/dev/npm-major-16b2d0ad78",
        lockfile_text,
        current_major=20,
    )

    assert ignore is True
    assert incompatible == [">=22"]


def test_same_dependabot_update_continues_after_vercel_node_upgrade():
    guard = load_vercel_ignore_module()

    lockfile_text = """
  '@vscode/test-electron@3.0.0':
    engines: {node: '>=22'}
"""

    ignore, incompatible = guard.should_ignore_build(
        "dependabot/npm_and_yarn/dev/npm-major-16b2d0ad78",
        lockfile_text,
        current_major=24,
    )

    assert ignore is False
    assert incompatible == []


def test_dev_branch_is_never_ignored_by_dependency_engine_guard():
    guard = load_vercel_ignore_module()

    lockfile_text = """
  '@vscode/test-electron@3.0.0':
    engines: {node: '>=22'}
"""

    ignore, incompatible = guard.should_ignore_build("dev", lockfile_text, current_major=20)

    assert ignore is False
    assert incompatible == []


def test_or_node_range_accepts_compatible_major_alternative():
    guard = load_vercel_ignore_module()

    assert guard.node_range_allows_major("^18.18.0 || ^20.9.0 || >=21.1.0", 20) is True
    assert guard.node_range_allows_major(">=18 <25", 20) is True
    assert guard.node_range_allows_major(">=v12.22.7", 20) is True
    assert guard.node_range_allows_major("24.x", 20) is False


def test_extracts_quoted_unquoted_spaced_and_block_node_engine_ranges():
    guard = load_vercel_ignore_module()

    lockfile_text = """
  quoted@1.0.0:
    engines: {node: '>=22'}
  unquoted@1.0.0:
    engines: {node: ^18.18.0 || ^20.9.0 || >=21.1.0}
  spaced@1.0.0:
    engines: { node: ">=18 <25" }
  block@1.0.0:
    engines:
      node: >=24
"""

    assert guard.extract_node_engine_ranges(lockfile_text) == [
        ">=22",
        "^18.18.0 || ^20.9.0 || >=21.1.0",
        ">=18 <25",
        ">=24",
    ]


def test_cli_returns_ignore_exit_code_for_incompatible_dependabot_preview(tmp_path, monkeypatch):
    guard = load_vercel_ignore_module()
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text("pkg@1.0.0:\n  engines: {node: '>=22'}\n", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vercel_ignore_build.py",
            "--branch",
            "dependabot/npm_and_yarn/dev/npm-major-16b2d0ad78",
            "--node-major",
            "20",
            "--lockfile",
            str(lockfile),
        ],
    )

    assert guard.main() == guard.BUILD_IGNORE


def test_cli_returns_continue_exit_code_for_dev_build(tmp_path, monkeypatch):
    guard = load_vercel_ignore_module()
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text("pkg@1.0.0:\n  engines: {node: '>=22'}\n", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vercel_ignore_build.py",
            "--branch",
            "dev",
            "--node-major",
            "20",
            "--lockfile",
            str(lockfile),
        ],
    )

    assert guard.main() == guard.BUILD_CONTINUE


def test_web_app_vercel_config_runs_ignore_command_from_repo_root():
    vercel_config = json.loads((PROJECT_ROOT / "frontend" / "apps" / "web_app" / "vercel.json").read_text())

    assert vercel_config["ignoreCommand"] == "cd ../../.. && python3 scripts/vercel_ignore_build.py"
