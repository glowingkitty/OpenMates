#!/usr/bin/env python3
"""Age-based cleanup of host scratch space that no repository inventory owns.

Covers what the repository-scoped `managed` cleanup cannot see:
  * top-level entries in /tmp owned by this user, untouched for TMP_MAX_AGE_DAYS
    (newest mtime anywhere inside) and not used by any running process;
  * worktree recovery archives older than RECOVERY_MAX_AGE_DAYS.

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
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TMP_MAX_AGE_DAYS = 3
RECOVERY_MAX_AGE_DAYS = 14
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
        uid: int | None = None, in_use: list[str] | None = None) -> dict:
    now = time.time() if now is None else now
    uid = os.getuid() if uid is None else uid
    in_use = _in_use_paths(uid) if in_use is None else in_use
    report = {"apply": apply, "inspected": 0, "deleted": [], "reclaimed_bytes": 0,
              "skipped": {"recent": 0, "in_use": 0, "permission": 0}, "failures": []}
    for path, category, cutoff in _candidates(tmp_root, recovery_root, now, uid):
        report["inspected"] += 1
        prefix = str(path)
        if any(item == prefix or item.startswith(prefix + "/") for item in in_use):
            report["skipped"]["in_use"] += 1
            continue
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
    print(json.dumps(run(args.tmp_root, recovery, apply=args.apply), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
