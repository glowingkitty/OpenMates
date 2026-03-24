#!/usr/bin/env python3
"""
Session lifecycle manager for concurrent Claude Code sessions.

Manages session registration, file tracking, concurrent edit safety,
tag-based instruction doc preloading, architecture doc staleness detection,
and automated deployment (lint + commit + push).

Architecture context: See docs/contributing/guides/concurrent-sessions.md for the full protocol.

Usage:
    # Session lifecycle (modes: feature, bug, docs, question, testing)
    python3 scripts/sessions.py start   --mode bug --task "fix embed decryption" [--tags frontend,debug]
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
    python3 scripts/sessions.py deploy  --session a3f2 --title "fix: msg" --message "body" [--no-verify]

    # Query context docs
    python3 scripts/sessions.py context --list       # list all available docs with line counts
    python3 scripts/sessions.py context --doc <name>
"""

import argparse
import fcntl
import fnmatch
import glob as glob_mod
import json
import os
import re
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
BACKLOG_FILE = PROJECT_ROOT / ".claude" / "backlog.json"
TASKS_DIR = PROJECT_ROOT / ".claude" / "tasks"
TASKS_META_FILE = TASKS_DIR / ".meta.json"
PROJECT_INDEX_FILE = PROJECT_ROOT / ".claude" / "project-index.json"
CODE_MAPPING_FILE = PROJECT_ROOT / "docs" / "architecture" / "code-mapping.yml"
STALE_SESSION_HOURS = 24
STALE_EMPTY_SESSION_HOURS = 6  # Sessions with zero tracked files expire faster
STALE_LOCK_MINUTES = 5
STALE_DOC_HOURS = 24
RECENT_COMMITS_COUNT = 5  # Number of recent git commits to show at session start
CONTRIBUTING_GUIDES_DIR = PROJECT_ROOT / "docs" / "contributing" / "guides"
CONTRIBUTING_STANDARDS_DIR = PROJECT_ROOT / "docs" / "contributing" / "standards"
DESIGN_GUIDE_DIR = PROJECT_ROOT / "docs" / "design-guide"
ARCH_DOCS_DIR = PROJECT_ROOT / "docs" / "architecture"
ENV_FILE = PROJECT_ROOT / ".env"

# ---------------------------------------------------------------------------
# Tag system — maps task tags to relevant instruction docs
# Docs are searched in: contributing/guides/, contributing/standards/, design-guide/
# ---------------------------------------------------------------------------

# Tags that map to instruction docs (loaded at session start)
TAG_TO_DOCS: dict[str, list[str]] = {
    "frontend": ["standards/frontend.md"],
    "backend": ["standards/backend.md"],
    "cli": ["standards/cli.md"],
    "debug": ["guides/debugging.md"],
    "test": ["guides/testing.md"],
    "i18n": ["guides/i18n.md", "guides/manage-translations.md"],
    "figma": ["guides/figma-to-code.md"],
    "settings": ["design-guide/settings-ui.md"],
    "embed": ["guides/add-embed-type.md"],
    "api": ["guides/add-api.md"],
    "planning": ["guides/planning.md"],
    "feature": ["guides/planning.md"],
    "logging": ["guides/logging.md"],
    "security": ["standards/backend.md"],
}

# Docs deferred until deploy phase (not loaded at session start)
DEPLOY_PHASE_DOCS = {"guides/git-and-deployment.md"}

# ---------------------------------------------------------------------------
# Session modes — controls what output sections are shown at start
# ---------------------------------------------------------------------------

VALID_MODES = ("feature", "bug", "docs", "question", "testing")

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
    "cli": [
        "cli", "openmates-cli", "openmates cli", "terminal", "command line",
        "command-line", "npm package", "crypto.ts", "client.ts", "ws.ts",
        "storage.ts", "embedRenderers", "pair auth", "pair-auth", "whoami",
        "memory_type_registry", "MEMORY_TYPE_REGISTRY",
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
    "cli": ["sync", "zero-knowledge", "security", "passkey", "signup", "web-app"],
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


def _get_commit_url(commit_hash: str) -> str | None:
    """Build a GitHub commit URL from remote origin URL and commit hash."""
    rc, remote_url, _ = _run_cmd(["git", "config", "--get", "remote.origin.url"])
    if rc != 0 or not remote_url:
        return None

    repository = remote_url.strip()
    if repository.startswith("git@github.com:"):
        repository = repository.replace("git@github.com:", "", 1)
    elif repository.startswith("https://github.com/"):
        repository = repository.replace("https://github.com/", "", 1)
    elif repository.startswith("http://github.com/"):
        repository = repository.replace("http://github.com/", "", 1)
    else:
        return None

    if repository.endswith(".git"):
        repository = repository[:-4]

    repository = repository.strip("/")
    if not repository:
        return None
    return f"https://github.com/{repository}/commit/{commit_hash}"



def _get_dirty_files() -> set[str]:
    """Parse `git status --porcelain` and return set of dirty file paths.

    Handles all porcelain v1 status formats including renames/copies
    (e.g., "R  old -> new") and quoted paths.

    Uses -uall to list individual files inside untracked directories,
    so that new files tracked by a session can be matched by path.
    Without -uall, git collapses untracked dirs to "?? dir/" and
    individual file paths never appear in the dirty set.
    """
    rc, stdout, _ = _run_cmd(["git", "status", "--porcelain", "-uall"])
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


def _get_staged_files() -> set[str]:
    """Return set of file paths currently in the git index (staged for commit)."""
    rc, stdout, _ = _run_cmd(["git", "diff", "--name-only", "--cached"])
    if rc != 0 or not stdout:
        return set()
    return {line.strip() for line in stdout.splitlines() if line.strip()}


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


def _get_commits_since_sha(sha: str) -> list[str]:
    """Return commits made after the given SHA (exclusive). Used for --since-last-deploy."""
    if not sha:
        return []
    rc, stdout, _ = _run_cmd([
        "git", "log", f"{sha}..HEAD",
        "--format=%h %ar %s",
        "--no-merges",
    ])
    if rc != 0 or not stdout:
        return []
    return stdout.splitlines()


def _load_last_deploy_sha() -> str:
    """Load the last-deployed commit SHA from .claude/sessions.json metadata."""
    data = _load_sessions()
    return data.get("last_deploy_sha", "")


def _save_last_deploy_sha(sha: str) -> None:
    """Persist the last-deployed commit SHA in sessions.json."""
    data = _load_sessions()
    data["last_deploy_sha"] = sha
    _save_sessions(data)


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
    """Load an instruction doc by relative path.

    Filenames use prefixed paths: 'guides/debugging.md', 'standards/frontend.md',
    or 'design-guide/settings-ui.md'.
    """
    CONTRIBUTING_DIR = PROJECT_ROOT / "docs" / "contributing"
    DOCS_DIR = PROJECT_ROOT / "docs"

    if filename.startswith("guides/") or filename.startswith("standards/"):
        path = CONTRIBUTING_DIR / filename
    elif filename.startswith("design-guide/"):
        path = DOCS_DIR / filename
    else:
        # Fallback: try contributing/guides, contributing/standards, design-guide
        for parent in (CONTRIBUTING_DIR / "guides", CONTRIBUTING_DIR / "standards", DOCS_DIR / "design-guide"):
            candidate = parent / filename
            if candidate.exists():
                path = candidate
                break
        else:
            return None

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
    for f in sorted(ARCH_DOCS_DIR.rglob("*.md")):
        if f.stem == "README":
            continue
        rel = f.relative_to(ARCH_DOCS_DIR)
        desc = ARCH_DOC_DESCRIPTIONS.get(f.stem, "")
        index.append({"name": f.stem, "file": str(rel), "description": desc})
    return index

# ---------------------------------------------------------------------------
# Task file helpers (.claude/tasks/<id>-<slug>.yml)
# ---------------------------------------------------------------------------


def _tasks_dir() -> Path:
    """Return the tasks directory, creating it if needed."""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    return TASKS_DIR


def _load_task_meta() -> dict:
    """Load .meta.json, returning defaults if missing."""
    _tasks_dir()
    if not TASKS_META_FILE.exists():
        return {"next_id": 1, "last_id": None}
    try:
        with open(TASKS_META_FILE) as f:
            return json.load(f)
    except Exception:
        return {"next_id": 1, "last_id": None}


def _save_task_meta(meta: dict) -> None:
    TASKS_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TASKS_META_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f)
    tmp.replace(TASKS_META_FILE)


def _slugify(title: str) -> str:
    """Convert title to lowercase-hyphenated slug, max 40 chars."""
    import re as _re
    slug = title.lower()
    slug = _re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:40].rstrip("-")


def _task_id_to_path(task_id: str) -> "Path | None":
    """Glob for <task_id>-*.yml inside the tasks dir."""
    d = _tasks_dir()
    matches = list(d.glob(f"{task_id}-*.yml"))
    return matches[0] if matches else None


def _parse_task_file(path: "Path") -> dict:
    """
    Custom line-by-line YAML reader for task files.
    Handles: scalar strings, block scalars (|), and list items (- "...").
    No external dependencies. Only handles the exact schema defined in the plan.
    """
    with open(path) as f:
        lines = f.readlines()

    task: dict = {}
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].rstrip("\n")
        # Skip comments and blank lines at top level
        if line.startswith("#") or line.strip() == "":
            i += 1
            continue

        # Top-level key: value or key: |
        if ":" in line and not line.startswith(" ") and not line.startswith("-"):
            colon = line.index(":")
            key = line[:colon].strip()
            rest = line[colon + 1:].strip()

            if rest == "|":
                # Block scalar: collect indented lines
                i += 1
                block_lines = []
                while i < n:
                    bl = lines[i].rstrip("\n")
                    if bl == "" or bl.startswith("  "):
                        block_lines.append(bl[2:] if bl.startswith("  ") else "")
                        i += 1
                    else:
                        break
                # Strip trailing blank lines
                while block_lines and block_lines[-1] == "":
                    block_lines.pop()
                task[key] = "\n".join(block_lines)
            else:
                # Inline value — strip surrounding quotes
                val = rest.strip("\"'")
                task[key] = val
                i += 1
        elif line.startswith("  - ") or line.startswith("    - "):
            # List continuation — shouldn't reach here at top level; skip
            i += 1
        else:
            i += 1

        # After reading a scalar key, check if next lines are list items
        # (for keys like plan:, acceptance_criteria:, tags:, files_to_modify:, files_modified:)
        if (
            ":" in line
            and not line.startswith(" ")
            and not line.startswith("-")
        ):
            key_just_set = line.split(":")[0].strip()
            list_keys = {"plan", "acceptance_criteria", "tags", "files_to_modify", "files_modified"}
            if key_just_set in list_keys and task.get(key_just_set) == "":
                # Collect the list items
                items = []
                while i < n:
                    bl = lines[i].rstrip("\n")
                    if bl.startswith("  - "):
                        items.append(bl[4:].strip().strip("\"'"))
                        i += 1
                    elif bl.strip() == "":
                        i += 1
                        # peek ahead
                        if i < n and not lines[i].startswith("  "):
                            break
                    else:
                        break
                task[key_just_set] = items

    # Ensure list fields are always lists
    for lk in ("plan", "acceptance_criteria", "tags", "files_to_modify", "files_modified"):
        if lk not in task:
            task[lk] = []
        elif not isinstance(task[lk], list):
            task[lk] = []

    return task


def _render_task_file(task: dict) -> str:
    """Serialize task dict to YAML string with fixed field order."""
    lines = []
    lines.append(f"id: {task.get('id', '')}")
    lines.append(f"title: \"{task.get('title', '')}\"")
    lines.append(f"status: {task.get('status', 'todo')}")
    lines.append(f"mode: {task.get('mode', 'feature')}")
    # tags
    tags = task.get("tags", [])
    if tags:
        lines.append("tags:")
        for t in tags:
            lines.append(f"  - {t}")
    else:
        lines.append("tags: []")
    lines.append(f"created: \"{task.get('created', _now_iso())}\"")
    lines.append(f"updated: \"{task.get('updated', _now_iso())}\"")
    lines.append(f"session: {task.get('session', '~')}")
    # context block scalar
    ctx = task.get("context", "")
    if ctx:
        lines.append("context: |")
        for cl in ctx.split("\n"):
            lines.append(f"  {cl}")
    else:
        lines.append("context: ''")
    # plan list
    plan = task.get("plan", [])
    if plan:
        lines.append("plan:")
        for step in plan:
            lines.append(f"  - \"{step}\"")
    else:
        lines.append("plan: []")
    # acceptance_criteria list
    ac = task.get("acceptance_criteria", [])
    if ac:
        lines.append("acceptance_criteria:")
        for item in ac:
            lines.append(f"  - \"{item}\"")
    else:
        lines.append("acceptance_criteria: []")
    # files_to_modify list
    ftm = task.get("files_to_modify", [])
    if ftm:
        lines.append("files_to_modify:")
        for f in ftm:
            lines.append(f"  - \"{f}\"")
    else:
        lines.append("files_to_modify: []")
    # files_modified list
    fm = task.get("files_modified", [])
    if fm:
        lines.append("files_modified:")
        for f in fm:
            lines.append(f"  - \"{f}\"")
    else:
        lines.append("files_modified: []")
    # notes block scalar
    notes = task.get("notes", "")
    if notes:
        lines.append("notes: |")
        for nl in notes.split("\n"):
            lines.append(f"  {nl}")
    else:
        lines.append("notes: ''")
    # summary block scalar
    summary = task.get("summary", "")
    if summary:
        lines.append("summary: |")
        for sl in summary.split("\n"):
            lines.append(f"  {sl}")
    else:
        lines.append("summary: ''")
    return "\n".join(lines) + "\n"


def _load_task(task_id: str) -> "dict | None":
    """Load a task file by ID. Returns None if not found."""
    path = _task_id_to_path(task_id)
    if path is None:
        return None
    return _parse_task_file(path)


def _save_task(task: dict) -> None:
    """Set updated timestamp and write task atomically."""
    task["updated"] = _now_iso()
    task_id = task["id"]
    path = _task_id_to_path(task_id)
    if path is None:
        # New file
        slug = _slugify(task.get("title", task_id))
        path = _tasks_dir() / f"{task_id}-{slug}.yml"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        f.write(_render_task_file(task))
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Backlog helpers
# ---------------------------------------------------------------------------


