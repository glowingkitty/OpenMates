"""Inactivity, archive-retention and recovery helpers for worktree expiry.

`sessions.py worktree expire` removes managed worktrees whose chat has been
inactive for the configured number of hours. This module holds the pieces that
are independent of the session store so `sessions.py` only makes thin calls:

* chat transcript activity lookup (Claude Code transcripts under
  ``~/.claude/projects``),
* pruning of recovery archives past their retention window,
* a bundle of commits that are not yet on the target branch, and
* lookup and rendering of the recovery archive for an expired session.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CHAT_ID_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{0,127}")
ARCHIVE_NAME_SUFFIX = ".tar.gz"


def claude_projects_dir() -> Path:
    """Return the Claude Code transcript root (same override as agent_peers)."""
    return Path(os.environ.get("OPENMATES_CLAUDE_PROJECTS_DIR") or Path.home() / ".claude/projects")


def chat_transcript_mtime(chat_id: str, projects_dir: Path | None = None) -> float | None:
    """Newest mtime of a chat transcript and its sub-agent transcripts, or None.

    A chat id that is empty or not a plain file stem has no transcript. Symlinked
    transcript files are ignored.
    """
    if not chat_id or not _CHAT_ID_RE.fullmatch(chat_id):
        return None
    base = projects_dir or claude_projects_dir()
    if not base.is_dir():
        return None
    newest: float | None = None
    for folder in base.iterdir():
        if folder.is_symlink() or not folder.is_dir():
            continue
        candidates = [folder / f"{chat_id}.jsonl"]
        subagents = folder / chat_id / "subagents"
        if subagents.is_dir() and not subagents.is_symlink():
            candidates.extend(subagents.glob("*.jsonl"))
        for candidate in candidates:
            try:
                info = candidate.lstat()
            except OSError:
                continue
            if candidate.is_symlink():
                continue
            if newest is None or info.st_mtime > newest:
                newest = info.st_mtime
    return newest


def chat_is_active(chat_id: str, *, now_timestamp: float, idle_hours: float,
                   projects_dir: Path | None = None) -> bool:
    """True when the chat transcript changed within ``idle_hours``."""
    mtime = chat_transcript_mtime(chat_id, projects_dir)
    return mtime is not None and now_timestamp - mtime < idle_hours * 3600


def prune_expiry_archives(archive_dir: Path, retention_hours: float, now_timestamp: float,
                          *, dry_run: bool = False) -> list[str]:
    """Delete recovery archives older than the retention window; return their names.

    Only regular ``*.tar.gz`` files created by the expiry code are considered;
    symlinks, directories and any other entry are never touched.
    """
    if not archive_dir.is_dir() or archive_dir.is_symlink():
        return []
    pruned: list[str] = []
    for entry in sorted(archive_dir.iterdir()):
        if not entry.name.endswith(ARCHIVE_NAME_SUFFIX) or entry.name.startswith("."):
            continue
        try:
            info = entry.lstat()
        except OSError:
            continue
        if not entry.is_file() or entry.is_symlink():
            continue
        if now_timestamp - info.st_mtime < retention_hours * 3600:
            continue
        if not dry_run:
            entry.unlink(missing_ok=True)
        pruned.append(entry.name)
    return pruned


def mark_manifests_archive_pruned(manifests: list[dict], pruned_names: list[str], now_iso: str) -> int:
    """Flag deletion manifests whose recovery archive was pruned; return the count."""
    names = set(pruned_names)
    marked = 0
    for manifest in manifests:
        archive = str(manifest.get("recovery_archive") or "")
        if archive and Path(archive).name in names and not manifest.get("recovery_archive_pruned_at"):
            manifest["recovery_archive_pruned_at"] = now_iso
            marked += 1
    return marked


def archive_deletion_date(archive: Path, retention_hours: float) -> str | None:
    """ISO date when the archive will be pruned, or None when it does not exist."""
    try:
        mtime = archive.lstat().st_mtime
    except OSError:
        return None
    return (datetime.fromtimestamp(mtime, timezone.utc) + timedelta(hours=retention_hours)).strftime("%Y-%m-%d")


def find_recovery_record(data: dict, *, session_id: str = "", agent_task_id: str = "") -> dict | None:
    """Newest deletion manifest for a session id or the chat that owned it."""
    for manifest in reversed(data.get("worktree_deletion_manifests") or []):
        if not isinstance(manifest, dict):
            continue
        if session_id and str(manifest.get("session_id") or "") == session_id:
            return manifest
        if agent_task_id and str(manifest.get("agent_task_id") or "") == agent_task_id:
            return manifest
    return None


def recovery_hint(manifest: dict, retention_hours: float) -> str:
    """One sentence naming the recovery archive and when it is deleted."""
    archive = str(manifest.get("recovery_archive") or "")
    sid = manifest.get("session_id")
    if not archive:
        return (f"Session {sid} was expired after inactivity; it held no unique changes, "
                "so no recovery archive exists. Run sessions.py start for a fresh workspace.")
    if manifest.get("recovery_archive_pruned_at"):
        return (f"Session {sid} was expired after inactivity; its recovery archive {archive} "
                f"was deleted on {manifest['recovery_archive_pruned_at'][:10]} (retention expired).")
    date = archive_deletion_date(Path(archive), retention_hours)
    if date is None:
        return f"Session {sid} was expired after inactivity; its recovery archive {archive} is missing."
    return (f"Session {sid} was expired after inactivity; its changes are in the recovery archive "
            f"{archive} (deleted automatically on {date}). Restore: "
            f"python3 scripts/sessions.py worktree restore-archive --session {sid}")


def head_bundle(path: Path, target_ref: str, max_bytes: int) -> bytes:
    """Bundle commits of HEAD that are not on ``target_ref`` so they survive removal."""
    scratch = path.parent / f".expiry-bundle-{os.getpid()}-{int(time.time() * 1000)}.tmp"
    try:
        subprocess.run(["git", "bundle", "create", str(scratch), "HEAD", f"^{target_ref}"],
                       cwd=path, capture_output=True, check=True, timeout=300)
        subprocess.run(["git", "bundle", "verify", str(scratch)],
                       cwd=path, capture_output=True, check=True, timeout=120)
        if scratch.stat().st_size > max_bytes:
            raise RuntimeError("Unmerged commits exceed the bounded archive budget; worktree retained")
        return scratch.read_bytes()
    finally:
        scratch.unlink(missing_ok=True)


def restore_steps(archive: str) -> list[str]:
    """Exact manual restore steps for an expiry archive."""
    return [
        f"mkdir -p /tmp/restore && tar -xzf {archive} -C /tmp/restore   # contains manifest.json, staged.patch, working.patch, untracked/, optional head.bundle",
        "python3 scripts/sessions.py start --mode <bug|feature|docs|testing> --task \"<resumed work>\"   # fresh managed worktree",
        "In that worktree, if head.bundle exists: git fetch /tmp/restore/head.bundle HEAD && git checkout FETCH_HEAD; else check out the manifest.json head commit",
        "git apply --index /tmp/restore/staged.patch; git apply /tmp/restore/working.patch",
        "Copy files from /tmp/restore/untracked/ into the worktree (inspect symlinks first)",
    ]
