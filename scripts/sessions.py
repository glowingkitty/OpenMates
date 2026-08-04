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
    python3 scripts/sessions.py edit-lease acquire --opencode-session ses_... --file path/to/file.py

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
    python3 scripts/sessions.py visual-smoke --session a3f2 --url https://app.dev.openmates.org/path --viewport laptop --viewport mobile --result passed --method playwright --run-id <artifact> --summary "Reviewed screenshots. Defects: none. Accepted differences: none."

    # Query context docs
    python3 scripts/sessions.py context --list       # list all available docs with line counts
    python3 scripts/sessions.py context --doc <name>
"""

import argparse
import fcntl
import fnmatch
import glob as glob_mod
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _resolve_control_plane_root(checkout_root: Path) -> Path:
    """Resolve the main checkout that owns shared session and lock state."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(checkout_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return checkout_root
    if result.returncode != 0 or not result.stdout.strip():
        return checkout_root
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = checkout_root / common_dir
    common_dir = common_dir.resolve()
    return common_dir.parent if common_dir.name == ".git" else checkout_root


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTROL_PLANE_ROOT = _resolve_control_plane_root(PROJECT_ROOT)
SESSIONS_FILE = CONTROL_PLANE_ROOT / ".claude" / "sessions.json"
TASKS_DIR = CONTROL_PLANE_ROOT / ".claude" / "tasks"
TASKS_META_FILE = TASKS_DIR / ".meta.json"
AGENT_WORKTREES_DIR = CONTROL_PLANE_ROOT / ".openmates-agent-worktrees"
WORKTREE_PATH_PREFIX_RE = re.compile(r"^(?:\.openmates-agent-worktrees|\.agent-worktrees)/agent-[^/]+/")
PROJECT_INDEX_FILE = CONTROL_PLANE_ROOT / ".claude" / "project-index.json"
OPENCODE_STALE_READ_STATE_FILE = CONTROL_PLANE_ROOT / ".opencode" / "stale-read-state.json"
OPENCODE_STALE_READ_LOCK_FILE = CONTROL_PLANE_ROOT / ".opencode" / "stale-read-state.lock"
CODE_MAPPING_FILE = PROJECT_ROOT / "docs" / "architecture" / "code-mapping.yml"
STALE_SESSION_HOURS = 24
STALE_EMPTY_SESSION_HOURS = 6  # Sessions with zero tracked files expire faster
STALE_LOCK_MINUTES = 5
VERCEL_DEPLOY_LOCK_MINUTES = 90
WORKTREE_CLEANUP_IDLE_HOURS = 48
WORKTREE_MANIFEST_RETENTION_HOURS = 30 * 24
WORKTREE_BOOTSTRAP_TIMEOUT_SECONDS = 300
WORKTREE_BINDING_MODES = {"pending", "native", "pilot_fallback", "legacy_grandfathered"}
INTEGRATION_WORKTREE_PREFIX = "integration-"
STALE_DOC_HOURS = 24
RECENT_COMMITS_COUNT = 5  # Number of recent git commits to show at session start
CONTRIBUTING_GUIDES_DIR = PROJECT_ROOT / "docs" / "contributing" / "guides"
CONTRIBUTING_STANDARDS_DIR = PROJECT_ROOT / "docs" / "contributing" / "standards"
DESIGN_GUIDE_DIR = PROJECT_ROOT / "docs" / "design-guide"
ARCH_DOCS_DIR = PROJECT_ROOT / "docs" / "architecture"
ENV_FILE = CONTROL_PLANE_ROOT / ".env"
VISUAL_SMOKE_UI_PATH_RE = re.compile(
    r"^(frontend/packages/ui/src/.+\.(svelte|css|ts)|frontend/apps/web_app/src/routes/.+\.(svelte|css|ts))$"
)
VISUAL_SMOKE_SPEC_PATH_RE = re.compile(r"^docs/specs/.+/spec\.yml$")
VISUAL_SMOKE_HIGH_RISK_RE = re.compile(
    r"(ActiveChat|Chat|MessageInput|Composer|Settings|Share|Embed|Landing|DailyInspiration|Welcome|Auth|Login|Signup|Billing|Usage|Navigation|Header|Sidebar)",
    re.IGNORECASE,
)
VISUAL_SMOKE_PASS_STATUSES = {"passed", "skipped"}
VISUAL_SMOKE_REQUIRED_VIEWPORTS = {"laptop", "mobile"}
VISUAL_SMOKE_REVIEW_RE = re.compile(r"\bscreenshot\w*\b.*\breview\w*\b|\breview\w*\b.*\bscreenshot\w*\b", re.IGNORECASE | re.DOTALL)
VISUAL_SMOKE_DEFECTS_RE = re.compile(r"\b(defects?|issues?|findings?)\s*:", re.IGNORECASE)
VISUAL_SMOKE_ACCEPTED_DIFF_RE = re.compile(r"\baccepted differences?\s*:", re.IGNORECASE)
APPLE_CONTEXT_KEYWORDS = (
    "apple",
    "ios",
    "iphone",
    "ipad",
    "macos",
    "watchos",
    "watch",
    "swift",
    "swiftui",
    "xcode",
    "testflight",
    "native",
)

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


def _current_head() -> str:
    rc, stdout, _ = _run_cmd(["git", "rev-parse", "HEAD"])
    return stdout.strip() if rc == 0 else ""


def _normalize_visual_smoke_viewports(value: object) -> set[str]:
    if isinstance(value, str):
        return {value.strip().lower()} if value.strip() else set()
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return set()


def _visual_smoke_summary_has_review(summary: str) -> bool:
    return bool(
        VISUAL_SMOKE_REVIEW_RE.search(summary)
        and VISUAL_SMOKE_DEFECTS_RE.search(summary)
        and VISUAL_SMOKE_ACCEPTED_DIFF_RE.search(summary)
    )


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


def _format_write_claim_conflict(filepath: str, session_id: str, session_info: dict) -> str:
    """Return an agent-actionable explanation for a live manual write claim."""
    task = session_info.get("task") or "No task description recorded"
    zellij = session_info.get("zellij_session") or "unknown"
    opencode = session_info.get("opencode_session_id") or "unknown"
    last_active = session_info.get("last_active") or ""
    try:
        age = f"{_minutes_since(last_active):.1f} minutes ago" if last_active else "unknown"
    except (ValueError, TypeError):
        age = "unknown"

    return (
        f"BLOCKED: Another live agent has a manual WRITING claim on '{filepath}'.\n"
        f"Task: {task}\n"
        f"Last active: {age}; terminal: {zellij}; OpenCode session: {opencode}; diagnostic id: {session_id}.\n"
        "Agent next step: do not ask the user to interpret this id. Work on non-conflicting files, "
        "check `python3 scripts/sessions.py status`, or retry after the claim is released. "
        "Ask the user only if this exact file blocks all useful progress."
    )


def _opencode_worktree_relative_path(resolved: Path) -> str | None:
    """Return the repo-relative path for a file inside a sessions.py worktree."""
    if not SESSIONS_FILE.is_file():
        return None
    try:
        sessions = json.loads(SESSIONS_FILE.read_text(encoding="utf-8")).get("sessions", {})
    except (json.JSONDecodeError, OSError):
        return None
    candidates: list[Path] = []
    for session in sessions.values():
        worktree_path = session.get("worktree", {}).get("path") if isinstance(session, dict) else None
        if not worktree_path:
            continue
        try:
            candidates.append(Path(worktree_path).resolve())
        except OSError:
            continue
    for worktree in sorted(candidates, key=lambda path: len(path.as_posix()), reverse=True):
        try:
            return resolved.relative_to(worktree).as_posix()
        except ValueError:
            continue
    return None


def normalize_opencode_stale_read_path(raw_path: str | Path) -> str | None:
    """Return a repository-relative regular-file path or None when unsafe."""
    try:
        root = PROJECT_ROOT.resolve()
        candidate = Path(raw_path)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            return _opencode_worktree_relative_path(resolved)
    except (OSError, ValueError):
        return None


def _opencode_stale_read_file_hash(relative_path: str, raw_path: str | Path | None = None) -> str | None:
    if raw_path is not None:
        try:
            candidate = Path(raw_path)
            path = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
            path = path.resolve()
        except OSError:
            path = PROJECT_ROOT / relative_path
    else:
        path = PROJECT_ROOT / relative_path
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _empty_opencode_stale_read_state() -> dict:
    return {"version": 1, "sessions": {}}


def _load_opencode_stale_read_state() -> dict:
    if not OPENCODE_STALE_READ_STATE_FILE.is_file():
        return _empty_opencode_stale_read_state()
    try:
        state = json.loads(OPENCODE_STALE_READ_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_opencode_stale_read_state()
    return state if isinstance(state, dict) and isinstance(state.get("sessions"), dict) else _empty_opencode_stale_read_state()


def _prune_opencode_stale_read_sessions(state: dict) -> None:
    for session_id, session in list(state["sessions"].items()):
        last_active = session.get("last_active", "") if isinstance(session, dict) else ""
        try:
            expired = not last_active or _hours_since(last_active) > STALE_SESSION_HOURS
        except (TypeError, ValueError):
            expired = True
        if expired:
            del state["sessions"][session_id]


def _mutate_opencode_stale_read_state(mutator) -> None:
    """Atomically update OpenCode-only hash metadata without source contents."""
    OPENCODE_STALE_READ_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OPENCODE_STALE_READ_LOCK_FILE.open("a+") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            state = _load_opencode_stale_read_state()
            _prune_opencode_stale_read_sessions(state)
            mutator(state)
            temporary = OPENCODE_STALE_READ_STATE_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            temporary.replace(OPENCODE_STALE_READ_STATE_FILE)
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)


def record_opencode_stale_read(session_id: str, raw_path: str | Path) -> None:
    relative_path = normalize_opencode_stale_read_path(raw_path)
    if not relative_path:
        return
    digest = _opencode_stale_read_file_hash(relative_path, raw_path)
    if not digest:
        return

    def record(state: dict) -> None:
        session = state["sessions"].setdefault(session_id, {"files": {}})
        session["last_active"] = _now_iso()
        session.setdefault("files", {})[relative_path] = {"sha256": digest, "recorded_at": _now_iso()}

    _mutate_opencode_stale_read_state(record)


def sync_opencode_stale_read(session_id: str, raw_path: str | Path) -> None:
    """Refresh the current session baseline after its successful file edit."""
    record_opencode_stale_read(session_id, raw_path)


def opencode_stale_read_error(session_id: str, raw_path: str | Path) -> str | None:
    relative_path = normalize_opencode_stale_read_path(raw_path)
    if not relative_path:
        return None
    expected = _load_opencode_stale_read_state().get("sessions", {}).get(session_id, {}).get("files", {}).get(relative_path, {}).get("sha256")
    if not expected:
        return None
    current = _opencode_stale_read_file_hash(relative_path, raw_path)
    if current and current != expected:
        return f"BLOCKED: {relative_path} changed since this OpenCode session read it. Re-read the file before editing."
    return None


def _load_sessions() -> dict:
    """Load sessions.json, creating it with defaults if missing."""
    if not SESSIONS_FILE.exists():
        SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = _default_sessions()
        _save_sessions(data)
        return data
    try:
        with open(SESSIONS_FILE) as f:
            data = json.load(f)
        _normalize_session_state_paths(data)
        return data
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


def _mutate_sessions(callback):
    """Run one sessions.json read-modify-write transaction under its file lock."""
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = SESSIONS_FILE.with_suffix(".lock")
    with open(lock_path, "a+") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            if SESSIONS_FILE.exists():
                try:
                    with open(SESSIONS_FILE) as sessions_file:
                        data = json.load(sessions_file)
                except (json.JSONDecodeError, OSError):
                    data = _default_sessions()
            else:
                data = _default_sessions()
            _normalize_session_state_paths(data)
            result = callback(data)
            tmp = SESSIONS_FILE.with_suffix(".tmp")
            with open(tmp, "w") as sessions_file:
                json.dump(data, sessions_file, indent=2)
                sessions_file.write("\n")
            tmp.replace(SESSIONS_FILE)
            return result
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def _default_sessions() -> dict:
    """Return a clean default sessions structure."""
    return {
        "locks": {
            "docker_rebuild": {"status": "NONE"},
            "vercel_deploy": {"status": "NONE"},
        },
        "edit_leases": {},
        "deploy_queue": [],
        "worktree_archive": [],
        "worktree_deletion_manifests": [],
        "sessions": {},
    }


def _current_git_sha(cwd: str | Path | None = None) -> str:
    """Return the current git commit for the requested checkout."""
    rc, stdout, stderr = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(cwd) if cwd else None)
    if rc != 0 or not stdout.strip():
        raise RuntimeError(f"Failed to resolve current git commit: {stderr}")
    return stdout.strip()