def _load_backlog() -> dict:
    """Load backlog.json, creating it with defaults if missing."""
    if not BACKLOG_FILE.exists():
        BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {"backlog": []}
        _save_backlog(data)
        return data
    try:
        with open(BACKLOG_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {"backlog": []}
        _save_backlog(data)
        return data


def _save_backlog(data: dict) -> None:
    """Atomically write backlog.json."""
    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BACKLOG_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.replace(BACKLOG_FILE)


def _format_backlog_for_display(backlog: list[dict]) -> str:
    """Format backlog entries as a compact numbered list for session start output."""
    if not backlog:
        return ""
    lines: list[str] = []
    for i, entry in enumerate(backlog, 1):
        title = entry.get("title", "(untitled)")
        desc = entry.get("description", "")
        files = entry.get("files", [])
        added = entry.get("added", "")[:10]  # date only
        line = f"  [{i}] {title}"
        if added:
            line += f"  ({added})"
        lines.append(line)
        if desc:
            lines.append(f"      {desc}")
        if files:
            lines.append(f"      Files: {', '.join(files)}")
    return "\n".join(lines)


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


def _prefetch_debug_context_summary(subcommand: str, entity_id: str, label: str) -> str:
    """Run a debug.py subcommand with --summary flag for condensed inline output.

    Falls back to full output if --summary is not supported.
    """
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        subcommand, entity_id, "--summary",
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        # Fall back to full output if --summary not supported or failed
        return _prefetch_debug_context(subcommand, entity_id, label)
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


def _prefetch_health_check() -> str:
    """Run the debug health check and return output for session start context."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "health",
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=45)
    if rc != 0 or not stdout.strip():
        err = (stderr or stdout or "no output").strip()[:300]
        return f"[!] Could not run automatic debug health check: {err}\n    (Is the api container running?)"
    return stdout.strip()


def _prefetch_health_check_compact() -> str:
    """Run a compact health check — returns a one-liner pass/fail summary."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "health", "--compact",
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        return "Health: UNKNOWN (could not reach api container)"
    return stdout.strip()


def _prefetch_recent_issues(limit: int = 2) -> str:
    """Fetch the most recent user-reported issues in compact format."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "issue", "--list", "--compact", "--list-limit", str(limit),
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        return "  (could not fetch recent issues)"
    return stdout.strip()


def _prefetch_error_overview(since_minutes: int = 30) -> str:
    """Fetch a compact error/warning overview for both dev and production servers.

    Combines dev (local OpenObserve + Redis fingerprints) and prod
    (Admin Debug API /errors) into a single block.
    """
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "errors", "--compact", "--top", "5", "--since", str(since_minutes),
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=45)
    if rc != 0 or not stdout.strip():
        return "  (could not fetch error overview)"
    return stdout.strip()


def _prefetch_vercel_status() -> str:
    """Fetch the latest Vercel deployment status and errors/warnings.

    Runs debug_vercel.py directly (not via Docker) since it only needs
    VERCEL_TOKEN and the .vercel/project.json file from the local repo.
    """
    script = str(PROJECT_ROOT / "backend" / "scripts" / "debug_vercel.py")
    cmd = ["python3", script]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        err_hint = (stderr or "no output").strip()[:200]
        return f"  (could not fetch Vercel status: {err_hint})"
    # Strip ANSI escape codes for clean box output
    ansi_re = re.compile(r'\x1b\[[0-9;]*m')
    clean = ansi_re.sub('', stdout.strip())
    return clean


def _prefetch_vercel_status_oneliner() -> str:
    """Return a single-line Vercel deployment status for HEALTH box (bug mode).

    Returns e.g. "✓ Ready (a5449792)" or "✗ ERROR (dpl_Bh9Wcq...)" or "" on failure.
    Much faster than the full _prefetch_vercel_status since it only needs the
    latest deployment status, not the full build log.
    """
    script = str(PROJECT_ROOT / "backend" / "scripts" / "debug_vercel.py")
    if not os.path.exists(script):
        return ""
    cmd = ["python3", script, "--status-only"]
    rc, stdout, stderr = _run_cmd(cmd, timeout=15)
    if rc != 0 or not stdout.strip():
        return ""
    # Strip ANSI codes
    ansi_re = re.compile(r'\[[0-9;]*m')
    line = ansi_re.sub('', stdout.strip()).split("\n")[0].strip()

    return line


def _prefetch_user_context(email: str) -> str:
    """Fetch user data with session context (10 chats, 20 embeds)."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "user", email, "--session-context",
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=45)
    if rc != 0 or not stdout.strip():
        err = (stderr or stdout or "no output").strip()[:300]
        return f"[!] Could not fetch user data for {email}: {err}"
    return stdout.strip()


