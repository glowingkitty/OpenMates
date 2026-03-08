#!/usr/bin/env python3
"""
Session lifecycle manager for concurrent Claude Code sessions.

Manages session registration, file tracking, concurrent edit safety,
architecture doc staleness detection, and automated deployment (lint + commit + push).

Architecture context: Replaces the legacy .claude/sessions.md markdown-based coordination.
See docs/claude/concurrent-sessions.md for the full protocol.

Usage:
    python3 scripts/sessions.py start   --task "fix embed decryption"
    python3 scripts/sessions.py end     --session a3f2
    python3 scripts/sessions.py status
    python3 scripts/sessions.py update  --session a3f2 --task "new description"
    python3 scripts/sessions.py claim   --session a3f2 --file path/to/file.py
    python3 scripts/sessions.py release --session a3f2 --file path/to/file.py
    python3 scripts/sessions.py track   --session a3f2 --file path/to/file.py
    python3 scripts/sessions.py lock    --session a3f2 --type docker
    python3 scripts/sessions.py unlock  --session a3f2 --type docker
    python3 scripts/sessions.py prepare-deploy --session a3f2
    python3 scripts/sessions.py deploy  --session a3f2 --title "fix: msg" --message "body"
"""

import argparse
import glob as glob_mod
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_FILE = PROJECT_ROOT / ".claude" / "sessions.json"
PROJECT_INDEX_FILE = PROJECT_ROOT / ".claude" / "project-index.json"
CODE_MAPPING_FILE = PROJECT_ROOT / "docs" / "architecture" / "code-mapping.yml"
STALE_SESSION_HOURS = 24
STALE_LOCK_MINUTES = 5
STALE_DOC_HOURS = 24

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    """Parse an ISO timestamp string to datetime."""
    # Handle both with and without Z suffix
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _hours_since(iso_str: str) -> float:
    """Return hours elapsed since the given ISO timestamp."""
    dt = _parse_iso(iso_str)
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 3600


def _minutes_since(iso_str: str) -> float:
    """Return minutes elapsed since the given ISO timestamp."""
    return _hours_since(iso_str) * 60


