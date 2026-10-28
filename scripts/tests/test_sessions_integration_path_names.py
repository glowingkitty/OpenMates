#!/usr/bin/env python3
# contract-test-file: tooling
"""Managed integration names only; no worktree removal or shared-state mutation."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def load_sessions_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "sessions.py"
    spec = importlib.util.spec_from_file_location("openmates_sessions_integration_path_names", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("integration-4805-20261008t2000", True),
        ("integration-abcd-20240229t2359", True),
        ("integration-abcd-123456789abc", True),
        ("integration-session_with-hyphen-abcdef012345", True),
        ("integration-4805-20260229t2000", False),
        ("integration-4805-20261308t2000", False),
        ("integration-4805-20260431t2000", False),
        ("integration-4805-20261008t2400", False),
        ("integration-4805-20261008t2060", False),
        ("integration-4805-00001008t2000", False),
        ("integration-4805-20261008T2000", False),
        ("integration-4805-2026108t2000", False),
        ("integration-4805-20261008t200", False),
        ("integration-4805-20261008t2000-extra", False),
        ("integration--20261008t2000", False),
        ("integration-4805-abcdef01234g", False),
        ("agent-4805-20261008t2000", False),
    ],
)
def test_current_and_valid_legacy_integration_names(monkeypatch, tmp_path, name, expected):
    sessions = load_sessions_module()
    managed = tmp_path / "managed"
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    assert sessions._is_integration_worktree_path(managed / name) is expected


def test_integration_name_requires_direct_managed_child_without_traversal(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "managed"
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    name = "integration-4805-20261008t2000"
    assert not sessions._is_integration_worktree_path(tmp_path / name)
    assert not sessions._is_integration_worktree_path(managed / "nested" / name)
    assert not sessions._is_integration_worktree_path(managed / "nested" / ".." / name)
    assert not sessions._is_integration_worktree_path(managed / ".." / "outside" / name)
    managed.mkdir()
    outside = tmp_path / name
    outside.mkdir()
    (managed / name).symlink_to(outside, target_is_directory=True)
    assert not sessions._is_integration_worktree_path(managed / name)