def _prefetch_debug_session_logs(debug_id: str) -> str:
    """Fetch logs tagged with a user debug session ID."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "logs", "--debug-id", debug_id,
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=45)
    if rc != 0 or not stdout.strip():
        err = (stderr or stdout or "no output").strip()[:300]
        return f"[!] Could not fetch logs for debug session {debug_id}: {err}"
    return stdout.strip()


def _prefetch_test_run(run_id: str) -> str:
    """Load context for a specific daily test run by its run ID prefix.

    Scans daily-run-*.json files for a matching run_id, then summarizes
    the run and fetches OpenObserve logs for failing specs via debug-id.
    """
    results_dir = PROJECT_ROOT / "test-results"
    if not results_dir.exists():
        return "  (test-results/ directory not found)"

    # Find matching daily run file
    matched_data = None
    for f in sorted(results_dir.glob("daily-run-*.json"), reverse=True):
        try:
            with open(f) as fh:
                data = json.load(fh)
            if data.get("run_id", "").startswith(run_id):
                matched_data = data
                break
        except (json.JSONDecodeError, OSError):
            continue

    if not matched_data:
        return f"  No daily run found matching run ID prefix: {run_id}"

    # Build summary
    lines: list[str] = []
    run_id_full = matched_data.get("run_id", "?")
    sha = str(matched_data.get("git_sha", "?"))[:9]
    duration = matched_data.get("duration_seconds", 0)
    summary = matched_data.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    not_started = summary.get("not_started", 0)

    lines.append(f"Run: {run_id_full}  Commit: {sha}  Duration: {duration}s")
    lines.append(f"Results: {passed}/{total} passed, {failed} failed, {not_started} not started")

    # List failing tests per suite
    failed_specs: list[str] = []
    suites = matched_data.get("suites", {})
    for suite_name, suite_data in suites.items():
        # Tests can be a list (playwright, pytest) or dict (legacy)
        tests = suite_data.get("tests", suite_data.get("results", []))
        if isinstance(tests, list):
            for test_info in tests:
                status = test_info.get("status", "")
                name = test_info.get("file", test_info.get("name", "?"))
                if status in ("failed", "error"):
                    error_msg = test_info.get("error", "")
                    # First line of error for compact display
                    first_error = error_msg.split("\n")[0][:100] if error_msg else ""
                    lines.append(f"  FAIL [{suite_name}] {name}")
                    if first_error:
                        lines.append(f"       {first_error}")
                    failed_specs.append(name.replace(".spec.ts", ""))
        elif isinstance(tests, dict):
            for test_name, test_info in tests.items():
                status = test_info.get("status", "")
                if status in ("failed", "error"):
                    lines.append(f"  FAIL [{suite_name}] {test_name}")
                    failed_specs.append(test_name)

    if not failed_specs:
        lines.append("  All tests passed.")
    else:
        # Fetch OpenObserve logs for the first 3 failing specs
        lines.append("")
        lines.append("Failure logs (first 3):")
        for spec_name in failed_specs[:3]:
            debug_key = f"{run_id_full}-{spec_name}"
            cmd = [
                "docker", "exec", "api",
                "python", "/app/backend/scripts/debug.py",
                "logs", "--debug-id", debug_key, "--since", "120",
            ]
            rc, stdout, stderr = _run_cmd(cmd, timeout=20)
            if rc == 0 and stdout.strip():
                # Show first 5 lines of logs per spec
                log_lines = stdout.strip().split("\n")[:5]
                lines.append(f"  [{spec_name}]")
                for ll in log_lines:
                    lines.append(f"    {ll}")
            else:
                lines.append(f"  [{spec_name}] (no debug logs found)")

    return "\n".join(lines)


RESULTS_DIR = PROJECT_ROOT / "test-results"
E2E_SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"

# Filename prefix patterns → category for E2E spec inventory.
# Order matters: first match wins. Keep specific prefixes before generic ones.
E2E_SPEC_CATEGORIES: list[tuple[str, list[str]]] = [
    ("Auth & Signup", [
        "account-recovery", "backup-code", "backup-codes", "multi-session",
        "recovery-key", "signup-flow", "signup-skip",
    ]),
    ("Chat", [
        "background-chat", "chat-flow", "chat-management", "chat-scroll",
        "chat-search", "daily-inspiration", "fork-conversation", "hidden-chats",
        "import-chats", "message-sync",
    ]),
    ("Payment", [
        "buy-credits", "saved-payment", "settings-buy-credits",
    ]),
    ("Search & AI", [
        "code-generation", "focus-mode", "follow-up", "travel-search",
        "web-search",
    ]),
    ("Media & Embeds", [
        "audio-recording", "embed-", "file-attachment", "pdf-flow",
    ]),
    ("Settings & Security", [
        "api-keys", "incognito-mode", "language-settings", "location-",
        "mention-dropdown", "model-override", "pii-detection",
    ]),
    ("Infrastructure", [
        "app-load", "connection-resilience", "dev-preview", "preview-error",
        "seo-demo", "shared-chat",
    ]),
    ("Reminders", [
        "reminder-",
    ]),
]


def _prefetch_test_summary() -> str:
    """Build a compact summary of the last test run + daily trend from result JSON files.

    Reads test-results/last-run.json for the most recent run details, and the
    last 5 daily-run-*.json archives for the trend view.
    """
    lines: list[str] = []

    # ── Last run summary ───────────────────────────────────────────────────
    last_run_file = RESULTS_DIR / "last-run.json"
    if last_run_file.exists():
        try:
            with open(last_run_file) as f:
                data = json.load(f)
            run_id = data.get("run_id", "?")
            git_sha = data.get("git_sha", "?")
            git_branch = data.get("git_branch", "?")
            duration = data.get("duration_seconds", 0)
            summary = data.get("summary", {})
            total = summary.get("total", 0)
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            skipped = summary.get("skipped", 0)
            not_started = summary.get("not_started", 0)

            lines.append(f"Run: {run_id}  Git: {git_sha} ({git_branch})  Duration: {duration}s")

            # Per-suite breakdown
            for suite_name in ("vitest", "pytest_unit", "pytest_integration", "playwright"):
                suite = data.get("suites", {}).get(suite_name, {})
                if not isinstance(suite, dict):
                    continue
                status = suite.get("status", "skipped")
                if status == "skipped":
                    reason = suite.get("reason", "")
                    lines.append(f"  {suite_name}: skipped ({reason})" if reason else f"  {suite_name}: skipped")
                    continue
                s_dur = suite.get("duration_seconds", 0)
                tests = suite.get("tests", [])
                s_passed = sum(1 for t in tests if t.get("status") == "passed")
                s_failed = sum(1 for t in tests if t.get("status") == "failed")
                s_not_started = sum(1 for t in tests if t.get("status") == "not_started")
                parts = [f"{s_passed} passed", f"{s_failed} failed"]
                if s_not_started:
                    parts.append(f"{s_not_started} not started")
                lines.append(f"  {suite_name}: {', '.join(parts)} ({s_dur}s)")

            lines.append(f"  Total: {total} tests, {passed} passed, {failed} failed, {skipped} skipped, {not_started} not started")

            # Failed tests
            failed_tests: list[str] = []
            for suite_name, suite_data in data.get("suites", {}).items():
                if not isinstance(suite_data, dict):
                    continue
                for t in suite_data.get("tests", []):
                    if t.get("status") == "failed":
                        name = t.get("file", t.get("name", "?"))
                        error = (t.get("error", "") or "")[:100]
                        # Strip ANSI escape codes for readability
                        error = re.sub(r"\x1b\[[0-9;]*m", "", error).strip()
                        failed_tests.append(f"    [{suite_name}] {name}: {error}")

            if failed_tests:
                lines.append(f"  Failed tests ({len(failed_tests)}):")
                for ft in failed_tests[:10]:
                    lines.append(ft)
                if len(failed_tests) > 10:
                    lines.append(f"    ... and {len(failed_tests) - 10} more")
        except (json.JSONDecodeError, OSError, KeyError) as e:
            lines.append(f"  [!] Could not parse last-run.json: {e}")
    else:
        lines.append("  No test results found (test-results/last-run.json missing)")

    # ── Daily run trend ────────────────────────────────────────────────────
    daily_files = sorted(
        RESULTS_DIR.glob("daily-run-*.json"),
        key=lambda p: p.name,
        reverse=True,
    )[:5]

    if daily_files:
        lines.append("")
        lines.append("Daily run trend (last 5):")
        for df in daily_files:
            try:
                with open(df) as f:
                    d = json.load(f)
                date = df.stem.replace("daily-run-", "")
                sha = str(d.get("git_sha", "?"))[:9]
                s = d.get("summary", {})
                total = s.get("total", 0)
                passed = s.get("passed", 0)
                failed = s.get("failed", 0)
                ns = s.get("not_started", 0)
                icon = "+" if failed == 0 else "x"
                ns_str = f", {ns} not started" if ns else ""
                lines.append(f"  {icon} {date}  {sha}  {passed}/{total} passed, {failed} failed{ns_str}")
            except (json.JSONDecodeError, OSError):
                lines.append(f"  ? {df.name}: could not parse")

    return "\n".join(lines)


def _get_skill_test_coverage() -> str:
    """Scan app skills and REST/CLI tests to show which skills lack test coverage.

    Returns a formatted string listing:
      - App skills with REST API tests
      - App skills with CLI E2E tests
      - App skills with NO tests (gap overview)

    Reads:
      - backend/apps/*/skills/ for implemented (non-stub) skills
      - backend/tests/test_rest_api_*.py for REST API test function names
      - frontend/apps/web_app/tests/cli-*.spec.ts for CLI test coverage

    Usage:
      python3 scripts/sessions.py context --doc skill-coverage
    """
    import re as _re

    apps_dir = PROJECT_ROOT / "backend" / "apps"
    backend_tests_dir = PROJECT_ROOT / "backend" / "tests"
    e2e_tests_dir = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"

    # --- Collect implemented skills (have a non-stub .py file with execute()) ---
    implemented: dict[str, list[str]] = {}  # app_id -> [skill_id, ...]

    def _skill_id_from_file(stem: str) -> str:
        """Convert file stem to skill ID: remove '_skill' suffix, underscores to hyphens."""
        return stem.replace("_skill", "").replace("_", "-")

    for app_dir in sorted(apps_dir.iterdir()):
        if not app_dir.is_dir() or app_dir.name.startswith("_"):
            continue
        skills_dir = app_dir / "skills"
        if not skills_dir.exists():
            continue
        skill_files = [
            f for f in skills_dir.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        ]
        app_id = app_dir.name
        skills = []
        for sf in sorted(skill_files):
            try:
                text = sf.read_text(errors="replace")
                if "def execute(" in text or "async def execute(" in text:
                    skills.append(_skill_id_from_file(sf.stem))
            except OSError:
                pass
        if skills:
            implemented[app_id] = skills

    # --- REST API test coverage ---
    # Strategy: extract all test function names, then match app+skill substrings.
    # Also handle special cases: "lifecycle" tests cover multiple skills of an app.
    rest_tested: set[str] = set()

    # Explicit REST API skill endpoint URLs (most reliable)
    rest_endpoint_pattern = _re.compile(
        r'/v1/apps/([a-z_-]+)/skills/([a-z_-]+)'
    )

    if backend_tests_dir.exists():
        for tf in backend_tests_dir.glob("test_rest_api_*.py"):
            try:
                text = tf.read_text(errors="replace")

                # Primary: parse actual endpoint URLs called in test bodies
                for m in rest_endpoint_pattern.finditer(text):
                    app_id = m.group(1).replace("-", "_")
                    skill_id = m.group(2)
                    if app_id in implemented:
                        # Normalize skill_id to match our skill naming
                        for sk in implemented[app_id]:
                            sk_norm = sk.replace("-", "_")
                            skill_norm = skill_id.replace("-", "_")
                            if sk_norm == skill_norm or sk_norm in skill_norm or skill_norm in sk_norm:
                                rest_tested.add(f"{app_id}/{sk}")
            except OSError:
                pass

    # --- CLI E2E test coverage ---
    cli_tested_apps: set[str] = set()  # apps fully covered by CLI spec
    cli_tested: set[str] = set()       # individual "app/skill" pairs

    if e2e_tests_dir.exists():
        for sf in e2e_tests_dir.glob("cli-*.spec.ts"):
            try:
                text = sf.read_text(errors="replace")

                # Look for CLI skill invocations: apps <app> <skill>
                for app_id in implemented:
                    for sk in implemented[app_id]:
                        # Check if spec explicitly invokes this skill via CLI
                        if (f"'apps', '{app_id}'" in text or
                                ("\"apps\", \"" + app_id + "\""  in text) or
                                f"apps {app_id}" in text):
                            if (f"'{sk}'" in text or f'"{sk}"' in text or
                                    sk.replace("-", "_") in text):
                                cli_tested.add(f"{app_id}/{sk}")

                # --app-id <app> → memories/settings tests cover the whole app
                for m in _re.finditer(r'--app-id[\s,]+([a-z][a-z_-]+)', text):
                    app_id = m.group(1).replace("-", "_")
                    if app_id in implemented:
                        cli_tested_apps.add(app_id)

                # Detect app coverage from spec filename and content
                # cli-images.spec.ts → images app coverage
                spec_stem = sf.stem.replace(".spec", "")
                for app_id in implemented:
                    if app_id in spec_stem:
                        cli_tested_apps.add(app_id)

                # cli-skills-pdf.spec.ts → pdf app coverage
                if "pdf" in spec_stem:
                    cli_tested_apps.add("pdf")

            except OSError:
                pass

    # --- Build coverage table ---
    covered_lines: list[str] = []
    no_coverage: list[str] = []

    for app_id in sorted(implemented):
        for skill in implemented[app_id]:
            key = f"{app_id}/{skill}"
            has_rest = key in rest_tested
            has_cli = key in cli_tested or app_id in cli_tested_apps
            if has_rest and has_cli:
                status = "REST+CLI"
            elif has_rest:
                status = "REST"
            elif has_cli:
                status = "CLI"
            else:
                no_coverage.append(key)
                continue
            covered_lines.append(f"  {key:<42} [{status}]")

    total_skills = sum(len(v) for v in implemented.values())
    result_lines = [
        f"Implemented skills: {total_skills} across {len(implemented)} apps",
        f"With tests: {len(covered_lines)}  |  No tests: {len(no_coverage)}",
        "",
    ]

    if no_coverage:
        result_lines.append("GAPS — skills with no test coverage:")
        for key in sorted(no_coverage):
            result_lines.append(f"  {key}")
        result_lines.append("")

    if covered_lines:
        result_lines.append("Covered skills:")
        result_lines.extend(covered_lines)

    return "\n".join(result_lines)


def _get_e2e_spec_categories() -> str:
    """Scan tests/*.spec.ts and return a categorized inventory summary.

    Groups spec files by filename prefix into categories defined in
    E2E_SPEC_CATEGORIES. Specs that don't match any category go into 'Other'.
    """
    if not E2E_SPEC_DIR.exists():
        return "  E2E spec directory not found"

    spec_files = sorted(
        f.stem.replace(".spec", "")
        for f in E2E_SPEC_DIR.glob("*.spec.ts")
    )
    if not spec_files:
        return "  No E2E spec files found"

    categorized: dict[str, list[str]] = {}
    uncategorized: list[str] = []

    for spec in spec_files:
        matched = False
        for cat_name, prefixes in E2E_SPEC_CATEGORIES:
            for prefix in prefixes:
                if spec.startswith(prefix):
                    categorized.setdefault(cat_name, []).append(spec)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            uncategorized.append(spec)

    lines: list[str] = []
    for cat_name, _ in E2E_SPEC_CATEGORIES:
        specs = categorized.get(cat_name, [])
        if specs:
            names = ", ".join(specs)
            lines.append(f"  {cat_name} ({len(specs)}): {names}")

    if uncategorized:
        names = ", ".join(uncategorized)
        lines.append(f"  Other ({len(uncategorized)}): {names}")

    return "\n".join(lines)


def _prefetch_test_events_o2() -> str:
    """Fetch recent test lifecycle events from OpenObserve via the test-events preset."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "logs", "--o2", "--preset", "test-events", "--since", "120",
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        err = (stderr or "no output").strip()[:200]
        return f"  (could not fetch test events from OpenObserve: {err})"
    return stdout.strip()


def _classify_uncommitted_files(uncommitted: list[str]) -> dict[str, list[str]]:
    """Classify uncommitted files into area buckets for compact display."""
    areas: dict[str, list[str]] = {"frontend": [], "backend": [], "docs": [], "other": []}
    for entry in uncommitted:
        # entry is like "M path/to/file" or "?? path/to/file"
        path = entry.split(" ", 1)[-1] if " " in entry else entry
        if path.startswith("frontend/"):
            areas["frontend"].append(entry)
        elif path.startswith("backend/"):
            areas["backend"].append(entry)
        elif path.startswith("docs/"):
            areas["docs"].append(entry)
        else:
            areas["other"].append(entry)
    return {k: v for k, v in areas.items() if v}


def _format_relative_time(time_str: str) -> str:
    """Convert git relative time strings to compact format: '3 hours ago' -> '3h'."""
    time_str = time_str.replace(" ago", "")
    replacements = [
        (" hours", "h"), (" hour", "h"),
        (" minutes", "m"), (" minute", "m"),
        (" seconds", "s"), (" second", "s"),
        (" days", "d"), (" day", "d"),
        (" weeks", "w"), (" week", "w"),
        (" months", "mo"), (" month", "mo"),
    ]
    for old, new in replacements:
        time_str = time_str.replace(old, new)
    return time_str



# ---------------------------------------------------------------------------
# Box-drawing section formatting
# ---------------------------------------------------------------------------

BOX_WIDTH = 72  # Total width of box-drawing sections


def _box_section(title: str, lines: list[str]) -> str:
    """Format a section with Unicode box-drawing characters for visual clarity.

    Example:
        ┌─ HEALTH ─────────────────────────────────────────────────────────┐
          OK (0% API errors, P95 42ms, queues clear, 0 app errors)
        └───────────────────────────────────────────────────────────────────┘
    """
    # Build top border: ┌─ TITLE ─...─┐
    inner_width = BOX_WIDTH - 2  # minus ┌ and ┐
    title_part = f"─ {title} "
    remaining = inner_width - len(title_part)
    top = "┌" + title_part + "─" * max(0, remaining) + "┐"
    bottom = "└" + "─" * inner_width + "┘"

    section_lines = [top]
    for line in lines:
        section_lines.append(f"  {line}")
    section_lines.append(bottom)
    return "\n".join(section_lines)


def _prefetch_recent_errors_timeline() -> str:
    """Fetch the last 10 actual error/warning log lines from OpenObserve.

    Returns formatted timeline of recent errors for bug mode auto-include.
    Queries both backend service errors and browser console errors.
    Extracts the human-readable message from JSON-structured log lines.
    """
    # Write a temp script file for docker exec to avoid quoting issues
    import tempfile
    script_content = """
import asyncio, json, sys
sys.path.insert(0, '/app/backend/scripts')
from debug_health import _openobserve_recent_errors

def extract_msg(raw):
    if not raw:
        return '?'
    raw = str(raw).strip()
    if raw.startswith('{'):
        try:
            d = json.loads(raw)
            msg = d.get('message') or d.get('msg') or d.get('error') or raw
            name = d.get('name', '')
            if name:
                parts = name.split('.')
                name = '.'.join(parts[-2:]) if len(parts) > 3 else name
                return f'[{name}] {msg}'
            return str(msg)
        except (json.JSONDecodeError, ValueError):
            pass
    return raw

async def main():
    errors = await _openobserve_recent_errors(limit=10, since_minutes=15)
    if not errors:
        print('No errors in the last 15 minutes')
        return
    from datetime import datetime
    for e in errors:
        ts_us = e.get('ts', 0) // 1000
        if ts_us > 0:
            dt = datetime.fromtimestamp(ts_us / 1_000_000)
            time_str = dt.strftime('%H:%M:%S')
        else:
            time_str = '??:??:??'
        svc = (e.get('service') or '?')[:14].ljust(14)
        msg = extract_msg(e.get('message', '?'))[:100]
        print(f'{time_str}  [{svc}] {msg}')
    print(f'-> {len(errors)} error(s) in last 15 min | Full: debug.py logs --o2 --preset top-warnings-errors')

asyncio.run(main())
"""
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', prefix='o2_errors_',
        dir=str(PROJECT_ROOT / "backend" / "scripts"),
        delete=False,
    )
    tmp.write(script_content)
    tmp_path = tmp.name
    tmp.close()

    try:
        # Map the host path to the container path
        container_path = tmp_path.replace(str(PROJECT_ROOT), '/app')
        cmd = ["docker", "exec", "api", "python", container_path]
        rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    if rc != 0 or not stdout.strip():
        return "(could not fetch recent errors from OpenObserve)"
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
    if getattr(args, "user", None):
        extra_tags += ["debug"]
    if getattr(args, "debug_id", None):
        extra_tags += ["debug"]
    if getattr(args, "vercel", False):
        extra_tags += ["debug"]
    if getattr(args, "run_id", None):
        extra_tags += ["test", "debug"]
    for et in extra_tags:
        if et not in tags:
            tags.append(et)

    mode = args.mode

    task_id_arg = getattr(args, "task_id", None)

    # Register session
    session_record: dict = {
        "task": args.task or "(pending)",
        "mode": mode,
        "tags": tags,
        "started": _now_iso(),
        "last_active": _now_iso(),
        "modified_files": [],
        "writing": None,
        "task_id": task_id_arg,
    }
    data["sessions"][sid] = session_record

    # Link task file to this session if --task-id was given
    if task_id_arg:
        linked_task = _load_task(task_id_arg)
        if linked_task:
            linked_task["session"] = sid
            _save_task(linked_task)
        else:
            print(f"Warning: --task-id {task_id_arg!r} not found; ignoring.", file=sys.stderr)
            task_id_arg = None
            data["sessions"][sid]["task_id"] = None

    _save_sessions(data)

    # ===================================================================
    # Output context for Claude (mode-aware, structured with box sections)
    # ===================================================================

    # ── Warn if workflow scripts themselves are modified but untracked ─────
    dirty_set = _get_dirty_files()
    workflow_dirty = [
        f for f in dirty_set
        if f in ("scripts/sessions.py",
                 "backend/scripts/debug.py",
                 "backend/scripts/debug_health.py",
                 "backend/scripts/debug_issue.py",
                 "backend/scripts/debug_logs.py",
                 "backend/scripts/debug_vercel.py")
    ]
    # Check against all sessions (not just this one) to see if any session owns them
    owned_by = {}
    for other_sid, other_info in data.get("sessions", {}).items():
        if other_sid == sid:
            continue
        for wf in workflow_dirty:
            if wf in other_info.get("modified_files", []):
                owned_by[wf] = other_sid

    # ── Header block ──────────────────────────────────────────────────────
    git_status = _get_git_status_summary()
    branch_info = git_status["branch"]
    if git_status["tracking"]:
        branch_info += f" ({git_status['tracking']})"
    uncommitted = git_status.get("uncommitted", [])

    header_lines = [
        f"  Mode:  {mode}",
        f"  Tags:  {', '.join(tags) if tags else 'none'}",
        f"  Task:  {args.task or '(pending)'}",
    ]

    # Git status line
    if mode in ("feature", "bug", "testing"):
        if uncommitted:
            areas = _classify_uncommitted_files(uncommitted)
            area_summary = ", ".join(f"{len(v)} {k}" for k, v in areas.items())
            header_lines.append(f"  Git:   {branch_info} | {len(uncommitted)} uncommitted [{area_summary}]")
        else:
            header_lines.append(f"  Git:   {branch_info} | clean")
    else:
        header_lines.append(f"  Git:   {branch_info}")

    # Recent commits — table layout: SHA  AGE   FULL TITLE (no truncation)
    if mode != "question":
        commit_limit = RECENT_COMMITS_COUNT if mode == "feature" else 3
        recent_commits = _get_recent_commits(count=commit_limit)
        if recent_commits:
            # Parse all rows first so we can align columns
            rows = []
            for commit_line in recent_commits:
                parts = commit_line.split(" ", 1)
                sha = parts[0]
                rest = parts[1] if len(parts) > 1 else ""
                time_str = ""
                msg = rest
                for marker in (" ago ",):
                    idx = rest.find(marker)
                    if idx >= 0:
                        time_str = _format_relative_time(rest[:idx + len(marker)].strip())
                        msg = rest[idx + len(marker):]
                        break
                rows.append((sha, time_str, msg))
            # Width of the widest age column for alignment
            max_age = max(len(r[1]) for r in rows) if rows else 0
            for i, (sha, age, msg) in enumerate(rows):
                prefix = "  Last:" if i == 0 else "       "
                age_padded = age.ljust(max_age)
                header_lines.append(f"{prefix}  {sha}  {age_padded}  {msg}")

    # Print header — include backlog count if any items pending
    backlog_count = len(_load_backlog().get("backlog", []))
    backlog_suffix = f" [{backlog_count} backlog]" if backlog_count > 0 else ""
    hdr_bar = "═" * (BOX_WIDTH - len(f"== SESSION {sid} ") - len(backlog_suffix) - 1)
    print(f"== SESSION {sid} {hdr_bar}{backlog_suffix}")
    print("\n".join(header_lines))
    print("═" * BOX_WIDTH)

    # ── Workflow script modification notice ────────────────────────────────
    if workflow_dirty:
        for wf in workflow_dirty:
            owner = owned_by.get(wf)
            if owner:
                print(
                    f"NOTICE: {wf} has uncommitted changes (tracked by session {owner}). "
                    f"Run: sessions.py status"
                )
            else:
                print(
                    f"NOTICE: {wf} has uncommitted changes not tracked by any session. "
                    f"Use: sessions.py track --session {sid} --file {wf}"
                )

    # ── Collect boxed sections ────────────────────────────────────────────
    sections: list[str] = []

    # ── HEALTH (bug handled specially below with Vercel; feature, testing normal) ─
    if mode in ("feature", "testing"):
        health_line = _prefetch_health_check_compact()
        sections.append(_box_section("HEALTH", [health_line]))

    # ── HEALTH + VERCEL one-liner (bug mode only) ─────────────────────────
    if mode == "bug":
        health_line = _prefetch_health_check_compact()
        health_lines = [health_line]
        # Only show Vercel inline if user didn't request full Vercel box
        if not getattr(args, "vercel", False):
            vercel_oneliner = _prefetch_vercel_status_oneliner()
            if vercel_oneliner:
                health_lines.append(f"Vercel: {vercel_oneliner}")
        sections.append(_box_section("HEALTH", health_lines))

    # ── RECENT ERRORS — auto-included in bug mode ────────────────────────
    if mode == "bug":
        errors_content = _prefetch_recent_errors_timeline()
        sections.append(_box_section("RECENT ERRORS (last 15min)", errors_content.split("\n")))

    # ── ISSUES (bug mode) ─────────────────────────────────────────────────
    if mode == "bug":
        issues_content = _prefetch_recent_issues(limit=2)
        sections.append(_box_section("ISSUES (last 24h)", issues_content.split("\n")))

    # ── ERROR TRENDS (bug mode) ───────────────────────────────────────────
    if mode == "bug":
        error_since = getattr(args, "error_since", 7)
        trends_content = _prefetch_error_overview(since_minutes=error_since * 24 * 60)
        sections.append(_box_section("ERROR TRENDS (7d, dev + prod)", trends_content.split("\n")))

    # ── TEST RESULTS (testing mode) ───────────────────────────────────────
    if mode == "testing":
        test_content = _prefetch_test_summary()
        sections.append(_box_section("TEST RESULTS", test_content.split("\n")))
        events_content = _prefetch_test_events_o2()
        sections.append(_box_section("TEST EVENTS (2h)", events_content.split("\n")))

    # ── E2E spec inventory (testing mode) ─────────────────────────────────
    if mode == "testing":
        spec_count = len(list(E2E_SPEC_DIR.glob("*.spec.ts"))) if E2E_SPEC_DIR.exists() else 0
        spec_lines = [f"Total: {spec_count} specs"]
        spec_lines.extend(_get_e2e_spec_categories().split("\n"))
        sections.append(_box_section("E2E SPECS", spec_lines))

    # ── Skill test coverage gaps (testing + debug mode) ───────────────────
    if mode in ("testing", "bug"):
        coverage_lines = _get_skill_test_coverage().split("\n")
        sections.append(_box_section("SKILL TEST COVERAGE", coverage_lines))

    # ── Explicit prefetch flags (all modes — user explicitly requested) ────
    issue_id = getattr(args, "issue", None)
    if issue_id:
        # Use --summary for inline context (condensed), not full report
        issue_content = _prefetch_debug_context_summary("issue", issue_id, "issue")
        sections.append(_box_section(f"ISSUE {issue_id[:12]}", issue_content.split("\n")))

    chat_id = getattr(args, "chat", None)
    if chat_id:
        chat_content = _prefetch_debug_context("chat", chat_id, "chat")
        sections.append(_box_section(f"CHAT {chat_id[:12]}", chat_content.split("\n")))

    embed_id = getattr(args, "embed", None)
    if embed_id:
        embed_content = _prefetch_debug_context("embed", embed_id, "embed")
        sections.append(_box_section(f"EMBED {embed_id[:12]}", embed_content.split("\n")))

    logs_opts = getattr(args, "logs", None)
    if logs_opts is not None:
        logs_content = _prefetch_logs(logs_opts or "since=10")
        sections.append(_box_section(f"LOGS ({logs_opts or 'since=10'})", logs_content.split("\n")))

    user_email = getattr(args, "user", None)
    if user_email:
        user_content = _prefetch_user_context(user_email)
        sections.append(_box_section(f"USER {user_email}", user_content.split("\n")))

    debug_id = getattr(args, "debug_id", None)
    if debug_id:
        debug_content = _prefetch_debug_session_logs(debug_id)
        sections.append(_box_section(f"DEBUG SESSION {debug_id}", debug_content.split("\n")))

    vercel_flag = getattr(args, "vercel", False)
    if vercel_flag:
        vercel_content = _prefetch_vercel_status()
        sections.append(_box_section("VERCEL (latest deployment)", vercel_content.split("\n")))

    run_id = getattr(args, "run_id", None)
    if run_id:
        run_content = _prefetch_test_run(run_id)
        sections.append(_box_section(f"TEST RUN {run_id[:20]}", run_content.split("\n")))

    # ── Since last deploy (explicit flag) ────────────────────────────────────
    if getattr(args, "since_last_deploy", False):
        last_sha = _load_last_deploy_sha()
        if last_sha:
            since_commits = _get_commits_since_sha(last_sha)
            if since_commits:
                # Build aligned table
                rows = []
                for cl in since_commits:
                    parts = cl.split(" ", 1)
                    sha = parts[0]
                    rest = parts[1] if len(parts) > 1 else ""
                    time_str = ""
                    msg = rest
                    for marker in (" ago ",):
                        idx = rest.find(marker)
                        if idx >= 0:
                            time_str = _format_relative_time(rest[:idx + len(marker)].strip())
                            msg = rest[idx + len(marker):]
                            break
                    rows.append((sha, time_str, msg))
                max_age = max(len(r[1]) for r in rows) if rows else 0
                since_lines = [f"Since last deploy ({last_sha[:9]}): {len(rows)} commit(s)"]
                for sha, age, msg in rows:
                    since_lines.append(f"  {sha}  {age.ljust(max_age)}  {msg}")
                # Also show changed files since last deploy
                rc, diff_out, _ = _run_cmd(["git", "diff", "--name-status", f"{last_sha}..HEAD"])
                if rc == 0 and diff_out:
                    since_lines.append("")
                    since_lines.append("Files changed:")
                    for line in diff_out.splitlines()[:20]:
                        since_lines.append(f"  {line}")
                    if len(diff_out.splitlines()) > 20:
                        since_lines.append(f"  ... +{len(diff_out.splitlines()) - 20} more")
                sections.append(_box_section("SINCE LAST DEPLOY", since_lines))
            else:
                sections.append(_box_section("SINCE LAST DEPLOY",
                    [f"No commits since last deploy ({last_sha[:9]}) — working tree is current."]))
        else:
            sections.append(_box_section("SINCE LAST DEPLOY",
                ["No previous deploy found in this project. Last deploy SHA will be recorded after first sessions.py deploy."]))

    # Print all boxed sections
    if sections:
        print()
        print("\n\n".join(sections))

    # ── Active sessions / locks ───────────────────────────────────────────
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

    session_lines = []
    for osid, info in other_sessions.items():
        files_str = ""
        if info.get("writing"):
            files_str = f" [WRITING: {info['writing']}]"
        elif info.get("modified_files"):
            files_str = f" [{len(info['modified_files'])} files]"
        tags_str = f" ({','.join(info['tags'])})" if info.get("tags") else ""
        task_lnk = f" [task:{info['task_id']}]" if info.get("task_id") else ""
        session_lines.append(f"{osid}: {info.get('task', '?')[:55]}{tags_str}{task_lnk}{files_str}")

    locks = data.get("locks", {})
    active_locks = [
        lt for lt, lv in locks.items() if lv.get("status") == "IN_PROGRESS"
    ]
    for lt in active_locks:
        lv = locks[lt]
        session_lines.append(f"LOCK: {lt} held by {lv.get('claimed_by', '?')}")

    if session_lines:
        print()
        print(_box_section("OTHER SESSIONS", session_lines))

    # ── Architecture docs (bug mode now included, with tag filtering) ─────
    if mode in ("feature", "docs", "bug"):
        arch_index = _get_arch_doc_index()
        if arch_index and tags:
            filter_keywords = set()
            for tag in tags:
                filter_keywords.update(TAG_TO_ARCH_KEYWORDS.get(tag, []))
                filter_keywords.add(tag)

            relevant_docs = [
                e for e in arch_index
                if any(kw in e["name"].lower() or kw in (e.get("description", "") or "").lower()
                       for kw in filter_keywords)
            ]
            other_count = len(arch_index) - len(relevant_docs)
            if relevant_docs:
                limit = 5 if mode in ("feature", "bug") else len(relevant_docs)
                shown = relevant_docs[:limit]
                names = ", ".join(e["name"] for e in shown)
                extra = ""
                if len(relevant_docs) > len(shown):
                    extra = f", +{len(relevant_docs) - len(shown)} more"
                print()
                print(f"Arch docs ({len(relevant_docs)} relevant, {other_count} others): {names}{extra}")
                print("  Load: sessions.py context --doc <name>")
        elif mode == "docs" and arch_index:
            print()
            names = ", ".join(e["name"] for e in arch_index[:10])
            if len(arch_index) > 10:
                names += f", +{len(arch_index) - 10} more"
            print(f"Arch docs ({len(arch_index)}): {names}")
            print("  Load: sessions.py context --doc <name>")

    # ── Stale docs hint (feature/docs/bug, max 3) ─────────────────────────
    if mode in ("feature", "docs", "bug"):
        stale = _check_stale_docs()
        if stale and tags:
            relevant_stale = [
                s for s in stale
                if any(tag in ARCH_DOC_DESCRIPTIONS.get(s["doc"].replace(".md", ""), "").lower()
                       or tag in s["doc"].replace(".md", "")
                       for tag in tags)
            ]
            stale = relevant_stale
        if stale:
            shown = stale[:3]
            print()
            print(f"Stale docs ({len(stale)}):")
            for s in shown:
                print(f"  {s['doc']} (doc: {s['doc_modified']}, code: {s['code_modified']})")
            if len(stale) > 3:
                print(f"  ... {len(stale) - 3} more (run: sessions.py stale-docs)")

    # ── Project index (minimal for all modes except question) ─────────────
    if mode not in ("question", "bug"):
        index = _load_or_generate_index()
        apps = index.get("backend_apps", [])
        routes = index.get("api_routes", [])
        comps = index.get("frontend_components", [])
        print()
        print(f"Project: {len(apps)} backend apps, {len(routes)} API routes, {len(comps)} frontend component groups")

    # Cleanup report
    if pruned:
        print(f"[Pruned {len(pruned)} stale sessions]")
    if cleared_locks:
        print(f"[Cleared {len(cleared_locks)} stale locks]")

    # ── Instruction docs ───────────────────────────────────────────────────
    docs_to_load = _resolve_docs_for_tags(tags, include_deploy=False)
    if mode == "question":
        docs_to_load = docs_to_load[:2]

    if docs_to_load:
        print()
        print(f"== INSTRUCTION DOCS ({len(docs_to_load)}: {', '.join(tags)}) ==")
        for doc_name in docs_to_load:
            doc_content = _load_doc_content(doc_name)
            if doc_content:
                print(f"\n--- {doc_name} ---")
                print(doc_content.rstrip())
            else:
                print(f"  [!] docs/contributing/{doc_name} not found")
        all_possible = set()
        for tag in tags:
            all_possible.update(TAG_TO_DOCS.get(tag, []))
        deferred = sorted(all_possible & DEPLOY_PHASE_DOCS)
        if deferred:
            print(f"\n[Deferred to deploy: {', '.join(deferred)}]")

    # ── Backlog (conditional: skip in question, limit in others) ──────────
    if mode != "question":
        backlog_data = _load_backlog()
        backlog_items = backlog_data.get("backlog", [])
        if backlog_items:
            max_show = 5
            shown_items = backlog_items[:max_show]
            remaining = len(backlog_items) - max_show
            print()
            print(f"== BACKLOG ({len(backlog_items)} items) ==")
            print("Consider these backlog tasks if related or urgent (ask user first):")
            # Build a limited display
            display_lines = []
            for i, item in enumerate(shown_items, 1):
                title = item.get("title", "?")
                desc = item.get("description", "")
                files = item.get("files", [])
                line = f"  [{i}] {title}"
                if desc:
                    line += f" — {desc[:60]}{'...' if len(desc) > 60 else ''}"
                if files:
                    line += f" ({len(files)} files)"
                display_lines.append(line)
            print("\n".join(display_lines))
            if remaining > 0:
                print(f"  ... +{remaining} more (sessions.py backlog-list)")

    # ── Linked task pending steps ───────────────────────────────────────────
    if mode != "question" and task_id_arg:
        linked = _load_task(task_id_arg)
        if linked:
            plan = linked.get("plan", [])
            pending = [(i + 1, s) for i, s in enumerate(plan) if "[ ]" in s]
            ac = linked.get("acceptance_criteria", [])
            pending_ac = [(i + 1, s) for i, s in enumerate(ac) if "[ ]" in s]
            done_count = sum(1 for s in plan if "[x]" in s)
            total_count = len(plan)
            print()
            print(f"┌─ TASK {task_id_arg}: {linked.get('title', '?')} ───")
            print(f"  Status: {linked.get('status', '?')}  |  {done_count}/{total_count} steps done")
            if pending:
                print("  Pending steps:")
                for num, step in pending:
                    print(f"    [{num}] {step}")
            else:
                print("  All steps complete (or no steps defined).")
            if pending_ac:
                print("  Pending AC:")
                for num, item in pending_ac:
                    print(f"    [{num}] {item}")
            notes = linked.get("notes", "")
            if notes:
                print(f"  Notes: {notes[:120]}{'...' if len(notes) > 120 else ''}")
            print(f"  Full details: sessions.py task-show --id {task_id_arg}")
            print("└─────────────────────────────────────────────────────")

    # ── Deploy reminder (compact, 1 line) ──────────────────────────────────
    if mode != "question":
        print()
        print(f"Deploy: deploy-docs -> prepare-deploy --session {sid} -> deploy --session {sid} --title \"...\" --end")

    print()
    print("== END ==")


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
            linked_task = info.get("task_id")
            task_str = f" [task: {linked_task}]" if linked_task else ""
            print(
                f"  [{sid}] {info.get('task', '?')} "
                f"(modified: {mod_count} files){task_str}{writing_str}"
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



def _has_frontend_files(files: list) -> bool:
    """Return True if any of the given file paths touch the frontend package."""
    return any(f.startswith("frontend/") for f in files)


def _run_translation_validation() -> tuple[int, str, str]:
    """
    Run `npm run validate:locales` inside frontend/packages/ui.
    Returns (returncode, stdout, stderr).
    Only checks that every $text() key used in source files exists in en.json —
    the fast Step 4 check that guards against the Vercel build failing.
    """
    import subprocess
    result = subprocess.run(
        ["npm", "run", "validate:locales"],
        cwd=os.path.join(os.path.dirname(__file__), "..", "frontend", "packages", "ui"),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


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

    # Run translation validation if any frontend files are staged
    if to_commit and _has_frontend_files(to_commit):
        print("Running translation validation (validate:locales)...")
        rc, stdout, stderr = _run_translation_validation()
        # Only show output if there are $text() key errors (Step 4) — suppress
        # the cross-locale completeness warnings (Step 6) which are pre-existing.
        step4_error = "❌ Found" in stdout and "not found in en.json" in stdout
        if rc != 0 and step4_error:
            print("TRANSLATION ERRORS — fix before deploying:")
            # Filter to only show the relevant lines, not the cross-locale noise
            for line in stdout.splitlines():
                if "not found in en.json" in line or "$text(" in line or "❌" in line:
                    print(f"  {line}")
        elif rc != 0 and not step4_error:
            # Other error (e.g. npm not found) — show full output
            print(f"  Warning: validate:locales exited {rc} (non-key error — check manually)")
        else:
            print("Translations: PASSED")
        print()

    # Related architecture docs
    related = _find_related_docs(modified)
    if related:
        print("Architecture docs to verify:")
        for doc in related:
            print(f"  - docs/architecture/{doc}")
        print()

    # Test coverage check — warn about source files with no tests
    source_files = [
        f for f in modified
        if any(f.endswith(ext) for ext in (".py", ".ts", ".svelte"))
        and "/tests/" not in f
        and "/__tests__/" not in f
        and not Path(f).name.startswith("test_")
        and not f.endswith(".test.ts")
        and not f.endswith(".spec.ts")
    ]
    if source_files:
        untested = []
        for filepath in source_files:
            result = _find_tests_for_file(filepath)
            if not result["unit_tests"] and not result["e2e_tests"]:
                untested.append(filepath)
        if untested:
            print(f"WARNING — no tests found for {len(untested)} file(s):")
            for f in untested:
                print(f"  ? {f}")
            print("  Run: sessions.py check-tests --session <id>")
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
    dirty_but_untracked = [f for f in dirty_files if f not in modified and f not in exclude]

    if not to_commit:
        # Surface untracked dirty files so the caller knows why nothing was committed
        if dirty_but_untracked:
            print("No tracked files to commit, but these dirty files are NOT tracked by this session:", file=sys.stderr)
            for f in sorted(dirty_but_untracked):
                print(f"  ? {f}", file=sys.stderr)
            print("Run: sessions.py track --session <ID> --file <path>  to include them.", file=sys.stderr)
        else:
            print("No files to commit.")
        sys.exit(2)

    # Warn about dirty files that will be left out
    if dirty_but_untracked:
        print("Warning — dirty files NOT tracked by this session (will not be committed):")
        for f in sorted(dirty_but_untracked):
            print(f"  ? {f}")
        print()

    # 1. Run linter (with CSS/HTML support and longer timeout)
    no_verify = getattr(args, "no_verify", False)
    lint_flags = _get_lint_flags(to_commit)
    if lint_flags and not no_verify:
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
    elif lint_flags and no_verify:
        print("Lint: SKIPPED (--no-verify)")

    # 1b. Translation validation — hard-fail if any $text() key is missing from en.json
    if _has_frontend_files(to_commit):
        print("Running translation validation (validate:locales)...")
        rc, stdout, stderr = _run_translation_validation()
        step4_error = "❌ Found" in stdout and "not found in en.json" in stdout
        if rc != 0 and step4_error:
            print("TRANSLATION VALIDATION FAILED — aborting deploy:", file=sys.stderr)
            for line in stdout.splitlines():
                if "not found in en.json" in line or "$text(" in line or "❌" in line:
                    print(f"  {line}", file=sys.stderr)
            print("", file=sys.stderr)
            print("Fix: add the missing key to the correct YAML source under", file=sys.stderr)
            print("  frontend/packages/ui/src/i18n/sources/", file=sys.stderr)
            print("Then run: cd frontend/packages/ui && npm run build:translations", file=sys.stderr)
            sys.exit(1)
        elif rc != 0 and not step4_error:
            # Non-key error (e.g. npm missing) — warn but don't block
            print(f"  Warning: validate:locales exited {rc} (check manually)", file=sys.stderr)
        else:
            print("Translations: PASSED")

    # 2. Git add — reset any staged files not belonging to this session first,
    # to prevent index bleed from concurrent sessions that already ran git add.
    staged_files = _get_staged_files()
    foreign_staged = [f for f in staged_files if f not in to_commit]
    if foreign_staged:
        print(f"Unstaging {len(foreign_staged)} file(s) staged by another session...")
        rc, _, stderr = _run_cmd(["git", "reset", "HEAD"] + foreign_staged)
        if rc != 0:
            print(f"git reset failed: {stderr}", file=sys.stderr)
            sys.exit(1)

    print(f"Adding {len(to_commit)} files...")
    rc, _, stderr = _run_cmd(["git", "add"] + to_commit)
    if rc != 0:
        print(f"git add failed: {stderr}", file=sys.stderr)
        sys.exit(1)

    # 3. Git commit
    commit_msg = args.title
    if args.message:
        commit_msg += "\n\n" + args.message

    # Append task summary into the commit description if session has a linked task
    linked_task_id = session.get("task_id")
    if linked_task_id:
        linked_task = _load_task(linked_task_id)
        if linked_task:
            task_summary = linked_task.get("summary", "").strip()
            if task_summary:
                commit_msg += "\n\n" + task_summary

    no_verify = getattr(args, "no_verify", False)
    if no_verify:
        print(
            "WARNING: committing without pre-commit hooks (--no-verify). "
            "Report the hook bug as a backlog item.",
            file=sys.stderr,
        )
    commit_cmd = ["git", "commit", "-m", commit_msg]
    if no_verify:
        commit_cmd.append("--no-verify")
    print(f"Committing: {args.title}")
    rc, stdout, stderr = _run_cmd(commit_cmd)
    if rc != 0:
        print(f"git commit failed: {stderr}", file=sys.stderr)
        sys.exit(1)

    # Extract commit hash — one rev-parse call, slice for short form
    rc, commit_hash_full, _ = _run_cmd(["git", "rev-parse", "HEAD"])
    commit_hash_full = (commit_hash_full or "").strip()
    commit_hash = commit_hash_full[:7] if commit_hash_full else "unknown"

    # 4. Git push
    print("Pushing to origin dev...")
    rc, stdout, stderr = _run_cmd(["git", "push", "origin", "dev"])
    if rc != 0:
        print(f"git push failed: {stderr}", file=sys.stderr)
        print("Commit was created locally but not pushed.")
        sys.exit(1)

    # Persist last deploy SHA for --since-last-deploy
    if commit_hash_full:
        _save_last_deploy_sha(commit_hash_full.strip())

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

    # ── --list: show all available docs ───────────────────────────────────
    if getattr(args, "list", False):
        # Build reverse map: doc filename -> which tags auto-load it
        doc_to_tags: dict[str, list[str]] = {}
        for tag, docs in TAG_TO_DOCS.items():
            for doc_filename in docs:
                doc_to_tags.setdefault(doc_filename, []).append(tag)

        print("== AVAILABLE INSTRUCTION DOCS (docs/contributing/ & docs/design-guide/) ==")
        print()
        rows = []
        for search_dir, prefix in [
            (CONTRIBUTING_GUIDES_DIR, "guides/"),
            (CONTRIBUTING_STANDARDS_DIR, "standards/"),
            (DESIGN_GUIDE_DIR, "design-guide/"),
        ]:
            if not search_dir.exists():
                continue
            for f in sorted(search_dir.iterdir()):
                if f.suffix != ".md":
                    continue
                rel_key = prefix + f.name
                try:
                    lines = sum(1 for _ in open(f))
                except OSError:
                    lines = 0
                tags_that_load = doc_to_tags.get(rel_key, [])
                is_deploy = rel_key in DEPLOY_PHASE_DOCS
                tag_str = f"auto: {', '.join(tags_that_load)}" if tags_that_load else (
                    "deploy-phase" if is_deploy else "manual only")
                rows.append((rel_key, lines, tag_str))
        if rows:
            max_name = max(len(r[0]) for r in rows)
            print(f"  {'Name':<{max_name}}  {'Lines':>5}  Tags")
            print(f"  {'-' * max_name}  {'-----':>5}  ----")
            for name, lines, tag_str in rows:
                print(f"  {name:<{max_name}}  {lines:>5}  {tag_str}")
        print()
        print("== AVAILABLE ARCHITECTURE DOCS (docs/architecture/) ==")
        print()
        if ARCH_DOCS_DIR.exists():
            arch_rows = []
            for f in sorted(ARCH_DOCS_DIR.rglob("*.md")):
                if f.stem == "README":
                    continue
                try:
                    lines = sum(1 for _ in open(f))
                except OSError:
                    lines = 0
                rel = str(f.relative_to(ARCH_DOCS_DIR))
                desc = ARCH_DOC_DESCRIPTIONS.get(f.stem, "")
                arch_rows.append((rel, lines, desc))
            max_arch = max(len(r[0]) for r in arch_rows) if arch_rows else 10
            print(f"  {'Name':<{max_arch}}  {'Lines':>5}  Description")
            print(f"  {'-' * max_arch}  {'-----':>5}  -----------")
            for name, lines, desc in arch_rows:
                print(f"  {name:<{max_arch}}  {lines:>5}  {desc}")
        print()
        print("Load with: sessions.py context --doc <name>")
        return

    doc_name = args.doc
    if not doc_name:
        print("Error: provide --doc <name> or --list.", file=sys.stderr)
        sys.exit(1)

    # Built-in virtual doc: skill-coverage
    if doc_name in ("skill-coverage", "skill-test-coverage"):
        coverage = _get_skill_test_coverage()
        print("== SKILL TEST COVERAGE ==")
        print(coverage)
        print("== END SKILL TEST COVERAGE ==")
        return

    # Try instruction doc first (contributing/guides, contributing/standards, design-guide)
    # Allow with or without .md extension
    if not doc_name.endswith(".md"):
        doc_name_md = doc_name + ".md"
    else:
        doc_name_md = doc_name
        doc_name = doc_name[:-3]

    # Search contributing/guides/, contributing/standards/, design-guide/ by filename
    instruction_dirs = [
        ("contributing/guides", CONTRIBUTING_GUIDES_DIR),
        ("contributing/standards", CONTRIBUTING_STANDARDS_DIR),
        ("design-guide", DESIGN_GUIDE_DIR),
    ]
    for label, search_dir in instruction_dirs:
        candidate = search_dir / doc_name_md
        if candidate.exists():
            with open(candidate) as f:
                content = f.read()
            print(f"== docs/{label}/{doc_name_md} ==")
            print(content.rstrip())
            print(f"\n== END {doc_name_md} ==")
            return

    # Check docs/architecture/ (search subdirectories too)
    arch_path = ARCH_DOCS_DIR / doc_name_md
    if arch_path.exists():
        with open(arch_path) as f:
            content = f.read()
        print(f"== docs/architecture/{doc_name_md} ==")
        print(content.rstrip())
        print(f"\n== END {doc_name_md} ==")
        return
    # Search subdirectories by filename
    if ARCH_DOCS_DIR.exists():
        for candidate in ARCH_DOCS_DIR.rglob(doc_name_md):
            if candidate.is_file():
                rel = candidate.relative_to(ARCH_DOCS_DIR)
                with open(candidate) as f:
                    content = f.read()
                print(f"== docs/architecture/{rel} ==")
                print(content.rstrip())
                print(f"\n== END {rel} ==")
                return

    # Not found — show available docs
    print(f"Error: Document '{doc_name}' not found.", file=sys.stderr)
    print("\nAvailable instruction docs (docs/contributing/ & docs/design-guide/):", file=sys.stderr)
    for label, search_dir in instruction_dirs:
        if search_dir.exists():
            for f in sorted(search_dir.iterdir()):
                if f.suffix == ".md":
                    print(f"  {label}/{f.stem}", file=sys.stderr)
    print("\nAvailable architecture docs (docs/architecture/):", file=sys.stderr)
    if ARCH_DOCS_DIR.exists():
        for f in sorted(ARCH_DOCS_DIR.rglob("*.md")):
            if f.stem != "README":
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
            print(f"== docs/contributing/{doc_name} ==")
            print(doc_content.rstrip())
            print(f"\n== END {doc_name} ==")
        else:
            print(f"[!] docs/contributing/{doc_name} not found")
    print()


# ---------------------------------------------------------------------------
# Test and Documentation Coverage Commands
# ---------------------------------------------------------------------------

# Test location patterns (aligned with docs/contributing/guides/testing.md)
_TEST_LOCATIONS = {
    # Python unit/integration tests
    ".py": [
        "backend/tests/test_{stem}.py",
        "backend/tests/test_rest_api_{stem}.py",
        "backend/apps/{app}/tests/test_{stem}.py",
        "backend/core/api/app/utils/__tests__/test_{stem}.py",
        "backend/core/api/app/services/test_{stem}.py",
    ],
    # TypeScript unit tests
    ".ts": [
        "{parent}/__tests__/{stem}.test.ts",
        "{parent}/__tests__/{stem}.spec.ts",
    ],
    # Svelte component tests
    ".svelte": [
        "{parent}/__tests__/{stem}.test.ts",
        "{parent}/__tests__/{stem}.spec.ts",
    ],
}

# E2E spec directory
_E2E_SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"

# Documentation search directories
_DOCS_DIRS = {
    "architecture": PROJECT_ROOT / "docs" / "architecture",
    "user-guide": PROJECT_ROOT / "docs" / "user-guide",
    "apps": PROJECT_ROOT / "docs" / "apps",
}


def _find_tests_for_file(filepath: str) -> dict:
    """
    Search for existing unit and E2E tests related to a source file.
    Returns dict with 'unit_tests', 'e2e_tests', and 'suggestions'.
    """
    path = Path(filepath)
    stem = path.stem  # e.g., "chatStore" from "chatStore.ts"
    suffix = path.suffix  # e.g., ".ts"
    parent = str(path.parent)  # e.g., "frontend/packages/ui/src/stores"
    result = {"unit_tests": [], "e2e_tests": [], "suggestions": []}

    # --- Search for unit tests ---
    patterns = _TEST_LOCATIONS.get(suffix, [])

    # Infer app name for Python files
    app = ""
    parts = Path(filepath).parts
    if "apps" in parts:
        idx = list(parts).index("apps")
        if idx + 1 < len(parts):
            app = parts[idx + 1]

    for pattern in patterns:
        try:
            candidate = pattern.format(stem=stem, parent=parent, app=app)
        except (KeyError, IndexError):
            continue
        full_path = PROJECT_ROOT / candidate
        if full_path.exists():
            result["unit_tests"].append(candidate)

    # Also do a glob search for any test file containing the stem name
    for test_glob_pattern in [
        f"**/__tests__/*{stem}*",
        f"**/test_{stem}*",
        f"**/*{stem}*.test.*",
        f"**/*{stem}*.spec.*",
    ]:
        for match in PROJECT_ROOT.glob(test_glob_pattern):
            rel = str(match.relative_to(PROJECT_ROOT))
            if rel not in result["unit_tests"] and "node_modules" not in rel:
                result["unit_tests"].append(rel)

    # --- Search for E2E tests referencing this file/component ---
    if _E2E_SPEC_DIR.exists():
        # Search by component name in spec files
        search_terms = [stem]
        # Also search for kebab-case version of camelCase names
        kebab = ""
        for i, c in enumerate(stem):
            if c.isupper() and i > 0:
                kebab += "-"
            kebab += c.lower()
        if kebab != stem.lower():
            search_terms.append(kebab)

        for spec_file in sorted(_E2E_SPEC_DIR.glob("*.spec.ts")):
            try:
                content = spec_file.read_text(errors="replace")
                for term in search_terms:
                    if term.lower() in content.lower():
                        rel = str(spec_file.relative_to(PROJECT_ROOT))
                        if rel not in result["e2e_tests"]:
                            result["e2e_tests"].append(rel)
                        break
            except OSError:
                pass

    # --- Build suggestions ---
    if not result["unit_tests"]:
        if suffix == ".py":
            suggested_path = f"backend/tests/test_{stem}.py" if not app else f"backend/apps/{app}/tests/test_{stem}.py"
            result["suggestions"].append(
                f"CREATE unit test: {suggested_path}\n"
                "    Follow testing.md Rule 2 (test behavior, not implementation, AAA pattern)"
            )
        elif suffix in (".ts", ".svelte"):
            suggested_path = f"{parent}/__tests__/{stem}.test.ts"
            result["suggestions"].append(
                f"CREATE unit test: {suggested_path}\n"
                "    Follow testing.md Rule 2 (test behavior, not implementation, AAA pattern)"
            )

    if not result["e2e_tests"] and suffix in (".svelte", ".ts"):
        result["suggestions"].append(
            "No E2E test references found for this component.\n"
            "    If new user-facing behavior was added, propose E2E test per testing.md Rule 7.\n"
            "    Check if an existing spec should be extended before creating a new one."
        )

    if result["unit_tests"]:
        result["suggestions"].append(
            "UPDATE existing tests to cover any new/changed behavior.\n"
            "    Run tests to verify: see testing.md 'What to Run After Changes' table."
        )

    return result


