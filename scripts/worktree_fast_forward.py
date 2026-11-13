#!/usr/bin/env python3
"""Fast-forward a parallel-lane worktree to origin/dev while keeping its edits.

Lanes cannot commit, so their work is a dirty diff on an old base. Moving the
lane to current origin/dev keeps deploy replays small and avoids stale-base
conflicts. Generated outputs (Specification artifacts, generated Rust
migration YAML) are reset to HEAD before the merge and rebuilt afterwards,
because deploy regenerates them anyway. Used by `sessions.py worktree
refresh-base --rebase` (``merge_overlap=True``: overlapping lane edits are
3-way merged by scripts/worktree_rebase.py) and by deploy's automatic
fast-forward (overlaps stay ``blocked``; deploy's replay decides).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from scripts import worktree_rebase
except ModuleNotFoundError:
    import worktree_rebase

# Full-repo Specification generation takes ~40-70 s on an idle host; a loaded
# host must not turn a slow generator into a misleading "stale artifact" error.
GENERATOR_TIMEOUT_SECONDS = 900


def _run(command: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _null_separated(command: list[str], cwd: Path) -> set[str]:
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, timeout=120)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Could not inspect worktree ({' '.join(command[:3])}): {detail}")
    return {item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\0") if item}


def path_matches_ref(worktree: Path, relative_path: str, ref: str) -> bool:
    """Return whether a worktree file's bytes equal ``ref:path`` (both absent counts)."""
    rc, ref_blob, _stderr = _run(["git", "rev-parse", "--verify", "--quiet", f"{ref}:{relative_path}"], worktree)
    local = worktree / relative_path
    if not local.exists() and not local.is_symlink():
        return rc != 0
    if rc != 0 or not local.is_file():
        return False
    hash_rc, local_blob, _stderr = _run(["git", "hash-object", "--", relative_path], worktree)
    return hash_rc == 0 and local_blob == ref_blob


def dirty_paths(worktree: Path) -> set[str]:
    """Return tracked changes against HEAD plus untracked, non-ignored files."""
    return _null_separated(["git", "diff", "--name-only", "-z", "HEAD", "--"], worktree) | _null_separated(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], worktree
    )


