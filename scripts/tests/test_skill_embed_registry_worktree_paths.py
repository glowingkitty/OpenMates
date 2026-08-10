"""Tests for skill/embed registry guard worktree path support.

Purpose: ensure OpenCode worktree edits to backend app metadata still trigger
the app-skill embed registry audits when routed through bridged hooks.
Architecture: inspect the shell guard source and the Python audit path resolver
without launching hooks or mutating app metadata.
Security: uses synthetic paths only and does not read credentials or private data.
Run: python3 -m pytest scripts/tests/test_skill_embed_registry_worktree_paths.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_skill_embed_registry.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_skill_embed_registry", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_guard_matches_openmates_worktree_app_metadata_paths() -> None:
    source = (ROOT / ".claude/hooks/skill-embed-registry-guard.sh").read_text(encoding="utf-8")

    assert ".openmates-agent-worktrees" in source
    assert "backend/apps/*/app.yml" in source


def test_audit_accepts_worktree_app_metadata_paths() -> None:
    audit = load_audit_module()
    path = ROOT / ".openmates-agent-worktrees" / "agent-test" / "backend" / "apps" / "demo" / "app.yml"

    assert audit.app_paths([str(path)]) == [path]