def _safe_worktree_name(session_id: str) -> str:
    """Return a deterministic local worktree directory name for one session."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-")
    if not safe:
        raise ValueError("session id must contain at least one safe character")
    return f"agent-{safe}"


def _session_worktree_path(session_id: str) -> Path:
    return AGENT_WORKTREES_DIR / _safe_worktree_name(session_id)


def is_valid_managed_worktree_path(path: str | Path) -> bool:
    """Return whether path is one direct managed source-worktree child."""
    candidate = Path(path).resolve()
    root = AGENT_WORKTREES_DIR.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    return len(relative.parts) == 1 and relative.name.startswith("agent-")


def validate_worktree_binding_mode(session: dict) -> str:
    """Validate and return one mutually exclusive worktree binding mode."""
    mode = str(session.get("binding_mode") or "legacy_grandfathered")
    if mode not in WORKTREE_BINDING_MODES:
        raise ValueError(f"Invalid worktree binding mode: {mode}")
    return mode


def bootstrap_session_worktree(worktree_path: str | Path) -> dict:
    """Install cached dependencies and generate prerequisites in one worktree."""
    worktree = Path(worktree_path).resolve()
    commands = [
        [
            "pnpm",
            "install",
            "--offline",
            "--frozen-lockfile",
            "--ignore-scripts",
            "--config.engine-strict=false",
        ],
        ["node", "frontend/packages/ui/scripts/build-tokens.js"],
        ["node", "frontend/packages/ui/scripts/build-translations.js"],
        ["node", "frontend/packages/ui/scripts/validate-locales.js"],
    ]
    started = time.monotonic()
    for index, command in enumerate(commands):
        try:
            rc, stdout, stderr = _run_cmd(
                command,
                cwd=str(worktree),
                timeout=WORKTREE_BOOTSTRAP_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "status": "failed",
                "reason": "dependency_install_failed" if index == 0 else "prerequisite_generation_failed",
                "message": str(exc),
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        if rc != 0:
            return {
                "status": "failed",
                "reason": "dependency_install_failed" if index == 0 else "prerequisite_generation_failed",
                "message": stderr or stdout or f"Command failed: {' '.join(command)}",
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
    return {
        "status": "ready",
        "completed_at": _now_iso(),
        "duration_ms": round((time.monotonic() - started) * 1000),
    }


def ensure_session_worktree(session_id: str) -> dict:
    """Ensure one session has an active local git worktree and metadata."""
    created: dict | None = None

    def existing(data: dict) -> dict | None:
        session = data.get("sessions", {}).get(session_id)
        if not session:
            raise RuntimeError(f"Session {session_id} not found")
        metadata = session.get("worktree")
        if isinstance(metadata, dict) and metadata.get("path") and metadata.get("status") in {"active", "merged"}:
            metadata["last_active"] = _now_iso()
            session["last_active"] = _now_iso()
            return dict(metadata)
        return None

    current = _mutate_sessions(existing)
    if current:
        return current

    base_commit = _current_git_sha()
    path = _session_worktree_path(session_id)
    if not is_valid_managed_worktree_path(path):
        raise RuntimeError(f"Refusing nested or unmanaged session worktree path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        rc, _stdout, stderr = _run_cmd(["git", "worktree", "add", str(path), base_commit])
        if rc != 0:
            raise RuntimeError(f"Failed to create session worktree: {stderr}")
    metadata = {
        "session_id": session_id,
        "path": str(path),
        "base_commit": base_commit,
        "status": "active",
        "created_at": _now_iso(),
        "last_active": _now_iso(),
    }
    session_data = _load_sessions().get("sessions", {}).get(session_id, {})
    if session_data.get("opencode_session_id"):
        metadata["bootstrap"] = bootstrap_session_worktree(path)

    def store(data: dict) -> dict:
        session = data.get("sessions", {}).get(session_id)
        if not session:
            raise RuntimeError(f"Session {session_id} not found")
        session["worktree"] = dict(metadata)
        session["last_active"] = _now_iso()
        return dict(metadata)

    created = _mutate_sessions(store)
    return created


def _worktree_changed_files(metadata: dict) -> list[str]:
    """Return repository-relative files changed in a session worktree."""
    worktree_path = metadata.get("path")
    base_commit = metadata.get("base_commit") or "HEAD"
    if not worktree_path:
        return []
    rc, stdout, stderr = _run_cmd(
        ["git", "diff", "--name-only", str(base_commit), "--"],
        cwd=str(worktree_path),
    )
    if rc != 0:
        raise RuntimeError(f"Failed to inspect worktree diff: {stderr}")
    changed = {line.strip() for line in stdout.splitlines() if line.strip()}
    rc, stdout, stderr = _run_cmd(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(worktree_path),
    )
    if rc != 0:
        raise RuntimeError(f"Failed to inspect worktree untracked files: {stderr}")
    changed.update(line.strip() for line in stdout.splitlines() if line.strip())
    return sorted(changed)


def _worktree_untracked_files(metadata: dict) -> set[str]:
    worktree_path = metadata.get("path")
    if not worktree_path:
        return set()
    rc, stdout, stderr = _run_cmd(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=str(worktree_path),
    )
    if rc != 0:
        raise RuntimeError(f"Failed to inspect worktree untracked files: {stderr}")
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _worktree_has_changes(metadata: dict) -> bool:
    return bool(_worktree_changed_files(metadata))


def _session_deploy_files(session: dict, exclude: set[str]) -> list[str]:
    """Return the deploy file set, preferring the isolated worktree diff."""
    metadata = session.get("worktree")
    if isinstance(metadata, dict) and metadata.get("path"):
        changed = set(_worktree_changed_files(metadata))
        deployed_states = metadata.get("root_applied_files")
        if isinstance(deployed_states, dict):
            current_states = _snapshot_file_states(Path(metadata["path"]), sorted(changed))
            baseline_states = dict(deployed_states)
            missing = [relative_path for relative_path in changed if relative_path not in baseline_states]
            if missing and metadata.get("merged_commit"):
                try:
                    baseline_states.update(_snapshot_worktree_base_states(metadata, missing))
                except RuntimeError:
                    pass
            changed = {
                relative_path
                for relative_path in changed
                if current_states.get(relative_path) != baseline_states.get(relative_path)
            }
        tracked = {_canonical_stored_repo_path(path) for path in session.get("modified_files") or []}
        if tracked:
            changed &= tracked
        return sorted(f for f in changed if f not in exclude)
    dirty_files = _get_dirty_files()
    return sorted(f for f in session.get("modified_files", []) if f in dirty_files and f not in exclude)


def _relative_repo_path_for_session(path_value: str | Path, session: dict | None = None) -> str:
    """Normalize a root or worktree path to a repository-relative file path."""
    stored_path = _canonical_stored_repo_path(path_value)
    if stored_path != str(path_value):
        return stored_path
    candidate = Path(stored_path)
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    metadata = session.get("worktree") if isinstance(session, dict) else None
    worktree_path = metadata.get("path") if isinstance(metadata, dict) else None
    if worktree_path:
        try:
            return resolved.relative_to(Path(worktree_path).resolve()).as_posix()
        except ValueError:
            pass
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        pass
    return stored_path


def _canonical_stored_repo_path(path_value: str | Path) -> str:
    """Strip legacy internal worktree prefixes from a stored repository path."""
    normalized = str(path_value).replace("\\", "/")
    while match := WORKTREE_PATH_PREFIX_RE.match(normalized):
        normalized = normalized[match.end():]
    return normalized


def _normalize_session_state_paths(data: dict) -> None:
    """Canonicalize persisted path keys created by legacy nested-worktree hooks."""
    sessions = data.setdefault("sessions", {})
    for session in sessions.values():
        if not isinstance(session, dict):
            continue
        normalized_files: list[str] = []
        for path_value in session.get("modified_files") or []:
            normalized = _relative_repo_path_for_session(path_value, session)
            if normalized not in normalized_files:
                normalized_files.append(normalized)
        session["modified_files"] = normalized_files
        if session.get("writing"):
            session["writing"] = _relative_repo_path_for_session(session["writing"], session)

    normalized_leases: dict[str, dict] = {}
    for path_value, lease in data.setdefault("edit_leases", {}).items():
        if not isinstance(lease, dict):
            continue
        session = sessions.get(lease.get("session_id"))
        normalized = _relative_repo_path_for_session(path_value, session)
        existing = normalized_leases.get(normalized)
        existing_updated = str((existing or {}).get("last_updated") or (existing or {}).get("since") or "")
        lease_updated = str(lease.get("last_updated") or lease.get("since") or "")
        if existing is None or lease_updated >= existing_updated:
            normalized_leases[normalized] = lease
    data["edit_leases"] = normalized_leases

    active_queue: list[dict] = []
    for item in data.setdefault("deploy_queue", []):
        if not isinstance(item, dict) or item.get("status") != "blocked":
            active_queue.append(item)
            continue
        session = sessions.get(item.get("session_id"))
        worktree = session.get("worktree") if isinstance(session, dict) else None
        if session is not None and (not isinstance(worktree, dict) or worktree.get("status") != "merged"):
            active_queue.append(item)
    data["deploy_queue"] = active_queue


def _resolve_session_id(data: dict, *, session_id: str = "", opencode_session_id: str = "") -> str:
    """Resolve a short sessions.py id from either explicit or OpenCode identity."""
    sessions = data.get("sessions", {})
    if session_id:
        if session_id not in sessions:
            raise RuntimeError(f"Session {session_id} not found")
        return session_id
    if opencode_session_id:
        matches = [sid for sid, info in sessions.items() if info.get("opencode_session_id") == opencode_session_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RuntimeError(f"OpenCode session {opencode_session_id} matches multiple sessions")
    raise RuntimeError("No active sessions.py session found for this OpenCode chat. Run: python3 scripts/sessions.py start --mode feature --task \"...\"")


def _normalize_edit_lease_path(path_value: str | Path, session: dict | None = None) -> str | None:
    """Return a repo-relative file key for root/worktree paths, or None outside the repo."""
    candidate = Path(path_value)
    try:
        resolved = (candidate if candidate.is_absolute() else PROJECT_ROOT / candidate).resolve()
    except OSError:
        resolved = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
    metadata = session.get("worktree") if isinstance(session, dict) else None
    worktree_path = metadata.get("path") if isinstance(metadata, dict) else None
    if worktree_path:
        try:
            return resolved.relative_to(Path(worktree_path).resolve()).as_posix()
        except ValueError:
            pass
    try:
        return _canonical_stored_repo_path(resolved.relative_to(PROJECT_ROOT.resolve()).as_posix())
    except ValueError:
        pass
    return None


def _edit_lease_is_active(lease: dict) -> bool:
    """Return whether an edit lease is still active under the normal lock TTL."""
    last_updated = str(lease.get("last_updated") or lease.get("since") or "")
    try:
        return bool(last_updated and _minutes_since(last_updated) < STALE_LOCK_MINUTES)
    except (TypeError, ValueError):
        return False


def _lease_owner_matches(lease: dict, *, session_id: str = "", opencode_session_id: str = "") -> bool:
    return bool(
        (session_id and lease.get("session_id") == session_id)
        or (opencode_session_id and lease.get("opencode_session_id") == opencode_session_id)
    )


def _prune_stale_edit_leases(data: dict) -> list[str]:
    """Remove expired OpenCode edit leases and return the released file keys."""
    leases = data.setdefault("edit_leases", {})
    released: list[str] = []
    for filepath, lease in list(leases.items()):
        if not isinstance(lease, dict) or not _edit_lease_is_active(lease):
            released.append(filepath)
            leases.pop(filepath, None)
    return released


def _format_edit_lease_conflict(filepath: str, lease: dict, sessions: dict) -> str:
    owner = str(lease.get("session_id") or "unknown")
    info = sessions.get(owner, {}) if isinstance(sessions, dict) else {}
    task = info.get("task") or "No task description recorded"
    opencode = lease.get("opencode_session_id") or info.get("opencode_session_id") or "unknown"
    last_updated = lease.get("last_updated") or lease.get("since") or ""
    try:
        age = f"{_minutes_since(str(last_updated)):.1f} minutes ago" if last_updated else "unknown"
    except (TypeError, ValueError):
        age = "unknown"
    return (
        f"BLOCKED: Another live agent has an edit lease on '{filepath}'.\n"
        f"Task: {task}\n"
        f"Last active: {age}; OpenCode session: {opencode}; diagnostic id: {owner}.\n"
        "Agent next step: do not ask the user to interpret this id. Work on non-conflicting files, "
        "check `python3 scripts/sessions.py status`, or retry after the lease expires/releases. "
        "Ask the user only if this exact file blocks all useful progress."
    )


def _manual_write_claim_conflict(filepath: str, session_id: str, sessions: dict) -> str | None:
    """Return a conflict message when another session has a live manual claim."""
    for other_sid, other_info in sessions.items():
        if other_sid == session_id:
            continue
        if other_info.get("writing") != filepath:
            continue
        last_active = other_info.get("last_active", "")
        try:
            if last_active and _minutes_since(last_active) > STALE_LOCK_MINUTES:
                other_info["writing"] = None
                continue
        except (TypeError, ValueError):
            other_info["writing"] = None
            continue
        return _format_write_claim_conflict(filepath, other_sid, other_info)
    return None


def acquire_edit_leases(*, session_id: str = "", opencode_session_id: str = "", files: list[str]) -> dict:
    """Acquire short-lived multi-file edit leases for one OpenCode edit tool call."""
    now = _now_iso()

    def mutate(data: dict) -> dict:
        sid = _resolve_session_id(data, session_id=session_id, opencode_session_id=opencode_session_id)
        sessions = data.setdefault("sessions", {})
        session = sessions[sid]
        _prune_stale_edit_leases(data)
        normalized_files = sorted(
            {
                normalized
                for raw_file in files
                if (normalized := _normalize_edit_lease_path(raw_file, session))
            }
        )
        if not normalized_files:
            session["last_active"] = now
            return {"session_id": sid, "files": []}

        leases = data.setdefault("edit_leases", {})
        for filepath in normalized_files:
            manual_conflict = _manual_write_claim_conflict(filepath, sid, sessions)
            if manual_conflict:
                raise RuntimeError(manual_conflict)
            existing = leases.get(filepath)
            if isinstance(existing, dict) and _edit_lease_is_active(existing) and not _lease_owner_matches(
                existing,
                session_id=sid,
                opencode_session_id=opencode_session_id,
            ):
                raise RuntimeError(_format_edit_lease_conflict(filepath, existing, sessions))

        for filepath in normalized_files:
            leases[filepath] = {
                "session_id": sid,
                "opencode_session_id": opencode_session_id,
                "since": now,
                "last_updated": now,
            }
            if filepath not in session.get("modified_files", []):
                session.setdefault("modified_files", []).append(filepath)
        session["last_active"] = now
        return {"session_id": sid, "files": normalized_files}

    return _mutate_sessions(mutate)


def release_edit_leases(*, session_id: str = "", opencode_session_id: str = "", files: list[str] | None = None) -> dict:
    """Release matching edit leases. Missing sessions are tolerated for cleanup."""
    def mutate(data: dict) -> dict:
        sid = ""
        session = None
        try:
            sid = _resolve_session_id(data, session_id=session_id, opencode_session_id=opencode_session_id)
            session = data.get("sessions", {}).get(sid)
        except RuntimeError:
            sid = session_id
        normalized_files = None
        if files:
            normalized_files = {
                normalized
                for raw_file in files
                if (normalized := _normalize_edit_lease_path(raw_file, session))
            }
        leases = data.setdefault("edit_leases", {})
        released: list[str] = []
        for filepath, lease in list(leases.items()):
            if normalized_files is not None and filepath not in normalized_files:
                continue
            if not isinstance(lease, dict):
                leases.pop(filepath, None)
                released.append(filepath)
                continue
            if _lease_owner_matches(lease, session_id=sid, opencode_session_id=opencode_session_id):
                leases.pop(filepath, None)
                released.append(filepath)
        if session is not None:
            session["last_active"] = _now_iso()
        return {"session_id": sid, "files": sorted(released)}

    return _mutate_sessions(mutate)


def _worktree_patch_id(metadata: dict, files: list[str] | None = None) -> str:
    """Return a stable identifier for the current worktree diff."""
    worktree_path = metadata.get("path")
    base_commit = metadata.get("base_commit") or "HEAD"
    if not worktree_path:
        return ""
    untracked_files = _worktree_untracked_files(metadata)
    selected_files = set(files) if files is not None else None
    if selected_files is not None:
        untracked_files &= selected_files
        tracked_files = sorted(selected_files - untracked_files)
    else:
        tracked_files = []
    diff_command = ["git", "diff", "--binary", str(base_commit), "--"]
    if files is None or tracked_files:
        result = subprocess.run(
            diff_command + tracked_files,
            cwd=str(worktree_path),
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Failed to hash worktree diff: {detail}")
        diff_bytes = result.stdout
    else:
        diff_bytes = b""
    digest = hashlib.sha256(diff_bytes)
    for relative_path in sorted(untracked_files):
        path = Path(worktree_path) / relative_path
        digest.update(relative_path.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _worktree_root_patch_is_applied(session_id: str, patch_id: str, files: list[str] | None = None) -> bool:
    """Return whether this exact worktree patch was already integrated into root."""
    if files is not None:
        return _worktree_root_patch_action(session_id, patch_id, files) == "applied"
    metadata = _load_sessions().get("sessions", {}).get(session_id, {}).get("worktree")
    return bool(patch_id and isinstance(metadata, dict) and metadata.get("root_applied_patch_id") == patch_id)


def _snapshot_file_states(base_path: Path, files: list[str]) -> dict[str, dict]:
    """Return content and executable-bit state for selected repository files."""
    states: dict[str, dict] = {}
    for relative_path in files:
        path = base_path / relative_path
        if not path.exists():
            states[relative_path] = {"exists": False}
            continue
        if not path.is_file():
            raise RuntimeError(f"Unsupported non-file deploy path: {relative_path}")
        states[relative_path] = {
            "exists": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "executable": bool(path.stat().st_mode & 0o111),
        }
    return states


def _snapshot_worktree_base_states(metadata: dict, files: list[str]) -> dict[str, dict]:
    """Return selected states from the last deploy commit or original source base."""
    worktree_path = Path(str(metadata.get("path") or ""))
    reference_commit = str(metadata.get("merged_commit") or metadata.get("base_commit") or "")
    if not worktree_path.is_dir() or not reference_commit:
        raise RuntimeError("Worktree base metadata is incomplete")
    states: dict[str, dict] = {}
    for relative_path in files:
        content = subprocess.run(
            ["git", "show", f"{reference_commit}:{relative_path}"],
            cwd=str(worktree_path),
            capture_output=True,
            timeout=30,
        )
        if content.returncode != 0:
            states[relative_path] = {"exists": False}
            continue
        mode = subprocess.run(
            ["git", "ls-tree", reference_commit, "--", relative_path],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if mode.returncode != 0 or not mode.stdout.strip():
            raise RuntimeError(f"Could not inspect base file mode: {relative_path}")
        states[relative_path] = {
            "exists": True,
            "sha256": hashlib.sha256(content.stdout).hexdigest(),
            "executable": mode.stdout.split(maxsplit=1)[0] == "100755",
        }
    return states


def _worktree_root_patch_action(session_id: str, patch_id: str, files: list[str]) -> str:
    """Return apply, applied, refresh, or conflict for a worktree integration retry."""
    metadata = _load_sessions().get("sessions", {}).get(session_id, {}).get("worktree")
    if not isinstance(metadata, dict) or not metadata.get("root_applied_patch_id"):
        return "apply"
    if metadata.get("root_applied_patch_id") == patch_id:
        return "applied" if _root_files_match_worktree(metadata, files) else "conflict"
    recorded_states = metadata.get("root_applied_files")
    if not isinstance(recorded_states, dict):
        return "conflict"
    missing_files = [relative_path for relative_path in files if relative_path not in recorded_states]
    base_states: dict[str, dict] = {}
    if missing_files:
        try:
            base_states = _snapshot_worktree_base_states(metadata, missing_files)
        except RuntimeError:
            return "conflict"
    expected = {
        relative_path: recorded_states.get(relative_path, base_states.get(relative_path))
        for relative_path in files
    }
    return "refresh" if _snapshot_file_states(CONTROL_PLANE_ROOT, files) == expected else "conflict"


def _record_worktree_root_patch(session_id: str, patch_id: str, files: list[str] | None = None) -> None:
    """Persist successful root integration so deploy retries are idempotent."""
    if not patch_id:
        raise ValueError("worktree patch id is required")

    def record(data: dict) -> None:
        metadata = data.get("sessions", {}).get(session_id, {}).get("worktree")
        if not isinstance(metadata, dict):
            raise RuntimeError(f"Session {session_id} worktree not found")
        metadata["root_applied_patch_id"] = patch_id
        metadata["root_applied_at"] = _now_iso()
        if files is not None:
            recorded_states = metadata.setdefault("root_applied_files", {})
            recorded_states.update(_snapshot_file_states(CONTROL_PLANE_ROOT, files))

    _mutate_sessions(record)


def _sync_worktree_files_to_root(metadata: dict, files: list[str]) -> None:
    """Refresh selected root files after a safely verified amended worktree retry."""
    worktree_path = metadata.get("path")
    if not worktree_path:
        raise RuntimeError("Session worktree path is missing")
    for relative_path in files:
        source = Path(worktree_path) / relative_path
        destination = CONTROL_PLANE_ROOT / relative_path
        if source.exists():
            if not source.is_file():
                raise RuntimeError(f"Unsupported non-file deploy path: {relative_path}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        elif destination.exists() or destination.is_symlink():
            if not destination.is_file() and not destination.is_symlink():
                raise RuntimeError(f"Unsupported non-file deploy path: {relative_path}")
            destination.unlink()


def _mark_worktree_deployed(
    session_id: str,
    patch_id: str,
    commit_hash: str,
    *,
    integration: dict | None = None,
) -> None:
    """Mark a worktree merged and clear its matching blocked deploy record."""
    def mark(data: dict) -> None:
        metadata = data.get("sessions", {}).get(session_id, {}).get("worktree")
        if isinstance(metadata, dict):
            metadata["status"] = "merged"
            metadata["merged_commit"] = commit_hash
            metadata["last_active"] = _now_iso()
            metadata.pop("pending_commit", None)
            metadata.pop("pending_commit_patch_id", None)
            if integration:
                metadata["integration"] = {
                    "id": integration.get("id"),
                    "patch_id": patch_id,
                    "source_base": integration.get("source_base"),
                    "final_base": integration.get("prepared_base"),
                    "commit": commit_hash,
                    "completed_at": _now_iso(),
                    "status": "merged",
                }
        if patch_id:
            data["deploy_queue"] = [
                item
                for item in data.setdefault("deploy_queue", [])
                if item.get("session_id") != session_id
            ]

    _mutate_sessions(mark)


def _git_is_ancestor(commit: str, target_ref: str) -> bool:
    """Return whether commit is reachable from target_ref."""
    if not commit or not target_ref:
        return False
    rc, _stdout, _stderr = _run_cmd(["git", "merge-base", "--is-ancestor", commit, target_ref])
    return rc == 0


def _record_worktree_pending_commit(session_id: str, patch_id: str, commit_hash: str) -> None:
    """Record a local deploy commit so a failed push can resume safely."""
    if not patch_id or not commit_hash:
        return

    def record(data: dict) -> None:
        metadata = data.get("sessions", {}).get(session_id, {}).get("worktree")
        if not isinstance(metadata, dict) or metadata.get("root_applied_patch_id") != patch_id:
            raise RuntimeError(f"Session {session_id} worktree integration state changed before commit")
        metadata["pending_commit"] = commit_hash
        metadata["pending_commit_patch_id"] = patch_id

    _mutate_sessions(record)


def _pending_worktree_push_commit(
    session_id: str,
    patch_id: str,
    files: list[str],
    dirty_files: list[str],
) -> str:
    """Return an exact clean local commit that should be pushed on deploy retry."""
    metadata = _load_sessions().get("sessions", {}).get(session_id, {}).get("worktree")
    if not isinstance(metadata, dict) or metadata.get("pending_commit_patch_id") != patch_id:
        return ""
    pending_commit = str(metadata.get("pending_commit") or "")
    if not pending_commit or set(files) & set(dirty_files):
        return ""
    rc, head_commit, _stderr = _run_cmd(["git", "rev-parse", "HEAD"])
    if rc != 0:
        return ""
    head_commit = head_commit.strip()
    if head_commit != pending_commit and not _root_files_match_worktree(metadata, files):
        return ""
    if _get_git_status_summary().get("unpushed", 0) <= 0:
        return ""
    return head_commit


def _root_files_match_worktree(metadata: dict, files: list[str]) -> bool:
    """Return whether selected root files exactly match their worktree versions."""
    worktree_path = metadata.get("path")
    if not worktree_path:
        return False
    for relative_path in files:
        source = Path(worktree_path) / relative_path
        destination = CONTROL_PLANE_ROOT / relative_path
        if source.exists() != destination.exists():
            return False
        if not source.exists():
            continue
        if not source.is_file() or not destination.is_file():
            return False
        if source.read_bytes() != destination.read_bytes():
            return False
        if (source.stat().st_mode & 0o111) != (destination.stat().st_mode & 0o111):
            return False
    return True


def _apply_worktree_diff_to_root(metadata: dict, files: list[str]) -> None:
    """Apply selected worktree changes to the root checkout working tree."""
    if not files:
        return
    worktree_path = metadata.get("path")
    base_commit = metadata.get("base_commit") or "HEAD"
    if not worktree_path:
        return
    untracked = _worktree_untracked_files(metadata) & set(files)
    tracked_files = [f for f in files if f not in untracked]
    diff_cmd = ["git", "diff", "--binary", str(base_commit), "--"] + tracked_files
    if tracked_files:
        diff_result = subprocess.run(
            diff_cmd,
            cwd=str(worktree_path),
            capture_output=True,
            text=False,
            timeout=120,
        )
        if diff_result.returncode != 0:
            raise RuntimeError(diff_result.stderr.decode("utf-8", errors="replace").strip())
        if diff_result.stdout:
            apply_result = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=str(CONTROL_PLANE_ROOT),
                input=diff_result.stdout,
                capture_output=True,
                timeout=120,
            )
            if apply_result.returncode != 0:
                raise RuntimeError(apply_result.stderr.decode("utf-8", errors="replace").strip())
    for relative_path in sorted(untracked):
        source = Path(worktree_path) / relative_path
        destination = CONTROL_PLANE_ROOT / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, destination)


class IntegrationConflict(RuntimeError):
    """A selected source patch cannot be reproduced on the requested dev base."""

    def __init__(self, message: str, *, patch_id: str, source_base: str, final_base: str):
        super().__init__(message)
        self.patch_id = patch_id
        self.source_base = source_base
        self.final_base = final_base


def _integration_worktree_path(session_id: str) -> Path:
    """Return a unique direct child reserved for disposable integration state."""
    safe_session_id = re.sub(r"[^a-zA-Z0-9_-]", "-", session_id)[:32] or "unknown"
    return AGENT_WORKTREES_DIR / f"{INTEGRATION_WORKTREE_PREFIX}{safe_session_id}-{secrets.token_hex(6)}"


def _is_integration_worktree_path(path: Path) -> bool:
    """Return whether path is a direct managed disposable integration checkout."""
    try:
        resolved = path.resolve(strict=False)
        parent = AGENT_WORKTREES_DIR.resolve(strict=False)
    except OSError:
        return False
    return bool(
        resolved.parent == parent
        and re.fullmatch(r"integration-[A-Za-z0-9_-]+-[0-9a-f]{12}", resolved.name)
    )


def _remove_integration_worktree(integration: dict) -> None:
    """Remove only a recognized disposable integration worktree."""
    path = Path(str(integration.get("path") or ""))
    if not _is_integration_worktree_path(path):
        raise RuntimeError(f"Refusing to remove unmanaged integration path: {path}")
    if not path.exists():
        return
    rc, _stdout, stderr = _run_cmd(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc != 0:
        raise RuntimeError(f"Could not remove integration worktree {path}: {stderr}")


def _apply_worktree_diff_to_checkout(
    source_metadata: dict,
    files: list[str],
    checkout_root: Path,
    *,
    patch_id: str,
    prepared_base: str,
) -> None:
    """Apply selected source changes to a clean integration checkout and stage them."""
    source_path = Path(str(source_metadata.get("path") or ""))
    source_base = str(source_metadata.get("base_commit") or "")
    if not source_path.is_dir() or not source_base:
        raise RuntimeError("Session source worktree metadata is incomplete")
    current_patch_id = _worktree_patch_id(source_metadata, files)
    if current_patch_id != patch_id:
        raise IntegrationConflict(
            "Session source patch changed during integration preparation",
            patch_id=patch_id,
            source_base=source_base,
            final_base=prepared_base,
        )

    untracked = _worktree_untracked_files(source_metadata) & set(files)
    tracked_files = [relative_path for relative_path in files if relative_path not in untracked]
    if tracked_files:
        diff_result = subprocess.run(
                ["git", "diff", "--binary", source_base, "--", *tracked_files],
                cwd=str(source_path),
                capture_output=True,
                timeout=120,
            )
        if diff_result.returncode != 0:
            raise RuntimeError(diff_result.stderr.decode("utf-8", errors="replace").strip())
        if diff_result.stdout:
            apply_command = ["git", "apply", "--index", "--whitespace=nowarn"]
            if prepared_base != source_base:
                apply_command.append("--3way")
            apply_result = subprocess.run(
                [*apply_command, "-"],
                cwd=str(checkout_root),
                input=diff_result.stdout,
                capture_output=True,
                timeout=120,
            )
            if apply_result.returncode != 0:
                detail = apply_result.stderr.decode("utf-8", errors="replace").strip()
                raise IntegrationConflict(
                    detail or "Selected patch conflicts with current origin/dev",
                    patch_id=patch_id,
                    source_base=source_base,
                    final_base=prepared_base,
                )

    for relative_path in sorted(untracked):
        source = source_path / relative_path
        destination = checkout_root / relative_path
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"Unsupported untracked deploy path: {relative_path}")
        if destination.exists() or destination.is_symlink():
            raise IntegrationConflict(
                f"Untracked source path already exists on current dev: {relative_path}",
                patch_id=patch_id,
                source_base=source_base,
                final_base=prepared_base,
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        rc, _stdout, stderr = _run_cmd(["git", "add", "--", relative_path], cwd=str(checkout_root))
        if rc != 0:
            raise RuntimeError(f"Could not stage untracked deploy path {relative_path}: {stderr}")


def _prepare_integration_worktree(
    session_id: str,
    source_metadata: dict,
    files: list[str],
    patch_id: str,
    prepared_base: str,
) -> dict:
    """Create and populate one disposable exact-base integration checkout."""
    if not files or not patch_id or not prepared_base:
        raise ValueError("Integration preparation requires files, patch ID, and base commit")
    AGENT_WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    path = _integration_worktree_path(session_id)
    integration = {
        "id": path.name,
        "path": str(path),
        "session_id": session_id,
        "patch_id": patch_id,
        "source_base": str(source_metadata.get("base_commit") or ""),
        "prepared_base": prepared_base,
        "files": sorted(files),
        "created_at": _now_iso(),
    }
    rc, _stdout, stderr = _run_cmd(
        ["git", "worktree", "add", "--detach", str(path), prepared_base],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc != 0:
        raise RuntimeError(f"Could not create integration worktree at {prepared_base[:9]}: {stderr}")
    try:
        _apply_worktree_diff_to_checkout(
            source_metadata,
            files,
            path,
            patch_id=patch_id,
            prepared_base=prepared_base,
        )
    except Exception:
        _remove_integration_worktree(integration)
        raise
    return integration


def _rebuild_integration_worktree(
    integration: dict,
    source_metadata: dict,
    files: list[str],
    prepared_base: str,
) -> dict:
    """Discard stale prepared state and reproduce the same patch on a newer base."""
    _remove_integration_worktree(integration)
    return _prepare_integration_worktree(
        str(integration.get("session_id") or "unknown"),
        source_metadata,
        files,
        str(integration.get("patch_id") or ""),
        prepared_base,
    )


def enqueue_worktree_deploy(
    session_id: str,
    title: str,
    patch_id: str,
    *,
    reason: str,
    integration: dict | None = None,
    final_base: str = "",
) -> dict:
    """Record a visible blocked deploy item for manual retry."""
    now = _now_iso()
    item = {
        "id": f"deploy-{session_id}-{hashlib.sha256((patch_id or title).encode('utf-8')).hexdigest()[:10]}",
        "session_id": session_id,
        "title": title,
        "patch_id": patch_id,
        "status": "blocked",
        "reason": reason,
        "created_at": now,
        "updated_at": now,
        "next_action": "Resolve the root integration conflict, then rerun sessions.py deploy.",
    }
    if integration:
        item.update(
            {
                "integration_id": integration.get("id"),
                "source_base": integration.get("source_base"),
                "final_base": final_base or integration.get("prepared_base"),
                "next_action": "Resolve the source patch conflict against current origin/dev, then rerun sessions.py deploy.",
            }
        )

    def store(data: dict) -> dict:
        queue = data.setdefault("deploy_queue", [])
        for existing in queue:
            if existing.get("id") == item["id"]:
                existing.update(item)
                return dict(existing)
        queue.append(dict(item))
        return dict(item)

    return _mutate_sessions(store)


def _validate_managed_worktree_path(path: str | Path) -> Path:
    managed_path = Path(path).resolve()
    if not is_valid_managed_worktree_path(managed_path):
        raise RuntimeError(
            f"Refusing agent worktree outside or nested beneath {AGENT_WORKTREES_DIR}: {managed_path}"
        )
    return managed_path


def _remove_git_worktree(metadata: dict) -> None:
    path = metadata.get("path")
    if not path:
        return
    managed_path = _validate_managed_worktree_path(path)
    rc, _stdout, stderr = _run_cmd(["git", "worktree", "remove", "--force", str(managed_path)])
    if rc != 0:
        raise RuntimeError(f"Failed to remove worktree {managed_path}: {stderr}")
    _run_cmd(["git", "worktree", "prune"])


def _linked_git_worktrees() -> list[dict]:
    """Return linked Git worktrees without changing repository state."""
    rc, stdout, stderr = _run_cmd(["git", "worktree", "list", "--porcelain"])
    if rc != 0:
        raise RuntimeError(f"Failed to list Git worktrees: {stderr}")
    records: list[dict] = []
    current: dict[str, str] = {}
    for line in [*stdout.splitlines(), ""]:
        if not line.strip():
            if current.get("path"):
                records.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value
        elif key == "detached":
            current["detached"] = "true"
    return records


def _worktree_candidate_id(path: str, metadata: dict | None = None) -> str:
    if metadata and metadata.get("session_id"):
        return str(metadata["session_id"])
    name = Path(path).name
    return name.removeprefix("agent-") if name.startswith("agent-") else name


def _candidate_last_active(session: dict | None, metadata: dict | None, path: Path, changed_files: list[str]) -> str:
    timestamps = [
        str((session or {}).get("last_active") or ""),
        str((metadata or {}).get("last_active") or ""),
    ]
    for relative_path in changed_files:
        candidate = path / relative_path
        try:
            timestamps.append(datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except OSError:
            continue
    valid = []
    for value in timestamps:
        if not value:
            continue
        try:
            valid.append((_parse_iso(value), value))
        except (TypeError, ValueError):
            continue
    if valid:
        return max(valid)[1]
    try:
        source_timestamps = [
            os.path.getmtime(child)
            for child in path.iterdir()
            if child.is_file() and child.name != ".git"
        ]
        if source_timestamps:
            return datetime.fromtimestamp(max(source_timestamps), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _candidate_changed_files(path: Path, metadata: dict | None) -> list[str]:
    if not path.exists():
        return []
    effective = dict(metadata or {})
    effective["path"] = str(path)
    effective.setdefault("base_commit", "HEAD")
    return _worktree_changed_files(effective)


def _discover_worktree_candidates() -> list[dict]:
    """Join sessions, linked worktrees, and physical worktree directories."""
    data = _load_sessions()
    sessions = data.get("sessions", {})
    by_path: dict[str, dict] = {}
    for session_id, session in sessions.items():
        metadata = session.get("worktree") if isinstance(session, dict) else None
        if not isinstance(metadata, dict) or not metadata.get("path"):
            continue
        by_path[str(Path(metadata["path"]).resolve())] = {
            "session_id": session_id,
            "session": session,
            "metadata": metadata,
        }

    linked = _linked_git_worktrees()
    managed_root = AGENT_WORKTREES_DIR.resolve()
    paths: dict[str, dict] = {}
    for item in linked:
        resolved = Path(item["path"]).resolve()
        try:
            resolved.relative_to(managed_root)
        except ValueError:
            if str(resolved) not in by_path:
                continue
        paths[str(resolved)] = dict(item)
    if AGENT_WORKTREES_DIR.exists():
        for pattern in ("agent-*", f"{INTEGRATION_WORKTREE_PREFIX}*"):
            for path in AGENT_WORKTREES_DIR.glob(pattern):
                if path.is_dir():
                    paths.setdefault(str(path.resolve()), {"path": str(path.resolve())})
    paths.update({path: {"path": path, **entry} for path, entry in by_path.items() if path not in paths})

    candidates: list[dict] = []
    root = PROJECT_ROOT.resolve()
    for resolved_path, linked_item in sorted(paths.items()):
        path = Path(resolved_path)
        if path == root:
            continue
        registered = by_path.get(resolved_path, {})
        metadata = registered.get("metadata") if isinstance(registered.get("metadata"), dict) else {}
        session = registered.get("session") if isinstance(registered.get("session"), dict) else {}
        session_id = str(registered.get("session_id") or _worktree_candidate_id(resolved_path, metadata))
        worktree_kind = "integration" if _is_integration_worktree_path(path) else "source"
        inspection_error = ""
        try:
            changed_files = _candidate_changed_files(path, metadata)
        except (OSError, RuntimeError) as exc:
            changed_files = []
            inspection_error = str(exc)
        last_active = _candidate_last_active(session, metadata, path, changed_files)
        try:
            idle_hours = _hours_since(last_active) if last_active else float("inf")
        except (TypeError, ValueError):
            idle_hours = float("inf")
        candidates.append(
            {
                "session_id": session_id,
                "path": resolved_path,
                "head": linked_item.get("head", ""),
                "linked": bool(linked_item.get("head")),
                "registered": bool(registered),
                "metadata": metadata,
                "worktree_kind": worktree_kind,
                "binding_mode": validate_worktree_binding_mode(session) if registered else "",
                "last_active": last_active,
                "idle_hours": idle_hours,
                "changed_files": changed_files,
                "inspection_error": inspection_error,
            }
        )
    return candidates


def _target_file_bytes(target_ref: str, relative_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{target_ref}:{relative_path}"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=30,
    )
    return result.stdout if result.returncode == 0 else None


def _worktree_target_files_match(candidate: dict, target_ref: str) -> bool:
    path = Path(candidate.get("path") or "")
    changed_files = candidate.get("changed_files") or []
    if not path.exists() or not changed_files:
        return False
    for relative_path in changed_files:
        local_path = path / relative_path
        target_bytes = _target_file_bytes(target_ref, relative_path)
        if local_path.exists():
            if not local_path.is_file() or target_bytes is None or local_path.read_bytes() != target_bytes:
                return False
        elif target_bytes is not None:
            return False
    return True


def _classify_worktree_candidate(
    candidate: dict,
    target_ref: str,
    idle_threshold: int,
    approved_obsolete: set[str],
) -> dict:
    """Classify one worktree conservatively against an exact dev target."""
    result = dict(candidate)
    session_id = str(result.get("session_id") or "")
    candidate_idle_hours = float(result.get("idle_hours", float("inf")))
    if not result.get("path") or not session_id:
        result.update(classification="malformed", reason_code="missing_identity")
        return result
    if candidate_idle_hours < idle_threshold:
        result.update(classification="recent_active", reason_code="recent_activity")
        return result
    if result.get("worktree_kind") == "integration":
        result.update(classification="disposable_integration", reason_code="reproducible_integration_state")
        return result
    if session_id in approved_obsolete:
        result.update(classification="superseded", reason_code="review_approved_obsolete")
        return result
    if result.get("inspection_error"):
        result.update(classification="malformed", reason_code="inspection_failed")
        return result
    if result.get("classification") in {"integrated", "duplicated", "superseded", "unique_stale", "uncertain"}:
        return result
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    integration = metadata.get("integration") if isinstance(metadata.get("integration"), dict) else {}
    deployed_patch = str(metadata.get("root_applied_patch_id") or integration.get("patch_id") or "")
    merged_commit = str(metadata.get("merged_commit") or "")
    if deployed_patch and merged_commit and _git_is_ancestor(merged_commit, target_ref):
        try:
            current_patch = _worktree_patch_id(metadata)
        except (OSError, RuntimeError):
            current_patch = ""
        if current_patch == deployed_patch:
            result.update(classification="integrated", reason_code="recorded_patch_reachable")
            return result
    if _worktree_target_files_match(result, target_ref):
        result.update(classification="duplicated", reason_code="target_files_match")
        return result
    changed_files = result.get("changed_files") or []
    head = str(result.get("head") or "")
    if not changed_files and head and _git_is_ancestor(head, target_ref):
        result.update(classification="integrated", reason_code="clean_head_reachable")
        return result
    result.update(
        classification="unique_stale" if changed_files else "uncertain",
        reason_code="unique_changes" if changed_files else "unproven_head",
    )
    return result


def _remove_reconciled_worktree(candidate: dict) -> None:
    candidate_path = Path(str(candidate.get("path") or ""))
    path = (
        candidate_path.resolve()
        if _is_integration_worktree_path(candidate_path)
        else _validate_managed_worktree_path(candidate_path)
    )
    rc, _stdout, stderr = _run_cmd(["git", "worktree", "remove", "--force", str(path)])
    if rc != 0 and path.exists():
        if candidate.get("linked"):
            raise RuntimeError(f"Failed to remove worktree {path}: {stderr}")
        shutil.rmtree(path)
    _run_cmd(["git", "worktree", "prune"])


def _refresh_reconciliation_candidate(
    candidate: dict,
    data: dict,
    target_ref: str,
    idle_hours: int,
    approved_obsolete: set[str],
) -> dict:
    """Re-read one deletion candidate while the sessions-state lock is held."""
    session_id = str(candidate.get("session_id") or "")
    current_session = data.get("sessions", {}).get(session_id)
    session = current_session if isinstance(current_session, dict) else {}
    metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else candidate.get("metadata", {})
    path = Path(str((metadata or {}).get("path") or candidate.get("path") or ""))
    fresh = {
        key: value
        for key, value in candidate.items()
        if key not in {"classification", "reason_code", "inspection_error"}
    }
    fresh["path"] = str(path)
    fresh["metadata"] = metadata or {}
    try:
        fresh["changed_files"] = _candidate_changed_files(path, metadata or {})
        fresh["inspection_error"] = ""
    except (OSError, RuntimeError) as exc:
        fresh["changed_files"] = []
        fresh["inspection_error"] = str(exc)
    fresh["last_active"] = _candidate_last_active(session, metadata or {}, path, fresh["changed_files"])
    try:
        fresh["idle_hours"] = _hours_since(fresh["last_active"]) if fresh["last_active"] else float("inf")
    except (TypeError, ValueError):
        fresh["idle_hours"] = float("inf")
    live_lease = any(
        isinstance(lease, dict) and lease.get("session_id") == session_id
        for lease in data.get("edit_leases", {}).values()
    )
    if session.get("writing") or live_lease:
        fresh["idle_hours"] = 0
    return _classify_worktree_candidate(fresh, target_ref, idle_hours, approved_obsolete)


def _prune_deletion_manifests(data: dict) -> None:
    retained = []
    for manifest in data.setdefault("worktree_deletion_manifests", []):
        deleted_at = str(manifest.get("deleted_at") or "")
        try:
            expired = not deleted_at or _hours_since(deleted_at) >= WORKTREE_MANIFEST_RETENTION_HOURS
        except (TypeError, ValueError):
            expired = True
        if not expired:
            retained.append(manifest)
    data["worktree_deletion_manifests"] = retained


def reconcile_session_worktrees(
    *,
    target_ref: str = "origin/dev",
    idle_hours: int = WORKTREE_CLEANUP_IDLE_HOURS,
    apply_safe: bool = False,
    approved_obsolete: set[str] | None = None,
    only_session_ids: set[str] | None = None,
) -> dict:
    """Report or safely apply reconciliation for all known agent worktrees."""
    approved = set(approved_obsolete or set())
    rc, target_commit, stderr = _run_cmd(["git", "rev-parse", target_ref])
    if rc != 0:
        raise RuntimeError(f"Failed to resolve {target_ref}: {stderr}")
    target_commit = target_commit.strip()
    items = []
    for candidate in _discover_worktree_candidates():
        if only_session_ids and str(candidate.get("session_id")) not in only_session_ids:
            continue
        if candidate.get("classification"):
            item = dict(candidate)
            if float(item.get("idle_hours", float("inf"))) < idle_hours:
                item.update(classification="recent_active", reason_code="recent_activity")
        else:
            item = _classify_worktree_candidate(candidate, target_commit, idle_hours, approved)
        items.append(item)

    safe_classes = {"integrated", "duplicated", "superseded", "disposable_integration"}
    deletable = [
        item for item in items
        if item.get("classification") in safe_classes and float(item.get("idle_hours", float("inf"))) >= idle_hours
    ]
    deleted: list[str] = []
    if apply_safe:
        refreshed_by_id: dict[str, dict] = {}

        def record(data: dict) -> None:
            _prune_deletion_manifests(data)
            sessions = data.setdefault("sessions", {})
            queue = data.setdefault("deploy_queue", [])
            manifests = data.setdefault("worktree_deletion_manifests", [])
            for item in deletable:
                fresh = _refresh_reconciliation_candidate(item, data, target_commit, idle_hours, approved)
                session_id = str(fresh["session_id"])
                refreshed_by_id[session_id] = fresh
                if (
                    fresh.get("classification") not in safe_classes
                    or float(fresh.get("idle_hours", float("inf"))) < idle_hours
                ):
                    continue
                try:
                    _remove_reconciled_worktree(fresh)
                except RuntimeError as exc:
                    fresh["classification"] = "cleanup_blocked"
                    fresh["reason_code"] = "remove_failed"
                    fresh["cleanup_error"] = str(exc)
                    continue
                deleted.append(session_id)
                sessions.pop(session_id, None)
                queue[:] = [entry for entry in queue if entry.get("session_id") != session_id]
                manifests.append(
                    {
                        "session_id": session_id,
                        "worktree_name": Path(str(fresh.get("path") or "")).name,
                        "classification": str(fresh.get("classification") or ""),
                        "reason": str(fresh.get("classification") or ""),
                        "reason_code": str(fresh.get("reason_code") or ""),
                        "last_active": str(fresh.get("last_active") or ""),
                        "changed_file_count": len(fresh.get("changed_files") or []),
                        "head": str(fresh.get("head") or ""),
                        "target_commit": target_commit,
                        "deleted_at": _now_iso(),
                    }
                )

        _mutate_sessions(record)
        items = [refreshed_by_id.get(str(item.get("session_id")), item) for item in items]

    unresolved = [item for item in items if str(item.get("session_id")) not in deleted and item not in deletable]
    if not apply_safe:
        unresolved = [item for item in items if item.get("classification") not in safe_classes]
    else:
        unresolved = [item for item in items if str(item.get("session_id")) not in deleted]
    return {
        "target_ref": target_ref,
        "target_commit": target_commit,
        "apply_safe": apply_safe,
        "items": items,
        "deleted": deleted,
        "unresolved": unresolved,
    }


def worktree_release_readiness(*, target_ref: str, excluded_active: set[str]) -> dict:
    report = reconcile_session_worktrees(target_ref=target_ref, apply_safe=False)
    blocked_deploys = [
        str(item.get("id") or item.get("session_id") or "")
        for item in _load_sessions().get("deploy_queue", [])
        if item.get("status") == "blocked"
    ]
    excluded = sorted(
        str(item.get("session_id")) for item in report["items"]
        if item.get("classification") == "recent_active" and str(item.get("session_id")) in excluded_active
    )
    blocking = sorted(
        str(item.get("session_id")) for item in report["items"]
        if not (item.get("classification") == "recent_active" and str(item.get("session_id")) in excluded_active)
    )
    return {
        **report,
        "ready": not blocking and not blocked_deploys,
        "excluded_active": excluded,
        "blocking_worktrees": blocking,
        "blocked_deploys": blocked_deploys,
    }


def finalize_session_worktree(session_id: str, *, target_ref: str = "origin/dev") -> None:
    """Remove a fully integrated worktree before deleting its session record."""
    def finalize(data: dict) -> str:
        session = data.get("sessions", {}).get(session_id)
        if not isinstance(session, dict):
            return "missing"
        metadata = session.get("worktree")
        if not isinstance(metadata, dict) or not metadata.get("path"):
            data.setdefault("sessions", {}).pop(session_id, None)
            return "removed"
        live_lease = any(
            isinstance(lease, dict) and lease.get("session_id") == session_id
            for lease in data.get("edit_leases", {}).values()
        )
        try:
            current_patch = _worktree_patch_id(metadata)
        except (OSError, RuntimeError):
            current_patch = ""
        integration = metadata.get("integration") if isinstance(metadata.get("integration"), dict) else {}
        deployed_patch = str(metadata.get("root_applied_patch_id") or integration.get("patch_id") or "")
        merged_commit = str(metadata.get("merged_commit") or "")
        integrated = (
            not session.get("writing")
            and not live_lease
            and bool(deployed_patch)
            and current_patch == deployed_patch
            and _git_is_ancestor(merged_commit, target_ref)
        )
        if not integrated:
            metadata["status"] = "changes_pending"
            metadata["last_active"] = _now_iso()
            return "pending"
        _remove_git_worktree(metadata)
        data.setdefault("sessions", {}).pop(session_id, None)
        data["deploy_queue"] = [
            item for item in data.setdefault("deploy_queue", []) if item.get("session_id") != session_id
        ]
        return "removed"

    result = _mutate_sessions(finalize)
    if result == "pending":
        raise RuntimeError(f"Session {session_id} worktree has residual or unintegrated changes")


def cleanup_session_worktrees(*, idle_hours: int = WORKTREE_CLEANUP_IDLE_HOURS) -> list[str]:
    """Compatibility wrapper for the safe reconciliation cleanup."""
    return reconcile_session_worktrees(idle_hours=idle_hours, apply_safe=True)["deleted"]


def _is_root_checkout_path(path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(CONTROL_PLANE_ROOT.resolve())
    except ValueError:
        return False
    return not relative.parts or relative.parts[0] not in {AGENT_WORKTREES_DIR.name, ".agent-worktrees"}


def evaluate_root_guard(action: str, target_path: str | Path, *, session_id: str = "") -> dict:
    """Return allow/warn/block for source operations attempted from root."""
    if action == "control-plane":
        return {"decision": "allow", "message": "control-plane operation allowed"}
    mode = os.environ.get("OPENMATES_ROOT_GUARD", "strict").strip().lower()
    if mode in {"off", "0", "false"}:
        return {"decision": "allow", "message": "root guard disabled"}
    target = Path(target_path)
    if not _is_root_checkout_path(target):
        return {"decision": "allow", "message": "target is outside root checkout"}
    command = f"python3 scripts/sessions.py worktree ensure --session {session_id or '<id>'}"
    message = (
        "Root checkout is the OpenMates control plane. Use the session worktree for source edits: "
        f"{command}"
    )
    if mode == "strict":
        return {"decision": "block", "message": message}
    return {"decision": "warn", "message": message}


def _prune_stale(data: dict) -> list[str]:
    """Remove sessions older than STALE_SESSION_HOURS. Returns list of pruned IDs."""
    pruned = []
    to_remove = []
    for sid, session in data.get("sessions", {}).items():
        worktree = session.get("worktree")
        if (
            isinstance(worktree, dict)
            and worktree.get("path")
            and worktree.get("status") in {"active", "merged"}
        ):
            continue
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
            stale_minutes = _lock_stale_minutes(lock_type)
            if last_updated and _minutes_since(last_updated) > stale_minutes:
                data["locks"][lock_type] = {"status": "NONE"}
                cleared.append(lock_type)
    return cleared


def _lock_stale_minutes(lock_type: str) -> int:
    """Return lock-specific stale timeout in minutes."""
    if lock_type == "vercel_deploy":
        return VERCEL_DEPLOY_LOCK_MINUTES
    return STALE_LOCK_MINUTES


def _is_lock_active(lock: dict, lock_type: str) -> bool:
    if lock.get("status") != "IN_PROGRESS":
        return False
    last_updated = lock.get("last_updated", "")
    return bool(last_updated and _minutes_since(last_updated) < _lock_stale_minutes(lock_type))


def _format_lock_block_message(lock_type: str, lock: dict) -> str:
    commit = str(lock.get("commit_sha") or "")
    commit_text = f", commit {commit[:9]}" if commit else ""
    return (
        f"BLOCKED: {lock_type} lock held by {lock.get('claimed_by', '?')}"
        f"{commit_text} (since {lock.get('since', '?')}, updated {lock.get('last_updated', '?')}). "
        "Wait for the root deploy push to finish, or run "
        f"`python3 scripts/sessions.py unlock --session <id> --type {_lock_type_short_name(lock_type)}` "
        "if you have confirmed the deploy is no longer active."
    )


def _lock_type_short_name(lock_type: str) -> str:
    if lock_type == "vercel_deploy":
        return "vercel"
    if lock_type == "docker_rebuild":
        return "docker"
    return lock_type


def _acquire_session_lock(lock_type: str, session_id: str, *, commit_sha: str = "", phase: str = "") -> bool:
    """Atomically acquire a shared session lock, or raise RuntimeError if active."""
    now = _now_iso()

    def mutate(data: dict) -> bool:
        locks = data.setdefault("locks", {})
        lock = locks.get(lock_type, {})
        if _is_lock_active(lock, lock_type):
            same_owner = lock.get("claimed_by") == session_id
            same_commit = not commit_sha or not lock.get("commit_sha") or lock.get("commit_sha") == commit_sha
            if same_owner and same_commit:
                lock["last_updated"] = now
                if commit_sha:
                    lock["commit_sha"] = commit_sha
                elif phase in {"integrating_worktree", "preparing_commit"}:
                    lock.pop("commit_sha", None)
                if phase:
                    lock["phase"] = phase
                locks[lock_type] = lock
                return False
            raise RuntimeError(_format_lock_block_message(lock_type, lock))
        if lock.get("status") == "IN_PROGRESS":
            print(
                f"Warning: Taking over stale {lock_type} lock from {lock.get('claimed_by', '?')}.",
                file=sys.stderr,
            )
        locks[lock_type] = {
            "status": "IN_PROGRESS",
            "claimed_by": session_id,
            "since": now,
            "last_updated": now,
        }
        if commit_sha:
            locks[lock_type]["commit_sha"] = commit_sha
        if phase:
            locks[lock_type]["phase"] = phase
        return True

    return _mutate_sessions(mutate)


def _release_session_lock(lock_type: str, *, commit_sha: str = "", released_by: str = "") -> bool:
    """Release a shared lock when the optional commit matches."""
    def mutate(data: dict) -> bool:
        lock = data.setdefault("locks", {}).get(lock_type, {})
        if lock.get("status") != "IN_PROGRESS":
            return False
        if commit_sha and lock.get("commit_sha") and lock.get("commit_sha") != commit_sha:
            return False
        data["locks"][lock_type] = {
            "status": "NONE",
            "last_released": _now_iso(),
            "released_by": released_by or "sessions.py",
        }
        if commit_sha:
            data["locks"][lock_type]["released_commit_sha"] = commit_sha
        return True

    return _mutate_sessions(mutate)


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
        cwd=cwd or str(CONTROL_PLANE_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _load_env_pairs(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE pairs from an env file without printing secrets."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return result
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _get_vercel_token_for_deploy_gate() -> str:
    token = os.environ.get("VERCEL_TOKEN", "")
    if token:
        return token
    return _load_env_pairs(ENV_FILE).get("VERCEL_TOKEN", "")


def _load_web_app_vercel_project_config() -> tuple[str, str]:
    project_json = CONTROL_PLANE_ROOT / "frontend" / "apps" / "web_app" / ".vercel" / "project.json"
    try:
        data = json.loads(project_json.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"Vercel project config missing: {project_json}") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Could not read Vercel project config: {exc}") from exc

    team_id = str(data.get("orgId") or "")
    project_id = str(data.get("projectId") or "")
    if not team_id or not project_id:
        raise RuntimeError("Vercel project config must include orgId and projectId")
    return team_id, project_id


def _extract_vercel_build_machine(project: dict) -> tuple[str, str]:
    resource_config = project.get("resourceConfig") or {}
    build_machine_type = str(resource_config.get("buildMachineType") or "").lower()
    build_machine_selection = str(resource_config.get("buildMachineSelection") or "").lower()
    return build_machine_type, build_machine_selection


def _extract_vercel_node_version(project: dict) -> str:
    return str(project.get("nodeVersion") or "")


def _fetch_vercel_project_settings(token: str, team_id: str, project_id: str) -> dict:
    url = f"https://api.vercel.com/v9/projects/{project_id}?teamId={team_id}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Vercel project API returned HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not query Vercel project settings: {exc}") from exc


def _enforce_vercel_standard_build_machine() -> None:
    """Hard gate deploys so a push cannot trigger paid Turbo/Elastic builds."""
    token = _get_vercel_token_for_deploy_gate()
    if not token:
        raise RuntimeError("VERCEL_TOKEN is required to verify the web app build machine before deploy")

    team_id, project_id = _load_web_app_vercel_project_config()
    project = _fetch_vercel_project_settings(token, team_id, project_id)
    build_machine_type, build_machine_selection = _extract_vercel_build_machine(project)
    node_version = _extract_vercel_node_version(project)

    if build_machine_type != "standard" or build_machine_selection != "fixed":
        raise RuntimeError(
            "Vercel web app build machine must be standard/fixed before deploy; "
            f"current buildMachineType={build_machine_type or '<missing>'}, "
            f"buildMachineSelection={build_machine_selection or '<missing>'}. "
            "Fix Vercel Project Settings > Build Machine before pushing."
        )

    if node_version != "24.x":
        raise RuntimeError(
            "Vercel web app Node.js version must be 24.x before deploy; "
            f"current nodeVersion={node_version or '<missing>'}. "
            "Fix Vercel Project Settings > General > Node.js Version before pushing."
        )


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
    # Call subprocess directly instead of _run_cmd to preserve leading whitespace.
    # _run_cmd calls .strip() on stdout which removes the leading space from the
    # first line's porcelain status code (e.g., " M file" becomes "M file"),
    # breaking the fixed-offset parsing at line[3:].
    result = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=str(CONTROL_PLANE_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    dirty = set()
    if result.returncode != 0 or not result.stdout:
        return dirty
    for line in result.stdout.splitlines():
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


def _get_staged_files(*, checkout_root: Path | None = None) -> set[str]:
    """Return set of file paths currently in the git index (staged for commit)."""
    rc, stdout, _ = _run_cmd(
        ["git", "diff", "--name-only", "--cached"],
        cwd=str(checkout_root or CONTROL_PLANE_ROOT),
    )
    if rc != 0 or not stdout:
        return set()
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _validate_staged_deploy_files(
    to_commit: set[str],
    *,
    context: str,
    checkout_root: Path | None = None,
) -> bool:
    """Ensure the staged index still points at exactly this deploy's file set."""
    staged_files = (
        _get_staged_files()
        if checkout_root is None
        else _get_staged_files(checkout_root=checkout_root)
    )
    missing_staged = sorted(to_commit - staged_files)
    foreign_staged = sorted(staged_files - to_commit)
    if not missing_staged and not foreign_staged:
        return True

    print(
        f"Staged index changed {context}; aborting to avoid committing the wrong files:",
        file=sys.stderr,
    )
    if missing_staged:
        print("  Missing staged deploy file(s):", file=sys.stderr)
        for f in missing_staged:
            print(f"    - {f}", file=sys.stderr)
    if foreign_staged:
        print("  Foreign staged file(s):", file=sys.stderr)
        for f in foreign_staged:
            print(f"    - {f}", file=sys.stderr)
    print("Restage the intended files and rerun deploy.", file=sys.stderr)
    return False


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
    """Fetch the most recent unprocessed issues in compact format."""
    cmd = [
        "docker", "exec", "api",
        "python", "/app/backend/scripts/debug.py",
        "issue", "--recent", str(limit),
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=30)
    if rc != 0 or not stdout.strip():
        return "  (could not fetch recent issues)"
    return stdout.strip()


