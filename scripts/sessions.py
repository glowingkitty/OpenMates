#!/usr/bin/env python3
"""
Session lifecycle manager for concurrent Claude Code sessions.

Manages session registration, file tracking, concurrent edit safety,
tag-based instruction doc preloading, architecture doc staleness detection,
and automated deployment (lint + commit + push).

Architecture context: See docs/claude/concurrent-sessions.md for the full protocol.

Usage:
    # Session lifecycle
    python3 scripts/sessions.py start   --task "fix embed decryption" [--tags frontend,debug]
    python3 scripts/sessions.py end     --session a3f2
    python3 scripts/sessions.py status
    python3 scripts/sessions.py update  --session a3f2 --task "new description"
    python3 scripts/sessions.py summary --session a3f2

    # File tracking
    python3 scripts/sessions.py track   --session a3f2 --file path/to/file.py
    python3 scripts/sessions.py claim   --session a3f2 --file path/to/file.py
    python3 scripts/sessions.py release --session a3f2 --file path/to/file.py

    # On-demand doc loading
    python3 scripts/sessions.py context --doc debugging
    python3 scripts/sessions.py context --doc sync
    python3 scripts/sessions.py deploy-docs

    # Infrastructure locks
    python3 scripts/sessions.py lock    --session a3f2 --type docker
    python3 scripts/sessions.py unlock  --session a3f2 --type docker

    # Deployment
    python3 scripts/sessions.py prepare-deploy --session a3f2
    python3 scripts/sessions.py deploy  --session a3f2 --title "fix: msg" --message "body"
"""

import argparse
import fcntl
import glob as glob_mod
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
import fnmatch
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_FILE = PROJECT_ROOT / ".claude" / "sessions.json"
PROJECT_INDEX_FILE = PROJECT_ROOT / ".claude" / "project-index.json"
CODE_MAPPING_FILE = PROJECT_ROOT / "docs" / "architecture" / "code-mapping.yml"
STALE_SESSION_HOURS = 24
STALE_EMPTY_SESSION_HOURS = 6  # Sessions with zero tracked files expire faster
STALE_LOCK_MINUTES = 5
STALE_DOC_HOURS = 24
RECENT_COMMITS_COUNT = 10  # Number of recent git commits to show at session start
CLAUDE_DOCS_DIR = PROJECT_ROOT / "docs" / "claude"
ARCH_DOCS_DIR = PROJECT_ROOT / "docs" / "architecture"

# ---------------------------------------------------------------------------
# Tag system — maps task tags to relevant docs/claude/*.md files
# ---------------------------------------------------------------------------

# Tags that map to instruction docs (loaded at session start)
TAG_TO_DOCS: dict[str, list[str]] = {
    "frontend": ["frontend-standards.md"],
    "backend": ["backend-standards.md"],
    "debug": ["debugging.md"],
    "test": ["testing.md"],
    "i18n": ["i18n.md", "manage-translations.md"],
    "figma": ["figma-to-code.md"],
    "embed": ["embed-types.md"],
    "api": ["add-api.md"],
    "planning": ["planning.md"],
    "feature": ["planning.md"],
    "logging": ["logging-and-docs.md"],
    "security": ["backend-standards.md"],
}

# Docs deferred until deploy phase (not loaded at session start)
DEPLOY_PHASE_DOCS = {"git-and-deployment.md"}

# Keywords in task descriptions that auto-infer tags
TAG_KEYWORDS: dict[str, list[str]] = {
    "frontend": [
        "svelte", "component", "css", "style", "button", "page", "layout",
        "ui", "ux", "nav", "sidebar", "modal", "toast", "settings page",
        "frontend", "front-end", "front end", "sveltekit", "vite",
    ],
    "backend": [
        "python", "fastapi", "api endpoint", "api route", "pydantic",
        "docker", "worker", "celery", "backend", "back-end", "back end",
        "skill", "directus", "database", "db", "sql", "migration",
    ],
    "debug": [
        "fix", "bug", "broken", "error", "crash", "fail", "issue",
        "debug", "investigate", "troubleshoot", "not working", "500",
        "404", "timeout", "undefined", "null", "missing",
    ],
    "test": [
        "test", "spec", "e2e", "playwright", "pytest", "vitest",
        "coverage", "assertion",
    ],
    "i18n": [
        "translat", "i18n", "locale", "language", "localization",
    ],
    "figma": [
        "figma", "design", "mockup", "wireframe",
    ],
    "embed": [
        "embed", "preview card", "fullscreen preview",
    ],
    "api": [
        "api integration", "third-party", "external api", "provider",
        "api key", "webhook",
    ],
    "feature": [
        "implement", "new feature", "add feature", "build feature",
    ],
    "logging": [
        "logging", "log level", "log format",
    ],
    "security": [
        "security", "encryption", "auth", "passkey", "csrf", "xss",
        "injection", "vulnerability",
    ],
}

