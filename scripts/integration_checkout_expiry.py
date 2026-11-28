#!/usr/bin/env python3
"""Prove that a leftover deploy integration checkout holds nothing unpushed (TASK-541).

A failed or superseded `sessions.py deploy` leaves `integration-<session>-<id>`
checkouts with a staged candidate patch. Worktree expiry used to keep every one
of them as "unique_changes", so about 30 of them (16 GB) never left the dev disk.

`integration_checkout_landed` returns True only when nothing in the checkout
would be lost: HEAD is on the target branch, there are no untracked files, and
either

* every changed file already has the same content on the target branch or in
  the session's own source lane (`agent-<session>`), or
* there are no unstaged edits and the staged patch was pushed as a commit on
  the target branch (same `git patch-id --stable`).

Anything else stays for the owner of the session. Process and chat liveness
checks are the caller's (sessions.py worktree expiry).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Commits searched for a matching patch after the checkout's HEAD.
PATCH_SEARCH_LIMIT = 600
GIT_TIMEOUT = 120


def _git(cwd: Path, *args: str, stdin: bytes | None = None) -> tuple[int, bytes]:
    result = subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True,
                            timeout=GIT_TIMEOUT, check=False)
    return result.returncode, result.stdout


def _blob(root: Path, name: str) -> str | None:
    path = root / name
    if not path.is_file() or path.is_symlink():
        return None
    code, out = _git(root, "hash-object", "--no-filters", "--", name)
    return out.decode().strip() if code == 0 and out.strip() else None


def _target_blob(cwd: Path, target_ref: str, name: str) -> str | None:
    code, out = _git(cwd, "rev-parse", "-q", "--verify", f"{target_ref}:{name}")
    return out.decode().strip() if code == 0 and out.strip() else None


def _patch_id(cwd: Path, diff: bytes) -> str:
    if not diff.strip():
        return ""
    _code, out = _git(cwd, "patch-id", "--stable", stdin=diff)
    return out.decode().split()[0] if out.split() else ""


def source_lane(path: Path) -> Path | None:
    """`agent-<session>` next to `integration-<session>-<id>`, when it still exists."""
    parts = path.name.split("-")
    if len(parts) < 3 or parts[0] != "integration":
        return None
    lane = path.parent / f"agent-{parts[1]}"
    return lane if lane.is_dir() else None


def integration_checkout_landed(path: Path, target_ref: str) -> bool:
    """True when the integration checkout at path holds no work missing from target_ref or its lane."""
    code, head = _git(path, "rev-parse", "HEAD")
    head_text = head.decode().strip()
    if code != 0 or not head_text:
        return False
    if _git(path, "merge-base", "--is-ancestor", head_text, target_ref)[0] != 0:
        return False
    code, untracked = _git(path, "ls-files", "--others", "--exclude-standard", "-z")
    if code != 0 or untracked.strip(b"\0"):
        return False
    code, names = _git(path, "diff", "--name-only", "-z", "HEAD")
    if code != 0:
        return False
    changed = [name.decode() for name in names.split(b"\0") if name]
    if not changed:
        return True
    lane = source_lane(path)
    if all(
        (current := _blob(path, name)) == _target_blob(path, target_ref, name)
        or (lane is not None and current is not None and current == _blob(lane, name))
        for name in changed
    ):
        return True
    code, unstaged = _git(path, "diff", "--binary")
    if code != 0 or unstaged.strip():
        return False
    code, staged = _git(path, "diff", "--cached", "--binary", "HEAD")
    mine = _patch_id(path, staged) if code == 0 else ""
    if not mine:
        return False
    code, history = _git(path, "log", "-p", "--binary", "--format=commit %H", "-n",
                         str(PATCH_SEARCH_LIMIT), f"{head_text}..{target_ref}")
    if code != 0:
        return False
    _code, ids = _git(path, "patch-id", "--stable", stdin=history)
    return any(line.split()[0] == mine for line in ids.decode().splitlines() if line.split())