def _is_apple_session_context(mode: str, tags: list[str], task: str | None) -> bool:
    """Return whether session startup should include Apple crash context."""
    if mode not in ("feature", "bug", "testing"):
        return False
    haystack = " ".join([task or "", *tags]).lower()
    return any(keyword in haystack for keyword in APPLE_CONTEXT_KEYWORDS)


def _prefetch_testflight_crashes(limit: int = 3) -> str:
    """Fetch a sanitized recent TestFlight crash summary via the Apple remote wrapper."""
    cmd = [
        "python3",
        str(PROJECT_ROOT / "scripts" / "apple_remote.py"),
        "testflight-crashes",
        "--limit",
        str(limit),
    ]
    rc, stdout, stderr = _run_cmd(cmd, timeout=20)
    if rc != 0 or not stdout.strip():
        detail = (stderr or stdout or "not configured or unreachable").strip().splitlines()[0]
        return f"  (could not fetch TestFlight crashes: {detail[:160]})"
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


# ── Linear integration helpers ────────────────────────────────────────────


def _linear_start_integration(
    sid: str,
    data: dict,
    mode: str,
    task: str | None,
    linear_issue_arg: str | None,
) -> None:
    """
    Handle Linear issue linking at session start.

    If --linear-issue is given, fetches the issue and marks it In Progress.
    If omitted but --task is set and LINEAR_API_KEY exists, auto-creates an issue.
    All failures are non-fatal (prints warnings, never blocks session start).
    """
    try:
        # Ensure scripts/ is on sys.path for the sibling module import
        _scripts_dir = str(Path(__file__).parent)
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from _linear_client import (
            get_api_key, get_issue,
            update_issue_status, add_label, post_comment,
        )
    except ImportError:
        if linear_issue_arg:
            print("Warning: _linear_client.py not found; skipping Linear integration.", file=sys.stderr)
        return

    if not get_api_key():
        if linear_issue_arg:
            print("Warning: LINEAR_API_KEY not set; skipping Linear integration.", file=sys.stderr)
        return

    issue_data = None
    linear_issue_id = None  # UUID for mutations

    if linear_issue_arg:
        # User provided an existing issue identifier (e.g., OPE-42)
        issue_data = get_issue(linear_issue_arg)
        if not issue_data:
            print(f"Warning: Could not fetch Linear issue {linear_issue_arg}; continuing without it.", file=sys.stderr)
            return
        linear_issue_id = issue_data["id"]
    elif task and task != "(pending)":
        # Reminder for the running Claude session to follow the Linear task workflow
        # in .claude/rules/linear-tasks.md (search for existing task before creating)
        print("  Linear: No issue linked to this session. Pass --issue OPE-XX next time to link one.", file=sys.stderr)
        return

    if not linear_issue_id:
        return

    # Store in session record
    identifier = issue_data.get("identifier", linear_issue_arg or "")
    data["sessions"][sid]["linear_issue_id"] = identifier
    data["sessions"][sid]["linear_uuid"] = linear_issue_id

    def store_linear_binding(current: dict) -> None:
        if sid not in current.get("sessions", {}):
            raise RuntimeError(f"Session {sid} ended before Linear linking completed")
        current["sessions"][sid]["linear_issue_id"] = identifier
        current["sessions"][sid]["linear_uuid"] = linear_issue_id

    _mutate_sessions(store_linear_binding)

    # Mark In Progress + add label
    update_issue_status(linear_issue_id, "In Progress")
    label_ids = issue_data.get("label_ids", [])
    add_label(linear_issue_id, current_label_ids=label_ids)

    # Post pickup comment (include Zellij attach info)
    post_comment(
        linear_issue_id,
        f"Picked up by Claude session `{sid}`\n\n"
        f"Resume: `claude --resume {sid}`\n"
        f"Zellij: `zellij attach session-{sid}`\n"
        f"Web UI: http://localhost:8082",
    )

    # Display issue context in session output
    display_lines = [f"  Issue:    {identifier}"]
    if issue_data.get("title"):
        display_lines.append(f"  Title:    {issue_data['title']}")
    if issue_data.get("url"):
        display_lines.append(f"  URL:      {issue_data['url']}")
    if issue_data.get("assignee"):
        display_lines.append(f"  Assignee: {issue_data['assignee']}")
    if issue_data.get("description"):
        # Show first 3 lines of description
        desc_lines = issue_data["description"].strip().splitlines()[:3]
        display_lines.append(f"  Desc:     {desc_lines[0]}")
        for dl in desc_lines[1:]:
            display_lines.append(f"            {dl}")
    display_lines.append("  Status:   → In Progress (auto-updated)")

    print(_box_section("LINEAR ISSUE", display_lines))


