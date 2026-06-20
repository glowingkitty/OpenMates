#!/usr/bin/env python3
"""Regression tests for Caddyfile staged-change guardrails."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = PROJECT_ROOT / "scripts" / "code_quality_guard.py"


def load_guard_module():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("openmates_code_quality_guard", GUARD_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_caddyfile_preflight_runs_runtime_and_semantic_checks(monkeypatch):
    guard = load_guard_module()
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(guard.subprocess, "run", fake_run)

    issues = guard._run_caddyfile_preflight(["deployment/dev_server/Caddyfile", "docs/example.md"])

    assert issues == []
    assert calls == [
        ["bash", "deployment/apply-caddy-config.sh", "--check", "deployment/dev_server/Caddyfile"],
        ["python3", "deployment/verify-caddyfile.py", "deployment/dev_server/Caddyfile"],
    ]


def test_caddyfile_preflight_blocks_and_skips_later_checks_after_runtime_failure(monkeypatch):
    guard = load_guard_module()
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 1, stdout="module not registered", stderr="")

    monkeypatch.setattr(guard.subprocess, "run", fake_run)

    issues = guard._run_caddyfile_preflight(["deployment/dev_server/Caddyfile"])

    assert len(issues) == 1
    assert "module not registered" in issues[0]
    assert calls == [["bash", "deployment/apply-caddy-config.sh", "--check", "deployment/dev_server/Caddyfile"]]


def test_settings_native_dialog_guard_blocks_added_prompt():
    guard = load_guard_module()

    issues = guard._audit_settings_native_dialogs([
        (
            "frontend/packages/ui/src/components/settings/CurrentSettingsPage.svelte",
            42,
            "const value = window.prompt('Bad overlay');",
        )
    ])

    assert len(issues) == 1
    assert "native browser prompt() dialogs are not allowed" in issues[0]


def test_settings_native_dialog_guard_ignores_non_settings_files():
    guard = load_guard_module()

    issues = guard._audit_settings_native_dialogs([
        ("frontend/packages/ui/src/components/Other.svelte", 10, "window.prompt('legacy');")
    ])

    assert issues == []


def test_settings_native_dialog_guard_covers_settings_shell():
    guard = load_guard_module()

    issues = guard._audit_settings_native_dialogs([
        ("frontend/packages/ui/src/components/Settings.svelte", 20, "confirm('Bad overlay');")
    ])

    assert len(issues) == 1
    assert "native browser confirm() dialogs are not allowed" in issues[0]
