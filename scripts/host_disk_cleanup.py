#!/usr/bin/env python3
"""Age-based cleanup of host scratch space that no repository inventory owns.

Covers what the repository-scoped `managed` cleanup cannot see:
  * top-level entries in /tmp owned by this user, untouched for TMP_MAX_AGE_DAYS
    (newest mtime anywhere inside) and not used by any running process;
  * worktree recovery archives older than RECOVERY_MAX_AGE_DAYS.

Also applies the approved retention rule (age by mtime, never while in use):
  * CI artifact dirs under test-results/ci-runs and logs/ci-candidates older than
    CI_ARTIFACT_MAX_AGE_DAYS, unless a queued, running, preparing or otherwise
    non-terminal job in logs/ci-coordinator/queue.sqlite3 references them (the
    queue is opened read-only; an unreadable queue skips these categories);
  * Rust target/ dirs of managed worktrees and ~/.cache/openmates-rust-* caches
    unchanged for RUST_IDLE_HOURS, unless a cargo/rustc process uses them.

Runs as the disk coordinator's `host` cleanup kind. Outside the elected owner it
only queues that maintenance (same handoff as docker-cleanup.sh), so cleanup
never races admission. `--dry-run` (default without --apply) reports only.
Architecture: scripts/disk_coordinator.py, scripts/resource_budget.py.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TMP_MAX_AGE_DAYS = 3
RECOVERY_MAX_AGE_DAYS = 14
CI_ARTIFACT_MAX_AGE_DAYS = 3
RUST_IDLE_HOURS = 24
TERMINAL_JOB_STATES = ("success", "failure", "cancelled")
JOB_REFERENCE_COLUMNS = ("id", "source", "run_id", "prepared_run_id", "preparation_id",
                         "preparation_key", "candidate_tree", "candidate_base")
CARGO_COMMANDS = frozenset({"cargo", "rustc", "rustdoc", "clippy-driver", "cargo-clippy"})
# Sockets, session runtimes and live agent scratch spaces are never touched.
PROTECTED_TMP_PREFIXES = (
    "claude-", "tmux-", "systemd-private-", "snap-private-tmp", ".X", ".ICE-unix",
    ".font-unix", ".XIM-unix", ".Test-unix", "ssh-", "pulse-", "dbus-", "vscode-",
    "openmates-docker-cleanup.lock",
)


def _in_use_paths(uid: int) -> list[str]:
    """Working directories and open files of this user's processes."""
    used: list[str] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            used.append(os.readlink(proc / "cwd"))
            for fd in (proc / "fd").iterdir():
                target = os.readlink(fd)
                if target.startswith("/"):
                    used.append(target)
        except OSError:
            continue
    return used


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _cargo_paths(uid: int) -> list[str]:
    """Directories named by running cargo/rustc processes (cwd, env, arguments)."""
    found: list[str] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            if (proc / "comm").read_text().strip() not in CARGO_COMMANDS:
                continue
            found.append(os.readlink(proc / "cwd"))
            values = (proc / "environ").read_bytes().split(b"\0")
            values += (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        for raw in values:
            text = raw.decode(errors="ignore").split("=", 1)[-1]
            if text.startswith("/"):
                found.append(text)
    return found


def _active_job_references(repository: Path) -> set[str] | None:
    """Identifiers held by non-terminal jobs; None when the queue cannot be read."""
    queue = repository / "logs/ci-coordinator/queue.sqlite3"
    if not queue.is_file():
        return set()
    marks = ",".join("?" * len(TERMINAL_JOB_STATES))
    try:
        with sqlite3.connect(f"file:{queue}?mode=ro", uri=True, timeout=2) as db:
            rows = db.execute(
                f"SELECT {','.join(JOB_REFERENCE_COLUMNS)} FROM jobs WHERE state NOT IN ({marks})",
                TERMINAL_JOB_STATES).fetchall()
    except sqlite3.Error:
        return None
    return {str(value) for row in rows for value in row if value}


def _retention_candidates(repository: Path, cache_root: Path, now: float,
                          references: set[str] | None) -> list[tuple[Path, str, float, Path | None]]:
    """(path, category, cutoff, owner_root) for the CI artifact and Rust rules."""
    found: list[tuple[Path, str, float, Path | None]] = []
    ci_cutoff = now - CI_ARTIFACT_MAX_AGE_DAYS * 86400
    rust_cutoff = now - RUST_IDLE_HOURS * 3600
    if references is not None:
        for category, base in (("ci_run", repository / "test-results/ci-runs"),
                               ("ci_candidate", repository / "logs/ci-candidates")):
            if not base.is_dir():
                continue
            for entry in base.iterdir():
                if entry.is_dir() and not entry.is_symlink() and entry.name not in references:
                    found.append((entry, category, ci_cutoff, None))
    for worktree in sorted((repository / ".openmates-agent-worktrees").glob("agent-*")):
        target = worktree / "target"
        if target.is_dir() and not target.is_symlink():
            found.append((target, "rust_target", rust_cutoff, worktree))
    if cache_root.is_dir():
        for entry in cache_root.glob("openmates-rust-*"):
            if not entry.is_symlink() and (entry.is_dir() or entry.is_file()):
                found.append((entry, "rust_cache", rust_cutoff, None))
    return found


def _tree_bytes(path: Path) -> int:
    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
            total += info.st_blocks * 512
            if stat.S_ISDIR(info.st_mode):
                pending.extend(current.iterdir())
        except OSError:
            continue
    return total


def _scan(path: Path, cutoff: float) -> tuple[bool, int]:
    """Return (stale, bytes). Stops at the first entry newer than cutoff."""
    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
        except OSError:
            continue
        if info.st_mtime > cutoff:
            return False, 0
        total += info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode):
            try:
                pending.extend(current.iterdir())
            except OSError:
                return False, 0  # unreadable content is not provably stale
    return True, total


