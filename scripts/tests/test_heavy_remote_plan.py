#!/usr/bin/env python3
# contract-test-file: tooling
"""Contracts for heavy_slot's E2B remote runs (planning, sync, local fallback).

Scope: local planning only; no E2B sandbox, key or network is used.
Run: python3 -m pytest scripts/tests/test_heavy_remote_plan.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import heavy_remote_plan as plan  # noqa: E402 - scripts/ is added to sys.path above
import heavy_slot  # noqa: E402 - scripts/ is added to sys.path above

ROOT = Path("/w/repo")


@pytest.mark.parametrize("argv", [
    ["cargo", "test", "-p", "openmates-sdk"],
    ["cargo", "check", "-p", "openmates"],
    ["cargo", "clippy", "--all-targets"],
    ["npx", "vitest", "run", "src/a.test.ts"],
    ["pnpm", "--dir", "/w/repo/frontend/packages/ui", "exec", "vitest", "run", "a.test.ts"],
    ["cargo", "build", "-p", "openmates", "--bin", "openmates"],
    ["npm", "run", "build:translations"],
    ["npm", "--prefix", "/w/repo/frontend/packages/ui", "run", "build:translations"],
    ["node", "scripts/build-translations.js"],
    ["pnpm", "exec", "svelte-check", "--threshold", "error"],
    ["bash", "-c", "cargo build && cargo test"],
    # 2026-11-13: quoted `|` in grep patterns and `;` sent these to the local queue.
    ["bash", "-c", "cargo test --lib -- cli::send 2>&1 | grep -E '^test result|FAILED|panicked'"],
    ["bash", "-c", "cargo check --workspace 2>&1 | grep -E '^(error|warning)' | head -20; "
                   "cargo test -p openmates-sdk --lib memory_ 2>&1 | tail -3"],
    ["bash", "-c", "cd frontend/apps/web_app && export NODE_OPTIONS=--max-old-space-size=6144 && "
                   "pnpm exec svelte-kit sync && pnpm exec svelte-check 2>/dev/null; echo done"],
])
def test_result_only_commands_run_remotely(argv: list[str]) -> None:
    planned = plan.plan_command(argv, ROOT, ROOT)
    assert planned is not None
    assert "/w/repo" not in planned.shell
    assert planned.cwd == plan.REMOTE_ROOT


@pytest.mark.parametrize("argv", [
    ["cargo", "build", "--release", "--target", "aarch64-unknown-linux-musl"],
    ["cargo", "test", "--target", "wasm32-unknown-unknown"],
    ["cargo", "+nightly", "test"],
    ["npx", "vitest", "-u"],
    ["npx", "vitest", "--update"],
    ["docker", "run", "image"],
    ["bash", "-c", "cargo test > out.txt"],
    ["bash", "-c", "cargo test; rm -rf x"],
    ["bash", "-c", "cd /tmp && cargo test"],
    ["bash", "-c", "cargo test & sleep 1"],
    ["bash", "-c", "cargo test $(echo -p x)"],
    ["bash", "-c", "cargo test && npx vitest run"],  # two kinds in one run
    ["npx", "playwright", "test", "--config", "/etc/hosts"],  # config outside worktree and /tmp
])
def test_other_commands_stay_local(argv: list[str]) -> None:
    assert plan.plan_command(argv, ROOT, ROOT) is None


def test_cwd_outside_the_worktree_stays_local() -> None:
    assert plan.plan_command(["cargo", "test"], Path("/tmp"), ROOT) is None


def test_bash_payload_keeps_separators_and_maps_paths() -> None:
    planned = plan.plan_command(
        ["bash", "-c", "cd /w/repo/frontend/packages/ui && npx vitest run src/x.test.ts 2>&1 | tail -6"],
        ROOT / "sub", ROOT)
    assert planned is not None and planned.kind == "vitest"
    assert planned.shell == ("cd /home/user/repo/frontend/packages/ui && npx vitest run src/x.test.ts "
                             "2>&1 | tail -6")
    assert planned.cwd == "/home/user/repo/sub"


def test_manifest_path_option_is_mapped() -> None:
    planned = plan.plan_command(["cargo", "test", "--manifest-path=/w/repo/a/Cargo.toml"], ROOT, ROOT)
    assert planned is not None
    assert "--manifest-path=/home/user/repo/a/Cargo.toml" in planned.shell


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def test_sync_plan_lists_changes_untracked_and_deletions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.org")
    _git(repo, "config", "user.name", "test")
    for name in ("keep.rs", "edit.rs", "gone.rs"):
        (repo / name).write_text(name)
    (repo / ".gitignore").write_text("target/\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "edit.rs").write_text("changed")
    (repo / "gone.rs").unlink()
    (repo / "new.rs").write_text("new")
    (repo / "target").mkdir()
    (repo / "target" / "big.bin").write_text("ignored")
    (repo / "frontend").mkdir()
    (repo / "frontend" / "pnpm-lock.yaml").write_text("lock")

    sync = plan.sync_plan(repo, base)

    assert sync.upload == ["edit.rs", "frontend/pnpm-lock.yaml", "new.rs"]
    assert sync.delete == ["gone.rs"]
    assert sync.dependencies_changed
    assert plan.has_commit(repo, base)
    assert not plan.has_commit(repo, "0" * 40)


def test_heavy_slot_runs_locally_when_remote_is_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(heavy_slot.host_load_guard, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(heavy_slot, "remote_venv_python", lambda: tmp_path / "python")
    (tmp_path / "python").write_text("")
    assert heavy_slot.remote_disabled_reason(local=True) == "--local"
    monkeypatch.setenv("OPENMATES_HEAVY_REMOTE", "0")
    assert heavy_slot.remote_disabled_reason(local=False) == "OPENMATES_HEAVY_REMOTE=0"
    monkeypatch.delenv("OPENMATES_HEAVY_REMOTE")
    assert heavy_slot.remote_disabled_reason(local=False) is None
    heavy_slot.remote_disabled_file().write_text("")
    assert "exists" in heavy_slot.remote_disabled_reason(local=False)


def test_heavy_slot_treats_remote_infra_failure_as_local_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(heavy_slot.host_load_guard, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(heavy_slot, "remote_venv_python", lambda: tmp_path / "python")
    (tmp_path / "python").write_text("")
    monkeypatch.setattr(heavy_slot, "worktree_root", lambda cwd: cwd)
    calls = []

    def fake_call(argv):
        calls.append(argv)
        return fake_call.code

    monkeypatch.setattr(heavy_slot.subprocess, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    fake_call.code = heavy_slot.REMOTE_EXIT_UNAVAILABLE
    assert heavy_slot.try_remote(["cargo", "test"], 60, local=False) is None
    fake_call.code = 101  # a failing test is the command's result, not a fallback
    assert heavy_slot.try_remote(["cargo", "test"], 60, local=False) == 101
    assert heavy_slot.try_remote(["cargo", "build", "--target", "x86_64-unknown-linux-musl"], 60,
                                 local=False) is None
    assert len(calls) == 2


def test_remote_exit_code_matches_runner() -> None:
    text = (Path(heavy_slot.SCRIPTS_DIR) / "heavy_remote.py").read_text()
    assert f"EXIT_REMOTE_UNAVAILABLE = {heavy_slot.REMOTE_EXIT_UNAVAILABLE}" in text


def test_cargo_build_copies_outputs_back() -> None:
    planned = plan.plan_command(["bash", "-c", "cargo build -p openmates 2>&1 | tail -3"], ROOT, ROOT)
    assert planned is not None and planned.cargo_build
    assert not plan.plan_command(["cargo", "test"], ROOT, ROOT).cargo_build


def test_canonical_checkout_paths_map_into_the_sandbox() -> None:
    canonical = Path("/w")
    root = Path("/w/.wt/agent-1")
    planned = plan.plan_command(["npx", "vitest", "run", "/w/frontend/a.test.ts"], root, root, canonical)
    assert planned is not None and "/home/user/repo/frontend/a.test.ts" in planned.shell
    planned = plan.plan_command(["npx", "vitest", "run", "/w/.wt/agent-1/b.test.ts"], root, root, canonical)
    assert "/home/user/repo/b.test.ts" in planned.shell


def test_playwright_proof_folder_under_tmp_is_mirrored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plan, "EXTERNAL_ROOTS", (str(tmp_path) + "/",))
    proof = tmp_path / "proof" / "run-1"
    proof.mkdir(parents=True)
    (proof / "playwright.proof.config.cjs").write_text("module.exports = {}")
    cli = ROOT / "frontend/apps/web_app/node_modules/@playwright/test/cli.js"
    planned = plan.plan_command(["node", str(cli), "test", "--config", str(proof / "playwright.proof.config.cjs"),
                                 "tests/x.spec.ts"], proof, ROOT)
    assert planned is not None and planned.kind == "playwright"
    assert planned.external_dirs == (str(proof),)
    assert planned.cwd == str(proof)
    assert "/home/user/repo/frontend/apps/web_app/node_modules/@playwright/test/cli.js" in planned.shell


def test_oversized_proof_folder_stays_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(plan, "EXTERNAL_ROOTS", (str(tmp_path) + "/",))
    monkeypatch.setattr(plan, "MAX_EXTERNAL_DIR_BYTES", 10)
    proof = tmp_path / "proof"
    proof.mkdir()
    (proof / "c.cjs").write_text("x" * 100)
    assert plan.plan_command(["npx", "playwright", "test", "--config", str(proof / "c.cjs")], ROOT, ROOT) is None
