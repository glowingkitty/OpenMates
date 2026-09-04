#!/usr/bin/env python3
"""Contracts for isolated exact-patch verification and CLI identity inspection."""

# contract-test-file: tooling

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_prepared", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_lock(root: Path, content: str = "lock-v1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pnpm-lock.yaml").write_text(content)


def test_dependency_reuse_requires_exact_lockfile_and_only_creates_symlinks(tmp_path: Path) -> None:
    sessions = load_sessions_module()
    prepared = tmp_path / "prepared"
    checkout = tmp_path / "checkout"
    write_lock(prepared)
    write_lock(checkout)
    (prepared / "node_modules").mkdir()
    (prepared / "frontend/packages/openmates-cli/node_modules").mkdir(parents=True)

    identity = sessions._link_prepared_dependencies(
        checkout,
        prepared,
        ["node_modules", "frontend/packages/openmates-cli/node_modules"],
    )

    assert identity == sessions._file_sha256(prepared / "pnpm-lock.yaml")
    assert (checkout / "node_modules").is_symlink()
    assert (checkout / "frontend/packages/openmates-cli/node_modules").is_symlink()
    assert (checkout / "node_modules").resolve() == (prepared / "node_modules").resolve()


def test_dependency_reuse_rejects_stale_lockfile_before_linking(tmp_path: Path) -> None:
    sessions = load_sessions_module()
    prepared = tmp_path / "prepared"
    checkout = tmp_path / "checkout"
    write_lock(prepared, "old")
    write_lock(checkout, "new")
    (prepared / "node_modules").mkdir()

    with pytest.raises(RuntimeError, match="lockfile identity mismatch"):
        sessions._link_prepared_dependencies(checkout, prepared, ["node_modules"])

    assert not (checkout / "node_modules").exists()


def test_installed_cli_identity_is_read_only_and_detects_candidate_bytes(tmp_path: Path) -> None:
    sessions = load_sessions_module()
    installed = tmp_path / "global" / "openmates"
    candidate = tmp_path / "candidate" / "frontend/packages/openmates-cli"
    (installed / "dist").mkdir(parents=True)
    (candidate / "dist").mkdir(parents=True)
    executable = installed / "dist/cli.js"
    candidate_cli = candidate / "dist/cli.js"
    executable.write_text("#!/usr/bin/env node\nconsole.log('same')\n")
    candidate_cli.write_bytes(executable.read_bytes())
    (installed / "package.json").write_text(json.dumps({"version": "1.2.3"}))
    (candidate / "package.json").write_text(json.dumps({"version": "1.2.3"}))
    before = {path: path.stat().st_mtime_ns for path in (executable, candidate_cli)}

    result = sessions._installed_cli_identity(tmp_path / "candidate", str(executable))

    assert result["contains_candidate_source"] is True
    assert result["installed_version"] == result["candidate_version"] == "1.2.3"
    assert result["inspection_mutated_install"] is False
    assert before == {path: path.stat().st_mtime_ns for path in (executable, candidate_cli)}


def test_profiles_are_fixed_and_never_install_dependencies() -> None:
    sessions = load_sessions_module()

    assert {"cli-typecheck", "cli-storage-unit"} <= set(sessions.PREPARED_VERIFICATION_PROFILES)
    for profile in sessions.PREPARED_VERIFICATION_PROFILES.values():
        command = " ".join(profile["command"])
        assert " install" not in command
        assert profile["dependency_paths"]


def test_verifier_always_removes_its_isolated_checkout(monkeypatch, tmp_path: Path, capsys) -> None:
    sessions = load_sessions_module()
    source = tmp_path / "source"
    checkout = tmp_path / "integration"
    write_lock(source)
    write_lock(checkout)
    session = {
        "modified_files": ["frontend/packages/openmates-cli/src/cli.ts"],
        "worktree": {"path": str(source), "base_commit": "base"},
    }
    removed: list[dict] = []
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"s1": session}})
    monkeypatch.setattr(
        sessions,
        "_resolve_deploy_selection",
        lambda *_args, **_kwargs: (["frontend/packages/openmates-cli/src/cli.ts"], "only"),
    )
    monkeypatch.setattr(
        sessions,
        "_build_deploy_manifest",
        lambda *_args, **_kwargs: {"patch_id": "patch", "manifest_id": "manifest"},
    )
    monkeypatch.setattr(sessions, "_fetch_origin_dev_commit", lambda: "origin")
    monkeypatch.setattr(
        sessions,
        "_prepare_integration_worktree",
        lambda *_args, **_kwargs: {"path": str(checkout)},
    )
    monkeypatch.setattr(sessions, "_link_prepared_dependencies", lambda *_args: "lock")
    monkeypatch.setattr(sessions, "_runtime_epoch_identity", lambda: "epoch")
    monkeypatch.setattr(sessions, "_remove_integration_worktree", lambda item: removed.append(item))

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(sessions.subprocess, "run", lambda *_args, **_kwargs: Completed())
    args = argparse.Namespace(
        session="s1",
        profile="cli-typecheck",
        only=["frontend/packages/openmates-cli/src/cli.ts"],
        use_staged=False,
        expected_manifest_id="manifest",
        executable="",
    )

    sessions.cmd_verify_prepared(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["patch_id"] == "patch"
    assert payload["runtime_epoch"] == "epoch"
    assert removed == [{"path": str(checkout)}]