# Architecture doc descriptions (for the compact index)
ARCH_DOC_DESCRIPTIONS: dict[str, str] = {
    "account-backup": "User account export/backup functionality",
    "account-recovery": "Recovery flow for users who lose login access",
    "admin-console-log-forwarding": "Client log forwarding to admin console",
    "ai-model-selection": "AI model routing and selection logic",
    "app-skills": "Skill architecture: request/response, execution model",
    "daily-inspiration": "Daily inspiration generation and delivery pipeline",
    "developer-settings": "Developer API access and device management",
    "device-sessions": "Device authorization and session management",
    "docs-web-app": "Documentation system at /docs",
    "email-privacy": "Client-side email encryption for privacy",
    "embeds": "Embed type system, storage, and rendering pipeline",
    "file-upload-pipeline": "File upload processing (images, PDFs)",
    "followup-suggestions": "Follow-up suggestion generation",
    "hallucination-mitigation": "Measures to reduce LLM hallucinations",
    "health-checks": "Service health check endpoints and monitoring",
    "logging": "Logging standards and configuration",
    "mates": "Digital team mate system architecture",
    "message-input-field": "Message input field component architecture",
    "message-parsing": "Message content parsing and rendering",
    "message-previews-grouping": "Message preview cards and grouping",
    "message-processing": "Message pipeline: preprocessing to postprocessing",
    "passkeys": "WebAuthn/passkey authentication flow",
    "payment-processing": "Payment processing via Stripe",
    "pii-protection": "PII detection and protection measures",
    "preprocessing-model-comparison": "Preprocessing model benchmarks",
    "prompt-injection": "Prompt injection prevention measures",
    "rest-api": "REST API documentation and standards",
    "security": "Zero-knowledge architecture and security model",
    "sensitive-data-redaction": "Sensitive data redaction pipeline",
    "servers": "Server infrastructure and deployment",
    "signup-and-auth": "Signup and authentication flows",
    "status-page": "Public status page architecture",
    "sync": "Cross-device synchronization protocol",
    "thinking-models": "Thinking/reasoning model integration",
    "translations": "Translation system and i18n pipeline",
    "vector-personalization": "Vector-based personalization system",
    "web-app": "Web application architecture overview",
    "zero-knowledge-storage": "Client-side encryption for all storage",
}

# Maps tags to keywords for filtering architecture docs at session start.
TAG_TO_ARCH_KEYWORDS: dict[str, list[str]] = {
    "frontend": ["web-app", "svelte", "component", "message-input", "message-parsing",
                 "message-previews", "embed", "sync", "passkey", "signup", "payment",
                 "translations", "status-page", "docs-web"],
    "backend": ["api", "skill", "processing", "worker", "celery", "health", "server",
                "logging", "model", "file-upload", "daily", "vector", "mates",
                "hallucination", "pii", "prompt-injection", "sensitive-data"],
    "debug": ["logging", "health", "admin-console", "device-session", "sync"],
    "test": ["health"],
    "embed": ["embed", "message-preview"],
    "i18n": ["translation"],
    "security": ["security", "zero-knowledge", "encryption", "passkey", "pii",
                 "prompt-injection", "email-privacy", "sensitive-data"],
    "api": ["rest-api", "api", "developer"],
}

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
    """Atomically write sessions.json with advisory file lock.

    Uses fcntl.flock to prevent concurrent write races when multiple
    Claude sessions modify sessions.json simultaneously.
    """
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = SESSIONS_FILE.with_suffix(".lock")
    try:
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                tmp = SESSIONS_FILE.with_suffix(".tmp")
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                    f.write("\n")
                tmp.replace(SESSIONS_FILE)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except OSError:
        # Fallback: write without lock (better than failing entirely)
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


def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=cwd or str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()



def _get_dirty_files() -> set[str]:
    """Parse `git status --porcelain` and return set of dirty file paths.

    Handles all porcelain v1 status formats including renames/copies
    (e.g., "R  old -> new") and quoted paths.
    """
    rc, stdout, _ = _run_cmd(["git", "status", "--porcelain"])
    dirty = set()
    if rc != 0 or not stdout:
        return dirty
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        # Porcelain v1 format: XY<space>path
        # For renames/copies: XY<space>old -> new
        path_part = line[3:]
        # Handle renames: take the NEW path (after " -> ")
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        # Strip quotes that git adds for paths with special chars
        path_part = path_part.strip().strip('"')
        if path_part:
            dirty.add(path_part)
    return dirty