def _find_docs_for_file(filepath: str) -> dict:
    """
    Search for architecture, user-guide, and app docs related to a source file.
    Returns dict with 'found_docs', 'stale_docs', and 'suggestions'.
    """
    path = Path(filepath)
    stem = path.stem
    result = {"found_docs": [], "stale_docs": [], "suggestions": []}

    # --- Check code-mapping.yml for mapped architecture docs ---
    code_mapping = _parse_code_mapping()
    file_mtime = 0
    full_path = PROJECT_ROOT / filepath
    if full_path.exists():
        file_mtime = os.path.getmtime(str(full_path))

    for doc_name, patterns in code_mapping.items():
        for pat in patterns:
            if fnmatch.fnmatch(filepath, pat):
                doc_path = ARCH_DOCS_DIR / doc_name
                rel = f"docs/architecture/{doc_name}"
                if doc_path.exists():
                    doc_mtime = os.path.getmtime(str(doc_path))
                    is_stale = file_mtime > doc_mtime + (STALE_DOC_HOURS * 3600)
                    entry = {"path": rel, "stale": is_stale}
                    result["found_docs"].append(entry)
                    if is_stale:
                        result["stale_docs"].append(rel)
                break

    # --- Search docs/ directories for mentions of the file/module name ---
    # Use the stem (filename without extension) as the primary search term.
    # Skip overly generic parent directory names that would match too broadly.
    _generic_dirs = {
        "services", "utils", "components", "routes", "tasks", "stores",
        "models", "schemas", "helpers", "app", "core", "api", "src",
        "email_tasks", "auth_routes", "tests", "__tests__",
    }
    search_terms = [stem]
    # Add the full filename (with extension) for more specific matching
    search_terms.append(path.name)

    for doc_category, doc_dir in _DOCS_DIRS.items():
        if not doc_dir.exists():
            continue
        for doc_file in sorted(doc_dir.glob("*.md")):
            if doc_file.name == "README.md":
                continue
            try:
                content = doc_file.read_text(errors="replace").lower()
                for term in search_terms:
                    # Use word-boundary matching for short terms to avoid false matches
                    term_lower = term.lower()
                    if len(term_lower) < 5:
                        continue  # Skip very short terms
                    if term_lower in content:
                        rel = f"docs/{doc_category}/{doc_file.name}"
                        # Avoid duplicates
                        if not any(d.get("path") == rel for d in result["found_docs"]):
                            doc_mtime = os.path.getmtime(str(doc_file))
                            is_stale = file_mtime > doc_mtime + (STALE_DOC_HOURS * 3600)
                            result["found_docs"].append({"path": rel, "stale": is_stale})
                            if is_stale:
                                result["stale_docs"].append(rel)
                        break
            except OSError:
                pass

    # --- Build suggestions ---
    if result["stale_docs"]:
        for doc in result["stale_docs"]:
            result["suggestions"].append(
                f"UPDATE (stale): {doc}\n"
                "    Code has changed more recently than this doc. Review and update."
            )

    if not result["found_docs"]:
        result["suggestions"].append(
            "No documentation found for this file/module.\n"
            "    If this is a new feature or significant module, consider creating:\n"
            f"    - docs/architecture/{stem}.md (architecture decision doc)\n"
            "    Follow logging-and-docs.md documentation standards."
        )
    elif not result["stale_docs"]:
        result["suggestions"].append(
            "All related docs appear up to date.\n"
            "    Verify content accuracy if behavior changed significantly."
        )

    return result