def _linear_complete_session(
    sid: str,
    session: dict,
    commit_sha: str | None = None,
) -> None:
    """
    Handle Linear issue completion at session end or deploy --end.

    Posts a summary comment, removes claude-is-working label, and updates
    status to In Review (code changes) or Done (docs/question).
    All failures are non-fatal.
    """
    linear_id = session.get("linear_issue_id")
    if not linear_id:
        return

    try:
        _scripts_dir = str(Path(__file__).parent)
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from _linear_client import (
            get_api_key, get_issue, update_issue_status,
            remove_label, post_comment,
        )
    except ImportError:
        return

    if not get_api_key():
        return

    # Fetch current issue state to get UUID and current labels
    issue_data = get_issue(linear_id)
    if not issue_data:
        # Fallback: try using stored UUID directly
        linear_uuid = session.get("linear_uuid")
        if not linear_uuid:
            print(f"Warning: Could not fetch Linear issue {linear_id} for completion.", file=sys.stderr)
            return
        # Proceed with UUID but no label context
        issue_data = {"id": linear_uuid, "label_ids": []}

    issue_uuid = issue_data["id"]
    modified = session.get("modified_files", [])
    mode = session.get("mode", "feature")

    # Build summary comment
    summary_lines = [f"Session `{sid}` completed."]
    if commit_sha:
        summary_lines.append(f"Commit: `{commit_sha}` on `dev`")
    if modified:
        summary_lines.append(f"Files changed: {len(modified)}")
        for f in modified[:10]:
            summary_lines.append(f"- `{f}`")
        if len(modified) > 10:
            summary_lines.append(f"- ... and {len(modified) - 10} more")

    post_comment(issue_uuid, "\n".join(summary_lines))

    # Remove claude-is-working label
    label_ids = issue_data.get("label_ids", [])
    remove_label(issue_uuid, current_label_ids=label_ids)

    # Update status based on mode
    if mode in ("docs", "question"):
        update_issue_status(issue_uuid, "Done")
    else:
        update_issue_status(issue_uuid, "In Review")

    print(f"  Linear: {linear_id} → {'Done' if mode in ('docs', 'question') else 'In Review'}")


def bind_opencode_session(data: dict, session_id: str, opencode_session_id: str) -> None:
    """Bind one authoritative OpenCode chat identity to a repo session."""
    if not re.fullmatch(r"ses_[A-Za-z0-9]+", opencode_session_id):
        raise ValueError(f"Invalid OpenCode session ID: {opencode_session_id}")
    sessions = data.get("sessions", {})
    if session_id not in sessions:
        raise ValueError(f"Unknown repo session ID: {session_id}")
    for other_id, session in sessions.items():
        if other_id != session_id and session.get("opencode_session_id") == opencode_session_id:
            session["opencode_session_id"] = None
    sessions[session_id]["opencode_session_id"] = opencode_session_id


def record_worktree_binding(
    *,
    opencode_session_id: str,
    mode: str,
    directory: str = "",
    reason: str = "",
) -> dict:
    """Persist one native or pilot-fallback binding result atomically."""
    if mode not in {"native", "pilot_fallback"}:
        raise ValueError(f"Unsupported binding result mode: {mode}")

    def update(data: dict) -> dict:
        session_id = _resolve_session_id(data, opencode_session_id=opencode_session_id)
        session = data["sessions"][session_id]
        worktree = session.get("worktree") or {}
        expected = Path(str(worktree.get("path") or "")).resolve()
        if mode == "native" and (not directory or Path(directory).resolve() != expected):
            raise RuntimeError("Native OpenCode directory does not match the session worktree")
        session["binding_mode"] = mode
        session["binding_updated_at"] = _now_iso()
        session["binding_failure_reason"] = reason if mode == "pilot_fallback" else ""
        session["last_active"] = _now_iso()
        return {"session_id": session_id, "mode": mode, "worktree_path": str(expected), "reason": reason}

    return _mutate_sessions(update)


def register_session_record(
    session_record: dict,
    opencode_session_id: str | None = None,
) -> tuple[str, list[str], list[str], dict]:
    """Atomically register one repo session and its authoritative OpenCode chat."""
    def register(data: dict) -> tuple[str, list[str], list[str], dict]:
        pruned = _prune_stale(data)
        cleared_locks = _prune_stale_locks(data)
        session_id = secrets.token_hex(2)
        attempts = 0
        while session_id in data.get("sessions", {}) and attempts < 10:
            session_id = secrets.token_hex(2)
            attempts += 1
        if session_id in data.get("sessions", {}):
            raise RuntimeError("Could not generate a unique session ID")
        data["sessions"][session_id] = dict(session_record)
        if opencode_session_id:
            bind_opencode_session(data, session_id, opencode_session_id)
        return session_id, pruned, cleared_locks, data

    return _mutate_sessions(register)