def _get_recent_commits(count: int = RECENT_COMMITS_COUNT) -> list[str]:
    """Return recent git commits as one-line summaries with relative timestamps."""
    rc, stdout, _ = _run_cmd([
        "git", "log", f"--max-count={count}",
        "--format=%h %ar %s",
        "--no-merges",
    ])
    if rc != 0 or not stdout:
        return []
    return stdout.splitlines()


def _get_git_status_summary() -> dict:
    """Return a compact git status summary for session start context."""
    result = {"branch": "unknown", "tracking": "", "uncommitted": [], "unpushed": 0}

    # Current branch
    rc, stdout, _ = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if rc == 0:
        result["branch"] = stdout.strip()

    # Tracking status (ahead/behind)
    rc, stdout, _ = _run_cmd([
        "git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"
    ])
    if rc == 0 and stdout.strip():
        parts = stdout.strip().split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])
            result["unpushed"] = ahead
            if ahead == 0 and behind == 0:
                result["tracking"] = "up to date with remote"
            else:
                parts_str = []
                if ahead:
                    parts_str.append(f"{ahead} ahead")
                if behind:
                    parts_str.append(f"{behind} behind")
                result["tracking"] = ", ".join(parts_str)

    # Uncommitted files (compact: just the paths with status)
    rc, stdout, _ = _run_cmd(["git", "status", "--porcelain"])
    if rc == 0 and stdout:
        for line in stdout.splitlines():
            if len(line) >= 4:
                status = line[:2].strip()
                path = line[3:]
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                path = path.strip().strip('"')
                if path:
                    result["uncommitted"].append(f"{status} {path}")

    return result


def _infer_tags(task: str) -> list[str]:
    """Infer tags from a task description using keyword matching.

    Returns a deduplicated, sorted list of tag names.
    """
    if not task:
        return []
    task_lower = task.lower()
    matched = set()
    for tag, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            if kw in task_lower:
                matched.add(tag)
                break
    return sorted(matched)


def _resolve_docs_for_tags(tags: list[str], *, include_deploy: bool = False) -> list[str]:
    """Given a list of tags, return the deduplicated list of doc filenames to load.

    By default, deploy-phase docs (git-and-deployment.md) are excluded.
    Pass include_deploy=True to include them (e.g., during prepare-deploy).
    """
    docs = set()
    for tag in tags:
        for doc in TAG_TO_DOCS.get(tag, []):
            if not include_deploy and doc in DEPLOY_PHASE_DOCS:
                continue
            docs.add(doc)
    return sorted(docs)


def _load_doc_content(filename: str) -> str | None:
    """Load the full content of a docs/claude/ file. Returns None if not found."""
    path = CLAUDE_DOCS_DIR / filename
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _get_arch_doc_index() -> list[dict]:
    """Return a compact index of available architecture docs with descriptions."""
    index = []
    if not ARCH_DOCS_DIR.exists():
        return index
    for f in sorted(ARCH_DOCS_DIR.iterdir()):
        if f.suffix != ".md" or f.stem == "README":
            continue
        desc = ARCH_DOC_DESCRIPTIONS.get(f.stem, "")
        index.append({"name": f.stem, "file": f.name, "description": desc})
    return index

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _prefetch_debug_context(subcommand: str, entity_id: str, label: str) -> str:
    """Run a debug.py subcommand inside the api container and return its output.

    Returns a formatted block ready to print, or an error notice if the fetch fails.
    All output is captured; nothing is printed directly.
    """
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        subcommand, entity_id,
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        err = (stderr or stdout or "no output").strip()[:300]
        # Detect device-not-approved 403 specifically and give an actionable hint
        if "device" in err.lower() and ("approved" in err.lower() or "confirm" in err.lower()):
            return (
                f"[!] Production API key device not approved for {label} {entity_id}.\n"
                "    Fix: log in to production → Settings → Developers → Devices → approve the pending device.\n"
                "    Then re-run this session start command."
            )
        return f"[!] Could not fetch {label} {entity_id}: {err}\n    (Is the api container running?)"
    return stdout.strip()


def _prefetch_logs(opts_str: str) -> str:
    """Run the OpenObserve web-app-health preset log fetch and return output.

    opts_str format: comma-separated key=value pairs, e.g. 'since=10,level=error'.
    Supported keys: since (minutes), level, preset.
    """
    # Parse opts
    opts: dict[str, str] = {}
    for part in (opts_str or "since=10").split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            opts[k.strip()] = v.strip()

    since = opts.get("since", "10")
    level = opts.get("level", "")
    preset = opts.get("preset", "web-app-health")

    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "logs", "--o2", "--preset", preset, "--since", since,
    ]
    if level:
        cmd += ["--level", level]

    rc, stdout, stderr = _run_cmd(cmd, timeout=45)
    if rc != 0 or not stdout.strip():
        err = (stderr or "no output").strip()[:200]
        return f"[!] Could not fetch logs (preset={preset}, since={since}m): {err}"
    return stdout.strip()