def cmd_check_tests(args: argparse.Namespace) -> None:
    """Search for existing unit and E2E tests related to session files or a specific file."""
    files_to_check = []

    if hasattr(args, "file") and args.file:
        files_to_check = [args.file]
    elif hasattr(args, "session") and args.session:
        data = _load_sessions()
        session = data.get("sessions", {}).get(args.session)
        if not session:
            print(f"Error: Session {args.session} not found.", file=sys.stderr)
            sys.exit(1)
        files_to_check = session.get("modified_files", [])
    else:
        print("Error: Provide --session or --file.", file=sys.stderr)
        sys.exit(1)

    if not files_to_check:
        print("No files to check.")
        return

    print("== TEST COVERAGE CHECK ==")
    print()

    for filepath in sorted(files_to_check):
        # Skip test files themselves and non-source files
        if "/tests/" in filepath or "/__tests__/" in filepath or filepath.startswith("test_"):
            continue
        if not any(filepath.endswith(ext) for ext in (".py", ".ts", ".svelte")):
            continue

        result = _find_tests_for_file(filepath)
        print(f"📁 {filepath}")

        if result["unit_tests"]:
            for t in result["unit_tests"]:
                print(f"  ✅ Unit test: {t}")
        else:
            print("  ❌ No unit tests found")

        if result["e2e_tests"]:
            for t in result["e2e_tests"]:
                print(f"  ✅ E2E test: {t}")
        else:
            if any(filepath.endswith(ext) for ext in (".svelte", ".ts")):
                print("  ❌ No E2E test references found")

        if result["suggestions"]:
            for s in result["suggestions"]:
                lines = s.split("\n")
                print(f"  → INSTRUCTION: {lines[0]}")
                for line in lines[1:]:
                    print(f"  {line}")

        print()

    print("== END TEST COVERAGE CHECK ==")