def cmd_start(args: argparse.Namespace) -> None:
    """Start a new session with tag-based doc preloading and git context."""
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
    linked_task = _load_task(task_id_arg) if task_id_arg else None
    if task_id_arg and not linked_task:
        print(f"Warning: --task-id {task_id_arg!r} not found; ignoring.", file=sys.stderr)
        task_id_arg = None

    # Register session
    #
    # `zellij_session`: captured from $ZELLIJ_SESSION_NAME so the auto-track
    # hook can deterministically identify which Claude Code instance fired
    # it (each parallel instance lives in its own Zellij tab named claude1,
    # claude2, ...). See cmd_track for the resolution logic. None when the
    # session is started outside Zellij (CI runners, bare ssh shells), in
    # which case auto-tracking gracefully degrades to silent no-op rather
    # than the previous race-prone max(last_active) fallback that caused
    # ghost ownership across unrelated sessions.
    opencode_session_id = getattr(args, "opencode_session", None)
    session_record: dict = {
        "task": args.task or "(pending)",
        "mode": mode,
        "tags": tags,
        "started": _now_iso(),
        "last_active": _now_iso(),
        "modified_files": [],
        "writing": None,
        "task_id": task_id_arg,
        "linear_issue_id": None,
        "zellij_session": os.environ.get("ZELLIJ_SESSION_NAME"),
        "opencode_session_id": None,
        "binding_mode": "pending" if opencode_session_id and mode != "question" else "legacy_grandfathered",
    }
    sid, pruned, cleared_locks, data = register_session_record(
        session_record,
        opencode_session_id,
    )
    worktree_metadata: dict | None = None
    worktree_error = ""
    if mode != "question":
        try:
            worktree_metadata = ensure_session_worktree(sid)
            data = _load_sessions()
        except (RuntimeError, OSError, ValueError) as exc:
            worktree_error = str(exc)

    # Link task file to this session if --task-id was given
    if linked_task:
        linked_task["session"] = sid
        _save_task(linked_task)

    # ── Linear integration ────────────────────────────────────────────────
    linear_issue_id = getattr(args, "linear_issue", None)
    _linear_start_integration(sid, data, mode, args.task, linear_issue_id)

    # ── Zellij integration ────────────────────────────────────────────────
    # NOTE: We no longer create a Zellij session on start. The CLI already
    # runs inside a Zellij session (claude1, claude2, etc). Creating extra
    # sessions caused unbounded session accumulation and OOM on the server.
    # Poller-spawned sessions still create their own Zellij sessions via
    # spawn_claude_session().

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
    # Session file lists record commit scope, not exclusive ownership.
    tracked_by = {}
    for other_sid, other_info in data.get("sessions", {}).items():
        if other_sid == sid:
            continue
        for wf in workflow_dirty:
            if wf in other_info.get("modified_files", []):
                tracked_by[wf] = other_sid

    # ── Header block ──────────────────────────────────────────────────────
    git_status = _get_git_status_summary()
    branch_info = git_status["branch"]
    if git_status["tracking"]:
        branch_info += f" ({git_status['tracking']})"
    uncommitted = git_status.get("uncommitted", [])

    linear_linked = data["sessions"][sid].get("linear_issue_id")
    header_lines = [
        f"  Mode:  {mode}",
        f"  Tags:  {', '.join(tags) if tags else 'none'}",
        f"  Task:  {args.task or '(pending)'}",
    ]
    if linear_linked:
        header_lines.append(f"  Linear: {linear_linked}")
    zellij_name = data["sessions"][sid].get("zellij_session")
    if zellij_name:
        header_lines.append(f"  Zellij: `zellij attach {zellij_name}` | http://localhost:8082")
    if worktree_metadata:
        header_lines.append(f"  Worktree: {worktree_metadata.get('path')}")
    elif worktree_error:
        header_lines.append(f"  Worktree: creation failed ({worktree_error})")

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

    # Print header
    hdr_bar = "═" * (BOX_WIDTH - len(f"== SESSION {sid} ") - 1)
    print(f"== SESSION {sid} {hdr_bar}")
    print("\n".join(header_lines))
    print("═" * BOX_WIDTH)

    # ── Workflow script modification notice ────────────────────────────────
    if workflow_dirty:
        for wf in workflow_dirty:
            tracked_session = tracked_by.get(wf)
            if tracked_session:
                print(
                    f"NOTICE: {wf} has uncommitted changes (also tracked by session {tracked_session}; advisory only). "
                    "Re-read it before editing."
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
        issue_lines = issues_content.split("\n")
        # Add hint when no specific --issue was provided
        if not getattr(args, "issue", None):
            issue_lines.append("")
            issue_lines.append("Hint: debug.py issue --recent 5  |  debug.py issue <ID> --timeline")
        sections.append(_box_section("ISSUES (last 24h)", issue_lines))

    # ── TESTFLIGHT CRASHES (Apple feature/debug/testing sessions) ──────────
    if _is_apple_session_context(mode, tags, args.task):
        crashes_content = _prefetch_testflight_crashes(limit=3)
        sections.append(_box_section("TESTFLIGHT CRASHES", crashes_content.split("\n")))

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
    # Auto-detect latest test run when --mode testing without explicit --run-id
    if not run_id and mode == "testing":
        last_run_file = RESULTS_DIR / "last-run.json"
        if last_run_file.exists():
            try:
                with open(last_run_file) as _f:
                    lr = json.load(_f)
                auto_run_id = lr.get("run_id", "")
                if auto_run_id:
                    run_id = auto_run_id
                    print(f"  Auto-loaded latest test run: {run_id[:30]}")
            except (json.JSONDecodeError, OSError):
                pass
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
            files_str = f" [TOUCHED: {len(info['modified_files'])} files, advisory]"
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
    # Tag-based docs are now handled by .claude/rules/ (path-scoped, auto-loaded).
    # On-demand loading still available: sessions.py context --doc <name>
    # Deploy-phase docs still loaded via: sessions.py deploy-docs
    docs_for_tags = _resolve_docs_for_tags(tags, include_deploy=False)
    if docs_for_tags:
        print(f"\nDocs available for tags ({', '.join(tags)}): {', '.join(docs_for_tags)}")
        print("  Load any with: sessions.py context --doc <name>")

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

    if not getattr(args, "force", False):
        _enforce_visual_smoke_end_gate(
            sid,
            session,
            modified,
            skip_reason=getattr(args, "skip_visual_smoke_reason", None),
        )

    worktree_backed = isinstance(session.get("worktree"), dict)
    if worktree_backed:
        try:
            finalize_session_worktree(sid)
        except RuntimeError as exc:
            print(f"ERROR: Cannot end session — {exc}", file=sys.stderr)
            print("Deploy all residual worktree changes or let 48-hour reconciliation classify the stale work.", file=sys.stderr)
            sys.exit(1)

    # ── Linear completion ─────────────────────────────────────────────────
    _linear_complete_session(sid, session)

    # ── Zellij cleanup ───────────────────────────────────────────────────
    # NEVER kill the zellij session the current process is attached to —
    # that would destroy the user's own terminal. Only kill spawned sub-sessions.
    zellij_name = session.get("zellij_session")
    if zellij_name:
        current_zellij = os.environ.get("ZELLIJ_SESSION_NAME")
        if current_zellij == zellij_name:
            print(f"  Zellij: keeping session '{zellij_name}' alive (this terminal is attached to it)")
        else:
            try:
                from _zellij_utils import kill_session
                kill_session(zellij_name)
                print(f"  Zellij: session '{zellij_name}' killed")
            except Exception:
                pass

    if not worktree_backed:
        def remove_plain(current: dict) -> None:
            current.setdefault("sessions", {}).pop(sid, None)
            _prune_stale(current)
        _mutate_sessions(remove_plain)

    print(f"Session {sid} ended and removed from sessions.json.")


def cmd_visual_smoke(args: argparse.Namespace) -> None:
    """Record deployed UI visual-smoke evidence for a session."""
    data = _load_sessions()
    sid = args.session
    session = data.get("sessions", {}).get(sid)
    if not session:
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    status = args.result
    summary = (args.summary or "").strip()
    if status in {"passed", "failed", "blocked"} and not summary:
        print("Error: --summary is required for visual smoke records.", file=sys.stderr)
        sys.exit(1)
    if status == "passed":
        if not args.url:
            print("Error: --url is required when --result passed.", file=sys.stderr)
            sys.exit(1)
        if not (args.run_id or args.screenshot):
            print("Error: --run-id or --screenshot is required when --result passed.", file=sys.stderr)
            sys.exit(1)
        viewports = _normalize_visual_smoke_viewports(args.viewport or [])
        missing = sorted(VISUAL_SMOKE_REQUIRED_VIEWPORTS - viewports)
        if missing:
            print(
                "Error: --viewport laptop and --viewport mobile are required when --result passed.",
                file=sys.stderr,
            )
            print(f"Missing viewport(s): {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        if not _visual_smoke_summary_has_review(summary):
            print(
                "Error: passed visual smoke summary must mention screenshot review, Defects:, and Accepted differences:.",
                file=sys.stderr,
            )
            sys.exit(1)
    if status == "skipped" and not (args.reason or summary):
        print("Error: --reason or --summary is required when --result skipped.", file=sys.stderr)
        sys.exit(1)

    commit = args.commit or _current_head()
    method = args.method or "playwright"
    record = {
        "status": status,
        "method": method,
        "urls": args.url or [],
        "viewports": sorted(_normalize_visual_smoke_viewports(args.viewport or [])),
        "run_id": args.run_id or "",
        "screenshots": args.screenshot or [],
        "summary": summary or args.reason,
        "reason": args.reason or "",
        "subject_commit": commit,
        "timestamp": _now_iso(),
    }
    if status == "passed":
        problems = _visual_smoke_pass_record_problems(record)
        if problems:
            print("Error: visual smoke evidence cannot be recorded as passed:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            sys.exit(1)
    session.setdefault("visual_smoke", []).append(record)
    _save_sessions(data)

    print("UI visual smoke recorded:")
    print(f"  session: {sid}")
    print(f"  result: {status}")
    print(f"  method: {method}")
    if commit:
        print(f"  commit: {commit[:9]}")
    for url in record["urls"]:
        print(f"  url: {url}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show current session state."""
    data = _load_sessions()
    _prune_stale(data)
    _prune_stale_locks(data)
    _prune_stale_edit_leases(data)
    _save_sessions(data)

    sessions = data.get("sessions", {})
    locks = data.get("locks", {})
    edit_leases = data.get("edit_leases", {})

    # --json: emit raw sessions dict for machine consumers (e.g. opencode plugin)
    if getattr(args, "json", False):
        dirty_files = _get_dirty_files()
        output = {"sessions": {}, "locks": locks, "edit_leases": edit_leases}
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

    if edit_leases:
        print("Edit leases:")
        for filepath, lease in sorted(edit_leases.items()):
            if not isinstance(lease, dict):
                continue
            print(
                f"  {filepath}: held by {lease.get('session_id', '?')} "
                f"(since {lease.get('since', '?')})"
            )
        print()

    # Sessions
    if not sessions:
        print("No active sessions.")
    else:
        print(f"Registered sessions ({len(sessions)}):")
        for sid, info in sessions.items():
            writing = info.get("writing")
            mod_count = len(info.get("modified_files", []))
            writing_str = f" WRITING: {writing}" if writing else ""
            linked_task = info.get("task_id")
            task_str = f" [task: {linked_task}]" if linked_task else ""
            linear_id = info.get("linear_issue_id")
            linear_str = f" [{linear_id}]" if linear_id else ""
            worktree = info.get("worktree") if isinstance(info.get("worktree"), dict) else {}
            lifecycle = f" [worktree: {worktree.get('status', 'none')}]" if worktree else ""
            print(
                f"  [{sid}] {info.get('task', '?')} "
                f"(touched: {mod_count} files, advisory){task_str}{linear_str}{lifecycle}{writing_str}"
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


def cmd_doctor(args: argparse.Namespace) -> None:
    """Diagnose deploy blockers without mutating git state."""
    data = _load_sessions()
    _prune_stale(data)
    _prune_stale_locks(data)

    sessions = data.get("sessions", {})
    session_id = getattr(args, "session", None) or ""
    dirty_files = sorted(_get_dirty_files())
    staged_files = sorted(_get_staged_files())
    git_summary = _get_git_status_summary()

    tracked_by_file: dict[str, list[str]] = {}
    for sid, info in sessions.items():
        for path in info.get("modified_files", []):
            tracked_by_file.setdefault(path, []).append(sid)

    print("== SESSION DOCTOR ==")
    print(f"Branch: {git_summary.get('branch', 'unknown')} ({git_summary.get('tracking') or 'no upstream status'})")
    print(f"Active sessions: {len(sessions)}")
    if session_id:
        if session_id not in sessions:
            print(f"Session: {session_id} (not found)")
        else:
            print(f"Session: {session_id} — {sessions[session_id].get('task', '?')}")
    print()

    locks = data.get("locks", {})
    active_locks = [(name, lock) for name, lock in locks.items() if lock.get("status") == "IN_PROGRESS"]
    if active_locks:
        print("Active locks:")
        for name, lock in active_locks:
            state = "active" if _is_lock_active(lock, name) else "stale"
            commit = str(lock.get("commit_sha") or "")[:9]
            commit_text = f", commit {commit}" if commit else ""
            print(
                f"  - {name}: {state}, held by {lock.get('claimed_by', '?')}"
                f"{commit_text}, phase {lock.get('phase', '?')}"
            )
        print()

    if staged_files:
        print(f"Staged files ({len(staged_files)}):")
        for path in staged_files:
            owners = tracked_by_file.get(path, [])
            owner_text = f" [tracked by: {', '.join(owners)}]" if owners else " [not tracked by a session]"
            print(f"  - {path}{owner_text}")
        print()

    if dirty_files:
        print(f"Dirty files ({len(dirty_files)}):")
        for path in dirty_files:
            owners = tracked_by_file.get(path, [])
            if session_id:
                if session_id in owners:
                    state = "tracked by this session"
                elif owners:
                    state = f"tracked by other session(s): {', '.join(owners)}"
                else:
                    state = "not tracked by any session"
            else:
                state = f"tracked by: {', '.join(owners)}" if owners else "not tracked by any session"
            print(f"  - {path} [{state}]")
        print()
    else:
        print("Dirty files: none")
        print()

    print("Suggested next commands:")
    if session_id and session_id in sessions:
        print(f"  python3 scripts/sessions.py prepare-deploy --session {session_id}")
        print(f"  python3 scripts/sessions.py track --session {session_id} --file <path>")
        print(f"  python3 scripts/sessions.py deploy --session {session_id} --title \"type: description\" --message \"...\"")
    else:
        print("  python3 scripts/sessions.py status")
        print("  python3 scripts/sessions.py start --mode <feature|bug|docs|testing> --task \"...\"")
        print("  python3 scripts/sessions.py prepare-deploy --session <id>")
    print("== END SESSION DOCTOR ==")


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

    if sid not in data.get("sessions", {}):
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    filepath = _normalize_edit_lease_path(args.file, data["sessions"][sid]) or args.file
    _prune_stale_edit_leases(data)

    stale_claims_cleared = False
    # Check if another session is writing to this file
    for other_sid, other_info in data.get("sessions", {}).items():
        if other_sid == sid:
            continue
        if other_info.get("writing") == filepath:
            last_active = other_info.get("last_active", "")
            if last_active and _minutes_since(last_active) > STALE_LOCK_MINUTES:
                other_info["writing"] = None
                stale_claims_cleared = True
                continue
            print(_format_write_claim_conflict(filepath, other_sid, other_info), file=sys.stderr)
            sys.exit(2)

    for lease_file, lease in data.get("edit_leases", {}).items():
        if lease_file != filepath:
            continue
        if isinstance(lease, dict) and _edit_lease_is_active(lease) and not _lease_owner_matches(lease, session_id=sid):
            print(_format_edit_lease_conflict(filepath, lease, data.get("sessions", {})), file=sys.stderr)
            sys.exit(2)

    if stale_claims_cleared:
        _save_sessions(data)

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


def _resolve_session_from_zellij(sessions: dict) -> Optional[str]:
    """Resolve the current session id from $ZELLIJ_SESSION_NAME.

    Returns:
        The single session id whose `zellij_session` matches the env var.
        None if the env var is unset, no session matches, or more than one
        session matches (caller decides whether to warn or skip).

    Why this exists: the auto-track and pre-edit-guard hooks have no way to
    know *which* Claude Code instance fired them. The previous fallback
    `max(last_active)` was racy across concurrent sessions and caused
    permanent ghost ownership of files in unrelated sessions (chat 7929b948
    incident, OPE-338 follow-up). Each parallel Claude Code instance lives
    in its own Zellij tab (claude1, claude2, ...), and `ZELLIJ_SESSION_NAME`
    is exposed to every child process — including hook scripts. We capture
    it on `cmd_start` and look it up here. Deterministic, no races.
    """
    zellij = os.environ.get("ZELLIJ_SESSION_NAME")
    if not zellij:
        return None
    matches = [
        sid for sid, info in sessions.items()
        if info.get("zellij_session") == zellij
    ]
    if len(matches) == 1:
        return matches[0]
    return None  # 0 matches (no session in this tab) or >1 (ambiguous)


def _resolve_session_identity(sessions: dict) -> Optional[str]:
    """Prefer the exact OpenCode chat identity over the legacy Zellij fallback."""
    opencode_session_id = os.environ.get("OPENCODE_SESSION_ID")
    if opencode_session_id:
        matches = [
            sid
            for sid, info in sessions.items()
            if info.get("opencode_session_id") == opencode_session_id
        ]
        if len(matches) == 1:
            return matches[0]
        return None
    return _resolve_session_from_zellij(sessions)


def cmd_track(args: argparse.Namespace) -> None:
    """Track one or more files as modified by this session (without write lock).

    If --session is omitted, resolves the exact OpenCode chat identity first and
    uses the legacy Zellij identity only when no OpenCode identity is present.
    If no unambiguous match exists, exits silently rather than ghost-attaching a
    file to the wrong session.

    Accepts multiple file paths: --file f1 f2 f3.
    """
    data = _load_sessions()
    sessions = data.get("sessions", {})
    sid = args.session

    if not sid:
        if not sessions:
            return  # No active session — silently ignore
        sid = _resolve_session_identity(sessions)
        if sid is None:
            # Identity unresolved: env var unset, no matching session in this
            # Zellij tab, or ambiguous (multiple sessions sharing one tab).
            # Silently exit. The user can still track explicitly with
            # `track --session <id> --file <path>` if they want to.
            zellij = os.environ.get("ZELLIJ_SESSION_NAME") or "(unset)"
            ambiguous = sum(
                1 for info in sessions.values()
                if info.get("zellij_session") == os.environ.get("ZELLIJ_SESSION_NAME")
            )
            if ambiguous > 1:
                print(
                    f"WARNING: ambiguous Zellij tab '{zellij}' has {ambiguous} "
                    f"sessions.py sessions; refusing to auto-track. "
                    f"Run `sessions.py end <old_id>` to disambiguate.",
                    file=sys.stderr,
                )
            return

    if sid not in sessions:
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    # Normalise to list (nargs="+" gives a list, but legacy single-string callers
    # might still pass a string via programmatic use)
    filepaths_raw = args.file if isinstance(args.file, list) else [args.file]

    for filepath in filepaths_raw:
        filepath = _relative_repo_path_for_session(filepath, sessions.get(sid))

        # Check for collisions with other sessions
        for other_sid, other_info in sessions.items():
            if other_sid == sid:
                continue
            other_files = other_info.get("modified_files", [])
            if filepath in other_files:
                other_task = other_info.get("task", "?")[:60]
                print(
                    f"ADVISORY: File '{filepath}' was also touched by session "
                    f"{other_sid} ('{other_task}'). "
                    "Re-read before editing; this does not reserve the file."
                )

        if filepath not in sessions[sid].get("modified_files", []):
            sessions[sid].setdefault("modified_files", []).append(filepath)
            print(f"Tracked '{filepath}' as modified in session {sid}.")
        else:
            print(f"File '{filepath}' already tracked in session {sid}.")

    if filepaths_raw:
        now = _now_iso()
        sessions[sid]["last_active"] = now
        worktree = sessions[sid].get("worktree")
        if isinstance(worktree, dict):
            worktree["last_active"] = now
            if worktree.get("status") == "merged":
                worktree["status"] = "active"
        data["sessions"] = sessions
        _save_sessions(data)


def cmd_track_stdin(args: argparse.Namespace) -> None:
    """Track a file from PostToolUse hook (reads JSON from stdin).

    Identity resolution: prefers `--session` if given, otherwise resolves
    via `_resolve_session_from_zellij` (matches the calling Claude Code
    instance's $ZELLIJ_SESSION_NAME against the session record's
    `zellij_session` field). Silent exit on no match — better to under-track
    than to attribute the edit to the wrong session.
    """
    data = _load_sessions()

    sessions = data.get("sessions", {})
    if not sessions:
        return  # No active session, silently exit

    sid = args.session
    if not sid:
        sid = _resolve_session_identity(sessions)
        if sid is None:
            return  # Identity unresolvable; silent exit

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

    filepath = _relative_repo_path_for_session(filepath, sessions.get(sid))

    if filepath not in sessions[sid].get("modified_files", []):
        sessions[sid].setdefault("modified_files", []).append(filepath)
    now = _now_iso()
    sessions[sid]["last_active"] = now
    worktree = sessions[sid].get("worktree")
    if isinstance(worktree, dict):
        worktree["last_active"] = now
        if worktree.get("status") == "merged":
            worktree["status"] = "active"
    _save_sessions(data)


def cmd_untrack(args: argparse.Namespace) -> None:
    """Remove file(s) from a session's modified_files list.

    Two modes:
      --file <path> [<path> ...]
          Remove the listed paths from the named session's modified_files.

      --all-ghosts
          Sweep the named session for files that were almost certainly
          ghost-attached by the legacy `max(last_active)` heuristic — i.e.
          files also tracked by another session whose `zellij_session` we
          recognize. Used as a one-time cleanup after upgrading to the
          Zellij-aware identity resolver. Conservative: only removes paths
          that have a clear "real owner" elsewhere.

    Note: this is the opposite of `track`. The existing `release` command
    operates on the single-file write claim (`writing` field), not on the
    `modified_files` list — different semantics, so we use a different name.
    """
    data = _load_sessions()
    sessions = data.get("sessions", {})
    sid = args.session

    if sid not in sessions:
        print(f"Error: Session {sid} not found.", file=sys.stderr)
        sys.exit(1)

    session = sessions[sid]
    modified = session.get("modified_files", [])

    to_remove: list[str] = []

    if getattr(args, "all_ghosts", False):
        # Build the set of "recognized" sessions: any other session that has
        # a non-None zellij_session. Sessions started before the identity
        # fix have zellij_session=None and are NOT considered authoritative.
        recognized_other_files: dict[str, str] = {}
        for other_sid, other_info in sessions.items():
            if other_sid == sid:
                continue
            if not other_info.get("zellij_session"):
                continue
            for f in other_info.get("modified_files", []):
                # First-write-wins: if multiple sessions own it, just pick one
                # for the report. We only need to know SOME other session
                # recognizes it.
                recognized_other_files.setdefault(f, other_sid)
        for f in list(modified):
            owner = recognized_other_files.get(f)
            if owner:
                to_remove.append(f)
                print(
                    f"Ghost candidate: '{f}' is also tracked by session "
                    f"{owner}; removing from {sid}."
                )
    else:
        if not args.file:
            print(
                "Error: untrack requires --file <path> [<path> ...] or "
                "--all-ghosts.",
                file=sys.stderr,
            )
            sys.exit(2)
        # Normalise like cmd_track does, so user-supplied absolute paths and
        # relative paths both work consistently.
        for raw in args.file:
            try:
                filepath = str(Path(raw).resolve().relative_to(PROJECT_ROOT))
            except ValueError:
                filepath = raw
            if filepath in modified:
                to_remove.append(filepath)
            else:
                print(
                    f"File '{filepath}' is not tracked by session {sid}; "
                    f"nothing to remove."
                )

    if not to_remove:
        print(f"No files removed from session {sid}.")
        return

    session["modified_files"] = [f for f in modified if f not in to_remove]
    session["last_active"] = _now_iso()
    _save_sessions(data)
    print(f"Removed {len(to_remove)} file(s) from session {sid}.")


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

    filepath = _normalize_edit_lease_path(filepath) or filepath
    _prune_stale_edit_leases(data)

    # Check if another session is writing to this file
    sessions = data.get("sessions", {})
    for sid, info in sessions.items():
        if info.get("writing") == filepath:
            # Check if the owning session is stale
            last_active = info.get("last_active", "")
            if last_active and _minutes_since(last_active) > STALE_LOCK_MINUTES:
                continue  # Stale session — allow write
            print(_format_write_claim_conflict(filepath, sid, info), file=sys.stderr)
            sys.exit(2)  # Exit 2 = blocking error for Claude hooks

    for lease_file, lease in data.get("edit_leases", {}).items():
        if lease_file == filepath and isinstance(lease, dict) and _edit_lease_is_active(lease):
            print(_format_edit_lease_conflict(filepath, lease, sessions), file=sys.stderr)
            sys.exit(2)

    sys.exit(0)  # Allow


def cmd_edit_lease(args: argparse.Namespace) -> None:
    """Acquire or release OpenCode edit leases around one edit tool call."""
    try:
        if args.edit_lease_action == "acquire":
            result = acquire_edit_leases(
                session_id=getattr(args, "session", None) or "",
                opencode_session_id=getattr(args, "opencode_session", None) or "",
                files=args.file or [],
            )
            print(json.dumps(result, sort_keys=True))
            return
        if args.edit_lease_action == "release":
            result = release_edit_leases(
                session_id=getattr(args, "session", None) or "",
                opencode_session_id=getattr(args, "opencode_session", None) or "",
                files=args.file or None,
            )
            print(json.dumps(result, sort_keys=True))
            return
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    print("Error: unknown edit-lease action", file=sys.stderr)
    sys.exit(1)


def cmd_stale_read(args: argparse.Namespace) -> None:
    """Record, check, or refresh OpenCode-only file-read hash state."""
    if args.stale_read_action == "record":
        record_opencode_stale_read(args.opencode_session, args.file)
        return
    if args.stale_read_action == "sync":
        sync_opencode_stale_read(args.opencode_session, args.file)
        return
    error = opencode_stale_read_error(args.opencode_session, args.file)
    if error:
        print(error, file=sys.stderr)
        sys.exit(2)


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
    sid = args.session
    lock_type = _normalize_lock_type(args.type)

    if lock_type not in ("docker_rebuild", "vercel_deploy"):
        print(
            f"Error: Unknown lock type '{args.type}'. "
            f"Use 'docker' or 'vercel'.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        _acquire_session_lock(lock_type, sid, phase="manual")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Lock '{lock_type}' acquired by session {sid}.")


def cmd_unlock(args: argparse.Namespace) -> None:
    """Release a lock."""
    lock_type = _normalize_lock_type(args.type)

    if lock_type not in ("docker_rebuild", "vercel_deploy"):
        print(
            f"Error: Unknown lock type '{args.type}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    _release_session_lock(lock_type, released_by=args.session)
    print(f"Lock '{lock_type}' released.")


def _active_lock_snapshot(lock_type: str) -> dict:
    """Return the active lock snapshot, or an empty dict when available/stale."""
    data = _load_sessions()
    lock = data.get("locks", {}).get(lock_type, {})
    if _is_lock_active(lock, lock_type):
        return dict(lock)
    return {}


def cmd_wait_lock(args: argparse.Namespace) -> None:
    """Wait for a shared lock to become available instead of verbally pausing."""
    lock_type = _normalize_lock_type(args.type)
    if lock_type not in ("docker_rebuild", "vercel_deploy"):
        print(f"Error: Unknown lock type '{args.type}'.", file=sys.stderr)
        sys.exit(1)

    timeout = args.timeout
    if timeout is None:
        timeout = VERCEL_DEPLOY_LOCK_MINUTES * 60 if lock_type == "vercel_deploy" else STALE_LOCK_MINUTES * 60
    poll = max(1, args.poll)
    deadline = time.time() + max(0, timeout)
    last_report = 0.0

    while True:
        lock = _active_lock_snapshot(lock_type)
        if not lock:
            print(f"Lock '{lock_type}' is available.")
            return

        now = time.time()
        if now >= deadline:
            print(_format_lock_block_message(lock_type, lock), file=sys.stderr)
            print(
                f"Timed out after {timeout}s waiting for lock '{lock_type}'. "
                "Do not force-unlock unless you have confirmed the other deploy/test is inactive.",
                file=sys.stderr,
            )
            sys.exit(1)

        if last_report == 0.0 or now - last_report >= 60:
            commit = str(lock.get("commit_sha") or "")[:9]
            commit_text = f", commit {commit}" if commit else ""
            print(
                f"Waiting for lock '{lock_type}' held by {lock.get('claimed_by', '?')}"
                f"{commit_text}, phase {lock.get('phase', '?')}..."
            )
            last_report = now

        time.sleep(min(poll, max(1, int(deadline - now))))


def _wait_and_acquire_session_lock(
    lock_type: str,
    session_id: str,
    *,
    commit_sha: str = "",
    phase: str = "",
    timeout: int | None = None,
    poll: int = 30,
) -> bool:
    """Wait for a shared lock and acquire it in the same loop to avoid races."""
    if timeout is None:
        timeout = VERCEL_DEPLOY_LOCK_MINUTES * 60 if lock_type == "vercel_deploy" else STALE_LOCK_MINUTES * 60
    poll = max(1, poll)
    deadline = time.time() + max(0, timeout)
    last_report = 0.0
    last_error = ""

    while True:
        try:
            return _acquire_session_lock(lock_type, session_id, commit_sha=commit_sha, phase=phase)
        except RuntimeError as exc:
            last_error = str(exc)

        now = time.time()
        if now >= deadline:
            raise RuntimeError(
                f"{last_error}\nTimed out after {timeout}s waiting for lock '{lock_type}'. "
                "No commit was created. Do not force-unlock unless you have confirmed "
                "the other deploy/test is inactive."
            )

        if last_report == 0.0 or now - last_report >= 60:
            lock = _active_lock_snapshot(lock_type)
            if lock:
                commit = str(lock.get("commit_sha") or "")[:9]
                commit_text = f", commit {commit}" if commit else ""
                print(
                    f"Waiting for lock '{lock_type}' held by {lock.get('claimed_by', '?')}"
                    f"{commit_text}, phase {lock.get('phase', '?')}..."
                )
            last_report = now

        time.sleep(min(poll, max(1, int(deadline - now))))


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
    if ".swift" in exts:
        flags.append("--swift")
    if ".css" in exts:
        flags.append("--css")
    if ".html" in exts:
        flags.append("--html")
    return flags


def _run_lint(files: list[str], *, checkout_root: Path | None = None) -> tuple[int, str, str]:
    """Run linter on specific files. Returns (returncode, stdout, stderr)."""
    lint_flags = _get_lint_flags(files)
    if not lint_flags:
        return 0, "", ""
    path_args: list[str] = []
    for f in files:
        path_args += ["--path", f]
    cmd = ["./scripts/lint_changed.sh"] + lint_flags + path_args
    return _run_cmd(cmd, cwd=str(checkout_root or CONTROL_PLANE_ROOT), timeout=LINT_TIMEOUT)



def _has_frontend_files(files: list) -> bool:
    """Return True if any of the given file paths touch the frontend package."""
    return any(f.startswith("frontend/") for f in files)


def _visual_smoke_ui_files(files: list[str]) -> list[str]:
    """Return changed runtime UI files that may need deployed visual smoke."""
    return [
        f for f in files
        if VISUAL_SMOKE_UI_PATH_RE.search(f)
        and "/tests/" not in f
        and "/__tests__/" not in f
        and not f.endswith((".test.ts", ".spec.ts"))
    ]


def _requires_visual_smoke(files: list[str]) -> bool:
    """Return whether changed files need deployed laptop/mobile UI review."""
    ui_files = _visual_smoke_ui_files(files)
    if not ui_files:
        return False
    if any(VISUAL_SMOKE_SPEC_PATH_RE.search(f) for f in files):
        return True
    if len(ui_files) >= 2:
        return True
    return any(VISUAL_SMOKE_HIGH_RISK_RE.search(Path(f).name) for f in ui_files)


def _commit_matches(record_commit: str, expected_commit: str | None) -> bool:
    if not expected_commit:
        return True
    if not record_commit:
        return False
    return record_commit.startswith(expected_commit) or expected_commit.startswith(record_commit)


def _visual_smoke_artifact_problems(run_id: str) -> list[str]:
    """Inspect local Playwright visual-smoke summary artifacts when available."""
    if not run_id or ":" in run_id:
        return []
    summary_path = Path(run_id)
    if not summary_path.is_absolute():
        summary_path = PROJECT_ROOT / summary_path
    if not summary_path.is_file() or summary_path.name != "summary.json":
        return []
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"could not parse Playwright visual-smoke summary {run_id}: {exc}"]

    problems: list[str] = []
    if summary.get("result") != "passed":
        problems.append(f"Playwright visual-smoke artifact result is {summary.get('result')!r}")
    viewports = _normalize_visual_smoke_viewports(summary.get("viewports") or [])
    if not VISUAL_SMOKE_REQUIRED_VIEWPORTS.issubset(viewports):
        problems.append("Playwright visual-smoke artifact is missing laptop and mobile viewports")
    for index, record in enumerate(summary.get("records") or []):
        if not isinstance(record, dict):
            continue
        record_problems = record.get("problems") or []
        if record_problems:
            problems.append(f"record {index} problems: {' | '.join(str(item) for item in record_problems[:3])}")
        console_errors = record.get("consoleErrors") or []
        if console_errors:
            problems.append(f"record {index} console errors: {' | '.join(str(item) for item in console_errors[:3])}")
    return problems


def _visual_smoke_pass_record_problems(record: dict) -> list[str]:
    problems: list[str] = []
    summary = str(record.get("summary") or "").strip()
    if not summary:
        problems.append("missing summary")
    elif not _visual_smoke_summary_has_review(summary):
        problems.append("summary must state screenshot review, defects, and accepted differences")
    if not (record.get("urls") or record.get("url")):
        problems.append("missing reviewed URL")
    if not (str(record.get("run_id") or "").strip() or record.get("screenshots")):
        problems.append("missing run_id or screenshot artifact")
    if not VISUAL_SMOKE_REQUIRED_VIEWPORTS.issubset(
        _normalize_visual_smoke_viewports(record.get("viewports") or record.get("viewport"))
    ):
        problems.append("missing laptop and mobile viewports")
    problems.extend(_visual_smoke_artifact_problems(str(record.get("run_id") or "")))
    return problems


def _latest_visual_smoke_record(session: dict, expected_commit: str | None = None) -> dict | None:
    records = session.get("visual_smoke")
    if not isinstance(records, list):
        return None
    for record in reversed(records):
        if not isinstance(record, dict):
            continue
        status = str(record.get("status") or "").strip()
        if status not in VISUAL_SMOKE_PASS_STATUSES:
            continue
        if status == "skipped" and not str(record.get("reason") or record.get("summary") or "").strip():
            continue
        if status == "passed" and _visual_smoke_pass_record_problems(record):
            continue
        if _commit_matches(str(record.get("subject_commit") or ""), expected_commit):
            return record
    return None


def _record_visual_smoke_skip(session: dict, reason: str, commit_sha: str | None = None) -> None:
    session.setdefault("visual_smoke", []).append(
        {
            "status": "skipped",
            "reason": reason,
            "summary": reason,
            "subject_commit": commit_sha or _current_head(),
            "timestamp": _now_iso(),
        }
    )


def _enforce_visual_smoke_end_gate(
    sid: str,
    session: dict,
    files: list[str],
    *,
    skip_reason: str | None = None,
    commit_sha: str | None = None,
) -> None:
    if not _requires_visual_smoke(files):
        return
    expected_commit = commit_sha or _current_head()
    if skip_reason:
        _record_visual_smoke_skip(session, skip_reason, expected_commit)
        print(f"UI visual smoke gate: SKIPPED ({skip_reason})")
        return
    if _latest_visual_smoke_record(session, expected_commit):
        print("UI visual smoke gate: PASSED")
        return

    print("UI VISUAL SMOKE REQUIRED — session cannot be ended yet.", file=sys.stderr)
    print("This session touched larger user-visible web UI. Before ending, inspect the deployed dev URL with Playwright for:", file=sys.stderr)
    print("  - blank/error/loading-only screens, broken media/icons, raw IDs/JSON/Markdown, clipping, overlap, overflow, contrast, or covered controls", file=sys.stderr)
    print("  - implementation-related error text, console-visible failure states, slow first paint, long spinner states, or unresponsive primary interactions where practical", file=sys.stderr)
    print("Run the helper, review the screenshots, then record a pass with defects and accepted differences:", file=sys.stderr)
    print(f"  node frontend/apps/web_app/scripts/visual-smoke.mjs --url https://app.dev.openmates.org/<route> --session {sid}", file=sys.stderr)
    print(f"  python3 scripts/sessions.py visual-smoke --session {sid} --url https://app.dev.openmates.org/<route> --viewport laptop --viewport mobile --result passed --method playwright --run-id test-results/visual-smoke/<run>/summary.json --summary \"Reviewed laptop and mobile screenshots. Defects: none. Accepted differences: none.\"", file=sys.stderr)
    print("If this is truly Tier 0/non-visual, rerun with:", file=sys.stderr)
    print(f"  python3 scripts/sessions.py end --session {sid} --skip-visual-smoke \"reason\"", file=sys.stderr)
    sys.exit(1)


def _should_validate_embed_registry(files: list[str]) -> bool:
    """Return True when changed files can affect generated embed contracts."""
    return any(
        f.startswith("frontend/packages/ui/src/components/embeds/")
        or f.startswith("frontend/packages/ui/src/data/embed")
        or (f.startswith("backend/apps/") and f.endswith("/app.yml"))
        for f in files
    )


def _should_run_sdk_cleartext_gate(files: list[str]) -> bool:
    """Return True when changed files can affect public npm/pip SDK parity."""
    return any(
        f.startswith("frontend/packages/openmates-cli/src/")
        or f.startswith("packages/openmates-python/openmates/")
        or f.startswith("scripts/audit_sdk_cleartext_")
        for f in files
    )


def _get_unpushed_files() -> list[str]:
    """Return files changed by local commits that have not reached origin/dev."""
    rc, stdout, _ = _run_cmd(["git", "diff", "--name-only", "origin/dev..HEAD"])
    if rc != 0 or not stdout:
        return []
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def _run_embed_registry_validation(*, checkout_root: Path | None = None) -> tuple[int, str, str]:
    """Run the generated embed registry check used by the Vercel build."""
    return _run_cmd(
        ["npm", "run", "generate-embed-registry"],
        cwd=str((checkout_root or CONTROL_PLANE_ROOT) / "frontend" / "packages" / "ui"),
        timeout=180,
    )


def _enforce_embed_registry_validation(files: list[str], *, checkout_root: Path | None = None) -> None:
    if not _should_validate_embed_registry(files):
        return
    print("Running embed registry validation (generate-embed-registry)...")
    rc, stdout, stderr = _run_embed_registry_validation(checkout_root=checkout_root)
    if rc != 0:
        print("EMBED REGISTRY VALIDATION FAILED — aborting deploy:", file=sys.stderr)
        if stdout:
            print(stdout, file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        sys.exit(1)
    print("Embed registry: PASSED")


def _run_sdk_cleartext_audit(
    command: list[str],
    *,
    checkout_root: Path | None = None,
) -> tuple[int, str, str]:
    return _run_cmd(command, cwd=str(checkout_root or CONTROL_PLANE_ROOT), timeout=180)


def _enforce_sdk_cleartext_gate(files: list[str], *, checkout_root: Path | None = None) -> None:
    if not _should_run_sdk_cleartext_gate(files):
        return
    checks = (
        [sys.executable, "scripts/audit_sdk_cleartext_parity.py"],
        [sys.executable, "scripts/audit_sdk_cleartext_boundary.py"],
        [sys.executable, "scripts/audit_sdk_docs_coverage.py"],
        [sys.executable, "scripts/audit_sdk_test_coverage.py"],
    )
    print("Running SDK cleartext parity/boundary audits...")
    for command in checks:
        if checkout_root is None:
            rc, stdout, stderr = _run_sdk_cleartext_audit(command)
        else:
            rc, stdout, stderr = _run_sdk_cleartext_audit(command, checkout_root=checkout_root)
        if rc != 0:
            print("SDK CLEARTEXT GATE FAILED — aborting deploy:", file=sys.stderr)
            print("  " + " ".join(command), file=sys.stderr)
            if stdout:
                print(stdout, file=sys.stderr)
            if stderr:
                print(stderr, file=sys.stderr)
            sys.exit(1)
    print("SDK cleartext gate: PASSED")


def _run_translation_validation(*, checkout_root: Path | None = None) -> tuple[int, str, str]:
    """
    Run `npm run validate:locales` inside frontend/packages/ui.
    Returns (returncode, stdout, stderr).
    Only checks that every $text() key used in source files exists in en.json —
    the fast Step 4 check that guards against the Vercel build failing.
    """
    import subprocess
    result = subprocess.run(
        ["npm", "run", "validate:locales"],
        cwd=str((checkout_root or CONTROL_PLANE_ROOT) / "frontend" / "packages" / "ui"),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def _run_translation_build(*, checkout_root: Path | None = None) -> tuple[int, str, str]:
    """
    Generate ignored locale JSON artifacts from YAML sources before validation.
    Returns (returncode, stdout, stderr).
    """
    import subprocess
    result = subprocess.run(
        ["npm", "run", "build:translations"],
        cwd=str((checkout_root or CONTROL_PLANE_ROOT) / "frontend" / "packages" / "ui"),
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result.returncode, result.stdout, result.stderr


def _run_deploy_gates(
    files: list[str],
    *,
    checkout_root: Path,
    no_verify: bool,
    skip_tests_reason: str | None,
    require_parity: bool,
) -> None:
    """Run source-dependent deploy gates against one authoritative checkout."""
    lint_flags = _get_lint_flags(files)
    if lint_flags and not no_verify:
        print("Running linter...")
        rc, stdout, stderr = _run_lint(files, checkout_root=checkout_root)
        if rc != 0:
            print("LINT FAILED — aborting deploy:", file=sys.stderr)
            if stdout:
                print(stdout, file=sys.stderr)
            if stderr:
                print(stderr, file=sys.stderr)
            raise RuntimeError("lint gate failed")
        print("Lint: PASSED")
    elif lint_flags:
        print("Lint: SKIPPED (--no-verify)")

    if _has_frontend_files(files):
        print("Generating locale JSON (build:translations)...")
        rc, stdout, stderr = _run_translation_build(checkout_root=checkout_root)
        if rc != 0:
            detail = stderr or stdout or "translation build failed"
            raise RuntimeError(detail)
        print("Translations build: PASSED")
        print("Running translation validation (validate:locales)...")
        rc, stdout, stderr = _run_translation_validation(checkout_root=checkout_root)
        if rc != 0:
            detail = stderr or stdout or "translation validation failed"
            raise RuntimeError(detail)
        print("Translations: PASSED")

    _run_test_enforcement_gate(files, skip_tests_reason, checkout_root=checkout_root)
    _enforce_sdk_cleartext_gate(files, checkout_root=checkout_root)

    if require_parity:
        print("Checking latest parity evidence...")
        rc, stdout, stderr = _run_cmd(
            [sys.executable, "scripts/verify_parity.py", "--check", "--no-skips"],
            cwd=str(checkout_root),
        )
        if rc != 0:
            detail = stderr or stdout or "parity evidence check failed"
            raise RuntimeError(detail)
        print("Parity evidence: PASSED")

    _run_pytest_gate(
        files,
        skip_reason=skip_tests_reason,
        no_verify=no_verify,
        checkout_root=checkout_root,
    )
    _enforce_embed_registry_validation(files, checkout_root=checkout_root)


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

    worktree_metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None
    dirty_files = _get_dirty_files()
    to_commit = _session_deploy_files(session, exclude)
    tracked_but_clean = [f for f in modified if f not in dirty_files]
    dirty_but_untracked = [f for f in dirty_files if f not in modified]
    excluded = [f for f in modified if f in exclude]

    print("== DEPLOYMENT PLAN ==")
    print(f"Session: {sid}")
    print(f"Task: {session.get('task', '?')}")
    if worktree_metadata:
        print(f"Worktree: {worktree_metadata.get('path')}")
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
        # Session file lists are advisory and may include already-finished work.
        file_tracking: dict[str, str] = {}
        for other_sid, other_info in data.get("sessions", {}).items():
            if other_sid == sid:
                continue
            for of in other_info.get("modified_files", []):
                file_tracking[of] = other_sid

        print("Warning — dirty files NOT tracked by this session:")
        for f in sorted(dirty_but_untracked):
            tracked_session = file_tracking.get(f)
            tag = f"  [also tracked by: {tracked_session}; advisory]" if tracked_session else ""
            print(f"  ? {f}{tag}")
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

    # Translation validation skipped here — deploy and pre-commit hook both
    # run validate:locales as blocking checks, so this was redundant and slow.

    if to_commit and _should_run_sdk_cleartext_gate(to_commit):
        print("SDK cleartext gate: REQUIRED")
        print("  python3 scripts/audit_sdk_cleartext_parity.py")
        print("  python3 scripts/audit_sdk_cleartext_boundary.py")
        print("  python3 scripts/audit_sdk_docs_coverage.py")
        print("  python3 scripts/audit_sdk_test_coverage.py")
        print()

    # Related architecture docs
    related = _find_related_docs(modified)
    if related:
        print("Architecture docs to verify:")
        for doc in related:
            print(f"  - docs/architecture/{doc}")
        print()

    # Test coverage check with verdicts
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
        verdicts = {"covered": 0, "partial": 0, "none": 0}
        all_specs: list[str] = []
        untested: list[str] = []
        for filepath in source_files:
            result = _find_tests_for_file(filepath)
            verdict = result["verdict"]
            verdicts[verdict] += 1
            for spec in result.get("e2e_specs", []):
                if spec not in all_specs:
                    all_specs.append(spec)
            if verdict == "none":
                untested.append(filepath)

        print(f"Test coverage: ✅ {verdicts['covered']}  ⚠️ {verdicts['partial']}  ❌ {verdicts['none']}")
        if untested:
            for f in untested:
                print(f"  ❌ {f}")
        if all_specs:
            print("  Related specs:")
            for spec in sorted(all_specs):
                print(f"    python3 scripts/tests.py run --spec {spec}")
        if untested:
            print("  Run: sessions.py check-tests --session <id>")
        print()

    # Suggest commands
    if to_commit:
        print("== COMMANDS ==")
        print("python3 scripts/verify_parity.py --run --web-spec <spec>.spec.ts --apple build")
        print(f'python3 scripts/sessions.py deploy --session {sid} --title "<type>: <description>" --message "..."')
        print("# To hard-gate deploy on the latest parity evidence:")
        print(f'python3 scripts/sessions.py deploy --session {sid} --title "..." --require-parity')

    print()
    print("== END DEPLOYMENT PLAN ==")


def _fetch_origin_dev_commit() -> str:
    """Fetch and return the exact current origin/dev commit."""
    rc, _stdout, stderr = _run_cmd(["git", "fetch", "origin", "dev"], cwd=str(CONTROL_PLANE_ROOT))
    if rc != 0:
        raise RuntimeError(f"Could not fetch origin/dev: {stderr}")
    rc, stdout, stderr = _run_cmd(["git", "rev-parse", "origin/dev"], cwd=str(CONTROL_PLANE_ROOT))
    if rc != 0 or not stdout:
        raise RuntimeError(f"Could not resolve origin/dev: {stderr}")
    return stdout.strip()


def _integration_commit_message(args: argparse.Namespace, session: dict) -> str:
    """Build the existing deploy commit message without checkout side effects."""
    commit_msg = args.title
    if args.message:
        commit_msg += "\n\n" + args.message
    linked_task_id = session.get("task_id")
    if linked_task_id:
        linked_task = _load_task(linked_task_id)
        if linked_task:
            task_summary = linked_task.get("summary", "").strip()
            if task_summary:
                commit_msg += "\n\n" + task_summary
    return commit_msg


def _bootstrap_integration_for_files(checkout_root: Path, files: list[str]) -> None:
    """Provide ignored frontend prerequisites only when selected files need them."""
    if not _has_frontend_files(files):
        return
    result = bootstrap_session_worktree(checkout_root)
    if result.get("status") != "ready":
        raise RuntimeError(
            f"Integration bootstrap failed ({result.get('reason', 'unknown')}): "
            f"{result.get('message', 'no detail')}"
        )


def _deploy_native_worktree(
    args: argparse.Namespace,
    session: dict,
    worktree_metadata: dict,
    to_commit: list[str],
    patch_id: str,
) -> None:
    """Validate and push one native session patch without modifying root."""
    sid = args.session
    no_verify = getattr(args, "no_verify", False)
    skip_tests_reason = getattr(args, "skip_tests_reason", None)
    require_parity = getattr(args, "require_parity", False)
    integration: dict | None = None
    deploy_lock_held = False
    commit_hash_full = ""

    try:
        prepared_base = _fetch_origin_dev_commit()
        integration = _prepare_integration_worktree(
            sid,
            worktree_metadata,
            to_commit,
            patch_id,
            prepared_base,
        )

        while True:
            checkout_root = Path(integration["path"])
            _bootstrap_integration_for_files(checkout_root, to_commit)
            _run_deploy_gates(
                to_commit,
                checkout_root=checkout_root,
                no_verify=no_verify,
                skip_tests_reason=skip_tests_reason,
                require_parity=require_parity,
            )

            _wait_and_acquire_session_lock(
                "vercel_deploy",
                sid,
                phase="finalizing_integration_worktree",
                timeout=getattr(args, "lock_timeout", None),
                poll=getattr(args, "lock_poll", 30),
            )
            deploy_lock_held = True
            final_base = _fetch_origin_dev_commit()
            if final_base != integration["prepared_base"]:
                _release_session_lock("vercel_deploy", released_by=sid)
                deploy_lock_held = False
                print(
                    f"origin/dev advanced from {integration['prepared_base'][:9]} to {final_base[:9]}; "
                    "rebuilding and rerunning gates."
                )
                integration = _rebuild_integration_worktree(
                    integration,
                    worktree_metadata,
                    to_commit,
                    final_base,
                )
                continue

            print("Checking Vercel web app build machine...")
            _enforce_vercel_standard_build_machine()
            print("Vercel build machine: standard/fixed")
            if not _validate_staged_deploy_files(
                set(to_commit),
                context="before integration commit",
                checkout_root=checkout_root,
            ):
                raise RuntimeError("Integration staged-file validation failed")

            commit_cmd = ["git", "commit", "-m", _integration_commit_message(args, session)]
            if no_verify:
                commit_cmd.append("--no-verify")
            os.environ["OPENMATES_SKIP_PRECOMMIT_LOCALES"] = "1"
            try:
                rc, _stdout, stderr = _run_cmd(commit_cmd, cwd=str(checkout_root), timeout=300)
            finally:
                os.environ.pop("OPENMATES_SKIP_PRECOMMIT_LOCALES", None)
            if rc != 0:
                raise RuntimeError(f"git commit failed in integration worktree: {stderr}")

            rc, commit_hash_full, stderr = _run_cmd(
                ["git", "rev-parse", "HEAD"],
                cwd=str(checkout_root),
            )
            commit_hash_full = commit_hash_full.strip()
            if rc != 0 or not commit_hash_full:
                raise RuntimeError(f"Could not resolve integration commit: {stderr}")

            print("Pushing integration commit to origin dev...")
            rc, _stdout, stderr = _run_cmd(
                ["git", "push", "origin", "HEAD:refs/heads/dev"],
                cwd=str(checkout_root),
                timeout=300,
            )
            if rc != 0:
                raise RuntimeError(f"git push failed: {stderr}")
            _release_session_lock("vercel_deploy", commit_sha=commit_hash_full, released_by=sid)
            deploy_lock_held = False
            break
    except IntegrationConflict as exc:
        item = enqueue_worktree_deploy(
            sid,
            args.title,
            patch_id,
            reason=str(exc),
            integration=integration,
            final_base=exc.final_base,
        )
        print(f"WORKTREE INTEGRATION BLOCKED — {item['id']}: {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"WORKTREE DEPLOY FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if deploy_lock_held:
            _release_session_lock("vercel_deploy", released_by=sid)
        if integration:
            try:
                _remove_integration_worktree(integration)
            except RuntimeError as cleanup_error:
                print(f"Integration cleanup warning: {cleanup_error}", file=sys.stderr)

    _save_last_deploy_sha(commit_hash_full)
    _mark_worktree_deployed(sid, patch_id, commit_hash_full, integration=integration)
    commit_hash = commit_hash_full[:7]
    print()
    print("== DEPLOYED ==")
    print(f"Commit: {commit_hash}")
    print(f"Files: {len(to_commit)}")
    for relative_path in sorted(to_commit):
        print(f"  {relative_path}")
    print("Branch: dev")

    related = _find_related_docs(to_commit)
    if related:
        print()
        print("Verify these architecture docs are still accurate:")
        for doc in related:
            print(f"  - docs/architecture/{doc}")

    if getattr(args, "end_session", False):
        latest_data = _load_sessions()
        latest_session = latest_data.get("sessions", {}).get(sid, session)
        _enforce_visual_smoke_end_gate(
            sid,
            latest_session,
            to_commit,
            skip_reason=getattr(args, "skip_visual_smoke_reason", None),
            commit_sha=commit_hash_full,
        )
        try:
            finalize_session_worktree(sid, target_ref=commit_hash_full)
        except RuntimeError as exc:
            print(f"DEPLOYED BUT SESSION FINALIZATION BLOCKED — {exc}", file=sys.stderr)
            print(f"Retry after resolving residual work: python3 scripts/sessions.py end --session {sid}", file=sys.stderr)
            sys.exit(1)
        _linear_complete_session(sid, latest_session, commit_sha=commit_hash)
        print(f"\nSession {sid} ended.")


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
    worktree_metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None

    use_staged = getattr(args, "use_staged", False)
    dirty_files = _get_dirty_files()
    to_commit = _session_deploy_files(session, exclude)
    staged_files_for_deploy = set(_get_staged_files()) if use_staged and not to_commit else set()
    if staged_files_for_deploy:
        to_commit = sorted(f for f in staged_files_for_deploy if f not in exclude)
        modified = sorted(set(modified) | set(to_commit))
    dirty_but_untracked = [f for f in dirty_files if f not in modified and f not in exclude]
    worktree_patch_id = _worktree_patch_id(worktree_metadata, to_commit) if worktree_metadata and to_commit else ""
    pending_worktree_commit = _pending_worktree_push_commit(
        sid,
        worktree_patch_id,
        to_commit,
        dirty_files,
    ) if worktree_patch_id else ""

    # Session file lists are advisory and may include already-finished work.
    file_tracking: dict[str, str] = {}
    for other_sid, other_info in data.get("sessions", {}).items():
        if other_sid == sid:
            continue
        for of in other_info.get("modified_files", []):
            file_tracking[of] = other_sid

    if not to_commit or pending_worktree_commit:
        git_summary = _get_git_status_summary()
        if git_summary.get("unpushed", 0) > 0:
            rc, commit_hash_full, _ = _run_cmd(["git", "rev-parse", "HEAD"])
            commit_hash_full = (commit_hash_full or "").strip() if rc == 0 else ""
            commit_hash = commit_hash_full[:7] if commit_hash_full else "unknown"

            _enforce_embed_registry_validation(_get_unpushed_files())

            deploy_lock_held = False
            try:
                _wait_and_acquire_session_lock(
                    "vercel_deploy",
                    sid,
                    phase="pushing_existing_commit",
                    timeout=getattr(args, "lock_timeout", None),
                    poll=getattr(args, "lock_poll", 30),
                )
                deploy_lock_held = True
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                sys.exit(1)
            print(f"Dev deploy push lock acquired for commit {commit_hash}.")

            print("Checking Vercel web app build machine...")
            try:
                _enforce_vercel_standard_build_machine()
            except RuntimeError as exc:
                if deploy_lock_held:
                    _release_session_lock("vercel_deploy", released_by=sid)
                print(f"VERCEL BUILD MACHINE GATE FAILED — {exc}", file=sys.stderr)
                sys.exit(1)
            print("Vercel build machine: standard/fixed")

            print(f"No files to commit; pushing {git_summary['unpushed']} existing commit(s) to origin dev...")
            rc, stdout, stderr = _run_cmd(["git", "push", "origin", "dev"])
            if rc != 0:
                if deploy_lock_held:
                    _release_session_lock("vercel_deploy", released_by=sid)
                print(f"git push failed: {stderr}", file=sys.stderr)
                print("Existing local commit(s) were not pushed.")
                sys.exit(1)
            if deploy_lock_held:
                _release_session_lock("vercel_deploy", released_by=sid)

            if commit_hash_full:
                _save_last_deploy_sha(commit_hash_full)
            if pending_worktree_commit:
                _mark_worktree_deployed(sid, worktree_patch_id, commit_hash_full)

            print()
            print("== DEPLOYED ==")
            print(f"Commit: {commit_hash}")
            print("Files: 0 (resumed previous deploy push)")
            print("Branch: dev")

            if getattr(args, "end_session", False):
                latest_data = _load_sessions()
                latest_session = latest_data.get("sessions", {}).get(sid, session)
                _enforce_visual_smoke_end_gate(
                    sid,
                    latest_session,
                    modified or _get_unpushed_files(),
                    skip_reason=getattr(args, "skip_visual_smoke_reason", None),
                    commit_sha=commit_hash_full,
                )
                try:
                    finalize_session_worktree(sid, target_ref=commit_hash_full)
                except RuntimeError as exc:
                    print(f"DEPLOYED BUT SESSION FINALIZATION BLOCKED — {exc}", file=sys.stderr)
                    print(f"Retry after resolving residual work: python3 scripts/sessions.py end --session {sid}", file=sys.stderr)
                    sys.exit(1)
                _linear_complete_session(sid, latest_session, commit_sha=commit_hash)
                print(f"Session {sid} ended.")
            sys.exit(0)

        # Surface untracked dirty files so the caller knows why nothing was committed
        if dirty_but_untracked:
            print("No tracked files to commit, but these dirty files are NOT tracked by this session:", file=sys.stderr)
            for f in sorted(dirty_but_untracked):
                tracked_session = file_tracking.get(f)
                tag = f"  [also tracked by: {tracked_session}; advisory]" if tracked_session else ""
                print(f"  ? {f}{tag}", file=sys.stderr)
            print("Run: sessions.py track --session <ID> --file <path>  to include them.", file=sys.stderr)
        else:
            print("No files to commit.")
        sys.exit(2)

    # Warn about dirty files that will be left out
    if dirty_but_untracked:
        print("Warning — dirty files NOT tracked by this session (will not be committed):")
        for f in sorted(dirty_but_untracked):
            tracked_session = file_tracking.get(f)
            tag = f"  [also tracked by: {tracked_session}; advisory]" if tracked_session else ""
            print(f"  ? {f}{tag}")
        print()

    if worktree_metadata and to_commit and validate_worktree_binding_mode(session) == "native":
        _deploy_native_worktree(args, session, worktree_metadata, to_commit, worktree_patch_id)
        return

    if worktree_metadata and to_commit:
        deploy_lock_held = False
        try:
            _wait_and_acquire_session_lock(
                "vercel_deploy",
                sid,
                phase="integrating_worktree",
                timeout=getattr(args, "lock_timeout", None),
                poll=getattr(args, "lock_poll", 30),
            )
            deploy_lock_held = True
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        print("Dev deploy integration lock acquired for worktree diff application.")

        try:
            patch_action = _worktree_root_patch_action(sid, worktree_patch_id, to_commit)
            if patch_action == "applied":
                print("Session worktree diff is already integrated; continuing deploy retry.")
            else:
                if patch_action == "conflict":
                    raise RuntimeError(
                        "Selected root files changed after the previous worktree integration; "
                        "resolve the root conflict before retrying."
                    )
                if patch_action == "refresh":
                    print("Refreshing safely amended session worktree files in root...")
                    _sync_worktree_files_to_root(worktree_metadata, to_commit)
                else:
                    print(f"Applying session worktree diff from {worktree_metadata.get('path')}...")
                    _apply_worktree_diff_to_root(worktree_metadata, to_commit)
                _record_worktree_root_patch(sid, worktree_patch_id, to_commit)
        except (RuntimeError, OSError) as exc:
            item = enqueue_worktree_deploy(sid, args.title, worktree_patch_id, reason=str(exc))
            print(f"WORKTREE INTEGRATION BLOCKED — {item['id']}: {exc}", file=sys.stderr)
            print("Resolve the root conflict, then rerun the same sessions.py deploy command.", file=sys.stderr)
            sys.exit(1)
        finally:
            if deploy_lock_held:
                _release_session_lock("vercel_deploy", released_by=sid)

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

    # 1b. Translation build + validation — generated JSON is ignored by git but
    # required at runtime, so deploy must refresh it before validation/restart.
    if _has_frontend_files(to_commit):
        print("Generating locale JSON (build:translations)...")
        rc, stdout, stderr = _run_translation_build()
        if rc != 0:
            print("TRANSLATION BUILD FAILED — aborting deploy:", file=sys.stderr)
            if stdout:
                print(stdout, file=sys.stderr)
            if stderr:
                print(stderr, file=sys.stderr)
            sys.exit(1)
        print("Translations build: PASSED")

        print("Running translation validation (validate:locales)...")
        rc, stdout, stderr = _run_translation_validation()
        if rc != 0:
            print("TRANSLATION VALIDATION FAILED — aborting deploy:", file=sys.stderr)
            if stdout:
                print(stdout, file=sys.stderr)
            if stderr:
                print(stderr, file=sys.stderr)
            print("", file=sys.stderr)
            print("Fix: update the relevant YAML source under", file=sys.stderr)
            print("  frontend/packages/ui/src/i18n/sources/", file=sys.stderr)
            print("Then run: cd frontend/packages/ui && npm run build:translations && npm run validate:locales", file=sys.stderr)
            sys.exit(1)
        else:
            print("Translations: PASSED")

    # 1c. Test enforcement gate — warn if related specs exist but weren't run
    skip_tests_reason = getattr(args, "skip_tests_reason", None)
    _run_test_enforcement_gate(to_commit, skip_tests_reason)

    # 1d. Public SDK changes must keep npm/pip feature parity and hide crypto
    # details behind cleartext APIs before any commit reaches dev.
    _enforce_sdk_cleartext_gate(to_commit)

    if getattr(args, "require_parity", False):
        print("Checking latest parity evidence...")
        rc, stdout, stderr = _run_cmd([sys.executable, "scripts/verify_parity.py", "--check", "--no-skips"])
        if rc != 0:
            print("PARITY GATE FAILED — run python3 scripts/verify_parity.py --run before deploying.", file=sys.stderr)
            if stdout:
                print(stdout, file=sys.stderr)
            if stderr:
                print(stderr, file=sys.stderr)
            sys.exit(1)
        print("Parity evidence: PASSED")

    # 1e. Pytest gate — hard-block on failing related pytest unit tests
    _run_pytest_gate(to_commit, skip_reason=skip_tests_reason, no_verify=no_verify)

    _enforce_embed_registry_validation(to_commit)

    print("Checking Vercel web app build machine...")
    try:
        _enforce_vercel_standard_build_machine()
    except RuntimeError as exc:
        print(f"VERCEL BUILD MACHINE GATE FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
    print("Vercel build machine: standard/fixed")

    deploy_lock_held = False
    try:
        _wait_and_acquire_session_lock(
            "vercel_deploy",
            sid,
            phase="preparing_commit",
            timeout=getattr(args, "lock_timeout", None),
            poll=getattr(args, "lock_poll", 30),
        )
        deploy_lock_held = True
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print("Dev deploy push lock acquired for commit preparation.")

    # 2. Git add — reset any staged files not belonging to this session first,
    # to prevent index bleed from concurrent sessions that already ran git add.
    staged_files = _get_staged_files()
    foreign_staged = [f for f in staged_files if f not in to_commit]
    if foreign_staged:
        if use_staged:
            print("--use-staged found staged files outside this session; aborting to avoid index bleed:", file=sys.stderr)
            for f in sorted(foreign_staged):
                print(f"  - {f}", file=sys.stderr)
            if deploy_lock_held:
                _release_session_lock("vercel_deploy", released_by=sid)
            sys.exit(1)
        print(f"Unstaging {len(foreign_staged)} file(s) staged by another session...")
        rc, _, stderr = _run_cmd(["git", "reset", "HEAD"] + foreign_staged)
        if rc != 0:
            print(f"git reset failed: {stderr}", file=sys.stderr)
            if deploy_lock_held:
                _release_session_lock("vercel_deploy", released_by=sid)
            sys.exit(1)

    if use_staged:
        staged_files = _get_staged_files()
        missing_staged = [f for f in to_commit if f not in staged_files]
        if missing_staged:
            print("--use-staged requires staged changes for every tracked deploy file:", file=sys.stderr)
            for f in sorted(missing_staged):
                print(f"  - {f}", file=sys.stderr)
            if deploy_lock_held:
                _release_session_lock("vercel_deploy", released_by=sid)
            sys.exit(1)
        print(f"Using pre-staged changes for {len(to_commit)} tracked file(s)")
    else:
        # Separate existing files from deleted files — git add fails on deleted files,
        # but they may already be staged via git rm. Only add files that exist on disk.
        files_to_add = [f for f in to_commit if (CONTROL_PLANE_ROOT / f).exists()]
        deleted_files = [f for f in to_commit if not (CONTROL_PLANE_ROOT / f).exists()]

        if deleted_files:
            # Ensure deleted files are staged (git rm --cached is safe even if already staged)
            print(f"Staging {len(deleted_files)} deleted file(s)...")
            rc, _, stderr = _run_cmd(["git", "rm", "--cached", "--ignore-unmatch"] + deleted_files)
            if rc != 0:
                print(f"git rm failed: {stderr}", file=sys.stderr)
                if deploy_lock_held:
                    _release_session_lock("vercel_deploy", released_by=sid)
                sys.exit(1)

        if files_to_add:
            print(f"Adding {len(files_to_add)} file(s)...")
            rc, _, stderr = _run_cmd(["git", "add"] + files_to_add)
            if rc != 0:
                print(f"git add failed: {stderr}", file=sys.stderr)
                if deploy_lock_held:
                    _release_session_lock("vercel_deploy", released_by=sid)
                sys.exit(1)

        print(f"Staging complete: {len(files_to_add)} added, {len(deleted_files)} deleted")

    print("Rechecking Vercel web app build machine before commit...")
    try:
        _enforce_vercel_standard_build_machine()
    except RuntimeError as exc:
        if deploy_lock_held:
            _release_session_lock("vercel_deploy", released_by=sid)
        print(f"VERCEL BUILD MACHINE GATE FAILED — {exc}", file=sys.stderr)
        print("No commit was created.", file=sys.stderr)
        sys.exit(1)
    print("Vercel build machine: standard/fixed")

    if not _validate_staged_deploy_files(
        set(to_commit),
        context="before commit",
    ):
        if deploy_lock_held:
            _release_session_lock("vercel_deploy", released_by=sid)
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
            "WARNING: committing without pre-commit hooks (--no-verify).",
            file=sys.stderr,
        )
    commit_cmd = ["git", "commit", "-m", commit_msg]
    if no_verify:
        commit_cmd.append("--no-verify")
    # Skip pre-commit locale validation — sessions.py already ran it above.
    os.environ["OPENMATES_SKIP_PRECOMMIT_LOCALES"] = "1"
    print(f"Committing: {args.title}")
    rc, stdout, stderr = _run_cmd(commit_cmd)
    os.environ.pop("OPENMATES_SKIP_PRECOMMIT_LOCALES", None)
    if rc != 0:
        if deploy_lock_held:
            _release_session_lock("vercel_deploy", released_by=sid)
        print(f"git commit failed: {stderr}", file=sys.stderr)
        sys.exit(1)

    # Extract commit hash — one rev-parse call, slice for short form
    rc, commit_hash_full, _ = _run_cmd(["git", "rev-parse", "HEAD"])
    commit_hash_full = (commit_hash_full or "").strip()
    commit_hash = commit_hash_full[:7] if commit_hash_full else "unknown"
    if worktree_metadata:
        _record_worktree_pending_commit(sid, worktree_patch_id, commit_hash_full)

    # 4. Git push. Vercel/test readiness is commit-scoped via
    # --expected-commit, so this mutex must not outlive the push.
    print("Pushing to origin dev...")
    rc, stdout, stderr = _run_cmd(["git", "push", "origin", "dev"])
    if rc != 0:
        if deploy_lock_held:
            _release_session_lock("vercel_deploy", released_by=sid)
        print(f"git push failed: {stderr}", file=sys.stderr)
        print("Commit was created locally but not pushed.")
        sys.exit(1)
    if deploy_lock_held:
        _release_session_lock("vercel_deploy", released_by=sid)

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

    if worktree_metadata:
        _mark_worktree_deployed(sid, worktree_patch_id, commit_hash_full)

    # Check related architecture docs
    related = _find_related_docs(to_commit)
    if related:
        print()
        print("Verify these architecture docs are still accurate:")
        for doc in related:
            print(f"  - docs/architecture/{doc}")

    # Auto-end session if --end flag is set
    if getattr(args, "end_session", False):
        latest_data = _load_sessions()
        latest_session = latest_data.get("sessions", {}).get(sid, session)
        _enforce_visual_smoke_end_gate(
            sid,
            latest_session,
            to_commit,
            skip_reason=getattr(args, "skip_visual_smoke_reason", None),
            commit_sha=commit_hash_full,
        )
        try:
            finalize_session_worktree(sid, target_ref=commit_hash_full)
        except RuntimeError as exc:
            print(f"DEPLOYED BUT SESSION FINALIZATION BLOCKED — {exc}", file=sys.stderr)
            print(f"Retry after resolving residual work: python3 scripts/sessions.py end --session {sid}", file=sys.stderr)
            sys.exit(1)
        _linear_complete_session(sid, latest_session, commit_sha=commit_hash)
        print(f"\nSession {sid} ended.")


def cmd_worktree(args: argparse.Namespace) -> None:
    """Manage automatic local session worktrees."""
    if args.worktree_action == "ensure":
        try:
            metadata = ensure_session_worktree(args.session)
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print("== SESSION WORKTREE ==")
        print(f"Session: {args.session}")
        print(f"Path: {metadata['path']}")
        print(f"Base: {metadata.get('base_commit', '')[:9]}")
        print(f"Status: {metadata.get('status', 'active')}")
        print("Use this path as the working directory for source edits.")
        return
    if args.worktree_action == "binding":
        try:
            result = record_worktree_binding(
                opencode_session_id=args.opencode_session,
                mode=args.mode,
                directory=args.directory or "",
                reason=args.reason or "",
            )
        except (RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, sort_keys=True))
        return
    if args.worktree_action == "cleanup":
        deleted = cleanup_session_worktrees(idle_hours=args.idle_hours)
        print(f"Deleted safely classified stale worktrees: {len(deleted)}")
        for session_id in deleted:
            print(f"  - {session_id}")
        return
    if args.worktree_action == "reconcile":
        if args.idle_hours < WORKTREE_CLEANUP_IDLE_HOURS and not args.only:
            print(
                f"Error: --idle-hours below {WORKTREE_CLEANUP_IDLE_HOURS} requires at least one --only SESSION_ID",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            report = reconcile_session_worktrees(
                target_ref=args.target,
                idle_hours=args.idle_hours,
                apply_safe=args.apply_safe,
                approved_obsolete=set(args.approve_obsolete or []),
                only_session_ids=set(args.only or []),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            counts: dict[str, int] = {}
            for item in report["items"]:
                classification = str(item.get("classification") or "unknown")
                counts[classification] = counts.get(classification, 0) + 1
            print("== WORKTREE RECONCILIATION ==")
            print(f"Target: {report['target_ref']} ({report['target_commit'][:10]})")
            print(f"Inspected: {len(report['items'])}")
            print(f"Deleted: {len(report['deleted'])}")
            print(f"Unresolved: {len(report['unresolved'])}")
            for classification, count in sorted(counts.items()):
                print(f"  {classification}: {count}")
            for item in report["unresolved"]:
                print(f"  ! {item.get('session_id')}: {item.get('classification')} ({item.get('reason_code', '')})")
        return
    if args.worktree_action == "release-readiness":
        try:
            report = worktree_release_readiness(
                target_ref=args.target,
                excluded_active=set(args.exclude_active or []),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print("== WORKTREE RELEASE READINESS ==")
            print(f"Target: {report['target_ref']} ({report['target_commit'][:10]})")
            print(f"Ready: {'yes' if report['ready'] else 'no'}")
            if report["excluded_active"]:
                print("Explicitly excluded recent work: " + ", ".join(report["excluded_active"]))
            if report["blocking_worktrees"]:
                print("Blocking worktrees: " + ", ".join(report["blocking_worktrees"]))
            if report["blocked_deploys"]:
                print("Blocked deploys: " + ", ".join(report["blocked_deploys"]))
            if not report["ready"]:
                print(f"Inspect: python3 scripts/sessions.py worktree reconcile --target {args.target}")
                print(
                    "Delete proven stale work: python3 scripts/sessions.py worktree reconcile "
                    f"--target {args.target} --idle-hours {WORKTREE_CLEANUP_IDLE_HOURS} --apply-safe"
                )
                print("Exclude only user-confirmed recent work with repeated --exclude-active <SESSION_ID> flags.")
        if not report["ready"]:
            sys.exit(1)
        return
    print("Error: unknown worktree action", file=sys.stderr)
    sys.exit(1)



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


def _find_tests_for_file(filepath: str, *, checkout_root: Path | None = None) -> dict:
    """
    Search for existing unit and E2E tests related to a source file.

    Returns dict with 'unit_tests', 'e2e_tests', 'e2e_specs' (spec filenames
    for run_tests.py), 'verdict' (covered/partial/none), and 'suggestions'.
    """
    root = checkout_root or PROJECT_ROOT
    path = Path(filepath)
    stem = path.stem  # e.g., "chatStore" from "chatStore.ts"
    suffix = path.suffix  # e.g., ".ts"
    parent = str(path.parent)  # e.g., "frontend/packages/ui/src/stores"
    result = {
        "unit_tests": [],
        "e2e_tests": [],
        "e2e_specs": [],
        "verdict": "none",
        "suggestions": [],
    }

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
        full_path = root / candidate
        if full_path.exists():
            result["unit_tests"].append(candidate)

    # Also do a glob search for any test file containing the stem name
    for test_glob_pattern in [
        f"**/__tests__/*{stem}*",
        f"**/test_{stem}*",
        f"**/*{stem}*.test.*",
        f"**/*{stem}*.spec.*",
    ]:
        for match in root.glob(test_glob_pattern):
            rel = str(match.relative_to(root))
            if rel not in result["unit_tests"] and "node_modules" not in rel:
                result["unit_tests"].append(rel)

    # --- Search for E2E tests referencing this file/component ---
    e2e_spec_dir = root / "frontend" / "apps" / "web_app" / "tests"
    if e2e_spec_dir.exists():
        # Build search terms: stem, kebab-case, parent directory context
        search_terms = [stem]

        # kebab-case version of camelCase names
        kebab = ""
        for i, c in enumerate(stem):
            if c.isupper() and i > 0:
                kebab += "-"
            kebab += c.lower()
        if kebab != stem.lower():
            search_terms.append(kebab)

        # Add contextual terms from the file path for filename matching
        # (e.g., "events" from backend/apps/events/ matches skill-events-*.spec.ts)
        filename_terms = _extract_context_terms(filepath)

        for spec_file in sorted(e2e_spec_dir.glob("*.spec.ts")):
            try:
                spec_name_lower = spec_file.stem.replace(".spec", "").lower()

                # 1. Check spec filename for app/domain terms (high precision)
                filename_match = any(
                    term in spec_name_lower for term in filename_terms
                )

                # 2. Check spec content for stem/kebab terms (exact component ref)
                content_match = False
                if not filename_match:
                    content = spec_file.read_text(errors="replace")
                    content_lower = content.lower()
                    for term in search_terms:
                        if term.lower() in content_lower:
                            content_match = True
                            break

                if filename_match or content_match:
                    rel = str(spec_file.relative_to(root))
                    spec_name = spec_file.name
                    if rel not in result["e2e_tests"]:
                        result["e2e_tests"].append(rel)
                    if spec_name not in result["e2e_specs"]:
                        result["e2e_specs"].append(spec_name)
            except OSError:
                pass

    # --- Compute verdict ---
    has_unit = bool(result["unit_tests"])
    has_e2e = bool(result["e2e_tests"])
    if has_unit and has_e2e:
        result["verdict"] = "covered"
    elif has_unit or has_e2e:
        result["verdict"] = "partial"
    else:
        result["verdict"] = "none"

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


def _extract_context_terms(filepath: str) -> list:
    """Extract meaningful context terms from a file path for E2E spec matching.

    Splits camelCase/snake_case stems and parent directory names into domain
    keywords (e.g., 'chatSyncService' -> ['chat', 'sync']).  Short or generic
    terms are filtered out.
    """
    import re

    path = Path(filepath)
    stem = path.stem
    terms = []

    _GENERIC_TERMS = {
        "service", "services", "store", "stores", "utils", "util",
        "helper", "helpers", "handler", "handlers", "component",
        "components", "index", "main", "base", "app", "core", "api",
        "src", "routes", "models", "schemas", "types", "mixin",
        "skill", "skills", "search", "embed", "embeds", "flow",
        "settings", "config", "data", "test", "tests", "chat",
        "message", "messages", "user", "users", "event", "events",
        "task", "tasks", "list", "item", "items", "view",
    }

    # Split camelCase and snake_case from stem
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)", stem)
    parts += stem.split("_")

    for part in parts:
        part_lower = part.lower()
        # Require >= 5 chars to avoid overly broad matches
        if len(part_lower) >= 5 and part_lower not in _GENERIC_TERMS:
            if part_lower not in terms:
                terms.append(part_lower)

    # Always add the app name from the path (e.g., "events" from
    # backend/apps/events/) — this bypasses the generic filter because
    # app names are strong signals for spec filename matching.
    path_parts = path.parts
    if "apps" in path_parts:
        idx = list(path_parts).index("apps")
        if idx + 1 < len(path_parts):
            app_name = path_parts[idx + 1].lower()
            if app_name not in terms and len(app_name) >= 3:
                terms.append(app_name)

    return terms


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


def _run_test_enforcement_gate(
    files_to_commit: list[str],
    skip_reason: str | None = None,
    *,
    checkout_root: Path | None = None,
) -> None:
    """Check test coverage for files being deployed and warn if specs exist but
    weren't verified.  Called from cmd_deploy.

    This is a WARNING gate, not a hard block — it prints actionable info and
    continues.  Use --skip-tests "reason" to suppress the warning entirely.
    """
    if skip_reason:
        print(f"Test gate: SKIPPED ({skip_reason})")
        return

    # Filter to source files only (skip tests, configs, docs, etc.)
    source_files = [
        f for f in files_to_commit
        if any(f.endswith(ext) for ext in (".py", ".ts", ".svelte"))
        and "/tests/" not in f
        and "/__tests__/" not in f
        and not Path(f).name.startswith("test_")
        and not f.endswith(".test.ts")
        and not f.endswith(".spec.ts")
    ]

    if not source_files:
        return

    # Exempt file patterns (docs-only, i18n, config — no spec needed)
    _EXEMPT_PATTERNS = (
        "i18n/sources/", "docs/", ".md", "Caddyfile",
        "docker-compose", ".yml", ".yaml", ".json",
    )
    non_exempt = [
        f for f in source_files
        if not any(pat in f for pat in _EXEMPT_PATTERNS)
    ]
    if not non_exempt:
        return

    all_specs: list[str] = []
    uncovered: list[str] = []

    for filepath in non_exempt:
        result = _find_tests_for_file(filepath, checkout_root=checkout_root)
        for spec in result.get("e2e_specs", []):
            if spec not in all_specs:
                all_specs.append(spec)
        if result["verdict"] == "none":
            uncovered.append(filepath)

    # Check if any related specs were run in the current session
    # by looking at test-results/last-run.json
    specs_run_recently: set[str] = set()
    last_run_path = CONTROL_PLANE_ROOT / "test-results" / "last-run.json"
    if last_run_path.exists():
        try:
            import json as _json
            last_run = _json.loads(last_run_path.read_text())
            pw_tests = last_run.get("suites", {}).get("playwright", {}).get("tests", [])
            if isinstance(pw_tests, list):
                for t in pw_tests:
                    name = t.get("name") or t.get("file") or ""
                    if name:
                        specs_run_recently.add(name)
        except (OSError, ValueError):
            pass

    unrun_specs = [s for s in all_specs if s not in specs_run_recently]

    # Print gate results
    if not unrun_specs and not uncovered:
        print("Test gate: PASSED")
        return

    print("── TEST ENFORCEMENT GATE ──")
    if uncovered:
        print(f"  ⚠️  {len(uncovered)} file(s) with NO test coverage:")
        for f in uncovered[:5]:
            print(f"      {f}")
        if len(uncovered) > 5:
            print(f"      ... and {len(uncovered) - 5} more")

    if unrun_specs:
        print(f"  ⚠️  {len(unrun_specs)} related spec(s) not run this session:")
        for spec in sorted(unrun_specs)[:5]:
            print(f"      python3 scripts/tests.py run --spec {spec}")
        if len(unrun_specs) > 5:
            print(f"      ... and {len(unrun_specs) - 5} more")

    print("  To suppress: deploy --skip-tests \"reason\"")
    print("── END TEST GATE ──")
    print()


# Pytest test files that must be excluded from the deploy gate — these match
# the ignore list used by run_tests.py:run_pytest() so the deploy gate stays
# consistent with the daily pytest suite.
_PYTEST_GATE_IGNORE_EXACT: set[str] = {
    "backend/tests/test_encryption_service.py",
    "backend/tests/test_integration_encryption.py",
}
_PYTEST_GATE_IGNORE_PREFIX: tuple[str, ...] = (
    "backend/tests/fixtures/",
)
_PYTEST_GATE_IGNORE_NAME_PREFIX: tuple[str, ...] = (
    "test_model_comparison_",
)
# Hard timeout for the pytest gate — deploys should stay fast; if a targeted
# test run exceeds this, the fix is to scope the tests better, not to wait.
_PYTEST_GATE_TIMEOUT_SECONDS: int = 180


def _is_backend_py(path: str) -> bool:
    return path.startswith("backend/") and path.endswith(".py")


def _is_pytest_gate_ignored(path: str) -> bool:
    if path in _PYTEST_GATE_IGNORE_EXACT:
        return True
    if any(path.startswith(p) for p in _PYTEST_GATE_IGNORE_PREFIX):
        return True
    name = Path(path).name
    return any(name.startswith(g) for g in _PYTEST_GATE_IGNORE_NAME_PREFIX)


def _is_pytest_test_file(path: str) -> bool:
    """True if the file is itself a pytest test module under backend/."""
    if not _is_backend_py(path):
        return False
    name = Path(path).name
    if not name.startswith("test_"):
        return False
    # Must live under a tests/ directory (backend/tests/ or backend/apps/*/tests/)
    return "/tests/" in path


def _resolve_pytest_venv() -> Path | None:
    """Return a usable python interpreter for pytest, matching run_tests.py."""
    candidates = [
        CONTROL_PLANE_ROOT / "backend" / ".venv" / "bin" / "python3",
        Path("/OpenMates/.venv/bin/python3"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _collect_pytest_targets(
    files_to_commit: list[str],
    *,
    checkout_root: Path | None = None,
) -> list[str]:
    """Return a deduplicated, filtered list of pytest test files related to
    the backend Python files in the current commit.
    """
    root = checkout_root or PROJECT_ROOT
    targets: list[str] = []
    seen: set[str] = set()

    for filepath in files_to_commit:
        if not _is_backend_py(filepath):
            continue

        candidates: list[str] = []

        if _is_pytest_test_file(filepath):
            candidates.append(filepath)
        else:
            result = _find_tests_for_file(filepath, checkout_root=root)
            for unit_test in result.get("unit_tests", []):
                if _is_backend_py(unit_test) and _is_pytest_test_file(unit_test):
                    candidates.append(unit_test)

        for candidate in candidates:
            if candidate in seen:
                continue
            if _is_pytest_gate_ignored(candidate):
                continue
            if not (root / candidate).is_file():
                continue
            seen.add(candidate)
            targets.append(candidate)

    return targets


def _run_pytest_gate(
    files_to_commit: list[str],
    *,
    skip_reason: str | None = None,
    no_verify: bool = False,
    checkout_root: Path | None = None,
) -> None:
    """Hard-block deploy if related pytest unit tests fail.

    Only runs when the commit touches backend/**/*.py files. Uses the local
    backend venv and runs only the test files related to the changed sources
    (resolved via _find_tests_for_file). On failure, prints pytest output and
    aborts the deploy. Honors --skip-tests "reason" and --no-verify.
    """
    if no_verify:
        print("Pytest gate: SKIPPED (--no-verify)")
        return
    if skip_reason:
        print(f"Pytest gate: SKIPPED ({skip_reason})")
        return

    backend_py = [f for f in files_to_commit if _is_backend_py(f)]
    if not backend_py:
        print("Pytest gate: SKIPPED (no backend python files changed)")
        return

    root = checkout_root or PROJECT_ROOT
    targets = _collect_pytest_targets(files_to_commit, checkout_root=root)
    if not targets:
        print("Pytest gate: SKIPPED (no related pytest tests found)")
        return

    venv_python = _resolve_pytest_venv()
    if venv_python is None:
        print("Pytest gate: SKIPPED (backend venv not found)", file=sys.stderr)
        return

    print(f"Running pytest gate ({len(targets)} test file(s))...")
    for t in targets:
        print(f"  • {t}")

    cmd = [
        str(venv_python), "-m", "pytest",
        *targets,
        "-m", "not integration and not benchmark",
        "--tb=short", "--color=no", "-q",
    ]

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=_PYTEST_GATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(
            f"PYTEST GATE FAILED — timed out after {_PYTEST_GATE_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        print("  Bypass with: deploy --skip-tests \"reason\"", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"Pytest gate: PASSED ({len(targets)} file(s) in {elapsed:.1f}s)")
        return

    print("PYTEST GATE FAILED — aborting deploy:", file=sys.stderr)
    if result.stdout:
        print(result.stdout, file=sys.stderr)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    print(
        "  Bypass with: deploy --skip-tests \"reason\"  (requires explicit justification)",
        file=sys.stderr,
    )
    sys.exit(1)


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

    # Track verdicts and all related specs for summary
    verdicts = {"covered": 0, "partial": 0, "none": 0}
    all_e2e_specs: list[str] = []
    checked_count = 0

    for filepath in sorted(files_to_check):
        # Skip test files themselves and non-source files
        if "/tests/" in filepath or "/__tests__/" in filepath or filepath.startswith("test_"):
            continue
        if not any(filepath.endswith(ext) for ext in (".py", ".ts", ".svelte")):
            continue

        checked_count += 1
        result = _find_tests_for_file(filepath)
        verdict = result["verdict"]
        verdicts[verdict] += 1

        # Collect unique spec names for the run command suggestion
        for spec in result.get("e2e_specs", []):
            if spec not in all_e2e_specs:
                all_e2e_specs.append(spec)

        verdict_icon = {"covered": "✅", "partial": "⚠️", "none": "❌"}[verdict]
        print(f"{verdict_icon} [{verdict.upper()}] {filepath}")

        if result["unit_tests"]:
            for t in result["unit_tests"]:
                print(f"    Unit: {t}")

        if result["e2e_tests"]:
            for t in result["e2e_tests"]:
                print(f"    E2E:  {t}")

        if verdict == "none":
            if result["suggestions"]:
                for s in result["suggestions"]:
                    lines = s.split("\n")
                    print(f"    → {lines[0]}")
                    for line in lines[1:]:
                        print(f"    {line}")

        print()

    # --- Summary ---
    print("── SUMMARY ──")
    print(f"  Files checked: {checked_count}")
    print(f"  Covered: {verdicts['covered']}  Partial: {verdicts['partial']}  None: {verdicts['none']}")

    if all_e2e_specs:
        print()
        print("  Related E2E specs to run:")
        for spec in sorted(all_e2e_specs):
            print(f"    python3 scripts/tests.py run --spec {spec}")

    if verdicts["none"] > 0:
        print()
        print("  ⚠️  Test-first enforcement: propose E2E tests for uncovered files")
        print("     before deploying. See testing.md 'Test-First Enforcement'.")

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
    """Trigger tests via the unified tests.py control plane."""
    suite = getattr(args, "suite", "all") or "all"
    env = getattr(args, "env", "development") or "development"

    tests_script = PROJECT_ROOT / "scripts" / "tests.py"
    if not tests_script.is_file():
        print("ERROR: scripts/tests.py not found.", file=sys.stderr)
        sys.exit(1)

    cmd = [sys.executable, str(tests_script), "run"]
    if suite != "all":
        cmd += ["--suite", suite]
    if env != "development":
        cmd += ["--environment", env]

    print(f"Running tests via tests.py (suite={suite}, environment={env})...")
    rc = subprocess.call(cmd, cwd=str(PROJECT_ROOT))
    sys.exit(rc)


def cmd_debug_vercel(args: argparse.Namespace) -> None:
    """Start a session and print Vercel build logs via the REST API (works for ERROR deployments)."""
    # Auto-start a session
    start_args = argparse.Namespace(
        mode="bug",
        task="debug Vercel deployment failure",
        tags="debug",
        issue=None,
        chat=None,
        embed=None,
        logs=None,
        user=None,
        debug_id=None,
        error_since=7,
        vercel=False,
        run_id=None,
        since_last_deploy=False,
        task_id=None,
        linear_issue=None,
        opencode_session=getattr(args, "opencode_session", None),
    )
    cmd_start(start_args)

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
# spawn-chat
# ---------------------------------------------------------------------------


def cmd_spawn_chat(args: argparse.Namespace) -> None:
    """Spawn a new Claude Code session in a separate Zellij tab.

    Creates an interactive Claude session visible in the Zellij web UI
    (localhost:8082) and attachable via `zellij attach <name>`.

    Default is plan mode (read-only). Use --mode execute for full edit access.
    """
    # Resolve prompt text
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.is_file():
            print(f"Error: prompt file not found: {args.prompt_file}", file=sys.stderr)
            sys.exit(1)
        prompt = (
            f"Read {args.prompt_file} in full and follow all the instructions precisely."
        )
    elif args.prompt:
        # Write inline prompt to temp file so claude reads it (avoids arg length issues)
        tmp_dir = PROJECT_ROOT / "scripts" / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        session_name = args.name or f"spawn-{int(datetime.now(timezone.utc).timestamp())}"
        prompt_file = tmp_dir / f"spawn-prompt-{session_name}.txt"
        prompt_file.write_text(args.prompt, encoding="utf-8")
        rel_path = prompt_file.relative_to(PROJECT_ROOT)
        prompt = f"Read {rel_path} in full and follow all the instructions precisely."
    else:
        print("Error: --prompt or --prompt-file is required.", file=sys.stderr)
        sys.exit(1)

    # Determine session name
    session_name = args.name or f"spawn-{int(datetime.now(timezone.utc).timestamp())}"

    # Determine mode and prepend behavioral instructions to the prompt
    permission_mode = args.mode or "plan"
    if permission_mode == "plan":
        mode_prefix = (
            "IMPORTANT: This is a PLAN-ONLY session. "
            "You MUST NOT edit, write, or create any files. "
            "Only read, search, and analyze code. "
            "Present your findings and proposed fix as a summary — do not implement it.\n\n"
        )
    else:
        mode_prefix = (
            "IMPORTANT: This is an EXECUTE session. "
            "You have full access to read, edit, and create files. "
            "Investigate the issue and implement the fix directly. "
            "Use sessions.py deploy to commit and push when done.\n\n"
        )

    # Handle Linear issue linking
    linear_issue_id = getattr(args, "linear_issue", None)
    linear_suffix = ""
    if linear_issue_id:
        try:
            scripts_dir = str(PROJECT_ROOT / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from _linear_client import get_issue, update_issue_status, add_label, post_comment
            issue_data = get_issue(linear_issue_id)
            if issue_data:
                # Mark In Progress + add claude-is-working label
                update_issue_status(issue_data["id"], "In Progress")
                add_label(issue_data["id"], issue_data.get("label_ids", []))
                # Post pickup comment
                post_comment(
                    issue_data["id"],
                    f"**Claude session started:** `{session_name}`\n\n"
                    f"**Mode:** {permission_mode}\n"
                    f"**Attach:** `zellij attach {session_name}`\n"
                    f"**Web UI:** http://localhost:8082"
                )
                print(f"Linear: {linear_issue_id} → In Progress + claude-is-working")

                # Build Linear MCP instructions for the prompt
                linear_suffix = (
                    f"\n\nLINEAR TASK TRACKING (REQUIRED):\n"
                    f"This session is linked to Linear issue {issue_data['identifier']}.\n"
                    f"Use the Linear MCP tools to keep the task updated:\n"
                    f"- Post SHORT progress comments (1-2 lines) on significant milestones:\n"
                    f'  mcp__linear__save_comment with issueId: "{issue_data["identifier"]}" and body: "your update"\n'
                    f"- Good examples: 'Found root cause in file.ts:245 — race condition on X'\n"
                    f"  or 'Fix deployed: commit abc123, updated key derivation'\n"
                    f"- At END: update status via mcp__linear__save_issue with\n"
                    f'  id: "{issue_data["identifier"]}", state: "In Review",\n'
                    f"  and post a final comment with resume commands:\n"
                    f"  zellij attach {session_name}\n"
                    f"  claude --resume <your-session-id>\n"
                )
            else:
                print(f"Warning: Could not fetch Linear issue {linear_issue_id}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Linear integration failed: {e}", file=sys.stderr)

    prompt = mode_prefix + prompt + linear_suffix

    try:
        from _zellij_utils import spawn_claude_session
    except ImportError:
        # Add scripts dir to path for import
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from _zellij_utils import spawn_claude_session

    success = spawn_claude_session(
        session_name=session_name,
        prompt=prompt,
        cwd=str(PROJECT_ROOT),
        permission_mode=permission_mode,
    )

    if success:
        mode_label = "execute (full access, skip-permissions)" if permission_mode == "execute" else "plan (research only, skip-permissions)"
        print(f"Session spawned: {session_name}")
        print(f"Mode: {mode_label}")
        print(f"Attach: zellij attach {session_name}")
        print("Web UI: http://localhost:8082")
    else:
        print("Error: failed to spawn session. Is Zellij running?", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# restore — Resume interrupted Claude Code sessions in Zellij
# ---------------------------------------------------------------------------

# Path to Claude Code's session storage for the OpenMates project
_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "projects" / "-home-superdev-projects-OpenMates"


def _discover_interrupted_sessions(
    max_age_hours: int = 24,
    limit: int = 15,
) -> list[dict]:
    """
    Scan Claude Code JSONL session files and return sessions that appear
    interrupted (have recent activity but no completion signal).

    Returns a list of dicts with keys:
        session_id, last_modified, first_user_msg, last_assistant_msg
    sorted by last_modified descending.
    """
    import json as _json
    import re as _re

    sessions_dir = _CLAUDE_SESSIONS_DIR
    if not sessions_dir.is_dir():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    results = []

    # Collect JSONL files sorted by mtime descending
    jsonl_files = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]

    for path in jsonl_files:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            continue

        session_id = path.stem
        first_user = None
        last_assistant = None

        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue

                    msg_type = obj.get("type", "")
                    msg = obj.get("message", {})
                    content = msg.get("content", "")

                    # Normalise content list → string
                    if isinstance(content, list):
                        texts = [
                            c.get("text", "")
                            for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        ]
                        content = " ".join(texts)
                    if not isinstance(content, str):
                        continue

                    # Strip system-reminder / command tags
                    content = _re.sub(
                        r"<system-reminder>.*?</system-reminder>", "", content, flags=_re.DOTALL
                    )
                    content = _re.sub(
                        r"<local-command.*?</local-command-stdout>", "", content, flags=_re.DOTALL
                    )
                    content = _re.sub(
                        r"<command-.*?>.*?</command-.*?>", "", content, flags=_re.DOTALL
                    )
                    content = content.strip()

                    if msg_type == "user" and not first_user and len(content) > 10:
                        first_user = content[:250]
                    if msg_type == "assistant" and content:
                        last_assistant = content[:250]
        except Exception:
            continue

        # Only include spawned sessions (started via spawn-chat with a prompt file)
        if not first_user or "Read scripts/.tmp/" not in first_user:
            continue

        # Detect completion signals in last assistant message
        completed = False
        if last_assistant:
            completion_phrases = [
                "all implementation is complete",
                "deployed as",
                "task summary",
                "successfully deployed",
                "session ended",
            ]
            lower = last_assistant.lower()
            completed = any(phrase in lower for phrase in completion_phrases)
            # "Committed X and pushed to dev" is a deploy confirmation
            if not completed and "committed" in lower and "pushed" in lower:
                completed = True

        results.append({
            "session_id": session_id,
            "last_modified": mtime.strftime("%Y-%m-%d %H:%M"),
            "first_user_msg": first_user or "(no user message found)",
            "last_assistant_msg": last_assistant or "(no output)",
            "likely_complete": completed,
        })

    return results


def cmd_git_stats(args: argparse.Namespace) -> None:
    """Delegate to scripts/git_stats.py for commit-activity and quality analytics."""
    script = Path(__file__).parent / "git_stats.py"
    cmd = [sys.executable, str(script), "--since", args.since, "--hotspots", str(args.hotspots)]
    if args.author:
        cmd += ["--author", args.author]
    if args.json:
        cmd += ["--json"]
    os.execvp(cmd[0], cmd)


def cmd_restore(args: argparse.Namespace) -> None:
    """Restore an interrupted Claude Code session in a new Zellij tab.

    Resumes the session with --resume and sends a continuation prompt.
    If --list is passed, discovers and prints recent interrupted sessions.
    """
    scripts_dir = str(PROJECT_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from _zellij_utils import resume_claude_session

    # --list mode: discover and print interrupted sessions
    if getattr(args, "list", False):
        sessions = _discover_interrupted_sessions(
            max_age_hours=getattr(args, "hours", 24),
        )
        if not sessions:
            print("No recent interrupted sessions found.")
            return

        # Extract OPE identifiers and fetch Linear titles in batch
        import re
        ope_ids_per_session = []
        all_ope_ids = set()
        for s in sessions:
            ope_match = re.search(r"OPE-\d+", s["first_user_msg"] or "")
            ope_id = ope_match.group(0) if ope_match else None
            ope_ids_per_session.append(ope_id)
            if ope_id:
                all_ope_ids.add(ope_id)

        # Batch-fetch Linear titles and states (graceful — returns {} on failure)
        linear_info_map: dict[str, dict[str, str]] = {}
        if all_ope_ids:
            try:
                from _linear_client import get_issues_batch
                linear_info_map = get_issues_batch(list(all_ope_ids))
            except Exception:
                pass  # Linear unavailable — fall back to ID-only display

        # Check git log for commits mentioning each OPE ID (recent 200 commits)
        ope_has_commits: dict[str, bool] = {}
        if all_ope_ids:
            try:
                import subprocess as _sp
                git_log = _sp.run(
                    ["git", "log", "--oneline", "-200", "--all"],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                    timeout=5,
                ).stdout
                for ope_id in all_ope_ids:
                    ope_has_commits[ope_id] = ope_id in git_log
            except Exception:
                pass  # git unavailable — skip commit check

        # Closed Linear states that mean the task is done
        _CLOSED_STATES = {"Done", "Cancelled", "Duplicate"}
        _REVIEW_STATES = {"In Review"}

        # Classify sessions and split into open vs closed
        open_sessions = []
        closed_sessions = []

        for i, s in enumerate(sessions):
            ope_id = ope_ids_per_session[i]

            # Extract action prefix (fix, verify, investigate, plan, test)
            if ope_id:
                action_match = re.search(r"spawn-prompt-(\w+)-OPE", s["first_user_msg"] or "")
                if not action_match:
                    action_match = re.search(r"planning-prompt-OPE", s["first_user_msg"] or "")
                    action = "plan" if action_match else ""
                else:
                    action = action_match.group(1)
            else:
                action = ""

            # Determine status from Linear state + git commits + heuristic
            linear_info = linear_info_map.get(ope_id) if ope_id else None
            linear_state = linear_info["state"] if linear_info else None
            has_commits = ope_has_commits.get(ope_id, False) if ope_id else False

            if linear_state in _CLOSED_STATES:
                status = "DONE"
            elif linear_state in _REVIEW_STATES:
                status = "REVIEW"
            elif has_commits and s["likely_complete"]:
                status = "DONE?"
            elif s["likely_complete"]:
                status = "DONE?"
            else:
                status = "INTR"

            # Build task hint
            if ope_id:
                title_suffix = f" — {linear_info['title']}" if linear_info else ""
                task_hint = f"{ope_id} ({action}){title_suffix}" if action else f"{ope_id}{title_suffix}"
            else:
                task_hint = s["last_assistant_msg"][:60] if s["last_assistant_msg"] else "(unknown)"

            entry = {
                **s,
                "ope_id": ope_id,
                "status": status,
                "task_hint": task_hint,
                "linear_state": linear_state,
                "has_commits": has_commits,
            }

            if status in ("DONE", "REVIEW", "DONE?"):
                closed_sessions.append(entry)
            else:
                open_sessions.append(entry)

        show_all = getattr(args, "show_all", False)

        # Print open sessions (always shown)
        if open_sessions:
            print(f"{'#':<3} {'Last Active':<17} {'Status':<8} {'Session ID':<38} Task")
            print("-" * 110)
            for i, entry in enumerate(open_sessions, 1):
                print(f"{i:<3} {entry['last_modified']:<17} {entry['status']:<8} {entry['session_id']:<38} {entry['task_hint']}")
        else:
            print("No open sessions found — all tasks appear completed.")

        # Print closed/review sessions (summary only, unless --all)
        if closed_sessions:
            if show_all:
                print(f"\n--- Completed/In Review ({len(closed_sessions)}) ---")
                for entry in closed_sessions:
                    state_tag = f"[{entry['linear_state']}]" if entry["linear_state"] else f"[{entry['status']}]"
                    commits_tag = " +commits" if entry["has_commits"] else ""
                    print(f"  {state_tag}{commits_tag}  {entry['session_id'][:8]}  {entry['task_hint']}")
            else:
                print(f"\n  Filtered out {len(closed_sessions)} completed session(s). Use --all to show them.")

        if open_sessions:
            print("\nRestore with: python3 scripts/sessions.py restore <session-id>")
            print("  or: python3 scripts/sessions.py restore <session-id> --name my-session --prompt 'custom message'")
        return

    # Single session restore
    session_id = args.session_id
    if not session_id:
        print("Error: session ID is required. Use --list to discover sessions.", file=sys.stderr)
        sys.exit(1)

    # Resolve short IDs (prefix match)
    if len(session_id) < 36:
        matches = list(_CLAUDE_SESSIONS_DIR.glob(f"{session_id}*.jsonl"))
        if len(matches) == 1:
            session_id = matches[0].stem
        elif len(matches) > 1:
            print(f"Error: ambiguous prefix '{session_id}' matches {len(matches)} sessions:", file=sys.stderr)
            for m in matches:
                print(f"  {m.stem}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Error: no session found matching '{session_id}'.", file=sys.stderr)
            sys.exit(1)

    # Determine Zellij session name
    zellij_name = getattr(args, "name", None) or f"restore-{session_id[:8]}"
    prompt = getattr(args, "prompt", None) or (
        "The server crashed and this session was interrupted. "
        "Continue where you left off."
    )

    success = resume_claude_session(
        session_name=zellij_name,
        claude_session_id=session_id,
        cwd=str(PROJECT_ROOT),
        prompt=prompt,
    )

    if success:
        print(f"Session restored: {zellij_name}")
        print(f"Claude session: {session_id}")
        print(f"Attach: zellij attach {zellij_name}")
        print("Web UI: http://localhost:8082")
    else:
        print("Error: failed to restore session. Is Zellij running?", file=sys.stderr)
        sys.exit(1)


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
    p_start.add_argument("--opencode-session", help=argparse.SUPPRESS)
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
    p_start.add_argument(
        "--linear-issue",
        "--linear",
        metavar="ISSUE_ID",
        help="Link to an existing Linear issue (e.g., OPE-42). "
        "Auto-fetches context, marks In Progress, adds claude-is-working label. "
        "If omitted and --task is set, a new Linear issue is auto-created.",
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
    p_end.add_argument(
        "--skip-visual-smoke",
        dest="skip_visual_smoke_reason",
        metavar="REASON",
        help="Skip the deployed visual-smoke end gate with an explicit reason.",
    )

    # visual-smoke
    p_visual_smoke = sub.add_parser(
        "visual-smoke",
        help="Record deployed UI visual-smoke evidence for a session",
    )
    p_visual_smoke.add_argument("--session", "-s", required=True, help="Session ID")
    p_visual_smoke.add_argument(
        "--url",
        action="append",
        help="Deployed app.dev.openmates.org URL inspected; repeat for multiple routes/viewports.",
    )
    p_visual_smoke.add_argument(
        "--viewport",
        action="append",
        choices=["laptop", "mobile"],
        help="Viewport class inspected. Passed smoke requires both: --viewport laptop --viewport mobile.",
    )
    p_visual_smoke.add_argument(
        "--result",
        required=True,
        choices=["passed", "failed", "blocked", "skipped"],
        help="Visual-smoke result.",
    )
    p_visual_smoke.add_argument(
        "--method",
        default="playwright",
        choices=["playwright", "firecrawl", "manual", "other"],
        help="Evidence method. Use playwright by default; firecrawl is an explicit fallback.",
    )
    p_visual_smoke.add_argument("--run-id", help="Playwright report path, Firecrawl job ID, screenshot ID, or other artifact ID.")
    p_visual_smoke.add_argument(
        "--screenshot",
        action="append",
        help="Screenshot artifact ID/path; repeat when useful.",
    )
    p_visual_smoke.add_argument(
        "--summary",
        help="Must include screenshot review, Defects:, and Accepted differences: for passed evidence.",
    )
    p_visual_smoke.add_argument("--reason", help="Required when result is skipped; optional context otherwise.")
    p_visual_smoke.add_argument("--commit", help="Subject commit SHA. Defaults to current HEAD.")

    # status
    p_status = sub.add_parser("status", help="Show current session state")
    p_status.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON (for machine consumers, e.g. opencode plugin)",
    )

    # doctor
    p_doctor = sub.add_parser(
        "doctor",
        help="Diagnose dirty-tree, staging, session tracking, and deploy-lock blockers",
    )
    p_doctor.add_argument(
        "--session", "-s", help="Session ID to focus the diagnosis on"
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
        "--session", "-s",
        help="Session ID (omit to resolve from $ZELLIJ_SESSION_NAME)",
    )
    p_track.add_argument("--file", "-f", required=True, nargs="+", help="File path(s)")

    # track-stdin (for hooks)
    p_track_stdin = sub.add_parser(
        "track-stdin", help="Track file from hook stdin"
    )
    p_track_stdin.add_argument("--session", "-s", help="Session ID")

    # untrack — remove files from a session's modified_files list
    p_untrack = sub.add_parser(
        "untrack",
        help="Remove file(s) from a session's modified_files list "
             "(opposite of track; cleans up ghost ownership)",
    )
    p_untrack.add_argument(
        "--session", "-s", required=True, help="Session ID to remove from"
    )
    p_untrack.add_argument(
        "--file", "-f", nargs="+",
        help="One or more file paths to untrack",
    )
    p_untrack.add_argument(
        "--all-ghosts", action="store_true",
        help="Remove every file currently in this session that is also "
             "tracked by another session whose zellij_session is recognized "
             "(one-time scrub for pre-fix ghost ownership)",
    )

    # check-write (for PreToolUse hook)
    p_check_write = sub.add_parser(
        "check-write", help="Check if file write is allowed (for hooks)"
    )
    p_check_write.add_argument(
        "--file", "-f", help="File path (optional; falls back to stdin JSON)"
    )

    p_edit_lease = sub.add_parser("edit-lease", help="Manage OpenCode multi-file edit leases")
    p_edit_lease_sub = p_edit_lease.add_subparsers(dest="edit_lease_action", required=True)
    p_edit_lease_acquire = p_edit_lease_sub.add_parser("acquire", help="Acquire edit leases before an edit tool call")
    p_edit_lease_acquire.add_argument("--session", "-s", help="Short sessions.py ID")
    p_edit_lease_acquire.add_argument("--opencode-session", help="OpenCode session ID")
    p_edit_lease_acquire.add_argument("--file", "-f", nargs="+", required=True, help="File path(s) to lease")
    p_edit_lease_release = p_edit_lease_sub.add_parser("release", help="Release edit leases after an edit tool call")
    p_edit_lease_release.add_argument("--session", "-s", help="Short sessions.py ID")
    p_edit_lease_release.add_argument("--opencode-session", help="OpenCode session ID")
    p_edit_lease_release.add_argument("--file", "-f", nargs="+", help="File path(s) to release; omit to release all held leases")

    p_stale_read = sub.add_parser("stale-read", help="Manage OpenCode stale-read hash protection")
    p_stale_read_sub = p_stale_read.add_subparsers(dest="stale_read_action", required=True)
    for action in ("record", "check", "sync"):
        p_stale_read_action = p_stale_read_sub.add_parser(action)
        p_stale_read_action.add_argument("--opencode-session", required=True, help="OpenCode session ID")
        p_stale_read_action.add_argument("--file", required=True, help="Repository file path")

    p_worktree = sub.add_parser("worktree", help="Manage automatic local session worktrees")
    p_worktree_sub = p_worktree.add_subparsers(dest="worktree_action", required=True)
    p_worktree_ensure = p_worktree_sub.add_parser("ensure", help="Create or show this session's worktree")
    p_worktree_ensure.add_argument("--session", "-s", required=True, help="Session ID")
    p_worktree_binding = p_worktree_sub.add_parser("binding", help="Record an OpenCode native-binding result")
    p_worktree_binding.add_argument("--opencode-session", required=True, help="OpenCode session ID")
    p_worktree_binding.add_argument("--mode", required=True, choices=["native", "pilot_fallback"])
    p_worktree_binding.add_argument("--directory", help="Canonical native session directory")
    p_worktree_binding.add_argument("--reason", help="Stable pilot fallback reason")
    p_worktree_cleanup = p_worktree_sub.add_parser("cleanup", help="Delete safely classified stale worktrees")
    p_worktree_cleanup.add_argument(
        "--idle-hours",
        type=int,
        default=WORKTREE_CLEANUP_IDLE_HOURS,
        help="Hours before safely classified stale worktrees may be deleted (default: 48)",
    )
    p_worktree_reconcile = p_worktree_sub.add_parser("reconcile", help="Report or safely reconcile all worktrees")
    p_worktree_reconcile.add_argument("--target", default="origin/dev", help="Exact integration ref (default: origin/dev)")
    p_worktree_reconcile.add_argument("--idle-hours", type=int, default=WORKTREE_CLEANUP_IDLE_HOURS)
    p_worktree_reconcile.add_argument("--apply-safe", action="store_true", help="Delete only eligible safe classifications")
    p_worktree_reconcile.add_argument(
        "--approve-obsolete",
        action="append",
        default=[],
        metavar="SESSION_ID",
        help="Mark reviewed work obsolete; immediate cleanup also requires matching --only and --idle-hours 0",
    )
    p_worktree_reconcile.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="SESSION_ID",
        help="Limit reconciliation to an explicit session ID; required before lowering --idle-hours",
    )
    p_worktree_reconcile.add_argument("--format", choices=["text", "json"], default="text")
    p_worktree_readiness = p_worktree_sub.add_parser(
        "release-readiness", help="Check worktree state before a dev-to-main pull request"
    )
    p_worktree_readiness.add_argument("--target", default="origin/dev", help="Exact release ref (default: origin/dev)")
    p_worktree_readiness.add_argument(
        "--exclude-active",
        action="append",
        default=[],
        metavar="SESSION_ID",
        help="Explicitly exclude one recent active worktree; repeat for multiple IDs",
    )
    p_worktree_readiness.add_argument("--format", choices=["text", "json"], default="text")

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

    # wait-lock
    p_wait_lock = sub.add_parser(
        "wait-lock",
        help="Wait until a shared Docker/Vercel lock is available",
    )
    p_wait_lock.add_argument(
        "--session", "-s", help="Session ID waiting for the lock"
    )
    p_wait_lock.add_argument(
        "--type",
        "-t",
        required=True,
        choices=["docker", "vercel", "docker_rebuild", "vercel_deploy"],
        help="Lock type",
    )
    p_wait_lock.add_argument(
        "--timeout",
        type=int,
        help="Seconds to wait before failing (default: lock stale timeout)",
    )
    p_wait_lock.add_argument(
        "--poll",
        type=int,
        default=30,
        help="Seconds between checks (default: 30)",
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
    p_deploy.add_argument(
        "--use-staged",
        action="store_true",
        dest="use_staged",
        help="Commit already staged hunks for the tracked session files instead of "
        "running git add on whole files. Use for concurrent same-file edits.",
    )
    p_deploy.add_argument(
        "--skip-tests",
        dest="skip_tests_reason",
        metavar="REASON",
        help="Skip test enforcement gate with an explicit reason "
        "(e.g., 'hotfix, will add test in follow-up'). Reason is logged.",
    )
    p_deploy.add_argument(
        "--skip-visual-smoke",
        dest="skip_visual_smoke_reason",
        metavar="REASON",
        help="Skip the deployed visual-smoke end gate with an explicit reason. Only applies with --end.",
    )
    p_deploy.add_argument(
        "--require-parity",
        action="store_true",
        dest="require_parity",
        help="Require a fresh no-skip scripts/verify_parity.py summary before deploy.",
    )
    p_deploy.add_argument(
        "--lock-timeout",
        type=int,
        dest="lock_timeout",
        help="Seconds to wait for the dev deploy push lock before committing "
        "(default: lock stale timeout).",
    )
    p_deploy.add_argument(
        "--lock-poll",
        type=int,
        default=30,
        dest="lock_poll",
        help="Seconds between dev deploy push lock checks (default: 30).",
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

    # spawn-chat
    p_spawn = sub.add_parser(
        "spawn-chat",
        help="Spawn a Claude Code session in a separate Zellij tab",
    )
    p_spawn.add_argument(
        "--prompt",
        help="Prompt text to send to Claude (written to temp file internally)",
    )
    p_spawn.add_argument(
        "--prompt-file",
        help="Path to a prompt file (Claude reads it directly)",
    )
    p_spawn.add_argument(
        "--name", "-n",
        help="Session name (default: auto-generated from timestamp)",
    )
    p_spawn.add_argument(
        "--mode",
        choices=["plan", "execute"],
        default="plan",
        help="Permission mode: 'plan' (read-only, default) or "
        "'execute' (full edit access via --dangerously-skip-permissions)",
    )
    p_spawn.add_argument(
        "--linear-issue", "--linear",
        metavar="ISSUE_ID",
        help="Linear issue to link (e.g., OPE-42). Auto-marks In Progress, "
        "adds claude-is-working label, and injects Linear update instructions.",
    )

    # restore
    p_restore = sub.add_parser(
        "restore",
        help="Restore an interrupted Claude Code session in a Zellij tab",
    )
    p_restore.add_argument(
        "session_id",
        nargs="?",
        help="Claude Code session UUID (or prefix) to resume",
    )
    p_restore.add_argument(
        "--list", "-l",
        action="store_true",
        help="Discover and list recent interrupted sessions",
    )
    p_restore.add_argument(
        "--name", "-n",
        help="Zellij session name (default: restore-<id-prefix>)",
    )
    p_restore.add_argument(
        "--prompt",
        help="Custom continuation prompt (default: 'continue where you left off')",
    )
    p_restore.add_argument(
        "--hours",
        type=int,
        default=24,
        help="How far back to scan for sessions (default: 24h, used with --list)",
    )
    p_restore.add_argument(
        "--all", "-a",
        action="store_true",
        dest="show_all",
        help="Show completed/in-review sessions too (default: hidden)",
    )

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

    p_git_stats = sub.add_parser(
        "git-stats",
        help="Show per-week commit activity, churn hotspots, and quality signals",
    )
    p_git_stats.add_argument("--since", default="6 months ago",
                             help="git log --since value (default: '6 months ago')")
    p_git_stats.add_argument("--author", default=None, help="Restrict to one author")
    p_git_stats.add_argument("--hotspots", type=int, default=20,
                             help="Number of churn hotspot files to show (default: 20)")
    p_git_stats.add_argument("--json", action="store_true",
                             help="Emit JSON instead of tables")

    args = parser.parse_args()

    commands = {
        "start": cmd_start,
        "end": cmd_end,
        "visual-smoke": cmd_visual_smoke,
        "status": cmd_status,
        "doctor": cmd_doctor,
        "update": cmd_update,
        "claim": cmd_claim,
        "release": cmd_release,
        "track": cmd_track,
        "track-stdin": cmd_track_stdin,
        "untrack": cmd_untrack,
        "check-write": cmd_check_write,
        "edit-lease": cmd_edit_lease,
        "stale-read": cmd_stale_read,
        "worktree": cmd_worktree,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
        "wait-lock": cmd_wait_lock,
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
        "task-create": cmd_task_create,
        "task-step": cmd_task_step,
        "task-ac": cmd_task_ac,
        "task-show": cmd_task_show,
        "task-list": cmd_task_list,
        "task-update": cmd_task_update,
        "task-track": cmd_task_track,
        "spawn-chat": cmd_spawn_chat,
        "restore": cmd_restore,
        "git-stats": cmd_git_stats,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