def cmd_start(args: argparse.Namespace) -> None:
    """Start a new session with tag-based doc preloading and git context."""
    data = _load_sessions()

    # Prune stale sessions and locks
    pruned = _prune_stale(data)
    cleared_locks = _prune_stale_locks(data)

    # Generate session ID (with collision guard)
    sid = secrets.token_hex(2)
    attempts = 0
    while sid in data.get("sessions", {}) and attempts < 10:
        sid = secrets.token_hex(2)
        attempts += 1

    # Resolve tags: explicit --tags override auto-inference from --task
    tags = []
    if hasattr(args, "tags") and args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        valid_tags = set(TAG_TO_DOCS.keys())
        unknown = [t for t in tags if t not in valid_tags]
        if unknown:
            print(
                f"Warning: unrecognized tags: {', '.join(unknown)}. "
                f"Valid tags: {', '.join(sorted(valid_tags))}",
                file=sys.stderr,
            )
    elif args.task:
        tags = _infer_tags(args.task)

    # Auto-merge tags from prefetch flags (deduplicated, preserving existing order)
    extra_tags: list[str] = []
    if getattr(args, "issue", None):
        extra_tags += ["debug"]
    if getattr(args, "chat", None):
        extra_tags += ["debug"]
    if getattr(args, "embed", None):
        extra_tags += ["debug", "embed"]
    if getattr(args, "logs", None) is not None:
        extra_tags += ["debug", "logging"]
    for et in extra_tags:
        if et not in tags:
            tags.append(et)

    # Register session
    data["sessions"][sid] = {
        "task": args.task or "(pending)",
        "tags": tags,
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
    if tags:
        print(f"Tags: {', '.join(tags)}")
    print()

    # Git status
    git_status = _get_git_status_summary()
    print("== GIT STATUS ==")
    branch_info = git_status["branch"]
    if git_status["tracking"]:
        branch_info += f" ({git_status['tracking']})"
    print(f"  Branch: {branch_info}")
    uncommitted = git_status.get("uncommitted", [])
    if uncommitted:
        print(f"  Uncommitted files ({len(uncommitted)}):")
        for uf in uncommitted[:20]:
            print(f"    {uf}")
        if len(uncommitted) > 20:
            print(f"    ... and {len(uncommitted) - 20} more")
    else:
        print("  Working tree: clean")
    print()

    # Recent commits
    recent_commits = _get_recent_commits()
    if recent_commits:
        print(f"== RECENT COMMITS ({len(recent_commits)}) ==")
        for commit_line in recent_commits:
            print(f"  {commit_line}")
        print()

    # Prefetched context — issue / chat / embed / logs
    # Collected now; printed as a single block so Claude sees it immediately.
    prefetch_items: list[tuple[str, str]] = []

    issue_id = getattr(args, "issue", None)
    if issue_id:
        prefetch_items.append((f"issue {issue_id}", _prefetch_debug_context("issue", issue_id, "issue")))

    chat_id = getattr(args, "chat", None)
    if chat_id:
        prefetch_items.append((f"chat {chat_id}", _prefetch_debug_context("chat", chat_id, "chat")))

    embed_id = getattr(args, "embed", None)
    if embed_id:
        prefetch_items.append((f"embed {embed_id}", _prefetch_debug_context("embed", embed_id, "embed")))

    logs_opts = getattr(args, "logs", None)
    if logs_opts is not None:
        prefetch_items.append((f"logs ({logs_opts or 'since=10'})", _prefetch_logs(logs_opts or "since=10")))

    if prefetch_items:
        print("== PREFETCHED CONTEXT ==")
        for label, content in prefetch_items:
            print(f"--- {label} ---")
            print(content)
            print()
        print("== END PREFETCHED CONTEXT ==")
        print()

    # Active sessions — only show sessions with tracked files or active in last 2h
    other_sessions = {}
    hidden_count = 0
    for k, v in data.get("sessions", {}).items():
        if k == sid:
            continue
        has_files = bool(v.get("modified_files"))
        has_writing = bool(v.get("writing"))
        last_active = v.get("last_active", "")
        recently_active = last_active and _hours_since(last_active) < 2
        if has_files or has_writing or recently_active:
            other_sessions[k] = v
        else:
            hidden_count += 1

    if other_sessions:
        count_str = f"{len(other_sessions)}"
        if hidden_count:
            count_str += f" shown, {hidden_count} idle hidden"
        print(f"== ACTIVE SESSIONS ({count_str}) ==")
        for osid, info in other_sessions.items():
            files_str = ""
            if info.get("writing"):
                files_str = f" [WRITING: {info['writing']}]"
            elif info.get("modified_files"):
                files_str = f" [modified: {len(info['modified_files'])} files]"
            tags_str = ""
            if info.get("tags"):
                tags_str = f" ({','.join(info['tags'])})"
            print(f"  {osid}: {info.get('task', '?')[:80]}{tags_str}{files_str}")
        print()
    elif hidden_count:
        print(f"[{hidden_count} idle sessions hidden (no tracked files, inactive >2h)]")
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

    # Stale docs — filtered by session tags
    stale = _check_stale_docs()
    if stale and tags:
        relevant_stale = []
        for s in stale:
            doc_stem = s["doc"].replace(".md", "")
            desc = ARCH_DOC_DESCRIPTIONS.get(doc_stem, "").lower()
            tag_related = any(tag in desc or tag in doc_stem for tag in tags)
            if tag_related:
                relevant_stale.append(s)
        stale = relevant_stale

    if stale:
        print(f"== STALE ARCHITECTURE DOCS ({len(stale)}) ==")
        for s in stale:
            print(f"  ! {s['doc']} (doc: {s['doc_modified']}, code: {s['code_modified']})")
        print()

    # Project index — filtered by tags
    index = _load_or_generate_index()
    print("== PROJECT INDEX ==")
    show_backend = not tags or any(t in tags for t in ("backend", "debug", "api", "security", "test"))
    show_frontend = not tags or any(t in tags for t in ("frontend", "embed", "figma", "i18n", "test"))

    if show_backend:
        apps = index.get("backend_apps", [])
        if apps:
            print(f"Backend apps ({len(apps)}): {', '.join(apps)}")
        routes = index.get("api_routes", [])
        if routes:
            print(f"API routes ({len(routes)}): {', '.join(routes)}")
        providers = index.get("shared_providers", [])
        if providers:
            print(f"Shared providers: {', '.join(providers)}")

    if show_frontend:
        comps = index.get("frontend_components", [])
        if comps:
            print(f"Frontend components: {', '.join(comps)}")
    print()

    # Architecture doc index — filtered by tags
    arch_index = _get_arch_doc_index()
    if arch_index:
        if tags:
            filter_keywords = set()
            for tag in tags:
                filter_keywords.update(TAG_TO_ARCH_KEYWORDS.get(tag, []))
                filter_keywords.add(tag)

            relevant_docs = []
            other_docs = []
            for entry in arch_index:
                desc = (entry.get("description", "") or "").lower()
                name = entry["name"].lower()
                is_relevant = any(kw in name or kw in desc for kw in filter_keywords)
                if is_relevant:
                    relevant_docs.append(entry)
                else:
                    other_docs.append(entry)
            if relevant_docs:
                print("== ARCHITECTURE DOCS (relevant to tags, load with: sessions.py context --doc <name>) ==")
                for entry in relevant_docs:
                    desc_str = f" \u2014 {entry['description']}" if entry["description"] else ""
                    print(f"  {entry['name']}{desc_str}")
                if other_docs:
                    print(f"  [{len(other_docs)} more docs available]")
                print()
            else:
                print("== ARCHITECTURE DOCS (load with: sessions.py context --doc <name>) ==")
                for entry in arch_index:
                    desc_str = f" \u2014 {entry['description']}" if entry["description"] else ""
                    print(f"  {entry['name']}{desc_str}")
                print()
        else:
            print("== ARCHITECTURE DOCS (load with: sessions.py context --doc <name>) ==")
            for entry in arch_index:
                desc_str = f" \u2014 {entry['description']}" if entry["description"] else ""
                print(f"  {entry['name']}{desc_str}")
            print()

    # Cleanup report
    if pruned:
        print(f"[Pruned {len(pruned)} stale sessions: {', '.join(pruned)}]")
    if cleared_locks:
        print(f"[Cleared {len(cleared_locks)} stale locks: {', '.join(cleared_locks)}]")

    # Preload instruction docs based on tags
    docs_to_load = _resolve_docs_for_tags(tags, include_deploy=False)
    if docs_to_load:
        print()
        print(f"== INSTRUCTION DOCS ({len(docs_to_load)} loaded based on tags: {', '.join(tags)}) ==")
        for doc_name in docs_to_load:
            doc_content = _load_doc_content(doc_name)
            if doc_content:
                print(f"\n{'=' * 60}")
                print(f"FILE: docs/claude/{doc_name}")
                print(f"{'=' * 60}")
                print(doc_content.rstrip())
            else:
                print(f"  [!] docs/claude/{doc_name} not found")
        all_possible = set()
        for tag in tags:
            all_possible.update(TAG_TO_DOCS.get(tag, []))
        deferred = sorted(all_possible & DEPLOY_PHASE_DOCS)
        if deferred:
            print(f"\n[Deferred to deploy phase: {', '.join(deferred)}]")
        print()

    # Task completion checklist — always shown so it's in the initial context window.
    # git-and-deployment.md is deferred, but this compact reminder ensures Claude
    # never forgets the deploy step even without running deploy-docs.
    print("== TASK COMPLETION CHECKLIST ==")
    print("When your task is done, run these IN ORDER before writing the Task Summary:")
    print("  1. python3 scripts/sessions.py deploy-docs")
    print(f"  2. python3 scripts/sessions.py prepare-deploy --session {sid}")
    print(f"  3. python3 scripts/sessions.py deploy --session {sid} --title \"type: description\" --message \"body\" --end")
    print("     (--end closes the session automatically after a successful push)")
    print("  4. Write Task Summary to user — 'Commit:' field MUST contain the real SHA from step 3")
    print("  5. Wait for user confirmation")
    print("NOTE: Pushing to dev via sessions.py deploy is NOT a destructive action.")
    print("      Do NOT wait for explicit permission — deploy is the expected default.")
    print()

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

    # Check for uncommitted modified files — BLOCK unless --force
    if modified:
        dirty_files = _get_dirty_files()
        uncommitted = [f for f in modified if f in dirty_files]
        if uncommitted:
            force = getattr(args, "force", False)
            if not force:
                print("ERROR: Cannot end session — uncommitted tracked files:")
                for f in uncommitted:
                    print(f"  - {f}")
                print()
                print("Deploy first, then end:")
                print("  python3 scripts/sessions.py deploy-docs")
                print(f"  python3 scripts/sessions.py deploy --session {sid} --title \"type: description\" --message \"body\" --end")
                print()
                print("Or force-end (skips deploy, loses tracking):")
                print(f"  python3 scripts/sessions.py end --session {sid} --force")
                sys.exit(1)
            else:
                print("== WARNING: Force-ending session with uncommitted tracked files ==")
                for f in uncommitted:
                    print(f"  - {f}")
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

    # --json: emit raw sessions dict for machine consumers (e.g. opencode plugin)
    if getattr(args, "json", False):
        dirty_files = _get_dirty_files()
        output = {"sessions": {}, "locks": locks}
        for sid, info in sessions.items():
            modified = info.get("modified_files", [])
            uncommitted = [f for f in modified if f in dirty_files]
            output["sessions"][sid] = {
                **info,
                "uncommitted_files": uncommitted,
                "has_uncommitted": bool(uncommitted),
            }
        print(json.dumps(output))
        return

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

    # Check for collisions with other sessions
    for other_sid, other_info in sessions.items():
        if other_sid == sid:
            continue
        other_files = other_info.get("modified_files", [])
        if filepath in other_files:
            other_task = other_info.get("task", "?")[:60]
            print(
                f"WARNING: File '{filepath}' is also tracked by session "
                f"{other_sid} ('{other_task}'). "
                f"Coordinate to avoid overwriting each other's changes."
            )

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


LINT_TIMEOUT = 300  # Lint can be slow for tsc/svelte-check across many files


def _get_lint_flags(files: list[str]) -> list[str]:
    """Determine lint_changed.sh flags based on file extensions."""
    flags = []
    exts = {os.path.splitext(f)[1] for f in files}
    if ".py" in exts:
        flags.append("--py")
    if ".ts" in exts:
        flags.append("--ts")
    if ".svelte" in exts:
        flags.append("--svelte")
    if ".yml" in exts or ".yaml" in exts:
        flags.append("--yml")
    if ".css" in exts:
        flags.append("--css")
    if ".html" in exts:
        flags.append("--html")
    return flags


def _run_lint(files: list[str]) -> tuple[int, str, str]:
    """Run linter on specific files. Returns (returncode, stdout, stderr)."""
    lint_flags = _get_lint_flags(files)
    if not lint_flags:
        return 0, "", ""
    path_args: list[str] = []
    for f in files:
        path_args += ["--path", f]
    cmd = ["./scripts/lint_changed.sh"] + lint_flags + path_args
    return _run_cmd(cmd, timeout=LINT_TIMEOUT)


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

    # Get dirty files from git
    dirty_files = _get_dirty_files()

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
        lint_flags = _get_lint_flags(to_commit)
        if lint_flags:
            print("Running linter...")
            rc, stdout, stderr = _run_lint(to_commit)
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

    # Get dirty files from git
    dirty_files = _get_dirty_files()

    to_commit = [
        f for f in modified if f in dirty_files and f not in exclude
    ]

    if not to_commit:
        print("No files to commit.")
        sys.exit(0)

    # 1. Run linter (with CSS/HTML support and longer timeout)
    lint_flags = _get_lint_flags(to_commit)
    if lint_flags:
        print("Running linter...")
        rc, stdout, stderr = _run_lint(to_commit)
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

    # Auto-end session if --end flag is set
    if getattr(args, "end_session", False):
        del data["sessions"][sid]
        _save_sessions(data)
        print(f"\nSession {sid} ended.")



def cmd_context(args: argparse.Namespace) -> None:
    """Load and print a specific doc on demand (instruction doc or architecture doc)."""
    doc_name = args.doc

    # Try instruction doc first (docs/claude/)
    # Allow with or without .md extension
    if not doc_name.endswith(".md"):
        doc_name_md = doc_name + ".md"
    else:
        doc_name_md = doc_name
        doc_name = doc_name[:-3]

    # Check docs/claude/
    claude_path = CLAUDE_DOCS_DIR / doc_name_md
    if claude_path.exists():
        with open(claude_path) as f:
            content = f.read()
        print(f"== docs/claude/{doc_name_md} ==")
        print(content.rstrip())
        print(f"\n== END {doc_name_md} ==")
        return

    # Check docs/architecture/
    arch_path = ARCH_DOCS_DIR / doc_name_md
    if arch_path.exists():
        with open(arch_path) as f:
            content = f.read()
        print(f"== docs/architecture/{doc_name_md} ==")
        print(content.rstrip())
        print(f"\n== END {doc_name_md} ==")
        return

    # Not found — show available docs
    print(f"Error: Document '{doc_name}' not found.", file=sys.stderr)
    print("\nAvailable instruction docs (docs/claude/):", file=sys.stderr)
    if CLAUDE_DOCS_DIR.exists():
        for f in sorted(CLAUDE_DOCS_DIR.iterdir()):
            if f.suffix == ".md":
                print(f"  {f.stem}", file=sys.stderr)
    print("\nAvailable architecture docs (docs/architecture/):", file=sys.stderr)
    if ARCH_DOCS_DIR.exists():
        for f in sorted(ARCH_DOCS_DIR.iterdir()):
            if f.suffix == ".md" and f.stem != "README":
                print(f"  {f.stem}", file=sys.stderr)
    sys.exit(1)


def cmd_summary(args: argparse.Namespace) -> None:
    """Print a compact session summary for handoff to another session."""
    data = _load_sessions()
    sid = args.session

    session = data.get("sessions", {}).get(sid)
    if not session:
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    modified = session.get("modified_files", [])
    tags = session.get("tags", [])

    print("== SESSION SUMMARY ==")
    print(f"Session ID: {sid}")
    print(f"Task: {session.get('task', '?')}")
    print(f"Tags: {', '.join(tags) if tags else '(none)'}")
    print(f"Started: {session.get('started', '?')}")
    print(f"Last active: {session.get('last_active', '?')}")
    print()

    if modified:
        print(f"Modified files ({len(modified)}):")
        for f in sorted(modified):
            print(f"  {f}")
        print()

        # Related architecture docs
        related = _find_related_docs(modified)
        if related:
            print("Related architecture docs:")
            for doc in related:
                print(f"  docs/architecture/{doc}")
            print()

    writing = session.get("writing")
    if writing:
        print(f"Currently writing: {writing}")
        print()

    # Deploy status — show clearly whether files are committed or pending
    if modified:
        dirty_files = _get_dirty_files()
        uncommitted = [f for f in modified if f in dirty_files]
        committed = [f for f in modified if f not in dirty_files]

        if uncommitted:
            print(f"Deploy status: PENDING ({len(uncommitted)} file(s) not yet committed)")
            for f in sorted(uncommitted):
                print(f"  ! {f}")
            print()
            print("  Deploy command:")
            print(f"    python3 scripts/sessions.py deploy --session {sid} --title \"type: description\" --message \"body\" --end")
        elif committed:
            # Try to get the most recent commit SHA that touched any of these files
            rc, sha, _ = _run_cmd(["git", "log", "-1", "--format=%h", "--"] + committed)
            sha_str = sha.strip() if rc == 0 and sha.strip() else "unknown"
            print(f"Deploy status: DEPLOYED (commit {sha_str})")
            for f in sorted(committed):
                print(f"  = {f}")
        else:
            print("Deploy status: no tracked files")
    else:
        print("Deploy status: no tracked files")

    print("== END SUMMARY ==")


def cmd_lint(args: argparse.Namespace) -> None:
    """Run linter on tracked files without deploying (for mid-session checks)."""
    data = _load_sessions()
    sid = args.session

    if sid not in data.get("sessions", {}):
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    session = data["sessions"][sid]
    modified = session.get("modified_files", [])

    if not modified:
        print("No tracked files to lint.")
        return

    print(f"Linting {len(modified)} tracked files...")
    lint_flags = _get_lint_flags(modified)
    if not lint_flags:
        print("No lintable file types found.")
        return

    rc, stdout, stderr = _run_lint(modified)
    if rc != 0:
        print("LINT ERRORS:")
        if stdout:
            print(stdout)
        if stderr:
            print(stderr)
        sys.exit(1)
    else:
        print("Lint: ALL PASSED")


def cmd_deploy_docs(args: argparse.Namespace) -> None:
    """Load deployment-phase instruction docs (git, deployment standards).

    Call this before prepare-deploy/deploy to get the deployment docs
    that were deferred during session start.
    """
    # Load all deploy-phase docs
    for doc_name in sorted(DEPLOY_PHASE_DOCS):
        doc_content = _load_doc_content(doc_name)
        if doc_content:
            print(f"== docs/claude/{doc_name} ==")
            print(doc_content.rstrip())
            print(f"\n== END {doc_name} ==")
        else:
            print(f"[!] docs/claude/{doc_name} not found")
    print()


def cmd_debug_vercel(args: argparse.Namespace) -> None:
    """Start a session and print Vercel build logs via the REST API (works for ERROR deployments)."""
    # Auto-start a session
    args.task = "debug Vercel deployment failure"
    args.tags = None
    cmd_start(args)

    print()
    # Delegate to debug_vercel.py which uses the Vercel REST API.
    # This works for both READY and ERROR deployments, unlike `vercel logs`.
    debug_vercel_script = PROJECT_ROOT / "backend" / "scripts" / "debug_vercel.py"
    rc, stdout, stderr = _run_cmd(
        [sys.executable, str(debug_vercel_script)],
        cwd=str(PROJECT_ROOT),
    )
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    if rc != 0:
        sys.exit(rc)


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
    p_start.add_argument(
        "--tags",
        help="Comma-separated tags (e.g., 'frontend,debug'). "
        "Auto-inferred from --task if omitted. "
        "Valid: frontend, backend, debug, test, i18n, figma, embed, "
        "api, planning, feature, logging, concurrent, security",
    )
    p_start.add_argument(
        "--issue",
        metavar="ISSUE_ID",
        help="Pre-fetch issue details at session start (runs debug.py issue <id>). "
        "Auto-adds 'debug' tag.",
    )
    p_start.add_argument(
        "--chat",
        metavar="CHAT_ID",
        help="Pre-fetch chat details at session start (runs debug.py chat <id>). "
        "Auto-adds 'debug' tag.",
    )
    p_start.add_argument(
        "--embed",
        metavar="EMBED_ID",
        help="Pre-fetch embed details at session start (runs debug.py embed <id>). "
        "Auto-adds 'debug,embed' tags.",
    )
    p_start.add_argument(
        "--logs",
        metavar="OPTS",
        nargs="?",
        const="since=10",
        help="Pre-fetch OpenObserve logs at session start. "
        "Optional value: comma-separated options like 'since=10,level=error' "
        "(default: since=10). Auto-adds 'debug,logging' tags.",
    )

    # end
    p_end = sub.add_parser("end", help="End a session")
    p_end.add_argument("--session", "-s", required=True, help="Session ID")
    p_end.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force-end even if there are uncommitted tracked files (skips deploy gate)",
    )

    # status
    p_status = sub.add_parser("status", help="Show current session state")
    p_status.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON (for machine consumers, e.g. opencode plugin)",
    )

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
    p_deploy.add_argument(
        "--end",
        action="store_true",
        dest="end_session",
        help="End the session after successful deploy",
    )

    # lint (run linter on tracked files without deploying)
    p_lint = sub.add_parser(
        "lint", help="Run linter on tracked files (no commit/push)"
    )
    p_lint.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )

    # context (on-demand doc loading)
    p_context = sub.add_parser(
        "context", help="Load a doc on demand (instruction or architecture)"
    )
    p_context.add_argument(
        "--doc", "-d", required=True,
        help="Document name (e.g., 'debugging', 'sync', 'embed-types')",
    )

    # summary (session handoff)
    p_summary = sub.add_parser(
        "summary", help="Print session summary for handoff"
    )
    p_summary.add_argument(
        "--session", "-s", required=True, help="Session ID"
    )

    # deploy-docs (load deferred deployment docs)
    sub.add_parser(
        "deploy-docs",
        help="Load deployment-phase docs (git, deployment standards) "
        "deferred from session start",
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
        "lint": cmd_lint,
        "context": cmd_context,
        "summary": cmd_summary,
        "deploy-docs": cmd_deploy_docs,
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