def cmd_check_docs(args: argparse.Namespace) -> None:
    """Search for architecture and user guide docs related to session files or a specific file."""
    files_to_check = []

    if hasattr(args, "file") and args.file:
        files_to_check = [args.file]
    elif hasattr(args, "session") and args.session:
        data = _load_sessions()
        session = data.get("sessions", {}).get(args.session)
        if not session:
            print(f"Error: Session {args.session} not found.", file=sys.stderr)
            sys.exit(1)
        files_to_check = session.get("modified_files", [])
    else:
        print("Error: Provide --session or --file.", file=sys.stderr)
        sys.exit(1)

    if not files_to_check:
        print("No files to check.")
        return

    print("== DOCUMENTATION CHECK ==")
    print()

    for filepath in sorted(files_to_check):
        # Skip docs files themselves, test files, and config files
        if filepath.startswith("docs/") or "/tests/" in filepath or "/__tests__/" in filepath:
            continue
        if not any(filepath.endswith(ext) for ext in (".py", ".ts", ".svelte", ".yml", ".yaml")):
            continue

        result = _find_docs_for_file(filepath)
        print(f"📁 {filepath}")

        if result["found_docs"]:
            for d in result["found_docs"]:
                status = "⚠️  STALE" if d["stale"] else "✅"
                print(f"  {status} {d['path']}")
        else:
            print("  ❌ No documentation found")

        if result["suggestions"]:
            for s in result["suggestions"]:
                lines = s.split("\n")
                print(f"  → INSTRUCTION: {lines[0]}")
                for line in lines[1:]:
                    print(f"  {line}")

        print()

    print("== END DOCUMENTATION CHECK ==")


def cmd_code_quality(args: argparse.Namespace) -> None:
    """Find the largest source files relevant to the current context for refactoring review."""
    # Determine which directories to scan based on tags
    tags = []
    if hasattr(args, "tags") and args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    elif hasattr(args, "session") and args.session:
        data = _load_sessions()
        session = data.get("sessions", {}).get(args.session)
        if session:
            tags = session.get("tags", [])

    min_lines = getattr(args, "min_lines", 200) or 200
    scan_dirs: list[tuple[str, str]] = []
    if not tags or any(t in tags for t in ("frontend", "embed", "figma", "i18n")):
        scan_dirs.append(("frontend/", "frontend"))
    if not tags or any(t in tags for t in ("backend", "api", "security", "debug")):
        scan_dirs.append(("backend/", "backend"))

    print(f"== CODE QUALITY (min {min_lines} lines, tags: {', '.join(tags) or 'all'}) ==")
    print()

    # Collect file sizes
    file_sizes: list[tuple[int, str]] = []
    extensions = {".py", ".ts", ".svelte", ".css"}

    for scan_prefix, label in scan_dirs:
        scan_path = PROJECT_ROOT / scan_prefix
        if not scan_path.exists():
            continue
        for root, dirs, files in os.walk(scan_path):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in (
                "node_modules", "__pycache__", ".git", "coverage", "dist",
                "build", ".svelte-kit", "test-results",
            )]
            for f in files:
                if not any(f.endswith(ext) for ext in extensions):
                    continue
                full_path = os.path.join(root, f)
                try:
                    with open(full_path) as fh:
                        line_count = sum(1 for _ in fh)
                    if line_count >= min_lines:
                        rel_path = os.path.relpath(full_path, PROJECT_ROOT)
                        file_sizes.append((line_count, rel_path))
                except OSError:
                    continue

    file_sizes.sort(reverse=True)

    if file_sizes:
        print(f"Largest files (>{min_lines} lines, top 15):")
        for line_count, path in file_sizes[:15]:
            print(f"  {line_count:>5} lines  {path}")
    else:
        print(f"No files over {min_lines} lines found in scanned directories.")

    print()
    print("== END CODE QUALITY ==")


