#!/usr/bin/env python3
"""Three-way rebase of a lane's uncommitted edits onto a newer origin/dev.

Lanes cannot commit, so their work is a dirty working tree on an old base.
When origin/dev changed files the lane also edited, a plain fast-forward
would overwrite or refuse those edits. This module merges each overlapping
file with ``git merge-file`` (base = old HEAD, ours = lane bytes, theirs =
origin/dev) before the fast-forward:

* every overlap merges cleanly -> the caller fast-forwards and writes the
  merged bytes back, so the lane diff is re-based onto the new HEAD;
* any true conflict -> nothing in the worktree changes and the exact files
  and conflict hunks are reported.

Before anything is touched a backup commit of the full dirty state (tracked
changes plus untracked, non-ignored files) is stored under
``refs/openmates/rebase-backups/<worktree>``, so lane edits are always
recoverable with ``git checkout <backup> -- <path>``. Generated artifacts are
never merged: worktree_fast_forward resets and regenerates them.
Used by ``sessions.py worktree refresh-base --rebase``.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

LANE_LABEL = "lane"
BASE_LABEL = "base"
UPSTREAM_LABEL = "origin/dev"
MAX_HUNK_LINES = 40
MAX_REPORTED_HUNKS = 10


@dataclass
class MergePlan:
    """Merged bytes per overlapping path (``None`` = deleted) plus conflicts."""

    merged: dict[str, bytes | None] = field(default_factory=dict)
    conflicts: list[dict] = field(default_factory=list)


def _git(worktree: Path, *args: str, env: dict | None = None, input: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=str(worktree), env=env, input=input, capture_output=True, timeout=300)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {detail}")
    return result.stdout


def blob(worktree: Path, ref: str, relative_path: str) -> bytes | None:
    """Return ``ref:path`` bytes, or ``None`` when the path is absent there."""
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{ref}:{relative_path}"], cwd=str(worktree), capture_output=True, timeout=120
    )
    return result.stdout if result.returncode == 0 else None


def local_bytes(worktree: Path, relative_path: str) -> bytes | None:
    path = worktree / relative_path
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


def backup_ref(worktree: Path) -> str:
    """Return the local-only ref that retains this worktree's pre-rebase edits."""
    digest = hashlib.sha256(str(Path(worktree).resolve()).encode()).hexdigest()[:12]
    return f"refs/openmates/rebase-backups/{Path(worktree).name[:48]}-{digest}"


def save_backup(worktree: Path, head: str, dirty: set[str]) -> str:
    """Commit the dirty state on a temporary index and pin it under ``backup_ref``.

    Never touches the lane's index, branch or files. Returns ``ref@commit``.
    """
    with tempfile.TemporaryDirectory(prefix="openmates-rebase-index-") as directory:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        _git(worktree, "read-tree", head, env=env)
        if dirty:
            _git(worktree, "add", "-A", "--", *sorted(dirty), env=env)
        tree = _git(worktree, "write-tree", env=env).decode().strip()
        env.update(
            GIT_AUTHOR_NAME="OpenMates Lane Rebase",
            GIT_AUTHOR_EMAIL="lane-rebase@openmates.invalid",
            GIT_COMMITTER_NAME="OpenMates Lane Rebase",
            GIT_COMMITTER_EMAIL="lane-rebase@openmates.invalid",
        )
        commit = _git(
            worktree, "commit-tree", tree, "-p", head, env=env, input=b"Lane edits before refresh-base --rebase\n"
        ).decode().strip()
    ref = backup_ref(worktree)
    _git(worktree, "update-ref", ref, commit)
    return f"{ref}@{commit}"


def _conflict_hunks(merged: str) -> list[dict]:
    """Extract conflict blocks (with output line numbers) from merge-file output."""
    hunks: list[dict] = []
    current: list[str] | None = None
    start = 0
    for number, line in enumerate(merged.splitlines(), start=1):
        if current is None and line.startswith("<<<<<<< "):
            current, start = [line], number
            continue
        if current is not None:
            current.append(line)
            if line.startswith(">>>>>>> "):
                text = current if len(current) <= MAX_HUNK_LINES else [*current[:MAX_HUNK_LINES], "... (truncated)"]
                hunks.append({"line": start, "end_line": number, "text": "\n".join(text)})
                current = None
    return hunks[:MAX_REPORTED_HUNKS]