def _candidates(tmp_root: Path, recovery_root: Path, now: float, uid: int) -> list[tuple[Path, str, float]]:
    found: list[tuple[Path, str, float]] = []
    tmp_cutoff = now - TMP_MAX_AGE_DAYS * 86400
    recovery_cutoff = now - RECOVERY_MAX_AGE_DAYS * 86400
    if tmp_root.is_dir():
        for entry in tmp_root.iterdir():
            try:
                info = entry.lstat()
            except OSError:
                continue
            if info.st_uid != uid or entry.name.startswith(PROTECTED_TMP_PREFIXES):
                continue
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                continue  # sockets, fifos and links stay
            found.append((entry, "tmp", tmp_cutoff))
    for base in (recovery_root / "expired-worktrees", recovery_root):
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if entry.name == "expired-worktrees" or entry.is_symlink():
                continue
            found.append((entry, "worktree_recovery", recovery_cutoff))
    return found


def run(tmp_root: Path, recovery_root: Path, *, apply: bool, now: float | None = None,
        uid: int | None = None, in_use: list[str] | None = None,
        repository: Path | None = None, cache_root: Path | None = None,
        cargo_paths: list[str] | None = None) -> dict:
    now = time.time() if now is None else now
    uid = os.getuid() if uid is None else uid
    in_use = _in_use_paths(uid) if in_use is None else in_use
    report = {"apply": apply, "inspected": 0, "deleted": [], "reclaimed_bytes": 0,
              "skipped": {"recent": 0, "in_use": 0, "permission": 0}, "failures": []}
    jobs = []
    if repository is not None:
        references = _active_job_references(repository)
        if references is None:
            report["skipped"]["queue_unreadable"] = 1
        cargo = _cargo_paths(uid) if cargo_paths is None else cargo_paths
        jobs = _retention_candidates(repository, cache_root or Path.home() / ".cache",
                                     now, references)
    work = [(p, c, cut, None) for p, c, cut in _candidates(tmp_root, recovery_root, now, uid)]
    for path, category, cutoff, owner in work + jobs:
        report["inspected"] += 1
        prefix = str(path)
        if any(item == prefix or item.startswith(prefix + "/") for item in in_use):
            report["skipped"]["in_use"] += 1
            continue
        if category.startswith("rust_") and any(
                _within(item, prefix) or (owner is not None and _within(item, str(owner)))
                for item in cargo):
            report["skipped"]["in_use"] += 1
            continue
        if category in ("ci_run", "ci_candidate"):
            # The directory's own mtime decides, as approved; size is for reporting.
            stale, size = path.lstat().st_mtime <= cutoff, 0
            if stale:
                size = _tree_bytes(path)
        else:
            stale, size = _scan(path, cutoff)
        if not stale:
            report["skipped"]["recent"] += 1
            continue
        if apply:
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except PermissionError:
                # Root-owned leftovers (e.g. written by containers) cannot be removed
                # by this user; retrying would never succeed, so do not fail the run.
                report["skipped"]["permission"] += 1
                continue
            except OSError as error:
                report["failures"].append({"path": prefix, "error": type(error).__name__})
                continue
        report["deleted"].append({"path": prefix, "category": category, "bytes": size})
        report["reclaimed_bytes"] += size
    return report


def _coordinated(repository: Path) -> bool:
    """Return True when this process may clean; otherwise queue the coordinator."""
    sys.path.insert(0, str(repository / "scripts"))
    import disk_coordinator  # noqa: E402 - repo-local module, path set just above

    active = disk_coordinator.configured(repository)
    if active is None:
        return True
    if disk_coordinator.owner_check(active):
        return True
    active.enqueue_maintenance(repository, "host")
    print(json.dumps({"queued": True, "kind": "host"}))
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="delete; default is a dry run")
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--tmp-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--recovery-root", type=Path)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(args.repository.resolve() / "scripts"))
    from disk_coordinator_state import canonical_repository  # noqa: E402 - repo-local module

    # Worktrees share the canonical checkout's sibling recovery directory.
    repository = canonical_repository(args.repository)
    recovery = args.recovery_root or repository.parent / ".openmates-worktree-recovery"
    if args.apply and not _coordinated(repository):
        return 0
    report = run(args.tmp_root, recovery, apply=args.apply, repository=repository)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