def cmd_find_redundancy(args: argparse.Namespace) -> None:
    """Find duplicated CSS classes, function names, and similar files."""
    tags = []
    if hasattr(args, "tags") and args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    scan_path = getattr(args, "path", None)
    if not scan_path:
        if any(t in tags for t in ("frontend", "embed", "figma")):
            scan_path = "frontend/"
        elif any(t in tags for t in ("backend", "api", "security")):
            scan_path = "backend/"
        else:
            scan_path = "."

    full_scan = PROJECT_ROOT / scan_path

    print(f"== REDUNDANCY SCAN ({scan_path}) ==")
    print()

    # 1. CSS class duplication (classes defined in multiple .svelte/.css files)
    css_classes: dict[str, list[str]] = {}
    css_extensions = {".svelte", ".css"}
    class_pattern = re.compile(r'\.([a-zA-Z_][\w-]*)\s*\{')

    for root, dirs, files in os.walk(full_scan):
        dirs[:] = [d for d in dirs if d not in (
            "node_modules", "__pycache__", ".git", "coverage", "dist",
            "build", ".svelte-kit", ".vercel", "test-results",
        )]
        for f in files:
            if not any(f.endswith(ext) for ext in css_extensions):
                continue
            full_path = os.path.join(root, f)
            try:
                with open(full_path, errors="replace") as fh:
                    content = fh.read()
                # For .svelte files, only look inside <style> blocks
                if f.endswith(".svelte"):
                    style_match = re.search(r'<style[^>]*>(.*?)</style>', content, re.DOTALL)
                    if not style_match:
                        continue
                    content = style_match.group(1)
                found_classes = set(class_pattern.findall(content))
                rel_path = os.path.relpath(full_path, PROJECT_ROOT)
                for cls in found_classes:
                    css_classes.setdefault(cls, []).append(rel_path)
            except OSError:
                continue

    # Filter to classes defined in 3+ files
    duplicated_css = {cls: files for cls, files in css_classes.items() if len(files) >= 3}
    if duplicated_css:
        sorted_css = sorted(duplicated_css.items(), key=lambda x: -len(x[1]))[:10]
        print("Duplicate CSS classes (defined in 3+ files, top 10):")
        for cls, files in sorted_css:
            print(f"  .{cls} — {len(files)} files")
            for fp in files[:3]:
                print(f"    {fp}")
            if len(files) > 3:
                print(f"    ... and {len(files) - 3} more")
    else:
        print("No CSS classes duplicated across 3+ files.")

    print()

    # 2. Duplicate exported function/const names across files
    export_pattern = re.compile(r'export\s+(?:function|const|let|class)\s+(\w+)')
    def_pattern = re.compile(r'^def\s+(\w+)\s*\(', re.MULTILINE)

    exports: dict[str, list[str]] = {}
    code_extensions = {".ts", ".py"}

    for root, dirs, files in os.walk(full_scan):
        dirs[:] = [d for d in dirs if d not in (
            "node_modules", "__pycache__", ".git", "coverage", "dist",
            "build", ".svelte-kit", ".vercel", "__tests__", "tests",
            "test-results",
        )]
        for f in files:
            if not any(f.endswith(ext) for ext in code_extensions):
                continue
            full_path = os.path.join(root, f)
            try:
                with open(full_path, errors="replace") as fh:
                    content = fh.read()
                rel_path = os.path.relpath(full_path, PROJECT_ROOT)
                if f.endswith(".ts"):
                    names = export_pattern.findall(content)
                else:
                    names = def_pattern.findall(content)
                for name in names:
                    if name.startswith("_"):
                        continue  # Skip private functions
                    exports.setdefault(name, []).append(rel_path)
            except OSError:
                continue

    # Filter to names exported from 3+ files (likely duplicates worth consolidating)
    dup_exports = {name: files for name, files in exports.items()
                   if len(files) >= 3 and len(name) > 3}
    if dup_exports:
        sorted_exports = sorted(dup_exports.items(), key=lambda x: -len(x[1]))[:10]
        print("Duplicate function/export names (3+ files, top 10):")
        for name, files in sorted_exports:
            print(f"  {name}() — {len(files)} files")
            for fp in files[:3]:
                print(f"    {fp}")
            if len(files) > 3:
                print(f"    ... and {len(files) - 3} more")
    else:
        print("No duplicate function/export names found across 3+ files.")

    print()
    print("== END REDUNDANCY SCAN ==")


def cmd_stale_docs(args: argparse.Namespace) -> None:
    """Show stale architecture docs, optionally filtered by tags."""
    tags = []
    if hasattr(args, "tags") and args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    stale = _check_stale_docs()
    if tags:
        stale = [
            s for s in stale
            if any(tag in ARCH_DOC_DESCRIPTIONS.get(s["doc"].replace(".md", ""), "").lower()
                   or tag in s["doc"].replace(".md", "")
                   for tag in tags)
        ]

    if not stale:
        print("No stale architecture docs found" + (f" for tags: {', '.join(tags)}" if tags else "") + ".")
        return

    print(f"== STALE ARCHITECTURE DOCS ({len(stale)}) ==")
    print()
    for s in stale:
        doc_stem = s["doc"].replace(".md", "")
        desc = ARCH_DOC_DESCRIPTIONS.get(doc_stem, "")
        days_stale = max(1, int(
            (datetime.strptime(s["code_modified"], "%Y-%m-%d") -
             datetime.strptime(s["doc_modified"], "%Y-%m-%d")).days
        ))
        print(f"  {s['doc']} ({days_stale}d stale)")
        if desc:
            print(f"    {desc}")
        print(f"    Doc: {s['doc_modified']}  Code changed: {s['code_modified']}  ({s['code_file']})")
        print()

    print("Load with: sessions.py context --doc <name>")
    print("== END STALE DOCS ==")


def cmd_backlog_add(args: argparse.Namespace) -> None:
    """Add a new entry to the backlog."""
    data = _load_backlog()
    # Use a stable auto-incrementing counter (not position-based)
    next_id = data.get("next_id", max((e.get("id", 0) for e in data["backlog"]), default=0) + 1)
    entry: dict = {
        "id": next_id,
        "title": args.title,
        "description": args.description or "",
        "files": args.files or [],
        "added": _now_iso()[:10],  # date only
    }
    data["backlog"].append(entry)
    data["next_id"] = next_id + 1
    _save_backlog(data)
    print(f"Backlog entry [{entry['id']}] added: {entry['title']}")
    if entry["description"]:
        print(f"  Description: {entry['description']}")
    if entry["files"]:
        print(f"  Files: {', '.join(entry['files'])}")


def cmd_backlog_done(args: argparse.Namespace) -> None:
    """Mark a backlog entry as done (removes it by 1-based index or id)."""
    data = _load_backlog()
    backlog = data.get("backlog", [])

    target_id = args.id
    # Find by the stored id field first, then fall back to positional index
    match_idx = None
    for i, entry in enumerate(backlog):
        if entry.get("id") == target_id:
            match_idx = i
            break
    # Fallback: treat as 1-based position
    if match_idx is None and 1 <= target_id <= len(backlog):
        match_idx = target_id - 1

    if match_idx is None:
        print(f"Error: No backlog entry with id {target_id}.", file=sys.stderr)
        print("  Run 'sessions.py backlog-list' to see current entries.", file=sys.stderr)
        sys.exit(1)

    removed = backlog.pop(match_idx)
    # IDs are stable — no re-numbering after removal
    data["backlog"] = backlog
    _save_backlog(data)
    print(f"Backlog entry removed: [{removed.get('id', '?')}] {removed.get('title', '?')}")
    print(f"  {len(backlog)} item(s) remaining.")


def cmd_backlog_list(args: argparse.Namespace) -> None:
    """List all backlog entries."""
    data = _load_backlog()
    backlog = data.get("backlog", [])
    if not backlog:
        print("Backlog is empty.")
        return
    print(f"== BACKLOG ({len(backlog)} items) ==")
    print(_format_backlog_for_display(backlog))
    print()
    print("Mark done: sessions.py backlog-done --id <N>")
    print("Add new:   sessions.py backlog-add --title \"...\" --description \"...\" [--files f1 f2]")


def cmd_task_create(args: argparse.Namespace) -> None:
    """Create a new task YAML file in .claude/tasks/."""
    meta = _load_task_meta()
    next_num = meta.get("next_id", 1)
    task_id = f"t{next_num:03d}"

    title = args.title
    tags = [t.strip() for t in args.tags.split(",")] if getattr(args, "tags", None) else []
    files_to_modify = list(getattr(args, "files", None) or [])

    task: dict = {
        "id": task_id,
        "title": title,
        "status": "in_progress",
        "mode": getattr(args, "mode", None) or "feature",
        "tags": tags,
        "created": _now_iso(),
        "updated": _now_iso(),
        "session": getattr(args, "session", None) or "~",
        "context": getattr(args, "context", None) or "",
        "plan": [],
        "acceptance_criteria": [],
        "files_to_modify": files_to_modify,
        "files_modified": [],
        "notes": "",
        "summary": "",
    }

    _save_task(task)

    # Update meta
    meta["next_id"] = next_num + 1
    meta["last_id"] = task_id
    _save_task_meta(meta)

    # Link to session if provided
    session_id = getattr(args, "session", None)
    if session_id:
        data = _load_sessions()
        if session_id in data.get("sessions", {}):
            data["sessions"][session_id]["task_id"] = task_id
            _save_sessions(data)

    path = _task_id_to_path(task_id)
    print(f"Created task {task_id}: {title}")
    print(f"  File: {path}")
    print(f"  Add steps:    sessions.py task-step --id {task_id} --add \"[ ] Step description\"")
    print(f"  Add AC:       sessions.py task-ac   --id {task_id} --add \"[ ] Acceptance criterion\"")
    print(f"  Show:         sessions.py task-show --id {task_id}")


