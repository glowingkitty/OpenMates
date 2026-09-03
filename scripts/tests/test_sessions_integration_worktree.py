#!/usr/bin/env python3
# contract-test-file: tooling
"""Integration-worktree tests for the sessions.py deploy path.

The fixtures use isolated Git repositories and never touch the OpenMates index.
They prove selected source changes can be validated in a disposable checkout
without changing the control checkout or source worktree.
"""

from __future__ import annotations

import importlib.util
import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_integration_worktree", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def create_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    remote = tmp_path / "remote.git"
    root = tmp_path / "root"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(root)], check=True, capture_output=True)
    git(root, "config", "user.email", "tests@openmates.invalid")
    git(root, "config", "user.name", "OpenMates Tests")
    git(root, "checkout", "-b", "dev")
    (root / ".gitignore").write_text(".openmates-agent-worktrees/\n", encoding="utf-8")
    (root / "changed.txt").write_text("before\n", encoding="utf-8")
    (root / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    (root / "tracked.bin").write_bytes(b"\x00before\xff")
    executable = root / "tool.sh"
    executable.write_text("#!/bin/sh\necho before\n", encoding="utf-8")
    executable.chmod(0o644)
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    git(root, "push", "-u", "origin", "dev")
    base = git(root, "rev-parse", "HEAD")

    source = tmp_path / "source"
    git(root, "worktree", "add", "--detach", str(source), base)
    (source / "changed.txt").write_text("after\n", encoding="utf-8")
    (source / "deleted.txt").unlink()
    executable = source / "tool.sh"
    executable.write_text("#!/bin/sh\necho after\n", encoding="utf-8")
    executable.chmod(0o755)
    (source / "tracked.bin").write_bytes(b"\x00after\xff")
    (source / "new.bin").write_bytes(b"\x00\x01new\xff")
    return root, source, base


def test_staged_files_include_both_sides_of_rename(tmp_path):
    sessions = load_sessions_module()
    root, _source, _base = create_fixture(tmp_path)
    (root / "changed.txt").rename(root / "renamed.txt")
    git(root, "add", "-A")

    staged = sessions._get_staged_files(checkout_root=root)

    assert "changed.txt" in staged
    assert "renamed.txt" in staged


def test_selected_patch_is_reproduced_without_mutating_root_or_source(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, source, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)
    metadata = {"path": str(source), "base_commit": base}
    files = ["changed.txt", "deleted.txt", "new.bin", "tool.sh", "tracked.bin"]
    root_before = git(root, "status", "--porcelain", "-uall")
    source_before = git(source, "status", "--porcelain", "-uall")

    integration = sessions._prepare_integration_worktree(
        "abcd",
        metadata,
        files,
        sessions._worktree_patch_id(metadata, files),
        base,
    )
    checkout = Path(integration["path"])

    assert (checkout / "changed.txt").read_text(encoding="utf-8") == "after\n"
    assert not (checkout / "deleted.txt").exists()
    assert (checkout / "new.bin").read_bytes() == b"\x00\x01new\xff"
    assert (checkout / "tracked.bin").read_bytes() == b"\x00after\xff"
    assert os.stat(checkout / "tool.sh").st_mode & 0o111
    assert set(git(checkout, "diff", "--cached", "--name-only").splitlines()) == set(files)
    assert git(root, "status", "--porcelain", "-uall") == root_before == ""
    assert git(source, "status", "--porcelain", "-uall") == source_before
    assert git(root, "rev-parse", "HEAD") == base

    sessions._remove_integration_worktree(integration)
    assert not checkout.exists()


def test_checkpoint_source_ignores_newer_live_edits(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, source, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)
    metadata = {"path": str(source), "base_commit": base}
    files = ["changed.txt", "deleted.txt", "new.bin", "tool.sh", "tracked.bin"]
    patch_id = sessions._worktree_patch_id(metadata, files)

    checkpoint = sessions._prepare_integration_worktree("abcd", metadata, files, patch_id, base)
    checkpoint_path = Path(checkpoint["path"])
    git(checkpoint_path, "commit", "-m", "checkpoint")
    checkpoint_commit = git(checkpoint_path, "rev-parse", "HEAD")
    sessions._remove_integration_worktree(checkpoint)

    (source / "changed.txt").write_text("newer live edit\n", encoding="utf-8")
    prepared = sessions._prepare_integration_worktree(
        "abcd",
        metadata,
        files,
        patch_id,
        base,
        checkpoint_commit=checkpoint_commit,
    )

    checkout = Path(prepared["path"])
    assert (checkout / "changed.txt").read_text(encoding="utf-8") == "after\n"
    assert (checkout / "new.bin").read_bytes() == b"\x00\x01new\xff"
    sessions._remove_integration_worktree(prepared)


def test_amended_patch_uses_last_deployed_commit_as_integration_base(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, source, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)

    (root / "changed.txt").write_text("after\n", encoding="utf-8")
    (root / "new.bin").write_bytes((source / "new.bin").read_bytes())
    git(root, "add", "changed.txt", "new.bin")
    git(root, "commit", "-m", "first deploy")
    deployed = git(root, "rev-parse", "HEAD")
    (source / "changed.txt").write_text("amended\n", encoding="utf-8")
    (source / "new.bin").write_bytes(b"amended binary")
    metadata = {"path": str(source), "base_commit": base, "merged_commit": deployed}
    files = ["changed.txt", "new.bin"]

    integration = sessions._prepare_integration_worktree(
        "abcd",
        metadata,
        files,
        sessions._worktree_patch_id(metadata, files),
        deployed,
    )
    checkout = Path(integration["path"])

    assert integration["source_base"] == deployed
    assert (checkout / "changed.txt").read_text(encoding="utf-8") == "amended\n"
    assert (checkout / "new.bin").read_bytes() == b"amended binary"
    assert set(git(checkout, "diff", "--cached", "--name-only").splitlines()) == set(files)
    sessions._remove_integration_worktree(integration)


def test_successful_integration_fast_forwards_dirty_control_plane_without_losing_unrelated_files(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, _source, base = create_fixture(tmp_path)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    next_checkout = tmp_path / "next"
    git(root, "worktree", "add", "--detach", str(next_checkout), base)
    (next_checkout / "changed.txt").write_text("deployed\n", encoding="utf-8")
    git(next_checkout, "add", "changed.txt")
    git(next_checkout, "commit", "-m", "next deploy")
    deployed = git(next_checkout, "rev-parse", "HEAD")
    unrelated = root / "unrelated.local"
    unrelated.write_text("keep me\n", encoding="utf-8")

    sessions._fast_forward_control_plane(deployed)

    assert git(root, "rev-parse", "HEAD") == deployed
    assert (root / "changed.txt").read_text(encoding="utf-8") == "deployed\n"
    assert unrelated.read_text(encoding="utf-8") == "keep me\n"


def test_control_plane_sync_preflight_rejects_lag(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, _source, base = create_fixture(tmp_path)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    with pytest.raises(RuntimeError, match="not synchronized"):
        sessions._enforce_control_plane_sync_ready("different-origin-head")


def test_control_plane_sync_preflight_allows_untracked_but_rejects_tracked_changes(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, _source, base = create_fixture(tmp_path)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    (root / "untracked.local").write_text("preserved\n", encoding="utf-8")

    sessions._enforce_control_plane_sync_ready(base)

    (root / "changed.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="tracked changes"):
        sessions._enforce_control_plane_sync_ready(base)


def test_gate_runner_uses_integration_checkout(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    checkout = tmp_path / "integration"
    checkout.mkdir()
    calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(
        sessions,
        "_run_lint",
        lambda _files, *, checkout_root: calls.append(("lint", checkout_root)) or (0, "", ""),
    )
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_sdk_cleartext_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)

    sessions._run_deploy_gates(
        ["scripts/sessions.py"],
        checkout_root=checkout,
        no_verify=False,
        skip_tests_reason="unit fixture",
        require_parity=False,
    )

    assert calls == [("lint", checkout)]


def test_gate_runner_generates_embed_registry_before_lint(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    checkout = tmp_path / "integration"
    checkout.mkdir()
    calls: list[str] = []

    monkeypatch.setattr(
        sessions,
        "_run_specification_gate",
        lambda *_args, **_kwargs: calls.append("specifications"),
    )
    monkeypatch.setattr(
        sessions,
        "_enforce_embed_registry_validation",
        lambda *_args, **_kwargs: calls.append("embed-registry"),
    )
    monkeypatch.setattr(
        sessions,
        "_run_lint",
        lambda _files, *, checkout_root: calls.append("lint") or (0, "", ""),
    )
    monkeypatch.setattr(sessions, "_run_translation_build", lambda **_kwargs: calls.append("translations") or (0, "", ""))
    monkeypatch.setattr(sessions, "_run_translation_validation", lambda **_kwargs: calls.append("locales") or (0, "", ""))
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: calls.append("tests"))
    monkeypatch.setattr(sessions, "_enforce_sdk_cleartext_gate", lambda *_args, **_kwargs: calls.append("sdk"))
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: calls.append("pytest"))

    sessions._run_deploy_gates(
        ["frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts"],
        checkout_root=checkout,
        no_verify=False,
        skip_tests_reason="unit fixture",
        require_parity=False,
        session_id="abcd",
    )

    assert calls[:3] == ["specifications", "embed-registry", "lint"]
    assert calls == [
        "specifications",
        "embed-registry",
        "lint",
        "translations",
        "locales",
        "tests",
        "sdk",
        "pytest",
    ]


def test_failed_gate_cleans_integration_and_leaves_all_authoritative_state_unchanged(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, source, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)
    metadata = {"path": str(source), "base_commit": base}
    files = ["changed.txt"]
    patch_id = sessions._worktree_patch_id(metadata, files)
    root_status = git(root, "status", "--porcelain", "-uall")
    source_status = git(source, "status", "--porcelain", "-uall")
    remote_head = git(root, "rev-parse", "origin/dev")

    monkeypatch.setattr(sessions, "_fetch_origin_dev_commit", lambda: base)
    monkeypatch.setattr(sessions, "_bootstrap_integration_for_files", lambda *_args: None)
    monkeypatch.setattr(
        sessions,
        "_run_deploy_gates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("expected gate failure")),
    )
    args = argparse.Namespace(
        session="abcd",
        title="test: failed gate",
        message=None,
        no_verify=False,
        skip_tests_reason=None,
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
        end_session=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        sessions._deploy_native_worktree(args, {}, metadata, files, patch_id)

    assert exc_info.value.code == 1
    assert not list(integrations.glob("integration-*"))
    assert git(root, "status", "--porcelain", "-uall") == root_status == ""
    assert git(source, "status", "--porcelain", "-uall") == source_status
    assert git(root, "rev-parse", "origin/dev") == remote_head
