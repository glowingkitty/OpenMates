#!/usr/bin/env python3
"""
Session lifecycle manager for concurrent Claude Code sessions.

Manages session registration, file tracking, concurrent edit safety,
tag-based instruction doc preloading, architecture doc staleness detection,
and automated deployment (lint + commit + push).

Architecture context: See docs/claude/concurrent-sessions.md for the full protocol.

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
    python3 scripts/sessions.py deploy  --session a3f2 --title "fix: msg" --message "body"
"""

import argparse
import base64
import fcntl
import fnmatch
import glob as glob_mod
import html
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
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
STALE_EMPTY_SESSION_HOURS = 6  # Sessions with zero tracked files expire faster
STALE_LOCK_MINUTES = 5
STALE_DOC_HOURS = 24
RECENT_COMMITS_COUNT = 10  # Number of recent git commits to show at session start
CLAUDE_DOCS_DIR = PROJECT_ROOT / "docs" / "claude"
ARCH_DOCS_DIR = PROJECT_ROOT / "docs" / "architecture"
ENV_FILE = PROJECT_ROOT / ".env"
PLANE_STATE_CACHE_FILE = PROJECT_ROOT / ".claude" / "plane-states.json"
PLANE_STATE_CACHE_HOURS = 24
OPENCODE_WEB_BASE_URL_DEFAULT = "https://code.dev.openmates.org"

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


def _load_env_file_values() -> dict[str, str]:
    """Load simple KEY=VALUE pairs from .env (if present)."""
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    try:
        with open(ENV_FILE) as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key.startswith("export "):
                    key = key.replace("export ", "", 1).strip()
                if key:
                    values[key] = value
    except OSError:
        return {}
    return values


def _get_env_value(name: str, env_file_values: dict[str, str] | None = None) -> str | None:
    """Resolve config value from process env first, then .env file."""
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    if env_file_values and name in env_file_values:
        fallback = env_file_values[name].strip()
        if fallback:
            return fallback
    return None


def _get_plane_config() -> dict | None:
    """Return Plane integration config from env/.env, or None when incomplete."""
    env_file_values = _load_env_file_values()
    base_url = _get_env_value("PLANE_BASE_URL", env_file_values)
    api_key = _get_env_value("PLANE_API_KEY", env_file_values)
    workspace_slug = _get_env_value("PLANE_WORKSPACE_SLUG", env_file_values)
    project_id = _get_env_value("PLANE_PROJECT_ID", env_file_values)

    if not all([base_url, api_key, workspace_slug, project_id]):
        return None
    assert base_url is not None
    assert api_key is not None
    assert workspace_slug is not None
    assert project_id is not None

    opencode_web_base_url = (
        _get_env_value("OPENCODE_WEB_BASE_URL", env_file_values)
        or OPENCODE_WEB_BASE_URL_DEFAULT
    )

    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "workspace_slug": workspace_slug,
        "project_id": project_id,
        "opencode_web_base_url": opencode_web_base_url.rstrip("/"),
    }


def _plane_api_request(
    config: dict,
    method: str,
    path: str,
    body: dict | None = None,
) -> dict | list | None:
    """Perform a Plane API request and return parsed JSON."""
    url = f"{config['base_url']}/api/v1{path}"
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=payload,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": config["api_key"],
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8").strip()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as err:
        details = err.read().decode("utf-8", errors="ignore").strip()
        details = details[:300] if details else str(err)
        print(f"[Plane] HTTP {err.code} on {method} {path}: {details}")
        return None
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as err:
        print(f"[Plane] Request failed on {method} {path}: {err}")
        return None