def merge_three_way(worktree: Path, relative_path: str, base: bytes | None, ours: bytes | None,
                    theirs: bytes | None) -> tuple[bytes | None, dict | None]:
    """Merge one path; return ``(result, None)`` or ``(None, conflict report)``."""
    if ours == theirs:
        return theirs, None
    if ours == base:
        return theirs, None
    if theirs == base:
        return ours, None
    if ours is None:
        return None, {"path": relative_path, "reason": "lane deleted the file; origin/dev modified it", "hunks": []}
    if theirs is None:
        return None, {"path": relative_path, "reason": "origin/dev deleted the file; lane modified it", "hunks": []}
    if any(b"\0" in data for data in (base or b"", ours, theirs)):
        return None, {"path": relative_path, "reason": "binary file changed on both sides", "hunks": []}
    with tempfile.TemporaryDirectory(prefix="openmates-merge-file-") as directory:
        files = []
        for name, data in (("ours", ours), ("base", base or b""), ("theirs", theirs)):
            target = Path(directory) / name
            target.write_bytes(data)
            files.append(str(target))
        result = subprocess.run(
            ["git", "merge-file", "-p", "--diff3", "-L", LANE_LABEL, "-L", BASE_LABEL, "-L", UPSTREAM_LABEL, *files],
            cwd=str(worktree), capture_output=True, timeout=120,
        )
    if result.returncode == 0:
        return result.stdout, None
    if 0 < result.returncode < 128:
        text = result.stdout.decode("utf-8", errors="replace")
        reason = "both sides changed the same lines" if base is not None else "both sides added the file"
        return None, {"path": relative_path, "reason": reason, "hunks": _conflict_hunks(text)}
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    raise RuntimeError(f"git merge-file failed for {relative_path}: {detail}")


def plan_merge(worktree: Path, head: str, target: str, paths: list[str]) -> MergePlan:
    """Compute merged bytes for every overlapping path without writing anything."""
    plan = MergePlan()
    for relative_path in sorted(paths):
        result, conflict = merge_three_way(
            worktree,
            relative_path,
            blob(worktree, head, relative_path),
            local_bytes(worktree, relative_path),
            blob(worktree, target, relative_path),
        )
        if conflict:
            plan.conflicts.append(conflict)
        else:
            plan.merged[relative_path] = result
    return plan


def write_merged(worktree: Path, merged: dict[str, bytes | None]) -> None:
    """Write merged bytes over the fast-forwarded checkout (``None`` deletes)."""
    for relative_path, data in merged.items():
        path = worktree / relative_path
        if data is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != data:
            path.write_bytes(data)


def restore(worktree: Path, originals: dict[str, bytes | None]) -> None:
    """Put the lane's original bytes back after a failed fast-forward."""
    write_merged(worktree, originals)


def format_conflicts(outcome: dict) -> str:
    """Return the refresh-base error text for a ``conflicted`` outcome."""
    lines = [
        "Reason: origin/dev changed lines this lane also edited; nothing in the worktree was changed.",
        f"Backup of all lane edits: {outcome.get('backup', '')}",
        "Conflicts:",
    ]
    for conflict in outcome.get("conflicts", []):
        lines.append(f"  {conflict['path']}: {conflict['reason']}")
        for hunk in conflict.get("hunks", []):
            lines.append(f"    merged lines {hunk['line']}-{hunk['end_line']}:")
            lines.extend("      " + text for text in hunk["text"].splitlines())
    lines.append(
        "Next: make each listed lane file its intended final content including origin/dev's change "
        "(see `git diff HEAD origin/dev -- <file>`; identical edits on both sides merge cleanly), "
        "then rerun refresh-base --rebase; or deploy on the recorded base and let its 3-way replay decide."
    )
    return "\n".join(lines)
