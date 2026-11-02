#!/usr/bin/env python3
"""Regression tests for the Docker Compose port-publish guard (tooling test)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = PROJECT_ROOT / "scripts" / "code_quality_guard.py"
REVIEWED = 'services:\n  web:\n    ports:\n      - "5173:5173"\n'


def load_guard_module():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "openmates_code_quality_guard_compose", GUARD_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_git(staged: dict[str, str]):
    def fake(args, check=True):
        if args[:2] == ["ls-tree", "-r"]:
            out = "backend/core/docker-compose.selfhost.yml\nREADME.md\n"
        elif args == ["show", "HEAD:backend/core/docker-compose.selfhost.yml"]:
            out = REVIEWED
        elif args[0] == "show" and args[1].startswith(":"):
            out = staged.get(args[1][1:], "")
        else:
            out = ""
        return subprocess.CompletedProcess(["git", *args], 0, stdout=out, stderr="")

    return fake


# contract-test: tooling
def test_exact_copy_of_tracked_compose_is_exempt(monkeypatch):
    guard = load_guard_module()
    path = "frontend/packages/openmates-tui-native/assets/selfhost/core/docker-compose.selfhost.yml"
    monkeypatch.setattr(guard, "_git", _fake_git({path: REVIEWED}))
    assert guard._reviewed_compose_copies([path, "README.md"]) == {path}


# contract-test: tooling
def test_modified_copy_is_still_checked(monkeypatch):
    guard = load_guard_module()
    path = "deploy/docker-compose.new.yml"
    monkeypatch.setattr(
        guard, "_git", _fake_git({path: REVIEWED + '      - "8080:8080"\n'})
    )
    assert guard._reviewed_compose_copies([path]) == set()
    assert guard._unsafe_compose_port_publish('      - "8080:8080"') is not None
