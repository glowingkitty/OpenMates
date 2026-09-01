#!/usr/bin/env python3
"""Regression tests for immutable, root-independent session deploy manifests.

These tests cover the selection bugs observed in long-running OpenCode chats:
an explicit staged or path-scoped correction must not grow to include older
session-tracked files, and every managed worktree mode uses isolated deploy.
"""

# contract-test-file: tooling

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_deploy_manifest", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_use_staged_is_authoritative_when_other_tracked_files_are_dirty(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    session = {
        "modified_files": ["selected.py", "older-a.py", "older-b.py"],
        "worktree": {"path": str(tmp_path), "base_commit": "base"},
    }
    monkeypatch.setattr(
        sessions,
        "_session_deploy_files",
        lambda _session, _exclude: ["older-a.py", "older-b.py", "selected.py"],
    )
    monkeypatch.setattr(sessions, "_get_staged_files", lambda **_kwargs: ["selected.py"])

    files, selector = sessions._resolve_deploy_selection(
        session,
        exclude=set(),
        use_staged=True,
    )

    assert selector == "staged"
    assert files == ["selected.py"]


def test_only_is_exact_and_rejects_non_session_work(monkeypatch):
    sessions = load_sessions_module()
    session = {"modified_files": ["selected.py", "older.py"]}
    monkeypatch.setattr(
        sessions,
        "_session_deploy_files",
        lambda _session, _exclude: ["older.py", "selected.py"],
    )

    files, selector = sessions._resolve_deploy_selection(
        session,
        exclude=set(),
        only=["selected.py"],
    )

    assert selector == "only"
    assert files == ["selected.py"]

    try:
        sessions._resolve_deploy_selection(session, exclude=set(), only=["foreign.py"])
    except RuntimeError as exc:
        assert "not tracked dirty work" in str(exc)
    else:
        raise AssertionError("expected non-session --only selection to fail")


def test_manifest_identity_changes_with_selection_or_patch(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    session = {
        "modified_files": ["a.py", "b.py"],
        "worktree": {"path": str(tmp_path), "base_commit": "base"},
    }
    patch_ids = {("a.py",): "patch-a", ("b.py",): "patch-b"}
    monkeypatch.setattr(
        sessions,
        "_worktree_patch_id",
        lambda _metadata, files: patch_ids[tuple(files)],
    )

    first = sessions._build_deploy_manifest("abcd", session, ["a.py"], selector="only")
    repeated = sessions._build_deploy_manifest("abcd", session, ["a.py"], selector="only")
    changed = sessions._build_deploy_manifest("abcd", session, ["b.py"], selector="only")

    assert first == repeated
    assert first["manifest_id"] != changed["manifest_id"]
    assert first["selected_files"] == ["a.py"]


def test_local_control_plane_lag_is_informational_and_does_not_fast_forward(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _root: "local-head")
    fast_forward_calls: list[str] = []
    monkeypatch.setattr(sessions, "_fast_forward_control_plane", fast_forward_calls.append)

    warning = sessions._control_plane_sync_warning("pushed-head")

    assert "informational only" in warning
    assert "deployment_affected=false" in warning
    assert fast_forward_calls == []


def test_missing_deploy_protocol_marker_defaults_to_legacy_v1(monkeypatch):
    sessions = load_sessions_module()

    def fake_run_cmd(command, **_kwargs):
        if command[:2] == ["git", "show"]:
            return 128, "", "path missing"
        if command[:3] == ["git", "cat-file", "-e"]:
            return 0, "", ""
        raise AssertionError(command)

    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)

    assert sessions._required_control_plane_deploy_protocol_version("origin/dev") == 1


def test_higher_deploy_protocol_marker_blocks_stale_runtime(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "CONTROL_PLANE_DEPLOY_PROTOCOL_VERSION", 2)
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, **_kwargs: (0, "3", ""))

    with pytest.raises(RuntimeError, match="requires control-plane deploy protocol v3"):
        sessions._enforce_control_plane_deploy_protocol_compatible("origin/dev")


def test_malformed_deploy_protocol_marker_fails_closed(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, **_kwargs: (0, "two", ""))

    with pytest.raises(RuntimeError, match="Malformed control-plane deploy protocol"):
        sessions._required_control_plane_deploy_protocol_version("origin/dev")


def test_validate_staged_deploy_files_allows_clean_noop_selected_path(monkeypatch):
    sessions = load_sessions_module()
    checked: list[str] = []
    monkeypatch.setattr(sessions, "_get_staged_files", lambda **_kwargs: {"real.py"})

    def path_has_diff(relative_path: str, **_kwargs) -> bool:
        checked.append(relative_path)
        return False

    monkeypatch.setattr(sessions, "_path_has_unstaged_diff", path_has_diff)

    assert sessions._validate_staged_deploy_files({"real.py", "contracts/generated/registry.yml"}, context="test")
    assert checked == ["contracts/generated/registry.yml"]


def test_validate_staged_deploy_files_rejects_dirty_missing_selected_path(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_get_staged_files", lambda **_kwargs: {"real.py"})
    monkeypatch.setattr(sessions, "_path_has_unstaged_diff", lambda _relative_path, **_kwargs: True)

    assert not sessions._validate_staged_deploy_files({"real.py", "dirty.py"}, context="test")


def test_path_has_unstaged_diff_fails_closed_on_git_status_error(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, **_kwargs: (128, "", "fatal status"))

    with pytest.raises(RuntimeError, match="Could not inspect deploy path status"):
        sessions._path_has_unstaged_diff("selected.py")


def test_legacy_grandfathered_managed_worktree_uses_native_integration(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    metadata = {"path": str(tmp_path), "base_commit": "base", "status": "active"}
    session = {
        "binding_mode": "legacy_grandfathered",
        "modified_files": ["selected.py"],
        "worktree": metadata,
    }
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": session}})
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda **_kwargs: ["selected.py"])
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: ["selected.py"])
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch")
    monkeypatch.setattr(sessions, "_pending_worktree_push_commit", lambda *_args: "")
    deployed: list[tuple] = []
    monkeypatch.setattr(
        sessions,
        "_deploy_native_worktree",
        lambda *call_args: deployed.append(call_args),
    )

    sessions.cmd_deploy(
        argparse.Namespace(
            session="abcd",
            title="test: exact deploy",
            message=None,
            exclude=None,
            only=None,
            use_staged=False,
            expected_manifest_id=None,
            expected_patch_id=None,
            expected_checkpoint_commit=None,
        )
    )

    assert len(deployed) == 1
    assert deployed[0][2] == metadata
    assert deployed[0][3] == ["selected.py"]