def regenerate(worktree: Path, reset: list[str], *, specification: set[str], rust_migration: set[str]) -> list[str]:
    """Rebuild reset generated files in the worktree; return warnings, never stage."""
    commands: list[tuple[str, list[str]]] = []
    if any(path in specification for path in reset):
        commands.append(("specifications.py", ["generate", "--repo-root", str(worktree)]))
    # The Rust migration YAML reads the assertion index, so rebuild it after it.
    if commands or any(path in rust_migration for path in reset):
        commands.append(("rust_migration_yaml.py", []))
    warnings: list[str] = []
    for script_name, extra in commands:
        script = worktree / "scripts" / script_name
        if not script.exists():
            continue
        try:
            rc, stdout, stderr = _run([sys.executable, str(script), *extra], worktree, timeout=GENERATOR_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            rc, stdout, stderr = 1, "", f"timed out after {GENERATOR_TIMEOUT_SECONDS}s"
        if rc != 0:
            # Deploy rebuilds these outputs in the integration checkout, so a
            # lane-local failure is reported to the caller rather than fatal.
            warnings.append(f"{script_name} failed during regeneration: {(stderr or stdout)[:500]}")
    return warnings


def fast_forward_to_origin_dev(
    worktree: Path, *, specification: set[str], rust_migration: set[str], merge_overlap: bool = False
) -> dict:
    """Fast-forward ``worktree`` to origin/dev, preserving dirty lane edits.

    Returns a dict with ``status``: ``current`` (already there), ``diverged``
    (HEAD not an ancestor of origin/dev), ``blocked`` (dirty files overlap
    incoming changes; ``overlap`` lists them and nothing was changed),
    ``conflicted`` (``merge_overlap`` only: a 3-way merge of an overlap hit a
    true conflict; ``conflicts`` lists files and hunks, ``backup`` the ref
    holding all lane edits, nothing was changed) or ``fast_forwarded``
    (``reset`` lists generated files reset and rebuilt, ``merged`` the
    overlapping lane files 3-way merged onto the new HEAD).
    Without ``merge_overlap``, dirty files that origin/dev also changed are
    tolerated only when their bytes already equal origin/dev.
    """
    worktree = Path(worktree)
    regenerable = specification | rust_migration
    rc, _stdout, stderr = _run(["git", "fetch", "origin", "dev"], worktree)
    if rc != 0:
        raise RuntimeError(f"Could not fetch origin/dev: {stderr}")
    rc, target, stderr = _run(["git", "rev-parse", "refs/remotes/origin/dev"], worktree)
    if rc != 0 or not target:
        raise RuntimeError(f"Could not resolve origin/dev: {stderr}")
    rc, head, stderr = _run(["git", "rev-parse", "HEAD"], worktree)
    if rc != 0 or not head:
        raise RuntimeError(f"Could not resolve worktree HEAD: {stderr}")
    result: dict = {"status": "current", "previous_head": head, "head": head, "target": target,
                    "overlap": [], "reset": [], "merged": [], "conflicts": [], "backup": "", "warnings": []}
    if head == target:
        return result
    if _run(["git", "merge-base", "--is-ancestor", head, target], worktree)[0] != 0:
        result["status"] = "diverged"
        return result
    incoming = _null_separated(["git", "diff", "--name-only", "-z", head, target, "--"], worktree)
    dirty = dirty_paths(worktree)
    reset = sorted(path for path in dirty if path in regenerable)
    overlap: list[str] = []
    for relative_path in sorted((dirty & incoming) - set(reset)):
        if path_matches_ref(worktree, relative_path, target):
            reset.append(relative_path)
        else:
            overlap.append(relative_path)
    merged: dict[str, bytes | None] = {}
    if overlap and not merge_overlap:
        result.update(status="blocked", overlap=overlap)
        return result
    if overlap:
        result["overlap"] = overlap
        result["backup"] = worktree_rebase.save_backup(worktree, head, dirty)
        plan = worktree_rebase.plan_merge(worktree, head, target, overlap)
        if plan.conflicts:
            result.update(status="conflicted", conflicts=plan.conflicts)
            return result
        merged = plan.merged
    reset.sort()
    touched = sorted(set(reset) | set(merged))
    originals = {path: worktree_rebase.local_bytes(worktree, path) for path in touched}
    try:
        for relative_path in touched:
            if _run(["git", "cat-file", "-e", f"HEAD:{relative_path}"], worktree)[0] == 0:
                rc, _stdout, stderr = _run(["git", "checkout", "HEAD", "--", relative_path], worktree)
                if rc != 0:
                    raise RuntimeError(f"Could not reset {relative_path} before fast-forward: {stderr}")
            else:
                (worktree / relative_path).unlink(missing_ok=True)
        rc, _stdout, stderr = _run(["git", "merge", "--ff-only", target], worktree, timeout=300)
        if rc != 0:
            raise RuntimeError(f"Could not fast-forward worktree to origin/dev: {stderr}")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        if _run(["git", "rev-parse", "HEAD"], worktree)[1] == head:
            worktree_rebase.restore(worktree, originals)
        backup = f" Backup of all lane edits: {result['backup']}." if result["backup"] else ""
        raise RuntimeError(f"{exc}. Lane files were restored where HEAD did not move.{backup}") from exc
    worktree_rebase.write_merged(worktree, merged)
    result.update(status="fast_forwarded", head=target, reset=sorted(reset), merged=sorted(merged))
    result["warnings"] = regenerate(worktree, reset, specification=specification, rust_migration=rust_migration)
    return result