def cmd_task_step(args: argparse.Namespace) -> None:
    """Add or check off a plan step in a task file."""
    task_id = args.id
    task = _load_task(task_id)
    if task is None:
        print(f"Error: Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)

    plan = task.get("plan", [])

    if getattr(args, "add", None):
        plan.append(args.add)
        task["plan"] = plan
        _save_task(task)
        print(f"[{task_id}] Added step [{len(plan)}]: {args.add}")

    elif getattr(args, "done", None) is not None:
        idx = args.done - 1
        if idx < 0 or idx >= len(plan):
            print(f"Error: Step {args.done} out of range (1–{len(plan)}).", file=sys.stderr)
            sys.exit(1)
        step = plan[idx]
        # Replace [ ] with [x]
        if "[ ]" in step:
            step = step.replace("[ ]", "[x]", 1)
        elif "[x]" in step:
            print(f"Step {args.done} is already checked off.")
            return
        else:
            step = "[x] " + step
        plan[idx] = step
        task["plan"] = plan
        _save_task(task)
        print(f"[{task_id}] Checked off step {args.done}: {step}")
    else:
        print("Use --add \"<text>\" or --done <N>.", file=sys.stderr)
        sys.exit(1)


def cmd_task_ac(args: argparse.Namespace) -> None:
    """Add or check off an acceptance criterion in a task file."""
    task_id = args.id
    task = _load_task(task_id)
    if task is None:
        print(f"Error: Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)

    ac = task.get("acceptance_criteria", [])

    if getattr(args, "add", None):
        ac.append(args.add)
        task["acceptance_criteria"] = ac
        _save_task(task)
        print(f"[{task_id}] Added AC [{len(ac)}]: {args.add}")

    elif getattr(args, "done", None) is not None:
        idx = args.done - 1
        if idx < 0 or idx >= len(ac):
            print(f"Error: AC {args.done} out of range (1–{len(ac)}).", file=sys.stderr)
            sys.exit(1)
        item = ac[idx]
        if "[ ]" in item:
            item = item.replace("[ ]", "[x]", 1)
        elif "[x]" in item:
            print(f"AC {args.done} is already checked off.")
            return
        else:
            item = "[x] " + item
        ac[idx] = item
        task["acceptance_criteria"] = ac
        _save_task(task)
        print(f"[{task_id}] Checked off AC {args.done}: {item}")
    else:
        print("Use --add \"<text>\" or --done <N>.", file=sys.stderr)
        sys.exit(1)


def cmd_task_show(args: argparse.Namespace) -> None:
    """Print full task details with numbered steps."""
    task_id = args.id
    task = _load_task(task_id)
    if task is None:
        print(f"Error: Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)

    plan = task.get("plan", [])
    ac = task.get("acceptance_criteria", [])
    done_steps = sum(1 for s in plan if "[x]" in s)
    total_steps = len(plan)

    print(f"== TASK {task_id}: {task.get('title', '?')} ==")
    print(f"Status: {task.get('status', '?')}  |  {done_steps}/{total_steps} steps done  |  Session: {task.get('session', '~')}")
    print(f"Mode: {task.get('mode', '?')}  |  Tags: {', '.join(task.get('tags', [])) or 'none'}")
    print(f"Created: {task.get('created', '?')}  |  Updated: {task.get('updated', '?')}")

    ctx = task.get("context", "")
    if ctx:
        print()
        print("Context:")
        for cl in ctx.split("\n"):
            print(f"  {cl}")

    if plan:
        print()
        print("Plan:")
        for i, step in enumerate(plan, 1):
            print(f"  [{i}] {step}")

    if ac:
        print()
        print("Acceptance Criteria:")
        for i, item in enumerate(ac, 1):
            print(f"  [{i}] {item}")

    ftm = task.get("files_to_modify", [])
    if ftm:
        print()
        print("Files to modify:")
        for f in ftm:
            print(f"  - {f}")

    fm = task.get("files_modified", [])
    if fm:
        print()
        print("Files modified:")
        for f in fm:
            print(f"  - {f}")

    notes = task.get("notes", "")
    if notes:
        print()
        print("Notes:")
        for nl in notes.split("\n"):
            print(f"  {nl}")

    summary = task.get("summary", "")
    if summary:
        print()
        print("Summary:")
        for sl in summary.split("\n"):
            print(f"  {sl}")


def cmd_task_list(args: argparse.Namespace) -> None:
    """List all task files as a compact table."""
    d = _tasks_dir()
    task_files = sorted(d.glob("t[0-9][0-9][0-9]-*.yml"))

    if not task_files:
        print("No tasks found. Create one: sessions.py task-create --title \"...\"")
        return

    status_filter = getattr(args, "status", None)

    tasks = []
    for path in task_files:
        try:
            t = _parse_task_file(path)
            tasks.append(t)
        except Exception:
            continue

    if status_filter:
        tasks = [t for t in tasks if t.get("status") == status_filter]

    if not tasks:
        print(f"No tasks with status '{status_filter}'.")
        return

    # Group by status
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        s = t.get("status", "todo")
        groups.setdefault(s, []).append(t)

    order = ["in_progress", "todo", "done", "abandoned"]
    print(f"== TASKS ({len(tasks)}) ==")
    for status in order:
        if status not in groups:
            continue
        print(f"\n  {status.upper()}:")
        for t in groups[status]:
            plan = t.get("plan", [])
            done = sum(1 for s in plan if "[x]" in s)
            total = len(plan)
            sess = t.get("session", "~")
            title = t.get("title", "?")
            tid = t.get("id", "?")
            step_info = f"{done}/{total} steps" if total else "no steps"
            print(f"    {tid}  {title[:50]:<50}  [{step_info}]  session:{sess}")
    print()
    print("Show details: sessions.py task-show --id <id>")
    print("Resume:       sessions.py start --mode <mode> --task \"...\" --task-id <id>")


def cmd_task_update(args: argparse.Namespace) -> None:
    """Update scalar fields in a task file."""
    task_id = args.id
    task = _load_task(task_id)
    if task is None:
        print(f"Error: Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)

    changed = []
    if getattr(args, "status", None):
        task["status"] = args.status
        changed.append(f"status={args.status}")
    if getattr(args, "title", None):
        task["title"] = args.title
        changed.append(f"title={args.title!r}")
    if getattr(args, "session", None):
        task["session"] = args.session
        changed.append(f"session={args.session}")
    if getattr(args, "notes", None):
        existing = task.get("notes", "")
        task["notes"] = (existing + "\n" + args.notes).strip()
        changed.append("notes appended")
    if getattr(args, "summary", None):
        existing = task.get("summary", "")
        task["summary"] = (existing + "\n" + args.summary).strip() if existing else args.summary
        changed.append("summary set")

    if not changed:
        print("Nothing to update. Use --status, --title, --session, --notes, or --summary.")
        return

    _save_task(task)

    # If session is updated, link it in sessions.json too
    if getattr(args, "session", None):
        data = _load_sessions()
        session_id = args.session
        if session_id in data.get("sessions", {}):
            data["sessions"][session_id]["task_id"] = task_id
            _save_sessions(data)

    print(f"[{task_id}] Updated: {', '.join(changed)}")


def cmd_task_track(args: argparse.Namespace) -> None:
    """Append a file path to files_modified in a task file."""
    task_id = args.id
    task = _load_task(task_id)
    if task is None:
        print(f"Error: Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)

    file_path = args.file
    fm = task.get("files_modified", [])
    if file_path not in fm:
        fm.append(file_path)
        task["files_modified"] = fm
        _save_task(task)
        print(f"[{task_id}] Tracked: {file_path}")
    else:
        print(f"[{task_id}] Already tracked: {file_path}")


def cmd_trigger_tests(args: argparse.Namespace) -> None:
    """Trigger tests via the unified run_tests.py orchestrator."""
    suite = getattr(args, "suite", "all") or "all"
    env = getattr(args, "env", "development") or "development"

    run_tests_script = PROJECT_ROOT / "scripts" / "run_tests.py"
    if not run_tests_script.is_file():
        print("ERROR: scripts/run_tests.py not found.", file=sys.stderr)
        sys.exit(1)

    cmd = [sys.executable, str(run_tests_script)]
    if suite != "all":
        cmd += ["--suite", suite]
    if env != "development":
        cmd += ["--environment", env]

    print(f"Running tests via run_tests.py (suite={suite}, environment={env})...")
    rc = subprocess.call(cmd, cwd=str(PROJECT_ROOT))
    sys.exit(rc)


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
    p_start.add_argument(
        "--mode", "-m",
        required=True,
        choices=VALID_MODES,
        help="Session mode: 'feature' (new functionality), 'bug' (debugging), "
        "'docs' (documentation), 'question' (codebase questions). "
        "Controls which context sections are shown.",
    )
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
    p_start.add_argument(
        "--user",
        metavar="EMAIL",
        help="Pre-fetch user data with session context (10 chats, 20 embeds). "
        "Auto-adds 'debug' tag.",
    )
    p_start.add_argument(
        "--debug-id",
        metavar="DEBUG_ID",
        help="Pre-fetch logs for a user debug session ID (e.g., 'dbg-a3f2c8'). "
        "Auto-adds 'debug' tag.",
    )
    p_start.add_argument(
        "--error-since",
        type=int,
        default=7,
        metavar="DAYS",
        help="Error trend lookback period in days (default: 7). "
        "Used in bug mode for error overview.",
    )
    p_start.add_argument(
        "--vercel",
        action="store_true",
        help="Pre-fetch latest Vercel deployment status and build errors. "
        "Auto-adds 'debug' tag.",
    )
    p_start.add_argument(
        "--run-id",
        metavar="RUN_ID",
        help="Pre-fetch context for a specific daily test run by its run ID prefix "
        "(e.g., '2026-03-18T03:00:01Z'). Shows summary, failing specs, and "
        "OpenObserve debug logs. Auto-adds 'test,debug' tags.",
    )
    p_start.add_argument(
        "--since-last-deploy",
        action="store_true",
        help="Show all commits and changed files since the last sessions.py deploy call. "
        "Useful when resuming work after a break or picking up from another session.",
    )
    p_start.add_argument(
        "--task-id",
        metavar="TASK_ID",
        help="Link an existing task file to this session (e.g. t003). "
        "Displays pending steps inline at startup.",
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
    p_deploy.add_argument(
        "--no-verify",
        action="store_true",
        dest="no_verify",
        help="Bypass pre-commit hooks (git commit --no-verify). Use only when a "
        "pre-existing hook bug prevents deploy. WARNING printed to stderr.",
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
        "--doc", "-d",
        help="Document name (e.g., 'debugging', 'sync', 'embed-types')",
    )
    p_context.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available docs with line counts and which tags auto-load them.",
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

    # check-tests
    p_check_tests = sub.add_parser(
        "check-tests",
        help="Search for existing unit and E2E tests related to modified files",
    )
    p_check_tests.add_argument(
        "--session", "-s",
        help="Session ID (checks session's modified_files)",
    )
    p_check_tests.add_argument(
        "--file", "-f",
        help="Specific file path to check test coverage for",
    )

    # check-docs
    p_check_docs = sub.add_parser(
        "check-docs",
        help="Search for architecture and user guide docs related to modified files",
    )
    p_check_docs.add_argument(
        "--session", "-s",
        help="Session ID (checks session's modified_files)",
    )
    p_check_docs.add_argument(
        "--file", "-f",
        help="Specific file path to check documentation for",
    )

    # trigger-tests
    p_trigger_tests = sub.add_parser(
        "trigger-tests",
        help="Trigger the GitHub Actions daily test workflow",
    )
    p_trigger_tests.add_argument(
        "--suite",
        choices=["all", "playwright", "pytest", "vitest"],
        default="all",
        help="Test suite to run (default: all)",
    )
    p_trigger_tests.add_argument(
        "--env",
        choices=["development", "production"],
        default="development",
        help="Target environment (default: development)",
    )
    p_trigger_tests.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Stream live status after triggering",
    )

    # debug-vercel
    sub.add_parser(
        "debug-vercel",
        help="Auto-start a session and print Vercel deployment logs for the web app",
    )

    # code-quality
    p_code_quality = sub.add_parser(
        "code-quality",
        help="Find largest source files for refactoring review",
    )
    p_code_quality.add_argument(
        "--session", "-s",
        help="Session ID (uses session tags to filter scan scope)",
    )
    p_code_quality.add_argument(
        "--tags",
        help="Comma-separated tags to filter scan scope (e.g., 'frontend')",
    )
    p_code_quality.add_argument(
        "--min-lines",
        type=int,
        default=200,
        help="Minimum line count threshold (default: 200)",
    )

    # find-redundancy
    p_find_redundancy = sub.add_parser(
        "find-redundancy",
        help="Find duplicated CSS classes, function names, and similar files",
    )
    p_find_redundancy.add_argument(
        "--path",
        help="Directory path to scan (default: auto from tags or '.')",
    )
    p_find_redundancy.add_argument(
        "--tags",
        help="Comma-separated tags to filter scan scope",
    )

    # stale-docs
    p_stale_docs = sub.add_parser(
        "stale-docs",
        help="Show stale architecture docs, optionally filtered by tags",
    )
    p_stale_docs.add_argument(
        "--tags",
        help="Comma-separated tags to filter results",
    )

    # backlog-add
    p_backlog_add = sub.add_parser(
        "backlog-add",
        help="Add a new task to the backlog (.claude/backlog.json)",
    )
    p_backlog_add.add_argument(
        "--title", "-t", required=True,
        help="Short title for the backlog task",
    )
    p_backlog_add.add_argument(
        "--description", "-d",
        help="Optional longer description of the task",
    )
    p_backlog_add.add_argument(
        "--files", "-f",
        nargs="*",
        metavar="FILE",
        help="Optional relevant file paths (space-separated)",
    )

    # backlog-done
    p_backlog_done = sub.add_parser(
        "backlog-done",
        help="Mark a backlog task as done (removes it from backlog)",
    )
    p_backlog_done.add_argument(
        "--id", "-i",
        required=True,
        type=int,
        metavar="N",
        help="Backlog entry id (shown in backlog-list and session start output)",
    )

    # backlog-list
    sub.add_parser(
        "backlog-list",
        help="List all current backlog tasks",
    )

    # task-create
    p_task_create = sub.add_parser(
        "task-create",
        help="Create a persistent task YAML file in .claude/tasks/",
    )
    p_task_create.add_argument("--title", "-t", required=True, help="Task title")
    p_task_create.add_argument("--session", "-s", help="Link to this session ID")
    p_task_create.add_argument("--context", "-c", help="Background context for the task")
    p_task_create.add_argument("--mode", "-m", choices=list(VALID_MODES), default="feature",
                               help="Task mode (default: feature)")
    p_task_create.add_argument("--tags", help="Comma-separated tags")
    p_task_create.add_argument("--files", "-f", nargs="*", metavar="FILE",
                               help="Files to modify (space-separated)")

    # task-step
    p_task_step = sub.add_parser(
        "task-step",
        help="Add or check off a plan step in a task file",
    )
    p_task_step.add_argument("--id", "-i", required=True, metavar="TASK_ID", help="Task ID (e.g. t001)")
    p_task_step.add_argument("--add", "-a", metavar="TEXT", help="Add a new step (e.g. '[ ] Step text')")
    p_task_step.add_argument("--done", "-d", type=int, metavar="N", help="Mark step N as done")

    # task-ac
    p_task_ac = sub.add_parser(
        "task-ac",
        help="Add or check off an acceptance criterion in a task file",
    )
    p_task_ac.add_argument("--id", "-i", required=True, metavar="TASK_ID", help="Task ID")
    p_task_ac.add_argument("--add", "-a", metavar="TEXT", help="Add a new acceptance criterion")
    p_task_ac.add_argument("--done", "-d", type=int, metavar="N", help="Mark AC N as done")

    # task-show
    p_task_show = sub.add_parser(
        "task-show",
        help="Print full task details with numbered steps",
    )
    p_task_show.add_argument("--id", "-i", required=True, metavar="TASK_ID", help="Task ID")

    # task-list
    p_task_list = sub.add_parser(
        "task-list",
        help="List all task files as a compact table",
    )
    p_task_list.add_argument(
        "--status",
        choices=["todo", "in_progress", "done", "abandoned"],
        help="Filter by status",
    )

    # task-update
    p_task_update = sub.add_parser(
        "task-update",
        help="Update scalar fields in a task file",
    )
    p_task_update.add_argument("--id", "-i", required=True, metavar="TASK_ID", help="Task ID")
    p_task_update.add_argument("--status", choices=["todo", "in_progress", "done", "abandoned"],
                               help="New status")
    p_task_update.add_argument("--title", help="New title")
    p_task_update.add_argument("--session", "-s", help="Link a session ID")
    p_task_update.add_argument("--notes", help="Append text to notes field")
    p_task_update.add_argument("--summary", help="Set/append task summary (what was done and why)")

    # task-track
    p_task_track = sub.add_parser(
        "task-track",
        help="Append a file to files_modified in a task file",
    )
    p_task_track.add_argument("--id", "-i", required=True, metavar="TASK_ID", help="Task ID")
    p_task_track.add_argument("--file", "-f", required=True, help="File path")

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
        "check-tests": cmd_check_tests,
        "check-docs": cmd_check_docs,
        "trigger-tests": cmd_trigger_tests,
        "debug-vercel": cmd_debug_vercel,
        "code-quality": cmd_code_quality,
        "find-redundancy": cmd_find_redundancy,
        "stale-docs": cmd_stale_docs,
        "backlog-add": cmd_backlog_add,
        "backlog-done": cmd_backlog_done,
        "backlog-list": cmd_backlog_list,
        "task-create": cmd_task_create,
        "task-step": cmd_task_step,
        "task-ac": cmd_task_ac,
        "task-show": cmd_task_show,
        "task-list": cmd_task_list,
        "task-update": cmd_task_update,
        "task-track": cmd_task_track,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
