#!/usr/bin/env python3
"""Concurrency contracts for disposable deploy integration worktrees.

These tests exercise exact-base preparation and conservative rebuilding after
origin/dev advances. A content conflict must be explicit and must not alter dev.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_integration_concurrency", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def create_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    remote = tmp_path / "remote.git"
    root = tmp_path / "root"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(root)], check=True, capture_output=True)
    git(root, "config", "user.email", "tests@openmates.invalid")
    git(root, "config", "user.name", "OpenMates Tests")
    git(root, "checkout", "-b", "dev")
    (root / ".gitignore").write_text(".openmates-agent-worktrees/\n", encoding="utf-8")
    (root / "a.txt").write_text("a0\n", encoding="utf-8")
    (root / "b.txt").write_text("b0\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    git(root, "push", "-u", "origin", "dev")
    base = git(root, "rev-parse", "HEAD")
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    git(root, "worktree", "add", "--detach", str(source_a), base)
    git(root, "worktree", "add", "--detach", str(source_b), base)
    (source_a / "a.txt").write_text("a1\n", encoding="utf-8")
    (source_b / "b.txt").write_text("b1\n", encoding="utf-8")
    return root, source_a, source_b, base


def test_parallel_preparations_are_unique_and_rebuild_on_advanced_dev(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, source_a, source_b, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)
    metadata_a = {"path": str(source_a), "base_commit": base}
    metadata_b = {"path": str(source_b), "base_commit": base}

    prepared_a = sessions._prepare_integration_worktree(
        "aaaa", metadata_a, ["a.txt"], sessions._worktree_patch_id(metadata_a, ["a.txt"]), base
    )
    prepared_b = sessions._prepare_integration_worktree(
        "bbbb", metadata_b, ["b.txt"], sessions._worktree_patch_id(metadata_b, ["b.txt"]), base
    )
    assert prepared_a["path"] != prepared_b["path"]

    (root / "a.txt").write_text("a1\n", encoding="utf-8")
    git(root, "add", "a.txt")
    git(root, "commit", "-m", "deploy a")
    git(root, "push", "origin", "dev")
    final_base = git(root, "rev-parse", "origin/dev")

    rebuilt_b = sessions._rebuild_integration_worktree(prepared_b, metadata_b, ["b.txt"], final_base)
    rebuilt_checkout = Path(rebuilt_b["path"])
    assert rebuilt_b["prepared_base"] == final_base
    assert (rebuilt_checkout / "a.txt").read_text(encoding="utf-8") == "a1\n"
    assert (rebuilt_checkout / "b.txt").read_text(encoding="utf-8") == "b1\n"
    assert git(root, "rev-parse", "origin/dev") == final_base

    sessions._remove_integration_worktree(prepared_a)
    sessions._remove_integration_worktree(rebuilt_b)


def test_prepare_integration_worktree_preserves_staged_added_files(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, _source_a, source_b, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)

    new_file = source_b / "scripts" / "audit_new.py"
    new_file.parent.mkdir(parents=True)
    new_file.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
    git(source_b, "add", "scripts/audit_new.py")
    metadata_b = {"path": str(source_b), "base_commit": base}
    files = ["scripts/audit_new.py"]
    prepared = sessions._prepare_integration_worktree(
        "bbbb",
        metadata_b,
        files,
        sessions._worktree_patch_id(metadata_b, files),
        base,
    )
    checkout = Path(prepared["path"])

    assert (checkout / "scripts" / "audit_new.py").read_text(encoding="utf-8") == (
        "#!/usr/bin/env python3\nprint('ok')\n"
    )
    assert git(checkout, "diff", "--name-only", "--cached") == "scripts/audit_new.py"

    sessions._remove_integration_worktree(prepared)


def test_advanced_base_conflict_is_explicit_and_leaves_dev_unchanged(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, _source_a, source_b, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)
    metadata_b = {"path": str(source_b), "base_commit": base}
    (source_b / "a.txt").write_text("source version\n", encoding="utf-8")
    files = ["a.txt"]
    patch_id = sessions._worktree_patch_id(metadata_b, files)
    prepared = sessions._prepare_integration_worktree("bbbb", metadata_b, files, patch_id, base)

    (root / "a.txt").write_text("dev version\n", encoding="utf-8")
    git(root, "add", "a.txt")
    git(root, "commit", "-m", "advance dev")
    git(root, "push", "origin", "dev")
    final_base = git(root, "rev-parse", "origin/dev")

    with pytest.raises(sessions.IntegrationConflict) as exc_info:
        sessions._rebuild_integration_worktree(prepared, metadata_b, files, final_base)

    assert exc_info.value.patch_id == patch_id
    assert exc_info.value.source_base == base
    assert exc_info.value.final_base == final_base
    assert git(root, "rev-parse", "origin/dev") == final_base
    assert git(root, "status", "--porcelain", "-uall") == ""

    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"sessions": {"bbbb": {"worktree": {"status": "active"}}}}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    item = sessions.enqueue_worktree_deploy(
        "bbbb",
        "test: conflict",
        patch_id,
        reason=str(exc_info.value),
        integration=prepared,
        final_base=final_base,
    )
    assert item["integration_id"] == prepared["id"]
    assert item["source_base"] == base
    assert item["final_base"] == final_base
    assert "origin/dev" in item["next_action"]


def test_stale_worktree_rebase_blocks_deletion_amplification(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, source_a, _source_b, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)

    (source_a / "a.txt").write_text("a0\nspeech toggle\n", encoding="utf-8")
    (root / "a.txt").write_text("a0\nmodel selector\nplus button\nsend button\n", encoding="utf-8")
    git(root, "add", "a.txt")
    git(root, "commit", "-m", "add composer controls")
    git(root, "push", "origin", "dev")
    current_dev = git(root, "rev-parse", "origin/dev")

    metadata = {
        "path": str(source_a),
        "base_commit": base,
        # Reproduces partial deploy metadata advancing globally while this file
        # remains based on the worktree's older HEAD.
        "merged_commit": current_dev,
    }
    files = ["a.txt"]
    patch_id = sessions._worktree_patch_id(metadata, files)

    with pytest.raises(sessions.IntegrationConflict, match="Deletion amplification detected") as exc_info:
        sessions._prepare_integration_worktree("aaaa", metadata, files, patch_id, current_dev)

    assert "a.txt (0 intended, 3 integrated)" in str(exc_info.value)
    assert git(root, "rev-parse", "origin/dev") == current_dev
    assert git(root, "status", "--porcelain", "-uall") == ""


def test_finalization_rebuilds_and_reruns_gates_before_detached_push(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    first_checkout = tmp_path / "integration-first"
    second_checkout = tmp_path / "integration-second"
    first_checkout.mkdir()
    second_checkout.mkdir()
    prepared_first = {
        "id": "integration-first",
        "path": str(first_checkout),
        "session_id": "abcd",
        "patch_id": "patch",
        "source_base": "source-base",
        "prepared_base": "dev-one",
    }
    prepared_second = {
        **prepared_first,
        "id": "integration-second",
        "path": str(second_checkout),
        "prepared_base": "dev-two",
    }
    fetched = iter(["dev-one", "dev-two", "dev-two"])
    gate_checkouts: list[Path] = []
    commands: list[tuple[list[str], str | None]] = []
    releases: list[str] = []
    removed: list[str] = []

    monkeypatch.setattr(sessions, "_fetch_origin_dev_commit", lambda: next(fetched))
    monkeypatch.setattr(sessions, "_create_worktree_checkpoint_commit", lambda *_args: "checkpoint")
    monkeypatch.setattr(sessions, "_prepare_integration_worktree", lambda *_args, **_kwargs: prepared_first)
    monkeypatch.setattr(sessions, "_rebuild_integration_worktree", lambda *_args: prepared_second)
    monkeypatch.setattr(sessions, "_bootstrap_integration_for_files", lambda *_args: None)
    monkeypatch.setattr(
        sessions,
        "_run_deploy_gates",
        lambda _files, *, checkout_root, **_kwargs: gate_checkouts.append(checkout_root),
    )
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        sessions,
        "_release_session_lock",
        lambda *_args, **kwargs: releases.append(kwargs.get("commit_sha", "")) or True,
    )
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_validate_staged_deploy_files", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_integration_commit_message", lambda *_args: "test: native integration")
    monkeypatch.setattr(sessions, "_remove_integration_worktree", lambda value: removed.append(value["id"]))
    monkeypatch.setattr(sessions, "_save_last_deploy_sha", lambda _sha: None)
    monkeypatch.setattr(sessions, "_mark_worktree_deployed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_find_related_docs", lambda _files: [])

    def fake_run_cmd(command, cwd=None, timeout=120):
        commands.append((command, cwd))
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, "commit-two", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    args = argparse.Namespace(
        session="abcd",
        title="test: native integration",
        message=None,
        no_verify=False,
        skip_tests_reason="fixture",
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
        end_session=False,
    )

    sessions._deploy_native_worktree(
        args,
        {"modified_files": ["a.txt"]},
        {"path": "/source", "base_commit": "source-base"},
        ["a.txt"],
        "patch",
    )

    assert gate_checkouts == [first_checkout, second_checkout]
    assert (["git", "push", "origin", "HEAD:refs/heads/dev"], str(second_checkout)) in commands
    assert releases == ["", "commit-two"]
    assert removed == ["integration-second"]