def _load_sessions() -> dict:
    """Load sessions.json, creating it with defaults if missing."""
    if not SESSIONS_FILE.exists():
        SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = _default_sessions()
        _save_sessions(data)
        return data
    try:
        with open(SESSIONS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupted file — reinitialize
        data = _default_sessions()
        _save_sessions(data)
        return data


def _save_sessions(data: dict) -> None:
    """Atomically write sessions.json."""
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSIONS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.replace(SESSIONS_FILE)


def _default_sessions() -> dict:
    """Return a clean default sessions structure."""
    return {
        "locks": {
            "docker_rebuild": {"status": "NONE"},
            "vercel_deploy": {"status": "NONE"},
        },
        "sessions": {},
    }


def _prune_stale(data: dict) -> list[str]:
    """Remove sessions older than STALE_SESSION_HOURS. Returns list of pruned IDs."""
    pruned = []
    to_remove = []
    for sid, session in data.get("sessions", {}).items():
        last_active = session.get("last_active", session.get("started", ""))
        if last_active and _hours_since(last_active) > STALE_SESSION_HOURS:
            to_remove.append(sid)
    for sid in to_remove:
        del data["sessions"][sid]
        pruned.append(sid)
    return pruned


def _prune_stale_locks(data: dict) -> list[str]:
    """Clear locks older than STALE_LOCK_MINUTES. Returns list of cleared lock types."""
    cleared = []
    for lock_type in ("docker_rebuild", "vercel_deploy"):
        lock = data.get("locks", {}).get(lock_type, {})
        if lock.get("status") == "IN_PROGRESS":
            last_updated = lock.get("last_updated", "")
            if last_updated and _minutes_since(last_updated) > STALE_LOCK_MINUTES:
                data["locks"][lock_type] = {"status": "NONE"}
                cleared.append(lock_type)
    return cleared


def _get_file_mtime(path: str) -> float:
    """Get modification time of a file, returning 0 if it doesn't exist."""
    full = PROJECT_ROOT / path
    if full.exists():
        return full.stat().st_mtime
    return 0.0


def _check_stale_docs() -> list[dict]:
    """Check for architecture docs that are stale relative to their mapped code.

    Returns list of dicts with doc, doc_modified, code_modified, code_file info.
    """
    stale = []
    if not CODE_MAPPING_FILE.exists():
        return stale

    # Simple YAML-like parser (no external dependency)
    mapping = _parse_code_mapping()

    for doc_name, code_patterns in mapping.items():
        doc_path = PROJECT_ROOT / "docs" / "architecture" / doc_name
        if not doc_path.exists():
            continue
        doc_mtime = doc_path.stat().st_mtime

        newest_code_file = ""
        newest_code_mtime = 0.0

        for pattern in code_patterns:
            full_pattern = str(PROJECT_ROOT / pattern)
            matches = glob_mod.glob(full_pattern, recursive=True)
            for match in matches:
                mtime = os.path.getmtime(match)
                if mtime > newest_code_mtime:
                    newest_code_mtime = mtime
                    newest_code_file = os.path.relpath(match, PROJECT_ROOT)

        if newest_code_mtime <= 0:
            continue

        hours_diff = (newest_code_mtime - doc_mtime) / 3600
        if hours_diff > STALE_DOC_HOURS:
            stale.append({
                "doc": doc_name,
                "doc_modified": datetime.fromtimestamp(
                    doc_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "code_file": newest_code_file,
                "code_modified": datetime.fromtimestamp(
                    newest_code_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
            })

    return stale


def _parse_code_mapping() -> dict[str, list[str]]:
    """Parse the simple YAML code-mapping file without requiring PyYAML.

    Expected format:
        embeds.md:
          - backend/apps/*/skills/*/embed*.py
          - frontend/packages/ui/src/components/embeds/**/*.svelte
    """
    mapping: dict[str, list[str]] = {}
    if not CODE_MAPPING_FILE.exists():
        return mapping

    current_doc = None
    with open(CODE_MAPPING_FILE) as f:
        for line in f:
            stripped = line.strip()
            # Skip comments and empty lines
            if not stripped or stripped.startswith("#"):
                continue
            # Doc name line (ends with colon, no leading dash)
            if stripped.endswith(":") and not stripped.startswith("-"):
                current_doc = stripped[:-1].strip()
                mapping[current_doc] = []
            # Pattern line (starts with dash)
            elif stripped.startswith("- ") and current_doc is not None:
                pattern = stripped[2:].strip()
                mapping[current_doc].append(pattern)

    return mapping


def _find_related_docs(modified_files: list[str]) -> list[str]:
    """Given a list of modified file paths, find architecture docs that cover them."""
    mapping = _parse_code_mapping()
    related = set()

    for doc_name, patterns in mapping.items():
        for pattern in patterns:
            for mod_file in modified_files:
                # Check if the modified file would match the glob pattern
                full_pattern = str(PROJECT_ROOT / pattern)
                full_file = str(PROJECT_ROOT / mod_file)
                # Use fnmatch-style check
                import fnmatch

                if fnmatch.fnmatch(full_file, full_pattern):
                    related.add(doc_name)
                    break

    return sorted(related)


def _generate_project_index() -> dict:
    """Generate a compact project index for Claude's context."""
    index: dict = {}

    # Backend apps
    apps_dir = PROJECT_ROOT / "backend" / "apps"
    if apps_dir.exists():
        apps = sorted(
            d.name
            for d in apps_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )
        index["backend_apps"] = apps

    # Frontend components
    comp_dir = PROJECT_ROOT / "frontend" / "packages" / "ui" / "src" / "components"
    if comp_dir.exists():
        comps = sorted(d.name for d in comp_dir.iterdir() if d.is_dir())
        index["frontend_components"] = comps

    # Frontend stores
    stores_dir = PROJECT_ROOT / "frontend" / "packages" / "ui" / "src" / "stores"
    if stores_dir.exists():
        stores = sorted(
            f.stem for f in stores_dir.iterdir() if f.suffix == ".ts" and f.is_file()
        )
        index["frontend_stores"] = stores

    # API routes
    routes_dir = PROJECT_ROOT / "backend" / "core" / "api" / "app" / "routes"
    if routes_dir.exists():
        routes = sorted(
            f.stem
            for f in routes_dir.iterdir()
            if f.suffix == ".py" and f.is_file() and f.stem != "__init__"
        )
        index["api_routes"] = routes

    # Shared providers
    providers_dir = PROJECT_ROOT / "backend" / "shared" / "providers"
    if providers_dir.exists():
        providers = sorted(
            d.name
            for d in providers_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )
        index["shared_providers"] = providers

    # Architecture docs
    arch_dir = PROJECT_ROOT / "docs" / "architecture"
    if arch_dir.exists():
        docs = sorted(
            f.stem
            for f in arch_dir.iterdir()
            if f.suffix == ".md" and f.stem != "README"
        )
        index["architecture_docs"] = docs

    index["generated_at"] = _now_iso()
    return index


def _load_or_generate_index() -> dict:
    """Load cached project index or regenerate if stale (>1 hour old)."""
    if PROJECT_INDEX_FILE.exists():
        try:
            with open(PROJECT_INDEX_FILE) as f:
                index = json.load(f)
            generated = index.get("generated_at", "")
            if generated and _hours_since(generated) < 1:
                return index
        except (json.JSONDecodeError, OSError):
            pass

    index = _generate_project_index()
    try:
        with open(PROJECT_INDEX_FILE, "w") as f:
            json.dump(index, f, indent=2)
            f.write("\n")
    except OSError:
        pass  # Non-fatal — index is a convenience
    return index


def _run_cmd(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=cwd or str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_start(args: argparse.Namespace) -> None:
    """Start a new session."""
    data = _load_sessions()

    # Prune stale sessions and locks
    pruned = _prune_stale(data)
    cleared_locks = _prune_stale_locks(data)

    # Generate session ID
    sid = secrets.token_hex(2)

    # Register session
    data["sessions"][sid] = {
        "task": args.task or "(pending)",
        "started": _now_iso(),
        "last_active": _now_iso(),
        "modified_files": [],
        "writing": None,
    }
    _save_sessions(data)

    # --- Output context for Claude ---
    print("== SESSION STARTED ==")
    print(f"Session ID: {sid}")
    print(f"Started: {_now_iso()}")
    if args.task:
        print(f"Task: {args.task}")
    print()

    # Active sessions
    other_sessions = {
        k: v for k, v in data.get("sessions", {}).items() if k != sid
    }
    if other_sessions:
        print(f"== ACTIVE SESSIONS ({len(other_sessions)}) ==")
        for osid, info in other_sessions.items():
            files_str = ""
            if info.get("writing"):
                files_str = f" [WRITING: {info['writing']}]"
            elif info.get("modified_files"):
                files_str = (
                    f" [modified: {len(info['modified_files'])} files]"
                )
            print(f"  {osid}: {info.get('task', '?')}{files_str}")
        print()

    # Locks
    locks = data.get("locks", {})
    active_locks = [
        lt for lt, lv in locks.items() if lv.get("status") == "IN_PROGRESS"
    ]
    if active_locks:
        print("== ACTIVE LOCKS ==")
        for lt in active_locks:
            lv = locks[lt]
            print(
                f"  {lt}: held by {lv.get('claimed_by', '?')} "
                f"(since {lv.get('since', '?')})"
            )
        print()

    # Stale docs
    stale = _check_stale_docs()
    if stale:
        print("== STALE ARCHITECTURE DOCS ==")
        for s in stale:
            print(
                f"  ! docs/architecture/{s['doc']} "
                f"(updated {s['doc_modified']}) "
                f"— code changed {s['code_modified']} in {s['code_file']}"
            )
        print()

    # Project index (compact summary)
    index = _load_or_generate_index()
    apps = index.get("backend_apps", [])
    if apps:
        print("== PROJECT INDEX ==")
        print(f"Backend apps ({len(apps)}): {', '.join(apps)}")
        comps = index.get("frontend_components", [])
        if comps:
            print(f"Frontend components: {', '.join(comps)}")
        routes = index.get("api_routes", [])
        if routes:
            print(f"API routes ({len(routes)}): {', '.join(routes)}")
        providers = index.get("shared_providers", [])
        if providers:
            print(f"Shared providers: {', '.join(providers)}")
        print()

    # Cleanup report
    if pruned:
        print(f"[Pruned {len(pruned)} stale sessions: {', '.join(pruned)}]")
    if cleared_locks:
        print(
            f"[Cleared {len(cleared_locks)} stale locks: "
            f"{', '.join(cleared_locks)}]"
        )

    print("== END SESSION CONTEXT ==")


def cmd_end(args: argparse.Namespace) -> None:
    """End a session and clean up."""
    data = _load_sessions()
    sid = args.session

    session = data.get("sessions", {}).get(sid)
    if not session:
        print(f"Warning: Session {sid} not found in sessions.json")
        # Still do cleanup
        _prune_stale(data)
        _save_sessions(data)
        return

    modified = session.get("modified_files", [])

    # Check for uncommitted modified files
    if modified:
        rc, stdout, _ = _run_cmd(["git", "status", "--porcelain"])
        if rc == 0 and stdout:
            dirty_files = set()
            for line in stdout.splitlines():
                # git status --porcelain format: XY filename
                if len(line) > 3:
                    dirty_files.add(line[3:].strip())

            uncommitted = [f for f in modified if f in dirty_files]
            if uncommitted:
                print("== WARNING: UNCOMMITTED MODIFIED FILES ==")
                for f in uncommitted:
                    print(f"  - {f}")
                print(
                    "These files were modified in this session but not committed."
                )
                print()

    # Check related architecture docs
    if modified:
        related = _find_related_docs(modified)
        if related:
            print("== ARCHITECTURE DOCS TO VERIFY ==")
            print(
                "You modified files related to these docs — "
                "verify they are still accurate:"
            )
            for doc in related:
                print(f"  - docs/architecture/{doc}")
            print()

    # Remove session
    del data["sessions"][sid]
    _prune_stale(data)
    _save_sessions(data)

    print(f"Session {sid} ended and removed from sessions.json.")


def cmd_status(args: argparse.Namespace) -> None:
    """Show current session state."""
    data = _load_sessions()
    _prune_stale(data)
    _prune_stale_locks(data)
    _save_sessions(data)

    sessions = data.get("sessions", {})
    locks = data.get("locks", {})

    print("== SESSION STATUS ==")
    print()

    # Locks
    print("Locks:")
    for lt, lv in locks.items():
        status = lv.get("status", "NONE")
        if status == "IN_PROGRESS":
            print(
                f"  {lt}: IN_PROGRESS "
                f"(by {lv.get('claimed_by', '?')}, "
                f"since {lv.get('since', '?')})"
            )
        else:
            print(f"  {lt}: NONE")
    print()

    # Sessions
    if not sessions:
        print("No active sessions.")
    else:
        print(f"Active sessions ({len(sessions)}):")
        for sid, info in sessions.items():
            writing = info.get("writing")
            mod_count = len(info.get("modified_files", []))
            writing_str = f" WRITING: {writing}" if writing else ""
            print(
                f"  [{sid}] {info.get('task', '?')} "
                f"(modified: {mod_count} files){writing_str}"
            )
            if info.get("modified_files"):
                for f in info["modified_files"]:
                    print(f"         - {f}")
    print()

    # Stale docs
    stale = _check_stale_docs()
    if stale:
        print(f"Stale architecture docs ({len(stale)}):")
        for s in stale:
            print(
                f"  ! {s['doc']} (doc: {s['doc_modified']}, "
                f"code: {s['code_modified']})"
            )


def cmd_update(args: argparse.Namespace) -> None:
    """Update a session's task description."""
    data = _load_sessions()
    sid = args.session

    if sid not in data.get("sessions", {}):
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    if args.task:
        data["sessions"][sid]["task"] = args.task
    data["sessions"][sid]["last_active"] = _now_iso()
    _save_sessions(data)
    print(f"Session {sid} updated.")


def cmd_claim(args: argparse.Namespace) -> None:
    """Claim a file for writing (prevents concurrent edits)."""
    data = _load_sessions()
    sid = args.session
    filepath = args.file

    if sid not in data.get("sessions", {}):
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    # Check if another session is writing to this file
    for other_sid, other_info in data.get("sessions", {}).items():
        if other_sid == sid:
            continue
        if other_info.get("writing") == filepath:
            print(
                f"BLOCKED: File '{filepath}' is currently being written "
                f"by session {other_sid} ({other_info.get('task', '?')}). "
                f"Wait for that session to finish writing.",
                file=sys.stderr,
            )
            sys.exit(2)

    # Claim the file
    data["sessions"][sid]["writing"] = filepath
    if filepath not in data["sessions"][sid].get("modified_files", []):
        data["sessions"][sid].setdefault("modified_files", []).append(filepath)
    data["sessions"][sid]["last_active"] = _now_iso()
    _save_sessions(data)
    print(f"Claimed '{filepath}' for writing in session {sid}.")


def cmd_release(args: argparse.Namespace) -> None:
    """Release a file write claim."""
    data = _load_sessions()
    sid = args.session

    if sid not in data.get("sessions", {}):
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    current_writing = data["sessions"][sid].get("writing")
    if current_writing == args.file or args.file is None:
        data["sessions"][sid]["writing"] = None
        data["sessions"][sid]["last_active"] = _now_iso()
        _save_sessions(data)
        released = current_writing or "(none)"
        print(f"Released write claim on '{released}' in session {sid}.")
    else:
        print(
            f"Warning: Session {sid} is writing '{current_writing}', "
            f"not '{args.file}'. Releasing anyway."
        )
        data["sessions"][sid]["writing"] = None
        _save_sessions(data)


def cmd_track(args: argparse.Namespace) -> None:
    """Track a file as modified by this session (without write lock).

    If --session is omitted, falls back to the most-recently-active session.
    This allows the OpenCode plugin to call `track --file <path>` without
    knowing the session ID (it uses whichever session is currently active).
    """
    data = _load_sessions()
    sessions = data.get("sessions", {})
    sid = args.session

    if not sid:
        # Fall back to most-recently-active session (OpenCode plugin path)
        if not sessions:
            return  # No active session — silently ignore
        sid = max(
            sessions.keys(),
            key=lambda s: sessions[s].get("last_active", ""),
        )

    if sid not in sessions:
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    filepath = args.file
    # Make relative to project root for consistent storage
    try:
        filepath = str(Path(filepath).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        pass  # Already relative or outside project

    if filepath not in sessions[sid].get("modified_files", []):
        sessions[sid].setdefault("modified_files", []).append(filepath)
        sessions[sid]["last_active"] = _now_iso()
        data["sessions"] = sessions
        _save_sessions(data)
        print(f"Tracked '{filepath}' as modified in session {sid}.")
    else:
        print(f"File '{filepath}' already tracked in session {sid}.")


def cmd_track_stdin(args: argparse.Namespace) -> None:
    """Track a file from PostToolUse hook (reads JSON from stdin)."""
    data = _load_sessions()

    # Find the most recently active session (hooks don't know session ID)
    sessions = data.get("sessions", {})
    if not sessions:
        return  # No active session, silently exit

    # Use the session specified, or find the most recent one
    sid = args.session
    if not sid:
        # Find most recently active session
        latest_sid = max(
            sessions.keys(),
            key=lambda s: sessions[s].get("last_active", ""),
        )
        sid = latest_sid

    if sid not in sessions:
        return

    # Read tool input from stdin (hook provides JSON)
    try:
        stdin_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    # Extract file path from tool input
    tool_input = stdin_data.get("tool_input", {})
    filepath = tool_input.get("filePath") or tool_input.get("file_path", "")

    if not filepath:
        return

    # Make relative to project root
    try:
        filepath = str(Path(filepath).relative_to(PROJECT_ROOT))
    except ValueError:
        # Already relative or outside project
        pass

    if filepath not in sessions[sid].get("modified_files", []):
        sessions[sid].setdefault("modified_files", []).append(filepath)
        sessions[sid]["last_active"] = _now_iso()
        _save_sessions(data)


def cmd_check_write(args: argparse.Namespace) -> None:
    """Check if a file can be written (for PreToolUse hook). Exit 2 to block.

    Accepts file path via:
      --file <path>   (OpenCode plugin passes it directly)
      stdin JSON      (Claude Code hook passes {"tool_input": {"filePath": ...}})
    """
    data = _load_sessions()

    # Prefer --file arg (OpenCode plugin); fall back to stdin JSON (Claude Code hook)
    filepath = getattr(args, "file", None) or ""
    if not filepath:
        try:
            stdin_data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            sys.exit(0)  # Can't parse — don't block
        tool_input = stdin_data.get("tool_input", {})
        filepath = tool_input.get("filePath") or tool_input.get("file_path", "")

    if not filepath:
        sys.exit(0)

    # Make relative
    try:
        filepath = str(Path(filepath).relative_to(PROJECT_ROOT))
    except ValueError:
        pass

    # Check if another session is writing to this file
    sessions = data.get("sessions", {})
    for sid, info in sessions.items():
        if info.get("writing") == filepath:
            # Check if the owning session is stale
            last_active = info.get("last_active", "")
            if last_active and _minutes_since(last_active) > STALE_LOCK_MINUTES:
                continue  # Stale session — allow write
            print(
                f"File '{filepath}' is currently being written by session "
                f"{sid} ({info.get('task', '?')}). "
                f"Wait for that session to finish.",
                file=sys.stderr,
            )
            sys.exit(2)  # Exit 2 = blocking error for Claude hooks

    sys.exit(0)  # Allow


def _normalize_lock_type(raw: str) -> str:
    """Normalize short lock type names to full names."""
    mapping = {
        "docker": "docker_rebuild",
        "docker_rebuild": "docker_rebuild",
        "vercel": "vercel_deploy",
        "vercel_deploy": "vercel_deploy",
    }
    normalized = mapping.get(raw.replace("-", "_"))
    if not normalized:
        return raw  # Return as-is; caller will validate
    return normalized


def cmd_lock(args: argparse.Namespace) -> None:
    """Acquire a lock (docker_rebuild or vercel_deploy)."""
    data = _load_sessions()
    sid = args.session
    lock_type = _normalize_lock_type(args.type)

    if lock_type not in ("docker_rebuild", "vercel_deploy"):
        print(
            f"Error: Unknown lock type '{args.type}'. "
            f"Use 'docker' or 'vercel'.",
            file=sys.stderr,
        )
        sys.exit(1)

    lock_key = lock_type
    lock = data.get("locks", {}).get(lock_key, {})

    if lock.get("status") == "IN_PROGRESS":
        last_updated = lock.get("last_updated", "")
        if last_updated and _minutes_since(last_updated) < STALE_LOCK_MINUTES:
            print(
                f"BLOCKED: {lock_type} lock held by "
                f"{lock.get('claimed_by', '?')} "
                f"(since {lock.get('since', '?')}, "
                f"updated {lock.get('last_updated', '?')}). "
                f"Wait and retry.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(
                f"Warning: Taking over stale {lock_type} lock from "
                f"{lock.get('claimed_by', '?')}."
            )

    data["locks"][lock_key] = {
        "status": "IN_PROGRESS",
        "claimed_by": sid,
        "since": _now_iso(),
        "last_updated": _now_iso(),
    }
    _save_sessions(data)
    print(f"Lock '{lock_type}' acquired by session {sid}.")


def cmd_unlock(args: argparse.Namespace) -> None:
    """Release a lock."""
    data = _load_sessions()
    lock_type = _normalize_lock_type(args.type)

    if lock_type not in ("docker_rebuild", "vercel_deploy"):
        print(
            f"Error: Unknown lock type '{args.type}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    data["locks"][lock_type] = {"status": "NONE"}
    _save_sessions(data)
    print(f"Lock '{lock_type}' released.")


def cmd_prepare_deploy(args: argparse.Namespace) -> None:
    """Show deployment plan: files to commit, lint status, suggested commands."""
    data = _load_sessions()
    sid = args.session

    if sid not in data.get("sessions", {}):
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    session = data["sessions"][sid]
    modified = session.get("modified_files", [])
    exclude = set(args.exclude or [])

    # Get git status
    rc, git_status, _ = _run_cmd(["git", "status", "--porcelain"])
    dirty_files = set()
    if rc == 0:
        for line in git_status.splitlines():
            if len(line) > 3:
                dirty_files.add(line[3:].strip())

    # Files to commit = modified_files that are dirty in git, minus exclusions
    to_commit = [
        f for f in modified if f in dirty_files and f not in exclude
    ]
    tracked_but_clean = [f for f in modified if f not in dirty_files]
    dirty_but_untracked = [f for f in dirty_files if f not in modified]
    excluded = [f for f in modified if f in exclude]

    print("== DEPLOYMENT PLAN ==")
    print(f"Session: {sid}")
    print(f"Task: {session.get('task', '?')}")
    print()

    if to_commit:
        print(f"Files to commit ({len(to_commit)}):")
        for f in sorted(to_commit):
            print(f"  + {f}")
    else:
        print("No files to commit.")
    print()

    if tracked_but_clean:
        print(f"Already committed ({len(tracked_but_clean)}):")
        for f in sorted(tracked_but_clean):
            print(f"  = {f}")
        print()

    if excluded:
        print(f"Excluded from commit ({len(excluded)}):")
        for f in sorted(excluded):
            print(f"  - {f}")
        print()

    if dirty_but_untracked:
        print("Warning — dirty files NOT tracked by this session:")
        for f in sorted(dirty_but_untracked):
            print(f"  ? {f}")
        print()

    # Run linter on files to commit
    if to_commit:
        # Determine file types for linter flags
        py_files = [f for f in to_commit if f.endswith(".py")]
        ts_files = [f for f in to_commit if f.endswith(".ts")]
        svelte_files = [f for f in to_commit if f.endswith(".svelte")]
        yml_files = [
            f for f in to_commit if f.endswith((".yml", ".yaml"))
        ]

        lint_flags = []
        if py_files:
            lint_flags.append("--py")
        if ts_files:
            lint_flags.append("--ts")
        if svelte_files:
            lint_flags.append("--svelte")
        if yml_files:
            lint_flags.append("--yml")

        if lint_flags:
            print("Running linter...")
            # Pass each file as --path <file> so only session-committed files
            # are checked (not all dirty files from concurrent sessions).
            path_args: list[str] = []
            for f in to_commit:
                path_args += ["--path", f]
            lint_cmd = ["./scripts/lint_changed.sh"] + lint_flags + path_args
            rc, stdout, stderr = _run_cmd(lint_cmd)
            if rc != 0:
                print("LINT ERRORS — fix before deploying:")
                if stdout:
                    print(stdout)
                if stderr:
                    print(stderr)
            else:
                print("Lint: PASSED")
        print()

    # Related architecture docs
    related = _find_related_docs(modified)
    if related:
        print("Architecture docs to verify:")
        for doc in related:
            print(f"  - docs/architecture/{doc}")
        print()

    # Suggest commands
    if to_commit:
        files_arg = " ".join(f'"{f}"' for f in sorted(to_commit))
        print("== COMMANDS ==")
        print(f"git add {files_arg}")
        print('git commit -m "<type>: <description>"')
        print("git push origin dev")

    print()
    print("== END DEPLOYMENT PLAN ==")


def cmd_deploy(args: argparse.Namespace) -> None:
    """Execute deployment: lint, git add, commit, push."""
    data = _load_sessions()
    sid = args.session

    if sid not in data.get("sessions", {}):
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    session = data["sessions"][sid]
    modified = session.get("modified_files", [])
    exclude = set(args.exclude or [])

    # Get git status to find actually dirty files
    rc, git_status, _ = _run_cmd(["git", "status", "--porcelain"])
    dirty_files = set()
    if rc == 0:
        for line in git_status.splitlines():
            if len(line) > 3:
                dirty_files.add(line[3:].strip())

    to_commit = [
        f for f in modified if f in dirty_files and f not in exclude
    ]

    if not to_commit:
        print("No files to commit.")
        sys.exit(0)

    # 1. Run linter
    py_files = [f for f in to_commit if f.endswith(".py")]
    ts_files = [f for f in to_commit if f.endswith(".ts")]
    svelte_files = [f for f in to_commit if f.endswith(".svelte")]
    yml_files = [f for f in to_commit if f.endswith((".yml", ".yaml"))]

    lint_flags = []
    if py_files:
        lint_flags.append("--py")
    if ts_files:
        lint_flags.append("--ts")
    if svelte_files:
        lint_flags.append("--svelte")
    if yml_files:
        lint_flags.append("--yml")

    if lint_flags:
        print("Running linter...")
        # Pass each file as --path <file> so the linter only checks files
        # being committed (not all dirty files from other sessions).
        path_args: list[str] = []
        for f in to_commit:
            path_args += ["--path", f]
        rc, stdout, stderr = _run_cmd(
            ["./scripts/lint_changed.sh"] + lint_flags + path_args
        )
        if rc != 0:
            print("LINT FAILED — aborting deploy:", file=sys.stderr)
            if stdout:
                print(stdout, file=sys.stderr)
            if stderr:
                print(stderr, file=sys.stderr)
            sys.exit(1)
        print("Lint: PASSED")

    # 2. Git add
    print(f"Adding {len(to_commit)} files...")
    rc, _, stderr = _run_cmd(["git", "add"] + to_commit)
    if rc != 0:
        print(f"git add failed: {stderr}", file=sys.stderr)
        sys.exit(1)

    # 3. Git commit
    commit_msg = args.title
    if args.message:
        commit_msg += "\n\n" + args.message

    print(f"Committing: {args.title}")
    rc, stdout, stderr = _run_cmd(
        ["git", "commit", "-m", commit_msg]
    )
    if rc != 0:
        print(f"git commit failed: {stderr}", file=sys.stderr)
        sys.exit(1)

    # Extract commit hash
    rc, commit_hash, _ = _run_cmd(
        ["git", "rev-parse", "--short", "HEAD"]
    )

    # 4. Git push
    print("Pushing to origin dev...")
    rc, stdout, stderr = _run_cmd(["git", "push", "origin", "dev"])
    if rc != 0:
        print(f"git push failed: {stderr}", file=sys.stderr)
        print("Commit was created locally but not pushed.")
        sys.exit(1)

    print()
    print("== DEPLOYED ==")
    print(f"Commit: {commit_hash}")
    print(f"Files: {len(to_commit)}")
    for f in sorted(to_commit):
        print(f"  {f}")
    print("Branch: dev")

    # Check related architecture docs
    related = _find_related_docs(to_commit)
    if related:
        print()
        print("Verify these architecture docs are still accurate:")
        for doc in related:
            print(f"  - docs/architecture/{doc}")



def cmd_debug_vercel(args: argparse.Namespace) -> None:
    """Start a session and print the Vercel build logs for the latest web app deployment."""
    # Auto-start a session
    args.task = "debug Vercel deployment failure"
    cmd_start(args)

    print()
    print("== VERCEL DEPLOYMENT LOGS ==")

    web_app_dir = str(PROJECT_ROOT / "frontend" / "apps" / "web_app")

    # 1. List deployments to find the latest URL
    rc, stdout, stderr = _run_cmd(
        ["vercel", "ls", "--cwd", web_app_dir],
        cwd=web_app_dir,
    )
    if rc != 0:
        print(f"Error running 'vercel ls': {stderr}", file=sys.stderr)
        sys.exit(1)

    # Parse lines: first data line after header has the latest deployment URL.
    # Line format: "  <age>  <url>  ● <Status>  <Environment>  <Duration>  <User>"
    latest_url = None
    latest_status = None
    for line in stdout.splitlines():
        parts = line.split()
        for i, part in enumerate(parts):
            if part.startswith("https://") and "vercel.app" in part:
                latest_url = part
                # Look for the ● bullet followed by the status word
                for j in range(i + 1, len(parts)):
                    if parts[j] == "●" and j + 1 < len(parts):
                        latest_status = parts[j + 1]
                        break
                    if parts[j] in ("Error", "Ready", "Building", "Canceled", "Queued"):
                        latest_status = parts[j]
                        break
                break
        if latest_url:
            break

    if not latest_url:
        print("Could not determine latest deployment URL from 'vercel ls'.")
        print(stdout)
        sys.exit(1)

    print(f"Latest deployment : {latest_url}")
    print(f"Status            : {latest_status or 'unknown'}")
    print()

    # 2. Inspect the deployment for build details
    rc, inspect_out, _ = _run_cmd(
        ["vercel", "inspect", latest_url, "--cwd", web_app_dir],
        cwd=web_app_dir,
    )
    if rc == 0 and inspect_out:
        print(inspect_out)
        print()

    # 3. Try to fetch runtime/build logs (only works for READY deployments)
    rc, log_out, log_err = _run_cmd(
        ["vercel", "logs", latest_url, "--cwd", web_app_dir],
        cwd=web_app_dir,
    )
    if rc == 0 and log_out:
        print("-- Build / Runtime Logs --")
        print(log_out)
    else:
        # For failed deployments, logs are not retrievable via CLI.
        # Print the hint from stderr if any.
        if log_err:
            print(f"vercel logs: {log_err}")
        print()
        print("Tip: For ERROR deployments the build log is only available in")
        print("     the Vercel dashboard. Check the 'Build Logs' tab at:")
        print(f"     https://vercel.com/dashboard")
        print()
        print("     Common fix: run `cd frontend/packages/ui && pnpm prepare`")
        print("     locally and look for ❌ validation errors in the output.")

    print()
    print("== END VERCEL LOGS ==")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude Code session lifecycle manager"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Start a new session")
    p_start.add_argument("--task", "-t", help="Task description")

    # end
    p_end = sub.add_parser("end", help="End a session")
    p_end.add_argument("--session", "-s", required=True, help="Session ID")

    # status
    sub.add_parser("status", help="Show current session state")

    # update
    p_update = sub.add_parser("update", help="Update session task")
    p_update.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )
    p_update.add_argument("--task", "-t", help="New task description")

    # claim
    p_claim = sub.add_parser("claim", help="Claim a file for writing")
    p_claim.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )
    p_claim.add_argument("--file", "-f", required=True, help="File path")

    # release
    p_release = sub.add_parser("release", help="Release write claim")
    p_release.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )
    p_release.add_argument("--file", "-f", help="File path (optional)")

    # track
    p_track = sub.add_parser("track", help="Track a file as modified")
    p_track.add_argument(
        "--session", "-s", help="Session ID (omit to use most-recently-active session)"
    )
    p_track.add_argument("--file", "-f", required=True, help="File path")

    # track-stdin (for hooks)
    p_track_stdin = sub.add_parser(
        "track-stdin", help="Track file from hook stdin"
    )
    p_track_stdin.add_argument("--session", "-s", help="Session ID")

    # check-write (for PreToolUse hook)
    p_check_write = sub.add_parser(
        "check-write", help="Check if file write is allowed (for hooks)"
    )
    p_check_write.add_argument(
        "--file", "-f", help="File path (optional; falls back to stdin JSON)"
    )

    # lock
    p_lock = sub.add_parser("lock", help="Acquire a lock")
    p_lock.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )
    p_lock.add_argument(
        "--type",
        "-t",
        required=True,
        choices=["docker", "vercel", "docker_rebuild", "vercel_deploy"],
        help="Lock type",
    )

    # unlock
    p_unlock = sub.add_parser("unlock", help="Release a lock")
    p_unlock.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )
    p_unlock.add_argument(
        "--type",
        "-t",
        required=True,
        choices=["docker", "vercel", "docker_rebuild", "vercel_deploy"],
        help="Lock type",
    )

    # prepare-deploy
    p_prep = sub.add_parser(
        "prepare-deploy", help="Show deployment plan"
    )
    p_prep.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )
    p_prep.add_argument(
        "--exclude",
        "-e",
        nargs="*",
        help="File paths to exclude from commit",
    )

    # deploy
    p_deploy = sub.add_parser(
        "deploy", help="Execute lint + commit + push"
    )
    p_deploy.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )
    p_deploy.add_argument(
        "--title", required=True, help="Commit title"
    )
    p_deploy.add_argument(
        "--message", "-m", help="Commit body (optional)"
    )
    p_deploy.add_argument(
        "--exclude",
        "-e",
        nargs="*",
        help="File paths to exclude",
    )

    # debug-vercel
    sub.add_parser(
        "debug-vercel",
        help="Auto-start a session and print Vercel deployment logs for the web app",
    )

    args = parser.parse_args()

    commands = {
        "start": cmd_start,
        "end": cmd_end,
        "status": cmd_status,
        "update": cmd_update,
        "claim": cmd_claim,
        "release": cmd_release,
        "track": cmd_track,
        "track-stdin": cmd_track_stdin,
        "check-write": cmd_check_write,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
        "prepare-deploy": cmd_prepare_deploy,
        "deploy": cmd_deploy,
        "debug-vercel": cmd_debug_vercel,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