def _extract_results(payload: dict | list | None) -> list[dict]:
    """Normalize paginated/non-paginated API payloads to a list of objects."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _load_plane_state_cache() -> dict:
    """Load cached Plane state mappings."""
    if not PLANE_STATE_CACHE_FILE.exists():
        return {}
    try:
        with open(PLANE_STATE_CACHE_FILE) as cache_file:
            data = json.load(cache_file)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_plane_state_cache(cache: dict) -> None:
    """Persist Plane state mapping cache."""
    try:
        PLANE_STATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PLANE_STATE_CACHE_FILE, "w") as cache_file:
            json.dump(cache, cache_file, indent=2)
            cache_file.write("\n")
    except OSError:
        return


def _get_plane_state_id(config: dict, group: str) -> str | None:
    """Resolve a Plane state ID by state group (started/completed)."""
    cache = _load_plane_state_cache()
    cache_key = f"{config['workspace_slug']}:{config['project_id']}"
    cached_entry = cache.get(cache_key, {})
    if isinstance(cached_entry, dict):
        fetched_at = cached_entry.get("fetched_at")
        cached_states = cached_entry.get("states")
        if isinstance(fetched_at, str) and isinstance(cached_states, dict):
            try:
                is_fresh = _hours_since(fetched_at) < PLANE_STATE_CACHE_HOURS
            except ValueError:
                is_fresh = False
            if is_fresh and isinstance(cached_states.get(group), str):
                return cached_states[group]

    workspace_slug = urllib.parse.quote(config["workspace_slug"], safe="")
    path = (
        f"/workspaces/{workspace_slug}/projects/{config['project_id']}/states/"
    )
    payload = _plane_api_request(config, "GET", path)
    states = _extract_results(payload)
    if not states:
        return None

    preferred_by_group: dict[str, dict] = {}
    for state in states:
        state_group = state.get("group")
        if not isinstance(state_group, str):
            continue
        existing = preferred_by_group.get(state_group)
        if not existing:
            preferred_by_group[state_group] = state
            continue
        if state.get("default") and not existing.get("default"):
            preferred_by_group[state_group] = state

    mapped_states: dict[str, str] = {}
    for state_group, state in preferred_by_group.items():
        state_id = state.get("id")
        if isinstance(state_id, str):
            mapped_states[state_group] = state_id

    cache[cache_key] = {
        "fetched_at": _now_iso(),
        "states": mapped_states,
    }
    _save_plane_state_cache(cache)

    return mapped_states.get(group)


def _get_opencode_session_id_for_project() -> str | None:
    """Best-effort lookup of the latest OpenCode session ID."""
    rc, stdout, _ = _run_cmd(
        ["opencode", "session", "list", "-n", "1", "--format", "json"],
        timeout=10,
    )
    if rc != 0 or not stdout:
        return None

    try:
        sessions = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    if not isinstance(sessions, list):
        return None
    if not sessions:
        return None
    session = sessions[0]
    if not isinstance(session, dict):
        return None
    session_id = session.get("id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


def _build_opencode_session_url(opencode_web_base_url: str, opencode_session_id: str) -> str:
    """Build the OpenCode web UI URL for a specific session."""
    encoded_project_path = base64.b64encode(str(PROJECT_ROOT).encode("utf-8")).decode("ascii")
    return f"{opencode_web_base_url}/{encoded_project_path}/session/{opencode_session_id}"


def _build_plane_description_html(
    sid: str,
    session: dict,
    *,
    commit_hash: str | None = None,
    completed_at: str | None = None,
) -> str:
    """Build rich Plane card description for start/completion updates."""
    task = html.escape(session.get("task", "(pending)"))
    started = html.escape(session.get("started", ""))
    tags = session.get("tags", [])
    tags_text = html.escape(", ".join(tags)) if tags else "none"
    opencode_url = session.get("opencode_session_url")

    lines = [
        "<h3>Session Summary</h3>",
        (
            "<p>This task tracks implementation and verification work for "
            f"<strong>{task}</strong>. "
            "Progress is maintained in the session lifecycle workflow so status is visible in Plane.</p>"
        ),
        (
            "<p>Use the OpenCode session link to inspect prompts, outputs, and execution details while the "
            "card is in Doing.</p>"
        ),
        f"<p><strong>Session ID:</strong> {html.escape(sid)}</p>",
        f"<p><strong>Started:</strong> {started}</p>",
        f"<p><strong>Tags:</strong> {tags_text}</p>",
    ]

    if isinstance(opencode_url, str) and opencode_url:
        escaped_url = html.escape(opencode_url, quote=True)
        lines.append(f"<p><a href=\"{escaped_url}\">OpenCode Session</a></p>")

    if completed_at:
        lines.append("<h3>Completion</h3>")
        lines.append(f"<p><strong>Completed:</strong> {html.escape(completed_at)}</p>")
        lines.append(
            f"<p><strong>Tracked Files:</strong> {len(session.get('modified_files', []))}</p>"
        )
        if commit_hash:
            commit_url = _get_commit_url(commit_hash)
            escaped_hash = html.escape(commit_hash)
            if commit_url:
                escaped_commit_url = html.escape(commit_url, quote=True)
                lines.append(
                    "<p><strong>Commit:</strong> "
                    f"<a href=\"{escaped_commit_url}\">{escaped_hash}</a></p>"
                )
            else:
                lines.append(f"<p><strong>Commit:</strong> {escaped_hash}</p>")

    return "\n".join(lines)


def _create_plane_work_item_for_session(sid: str, session: dict) -> str | None:
    """Create a Plane work item in Doing/started state for this session."""
    config = _get_plane_config()
    if not config:
        return None

    started_state_id = _get_plane_state_id(config, "started")
    if not started_state_id:
        print("[Plane] Could not resolve a 'started' state for this project.")
        return None

    title = f"[{sid}] {session.get('task', '(pending)')}"
    description_html = _build_plane_description_html(sid, session)
    workspace_slug = urllib.parse.quote(config["workspace_slug"], safe="")
    path = f"/workspaces/{workspace_slug}/projects/{config['project_id']}/work-items/"
    payload = {
        "name": title,
        "description_html": description_html,
        "state": started_state_id,
    }

    response = _plane_api_request(config, "POST", path, payload)
    if not isinstance(response, dict):
        return None

    work_item_id = response.get("id")
    if isinstance(work_item_id, str):
        return work_item_id
    return None


def _mark_plane_work_item_done(session: dict, sid: str, commit_hash: str | None = None) -> None:
    """Move a Plane work item to completed and attach final summary metadata."""
    work_item_id = session.get("plane_work_item_id")
    if not isinstance(work_item_id, str) or not work_item_id:
        return

    config = _get_plane_config()
    if not config:
        return

    completed_state_id = _get_plane_state_id(config, "completed")
    if not completed_state_id:
        print("[Plane] Could not resolve a 'completed' state for this project.")
        return

    completed_at = _now_iso()
    description_html = _build_plane_description_html(
        sid,
        session,
        commit_hash=commit_hash,
        completed_at=completed_at,
    )

    workspace_slug = urllib.parse.quote(config["workspace_slug"], safe="")
    path = (
        f"/workspaces/{workspace_slug}/projects/{config['project_id']}/work-items/"
        f"{work_item_id}/"
    )
    payload = {
        "state": completed_state_id,
        "description_html": description_html,
    }
    response = _plane_api_request(config, "PATCH", path, payload)
    if response is not None:
        print(f"[Plane] Work item {work_item_id} moved to Done.")


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
    """Fetch a compact error/warning overview from OpenObserve + Redis fingerprints."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "errors", "--compact", "--top", "5", "--since", str(since_minutes),
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        return "  (could not fetch error overview)"
    return stdout.strip()


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
    for et in extra_tags:
        if et not in tags:
            tags.append(et)

    mode = args.mode

    # Register session
    data["sessions"][sid] = {
        "task": args.task or "(pending)",
        "mode": mode,
        "tags": tags,
        "started": _now_iso(),
        "last_active": _now_iso(),
        "modified_files": [],
        "writing": None,
        "opencode_session_id": None,
        "opencode_session_url": None,
        "plane_work_item_id": None,
    }

    # Attach OpenCode session metadata (best effort) for Plane card linking
    plane_config = _get_plane_config()
    opencode_session_id = _get_opencode_session_id_for_project()
    opencode_web_base_url = (
        plane_config["opencode_web_base_url"]
        if plane_config
        else OPENCODE_WEB_BASE_URL_DEFAULT
    )
    if opencode_session_id:
        opencode_session_url = _build_opencode_session_url(
            opencode_web_base_url,
            opencode_session_id,
        )
        data["sessions"][sid]["opencode_session_id"] = opencode_session_id
        data["sessions"][sid]["opencode_session_url"] = opencode_session_url

    _save_sessions(data)

    # Create Plane work item in Doing/started state (best effort, never blocking)
    work_item_id = _create_plane_work_item_for_session(sid, data["sessions"][sid])
    if work_item_id:
        data["sessions"][sid]["plane_work_item_id"] = work_item_id
        _save_sessions(data)

    # --- Output context for Claude (mode-aware) ---
    # Mode determines which sections are shown and at what verbosity.
    # Modes: feature, bug, docs, question, testing

    print("== SESSION STARTED ==")
    print(f"Session ID: {sid}")
    print(f"Mode: {mode}")
    print(f"Started: {_now_iso()}")
    if args.task:
        print(f"Task: {args.task}")
    if tags:
        print(f"Tags: {', '.join(tags)}")
    if data["sessions"][sid].get("opencode_session_url"):
        print(f"OpenCode URL: {data['sessions'][sid]['opencode_session_url']}")
    if work_item_id:
        print(f"Plane Work Item: {work_item_id}")
    print()

    # ── Git status ─────────────────────────────────────────────────────────
    # feature/bug/testing: full | docs: branch only | question: branch only
    git_status = _get_git_status_summary()
    if mode in ("feature", "bug", "testing"):
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
    else:
        print(f"Branch: {git_status['branch']}")
        print()

    # ── Recent commits ─────────────────────────────────────────────────────
    # feature: 10 | bug/docs: 5 | question: skip
    if mode != "question":
        commit_limit = RECENT_COMMITS_COUNT if mode == "feature" else 5
        recent_commits = _get_recent_commits(count=commit_limit)
        if recent_commits:
            print(f"== RECENT COMMITS ({len(recent_commits)}) ==")
            for commit_line in recent_commits:
                print(f"  {commit_line}")
            print()

    # ── Health check ───────────────────────────────────────────────────────
    # bug: full health check | feature/testing: compact one-liner | docs/question: skip
    prefetch_items: list[tuple[str, str]] = []

    if mode == "bug":
        prefetch_items.append(("debug health (auto)", _prefetch_health_check()))
    elif mode in ("feature", "testing"):
        prefetch_items.append(("health (compact)", _prefetch_health_check_compact()))

    # ── Bug-mode only: recent issues + error overview ──────────────────────
    if mode == "bug":
        prefetch_items.append(("recent user issues", _prefetch_recent_issues(limit=2)))
        prefetch_items.append(("error overview (30m)", _prefetch_error_overview(since_minutes=30)))

    # ── Testing-mode: test summary, spec inventory, OpenObserve events ─────
    if mode == "testing":
        prefetch_items.append(("last test run + daily trend", _prefetch_test_summary()))
        prefetch_items.append(("OpenObserve test events (2h)", _prefetch_test_events_o2()))

    # ── Explicit prefetch flags (all modes — user explicitly requested) ────
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

    user_email = getattr(args, "user", None)
    if user_email:
        prefetch_items.append((f"user {user_email}", _prefetch_user_context(user_email)))

    debug_id = getattr(args, "debug_id", None)
    if debug_id:
        prefetch_items.append((f"debug session {debug_id}", _prefetch_debug_session_logs(debug_id)))

    # ── E2E spec inventory (testing mode only) ────────────────────────────
    if mode == "testing":
        spec_count = len(list(E2E_SPEC_DIR.glob("*.spec.ts"))) if E2E_SPEC_DIR.exists() else 0
        print(f"== E2E SPEC INVENTORY ({spec_count} specs) ==")
        print(_get_e2e_spec_categories())
        print()

    if prefetch_items:
        print("== PREFETCHED CONTEXT ==")
        for label, content in prefetch_items:
            print(f"--- {label} ---")
            print(content)
            print()
        print("== END PREFETCHED CONTEXT ==")
        print()

    # ── Active sessions / locks (all modes) ────────────────────────────────
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

    # ── Stale architecture docs ────────────────────────────────────────────
    # feature/docs: yes (tag-filtered) | bug/question: skip
    if mode in ("feature", "docs"):
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

    # ── Project index ──────────────────────────────────────────────────────
    # feature/docs: full (tag-filtered) | bug/testing: minimal | question: tag-filtered
    if mode != "question":
        index = _load_or_generate_index()
        if mode in ("bug", "testing"):
            # Bug mode: minimal — just list counts
            apps = index.get("backend_apps", [])
            routes = index.get("api_routes", [])
            comps = index.get("frontend_components", [])
            print(f"Project: {len(apps)} backend apps, {len(routes)} API routes, {len(comps)} frontend component groups")
            print()
        else:
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

    # ── Architecture doc index ─────────────────────────────────────────────
    # feature: tag-filtered | bug: relevant only | docs: all | question: relevant only
    if mode != "question" or tags:
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
                elif mode == "docs":
                    # docs mode with tags but no matches — show all
                    print("== ARCHITECTURE DOCS (load with: sessions.py context --doc <name>) ==")
                    for entry in arch_index:
                        desc_str = f" \u2014 {entry['description']}" if entry["description"] else ""
                        print(f"  {entry['name']}{desc_str}")
                    print()
            elif mode == "docs":
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

    # ── Instruction docs ───────────────────────────────────────────────────
    # feature/bug/docs: full tag-based loading | question: relevant only (minimal)
    docs_to_load = _resolve_docs_for_tags(tags, include_deploy=False)
    if mode == "question":
        # Question mode: only load docs directly relevant to tags, no full dumps
        docs_to_load = docs_to_load[:2]  # At most 2 docs for question mode

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

    # ── Task completion checklist ──────────────────────────────────────────
    # feature/bug/docs: yes | question: skip
    if mode != "question":
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

    # Mark linked Plane work item as Done when session is intentionally ended.
    _mark_plane_work_item_done(session, sid)

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

    # Extract commit hash (short for display, full for URLs)
    rc, commit_hash, _ = _run_cmd(
        ["git", "rev-parse", "--short", "HEAD"]
    )
    rc, commit_hash_full, _ = _run_cmd(["git", "rev-parse", "HEAD"])
    if rc != 0 or not commit_hash_full:
        commit_hash_full = commit_hash

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
        _mark_plane_work_item_done(session, sid, commit_hash=commit_hash_full)
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


# ---------------------------------------------------------------------------
# Test and Documentation Coverage Commands
# ---------------------------------------------------------------------------

# Test location patterns (aligned with docs/claude/testing.md)
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
        "check-tests": cmd_check_tests,
        "check-docs": cmd_check_docs,
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
