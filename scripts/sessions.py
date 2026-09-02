#!/usr/bin/env python3
"""
Session lifecycle manager for concurrent OpenMates agent sessions.

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

    # OpenCode transcript debugging
    python3 scripts/sessions.py opencode-chat read https://code.dev.openmates.org/<project>/session/ses_...
    python3 scripts/sessions.py opencode-chat search ses_... "worktree"
    python3 scripts/sessions.py chat attachments ses_... --out /tmp/opencode/chat-files
    python3 scripts/sessions.py chat read ses_...  # alias for opencode-chat

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
import base64
import binascii
import fcntl
import fnmatch
import glob as glob_mod
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from scripts.opencode_presence_store import PresenceStore, PresenceStoreError, TaskClaimConflict
except ModuleNotFoundError:
    from opencode_presence_store import PresenceStore, PresenceStoreError, TaskClaimConflict

try:
    from scripts.engineering_control_plane import (
        ControlPlaneApiError,
        ENV_FILE as ENGINEERING_CONTROL_PLANE_ENV_FILE,
        control_plane_api_request,
    )
except ModuleNotFoundError:
    from engineering_control_plane import (
        ControlPlaneApiError,
        ENV_FILE as ENGINEERING_CONTROL_PLANE_ENV_FILE,
        control_plane_api_request,
    )

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
OPENCODE_PRESENCE_STATE_FILE = CONTROL_PLANE_ROOT / ".opencode" / "presence.json"
OPENCODE_PRESENCE_LOCK_FILE = CONTROL_PLANE_ROOT / ".opencode" / "presence.lock"
CONTROL_PLANE_DEPLOY_PROTOCOL_FILE = ".opencode/deploy-protocol-version"
CONTROL_PLANE_DEPLOY_PROTOCOL_VERSION = 2
OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
OPENCODE_SERVER_URL = os.environ.get("OPENCODE_SERVER_URL", "http://127.0.0.1:4096")
OPENCODE_RESTART_ACTIVE_STATUSES = {"busy", "retry"}
OPENCODE_WEB_BASE_URL = os.environ.get("OPENCODE_WEB_BASE_URL", "https://code.dev.openmates.org")
CODE_MAPPING_FILE = PROJECT_ROOT / "docs" / "architecture" / "code-mapping.yml"
STALE_SESSION_HOURS = 24
STALE_EMPTY_SESSION_HOURS = 6  # Sessions with zero tracked files expire faster
STALE_LOCK_MINUTES = 5
CHECKPOINT_LOCK_RETENTION_HOURS = 24
VERCEL_DEPLOY_LOCK_MINUTES = 90
DOCKER_TEST_LEASE_TTL_SECONDS = 30 * 60
DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS = 60
DOCKER_OPERATION_HISTORY_LIMIT = 20
DOCKER_OPERATION_ACTIVE_STATUSES = {"queued", "admitted", "draining_tests", "restarting", "verifying"}
DOCKER_OPERATION_TERMINAL_STATUSES = {"completed", "failed"}
DOCKER_RESOURCE_DEV_STACK = "dev-stack"
DOCKER_RESTART_DEFAULT_TIMEOUT_SECONDS = 2 * 60 * 60
DOCKER_OPERATION_TTL_SECONDS = 3 * 60 * 60
DOCKER_HEALTH_DEFAULT_TIMEOUT_SECONDS = 5 * 60
PRODUCT_RUNTIME_CHECKOUT = CONTROL_PLANE_ROOT.parent / ".openmates-runtime" / "product-stack"
PRODUCT_RUNTIME_STATE_FILE = CONTROL_PLANE_ROOT / ".claude" / "product-runtime-state.json"
PRODUCT_RUNTIME_STATE_LOCK_FILE = CONTROL_PLANE_ROOT / ".claude" / "product-runtime-state.lock"
PRODUCT_RUNTIME_GENERATED_PATHS = frozenset(
    {
        "docs/architecture/compliance/browser-storage.yml",
        "docs/architecture/compliance/cookies.yml",
    }
)
API_HEALTH_DEFAULT_URL = "https://api.dev.openmates.org/health"
API_HEALTH_INCIDENT_STALE_SECONDS = 5 * 60
API_HEALTH_PROBE_TIMEOUT_SECONDS = 10
CONTINUATION_ALLOWED_TYPES = {"resource_ready", "health_ready", "deployment_ready", "media_delivery", "task_ready"}
CONTINUATION_MAX_DELIVERY_ATTEMPTS = 2
OPENMATES_TASK_BRIDGE_PROFILE = "opencode-personal"
OPENMATES_TASK_BRIDGE_API_URL = "https://api.dev.openmates.org"
OPENMATES_TASK_BRIDGE_TIMEOUT_SECONDS = 20
OPENMATES_TASK_BRIDGE_MAX_JSON_BYTES = 4 * 1024 * 1024
OPENMATES_TASK_OPEN_STATUSES = {"backlog", "todo", "in_progress", "blocked"}
OPENMATES_TASK_WAIT_QUEUE_STATES = {"waiting", "waiting_for_user", "blocked"}
OPENMATES_TASK_STOP_EXECUTION_STATES = {"failed", "aborted", "stopped", "waiting_for_user"}
MEDIA_DELIVERY_MAX_ATTEMPTS = 2
MEDIA_AUTOMATION_ENABLED = os.environ.get("OPENMATES_OPENCODE_RESPONSE_MEDIA_AUTOMATION", "").strip() == "1"
PROTECTED_CONTROL_PLANE_EXACT_PATHS = frozenset(
    {
        "opencode.json",
        "scripts/opencode_permission_watcher.py",
        "scripts/opencode_credential_migration.py",
        "scripts/opencode_runtime_release.py",
        "scripts/sync_opencode_runtime_hook.py",
        "scripts/sessions.py",
        "scripts/server-restart.sh",
        "scripts/start-opencode-server.sh",
    }
)
PROTECTED_CONTROL_PLANE_PREFIXES = (
    ".opencode/",
    "backend/engineering_control_plane/",
    "scripts/patches/opencode-",
)
PREPARED_VERIFICATION_PROFILES = {
    "cli-typecheck": {
        "command": ["pnpm", "--dir", "frontend/packages/openmates-cli", "run", "typecheck"],
        "dependency_paths": ["node_modules", "frontend/packages/openmates-cli/node_modules"],
        "timeout": 300,
    },
    "cli-storage-unit": {
        "command": ["pnpm", "--dir", "frontend/packages/openmates-cli", "run", "test:unit:storage"],
        "dependency_paths": ["node_modules", "frontend/packages/openmates-cli/node_modules"],
        "timeout": 300,
    },
}
DOCKER_COMPOSE_FILE = CONTROL_PLANE_ROOT / "backend" / "core" / "docker-compose.yml"
DOCKER_COMPOSE_OVERRIDE = CONTROL_PLANE_ROOT / "backend" / "core" / "docker-compose.override.yml"
DOCKER_SETUP_SERVICES = {"cms-setup", "vault-setup"}
DOCKER_NON_RESTARTABLE_SERVICES = DOCKER_SETUP_SERVICES
WORKTREE_CLEANUP_IDLE_HOURS = 48
WORKTREE_HARD_MAX_AGE_HOURS = 72
WORKTREE_MAX_COUNT = int(os.environ.get("OPENMATES_WORKTREE_MAX_COUNT", "200"))
WORKTREE_MIN_FREE_BYTES = int(float(os.environ.get("OPENMATES_WORKTREE_MIN_FREE_GIB", "30")) * 1024**3)
WORKTREE_MAX_DISK_PERCENT = int(os.environ.get("OPENMATES_WORKTREE_MAX_DISK_PERCENT", "85"))
WORKTREE_MANIFEST_RETENTION_HOURS = 30 * 24
WORKTREE_AUTO_INTEGRATION_GRACE_MINUTES = 15
WORKTREE_AUTO_INTEGRATION_BINDING_MODES = {"native", "pilot_fallback", "worktree_routed"}
WORKTREE_AUTO_INTEGRATION_SENSITIVE_PREFIXES = (
    ".env",
    ".claude/",
    ".codex/",
    ".github/workflows/",
    ".opencode/",
    "apple/",
    "backend/core/api/app/routes/auth",
    "backend/core/directus/migrations/",
    "backend/core/directus/schema/",
    "scripts/apple_remote.py",
    "scripts/prod-",
    "scripts/sessions.py",
    "scripts/worktree-",
)
WORKTREE_AUTO_INTEGRATION_SENSITIVE_PATH_RE = re.compile(
    r"(^|/)(auth|billing|encrypt(?:ion)?|entitlements?|migrations?|payments?|permissions?|privacy|secrets?|signing)(/|[._-])",
    re.IGNORECASE,
)
WORKTREE_AUTO_INTEGRATION_SENSITIVE_SUFFIXES = (".key", ".mobileprovision", ".p12", ".pbxproj", ".pem")
WORKTREE_NON_DEPLOYABLE_RUNTIME_PREFIXES = ("scripts/.tmp/", "test-results/")
WORKTREE_ROOT_HANDOFF_DENIED_PATHS = frozenset({"config.json"})
WORKTREE_ROOT_HANDOFF_DENIED_PREFIXES = (".git/", "logs/nightly-reports/")
WORKTREE_CHECKPOINT_LOCKS_DIR = CONTROL_PLANE_ROOT / ".claude" / "checkpoint-locks"
WORKTREE_RECONCILIATION_REPORT = CONTROL_PLANE_ROOT / "logs" / "nightly-reports" / "worktree-reconciliation.json"
DEFAULT_REPO_ID = "openmates"
OPENMATESCLOUD_REPO_ID = "openmatescloud"
OPENMATESCLOUD_REPO_ROOT = (CONTROL_PLANE_ROOT.parent / "OpenMatesCloud").resolve()
OPENMATESCLOUD_REPO_BRANCH = "main"
OPENMATESCLOUD_REPO_REMOTE = "origin"
OPENMATESCLOUD_REPO_REMOTE_ID_SHA256 = "7fccd2227ef3f311f489546cb0823c292a28aec9d7dafc2840389f022246e490"
REPO_ALIASES = {
    "default": DEFAULT_REPO_ID,
    "openmates": DEFAULT_REPO_ID,
    "openmatescloud": OPENMATESCLOUD_REPO_ID,
    "openmates-cloud": OPENMATESCLOUD_REPO_ID,
    "cloud": OPENMATESCLOUD_REPO_ID,
}
SPECIFICATION_GENERATED_ARTIFACTS = {
    "specifications/generated/assertion-index.yml",
    "specifications/generated/coverage.yml",
    "specifications/generated/registry.yml",
}
WORKTREE_BOOTSTRAP_TIMEOUT_SECONDS = 300
WORKTREE_SHARED_RUNTIME_PATHS = (Path(".env"), Path("logs/nightly-reports"))
WORKTREE_BINDING_MODES = {"pending", "native", "pilot_fallback", "legacy_grandfathered", "worktree_routed", "repo_routed"}
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
VISUAL_SMOKE_PLAN_PATH_RE = re.compile(r"^docs/plans/.+/plan\.yml$")
VISUAL_SMOKE_HIGH_RISK_RE = re.compile(
    r"(ActiveChat|Chat|MessageInput|Composer|Settings|Share|Embed|Landing|DailyInspiration|Welcome|Auth|Login|Signup|Billing|Usage|Navigation|Header|Sidebar)",
    re.IGNORECASE,
)
VISUAL_SMOKE_PASS_STATUSES = {"passed", "skipped"}
VISUAL_SMOKE_REQUIRED_VIEWPORTS = {"laptop", "mobile"}
VISUAL_SMOKE_REVIEW_RE = re.compile(r"\bscreenshot\w*\b.*\breview\w*\b|\breview\w*\b.*\bscreenshot\w*\b", re.IGNORECASE | re.DOTALL)
VISUAL_SMOKE_DEFECTS_RE = re.compile(r"\b(defects?|issues?|findings?)\s*:", re.IGNORECASE)
VISUAL_SMOKE_ACCEPTED_DIFF_RE = re.compile(r"\baccepted differences?\s*:", re.IGNORECASE)
PROOF_VIDEO_PRODUCT_PATH_RE = re.compile(
    r"^(frontend/(apps/web_app/src|packages/ui/src|packages/openmates-cli/src)/|backend/(apps|core|shared)/|packages/openmates-python/openmates/|apple/)",
)
PROOF_VIDEO_DEV_TEST_RECORDING_CLEANUP_PATHS = {
    "backend/core/api/app/routes/test_recordings.py",
    "backend/core/api/main.py",
    "backend/tests/test_test_recordings.py",
    "deployment/dev_server/Caddyfile",
    "scripts/audit_rest_api_surface.py",
}
PROOF_VIDEO_EXAMPLE_CHAT_PATH_RE = re.compile(
    r"^(frontend/packages/ui/src/(data/web-app-example-chats\.json|demo_chats/data/example_chats/|i18n/sources/example_chats/)|frontend/apps/web_app/tests/.*example-chat.*\.spec\.ts$)",
    re.IGNORECASE,
)
PROOF_VIDEO_E2E_PATH_RE = re.compile(r"^frontend/apps/web_app/tests/.+\.spec\.ts$", re.IGNORECASE)
PROOF_VIDEO_NOT_REQUIRED_RE = re.compile(r"proof-video:\s*not_required\s+reason=([A-Za-z0-9_.-]+)")
PROOF_VIDEO_NOT_REQUIRED_REASONS = {
    "api_setup",
    "account_health",
    "cleanup_only",
    "cli_helper",
    "non_visual_setup",
    "performance_probe",
    "storage_audit",
    "visual_smoke_not_needed",
}
PROOF_VIDEO_PASS_STATUSES = {"passed", "reviewed"}
PROOF_VIDEO_PRIVACY_ACCEPTED_STATUSES = {"passed", "not_applicable"}
PROOF_VIDEO_DEVICE_PROFILES = {
    "cli-terminal": (1280, 720),
    "web-phone": (390, 844),
    "web-laptop": (1440, 900),
    "apple-iphone-portrait": (393, 852),
    "apple-ipad-landscape": (1366, 1024),
}
OPENMATES_CLI_PROOF_EXECUTABLES = {"openmates", "openmates-cli"}
OPENMATES_CLI_PROOF_SOURCE_MARKERS = (
    "frontend/packages/openmates-cli",
    "packages/openmates-cli",
)
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
OPENCODE_SESSION_ID_RE = re.compile(r"^ses_[A-Za-z0-9_-]+$")
OPENCODE_CHAT_URL_SESSION_RE = re.compile(r"/session/(?P<session>ses_[A-Za-z0-9_-]+)")
OPENCODE_CHAT_ISSUE_RE = re.compile(
    r"(^|\n)\s*error:|\b(blocked|failed|failure|traceback|timeout|timed out|permission denied|no active sessions\.py|"
    r"apply_patch verification failed)\b",
    re.IGNORECASE,
)
OPENCODE_CHAT_ARTIFACT_RE = re.compile(r"(Full output saved to:|output truncated)", re.IGNORECASE)
OPENCODE_CHAT_DEFAULT_MAX_MESSAGES = 160
OPENCODE_CHAT_DEFAULT_MAX_PARTS_PER_MESSAGE = 24
OPENCODE_CHAT_DEFAULT_MAX_PART_CHARS = 1_500
OPENCODE_CHAT_DEFAULT_MAX_ISSUES = 60
OPENCODE_CHAT_TOOL_OUTPUT_PREVIEW_CHARS = 600
OPENCODE_CHAT_TEXT_CHILD_SESSION_LIMIT = 25
OPENCODE_CHAT_REPOSITORY_FILE_LIMIT = 50
OPENCODE_CHAT_ATTACHMENT_TYPES = {"file", "image", "attachment"}
OPENCODE_CHAT_ATTACHMENT_LIMIT = 100
OPENCODE_CHAT_SIGNAL_MODES = {"actionable", "all"}
COORDINATION_COMPLETED_HOURS = 1
COORDINATION_SESSION_LIMIT = 12

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
MODE_ALIASES = {
    "debug": "bug",
    "execute": "feature",
    "investigate": "question",
    "investigation": "question",
    "plan": "question",
}

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


def _resolve_repo_id(raw_repo: str | None) -> str:
    """Normalize a user-facing repository selector to a supported repo id."""
    key = (raw_repo or DEFAULT_REPO_ID).strip().lower()
    repo_id = REPO_ALIASES.get(key)
    if not repo_id:
        supported = ", ".join(sorted(REPO_ALIASES))
        raise ValueError(f"Unsupported repository {raw_repo!r}. Supported: {supported}")
    return repo_id


def _repo_metadata(repo_id: str) -> dict[str, str]:
    """Return allowlisted repository metadata for the session control plane."""
    if repo_id == DEFAULT_REPO_ID:
        return {
            "repo_id": DEFAULT_REPO_ID,
            "repo_name": "OpenMates",
            "repo_root": str(CONTROL_PLANE_ROOT.resolve()),
            "repo_branch": "dev",
            "repo_remote": "origin",
            "repo_kind": "control_plane",
        }
    if repo_id == OPENMATESCLOUD_REPO_ID:
        return {
            "repo_id": OPENMATESCLOUD_REPO_ID,
            "repo_name": "OpenMatesCloud",
            "repo_root": str(OPENMATESCLOUD_REPO_ROOT),
            "repo_branch": OPENMATESCLOUD_REPO_BRANCH,
            "repo_remote": OPENMATESCLOUD_REPO_REMOTE,
            "repo_remote_identity_sha256": OPENMATESCLOUD_REPO_REMOTE_ID_SHA256,
            "repo_kind": "sibling",
        }
    raise ValueError(f"Unsupported repository id: {repo_id}")


def _session_repo_metadata(session: dict | None) -> dict[str, str]:
    """Return canonical allowlisted metadata for a persisted session."""
    return _repo_metadata(_session_repo_id(session))


def _remote_identity_sha256(remote_url: str) -> str:
    """Hash the canonical git remote identity without storing private URLs."""
    normalized = remote_url.strip().rstrip("/")
    if not normalized:
        return ""
    if "://" in normalized:
        parsed = urllib.parse.urlparse(normalized)
        try:
            port = parsed.port
        except ValueError:
            return ""
        default_ports = {"git": 9418, "http": 80, "https": 443, "ssh": 22}
        if port and default_ports.get(parsed.scheme) != port:
            return ""
        host = parsed.hostname or ""
        path = parsed.path.lstrip("/")
        identity = f"{host.lower()}/{path}" if host and path else normalized
    elif re.match(r"^[^@]+@[^:]+:.+", normalized):
        user_host, path = normalized.split(":", 1)
        host = user_host.rsplit("@", 1)[-1]
        identity = f"{host.lower()}/{path.lstrip('/')}"
    else:
        identity = str(Path(normalized).expanduser().resolve())
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _validate_session_repo(repo: dict[str, str]) -> None:
    """Fail fast when an allowlisted sibling repository is unavailable."""
    root = Path(repo["repo_root"])
    if repo.get("repo_kind") == "control_plane":
        return
    if not root.is_dir():
        raise RuntimeError(f"{repo['repo_name']} checkout not found: {root}")
    rc, stdout, stderr = _run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=str(root))
    if rc != 0 or Path(stdout).resolve() != root.resolve():
        raise RuntimeError(f"{repo['repo_name']} is not a git checkout at {root}: {stderr or stdout}")
    rc, stdout, stderr = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root))
    expected_branch = repo["repo_branch"]
    if rc != 0 or stdout.strip() != expected_branch:
        raise RuntimeError(
            f"{repo['repo_name']} checkout must be on {expected_branch}: {stderr or stdout or '<unknown>'}"
        )
    expected_remote = repo["repo_remote"]
    rc, stdout, stderr = _run_cmd(["git", "remote", "get-url", expected_remote], cwd=str(root))
    expected_remote_identity = repo.get("repo_remote_identity_sha256")
    if rc != 0 or not expected_remote_identity or _remote_identity_sha256(stdout) != expected_remote_identity:
        detail = stderr or "remote identity mismatch"
        raise RuntimeError(f"{repo['repo_name']} {expected_remote} remote is not valid: {detail}")


def _session_repo_id(session: dict | None) -> str:
    return str((session or {}).get("repo_id") or DEFAULT_REPO_ID)


def _session_repo_name(session: dict | None) -> str:
    return _session_repo_metadata(session)["repo_name"]


def _session_repo_branch(session: dict | None) -> str:
    return _session_repo_metadata(session)["repo_branch"]


def _session_repo_remote(session: dict | None) -> str:
    return _session_repo_metadata(session)["repo_remote"]


def _session_checkout_root(session: dict | None) -> Path:
    repo_root = Path(_session_repo_metadata(session)["repo_root"]).expanduser().resolve()
    # Only the control-plane repository uses per-session managed worktrees.
    # Persisted or injected worktree metadata must never redirect a sibling
    # repository session outside its allowlisted checkout.
    if repo_root != CONTROL_PLANE_ROOT.resolve():
        return repo_root
    worktree = (session or {}).get("worktree")
    if isinstance(worktree, dict) and worktree.get("path"):
        return Path(str(worktree["path"])).expanduser().resolve()
    return repo_root


def _session_is_control_plane_repo(session: dict | None) -> bool:
    repo_root = Path(_session_repo_metadata(session)["repo_root"]).expanduser().resolve()
    return repo_root == CONTROL_PLANE_ROOT.resolve()


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
    """Return the repo-relative path for a file inside a routed session checkout."""
    if not SESSIONS_FILE.is_file():
        return None
    try:
        sessions = json.loads(SESSIONS_FILE.read_text(encoding="utf-8")).get("sessions", {})
    except (json.JSONDecodeError, OSError):
        return None
    candidates: list[Path] = []
    for session in sessions.values():
        worktree_path = session.get("worktree", {}).get("path") if isinstance(session, dict) else None
        repo_root = session.get("repo_root") if isinstance(session, dict) else None
        for candidate in (worktree_path, repo_root):
            if not candidate:
                continue
            try:
                candidates.append(Path(candidate).resolve())
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


def _decode_opencode_project_path(encoded: str) -> str | None:
    value = urllib.parse.unquote(encoded.strip())
    if not value:
        return None
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return decoded if decoded.startswith("/") else None


def _repo_session_opencode_id(reference: str) -> str | None:
    """Resolve a short sessions.py repository ID to its OpenCode chat ID."""
    try:
        session = _load_sessions().get("sessions", {}).get(reference)
    except Exception:
        return None
    if not isinstance(session, dict):
        return None
    opencode_session_id = str(session.get("opencode_session_id") or "")
    return opencode_session_id if OPENCODE_SESSION_ID_RE.match(opencode_session_id) else None


def parse_opencode_chat_reference(reference: str) -> dict[str, str | None]:
    """Return the OpenCode session ID and optional project path from a chat URL or repo session ID."""
    raw = reference.strip()
    if not raw:
        raise ValueError("OpenCode chat reference is required")
    if OPENCODE_SESSION_ID_RE.match(raw):
        return {"session_id": raw, "project_directory": None}
    if repo_opencode_id := _repo_session_opencode_id(raw):
        return {"session_id": repo_opencode_id, "project_directory": None, "repository_session_id": raw}

    parsed = urllib.parse.urlparse(raw)
    segments = [segment for segment in parsed.path.split("/") if segment]
    for index, segment in enumerate(segments):
        if segment != "session" or index + 1 >= len(segments):
            continue
        session_id = urllib.parse.unquote(segments[index + 1])
        if not OPENCODE_SESSION_ID_RE.match(session_id):
            break
        project_directory = _decode_opencode_project_path(segments[index - 1]) if index > 0 else None
        return {"session_id": session_id, "project_directory": project_directory}

    match = OPENCODE_CHAT_URL_SESSION_RE.search(raw)
    if match:
        return {"session_id": match.group("session"), "project_directory": None}
    raise ValueError("Expected an OpenCode session ID, short repository session ID, or /<project>/session/ses_... URL")


def opencode_chat_url(session_id: str, project_directory: str | Path | None = None) -> str:
    """Return the OpenCode Web deep link for a local project/session pair."""
    directory = str(Path(project_directory or CONTROL_PLANE_ROOT).resolve())
    encoded = base64.urlsafe_b64encode(directory.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{OPENCODE_WEB_BASE_URL.rstrip('/')}/{encoded}/session/{session_id}"


def _opencode_timestamp_iso(value: object) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown"


def _opencode_readonly_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = (db_path or OPENCODE_DB_PATH).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"OpenCode database not found: {path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _decode_opencode_json(raw: object) -> Any:
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return raw


def _truncate_opencode_value(value: Any, max_chars: int, truncated: dict[str, bool]) -> Any:
    if isinstance(value, str):
        if len(value) > max_chars:
            truncated["fields"] = True
            return value[:max_chars] + "...[truncated]"
        return value
    if isinstance(value, dict):
        return {str(key): _truncate_opencode_value(item, max_chars, truncated) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_opencode_value(item, max_chars, truncated) for item in value]
    return value


def _bounded_opencode_text(value: Any, max_chars: int, truncated: dict[str, bool]) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else ""
    bounded = _truncate_opencode_value(text, max_chars, truncated)
    return str(bounded)


def _opencode_message_projection(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"role": "unknown", "raw": data}
    projected = {
        key: data[key]
        for key in ("role", "agent", "mode", "modelID", "providerID", "finish")
        if key in data
    }
    model = data.get("model")
    if isinstance(model, dict):
        projected["model"] = {
            key: model[key]
            for key in ("providerID", "modelID", "variant")
            if key in model
        }
    return projected


def _opencode_part_projection(
    data: Any,
    *,
    include_tool_output: bool,
    max_chars: int,
    truncated: dict[str, bool],
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return {"type": "unknown", "value": _truncate_opencode_value(data, max_chars, truncated)}
    part_type = str(data.get("type") or "unknown")
    if part_type in {"reasoning", "step-start", "step-finish", "snapshot"}:
        return None
    if part_type == "text":
        return {
            "type": "text",
            "text": _bounded_opencode_text(data.get("text", ""), max_chars, truncated),
            "phase": (data.get("metadata") or {}).get("openai", {}).get("phase") if isinstance(data.get("metadata"), dict) else None,
        }
    if part_type == "tool":
        state = data.get("state") if isinstance(data.get("state"), dict) else {}
        projected = {
            "type": "tool",
            "tool": str(data.get("tool") or "unknown"),
            "status": str(state.get("status") or "unknown"),
            "title": data.get("title"),
            "call_id": data.get("callID") or data.get("callId"),
        }
        if state.get("error"):
            projected["error"] = _bounded_opencode_text(state.get("error"), max_chars, truncated)
        output = state.get("output")
        input_value = state.get("input")
        output_text = _bounded_opencode_text(output, OPENCODE_CHAT_TOOL_OUTPUT_PREVIEW_CHARS, truncated)
        if include_tool_output:
            projected["input"] = _truncate_opencode_value(input_value, max_chars, truncated)
            projected["output"] = _truncate_opencode_value(output, max_chars, truncated)
        elif output_text and (
            projected["status"] == "error"
            or OPENCODE_CHAT_ISSUE_RE.search(output_text)
            or OPENCODE_CHAT_ARTIFACT_RE.search(output_text)
        ):
            projected["output_preview"] = output_text
        return projected
    if part_type in {"file", "image", "attachment"}:
        url = str(data.get("url") or "")
        return {
            "type": part_type,
            "filename": data.get("filename") or data.get("name"),
            "mime": data.get("mime") or data.get("mimeType"),
            "extractable": url.startswith("data:"),
            "content_omitted": True,
        }
    return {
        "type": part_type,
        "status": data.get("status"),
        "text": _bounded_opencode_text(data.get("text", ""), max_chars, truncated) if data.get("text") else None,
    }


def _opencode_model_label(message: dict[str, Any]) -> str:
    model = message.get("model")
    if isinstance(model, dict):
        provider = str(model.get("providerID") or "")
        model_id = str(model.get("modelID") or "")
        variant = str(model.get("variant") or "")
        label = "/".join(item for item in (provider, model_id) if item)
        return f"{label} ({variant})" if label and variant else label
    provider = str(message.get("providerID") or "")
    model_id = str(message.get("modelID") or "")
    return "/".join(item for item in (provider, model_id) if item)


def _sqlite_like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _find_opencode_descendant_sessions(connection: sqlite3.Connection, session_id: str) -> list[str]:
    discovered: list[str] = []
    queue = [session_id]
    while queue:
        parent = queue.pop(0)
        rows = connection.execute(
            """
            SELECT id
            FROM session
            WHERE parent_id = ?
            ORDER BY time_created ASC, id ASC
            """,
            (parent,),
        ).fetchall()
        for row in rows:
            child_id = str(row["id"])
            if child_id in discovered or child_id == session_id:
                continue
            discovered.append(child_id)
            queue.append(child_id)
    return discovered


def _opencode_parent_chain(session_id: str, *, db_path: Path | None = None) -> list[str]:
    """Return immediate-to-root OpenCode parents for a session, best-effort."""
    if not session_id:
        return []
    try:
        connection = _opencode_readonly_connection(db_path)
    except (FileNotFoundError, sqlite3.Error):
        return []
    parents: list[str] = []
    visited = {session_id}
    current = session_id
    try:
        while current:
            row = connection.execute(
                "SELECT parent_id FROM session WHERE id = ?",
                (current,),
            ).fetchone()
            if row is None:
                break
            parent_id = str(row["parent_id"] or "")
            if not parent_id or parent_id in visited:
                break
            parents.append(parent_id)
            visited.add(parent_id)
            current = parent_id
    except sqlite3.Error:
        return parents
    finally:
        connection.close()
    return parents


def _load_opencode_session_rows(
    connection: sqlite3.Connection,
    session_id: str,
    *,
    include_children: bool,
) -> list[sqlite3.Row]:
    root = connection.execute(
        """
        SELECT id, directory, parent_id, title, time_created, time_updated
        FROM session
        WHERE id = ?
        """,
        (session_id,),
    ).fetchone()
    if root is None:
        raise LookupError(f"OpenCode session not found: {session_id}")
    session_ids = [session_id]
    if include_children:
        session_ids.extend(_find_opencode_descendant_sessions(connection, session_id))
    placeholders = ", ".join("?" for _ in session_ids)
    return connection.execute(
        f"""
        SELECT id, directory, parent_id, title, time_created, time_updated
        FROM session
        WHERE id IN ({placeholders})
        ORDER BY COALESCE(parent_id, id) ASC, time_created ASC, id ASC
        """,
        tuple(session_ids),
    ).fetchall()


def _load_opencode_message_rows(
    connection: sqlite3.Connection,
    session_ids: list[str],
    *,
    query: str | None,
    max_messages: int,
) -> tuple[list[sqlite3.Row], bool]:
    placeholders = ", ".join("?" for _ in session_ids)
    parameters: list[Any] = [*session_ids]
    match_sql = ""
    if query:
        pattern = _sqlite_like_pattern(query)
        match_sql = (
            "AND (message.data LIKE ? ESCAPE '\\' "
            "OR EXISTS (SELECT 1 FROM part WHERE part.message_id = message.id AND part.data LIKE ? ESCAPE '\\'))"
        )
        parameters.extend([pattern, pattern])
    parameters.append(max_messages + 1)
    rows = connection.execute(
        f"""
        SELECT id, session_id, time_created, time_updated, data
        FROM (
            SELECT id, session_id, time_created, time_updated, data
            FROM message
            WHERE session_id IN ({placeholders})
            {match_sql}
            ORDER BY time_created DESC, id DESC
            LIMIT ?
        ) AS recent_messages
        ORDER BY time_created ASC, id ASC
        """,
        tuple(parameters),
    ).fetchall()
    truncated = len(rows) > max_messages
    return (rows[-max_messages:] if truncated else rows), truncated


def _load_opencode_part_rows(
    connection: sqlite3.Connection,
    message_id: str,
    *,
    max_parts_per_message: int,
) -> tuple[list[sqlite3.Row], bool]:
    rows = connection.execute(
        """
        SELECT id, message_id, session_id, time_created, time_updated, data
        FROM part
        WHERE message_id = ?
        ORDER BY time_created ASC, id ASC
        LIMIT ?
        """,
        (message_id, max_parts_per_message + 1),
    ).fetchall()
    return rows[:max_parts_per_message], len(rows) > max_parts_per_message


def _matching_repository_sessions(opencode_session_id: str) -> list[dict[str, Any]]:
    try:
        sessions = _load_sessions().get("sessions", {})
    except Exception:
        return []
    matches = []
    for session_id, session in sessions.items():
        if not isinstance(session, dict) or session.get("opencode_session_id") != opencode_session_id:
            continue
        worktree = session.get("worktree") if isinstance(session.get("worktree"), dict) else {}
        modified_files = session.get("modified_files") or []
        matches.append(
            {
                "repository_session_id": session_id,
                "task": session.get("task"),
                "mode": session.get("mode"),
                "tags": session.get("tags") or [],
                "last_active": session.get("last_active"),
                "worktree": {
                    "status": worktree.get("status"),
                    "path": worktree.get("path"),
                    "binding_mode": worktree.get("binding_mode"),
                },
                "modified_file_count": len(modified_files),
                "modified_files": modified_files[:OPENCODE_CHAT_REPOSITORY_FILE_LIMIT],
                "modified_files_truncated": len(modified_files) > OPENCODE_CHAT_REPOSITORY_FILE_LIMIT,
            }
        )
    return matches


def _record_opencode_issue_signal(
    issues: list[dict[str, Any]],
    *,
    max_issues: int,
    kind: str,
    session_id: str,
    message_id: str,
    part_id: str,
    tool: str = "",
    text: str = "",
) -> None:
    if len(issues) >= max_issues:
        return
    issues.append(
        {
            "kind": kind,
            "session_id": session_id,
            "message_id": message_id,
            "part_id": part_id,
            "tool": tool or None,
            "text": textwrap.shorten(" ".join(text.split()), width=300, placeholder="...[truncated]") if text else "",
        }
    )


def read_opencode_chat(
    reference: str,
    *,
    query: str | None = None,
    include_children: bool = True,
    include_tool_output: bool = False,
    signal_mode: str = "actionable",
    max_messages: int = OPENCODE_CHAT_DEFAULT_MAX_MESSAGES,
    max_parts_per_message: int = OPENCODE_CHAT_DEFAULT_MAX_PARTS_PER_MESSAGE,
    max_part_chars: int = OPENCODE_CHAT_DEFAULT_MAX_PART_CHARS,
    max_issues: int = OPENCODE_CHAT_DEFAULT_MAX_ISSUES,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Read a bounded local OpenCode transcript from a session ID or web URL."""
    if min(max_messages, max_parts_per_message, max_part_chars, max_issues) <= 0:
        raise ValueError("OpenCode chat limits must be positive")
    if signal_mode not in OPENCODE_CHAT_SIGNAL_MODES:
        raise ValueError(f"OpenCode chat signal mode must be one of: {', '.join(sorted(OPENCODE_CHAT_SIGNAL_MODES))}")
    parsed = parse_opencode_chat_reference(reference)
    session_id = str(parsed["session_id"])
    truncated = {"messages": False, "parts": False, "fields": False, "issues": False}
    connection = _opencode_readonly_connection(db_path)
    try:
        session_rows = _load_opencode_session_rows(connection, session_id, include_children=include_children)
        sessions = [
            {
                "session_id": str(row["id"]),
                "parent_session_id": str(row["parent_id"]) if row["parent_id"] else None,
                "title": str(row["title"] or ""),
                "directory": str(row["directory"] or ""),
                "time_created": _opencode_timestamp_iso(row["time_created"]),
                "time_updated": _opencode_timestamp_iso(row["time_updated"]),
            }
            for row in session_rows
        ]
        session_ids = [session["session_id"] for session in sessions]
        message_rows, messages_truncated = _load_opencode_message_rows(
            connection,
            session_ids,
            query=query,
            max_messages=max_messages,
        )
        truncated["messages"] = messages_truncated
        messages: list[dict[str, Any]] = []
        issue_signals: list[dict[str, Any]] = []
        suppressed_signal_count = 0
        part_count = 0
        query_folded = query.casefold() if query else None
        for row in message_rows:
            message_data = _decode_opencode_json(row["data"])
            projected_message = _opencode_message_projection(message_data)
            part_rows, parts_truncated = _load_opencode_part_rows(
                connection,
                str(row["id"]),
                max_parts_per_message=max_parts_per_message,
            )
            if parts_truncated:
                truncated["parts"] = True
            parts: list[dict[str, Any]] = []
            message_matches = False
            for part_row in part_rows:
                decoded_part = _decode_opencode_json(part_row["data"])
                raw_part_text = json.dumps(decoded_part, ensure_ascii=False, sort_keys=True) if isinstance(decoded_part, (dict, list)) else str(decoded_part)
                projected_part = _opencode_part_projection(
                    decoded_part,
                    include_tool_output=include_tool_output,
                    max_chars=max_part_chars,
                    truncated=truncated,
                )
                if projected_part is None:
                    continue
                part_matches = bool(query_folded and query_folded in raw_part_text.casefold())
                message_matches = message_matches or part_matches
                if part_matches:
                    projected_part["matched"] = True
                part_type = projected_part.get("type")
                if part_type == "tool":
                    status = str(projected_part.get("status") or "")
                    error_text = str(projected_part.get("error") or "")
                    preview_text = str(projected_part.get("output_preview") or "")
                    if status == "error" or error_text:
                        _record_opencode_issue_signal(
                            issue_signals,
                            max_issues=max_issues,
                            kind="tool_error",
                            session_id=str(row["session_id"]),
                            message_id=str(row["id"]),
                            part_id=str(part_row["id"]),
                            tool=str(projected_part.get("tool") or ""),
                            text=error_text or preview_text,
                        )
                    elif preview_text and OPENCODE_CHAT_ARTIFACT_RE.search(preview_text):
                        _record_opencode_issue_signal(
                            issue_signals,
                            max_issues=max_issues,
                            kind="tool_artifact",
                            session_id=str(row["session_id"]),
                            message_id=str(row["id"]),
                            part_id=str(part_row["id"]),
                            tool=str(projected_part.get("tool") or ""),
                            text=preview_text,
                        )
                    elif preview_text and OPENCODE_CHAT_ISSUE_RE.search(preview_text):
                        if signal_mode != "all":
                            suppressed_signal_count += 1
                        else:
                            _record_opencode_issue_signal(
                                issue_signals,
                                max_issues=max_issues,
                                kind="tool_output_signal",
                                session_id=str(row["session_id"]),
                                message_id=str(row["id"]),
                                part_id=str(part_row["id"]),
                                tool=str(projected_part.get("tool") or ""),
                                text=preview_text,
                            )
                elif part_type == "text":
                    text = str(projected_part.get("text") or "")
                    if OPENCODE_CHAT_ISSUE_RE.search(text):
                        if signal_mode != "all":
                            suppressed_signal_count += 1
                        else:
                            _record_opencode_issue_signal(
                                issue_signals,
                                max_issues=max_issues,
                                kind="text_signal",
                                session_id=str(row["session_id"]),
                                message_id=str(row["id"]),
                                part_id=str(part_row["id"]),
                                text=text,
                            )
                projected_part.update(
                    {
                        "part_id": str(part_row["id"]),
                        "time_created": _opencode_timestamp_iso(part_row["time_created"]),
                    }
                )
                parts.append(projected_part)
            message_raw_text = json.dumps(message_data, ensure_ascii=False, sort_keys=True) if isinstance(message_data, (dict, list)) else str(message_data)
            if query_folded and not (message_matches or query_folded in message_raw_text.casefold()):
                continue
            messages.append(
                {
                    "message_id": str(row["id"]),
                    "session_id": str(row["session_id"]),
                    "time_created": _opencode_timestamp_iso(row["time_created"]),
                    "time_updated": _opencode_timestamp_iso(row["time_updated"]),
                    "role": projected_message.get("role") or "unknown",
                    "agent": projected_message.get("agent"),
                    "mode": projected_message.get("mode"),
                    "model": _opencode_model_label(projected_message),
                    "finish": projected_message.get("finish"),
                    "parts": parts,
                }
            )
            part_count += len(parts)
        if len(issue_signals) >= max_issues:
            truncated["issues"] = True
        return {
            "status": "ok",
            "reference": reference,
            "session_id": session_id,
            "project_directory_from_url": parsed.get("project_directory"),
            "database": str((db_path or OPENCODE_DB_PATH).expanduser()),
            "query": query,
            "resolved_repository_session_id": parsed.get("repository_session_id"),
            "include_children": include_children,
            "include_tool_output": include_tool_output,
            "signal_mode": signal_mode,
            "suppressed_signal_count": suppressed_signal_count,
            "sessions": sessions,
            "repository_sessions": _matching_repository_sessions(session_id),
            "attachments": list_opencode_chat_attachments(
                session_id,
                include_children=include_children,
                db_path=db_path,
            )["attachments"],
            "attachment_extract_command": _opencode_attachment_extract_command(session_id),
            "message_count": len(messages),
            "part_count": part_count,
            "issue_signals": issue_signals,
            "messages": messages,
            "truncated": truncated,
        }
    finally:
        connection.close()


def search_opencode_chat(reference: str, query: str, **kwargs: Any) -> dict[str, Any]:
    """Search a bounded local OpenCode transcript from a session ID or web URL."""
    return read_opencode_chat(reference, query=query, **kwargs)


def _opencode_repository_map() -> dict[str, dict[str, Any]]:
    """Return OpenCode session ID -> durable repository session metadata."""
    try:
        durable_sessions = _load_sessions().get("sessions", {})
    except Exception:
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for repository_session_id, session in durable_sessions.items():
        if not isinstance(session, dict):
            continue
        opencode_session_id = str(session.get("opencode_session_id") or "")
        if not opencode_session_id:
            continue
        mapped[opencode_session_id] = {
            "repository_session_id": repository_session_id,
            "task": session.get("task") or "",
            "mode": session.get("mode") or "",
            "worktree": session.get("worktree") if isinstance(session.get("worktree"), dict) else {},
        }
    return mapped


def _opencode_session_titles(session_ids: list[str], *, db_path: Path | None = None) -> dict[str, str]:
    """Fetch safe OpenCode session titles for a small visible set."""
    wanted = [session_id for session_id in session_ids if session_id]
    if not wanted:
        return {}
    placeholders = ",".join("?" for _ in wanted)
    try:
        connection = _opencode_readonly_connection(db_path)
    except (FileNotFoundError, sqlite3.Error):
        return {}
    try:
        rows = connection.execute(
            f"SELECT id, title FROM session WHERE id IN ({placeholders})",
            wanted,
        ).fetchall()
        return {str(row["id"]): str(row["title"] or "") for row in rows}
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def _opencode_current_activity_label(session_id: str, *, db_path: Path | None = None) -> str:
    """Best-effort current activity label for a visibly busy OpenCode chat."""
    if not session_id:
        return "unavailable"
    try:
        connection = _opencode_readonly_connection(db_path)
    except (FileNotFoundError, sqlite3.Error):
        return "unavailable"
    try:
        rows = connection.execute(
            """
            SELECT data
            FROM part
            WHERE session_id = ?
            ORDER BY time_created DESC, id DESC
            LIMIT 20
            """,
            (session_id,),
        ).fetchall()
    except sqlite3.Error:
        return "unavailable"
    finally:
        connection.close()

    truncated = {"fields": False}
    saw_recent_part = False
    for row in rows:
        part = _opencode_part_projection(
            _decode_opencode_json(row["data"]),
            include_tool_output=False,
            max_chars=160,
            truncated=truncated,
        )
        if not part:
            continue
        saw_recent_part = True
        if part.get("type") == "tool":
            tool = part.get("tool") or "unknown"
            status = part.get("status") or "unknown"
            if status in {"completed", "error"}:
                continue
            title = f" ({part['title']})" if part.get("title") else ""
            return f"tool {tool} {status}{title}"
        if part.get("type") == "text" and part.get("text"):
            return "responding"
    return "responding" if saw_recent_part else "unavailable"


def list_recent_opencode_chats(
    *,
    days: int = 3,
    limit: int = 20,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """List recent top-level OpenCode chats with repository mapping when available."""
    if days <= 0 or limit <= 0:
        raise ValueError("OpenCode recent chat days and limit must be positive")
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    connection = _opencode_readonly_connection(db_path)
    try:
        rows = connection.execute(
            """
            SELECT s.id, s.title, s.directory, s.parent_id, s.time_created, s.time_updated,
                   (SELECT COUNT(*) FROM session c WHERE c.parent_id = s.id) AS child_count
            FROM session s
            WHERE s.parent_id IS NULL AND s.time_updated >= ?
            ORDER BY s.time_updated DESC, s.id DESC
            LIMIT ?
            """,
            (cutoff_ms, limit),
        ).fetchall()
    finally:
        connection.close()

    repository_map = _opencode_repository_map()
    try:
        presence = _opencode_presence_store().snapshot()
    except PresenceStoreError:
        presence = {"sessions": {}}
    presence_sessions = presence.get("sessions", {}) if isinstance(presence, dict) else {}
    chats = []
    for row in rows:
        session_id = str(row["id"])
        mapped = repository_map.get(session_id, {})
        presence_record = presence_sessions.get(session_id, {}) if isinstance(presence_sessions, dict) else {}
        state = ""
        if isinstance(presence_record, dict):
            execution = str(presence_record.get("execution") or "")
            turn = str(presence_record.get("turn") or "")
            state = "/".join(item for item in (execution, turn) if item)
        chats.append(
            {
                "repository_session_id": mapped.get("repository_session_id") or None,
                "opencode_session_id": session_id,
                "title": str(row["title"] or ""),
                "task": mapped.get("task") or "",
                "directory": str(row["directory"] or ""),
                "time_created": _opencode_timestamp_iso(row["time_created"]),
                "time_updated": _opencode_timestamp_iso(row["time_updated"]),
                "child_count": int(row["child_count"] or 0),
                "state": state or "unknown",
                "inspect_command": f"python3 scripts/sessions.py chat read {mapped.get('repository_session_id') or session_id}",
            }
        )
    return {"status": "ok", "days": days, "limit": limit, "database": str((db_path or OPENCODE_DB_PATH).expanduser()), "chats": chats}


def _safe_attachment_filename(value: str, fallback: str, mime: str = "") -> str:
    raw = (value or fallback).strip() or fallback
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-") or fallback
    if "." not in Path(safe).name and mime:
        extension = mimetypes.guess_extension(mime.split(";", 1)[0].strip()) or ""
        if extension:
            safe += extension
    return safe[:120]


def _parse_data_url(value: str) -> tuple[str, bytes]:
    match = re.match(r"^data:(?P<mime>[^;,]+)?(?P<params>(?:;[^,]*)?),(?P<body>.*)$", value, re.DOTALL)
    if not match:
        raise ValueError("attachment is not a data URL")
    mime = match.group("mime") or "application/octet-stream"
    params = match.group("params") or ""
    body = match.group("body") or ""
    if ";base64" in params:
        return mime, base64.b64decode(body, validate=True)
    return mime, urllib.parse.unquote_to_bytes(body)


def _data_url_metadata(value: str) -> tuple[str, int | None]:
    match = re.match(r"^data:(?P<mime>[^;,]+)?(?P<params>(?:;[^,]*)?),(?P<body>.*)$", value, re.DOTALL)
    if not match:
        raise ValueError("attachment is not a data URL")
    mime = match.group("mime") or "application/octet-stream"
    params = match.group("params") or ""
    body = match.group("body") or ""
    if ";base64" in params:
        stripped = re.sub(r"\s+", "", body)
        padding = len(stripped) - len(stripped.rstrip("="))
        return mime, max(0, (len(stripped) * 3) // 4 - padding)
    return mime, None


def _opencode_attachment_default_out_dir(session_id: str) -> Path:
    safe_session = re.sub(r"[^A-Za-z0-9_-]+", "-", session_id).strip("-") or "session"
    return Path("/tmp/opencode") / f"opencode-attachments-{safe_session}"


def _opencode_attachment_extract_command(session_id: str, out_dir: Path | None = None) -> str:
    target = out_dir or _opencode_attachment_default_out_dir(session_id)
    return f"python3 scripts/sessions.py chat attachments {session_id} --out {target}"


def list_opencode_chat_attachments(
    reference: str,
    *,
    include_children: bool = True,
    part_ids: set[str] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Return metadata for file/image parts retained in a local OpenCode chat."""
    parsed = parse_opencode_chat_reference(reference)
    session_id = str(parsed["session_id"])
    connection = _opencode_readonly_connection(db_path)
    try:
        session_rows = _load_opencode_session_rows(connection, session_id, include_children=include_children)
        session_ids = [str(row["id"]) for row in session_rows]
        placeholders = ",".join("?" for _ in session_ids)
        rows = connection.execute(
            f"""
            SELECT
                part.id AS part_id,
                part.message_id AS message_id,
                message.session_id AS session_id,
                part.time_created AS time_created,
                part.data AS data
            FROM part
            JOIN message ON message.id = part.message_id
            WHERE message.session_id IN ({placeholders})
            ORDER BY message.time_created ASC, part.time_created ASC, part.id ASC
            """,
            tuple(session_ids),
        ).fetchall()
        attachments: list[dict[str, Any]] = []
        for row in rows:
            part_id = str(row["part_id"])
            if part_ids and part_id not in part_ids:
                continue
            data = _decode_opencode_json(row["data"])
            if not isinstance(data, dict):
                continue
            part_type = str(data.get("type") or "")
            if part_type not in OPENCODE_CHAT_ATTACHMENT_TYPES:
                continue
            url = str(data.get("url") or "")
            mime = str(data.get("mime") or data.get("mimeType") or "")
            filename = str(data.get("filename") or data.get("name") or "")
            source = "data-url" if url.startswith("data:") else "url" if url else "unknown"
            byte_count = None
            if url.startswith("data:"):
                try:
                    parsed_mime, byte_count = _data_url_metadata(url)
                    mime = mime or parsed_mime
                except ValueError:
                    source = "invalid-data-url"
            attachments.append(
                {
                    "part_id": part_id,
                    "message_id": str(row["message_id"]),
                    "session_id": str(row["session_id"]),
                    "time_created": _opencode_timestamp_iso(row["time_created"]),
                    "type": part_type,
                    "filename": filename or None,
                    "mime": mime or None,
                    "source": source,
                    "extractable": source == "data-url",
                    "byte_count": byte_count,
                }
            )
            if len(attachments) >= OPENCODE_CHAT_ATTACHMENT_LIMIT:
                break
        return {
            "status": "ok",
            "reference": reference,
            "session_id": session_id,
            "database": str((db_path or OPENCODE_DB_PATH).expanduser()),
            "include_children": include_children,
            "attachment_count": len(attachments),
            "extract_command": _opencode_attachment_extract_command(session_id),
            "attachments": attachments,
            "truncated": len(attachments) >= OPENCODE_CHAT_ATTACHMENT_LIMIT,
        }
    finally:
        connection.close()


def extract_opencode_chat_attachments(
    reference: str,
    *,
    out_dir: Path | None = None,
    include_children: bool = True,
    part_ids: set[str] | None = None,
    db_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Decode OpenCode data-URL attachments into ordinary local files."""
    listing = list_opencode_chat_attachments(
        reference,
        include_children=include_children,
        part_ids=part_ids,
        db_path=db_path,
    )
    parsed = parse_opencode_chat_reference(reference)
    session_id = str(parsed["session_id"])
    target_dir = out_dir or _opencode_attachment_default_out_dir(session_id)
    saved: list[dict[str, Any]] = []
    if dry_run:
        return {**listing, "out_dir": str(target_dir), "saved": saved}

    target_dir.mkdir(parents=True, exist_ok=True)
    connection = _opencode_readonly_connection(db_path)
    try:
        for index, item in enumerate(listing["attachments"], start=1):
            if not item.get("extractable"):
                continue
            row = connection.execute("SELECT data FROM part WHERE id = ?", (item["part_id"],)).fetchone()
            if row is None:
                continue
            data = _decode_opencode_json(row["data"])
            if not isinstance(data, dict):
                continue
            mime, payload = _parse_data_url(str(data.get("url") or ""))
            base_name = _safe_attachment_filename(str(item.get("filename") or ""), f"attachment-{index:03d}", mime)
            stem = Path(base_name).stem or f"attachment-{index:03d}"
            suffix = Path(base_name).suffix or (mimetypes.guess_extension(mime) or "")
            file_name = f"{index:03d}-{stem}-{str(item['part_id'])[-8:]}{suffix}"
            path = target_dir / file_name
            path.write_bytes(payload)
            saved_item = {**item, "path": str(path), "byte_count": len(payload), "mime": item.get("mime") or mime}
            saved.append(saved_item)
    finally:
        connection.close()
    return {**listing, "out_dir": str(target_dir), "saved": saved}


def _opencode_attachment_hint_lines(opencode_session_id: str) -> list[str]:
    try:
        listing = list_opencode_chat_attachments(opencode_session_id, include_children=False)
    except (FileNotFoundError, LookupError, ValueError, sqlite3.Error):
        return []
    attachments = listing.get("attachments") or []
    extractable = [item for item in attachments if item.get("extractable")]
    if not extractable:
        return []
    lines = [
        f"This OpenCode chat contains {len(extractable)} extractable uploaded file(s).",
        f"Extract: {_opencode_attachment_extract_command(opencode_session_id)}",
    ]
    for item in extractable[:5]:
        size = f", {item['byte_count']} bytes" if item.get("byte_count") is not None else ""
        lines.append(f"  - {item.get('part_id')}: {item.get('filename') or '(unnamed)'} ({item.get('mime') or 'unknown'}{size})")
    if len(extractable) > 5:
        lines.append(f"  ... +{len(extractable) - 5} more")
    return lines


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
                if SESSIONS_FILE.exists():
                    try:
                        with open(SESSIONS_FILE) as current_file:
                            current = json.load(current_file)
                        for key in ("locks", "infrastructure", "edit_leases", "deploy_queue"):
                            if key in current:
                                data[key] = current[key]
                    except (json.JSONDecodeError, OSError):
                        pass
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
        "infrastructure": {
            "test_leases": {},
            "docker_operations": [],
        },
        "deploy_queue": [],
        "worktree_archive": [],
        "worktree_deletion_manifests": [],
        "sessions": {},
    }


def _infrastructure_state(data: dict) -> dict:
    infrastructure = data.setdefault("infrastructure", {})
    infrastructure.setdefault("test_leases", {})
    infrastructure.setdefault("docker_operations", [])
    return infrastructure


def _persistent_coordination_enabled() -> bool:
    configured = os.getenv("OPENMATES_COORDINATION_BACKEND", "").strip().lower()
    if configured not in {"", "api", "local"}:
        raise RuntimeError("OPENMATES_COORDINATION_BACKEND must be 'api' or 'local'")
    if configured == "local":
        return False
    if configured == "api" and not ENGINEERING_CONTROL_PLANE_ENV_FILE.is_file():
        raise RuntimeError(
            f"Persistent coordination was requested but configuration is missing: {ENGINEERING_CONTROL_PLANE_ENV_FILE}"
        )
    return configured == "api" or ENGINEERING_CONTROL_PLANE_ENV_FILE.is_file()


def _coordination_owner_key(pid: int | None = None) -> str:
    return f"{socket.gethostname()}:{pid if pid is not None else os.getpid()}"


def _legacy_lease_record(lease: dict, *, owner: str = "") -> dict:
    owner_key = str(lease.get("owner_key") or "")
    owner_pid = int(owner_key.rsplit(":", 1)[-1]) if owner_key.rsplit(":", 1)[-1].isdigit() else 0
    return {
        "lease_id": str(lease.get("lease_key") or ""),
        "owner": owner,
        "owner_pid": owner_pid,
        "owner_host": owner_key.rsplit(":", 1)[0] if ":" in owner_key else "",
        "resources": list(lease.get("resources") or []),
        "acquired_at": str(lease.get("acquired_at") or ""),
        "updated_at": str(lease.get("acquired_at") or ""),
        "expires_at": str(lease.get("expires_at") or ""),
        "status": str(lease.get("status") or ""),
    }


def _lease_has_dead_local_owner(lease: dict) -> bool:
    owner_pid = int(lease.get("owner_pid") or 0)
    return bool(
        owner_pid
        and lease.get("owner_host") == socket.gethostname()
        and not _process_is_alive(owner_pid)
    )


def _legacy_operation_record(operation: dict) -> dict:
    metadata = operation.get("metadata") if isinstance(operation.get("metadata"), dict) else {}
    return {
        "id": str(operation.get("operation_key") or ""),
        "session_id": str(metadata.get("session_id") or ""),
        "services": list(metadata.get("services") or []),
        "resources": list(operation.get("resources") or []),
        "status": str(operation.get("status") or ""),
        "requested_at": str(operation.get("requested_at") or ""),
        "updated_at": str(operation.get("completed_at") or operation.get("admitted_at") or operation.get("requested_at") or ""),
        "started_at": str(operation.get("admitted_at") or ""),
        "completed_at": str(operation.get("completed_at") or ""),
        **metadata,
    }


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _prune_stale_test_resource_leases(data: dict) -> list[str]:
    leases = _infrastructure_state(data)["test_leases"]
    removed = []
    now = datetime.now(timezone.utc)
    host = socket.gethostname()
    for lease_id, lease in list(leases.items()):
        try:
            updated_at = _parse_iso(str(lease.get("updated_at") or lease.get("acquired_at") or ""))
        except (TypeError, ValueError):
            updated_at = None
        expired = not updated_at or (now - updated_at).total_seconds() > DOCKER_TEST_LEASE_TTL_SECONDS
        owner_pid = int(lease.get("owner_pid") or 0)
        dead_local_process = bool(
            owner_pid
            and lease.get("owner_host") == host
            and not _process_is_alive(owner_pid)
        )
        if expired or dead_local_process:
            leases.pop(lease_id, None)
            removed.append(lease_id)
    return removed


def _docker_operation_resources(_services: list[str]) -> set[str]:
    return {DOCKER_RESOURCE_DEV_STACK}


def _active_docker_operation(data: dict) -> dict | None:
    operations = _infrastructure_state(data)["docker_operations"]
    return next(
        (
            operation
            for operation in operations
            if operation.get("status") in DOCKER_OPERATION_ACTIVE_STATUSES
        ),
        None,
    )


def _prune_stale_docker_operations(data: dict) -> list[str]:
    operations = _infrastructure_state(data)["docker_operations"]
    now = datetime.now(timezone.utc)
    host = socket.gethostname()
    failed = []
    for operation in operations:
        if operation.get("status") not in DOCKER_OPERATION_ACTIVE_STATUSES:
            continue
        try:
            updated_at = _parse_iso(str(operation.get("updated_at") or operation.get("requested_at") or ""))
        except (TypeError, ValueError):
            updated_at = None
        owner_pid = int(operation.get("owner_pid") or 0)
        process_ended = bool(
            owner_pid
            and operation.get("owner_host") == host
            and not _process_is_alive(owner_pid)
        )
        expired = not updated_at or (now - updated_at).total_seconds() > DOCKER_OPERATION_TTL_SECONDS
        if not process_ended and not expired:
            continue
        operation["status"] = "failed"
        operation["updated_at"] = _now_iso()
        operation["completed_at"] = operation["updated_at"]
        operation["error"] = (
            "Restart owner process ended before completion"
            if process_ended
            else "Restart operation expired"
        )
        failed.append(str(operation.get("id") or "unknown"))
    return failed


def acquire_test_resource_lease(
    lease_id: str,
    owner: str,
    resources: set[str],
    *,
    timeout: int = DOCKER_RESTART_DEFAULT_TIMEOUT_SECONDS,
    poll: int = 5,
    mode: str = "exclusive",
) -> dict:
    """Acquire or renew a test lease after any conflicting operation completes."""
    if not resources:
        return {}
    if mode not in {"shared", "exclusive"}:
        raise ValueError(f"Unknown test resource lease mode: {mode}")
    if _persistent_coordination_enabled():
        deadline = time.time() + max(0, timeout)
        last_report = 0.0
        while True:
            try:
                response = control_plane_api_request(
                    "POST",
                    "/v1/coordination/leases",
                    data={
                        "lease_key": lease_id,
                        "owner_key": _coordination_owner_key(),
                        "resources": sorted(resources),
                        "ttl_seconds": DOCKER_TEST_LEASE_TTL_SECONDS,
                        "mode": mode,
                    },
                )
                return _legacy_lease_record(response["lease"], owner=owner)
            except ControlPlaneApiError as exc:
                conflict = re.search(r"(?:already leased|unavailable): ([A-Za-z0-9_.:-]+)$", exc.detail)
                if exc.status == 409 and conflict:
                    conflicting_lease_id = conflict.group(1)
                    try:
                        response = control_plane_api_request(
                            "GET",
                            f"/v1/coordination/leases/{urllib.parse.quote(conflicting_lease_id, safe='')}",
                        )
                    except ControlPlaneApiError:
                        response = {}
                    conflicting = _legacy_lease_record(response.get("lease") or {})
                    if (
                        conflicting.get("owner_host") == socket.gethostname()
                        and int(conflicting.get("owner_pid") or 0) > 0
                        and not _process_is_alive(int(conflicting["owner_pid"]))
                    ):
                        control_plane_api_request(
                            "DELETE",
                            f"/v1/coordination/leases/{urllib.parse.quote(conflicting_lease_id, safe='')}",
                        )
                        continue
                if exc.status != 409 or time.time() >= deadline:
                    raise RuntimeError(f"Persistent test lease acquisition failed: {exc.detail}") from exc
                now = time.time()
                if last_report == 0.0 or now - last_report >= 60:
                    print(
                        f"Waiting for test resource admission: {exc.detail}",
                        file=sys.stderr,
                        flush=True,
                    )
                    last_report = now
                time.sleep(min(max(1, poll), max(1, int(deadline - time.time()))))
    deadline = time.time() + max(0, timeout)
    poll = max(1, poll)
    while True:
        blocked_by = ""

        def mutate(data: dict) -> dict | None:
            nonlocal blocked_by
            _prune_stale_test_resource_leases(data)
            _prune_stale_docker_operations(data)
            operation = _active_docker_operation(data)
            if operation and resources.intersection(operation.get("resources", [])):
                blocked_by = str(operation.get("id") or "unknown")
                return None
            leases = _infrastructure_state(data)["test_leases"]
            existing = leases.get(lease_id)
            if isinstance(existing, dict):
                if (
                    existing.get("owner") == owner
                    and set(existing.get("resources") or []) == resources
                    and str(existing.get("mode") or "exclusive") == mode
                ):
                    existing["updated_at"] = _now_iso()
                    return dict(existing)
                blocked_by = lease_id
                return None
            for active_lease_id, active_lease in leases.items():
                if not resources.intersection(active_lease.get("resources", [])):
                    continue
                if str(active_lease.get("mode") or "exclusive") == "exclusive" or mode == "exclusive":
                    blocked_by = str(active_lease_id)
                    return None
            now = _now_iso()
            lease = {
                "lease_id": lease_id,
                "owner": owner,
                "owner_pid": os.getpid(),
                "owner_host": socket.gethostname(),
                "resources": sorted(resources),
                "mode": mode,
                "acquired_at": now,
                "updated_at": now,
            }
            leases[lease_id] = lease
            return lease

        lease = _mutate_sessions(mutate)
        if lease:
            return lease
        if time.time() >= deadline:
            raise RuntimeError(
                f"Docker restart {blocked_by} is queued or active for {', '.join(sorted(resources))}"
            )
        time.sleep(min(poll, max(1, int(deadline - time.time()))))




def release_test_resource_lease(lease_id: str) -> bool:
    if _persistent_coordination_enabled():
        response = control_plane_api_request("DELETE", f"/v1/coordination/leases/{lease_id}")
        return bool(response.get("released"))

    def mutate(data: dict) -> bool:
        return _infrastructure_state(data)["test_leases"].pop(lease_id, None) is not None

    return _mutate_sessions(mutate)


def renew_test_resource_lease(
    lease_id: str,
    owner: str,
    resources: set[str],
    *,
    mode: str = "exclusive",
) -> dict:
    """Refresh a lease TTL without changing ownership, resources, or mode."""
    return acquire_test_resource_lease(
        lease_id,
        owner,
        resources,
        timeout=0,
        poll=1,
        mode=mode,
    )


def transfer_test_resource_lease(lease_id: str, *, expected_owner_pid: int, new_owner_pid: int) -> dict:
    """Atomically transfer a local test lease to a spawned child process."""
    host = socket.gethostname()
    if _persistent_coordination_enabled():
        try:
            response = control_plane_api_request(
                "POST",
                f"/v1/coordination/leases/{lease_id}/transfer",
                data={
                    "expected_owner_key": _coordination_owner_key(expected_owner_pid),
                    "new_owner_key": _coordination_owner_key(new_owner_pid),
                },
            )
        except ControlPlaneApiError as exc:
            raise RuntimeError(f"Docker test lease {lease_id} is not owned by the launching process") from exc
        return _legacy_lease_record(response["lease"])

    def mutate(data: dict) -> dict:
        lease = _infrastructure_state(data)["test_leases"].get(lease_id)
        if not isinstance(lease, dict):
            raise RuntimeError(f"Docker test lease {lease_id} no longer exists")
        if lease.get("owner_host") != host or int(lease.get("owner_pid") or 0) != expected_owner_pid:
            raise RuntimeError(f"Docker test lease {lease_id} is not owned by the launching process")
        lease["owner_pid"] = new_owner_pid
        lease["updated_at"] = _now_iso()
        return dict(lease)

    return _mutate_sessions(mutate)


def test_resource_lease_owned_by(lease_id: str, *, owner_pid: int) -> bool:
    """Return whether a local lease is currently owned by the expected process."""
    if _persistent_coordination_enabled():
        response = control_plane_api_request(
            "GET",
            f"/v1/coordination/leases/{lease_id}/owned?{urllib.parse.urlencode({'owner_key': _coordination_owner_key(owner_pid)})}",
        )
        return bool(response.get("owned"))
    data = _load_sessions()
    lease = _infrastructure_state(data)["test_leases"].get(lease_id)
    return bool(
        isinstance(lease, dict)
        and lease.get("owner_host") == socket.gethostname()
        and int(lease.get("owner_pid") or 0) == owner_pid
    )


def request_docker_restart(session_id: str, services: list[str]) -> dict:
    """Atomically queue one restart, preventing new dependent test leases."""
    normalized_services = sorted(set(services))
    resources = sorted(_docker_operation_resources(normalized_services))
    now = _now_iso()
    if _persistent_coordination_enabled():
        operation_id = f"docker-{secrets.token_hex(4)}"
        try:
            response = control_plane_api_request(
                "POST",
                "/v1/coordination/runtime-operations",
                data={
                    "operation_key": operation_id,
                    "operation_type": "product_docker_restart",
                    "resources": resources,
                    "metadata": {
                        "session_id": session_id,
                        "services": normalized_services,
                        "owner_pid": os.getpid(),
                        "owner_host": socket.gethostname(),
                        "waiting_for_tests": [],
                    },
                },
            )
        except ControlPlaneApiError as exc:
            raise RuntimeError(f"Docker restart request conflicted: {exc.detail}") from exc
        return _legacy_operation_record(response["operation"])

    def mutate(data: dict) -> dict:
        _prune_stale_test_resource_leases(data)
        _prune_stale_docker_operations(data)
        operations = _infrastructure_state(data)["docker_operations"]
        for active in operations:
            if active.get("status") not in DOCKER_OPERATION_ACTIVE_STATUSES:
                continue
            if (
                active.get("session_id") == session_id
                and sorted(active.get("services", [])) == normalized_services
                and sorted(active.get("resources", [])) == resources
            ):
                active["updated_at"] = now
                return dict(active)
        operation = {
            "id": f"docker-{secrets.token_hex(4)}",
            "session_id": session_id,
            "services": normalized_services,
            "resources": resources,
            "status": "queued",
            "owner_pid": os.getpid(),
            "owner_host": socket.gethostname(),
            "requested_at": now,
            "updated_at": now,
            "waiting_for_tests": [],
        }
        operations.append(operation)
        del operations[:-DOCKER_OPERATION_HISTORY_LIMIT]
        return dict(operation)

    return _mutate_sessions(mutate)


def update_docker_operation(operation_id: str, status: str, **fields) -> dict:
    if status not in DOCKER_OPERATION_ACTIVE_STATUSES | DOCKER_OPERATION_TERMINAL_STATUSES:
        raise ValueError(f"Unknown Docker operation status: {status}")
    if _persistent_coordination_enabled():
        try:
            response = control_plane_api_request(
                "PATCH",
                f"/v1/coordination/runtime-operations/{operation_id}",
                data={"status": status, "metadata": fields},
            )
        except ControlPlaneApiError as exc:
            raise RuntimeError(f"Docker operation update failed: {exc.detail}") from exc
        return _legacy_operation_record(response["operation"])

    def mutate(data: dict) -> dict:
        operations = _infrastructure_state(data)["docker_operations"]
        operation = next((item for item in operations if item.get("id") == operation_id), None)
        if operation is None:
            raise RuntimeError(f"Docker operation not found: {operation_id}")
        now = _now_iso()
        operation.update(fields)
        operation["status"] = status
        operation["updated_at"] = now
        if status == "restarting" and not operation.get("started_at"):
            operation["started_at"] = now
        if status in DOCKER_OPERATION_TERMINAL_STATUSES:
            operation["completed_at"] = now
        return dict(operation)

    return _mutate_sessions(mutate)


def _list_persistent_docker_operations(*, limit: int = DOCKER_OPERATION_HISTORY_LIMIT) -> list[dict]:
    if not _persistent_coordination_enabled():
        return []
    statuses = sorted(DOCKER_OPERATION_ACTIVE_STATUSES | DOCKER_OPERATION_TERMINAL_STATUSES)
    query = urllib.parse.urlencode(
        [
            ("operation_type", "product_docker_restart"),
            ("limit", str(max(1, min(limit, 100)))),
            *[("status", status) for status in statuses],
        ]
    )
    try:
        response = control_plane_api_request("GET", f"/v1/coordination/runtime-operations?{query}")
    except ControlPlaneApiError:
        return []
    return [_legacy_operation_record(operation) for operation in response.get("operations") or []]


def _active_docker_operation_from_list(docker_operations: list[dict]) -> dict | None:
    active_status_priority = {
        "restarting": 0,
        "verifying": 1,
        "draining_tests": 2,
        "admitted": 3,
        "queued": 4,
    }
    active_candidates = [
        operation
        for operation in docker_operations
        if isinstance(operation, dict) and operation.get("status") in DOCKER_OPERATION_ACTIVE_STATUSES
    ]
    active_candidates.sort(
        key=lambda operation: (
            active_status_priority.get(str(operation.get("status") or ""), 99),
            str(operation.get("requested_at") or ""),
            str(operation.get("id") or ""),
        )
    )
    return next(iter(active_candidates), None)


def _persistent_active_docker_operation() -> dict | None:
    return _active_docker_operation_from_list(_list_persistent_docker_operations(limit=50))



def wait_for_docker_operation_admitted(
    operation_id: str,
    *,
    timeout: int = DOCKER_RESTART_DEFAULT_TIMEOUT_SECONDS,
    poll: int = 5,
) -> dict:
    """Wait for the persistent coordinator to admit a queued restart."""
    if not _persistent_coordination_enabled():
        return {"id": operation_id, "status": "admitted"}
    deadline = time.time() + max(0, timeout)
    poll = max(1, poll)
    last_report = 0.0
    while True:
        operation = update_docker_operation(operation_id, "queued")
        status = str(operation.get("status") or "")
        if status == "admitted":
            return operation
        if status in DOCKER_OPERATION_TERMINAL_STATUSES:
            raise RuntimeError(f"Docker operation {operation_id} ended before admission: {status}")
        if status != "queued":
            return operation
        now = time.time()
        if now >= deadline:
            raise RuntimeError(f"Timed out after {timeout}s waiting for Docker operation admission: {operation_id}")
        if last_report == 0.0 or now - last_report >= 30:
            blockers = _runtime_operation_blockers(operation_id)
            failed_operations = _fail_dead_local_persistent_operation_blockers(blockers["operations"])
            if failed_operations:
                last_report = 0.0
                continue
            update_docker_operation(
                operation_id,
                "queued",
                waiting_for_tests=[str(item.get("lease_id") or "unknown") for item in blockers["leases"]],
                waiting_for_operations=[str(item.get("id") or "unknown") for item in blockers["operations"]],
            )
            lease_ids = [str(item.get("lease_id") or "unknown") for item in blockers["leases"]]
            operation_labels = [
                "/".join(
                    filter(
                        None,
                        [
                            str(item.get("id") or "unknown"),
                            str(item.get("session_id") or ""),
                            str(item.get("status") or ""),
                        ],
                    )
                )
                for item in blockers["operations"]
            ]
            reasons = []
            if lease_ids:
                reasons.append(f"leases={','.join(lease_ids)}")
            if operation_labels:
                reasons.append(f"operations={','.join(operation_labels)}")
            detail = "; ".join(reasons) if reasons else "no blocker after reconciliation; retrying admission"
            print(f"Waiting for Docker operation admission: {operation_id} ({detail})", flush=True)
            last_report = now
        time.sleep(min(poll, max(1, int(deadline - now))))


def _fail_dead_local_persistent_operation_blockers(operations: list[dict]) -> list[str]:
    """Fail active same-host blockers after their owning process has exited."""
    host = socket.gethostname()
    failed: list[str] = []
    for operation in operations:
        operation_id = str(operation.get("id") or "")
        owner_pid = int(operation.get("owner_pid") or 0)
        if (
            not operation_id
            or operation.get("status") not in DOCKER_OPERATION_ACTIVE_STATUSES
            or operation.get("owner_host") != host
            or not owner_pid
            or _process_is_alive(owner_pid)
        ):
            continue
        update_docker_operation(
            operation_id,
            "failed",
            failure_class="owner-exited",
            error="Restart owner process ended before completion",
        )
        failed.append(operation_id)
    return failed


def _runtime_operation_blockers(operation_id: str) -> dict[str, list[dict]]:
    """Return current lease and operation blockers after safe reconciliation."""
    if _persistent_coordination_enabled():
        response = control_plane_api_request(
            "GET",
            f"/v1/coordination/runtime-operations/{operation_id}/blocking-leases",
        )
        leases = [_legacy_lease_record(lease) for lease in response.get("leases") or []]
        operations = [_legacy_operation_record(operation) for operation in response.get("operations") or []]
        released = []
        for lease in leases:
            if not _lease_has_dead_local_owner(lease):
                continue
            control_plane_api_request("DELETE", f"/v1/coordination/leases/{lease['lease_id']}")
            released.append(lease["lease_id"])
        if released:
            response = control_plane_api_request(
                "GET",
                f"/v1/coordination/runtime-operations/{operation_id}/blocking-leases",
            )
            leases = [_legacy_lease_record(lease) for lease in response.get("leases") or []]
            operations = [_legacy_operation_record(operation) for operation in response.get("operations") or []]
        return {"leases": leases, "operations": operations}

    def mutate(data: dict) -> dict[str, list[dict]]:
        _prune_stale_test_resource_leases(data)
        operations = _infrastructure_state(data)["docker_operations"]
        operation = next((item for item in operations if item.get("id") == operation_id), None)
        if operation is None:
            raise RuntimeError(f"Docker operation not found: {operation_id}")
        resources = set(operation.get("resources", []))
        leases = [
            dict(lease)
            for lease in _infrastructure_state(data)["test_leases"].values()
            if resources.intersection(lease.get("resources", []))
        ]
        operation["waiting_for_tests"] = sorted(str(lease.get("lease_id")) for lease in leases)
        operation["updated_at"] = _now_iso()
        blockers = [
            dict(item)
            for item in operations
            if item is not operation
            and item.get("status") in DOCKER_OPERATION_ACTIVE_STATUSES
            and resources.intersection(item.get("resources", []))
        ]
        return {"leases": leases, "operations": blockers}

    return _mutate_sessions(mutate)


def _blocking_test_resource_leases(operation_id: str) -> list[dict]:
    return _runtime_operation_blockers(operation_id)["leases"]


def wait_for_docker_test_leases(
    operation_id: str,
    *,
    timeout: int = DOCKER_RESTART_DEFAULT_TIMEOUT_SECONDS,
    poll: int = 5,
    heartbeat=None,
) -> list[dict]:
    deadline = time.time() + max(0, timeout)
    poll = max(1, poll)
    update_docker_operation(operation_id, "draining_tests")
    while True:
        leases = _blocking_test_resource_leases(operation_id)
        if not leases:
            return []
        if heartbeat:
            heartbeat()
        if time.time() >= deadline:
            lease_ids = ", ".join(str(lease.get("lease_id")) for lease in leases)
            raise RuntimeError(f"Timed out waiting for dependent tests: {lease_ids}")
        time.sleep(min(poll, max(1, int(deadline - time.time()))))


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


def link_shared_worktree_resources(worktree_path: str | Path) -> list[str]:
    """Link ignored runtime inputs to their canonical control-plane copies."""
    worktree = Path(worktree_path).resolve()
    available: list[tuple[Path, Path, Path]] = []
    for relative_path in WORKTREE_SHARED_RUNTIME_PATHS:
        source = CONTROL_PLANE_ROOT / relative_path
        target = worktree / relative_path
        if target.is_symlink():
            if target.resolve(strict=False) != source.resolve():
                raise RuntimeError(f"Refusing to replace existing worktree runtime resource: {relative_path}")
        elif target.exists():
            raise RuntimeError(f"Refusing to replace existing worktree runtime resource: {relative_path}")
        available.append((relative_path, source, target))

    for _relative_path, source, target in available:
        if not target.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=source.is_dir())
    return [relative_path.as_posix() for relative_path, _source, _target in available]


def validate_worktree_binding_mode(session: dict) -> str:
    """Validate and return one mutually exclusive worktree binding mode."""
    mode = str(session.get("binding_mode") or "legacy_grandfathered")
    if mode not in WORKTREE_BINDING_MODES:
        raise ValueError(f"Invalid worktree binding mode: {mode}")
    return mode


def bootstrap_session_worktree(worktree_path: str | Path) -> dict:
    """Install cached dependencies and generate prerequisites in one worktree."""
    worktree = Path(worktree_path).resolve()
    linked_resources = link_shared_worktree_resources(worktree)
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
        "shared_runtime_resources": linked_resources,
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
            worktree_path = Path(str(metadata["path"]))
            if not _existing_direct_managed_worktree(worktree_path):
                raise RuntimeError(f"Session {session_id} has an invalid or missing managed worktree: {worktree_path}")
            if metadata.get("status") == "merged":
                metadata["status"] = "active"
            metadata["last_active"] = _now_iso()
            session["last_active"] = _now_iso()
            return dict(metadata)
        return None

    current = _mutate_sessions(existing)
    if current:
        current["shared_runtime_resources"] = link_shared_worktree_resources(current["path"])
        return current

    _enforce_worktree_creation_capacity()
    session_data = _load_sessions().get("sessions", {}).get(session_id, {})
    base_commit = (
        _fetch_origin_dev_commit()
        if _session_is_control_plane_repo(session_data)
        else _current_git_sha(_session_checkout_root(session_data))
    )
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


def _worktree_new_files(metadata: dict, files: set[str]) -> set[str]:
    """Return selected source files that do not exist in the recorded base."""
    worktree_path = metadata.get("path")
    base_commit = metadata.get("merged_commit") or metadata.get("base_commit") or ""
    if not worktree_path or not base_commit:
        return set()
    worktree_root = Path(str(worktree_path))
    new_files: set[str] = set()
    for relative_path in files:
        source = worktree_root / relative_path
        if not source.exists():
            continue
        rc, _stdout, _stderr = _run_cmd(
            ["git", "cat-file", "-e", f"{base_commit}:{relative_path}"],
            cwd=str(worktree_root),
        )
        if rc != 0:
            new_files.add(relative_path)
    return new_files


def _worktree_has_changes(metadata: dict) -> bool:
    return bool(_worktree_changed_files(metadata))


def _normalize_root_handoff_path(path_value: str | Path) -> str:
    """Return one safe repository-relative path for explicit root handoff."""
    raw = str(path_value or "").replace("\\", "/")
    candidate = Path(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe root handoff path: {path_value}")
    normalized = _canonical_stored_repo_path(raw).removeprefix("./")
    if not normalized or normalized == "." or normalized.startswith("/"):
        raise ValueError(f"Unsafe root handoff path: {path_value}")
    if is_protected_control_plane_path(normalized):
        raise ValueError(f"Protected control-plane path cannot be imported: {normalized}")
    if normalized in WORKTREE_ROOT_HANDOFF_DENIED_PATHS:
        raise ValueError(f"Sensitive runtime path cannot be imported: {normalized}")
    if any(normalized.startswith(prefix) for prefix in WORKTREE_ROOT_HANDOFF_DENIED_PREFIXES):
        raise ValueError(f"Shared runtime path cannot be imported: {normalized}")
    if any(normalized.startswith(prefix) for prefix in WORKTREE_NON_DEPLOYABLE_RUNTIME_PREFIXES):
        raise ValueError(f"Non-deployable runtime path cannot be imported: {normalized}")
    name = Path(normalized).name.lower()
    if name == ".env" or name.startswith(".env.") or name.endswith(WORKTREE_AUTO_INTEGRATION_SENSITIVE_SUFFIXES):
        raise ValueError(f"Sensitive file cannot be imported: {normalized}")
    resolved = (CONTROL_PLANE_ROOT / normalized).resolve(strict=False)
    try:
        resolved.relative_to(CONTROL_PLANE_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"Root handoff path escapes the repository: {normalized}") from exc
    return normalized


def list_root_dirty_files(*, path_prefix: str = "") -> dict:
    """List safe dirty root paths without exposing file contents."""
    prefix = path_prefix.replace("\\", "/").removeprefix("./")
    if prefix:
        prefix_path = Path(prefix)
        if prefix_path.is_absolute() or ".." in prefix_path.parts:
            raise ValueError(f"Unsafe root dirty prefix: {path_prefix}")
        prefix = prefix.rstrip("/") + "/"

    dirty = _get_dirty_files(checkout_root=CONTROL_PLANE_ROOT)
    staged = _get_staged_files(checkout_root=CONTROL_PLANE_ROOT)
    rc, stdout, stderr = _run_cmd(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=str(CONTROL_PLANE_ROOT)
    )
    if rc != 0:
        raise RuntimeError(f"Failed to inspect root untracked files: {stderr}")
    untracked = {line.strip() for line in stdout.splitlines() if line.strip()}
    rc, stdout, stderr = _run_cmd(
        ["git", "diff", "--name-only", "origin/dev", "--"], cwd=str(CONTROL_PLANE_ROOT)
    )
    if rc != 0:
        raise RuntimeError(f"Failed to compare root files with origin/dev: {stderr}")
    differs_from_origin = {line.strip() for line in stdout.splitlines() if line.strip()} | untracked

    files: list[dict] = []
    omitted = 0
    for raw_path in sorted(dirty):
        if prefix and not (raw_path + "/").startswith(prefix):
            continue
        try:
            relative_path = _normalize_root_handoff_path(raw_path)
        except ValueError:
            omitted += 1
            continue
        root_path = CONTROL_PLANE_ROOT / relative_path
        if root_path.is_symlink() or (root_path.exists() and not root_path.is_file()):
            omitted += 1
            continue
        files.append({
            "path": relative_path,
            "state": "deleted" if not root_path.exists() else "untracked" if relative_path in untracked else "modified",
            "staged": relative_path in staged,
            "differs_from_origin": relative_path in differs_from_origin,
        })
    rc, origin_dev, stderr = _run_cmd(["git", "rev-parse", "origin/dev"], cwd=str(CONTROL_PLANE_ROOT))
    if rc != 0:
        raise RuntimeError(f"Failed to resolve origin/dev: {stderr}")
    return {
        "root": str(CONTROL_PLANE_ROOT),
        "origin_dev": origin_dev.strip(),
        "files": files,
        "omitted_unsafe_count": omitted,
    }


def import_root_dirty_file(
    path_value: str | Path,
    *,
    session_id: str = "",
    opencode_session_id: str = "",
) -> dict:
    """Copy one explicitly selected dirty root file into a clean session path."""
    relative_path = _normalize_root_handoff_path(path_value)
    data = _load_sessions()
    resolved_session_id = _resolve_session_id(
        data, session_id=session_id, opencode_session_id=opencode_session_id
    )
    session = data["sessions"][resolved_session_id]
    if not _session_is_control_plane_repo(session):
        raise RuntimeError("Root handoff is only available for the OpenMates control-plane repository")
    metadata = session.get("worktree")
    if not isinstance(metadata, dict) or not metadata.get("path"):
        raise RuntimeError(f"Session {resolved_session_id} has no managed worktree")
    worktree_root = Path(str(metadata["path"])).resolve()
    if not is_valid_managed_worktree_path(worktree_root) or not _existing_direct_managed_worktree(worktree_root):
        raise RuntimeError(f"Session {resolved_session_id} has an invalid managed worktree")
    if relative_path not in _get_dirty_files(checkout_root=CONTROL_PLANE_ROOT):
        raise RuntimeError(f"Root path is not currently dirty: {relative_path}")
    if relative_path in _get_dirty_files(checkout_root=worktree_root):
        raise RuntimeError(f"Session path already has local changes: {relative_path}")

    source = CONTROL_PLANE_ROOT / relative_path
    destination = worktree_root / relative_path
    try:
        destination.resolve(strict=False).relative_to(worktree_root)
    except ValueError as exc:
        raise RuntimeError(f"Session destination escapes through a symlink: {relative_path}") from exc
    if source.is_symlink() or (source.exists() and not source.is_file()):
        raise RuntimeError(f"Unsupported root handoff source: {relative_path}")
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise RuntimeError(f"Unsupported session handoff destination: {relative_path}")

    source_state = "deleted"
    source_sha256 = ""
    if source.exists():
        source_state = "file"
        source_sha256 = _file_sha256(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".root-import-", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copy2(source, temporary)
            if _file_sha256(source) != source_sha256:
                raise RuntimeError(f"Root path changed during import: {relative_path}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    elif destination.exists():
        destination.unlink()

    imported_at = _now_iso()

    def record(current: dict) -> None:
        current_session = current.get("sessions", {}).get(resolved_session_id)
        if not isinstance(current_session, dict):
            raise RuntimeError(f"Session {resolved_session_id} disappeared during root import")
        if relative_path not in current_session.setdefault("modified_files", []):
            current_session["modified_files"].append(relative_path)
        current_session["workspace_state"] = "changes_pending"
        current_session["last_active"] = imported_at
        current_worktree = current_session.get("worktree")
        if not isinstance(current_worktree, dict):
            raise RuntimeError(f"Session {resolved_session_id} worktree disappeared during root import")
        imports = current_worktree.setdefault("root_imports", [])
        imports.append({
            "path": relative_path,
            "state": source_state,
            "sha256": source_sha256,
            "root_head": _current_git_sha(CONTROL_PLANE_ROOT),
            "imported_at": imported_at,
        })
        del imports[:-50]
        current_worktree["last_active"] = imported_at

    _mutate_sessions(record)
    return {
        "session_id": resolved_session_id,
        "path": relative_path,
        "state": source_state,
        "sha256": source_sha256,
        "worktree_path": str(worktree_root),
    }


def _worktree_head(path: str | Path) -> str:
    rc, stdout, stderr = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(path))
    if rc != 0:
        raise RuntimeError(f"Failed to inspect worktree HEAD: {stderr}")
    return stdout.strip()


def _worktree_branch(path: str | Path) -> str:
    rc, stdout, stderr = _run_cmd(["git", "branch", "--show-current"], cwd=str(path))
    if rc != 0:
        raise RuntimeError(f"Failed to inspect worktree branch: {stderr}")
    return stdout.strip()


def _session_worktree_warnings(session_id: str, session: dict) -> list[str]:
    """Return actionable warnings when session metadata and git state diverge."""
    metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None
    if not isinstance(metadata, dict) or not metadata.get("path"):
        return []
    worktree_path = Path(str(metadata["path"]))
    if not worktree_path.exists():
        return [f"session {session_id} worktree path is missing: {worktree_path}"]
    warnings: list[str] = []
    try:
        head = _worktree_head(worktree_path)
        branch = _worktree_branch(worktree_path)
    except RuntimeError as exc:
        return [str(exc)]
    status = str(metadata.get("status") or "")
    merged_commit = str(metadata.get("merged_commit") or "")
    if status == "merged":
        if merged_commit and head != merged_commit:
            warnings.append(
                f"session {session_id} is marked merged at {merged_commit[:9]} but worktree HEAD is {head[:9]}"
            )
        if not branch:
            warnings.append(
                f"session {session_id} worktree is detached after merge; start a new worktree before follow-up edits or evidence"
            )
        pending_files = _worktree_changed_files(metadata)
        if pending_files:
            warnings.append(
                f"session {session_id} merged worktree still has {len(pending_files)} changed file(s); do not bind new evidence to this checkout"
            )
    elif status == "active" and not branch:
        warnings.append(f"session {session_id} active worktree is detached at {head[:9]}")
    return warnings


def _is_deployable_worktree_path(relative_path: str) -> bool:
    return not any(relative_path.startswith(prefix) for prefix in WORKTREE_NON_DEPLOYABLE_RUNTIME_PREFIXES)


def _session_deploy_files(session: dict, exclude: set[str]) -> list[str]:
    """Return the deploy file set, preferring the isolated worktree diff."""
    if not _session_is_control_plane_repo(session):
        dirty_files = _get_dirty_files(checkout_root=_session_checkout_root(session))
        tracked = {_canonical_stored_repo_path(path) for path in session.get("modified_files") or []}
        return sorted(f for f in tracked if f in dirty_files and f not in exclude and _is_deployable_worktree_path(f))

    metadata = session.get("worktree")
    if isinstance(metadata, dict) and metadata.get("path"):
        changed = set(_worktree_changed_files(metadata))
        tracked = {_canonical_stored_repo_path(path) for path in session.get("modified_files") or []}
        if metadata.get("merged_commit"):
            changed.update(tracked)
        changed = {relative_path for relative_path in changed if _is_deployable_worktree_path(relative_path)}
        deployed_states = metadata.get("root_applied_files")
        if metadata.get("merged_commit"):
            current_states = _snapshot_file_states(Path(metadata["path"]), sorted(changed))
            baseline_states = _snapshot_worktree_base_states(metadata, sorted(changed))
            changed = {
                relative_path
                for relative_path in changed
                if current_states.get(relative_path) != baseline_states.get(relative_path)
            }
        elif isinstance(deployed_states, dict):
            current_states = _snapshot_file_states(Path(metadata["path"]), sorted(changed))
            baseline_states = dict(deployed_states)
            changed = {
                relative_path
                for relative_path in changed
                if current_states.get(relative_path) != baseline_states.get(relative_path)
            }
        if tracked:
            changed &= tracked
        if changed:
            target_ref = f"{_session_repo_remote(session)}/{_session_repo_branch(session)}"
            try:
                current_states = _snapshot_file_states(Path(metadata["path"]), sorted(changed))
                target_states = _snapshot_worktree_base_states(
                    {"path": metadata["path"], "merged_commit": target_ref},
                    sorted(changed),
                )
                changed = {
                    relative_path
                    for relative_path in changed
                    if current_states.get(relative_path) != target_states.get(relative_path)
                }
            except RuntimeError:
                # A missing/stale remote-tracking ref must not hide real work.
                pass
        return sorted(f for f in changed if f not in exclude)
    dirty_files = _get_dirty_files(checkout_root=_session_checkout_root(session))
    return sorted(
        f for f in session.get("modified_files", [])
        if f in dirty_files and f not in exclude and _is_deployable_worktree_path(f)
    )


def is_protected_control_plane_path(path: str) -> bool:
    """Return whether a repository path belongs to the shared coding traffic controller."""
    normalized = _canonical_stored_repo_path(str(path or "").replace("\\", "/")).removeprefix("./")
    if normalized in PROTECTED_CONTROL_PLANE_EXACT_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in PROTECTED_CONTROL_PLANE_PREFIXES)


def _current_runtime_allows_control_plane_deploy(session: dict | None) -> bool:
    return (
        isinstance(session, dict)
        and bool(os.environ.get("CODEX_SESSION_ID"))
        and not os.environ.get("OPENCODE_SESSION_ID")
    )


def validate_product_session_deploy_paths(paths: list[str], session: dict | None = None) -> None:
    """Reject control-plane changes from the product-session deployment lane."""
    protected = sorted({path for path in paths if is_protected_control_plane_path(path)})
    if not protected:
        return
    if _current_runtime_allows_control_plane_deploy(session):
        return
    rendered = ", ".join(protected)
    raise RuntimeError(
        "CONTROL-PLANE DEPLOY BLOCKED — ordinary OpenCode product sessions cannot deploy "
        f"shared orchestration files: {rendered}. Preserve the worktree and move these changes "
        "to the dedicated Codex control-plane recovery branch for review."
    )


def _resolve_deploy_selection(
    session: dict,
    *,
    exclude: set[str],
    use_staged: bool = False,
    only: list[str] | None = None,
) -> tuple[list[str], str]:
    """Resolve one authoritative deploy file selector.

    Historical ``modified_files`` entries remain advisory. An explicit staged
    or path selector must never be widened with other dirty files from the same
    long-running session.
    """
    requested_only = {
        _canonical_stored_repo_path(path)
        for path in (only or [])
        if _canonical_stored_repo_path(path) not in exclude
    }
    if use_staged and requested_only:
        raise RuntimeError("--use-staged and --only are mutually exclusive deploy selectors")

    default_files = set(_session_deploy_files(session, exclude))
    if requested_only:
        unavailable = sorted(requested_only - default_files)
        if unavailable:
            raise RuntimeError(
                "--only contains files that are not tracked dirty work for this session: "
                + ", ".join(unavailable)
            )
        return sorted(requested_only), "only"

    if use_staged:
        checkout_root = _session_checkout_root(session)
        staged_files = (
            _get_staged_files()
            if checkout_root == CONTROL_PLANE_ROOT
            else _get_staged_files(checkout_root=checkout_root)
        )
        staged = {
            _canonical_stored_repo_path(path)
            for path in staged_files
            if _canonical_stored_repo_path(path) not in exclude
        }
        tracked = {
            _canonical_stored_repo_path(path)
            for path in session.get("modified_files") or []
        }
        foreign = sorted(staged - tracked)
        if foreign:
            raise RuntimeError(
                "--use-staged found staged files outside this session: " + ", ".join(foreign)
            )
        return sorted(staged), "staged"

    return sorted(default_files), "tracked_dirty"


def _build_deploy_manifest(
    session_id: str,
    session: dict,
    files: list[str],
    *,
    selector: str,
) -> dict:
    """Build a deterministic identity for one resolved source patch."""
    metadata = (
        session.get("worktree")
        if _session_is_control_plane_repo(session) and isinstance(session.get("worktree"), dict)
        else None
    )
    patch_id = _worktree_patch_id(metadata, files) if metadata and files else ""
    payload = {
        "session_id": session_id,
        "repository": _session_repo_id(session),
        "target_branch": _session_repo_branch(session),
        "source_base": str((metadata or {}).get("base_commit") or ""),
        "selector": selector,
        "selected_files": sorted(files),
        "generated_files": [],
        "patch_id": patch_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**payload, "manifest_id": hashlib.sha256(encoded).hexdigest()}


def _file_sha256(path: Path) -> str:
    """Return one content identity without exposing file contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepared_dependency_identity(root: Path) -> str:
    """Return the exact dependency lock identity for a prepared checkout."""
    lockfile = root / "pnpm-lock.yaml"
    if not lockfile.is_file():
        raise RuntimeError(f"Prepared dependency root has no pnpm-lock.yaml: {root}")
    return _file_sha256(lockfile)


def _link_prepared_dependencies(
    checkout_root: Path,
    dependency_root: Path,
    relative_paths: list[str],
) -> str:
    """Link immutable, lockfile-compatible dependency trees into one checkout."""
    checkout_identity = _prepared_dependency_identity(checkout_root)
    prepared_identity = _prepared_dependency_identity(dependency_root)
    if checkout_identity != prepared_identity:
        raise RuntimeError(
            "Prepared dependencies are stale for this patch base: lockfile identity mismatch"
        )
    for relative in relative_paths:
        source = dependency_root / relative
        target = checkout_root / relative
        if not source.is_dir():
            raise RuntimeError(f"Prepared dependency path is unavailable: {relative}")
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"Validation checkout unexpectedly contains dependency state: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=True)
    return prepared_identity


def _installed_cli_identity(candidate_root: Path, executable: str = "") -> dict:
    """Inspect the installed CLI and candidate package without changing either."""
    requested = executable or os.environ.get("OPENMATES_CLI", "") or shutil.which("openmates") or ""
    if not requested:
        raise RuntimeError("The openmates executable is not installed or on PATH")
    executable_path = Path(requested).expanduser()
    if not executable_path.is_absolute():
        resolved_command = shutil.which(str(executable_path))
        if not resolved_command:
            raise RuntimeError(f"Could not resolve installed CLI executable: {requested}")
        executable_path = Path(resolved_command)
    executable_path = executable_path.absolute()
    resolved_path = executable_path.resolve(strict=True)
    installed_package_root = resolved_path.parent.parent
    installed_package_json = installed_package_root / "package.json"
    installed_metadata = json.loads(installed_package_json.read_text()) if installed_package_json.is_file() else {}

    candidate_package_root = candidate_root / "frontend" / "packages" / "openmates-cli"
    candidate_package_json = candidate_package_root / "package.json"
    if not candidate_package_json.is_file():
        raise RuntimeError("Candidate CLI package.json is unavailable")
    candidate_metadata = json.loads(candidate_package_json.read_text())
    candidate_dist = candidate_package_root / "dist" / "cli.js"
    installed_hash = _file_sha256(resolved_path)
    candidate_hash = _file_sha256(candidate_dist) if candidate_dist.is_file() else ""
    return {
        "executable_path": str(executable_path),
        "resolved_path": str(resolved_path),
        "installed_package_root": str(installed_package_root),
        "installed_version": str(installed_metadata.get("version") or ""),
        "installed_executable_sha256": installed_hash,
        "candidate_package_root": str(candidate_package_root),
        "candidate_version": str(candidate_metadata.get("version") or ""),
        "candidate_executable_sha256": candidate_hash,
        "contains_candidate_source": bool(candidate_hash and candidate_hash == installed_hash),
        "inspection_mutated_install": False,
    }



def _relative_repo_path_for_session(path_value: str | Path, session: dict | None = None) -> str:
    """Normalize a root or worktree path to a repository-relative file path."""
    stored_path = _canonical_stored_repo_path(path_value)
    if stored_path != str(path_value):
        return stored_path
    candidate = Path(stored_path)
    if not candidate.is_absolute():
        return stored_path
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
    repo_root = None
    if isinstance(session, dict):
        try:
            repo_root = _session_checkout_root(session)
        except ValueError:
            repo_root = None
    if repo_root:
        try:
            return resolved.relative_to(repo_root).as_posix()
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
        new_files = (
            _worktree_new_files(metadata, selected_files) | untracked_files
        ) & selected_files
        tracked_files = sorted(selected_files - new_files)
    else:
        new_files = untracked_files
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
    for relative_path in sorted(new_files):
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
        mode = subprocess.run(
            ["git", "ls-tree", reference_commit, "--", f":(literal){relative_path}"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if mode.returncode != 0:
            raise RuntimeError(f"Could not inspect base file mode: {relative_path}")
        if not mode.stdout.strip():
            states[relative_path] = {"exists": False}
            continue
        content = subprocess.run(
            ["git", "show", f"{reference_commit}:{relative_path}"],
            cwd=str(worktree_path),
            capture_output=True,
            timeout=30,
        )
        if content.returncode != 0:
            raise RuntimeError(f"Could not inspect base file content: {relative_path}")
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
    current_session = _load_sessions().get("sessions", {}).get(session_id, {})
    current_metadata = current_session.get("worktree") if isinstance(current_session, dict) else None
    source_head_matches_deployed_commit = False
    source_matches_deployed_commit = False
    if isinstance(current_metadata, dict) and current_metadata.get("path"):
        try:
            source_head_matches_deployed_commit = _worktree_head(current_metadata["path"]) == commit_hash
            source_matches_deployed_commit = (
                source_head_matches_deployed_commit
                and not _worktree_changed_files({**current_metadata, "base_commit": commit_hash})
            )
        except (OSError, RuntimeError):
            source_matches_deployed_commit = False
    # Synchronisation rebases any work created after the immutable deployment
    # checkpoint onto commit_hash.  A clean source at that exact commit is the
    # only state that may truthfully be called merged.  A patch fingerprint
    # cannot be compared here: after a successful deploy the selected patch is
    # part of HEAD and therefore correctly disappears from the working diff.
    merged_state_is_truthful = source_matches_deployed_commit

    def mark(data: dict) -> None:
        metadata = data.get("sessions", {}).get(session_id, {}).get("worktree")
        if isinstance(metadata, dict):
            metadata["status"] = "merged" if merged_state_is_truthful else "changes_pending"
            metadata["merged_commit"] = commit_hash
            if source_head_matches_deployed_commit:
                metadata["base_commit"] = commit_hash
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
            session = data.get("sessions", {}).get(session_id)
            if isinstance(session, dict):
                session["workspace_state"] = "integrated" if merged_state_is_truthful else "changes_pending"
                auto = session.get("auto_integration")
                if isinstance(auto, dict):
                    auto["status"] = "integrated" if merged_state_is_truthful else "changes_pending"
                    auto["updated_at"] = _now_iso()
        if patch_id:
            data["deploy_queue"] = [
                item
                for item in data.setdefault("deploy_queue", [])
                if item.get("session_id") != session_id
            ]

    _mutate_sessions(mark)
    if merged_state_is_truthful:
        with _worktree_checkpoint_lock(session_id):
            latest_session = _load_sessions().get("sessions", {}).get(session_id, {})
            latest_auto = latest_session.get("auto_integration") if isinstance(latest_session.get("auto_integration"), dict) else {}
            if latest_auto.get("patch_id") == patch_id and latest_auto.get("status") == "integrated":
                _delete_worktree_checkpoint_ref(
                    session_id,
                    expected_commit=str(latest_auto.get("checkpoint_commit") or ""),
                )


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


def _split_specification_generated_artifacts(files: list[str]) -> tuple[list[str], list[str]]:
    """Separate deterministic Specification outputs from source patches."""
    generated = [relative_path for relative_path in files if relative_path in SPECIFICATION_GENERATED_ARTIFACTS]
    source = [relative_path for relative_path in files if relative_path not in SPECIFICATION_GENERATED_ARTIFACTS]
    return source, generated


def _numstat_deletions(
    checkout_root: Path,
    base_ref: str,
    files: list[str],
    *,
    cached: bool = False,
) -> dict[str, int | None]:
    """Return per-file text deletions, using None for binary changes."""
    command = ["git", "diff", "--numstat"]
    if cached:
        command.append("--cached")
    command.extend([base_ref, "--", *files])
    rc, stdout, stderr = _run_cmd(command, cwd=str(checkout_root))
    if rc != 0:
        raise RuntimeError(f"Could not inspect integration deletion counts: {stderr}")
    deletions: dict[str, int | None] = {relative_path: 0 for relative_path in files}
    for line in stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        _added, removed, relative_path = fields
        if relative_path not in deletions:
            continue
        deletions[relative_path] = None if removed == "-" else int(removed)
    return deletions


def _enforce_no_integration_deletion_amplification(
    source_metadata: dict,
    files: list[str],
    checkout_root: Path,
    *,
    patch_id: str,
    prepared_base: str,
) -> None:
    """Block stale worktree rebases that delete lines absent from the source edit.

    A long-lived worktree may retain an old file while partial deploy metadata
    advances ``merged_commit``. Diffing that old file against the newer global
    baseline turns unrelated upstream additions into apparent deletions. The
    actual worktree HEAD remains the authoritative statement of what the agent
    edited, so integration must never delete more text than that source patch.
    """
    if not files:
        return
    source_path = Path(str(source_metadata.get("path") or ""))
    source_head = _worktree_head(source_path)
    if not source_head:
        raise RuntimeError("Could not resolve the source worktree HEAD for deletion safety")
    source_deletions = _numstat_deletions(source_path, source_head, files)
    integrated_deletions = _numstat_deletions(
        checkout_root,
        prepared_base,
        files,
        cached=True,
    )
    amplified = []
    for relative_path in files:
        source_count = source_deletions.get(relative_path)
        integrated_count = integrated_deletions.get(relative_path)
        if source_count is None or integrated_count is None or integrated_count <= source_count:
            continue
        amplified.append(f"{relative_path} ({source_count} intended, {integrated_count} integrated)")
    if amplified:
        source_base = str(source_metadata.get("merged_commit") or source_metadata.get("base_commit") or "")
        raise IntegrationConflict(
            "Deletion amplification detected while rebasing a stale worktree: "
            + ", ".join(amplified)
            + ". Refresh or reconcile these files against current origin/dev before deploying.",
            patch_id=patch_id,
            source_base=source_base,
            final_base=prepared_base,
        )


def _selected_paths_changed_between_refs(
    repo_root: Path,
    source_ref: str,
    target_ref: str,
    files: list[str],
) -> list[str]:
    """Return selected paths whose upstream content changed between two refs."""
    if not files or source_ref == target_ref:
        return []
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            source_ref,
            target_ref,
            "--",
            *(f":(literal){relative_path}" for relative_path in files),
        ],
        cwd=str(repo_root),
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Could not inspect selected upstream changes: {detail}")
    return sorted(
        {
            raw_path.decode("utf-8", errors="replace")
            for raw_path in result.stdout.split(b"\0")
            if raw_path
        }
    )


def _regenerate_specification_artifacts(checkout_root: Path, generated_files: list[str]) -> None:
    """Regenerate selected Specification artifacts in an integration checkout."""
    if not generated_files:
        return
    script = checkout_root / "scripts" / "specifications.py"
    if not script.exists():
        raise RuntimeError("Specification artifact generation unavailable: scripts/specifications.py is missing")
    result = subprocess.run(
        [sys.executable, str(script), "generate", "--repo-root", str(checkout_root)],
        cwd=str(checkout_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "Specification artifact generation failed"
        raise RuntimeError(detail.strip())
    rc, _stdout, stderr = _run_cmd(["git", "add", "--", *sorted(generated_files)], cwd=str(checkout_root))
    if rc != 0:
        raise RuntimeError(f"Could not stage regenerated Specification artifacts: {stderr}")


def _apply_worktree_diff_to_checkout(
    source_metadata: dict,
    files: list[str],
    checkout_root: Path,
    *,
    patch_id: str,
    prepared_base: str,
    checkpoint_commit: str = "",
) -> None:
    """Apply selected source changes to a clean integration checkout and stage them."""
    source_path = Path(str(source_metadata.get("path") or ""))
    source_base = str(source_metadata.get("merged_commit") or source_metadata.get("base_commit") or "")
    if not source_path.is_dir() or not source_base:
        raise RuntimeError("Session source worktree metadata is incomplete")
    patch_files, specification_generated_files = _split_specification_generated_artifacts(files)
    if checkpoint_commit:
        rc, checkpoint_parent, stderr = _run_cmd(
            ["git", "rev-parse", f"{checkpoint_commit}^"],
            cwd=str(CONTROL_PLANE_ROOT),
        )
        checkpoint_parent = checkpoint_parent.strip()
        if rc != 0 or checkpoint_parent != source_base:
            raise IntegrationConflict(
                stderr or "Checkpoint parent no longer matches the recorded source base",
                patch_id=patch_id,
                source_base=source_base,
                final_base=prepared_base,
            )
        diff_result = subprocess.run(
            ["git", "diff", "--binary", source_base, checkpoint_commit, "--", *patch_files],
            cwd=str(CONTROL_PLANE_ROOT),
            capture_output=True,
            timeout=120,
        )
        if diff_result.returncode != 0:
            raise RuntimeError(diff_result.stderr.decode("utf-8", errors="replace").strip())
        diff_bytes = diff_result.stdout
        if diff_bytes:
            apply_command = ["git", "apply", "--index", "--whitespace=nowarn"]
            if prepared_base != source_base:
                apply_command.append("--3way")
            apply_result = subprocess.run(
                [*apply_command, "-"],
                cwd=str(checkout_root),
                input=diff_bytes,
                capture_output=True,
                timeout=120,
            )
            if apply_result.returncode != 0:
                detail = apply_result.stderr.decode("utf-8", errors="replace").strip()
                raise IntegrationConflict(
                    detail or "Checkpoint conflicts with current origin/dev",
                    patch_id=patch_id,
                    source_base=source_base,
                    final_base=prepared_base,
                )
        _regenerate_specification_artifacts(checkout_root, specification_generated_files)
        _enforce_no_integration_deletion_amplification(
            source_metadata,
            patch_files,
            checkout_root,
            patch_id=patch_id,
            prepared_base=prepared_base,
        )
        return
    current_patch_id = _worktree_patch_id(source_metadata, files)
    if current_patch_id != patch_id:
        raise IntegrationConflict(
            "Session source patch changed during integration preparation",
            patch_id=patch_id,
            source_base=source_base,
            final_base=prepared_base,
        )

    new_files = (
        _worktree_untracked_files(source_metadata)
        | _worktree_new_files(source_metadata, set(patch_files))
    ) & set(patch_files)
    new_files = {
        relative_path
        for relative_path in new_files
        if _run_cmd(
            ["git", "cat-file", "-e", f"{source_base}:{relative_path}"],
            cwd=str(source_path),
        )[0] != 0
    }
    tracked_files = [relative_path for relative_path in patch_files if relative_path not in new_files]
    if tracked_files:
        with tempfile.TemporaryDirectory(prefix="openmates-integration-index-") as temp_dir:
            index_env = {**os.environ, "GIT_INDEX_FILE": str(Path(temp_dir) / "index")}
            read_tree_result = subprocess.run(
                ["git", "read-tree", source_base],
                cwd=str(source_path),
                env=index_env,
                capture_output=True,
                timeout=120,
            )
            if read_tree_result.returncode != 0:
                raise RuntimeError(read_tree_result.stderr.decode("utf-8", errors="replace").strip())
            diff_result = subprocess.run(
                ["git", "diff", "--binary", source_base, "--", *tracked_files],
                cwd=str(source_path),
                env=index_env,
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

    for relative_path in sorted(new_files):
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

    _regenerate_specification_artifacts(checkout_root, specification_generated_files)
    _enforce_no_integration_deletion_amplification(
        source_metadata,
        patch_files,
        checkout_root,
        patch_id=patch_id,
        prepared_base=prepared_base,
    )


def _prepare_integration_worktree(
    session_id: str,
    source_metadata: dict,
    files: list[str],
    patch_id: str,
    prepared_base: str,
    *,
    checkpoint_commit: str = "",
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
        "source_base": str(source_metadata.get("merged_commit") or source_metadata.get("base_commit") or ""),
        "prepared_base": prepared_base,
        "files": sorted(files),
        "checkpoint_commit": checkpoint_commit,
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
            checkpoint_commit=checkpoint_commit,
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
    prepare_args = (
        str(integration.get("session_id") or "unknown"),
        source_metadata,
        files,
        str(integration.get("patch_id") or ""),
        prepared_base,
    )
    checkpoint_commit = str(integration.get("checkpoint_commit") or "")
    if checkpoint_commit:
        return _prepare_integration_worktree(*prepare_args, checkpoint_commit=checkpoint_commit)
    return _prepare_integration_worktree(*prepare_args)


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


def _worktree_checkpoint_ref(session_id: str) -> str:
    """Return the local-only Git ref used to retain one session checkpoint."""
    safe_session_id = re.sub(r"[^A-Za-z0-9_-]", "-", session_id)[:64] or "unknown"
    return f"refs/openmates/checkpoints/{safe_session_id}"


def _checkpoint_ref_expected_commit(session_id: str, checkpoint_ref: str, new_commit: str) -> str:
    """Return the compare-and-swap value without overwriting unrelated recovery state."""
    rc, previous_commit, _stderr = _run_cmd(
        ["git", "rev-parse", "--verify", checkpoint_ref],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc != 0:
        return "0" * 40
    previous_commit = previous_commit.strip()
    if previous_commit == new_commit:
        return previous_commit
    session = _load_sessions().get("sessions", {}).get(session_id, {})
    auto_integration = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
    if (
        auto_integration.get("checkpoint_ref") == checkpoint_ref
        and auto_integration.get("checkpoint_commit") == previous_commit
    ):
        return previous_commit
    # A normal deploy attempt creates the recovery commit before running its
    # gates. If a gate fails, that commit remains at the session-owned ref but
    # is intentionally not promoted into auto_integration metadata. A retry
    # must be able to replace that exact session checkpoint without weakening
    # the compare-and-swap guard for arbitrary commits or reused session IDs.
    rc, subject, _stderr = _run_cmd(
        ["git", "show", "-s", "--format=%s", previous_commit],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc == 0 and subject.strip() == f"checkpoint: preserve session {session_id}":
        return previous_commit
    raise RuntimeError(f"Refusing to overwrite checkpoint ref with unverified provenance: {checkpoint_ref}")


def _delete_worktree_checkpoint_ref(session_id: str, *, expected_commit: str = "") -> bool:
    """Delete a local checkpoint ref after its exact patch is integrated."""
    command = ["git", "update-ref", "-d", _worktree_checkpoint_ref(session_id)]
    if expected_commit:
        command.append(expected_commit)
    rc, _stdout, _stderr = _run_cmd(command, cwd=str(CONTROL_PLANE_ROOT))
    if rc == 0:
        return True
    verify_rc, _actual, _verify_stderr = _run_cmd(
        ["git", "rev-parse", "--verify", _worktree_checkpoint_ref(session_id)],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    return verify_rc != 0


@contextmanager
def _worktree_checkpoint_lock(session_id: str):
    """Serialize checkpoint ref and metadata updates for one session."""
    WORKTREE_CHECKPOINT_LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    safe_session_id = re.sub(r"[^A-Za-z0-9_-]", "-", session_id)[:64] or "unknown"
    with (WORKTREE_CHECKPOINT_LOCKS_DIR / f"{safe_session_id}.lock").open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _prune_checkpoint_lock_files(data: dict) -> list[str]:
    """Remove orphaned checkpoint lock files after their session records expire."""
    if not WORKTREE_CHECKPOINT_LOCKS_DIR.is_dir():
        return []
    active_lock_names = {
        f"{re.sub(r'[^A-Za-z0-9_-]', '-', str(session_id))[:64] or 'unknown'}.lock"
        for session_id in data.get("sessions", {})
    }
    removed: list[str] = []
    cutoff = time.time() - CHECKPOINT_LOCK_RETENTION_HOURS * 60 * 60
    for lock_path in WORKTREE_CHECKPOINT_LOCKS_DIR.glob("*.lock"):
        if lock_path.name in active_lock_names:
            continue
        try:
            if lock_path.stat().st_mtime > cutoff:
                continue
            lock_path.unlink()
        except OSError:
            continue
        removed.append(lock_path.stem)
    try:
        WORKTREE_CHECKPOINT_LOCKS_DIR.rmdir()
    except OSError:
        pass
    return removed


def _create_worktree_checkpoint_commit(
    session_id: str,
    metadata: dict,
    files: list[str],
    patch_id: str,
) -> str:
    """Commit an exact source patch to a local ref without changing source or dev."""
    source_base = str(metadata.get("merged_commit") or metadata.get("base_commit") or "")
    if not source_base:
        raise RuntimeError("Cannot checkpoint a worktree without a source base")
    integration = _prepare_integration_worktree(session_id, metadata, files, patch_id, source_base)
    try:
        checkout_root = Path(str(integration["path"]))
        rc, _stdout, stderr = _run_cmd(
            ["git", "commit", "--no-verify", "-m", f"checkpoint: preserve session {session_id}"],
            cwd=str(checkout_root),
            timeout=300,
        )
        if rc != 0:
            diff_rc, _diff_stdout, diff_stderr = _run_cmd(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(checkout_root),
            )
            if diff_rc != 0:
                raise RuntimeError(f"Could not create worktree checkpoint commit: {stderr or _stdout or diff_stderr}")
            commit_hash = source_base
        else:
            rc, commit_hash, stderr = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(checkout_root))
            commit_hash = commit_hash.strip()
            if rc != 0 or not commit_hash:
                raise RuntimeError(f"Could not resolve worktree checkpoint commit: {stderr}")
        checkpoint_ref = _worktree_checkpoint_ref(session_id)
        expected_commit = _checkpoint_ref_expected_commit(session_id, checkpoint_ref, commit_hash)
        rc, _stdout, stderr = _run_cmd(
            ["git", "update-ref", checkpoint_ref, commit_hash, expected_commit],
            cwd=str(CONTROL_PLANE_ROOT),
        )
        if rc != 0:
            raise RuntimeError(f"Could not retain worktree checkpoint ref: {stderr}")
        return commit_hash
    finally:
        _remove_integration_worktree(integration)


def _auto_integration_block_reason(files: list[str]) -> str:
    """Return a stable reason when a patch requires explicit operator review."""
    for relative_path in files:
        if any(relative_path == prefix or relative_path.startswith(prefix) for prefix in WORKTREE_AUTO_INTEGRATION_SENSITIVE_PREFIXES):
            return f"sensitive_path:{relative_path}"
        if relative_path.endswith(WORKTREE_AUTO_INTEGRATION_SENSITIVE_SUFFIXES) or WORKTREE_AUTO_INTEGRATION_SENSITIVE_PATH_RE.search(relative_path):
            return f"sensitive_path:{relative_path}"
    return ""


def checkpoint_session_worktree(opencode_session_id: str, *, event: str) -> dict:
    """Checkpoint one top-level mutating chat and make safe patches integration eligible."""
    if event not in {"idle", "closed"}:
        raise ValueError("checkpoint event must be idle or closed")
    data = _load_sessions()
    matched = session_for_opencode(data, opencode_session_id)
    if not matched:
        return {"status": "skipped", "reason": "not_top_level_session"}
    session_id, session = matched
    if session.get("auto_integration_policy") != "enabled":
        return {"status": "skipped", "reason": "automatic_recovery_not_enabled"}
    metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None
    if (
        session.get("mode") == "question"
        or not metadata
        or not metadata.get("path")
        or session.get("binding_mode") not in WORKTREE_AUTO_INTEGRATION_BINDING_MODES
    ):
        return {"status": "skipped", "reason": "not_mutating_worktree"}
    with _worktree_checkpoint_lock(session_id):
        return _checkpoint_session_worktree_locked(session_id, event=event)


def _store_session_worktree_active(data: dict, session_id: str, now: str) -> dict:
    session = data.get("sessions", {}).get(session_id)
    if not isinstance(session, dict):
        return {"status": "skipped", "reason": "session_disappeared"}
    metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None
    if not metadata:
        return {"status": "skipped", "reason": "not_mutating_worktree"}
    metadata["status"] = "active"
    metadata["last_active"] = now
    session["last_active"] = now
    session["workspace_state"] = "changes_pending"
    auto = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else None
    if auto and auto.get("status") != "integrated":
        auto["status"] = "changes_pending"
        auto["updated_at"] = now
        auto["block_reason"] = "live_turn_started"
    return {"status": "active", "session_id": session_id, "workspace_state": "changes_pending"}


def activate_session_worktree(opencode_session_id: str) -> dict:
    """Invalidate an idle checkpoint when its top-level chat starts a new turn."""
    matched = session_for_opencode(_load_sessions(), opencode_session_id)
    if not matched:
        return {"status": "skipped", "reason": "not_top_level_session"}
    session_id, _session = matched
    with _worktree_checkpoint_lock(session_id):
        return _mutate_sessions(lambda data: _store_session_worktree_active(data, session_id, _now_iso()))


def _checkpoint_session_worktree_locked(session_id: str, *, event: str) -> dict:
    """Create and persist one checkpoint while holding its session lock."""
    data = _load_sessions()
    session = data.get("sessions", {}).get(session_id)
    if not isinstance(session, dict):
        return {"status": "skipped", "reason": "session_disappeared"}
    metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None
    if not metadata or not metadata.get("path"):
        return {"status": "skipped", "reason": "worktree_binding_changed"}
    files = _session_deploy_files(session, set())
    if not files:
        workspace_state = "integrated" if metadata.get("merged_commit") else "clean"

        def mark_clean(current: dict) -> None:
            current_session = current.get("sessions", {}).get(session_id)
            if isinstance(current_session, dict):
                current_session["workspace_state"] = workspace_state

        _mutate_sessions(mark_clean)
        return {"status": "skipped", "reason": "no_pending_changes", "workspace_state": workspace_state}

    patch_id = _worktree_patch_id(metadata, files)
    def mark_checkpointing(current: dict) -> None:
        current_session = current.get("sessions", {}).get(session_id)
        if isinstance(current_session, dict):
            current_session["workspace_state"] = "changes_pending"

    _mutate_sessions(mark_checkpointing)
    try:
        checkpoint_commit = _create_worktree_checkpoint_commit(session_id, metadata, files, patch_id)
    except (OSError, RuntimeError) as exc:
        failure_reason = f"checkpoint_failed:{str(exc)[-1000:]}"

        def mark_failed(current: dict) -> None:
            current_session = current.get("sessions", {}).get(session_id)
            if not isinstance(current_session, dict):
                return
            previous = current_session.get("auto_integration") if isinstance(current_session.get("auto_integration"), dict) else {}
            current_session["workspace_state"] = "recovery_needed"
            current_session["auto_integration"] = {
                **previous,
                "status": "blocked",
                "event": event,
                "patch_id": patch_id,
                "files": sorted(files),
                "checkpointed_at": _now_iso(),
                "block_reason": failure_reason,
            }

        _mutate_sessions(mark_failed)
        raise
    current_patch_id = _worktree_patch_id(metadata, files)
    existing = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
    hold = bool(existing.get("hold"))
    live_lease = any(
        isinstance(lease, dict) and lease.get("session_id") == session_id
        for lease in data.get("edit_leases", {}).values()
    )
    block_reason = _auto_integration_block_reason(files)
    if current_patch_id != patch_id:
        status = "recovery_needed"
        block_reason = "patch_changed_during_checkpoint"
    elif hold or live_lease:
        status = "held"
        block_reason = "explicit_hold" if hold else "live_edit_lease"
    elif block_reason:
        status = "blocked"
    else:
        status = "eligible"
    eligible_after = (
        datetime.now(timezone.utc) + timedelta(minutes=WORKTREE_AUTO_INTEGRATION_GRACE_MINUTES)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = _now_iso()

    def store(current: dict) -> dict:
        current_session = current.get("sessions", {}).get(session_id)
        if not isinstance(current_session, dict):
            raise RuntimeError(f"Session {session_id} disappeared during checkpoint")
        current_session["workspace_state"] = "checkpointed" if status == "eligible" else ("held" if status == "held" else "recovery_needed")
        current_session["auto_integration"] = {
            "status": status,
            "hold": hold,
            "event": event,
            "patch_id": patch_id,
            "checkpoint_commit": checkpoint_commit,
            "checkpoint_ref": _worktree_checkpoint_ref(session_id),
            "files": sorted(files),
            "checkpointed_at": now,
            "eligible_after": eligible_after,
            "block_reason": block_reason,
        }
        return dict(current_session["auto_integration"])

    result = _mutate_sessions(store)
    return {"session_id": session_id, **result}


def _auto_integration_presence_is_live(session: dict) -> bool:
    """Return whether the top-level OpenCode chat is currently executing."""
    opencode_session_id = str(session.get("opencode_session_id") or "")
    if not opencode_session_id:
        return False
    try:
        record = _opencode_presence_store().snapshot().get("sessions", {}).get(opencode_session_id, {})
    except (OSError, PresenceStoreError):
        return True
    return record.get("execution") in {"busy", "retrying"}


def _checkpoint_ref_matches(session_id: str, auto: dict) -> bool:
    """Return whether durable metadata still names the retained checkpoint ref."""
    checkpoint_ref = str(auto.get("checkpoint_ref") or "")
    checkpoint_commit = str(auto.get("checkpoint_commit") or "")
    if checkpoint_ref != _worktree_checkpoint_ref(session_id) or not checkpoint_commit:
        return False
    rc, actual_commit, _stderr = _run_cmd(
        ["git", "rev-parse", "--verify", checkpoint_ref],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    return rc == 0 and actual_commit.strip() == checkpoint_commit


def select_auto_integration_candidates(*, now: str | None = None) -> list[dict]:
    """Return exact current checkpoints eligible for the normal deploy transaction."""
    data = _load_sessions()
    current_time = _parse_iso(now or _now_iso())
    selected: list[dict] = []
    rejected: list[tuple[str, str, str]] = []
    for session_id, session in sorted(data.get("sessions", {}).items()):
        if not isinstance(session, dict):
            continue
        auto = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
        metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else {}
        if auto.get("status") != "eligible" or not metadata.get("path"):
            continue
        if auto.get("hold"):
            rejected.append((session_id, "held", "explicit_hold"))
            continue
        if session.get("auto_integration_policy") != "enabled" or session.get("binding_mode") not in WORKTREE_AUTO_INTEGRATION_BINDING_MODES:
            rejected.append((session_id, "blocked", "legacy_or_unapproved_session"))
            continue
        if not _checkpoint_ref_matches(session_id, auto):
            rejected.append((session_id, "recovery_needed", "checkpoint_ref_missing_or_changed"))
            continue
        try:
            if _parse_iso(str(auto.get("eligible_after") or "")) > current_time:
                continue
        except (TypeError, ValueError):
            rejected.append((session_id, "recovery_needed", "invalid_eligible_after"))
            continue
        if _auto_integration_presence_is_live(session):
            rejected.append((session_id, "held", "live_presence"))
            continue
        if any(
            isinstance(lease, dict) and lease.get("session_id") == session_id
            for lease in data.get("edit_leases", {}).values()
        ):
            rejected.append((session_id, "held", "live_edit_lease"))
            continue
        try:
            files = _session_deploy_files(session, set())
            checkpoint_files = sorted(str(path) for path in auto.get("files") or [])
            if sorted(files) != checkpoint_files:
                rejected.append((session_id, "recovery_needed", "checkpoint_file_set_changed"))
                continue
            block_reason = _auto_integration_block_reason(files)
            if block_reason:
                rejected.append((session_id, "blocked", block_reason))
                continue
            if not files or _worktree_patch_id(metadata, files) != auto.get("patch_id"):
                rejected.append((session_id, "recovery_needed", "checkpoint_patch_changed"))
                continue
        except (OSError, RuntimeError) as exc:
            rejected.append(
                (session_id, "recovery_needed", f"candidate_inspection_failed:{str(exc)[-1000:]}")
            )
            continue
        selected.append(
            {
                "session_id": session_id,
                "task": str(session.get("task") or "checkpointed work"),
                "patch_id": str(auto.get("patch_id") or ""),
                "checkpoint_commit": str(auto.get("checkpoint_commit") or ""),
                "files": files,
            }
        )
    for session_id, status, reason in rejected:
        _record_auto_integration_state(session_id, status, reason=reason)
    return selected


def _record_auto_integration_state(session_id: str, status: str, *, reason: str = "") -> None:
    """Persist an automatic integration transition independently from chat presence."""
    def store(data: dict) -> None:
        session = data.get("sessions", {}).get(session_id)
        if not isinstance(session, dict):
            return
        auto = session.setdefault("auto_integration", {})
        auto["status"] = status
        auto["updated_at"] = _now_iso()
        auto["block_reason"] = reason
        if status in {"changes_pending", "integrated", "integrating", "held"}:
            session["workspace_state"] = status
        else:
            session["workspace_state"] = "recovery_needed"

    _mutate_sessions(store)


def checkpoint_idle_sessions(*, now: str | None = None) -> list[dict]:
    """Checkpoint opted-in mutating sessions that stopped producing heartbeats."""
    current_time = _parse_iso(now or _now_iso())
    data = _load_sessions()
    results: list[dict] = []
    for _session_id, session in sorted(data.get("sessions", {}).items()):
        if not isinstance(session, dict) or session.get("auto_integration_policy") != "enabled":
            continue
        try:
            opencode_session_id = str(session.get("opencode_session_id") or "")
            if not opencode_session_id or _auto_integration_presence_is_live(session):
                continue
            last_active = str(session.get("last_active") or session.get("started") or "")
            try:
                idle_minutes = (current_time - _parse_iso(last_active)).total_seconds() / 60
            except (TypeError, ValueError):
                continue
            if idle_minutes < WORKTREE_AUTO_INTEGRATION_GRACE_MINUTES:
                continue
            auto = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
            metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else {}
            files = _session_deploy_files(session, set())
            if not files:
                continue
            retryable_status = auto.get("status") in {"blocked", "recovery_needed"} or (
                auto.get("status") == "held" and auto.get("block_reason") != "explicit_hold"
            )
            if not retryable_status and auto.get("patch_id") and auto.get("files") == files:
                try:
                    if _worktree_patch_id(metadata, files) == auto.get("patch_id"):
                        continue
                except (OSError, RuntimeError):
                    pass
            results.append(checkpoint_session_worktree(opencode_session_id, event="idle"))
        except (OSError, RuntimeError) as exc:
            # One corrupt or unrecoverable worktree must not suppress every
            # later checkpoint/integration candidate in the hourly pass.
            results.append(
                {
                    "session_id": str(_session_id),
                    "status": "blocked",
                    "reason": str(exc)[-2000:],
                }
            )
    return results


def _complete_auto_integration(candidate: dict) -> bool:
    """Finish only the checkpoint that the worker actually deployed."""
    session_id = str(candidate["session_id"])
    with _worktree_checkpoint_lock(session_id):
        session = _load_sessions().get("sessions", {}).get(session_id, {})
        auto = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
        if (
            auto.get("status") != "integrated"
            or auto.get("patch_id") != candidate.get("patch_id")
            or auto.get("checkpoint_commit") != candidate.get("checkpoint_commit")
        ):
            return False
        metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else {}
        files = sorted(str(path) for path in candidate.get("files") or [])
        try:
            source_still_matches = bool(files) and _worktree_patch_id(metadata, files) == candidate.get("patch_id")
        except (OSError, RuntimeError):
            source_still_matches = False
        if not source_still_matches:
            _record_auto_integration_state(session_id, "changes_pending", reason="source_changed_during_deploy")
            return False
        if not _delete_worktree_checkpoint_ref(
            session_id,
            expected_commit=str(candidate.get("checkpoint_commit") or ""),
        ):
            _record_auto_integration_state(session_id, "recovery_needed", reason="checkpoint_ref_cleanup_failed")
            return False
        _record_auto_integration_state(session_id, "integrated")
        return True


def _claim_auto_integration(candidate: dict) -> bool:
    """Atomically claim one unchanged eligible checkpoint for a worker."""
    session_id = str(candidate["session_id"])
    with _worktree_checkpoint_lock(session_id):
        session = _load_sessions().get("sessions", {}).get(session_id, {})
        auto = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
        if _auto_integration_presence_is_live(session):
            _mutate_sessions(lambda data: _store_session_worktree_active(data, session_id, _now_iso()))
            return False
        if (
            auto.get("status") != "eligible"
            or auto.get("patch_id") != candidate.get("patch_id")
            or auto.get("checkpoint_commit") != candidate.get("checkpoint_commit")
            or not _checkpoint_ref_matches(session_id, auto)
        ):
            return False
        _record_auto_integration_state(session_id, "integrating")
        return True


def _fail_auto_integration(candidate: dict, reason: str) -> None:
    """Block only the same checkpoint claimed by this worker."""
    session_id = str(candidate["session_id"])
    with _worktree_checkpoint_lock(session_id):
        session = _load_sessions().get("sessions", {}).get(session_id, {})
        auto = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
        if (
            auto.get("patch_id") == candidate.get("patch_id")
            and auto.get("checkpoint_commit") == candidate.get("checkpoint_commit")
        ):
            _record_auto_integration_state(session_id, "blocked", reason=reason)


def auto_integrate_checkpoints(*, runner=None, now: str | None = None, dry_run: bool = False) -> dict:
    """Integrate eligible checkpoints through sessions.py deploy with no gate waivers."""
    checkpointed = [] if dry_run else checkpoint_idle_sessions(now=now)
    candidates = select_auto_integration_candidates(now=now)
    result = {
        "checkpointed": checkpointed,
        "eligible": [item["session_id"] for item in candidates],
        "integrated": [],
        "blocked": [],
    }
    if dry_run:
        return result
    if runner is None:
        def runner(command: list[str]) -> tuple[int, str, str]:
            completed = subprocess.run(
                command,
                cwd=str(CONTROL_PLANE_ROOT),
                capture_output=True,
                text=True,
                timeout=3600,
            )
            return completed.returncode, completed.stdout, completed.stderr
    for candidate in candidates:
        session_id = candidate["session_id"]
        if not _claim_auto_integration(candidate):
            continue
        command = [
            sys.executable,
            "scripts/sessions.py",
            "deploy",
            "--session",
            session_id,
            "--title",
            f"chore: integrate idle session {session_id}",
            "--message",
            f"Automatically integrate the validated checkpoint for: {candidate['task']}",
            "--expected-patch-id",
            candidate["patch_id"],
            "--expected-checkpoint-commit",
            candidate["checkpoint_commit"],
        ]
        returncode, stdout, stderr = runner(command)
        if returncode == 0:
            if _complete_auto_integration(candidate):
                result["integrated"].append(session_id)
            else:
                result["blocked"].append({"session_id": session_id, "reason": "checkpoint_changed_during_deploy"})
            continue
        reason = (stderr or stdout or "automatic deploy failed").strip()[-2000:]
        _fail_auto_integration(candidate, reason)
        result["blocked"].append({"session_id": session_id, "reason": reason})
    return result


def _validate_managed_worktree_path(path: str | Path) -> Path:
    managed_path = Path(path).resolve()
    if not is_valid_managed_worktree_path(managed_path):
        raise RuntimeError(
            f"Refusing agent worktree outside or nested beneath {AGENT_WORKTREES_DIR}: {managed_path}"
        )
    return managed_path


def _existing_direct_managed_worktree(path: str | Path, *, linked_paths: set[Path] | None = None) -> bool:
    """Return whether a path is a linked worktree of the control-plane repository."""
    candidate = Path(path)
    if not is_valid_managed_worktree_path(candidate) or not candidate.is_dir():
        return False
    if linked_paths is None:
        linked_paths = {
            Path(str(item.get("path") or "")).resolve()
            for item in _linked_git_worktrees()
            if item.get("path")
        }
    return candidate.resolve() in linked_paths


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


def _discover_worktree_candidates(*, only_session_ids: set[str] | None = None) -> list[dict]:
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
    root = CONTROL_PLANE_ROOT.resolve()
    for resolved_path, linked_item in sorted(paths.items()):
        path = Path(resolved_path)
        if path == root:
            continue
        registered = by_path.get(resolved_path, {})
        metadata = registered.get("metadata") if isinstance(registered.get("metadata"), dict) else {}
        session = registered.get("session") if isinstance(registered.get("session"), dict) else {}
        session_id = str(registered.get("session_id") or _worktree_candidate_id(resolved_path, metadata))
        if only_session_ids and session_id not in only_session_ids:
            continue
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
                "session": session,
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


def _target_file_mode(target_ref: str, relative_path: str) -> str | None:
    result = subprocess.run(
        ["git", "ls-tree", target_ref, "--", relative_path],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split(maxsplit=1)[0]


def _local_file_mode(path: Path) -> str | None:
    if path.is_symlink():
        return "120000"
    if not path.is_file():
        return None
    return "100755" if path.stat().st_mode & 0o111 else "100644"


def _worktree_target_files_match(candidate: dict, target_ref: str) -> bool:
    path = Path(candidate.get("path") or "")
    changed_files = candidate.get("changed_files") or []
    if not path.exists() or not changed_files:
        return False
    for relative_path in changed_files:
        local_path = path / relative_path
        target_bytes = _target_file_bytes(target_ref, relative_path)
        target_mode = _target_file_mode(target_ref, relative_path)
        if local_path.exists() or local_path.is_symlink():
            local_mode = _local_file_mode(local_path)
            if local_mode is None:
                return False
            local_bytes = os.readlink(local_path).encode() if local_path.is_symlink() else local_path.read_bytes()
            if target_bytes is None or target_mode is None or local_mode != target_mode or local_bytes != target_bytes:
                return False
        elif target_bytes is not None or target_mode is not None:
            return False
    return True


def _legacy_worktree_chat_lineage(db_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Reconstruct legacy worktree ownership from bounded session-start outputs."""
    try:
        connection = _opencode_readonly_connection(db_path)
    except (FileNotFoundError, sqlite3.Error):
        return {}
    try:
        parents = {
            str(row["id"]): str(row["parent_id"]) if row["parent_id"] else None
            for row in connection.execute("SELECT id, parent_id FROM session")
        }

        def top_level(session_id: str) -> str:
            current = session_id
            seen = {current}
            while parents.get(current) and parents[current] not in seen:
                current = str(parents[current])
                seen.add(current)
            return current

        events: dict[str, dict[str, Any]] = {}
        rows = connection.execute(
            """
            SELECT session_id, time_created, data
            FROM part
            WHERE data LIKE '%== SESSION %' AND data LIKE '%Worktree:%'
            """
        )
        for row in rows:
            decoded = _decode_opencode_json(row["data"])
            if not isinstance(decoded, dict) or decoded.get("type") != "tool":
                continue
            state = decoded.get("state") if isinstance(decoded.get("state"), dict) else {}
            output = str(state.get("output") or "")
            session_match = re.search(r"== SESSION ([0-9a-f]{4})\b", output)
            worktree_match = re.search(r"^\s*Worktree:\s+(.+?)\s*$", output, re.MULTILINE)
            if not session_match or not worktree_match or not worktree_match.group(1).strip().startswith("/"):
                continue
            repository_session_id = session_match.group(1)
            created_ms = int(row["time_created"] or 0)
            previous = events.get(repository_session_id)
            if previous and int(previous["lineage_created_ms"]) >= created_ms:
                continue
            events[repository_session_id] = {
                "chat_lineage": top_level(str(row["session_id"])),
                "lineage_created_ms": created_ms,
            }
        return events
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def _plan_duplicate_chat_worktrees(candidates: list[dict]) -> dict:
    """Keep only the newest source worktree for each known chat lineage."""
    grouped: dict[str, list[dict]] = {}
    lineage_unknown: list[str] = []
    integration_excluded: list[str] = []
    invalid_path_excluded: list[str] = []
    for candidate in candidates:
        session_id = str(candidate.get("session_id") or "")
        if candidate.get("worktree_kind") == "integration":
            integration_excluded.append(session_id)
            continue
        if candidate.get("lineage_path_valid") is False:
            invalid_path_excluded.append(session_id)
            continue
        lineage = str(candidate.get("chat_lineage") or "")
        if not lineage:
            lineage_unknown.append(session_id)
            continue
        grouped.setdefault(lineage, []).append(candidate)

    retained: list[str] = []
    remove: list[str] = []
    groups: list[dict] = []
    authoritative: dict[str, str] = {}
    for lineage, items in sorted(grouped.items()):
        ordered = sorted(
            items,
            key=lambda item: (
                int(item.get("lineage_created_ms") or 0),
                str((item.get("metadata") or {}).get("created_at") or ""),
                str(item.get("last_active") or ""),
                bool(item.get("lineage_bound")),
                str(item.get("path") or ""),
            ),
        )
        keep = ordered[-1]
        authoritative[lineage] = str(keep.get("session_id") or "")
        if len(items) < 2:
            continue
        discarded = ordered[:-1]
        retained.append(str(keep.get("session_id") or ""))
        remove.extend(str(item.get("session_id") or "") for item in discarded)
        groups.append(
            {
                "chat_lineage": lineage,
                "retained": str(keep.get("session_id") or ""),
                "remove": [str(item.get("session_id") or "") for item in discarded],
            }
        )
    return {
        "duplicate_chat_count": len(groups),
        "groups": groups,
        "authoritative": authoritative,
        "retained": sorted(retained),
        "remove": sorted(remove),
        "lineage_unknown": sorted(lineage_unknown),
        "integration_excluded": sorted(integration_excluded),
        "invalid_path_excluded": sorted(invalid_path_excluded),
    }


def _chat_lineage_worktree_candidates(*, db_path: Path | None = None) -> list[dict]:
    """Enrich current worktree candidates with durable or reconstructed chat lineage."""
    legacy = _legacy_worktree_chat_lineage(db_path)
    linked_paths = {
        Path(str(item.get("path") or "")).resolve()
        for item in _linked_git_worktrees()
        if item.get("path")
    }
    enriched: list[dict] = []
    for candidate in _discover_worktree_candidates():
        item = dict(candidate)
        session = item.get("session") if isinstance(item.get("session"), dict) else {}
        event = legacy.get(str(item.get("session_id") or ""), {})
        lineage = str(session.get("opencode_top_level_session_id") or event.get("chat_lineage") or "")
        created_ms = int(event.get("lineage_created_ms") or 0)
        if not created_ms:
            created_at = str((item.get("metadata") or {}).get("created_at") or session.get("started") or "")
            try:
                created_ms = int(_parse_iso(created_at).timestamp() * 1000) if created_at else 0
            except (TypeError, ValueError):
                created_ms = 0
        item["chat_lineage"] = lineage
        item["lineage_created_ms"] = created_ms
        item["lineage_bound"] = bool(lineage and session.get("opencode_session_id") == lineage)
        item["lineage_path_valid"] = _existing_direct_managed_worktree(
            str(item.get("path") or ""),
            linked_paths=linked_paths,
        )
        enriched.append(item)
    return enriched


def _retain_worktree_head_checkpoint(session_id: str, candidate: dict) -> str:
    """Retain one clean but unproven worktree head before duplicate cleanup."""
    head = str(candidate.get("head") or "")
    if not head:
        raise RuntimeError(f"Cannot checkpoint duplicate worktree {session_id} without a head commit")
    checkpoint_ref = _worktree_checkpoint_ref(session_id)
    expected = _checkpoint_ref_expected_commit(session_id, checkpoint_ref, head)
    rc, _stdout, stderr = _run_cmd(
        ["git", "update-ref", checkpoint_ref, head, expected],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc != 0:
        raise RuntimeError(f"Could not retain duplicate worktree head: {stderr}")
    return head


def _checkpoint_duplicate_worktree(session_id: str, candidate: dict) -> str:
    """Retain the latest readable state before deleting one duplicate worktree."""
    files = list(candidate.get("changed_files") or [])
    if files:
        metadata = dict(candidate.get("metadata") or {})
        metadata["path"] = str(candidate.get("path") or "")
        if not metadata.get("base_commit") and not metadata.get("merged_commit"):
            metadata["base_commit"] = str(candidate.get("head") or _current_git_sha(metadata["path"]))
        patch_id = _worktree_patch_id(metadata, files)
        return _create_worktree_checkpoint_commit(session_id, metadata, files, patch_id)
    if not candidate.get("head"):
        checkpoint_ref = _worktree_checkpoint_ref(session_id)
        rc, existing_checkpoint, _stderr = _run_cmd(
            ["git", "rev-parse", "--verify", checkpoint_ref],
            cwd=str(CONTROL_PLANE_ROOT),
        )
        if rc == 0:
            return existing_checkpoint.strip()
        if not (Path(str(candidate.get("path") or "")) / ".git").exists():
            return ""
    return _retain_worktree_head_checkpoint(session_id, candidate)


def deduplicate_chat_worktrees(
    *,
    target_ref: str = "origin/dev",
    apply: bool = False,
    db_path: Path | None = None,
) -> dict:
    """Report or remove older source worktrees owned by the same top-level chat."""
    rc, target_commit, stderr = _run_cmd(["git", "rev-parse", target_ref])
    if rc != 0:
        raise RuntimeError(f"Failed to resolve {target_ref}: {stderr}")
    target_commit = target_commit.strip()
    candidates = _chat_lineage_worktree_candidates(db_path=db_path)
    plan = _plan_duplicate_chat_worktrees(candidates)
    report = {
        "target_ref": target_ref,
        "target_commit": target_commit,
        "apply": apply,
        **plan,
        "deleted": [],
        "checkpointed": [],
        "blocked": [],
    }
    if not apply:
        return report

    candidates_by_id = {str(item.get("session_id") or ""): item for item in candidates}
    retained_by_lineage = dict(plan["authoritative"])
    for session_id in plan["remove"]:
        candidate = candidates_by_id[session_id]
        lineage = str(candidate.get("chat_lineage") or "")
        retained_session_id = retained_by_lineage[lineage]
        def remove_duplicate(data: dict) -> dict:
            session = data.get("sessions", {}).get(session_id, {})
            live_lease = any(
                isinstance(lease, dict) and lease.get("session_id") == session_id
                for lease in data.get("edit_leases", {}).values()
            )
            if session.get("writing") or live_lease:
                return {"blocked": "live_edit"}
            fresh = _refresh_reconciliation_candidate(candidate, data, target_commit, 0, set())
            if not _existing_direct_managed_worktree(str(fresh.get("path") or "")):
                return {"blocked": "invalid_or_missing_worktree"}
            if fresh.get("classification") == "malformed":
                return {"blocked": "inspection_failed"}
            checkpoint_commit = ""
            if fresh.get("classification") not in {"integrated", "duplicated", "superseded"}:
                checkpoint_commit = _checkpoint_duplicate_worktree(session_id, fresh)
            _remove_reconciled_worktree(fresh)
            _prune_deletion_manifests(data)
            data.setdefault("sessions", {}).pop(session_id, None)
            data["deploy_queue"] = [
                item for item in data.setdefault("deploy_queue", [])
                if str(item.get("session_id") or "") != session_id
            ]
            data["edit_leases"] = {
                path: lease
                for path, lease in data.setdefault("edit_leases", {}).items()
                if str(lease.get("session_id") or "") != session_id
            }
            data.setdefault("worktree_deletion_manifests", []).append(
                {
                    "session_id": session_id,
                    "worktree_name": Path(str(candidate.get("path") or "")).name,
                    "classification": "duplicate_chat_worktree",
                    "reason": "older_worktree_for_same_chat",
                    "reason_code": "duplicate_chat_lineage",
                    "chat_lineage": lineage,
                    "retained_session_id": retained_session_id,
                    "checkpoint_ref": _worktree_checkpoint_ref(session_id) if checkpoint_commit else "",
                    "checkpoint_commit": checkpoint_commit,
                    "changed_file_count": len(fresh.get("changed_files") or []),
                    "head": str(fresh.get("head") or ""),
                    "target_commit": target_commit,
                    "deleted_at": _now_iso(),
                }
            )
            return {"deleted": True, "checkpoint_commit": checkpoint_commit}

        try:
            with _worktree_checkpoint_lock(session_id):
                outcome = _mutate_sessions(remove_duplicate)
        except (OSError, RuntimeError) as exc:
            report["blocked"].append({"session_id": session_id, "reason": f"cleanup_failed:{exc}"})
            continue
        if outcome.get("blocked"):
            report["blocked"].append({"session_id": session_id, "reason": str(outcome["blocked"])})
            continue
        checkpoint_commit = str(outcome.get("checkpoint_commit") or "")
        if checkpoint_commit:
            report["checkpointed"].append(
                {
                    "session_id": session_id,
                    "checkpoint_ref": _worktree_checkpoint_ref(session_id),
                    "checkpoint_commit": checkpoint_commit,
                }
            )
        report["deleted"].append(session_id)

    def bind_authoritative(data: dict) -> None:
        sessions = data.setdefault("sessions", {})
        for lineage, session_id in retained_by_lineage.items():
            if session_id not in sessions:
                continue
            sessions[session_id]["opencode_top_level_session_id"] = lineage
            bind_opencode_session(data, session_id, lineage)

    _mutate_sessions(bind_authoritative)
    return report


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
    if session_id in approved_obsolete:
        result.update(classification="superseded", reason_code="review_approved_obsolete")
        return result
    if result.get("inspection_error"):
        result.update(classification="malformed", reason_code="inspection_failed")
        return result
    if result.get("worktree_kind") == "integration":
        if result.get("changed_files"):
            result.update(classification="unique_stale", reason_code="integration_has_changes")
            return result
        result.update(classification="disposable_integration", reason_code="reproducible_integration_state")
        return result
    if result.get("classification") in {"integrated", "duplicated", "superseded", "unique_stale", "uncertain"}:
        return result
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    integration = metadata.get("integration") if isinstance(metadata.get("integration"), dict) else {}
    deployed_patch = str(metadata.get("root_applied_patch_id") or integration.get("patch_id") or "")
    merged_commit = str(metadata.get("merged_commit") or "")
    if merged_commit and _git_is_ancestor(merged_commit, target_ref):
        if _worktree_target_files_match(result, merged_commit):
            result.update(classification="integrated", reason_code="merged_file_states_reachable")
            return result
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
        try:
            shutil.rmtree(path)
        except OSError as host_exc:
            try:
                _remove_expired_worktree_with_container(path)
            except (OSError, RuntimeError) as cleanup_exc:
                details = "; ".join(
                    item for item in (stderr.strip(), str(host_exc), str(cleanup_exc)) if item
                )
                raise RuntimeError(f"Failed to remove worktree {path}: {details}") from cleanup_exc
    if path.exists():
        raise RuntimeError(f"Worktree still exists after removal: {path}")
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
    if only_session_ids:
        try:
            discovered = _discover_worktree_candidates(only_session_ids=only_session_ids)
        except TypeError as exc:
            # Preserve compatibility with tests and downstream wrappers that
            # monkeypatch the historical zero-argument discovery hook.
            if "unexpected keyword argument" not in str(exc):
                raise
            discovered = _discover_worktree_candidates()
            discovered = [
                candidate
                for candidate in discovered
                if str(candidate.get("session_id") or "") in only_session_ids
            ]
    else:
        discovered = _discover_worktree_candidates()
    for candidate in discovered:
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


def _write_worktree_reconciliation_payload(payload: dict) -> None:
    WORKTREE_RECONCILIATION_REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = WORKTREE_RECONCILIATION_REPORT.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(WORKTREE_RECONCILIATION_REPORT)


def _write_worktree_reconciliation_started(target_ref: str) -> None:
    """Replace stale scheduler health before reconciliation can mutate state."""
    _write_worktree_reconciliation_payload(
        {
            "generated_at": _now_iso(),
            "status": "running",
            "target_ref": target_ref,
        }
    )


def _write_worktree_reconciliation_report(report: dict) -> None:
    """Persist a bounded scheduler health summary without source contents."""
    counts: dict[str, int] = {}
    for item in report.get("items", []):
        classification = str(item.get("classification") or "unknown")
        counts[classification] = counts.get(classification, 0) + 1
    unresolved_stale = sum(
        1
        for item in report.get("unresolved", [])
        if item.get("classification") != "recent_active"
    )
    summary = {
        "generated_at": _now_iso(),
        "status": "warning" if unresolved_stale else "ok",
        "target_ref": str(report.get("target_ref") or ""),
        "target_commit": str(report.get("target_commit") or ""),
        "inspected": len(report.get("items", [])),
        "deleted": len(report.get("deleted", [])),
        "unresolved": len(report.get("unresolved", [])),
        "unresolved_stale": unresolved_stale,
        "counts": counts,
    }
    _write_worktree_reconciliation_payload(summary)


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


def _worktree_pending_files(session: dict) -> list[str]:
    """Return files whose current state differs from the last deployed commit."""
    metadata = session.get("worktree")
    if not isinstance(metadata, dict) or not metadata.get("path"):
        return []
    worktree_path = str(metadata["path"])
    rc, stdout, stderr = _run_cmd(["git", "diff", "--name-only", "HEAD", "--"], cwd=worktree_path)
    if rc != 0:
        raise RuntimeError(f"Failed to inspect worktree dirtiness: {stderr}")
    candidates = {line.strip() for line in stdout.splitlines() if line.strip()}
    candidates.update(_worktree_untracked_files(metadata))
    candidates.update(_canonical_stored_repo_path(path) for path in session.get("modified_files") or [])
    if not candidates:
        return []
    merged_commit = str(metadata.get("merged_commit") or "")
    if not merged_commit:
        return sorted(candidates)
    files = sorted(candidates)
    current_states = _snapshot_file_states(Path(str(metadata["path"])), files)
    deployed_states = _snapshot_worktree_base_states(metadata, files)
    return [path for path in files if current_states.get(path) != deployed_states.get(path)]


def finalize_session_worktree(session_id: str, *, target_ref: str = "origin/dev", force: bool = False) -> None:
    """Remove a fully integrated worktree before deleting its session record."""
    def finalize(data: dict) -> str:
        session = data.get("sessions", {}).get(session_id)
        if not isinstance(session, dict):
            return "missing"
        metadata = session.get("worktree")
        if not isinstance(metadata, dict) or not metadata.get("path"):
            data.setdefault("sessions", {}).pop(session_id, None)
            return "removed"
        docker_lock = data.get("locks", {}).get("docker_rebuild", {})
        if _is_lock_active(docker_lock, "docker_rebuild") and docker_lock.get("claimed_by") == session_id:
            metadata["last_active"] = _now_iso()
            return "docker_busy"
        live_lease = any(
            isinstance(lease, dict) and lease.get("session_id") == session_id
            for lease in data.get("edit_leases", {}).values()
        )
        try:
            pending_files = _worktree_pending_files(session)
        except (OSError, RuntimeError):
            pending_files = ["<inspection-failed>"]
        merged_commit = str(metadata.get("merged_commit") or "")
        pristine_undeployed = (
            not merged_commit
            and not pending_files
            and _current_git_sha(Path(str(metadata["path"]))) == str(metadata.get("base_commit") or "")
        )
        integrated = (
            not session.get("writing")
            and not live_lease
            and (
                pristine_undeployed
                or (bool(merged_commit) and not pending_files and _git_is_ancestor(merged_commit, target_ref))
            )
        )
        if not integrated and force:
            data.setdefault("sessions", {}).pop(session_id, None)
            data["deploy_queue"] = [
                item for item in data.setdefault("deploy_queue", []) if item.get("session_id") != session_id
            ]
            return "force_removed"
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
    if result == "docker_busy":
        raise RuntimeError(f"Session {session_id} worktree is in use by a Docker restart")
    if result == "pending":
        raise RuntimeError(f"Session {session_id} worktree has residual or unintegrated changes")


def _managed_worktree_records() -> list[dict]:
    """Return lightweight managed worktree records without running source diffs."""
    data = _load_sessions()
    sessions = data.get("sessions", {})
    root = AGENT_WORKTREES_DIR.resolve(strict=False)
    by_path: dict[str, dict] = {}
    for session_id, session in sessions.items():
        if not isinstance(session, dict):
            continue
        metadata = session.get("worktree")
        if not isinstance(metadata, dict) or not metadata.get("path"):
            continue
        path = Path(str(metadata["path"])).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError:
            continue
        by_path[str(path)] = {
            "session_id": str(session_id),
            "session": session,
            "metadata": metadata,
        }

    paths: dict[str, dict] = {}
    for linked in _linked_git_worktrees():
        path = Path(str(linked.get("path") or "")).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError:
            continue
        paths[str(path)] = {**linked, "linked": True}
    if AGENT_WORKTREES_DIR.is_dir():
        for path in AGENT_WORKTREES_DIR.iterdir():
            if not path.is_dir():
                continue
            resolved = path.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            paths.setdefault(str(resolved), {"path": str(resolved), "linked": False})
    for path in by_path:
        paths.setdefault(path, {"path": path, "linked": False})

    records: list[dict] = []
    for path_text, linked in sorted(paths.items()):
        registered = by_path.get(path_text, {})
        metadata = registered.get("metadata") if isinstance(registered.get("metadata"), dict) else {}
        session = registered.get("session") if isinstance(registered.get("session"), dict) else {}
        path = Path(path_text)
        timestamp: float | None = None
        created_at = str(metadata.get("created_at") or session.get("started") or "")
        if created_at:
            try:
                timestamp = _parse_iso(created_at).timestamp()
            except (TypeError, ValueError):
                timestamp = None
        if timestamp is None and path.exists():
            # Unregistered recovery/orphan directories have no durable birth
            # timestamp, so filesystem age is the conservative fallback only.
            timestamp = path.stat().st_mtime
        records.append(
            {
                "session_id": str(registered.get("session_id") or _worktree_candidate_id(path_text, metadata)),
                "path": path_text,
                "path_timestamp": timestamp,
                "linked": bool(linked.get("linked") or linked.get("head")),
                "registered": bool(registered),
                "metadata": metadata,
                "session": session,
            }
        )
    return records


def _managed_worktree_age_hours(record: dict, now_timestamp: float) -> float:
    timestamp = record.get("path_timestamp")
    if not isinstance(timestamp, (int, float)):
        return 0
    return max(0.0, (now_timestamp - float(timestamp)) / 3600)


def _hard_expiry_record_is_live(record: dict, data: dict) -> bool:
    """Protect a currently executing or explicitly leased session from expiry."""
    session_id = str(record.get("session_id") or "")
    session = record.get("session") if isinstance(record.get("session"), dict) else {}
    if not session and session_id:
        current = data.get("sessions", {}).get(session_id)
        session = current if isinstance(current, dict) else {}
    if not session:
        return False
    if session.get("writing"):
        return True
    if any(
        isinstance(lease, dict) and str(lease.get("session_id") or "") == session_id
        for lease in data.get("edit_leases", {}).values()
    ):
        return True
    docker_lock = data.get("locks", {}).get("docker_rebuild", {})
    if _is_lock_active(docker_lock, "docker_rebuild") and str(docker_lock.get("claimed_by") or "") == session_id:
        return True
    return _auto_integration_presence_is_live(session)


def _hard_expiry_record_is_safely_disposable(record: dict) -> tuple[bool, str]:
    """Require proof that an aged worktree contains no unrecoverable work."""
    path = Path(str(record.get("path") or ""))
    if not path.exists():
        return True, "missing"
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    try:
        if _candidate_changed_files(path, metadata):
            return False, "unique_changes"
    except (OSError, RuntimeError, ValueError):
        return False, "inspection_failed"
    rc, head, _stderr = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(path))
    if rc != 0 or not head.strip():
        return False, "inspection_failed"
    session = record.get("session") if isinstance(record.get("session"), dict) else {}
    target_ref = f"{_session_repo_remote(session)}/{_session_repo_branch(session)}"
    if not _git_is_ancestor(head.strip(), target_ref):
        return False, "unmerged_head"
    return True, "reachable_clean_head"


def _remove_expired_worktree_with_container(path: Path) -> None:
    """Remove root-owned contents from one exact managed directory."""
    image = os.environ.get("OPENMATES_WORKTREE_CLEANUP_IMAGE", "openmates-core-api:latest")
    inspect_rc, _stdout, inspect_stderr = _run_cmd(["docker", "image", "inspect", image])
    if inspect_rc != 0:
        raise RuntimeError(f"cleanup image {image!r} is unavailable: {inspect_stderr or 'image inspect failed'}")
    cleanup_script = (
        "from pathlib import Path; import shutil; root=Path('/cleanup'); "
        "[(item.unlink() if item.is_symlink() or item.is_file() else shutil.rmtree(item)) "
        "for item in list(root.iterdir())]"
    )
    rc, _stdout, stderr = _run_cmd(
        [
            "docker", "run", "--rm", "--network", "none", "--pids-limit", "64",
            "--memory", "128m", "--cpus", "0.5",
            "--mount", f"type=bind,source={path},target=/cleanup",
            "--entrypoint", "python3", image, "-c", cleanup_script,
        ]
    )
    if rc != 0:
        raise RuntimeError(stderr or "container cleanup failed")
    path.rmdir()


def _remove_expired_worktree(record: dict) -> None:
    """Remove one exact expired path while refusing anything outside managed storage."""
    path = Path(str(record.get("path") or "")).resolve(strict=False)
    root = AGENT_WORKTREES_DIR.resolve(strict=False)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing expired worktree outside {root}: {path}") from exc
    if not relative.parts or path == root or path == CONTROL_PLANE_ROOT.resolve():
        raise RuntimeError(f"Refusing unsafe expired worktree path: {path}")
    if not path.exists():
        return
    rc, _stdout, stderr = _run_cmd(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc != 0 and path.exists():
        try:
            shutil.rmtree(path)
        except OSError as host_exc:
            try:
                _remove_expired_worktree_with_container(path)
            except (OSError, RuntimeError) as cleanup_exc:
                details = "; ".join(
                    item for item in (stderr.strip(), str(host_exc), str(cleanup_exc)) if item
                )
                raise RuntimeError(f"Failed to remove expired worktree {path}: {details}") from cleanup_exc
    if path.exists():
        raise RuntimeError(f"Expired worktree still exists after removal: {path}")


def expire_managed_worktrees(
    *,
    max_age_hours: int = WORKTREE_HARD_MAX_AGE_HOURS,
    now_timestamp: float | None = None,
) -> dict:
    """Unconditionally delete managed worktrees after the configured hard lifetime."""
    if max_age_hours < WORKTREE_HARD_MAX_AGE_HOURS:
        raise ValueError(
            f"max_age_hours below the configured hard lifetime ({WORKTREE_HARD_MAX_AGE_HOURS}) is not allowed"
        )
    current_timestamp = time.time() if now_timestamp is None else now_timestamp
    records = _managed_worktree_records()
    current_data = _load_sessions()
    live_session_ids = {
        str(record.get("session_id") or "")
        for record in records
        if _hard_expiry_record_is_live(record, current_data)
    }
    expired: list[dict] = []
    protected_unresolved: list[dict] = []
    for record in records:
        age_hours = _managed_worktree_age_hours(record, current_timestamp)
        session_id = str(record.get("session_id") or "")
        if age_hours < max_age_hours or session_id in live_session_ids:
            continue
        disposable, reason = _hard_expiry_record_is_safely_disposable(record)
        candidate = {**record, "age_hours": age_hours}
        if disposable:
            expired.append(candidate)
        else:
            protected_unresolved.append(
                {"session_id": session_id, "path": str(record.get("path") or ""), "reason": reason}
            )
    expired.sort(key=lambda item: len(Path(str(item["path"])).parts), reverse=True)
    retained = sorted(
        str(record["session_id"])
        for record in records
        if _managed_worktree_age_hours(record, current_timestamp) < max_age_hours
        or str(record.get("session_id") or "") in live_session_ids
    )
    deleted_records: list[dict] = []
    failures: list[dict] = []
    for record in expired:
        try:
            _remove_expired_worktree(record)
        except RuntimeError as exc:
            failures.append({"session_id": record["session_id"], "path": record["path"], "error": str(exc)})
            continue
        deleted_records.append(record)

    deleted_ids = sorted({str(record["session_id"]) for record in deleted_records})
    for session_id in deleted_ids:
        _delete_worktree_checkpoint_ref(session_id)
    deleted_paths = [Path(str(record["path"])).resolve(strict=False) for record in deleted_records]

    def store(data: dict) -> None:
        _prune_deletion_manifests(data)
        sessions = data.setdefault("sessions", {})
        manifests = data.setdefault("worktree_deletion_manifests", [])
        removed_session_ids: set[str] = set()
        for session_id, session in list(sessions.items()):
            metadata = session.get("worktree") if isinstance(session, dict) else None
            path_text = str(metadata.get("path") or "") if isinstance(metadata, dict) else ""
            if not path_text:
                continue
            session_path = Path(path_text).resolve(strict=False)
            if not any(session_path == deleted_path or session_path.is_relative_to(deleted_path) for deleted_path in deleted_paths):
                continue
            removed_session_ids.add(str(session_id))
            sessions.pop(session_id, None)
        removed_session_ids.update(deleted_ids)
        data["deploy_queue"] = [
            item for item in data.setdefault("deploy_queue", [])
            if str(item.get("session_id") or "") not in removed_session_ids
        ]
        data["edit_leases"] = {
            path: lease
            for path, lease in data.setdefault("edit_leases", {}).items()
            if str(lease.get("session_id") or "") not in removed_session_ids
        }
        for record in deleted_records:
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            session = record.get("session") if isinstance(record.get("session"), dict) else {}
            manifests.append(
                {
                    "session_id": str(record["session_id"]),
                    "worktree_name": Path(str(record["path"])).name,
                    "classification": "expired",
                    "reason": f"hard_max_age_{max_age_hours}h",
                    "reason_code": "hard_max_age",
                    "last_active": str(metadata.get("last_active") or session.get("last_active") or ""),
                    "changed_file_count": len(session.get("modified_files") or []),
                    "head": str(record.get("head") or ""),
                    "target_commit": str(metadata.get("merged_commit") or ""),
                    "deleted_at": _now_iso(),
                }
            )

    if deleted_records:
        _mutate_sessions(store)
        _run_cmd(["git", "worktree", "prune"], cwd=str(CONTROL_PLANE_ROOT))
    return {
        "max_age_hours": max_age_hours,
        "inspected": len(records),
        "deleted": deleted_ids,
        "retained": retained,
        "protected_live": sorted(
            str(record.get("session_id") or "")
            for record in records
            if str(record.get("session_id") or "") in live_session_ids
            and _managed_worktree_age_hours(record, current_timestamp) >= max_age_hours
        ),
        "protected_unresolved": protected_unresolved,
        "failures": failures,
    }


def _enforce_worktree_creation_capacity() -> None:
    """Clean expired worktrees, then refuse creation before disk or count exhaustion."""
    expire_managed_worktrees(max_age_hours=WORKTREE_HARD_MAX_AGE_HOURS)
    worktree_count = sum(1 for path in AGENT_WORKTREES_DIR.iterdir() if path.is_dir()) if AGENT_WORKTREES_DIR.is_dir() else 0
    usage = shutil.disk_usage(CONTROL_PLANE_ROOT)
    # free excludes reserved blocks, while used does not include them. Using
    # total-free double-counts reserved capacity and trips the 85% gate early.
    used_percent = (usage.used * 100 / usage.total) if usage.total else 100.0
    breaches: list[str] = []
    if worktree_count >= WORKTREE_MAX_COUNT:
        breaches.append(f"worktree count limit reached ({worktree_count}/{WORKTREE_MAX_COUNT})")
    if usage.free < WORKTREE_MIN_FREE_BYTES:
        breaches.append(
            f"free space below minimum ({usage.free / 1024**3:.1f} GiB < {WORKTREE_MIN_FREE_BYTES / 1024**3:.1f} GiB)"
        )
    if used_percent >= WORKTREE_MAX_DISK_PERCENT:
        breaches.append(f"filesystem use limit reached ({used_percent:.1f}% >= {WORKTREE_MAX_DISK_PERCENT}%)")
    if breaches:
        raise RuntimeError(
            "; ".join(breaches)
            + f". Run: python3 scripts/sessions.py worktree expire --max-age-hours {WORKTREE_HARD_MAX_AGE_HOURS}"
        )


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
    if lock_type == "vercel_deploy" or lock_type.endswith("_deploy"):
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
        if released_by and lock.get("claimed_by") and lock.get("claimed_by") != released_by:
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



def _get_dirty_files(*, checkout_root: Path | None = None) -> set[str]:
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
        cwd=str(checkout_root or CONTROL_PLANE_ROOT),
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
        ["git", "diff", "--name-only", "--cached", "--no-renames"],
        cwd=str(checkout_root or CONTROL_PLANE_ROOT),
    )
    if rc != 0 or not stdout:
        return set()
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _path_has_unstaged_diff(relative_path: str, *, checkout_root: Path | None = None) -> bool:
    """Return whether a selected path has staged, unstaged, or untracked changes."""
    rc, stdout, stderr = _run_cmd(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", relative_path],
        cwd=str(checkout_root or CONTROL_PLANE_ROOT),
    )
    if rc != 0:
        raise RuntimeError(f"Could not inspect deploy path status for {relative_path}: {stderr}")
    return bool(stdout.strip())


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
    missing_staged = sorted(
        relative_path
        for relative_path in to_commit - staged_files
        if _path_has_unstaged_diff(relative_path, checkout_root=checkout_root)
    )
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


def _get_recent_commits(count: int = RECENT_COMMITS_COUNT, *, checkout_root: Path | None = None) -> list[str]:
    """Return recent git commits as one-line summaries with relative timestamps."""
    rc, stdout, _ = _run_cmd([
        "git", "log", f"--max-count={count}",
        "--format=%h %ar %s",
        "--no-merges",
    ], cwd=str(checkout_root or CONTROL_PLANE_ROOT))
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


def _get_git_status_summary(*, checkout_root: Path | None = None) -> dict:
    """Return a compact git status summary for session start context."""
    result = {"branch": "unknown", "tracking": "", "uncommitted": [], "unpushed": 0}

    # Current branch
    cwd = str(checkout_root or CONTROL_PLANE_ROOT)
    rc, stdout, _ = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    if rc == 0:
        result["branch"] = stdout.strip()

    # Tracking status (ahead/behind)
    rc, stdout, _ = _run_cmd([
        "git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"
    ], cwd=cwd)
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
    rc, stdout, _ = _run_cmd(["git", "status", "--porcelain"], cwd=cwd)
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

    # Post pickup comment with current OpenCode-era resume guidance.
    post_comment(
        linear_issue_id,
        f"Picked up by OpenCode session `{sid}`\n\n"
        f"Resume from the OpenCode Web project sidebar or inspect the linked chat with\n"
        f"`python3 scripts/sessions.py chat read <opencode-session-id>`.",
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
    sessions[session_id].setdefault("opencode_top_level_session_id", opencode_session_id)


def session_for_opencode(data: dict, opencode_session_id: str, *, repo_id: str = "") -> tuple[str, dict] | None:
    """Return the one repository session already bound to an OpenCode chat."""
    sessions = data.get("sessions", {})
    matches = [
        (session_id, session)
        for session_id, session in sessions.items()
        if session.get("opencode_session_id") == opencode_session_id
        and (not repo_id or _session_repo_id(session) == repo_id)
    ]
    if not matches:
        matches = [
            (session_id, session)
            for session_id, session in sessions.items()
            if session.get("opencode_top_level_session_id") == opencode_session_id
            and (not repo_id or _session_repo_id(session) == repo_id)
        ]
    if len(matches) > 1:
        raise RuntimeError(f"OpenCode session {opencode_session_id} matches multiple repository sessions")
    return matches[0] if matches else None


def opencode_session_reusable_for_start(session: dict, task: str | None = None) -> bool:
    """Return whether `sessions.py start` may keep using this chat binding.

    A restart or same-task continuation must retain its existing worktree. Once
    work from a different task has been integrated or durably checkpointed,
    however, reusing that worktree mixes historical residue into the new task.
    """
    incoming_task = str(task or "").strip()
    current_task = str(session.get("task") or "").strip()
    if not incoming_task or not current_task or incoming_task == current_task:
        return True

    worktree = session.get("worktree") or {}
    integration = worktree.get("integration") or {}
    auto_integration = session.get("auto_integration") or {}
    work_is_preserved = (
        integration.get("status") == "merged"
        or bool(session.get("merged_commit"))
        or bool(auto_integration.get("checkpoint_ref"))
    )
    return not work_is_preserved


def rotate_opencode_session_binding(
    data: dict,
    session_id: str,
    opencode_session_id: str,
    *,
    now: str | None = None,
) -> None:
    """Retire one preserved repo-session binding before creating its successor."""
    session = data.get("sessions", {}).get(session_id)
    if not isinstance(session, dict):
        raise RuntimeError(f"Cannot rotate unknown repository session {session_id}")
    if opencode_session_id not in {
        session.get("opencode_session_id"),
        session.get("opencode_top_level_session_id"),
    }:
        raise RuntimeError(
            f"Repository session {session_id} is no longer bound to {opencode_session_id}"
        )
    session["opencode_session_id"] = None
    session["opencode_top_level_session_id"] = None
    session["rotated_opencode_session_id"] = opencode_session_id
    session["rotated_at"] = now or _now_iso()


def refresh_existing_session_for_start(
    data: dict,
    session_id: str,
    opencode_session_id: str,
    *,
    mode: str,
    tags: list[str],
    task: str | None,
    repo_kind: str,
    now: str | None = None,
) -> dict:
    """Refresh an existing session and restore its authoritative chat binding."""
    current = session_for_opencode(data, opencode_session_id)
    if current is None or current[0] != session_id:
        current_id = current[0] if current else "none"
        raise RuntimeError(
            f"OpenCode session {opencode_session_id} binding changed while starting "
            f"(selected {session_id}, current {current_id}); run sessions.py start again"
        )
    session = data["sessions"][session_id]
    bind_opencode_session(data, session_id, opencode_session_id)
    session["last_active"] = now or _now_iso()
    session["mode"] = mode
    session["tags"] = tags
    session["binding_mode"] = "pending" if repo_kind == "control_plane" else "repo_routed"
    session["auto_integration_policy"] = "enabled" if repo_kind == "control_plane" else "disabled"
    if task:
        session["task"] = task
    return data


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
        if not _session_is_control_plane_repo(session):
            checkout_root = _session_checkout_root(session)
            session["binding_mode"] = "repo_routed"
            session["binding_updated_at"] = _now_iso()
            session["binding_failure_reason"] = ""
            session["last_active"] = _now_iso()
            return {
                "session_id": session_id,
                "mode": "repo_routed",
                "worktree_path": str(checkout_root),
                "repo": _session_repo_name(session),
            }
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


def refresh_worktree_base_after_fast_forward(worktree: dict) -> str:
    """Align deploy metadata after a managed worktree is safely fast-forwarded."""
    worktree_path = str(worktree.get("path") or "")
    recorded_base = str(worktree.get("base_commit") or "")
    recorded_merged = str(worktree.get("merged_commit") or "")
    if not worktree_path or not recorded_base:
        return ""
    current_head = _current_git_sha(Path(worktree_path))
    if not current_head:
        return ""
    if current_head == recorded_base and (not recorded_merged or recorded_merged == current_head):
        return ""
    rc, upstream_head, stderr = _run_cmd(
        ["git", "rev-parse", "refs/remotes/origin/dev"],
        cwd=worktree_path,
    )
    if rc != 0:
        raise RuntimeError(
            "Reason: origin/dev could not be resolved while validating the managed worktree. "
            f"Next: preserve the worktree and inspect its commits before repair. {stderr}".strip()
        )
    rc, _stdout, stderr = _run_cmd(
        ["git", "merge-base", "--is-ancestor", current_head, upstream_head.strip()],
        cwd=worktree_path,
    )
    if rc != 0:
        raise RuntimeError(
            "Reason: managed worktree HEAD is not integrated in origin/dev. "
            f"Next: preserve the worktree and inspect its commits before repair. {stderr}".strip()
        )
    rc, _stdout, stderr = _run_cmd(
        ["git", "merge-base", "--is-ancestor", recorded_base, current_head],
        cwd=worktree_path,
    )
    if rc != 0:
        raise RuntimeError(
            "Reason: managed worktree HEAD diverged from its recorded base. "
            f"Next: preserve the worktree and inspect both commits before repair. {stderr}".strip()
        )
    if recorded_merged and recorded_merged != current_head:
        rc, _stdout, stderr = _run_cmd(
            ["git", "merge-base", "--is-ancestor", recorded_merged, current_head],
            cwd=worktree_path,
        )
        if rc != 0:
            raise RuntimeError(
                "Reason: managed worktree deployed baseline diverged from origin/dev. "
                f"Next: preserve the worktree and inspect both commits before repair. {stderr}".strip()
            )
        worktree["merged_commit"] = current_head
    worktree["base_commit"] = current_head
    return recorded_base if recorded_base != current_head else ""


def refresh_session_worktree_base(session_id: str) -> dict[str, str]:
    """Refresh one session's recorded base after a safe worktree fast-forward."""
    def update(data: dict) -> dict[str, str]:
        resolved_session_id = _resolve_session_id(data, session_id=session_id)
        session = data["sessions"][resolved_session_id]
        worktree = session.get("worktree") if isinstance(session.get("worktree"), dict) else {}
        previous_base = refresh_worktree_base_after_fast_forward(worktree)
        if worktree.get("path") and _existing_direct_managed_worktree(worktree.get("path")):
            session["binding_mode"] = "worktree_routed"
            session["binding_updated_at"] = _now_iso()
            session["binding_failure_reason"] = ""
        if previous_base or session.get("binding_mode") == "worktree_routed":
            session["last_active"] = _now_iso()
            worktree["last_active"] = session["last_active"]
        return {
            "session_id": resolved_session_id,
            "previous_base": previous_base,
            "base_commit": str(worktree.get("base_commit") or ""),
            "binding_mode": str(session.get("binding_mode") or ""),
            "worktree_path": str(worktree.get("path") or ""),
        }

    return _mutate_sessions(update)


def repair_worktree_routing(opencode_session_id: str) -> dict:
    """Reconstruct durable tool routing without depending on OpenCode runtime state."""
    recreated = False
    initial = _mutate_sessions(lambda data: data)
    initial_session_id = _resolve_session_id(initial, opencode_session_id=opencode_session_id)
    initial_session = initial["sessions"][initial_session_id]
    initial_worktree = initial_session.get("worktree") or {}
    initial_path = Path(str(initial_worktree.get("path") or ""))
    integration = initial_worktree.get("integration") if isinstance(initial_worktree.get("integration"), dict) else {}
    if initial_path and not _existing_direct_managed_worktree(initial_path) and integration.get("status") == "merged":
        rc, target_commit, stderr = _run_cmd(["git", "rev-parse", "refs/remotes/origin/dev"])
        if rc != 0:
            raise RuntimeError(f"Could not resolve origin/dev while repairing {initial_session_id}: {stderr}")
        recovery_path = initial_path.with_name(
            f"{initial_path.name}.recovery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        if initial_path.exists():
            initial_path.rename(recovery_path)
        _run_cmd(["git", "worktree", "prune"])
        rc, _stdout, stderr = _run_cmd(["git", "worktree", "add", str(initial_path), target_commit])
        if rc != 0:
            if recovery_path.exists() and not initial_path.exists():
                recovery_path.rename(initial_path)
            raise RuntimeError(f"Failed to recreate merged session worktree {initial_session_id}: {stderr}")

        def record_recovery(data: dict) -> None:
            recovered = data["sessions"][initial_session_id]["worktree"]
            recovered["base_commit"] = target_commit
            recovered["status"] = "active"
            recovered["recovered_from"] = str(recovery_path) if recovery_path.exists() else ""
            recovered["recovered_at"] = _now_iso()

        _mutate_sessions(record_recovery)
        recreated = True

    def update(data: dict) -> dict:
        session_id = _resolve_session_id(data, opencode_session_id=opencode_session_id)
        session = data["sessions"][session_id]
        worktree = session.get("worktree") or {}
        worktree_path = str(worktree.get("path") or "")
        if (
            worktree.get("status") not in {"active", "changes_pending", "merged"}
            or not worktree_path
            or not _existing_direct_managed_worktree(worktree_path)
        ):
            raise RuntimeError(
                f"Reason: session {session_id} has no active worktree to route tools into. "
                f"Next: run python3 scripts/sessions.py worktree ensure --session {session_id}."
            )
        shared_runtime_resources = link_shared_worktree_resources(worktree_path)
        refresh_worktree_base_after_fast_forward(worktree)
        session["binding_mode"] = "worktree_routed"
        session["binding_updated_at"] = _now_iso()
        session["binding_failure_reason"] = ""
        session["last_active"] = _now_iso()
        if worktree.get("status") in {"changes_pending", "merged"}:
            worktree["status"] = "active"
        if recreated:
            session["workspace_state"] = "clean"
            session.pop("auto_integration", None)
        worktree["last_active"] = session["last_active"]
        return {
            "session_id": session_id,
            "mode": "worktree_routed",
            "worktree_path": worktree_path,
            "shared_runtime_resources": shared_runtime_resources,
        }

    return _mutate_sessions(update)


def register_session_record(
    session_record: dict,
    opencode_session_id: str | None = None,
    replace_session_id: str | None = None,
) -> tuple[str, list[str], list[str], dict, bool]:
    """Atomically register one repo session and its authoritative OpenCode chat."""
    def register(data: dict) -> tuple[str, list[str], list[str], dict, bool]:
        pruned = _prune_stale(data)
        cleared_locks = _prune_stale_locks(data)
        _prune_checkpoint_lock_files(data)
        if opencode_session_id and replace_session_id:
            rotate_opencode_session_binding(data, replace_session_id, opencode_session_id)
        if opencode_session_id:
            existing = session_for_opencode(
                data,
                opencode_session_id,
                repo_id=str(session_record.get("repo_id") or ""),
            )
            if existing:
                existing_id, existing_session = existing
                bind_opencode_session(data, existing_id, opencode_session_id)
                existing_session["last_active"] = _now_iso()
                return existing_id, pruned, cleared_locks, data, False
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
        return session_id, pruned, cleared_locks, data, True

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
    try:
        repo = _repo_metadata(_resolve_repo_id(getattr(args, "repo", None)))
        _validate_session_repo(repo)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

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
    existing = session_for_opencode(
        _load_sessions(),
        opencode_session_id,
        repo_id=repo["repo_id"],
    ) if opencode_session_id else None
    replace_session_id: str | None = None
    if existing and not opencode_session_reusable_for_start(existing[1], args.task):
        replace_session_id = existing[0]
        existing = None
    if existing and _session_repo_id(existing[1]) != repo["repo_id"]:
        existing = None
    is_new_session = existing is None
    if existing:
        sid, _existing_session = existing

        def refresh_existing(data: dict) -> dict:
            return refresh_existing_session_for_start(
                data,
                sid,
                opencode_session_id,
                mode=mode,
                tags=tags,
                task=args.task,
                repo_kind=repo["repo_kind"],
            )

        data = _mutate_sessions(refresh_existing)
        pruned: list[str] = []
        cleared_locks: list[str] = []
    else:
        session_record: dict = {
            **repo,
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
            "opencode_top_level_session_id": opencode_session_id,
            "binding_mode": (
                "repo_routed"
                if opencode_session_id and mode != "question" and repo["repo_kind"] != "control_plane"
                else ("pending" if opencode_session_id and mode != "question" else "legacy_grandfathered")
            ),
            "auto_integration_policy": "enabled" if opencode_session_id and mode != "question" and repo["repo_kind"] == "control_plane" else "disabled",
        }
        sid, pruned, cleared_locks, data, registered_new = register_session_record(
            session_record,
            opencode_session_id,
            replace_session_id,
        )
        is_new_session = registered_new
    worktree_metadata: dict | None = None
    worktree_error = ""
    if mode != "question" and repo["repo_kind"] == "control_plane":
        try:
            worktree_metadata = ensure_session_worktree(sid)
            data = _load_sessions()
            if opencode_session_id:
                repair_worktree_routing(opencode_session_id)
                data = _load_sessions()
        except (RuntimeError, OSError, ValueError) as exc:
            worktree_error = str(exc)
    elif mode != "question":
        data = _load_sessions()

    # Link task file to this session if --task-id was given
    if linked_task and is_new_session:
        linked_task["session"] = sid
        _save_task(linked_task)

    # ── Linear integration ────────────────────────────────────────────────
    linear_issue_id = getattr(args, "linear_issue", None)
    if is_new_session:
        _linear_start_integration(sid, data, mode, args.task, linear_issue_id)

    # ── OpenCode integration ──────────────────────────────────────────────
    # Start records the current chat/worktree binding only. Parallel workers are
    # now persisted OpenCode Web chats, not additional Zellij terminal sessions.

    # ===================================================================
    # Output context for the active agent (mode-aware, structured with box sections)
    # ===================================================================

    # ── Warn if workflow scripts themselves are modified but untracked ─────
    session_checkout_root = _session_checkout_root(data["sessions"].get(sid, {}))
    dirty_set = _get_dirty_files(checkout_root=session_checkout_root)
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
    git_status = _get_git_status_summary(checkout_root=session_checkout_root)
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
    if repo["repo_kind"] != "control_plane":
        header_lines.append(f"  Repo:  {repo['repo_name']} ({repo['repo_branch']})")
    if linear_linked:
        header_lines.append(f"  Linear: {linear_linked}")
    zellij_name = data["sessions"][sid].get("zellij_session")
    if zellij_name:
        header_lines.append(f"  Zellij: `zellij attach {zellij_name}` | http://localhost:8082")
    if worktree_metadata:
        header_lines.append(f"  Worktree: {worktree_metadata.get('path')}")
    elif worktree_error:
        header_lines.append(f"  Worktree: creation failed ({worktree_error})")
    elif repo["repo_kind"] != "control_plane":
        header_lines.append(f"  Checkout: {repo['repo_root']}")

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
        recent_commits = _get_recent_commits(count=commit_limit, checkout_root=session_checkout_root)
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
    if opencode_session_id:
        attachment_lines = _opencode_attachment_hint_lines(opencode_session_id)
        if attachment_lines:
            sections.append(_box_section("OPENCODE ATTACHMENTS", attachment_lines))

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

    # ── Current coordination state ────────────────────────────────────────
    try:
        presence = _opencode_presence_store().snapshot()
    except PresenceStoreError as error:
        presence = {"sessions": {}, "task_claims": {}, "diagnostics": [{"code": "unavailable_store", "message": str(error)}]}
    coordination_view = presence_status_view(data, presence)
    print()
    print(_format_coordination_section(sid, data, coordination_view))

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
        dirty_files = _get_dirty_files(checkout_root=_session_checkout_root(session))
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
        related = _find_related_docs(modified) if _session_is_control_plane_repo(session) else []
        if related:
            print("== ARCHITECTURE DOCS TO VERIFY ==")
            print(
                "You modified files related to these docs — "
                "verify they are still accurate:"
            )
            for doc in related:
                print(f"  - docs/architecture/{doc}")
            print()

    if not getattr(args, "force", False) and _session_is_control_plane_repo(session):
        _enforce_visual_smoke_end_gate(
            sid,
            session,
            modified,
            skip_reason=getattr(args, "skip_visual_smoke_reason", None),
        )
        _enforce_proof_video_end_gate(sid, session, modified)

    worktree_backed = isinstance(session.get("worktree"), dict)
    if worktree_backed:
        try:
            finalize_session_worktree(sid, force=getattr(args, "force", False))
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
            _prune_checkpoint_lock_files(current)
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


def _command_invokes_openmates_cli(argv: list[str]) -> bool:
    """Return true only when a proof command visibly executes OpenMates CLI."""

    tokens = [str(token) for token in argv if str(token).strip()]
    if not tokens:
        return False
    executable = Path(tokens[0]).name
    if executable in OPENMATES_CLI_PROOF_EXECUTABLES:
        return True
    token_names = {Path(token).name for token in tokens}
    if token_names & OPENMATES_CLI_PROOF_EXECUTABLES:
        return True
    joined = " ".join(tokens)
    if any(marker in joined for marker in OPENMATES_CLI_PROOF_SOURCE_MARKERS):
        return any(name in {"cli.ts", "cli.js", "openmates", "openmates-cli"} for name in token_names)
    return False


def _publish_proof_media_to_opencode_response(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Upload reviewed proof media for final OpenCode response embedding."""
    from spec_demo import require_review_receipt_integrity, resolve_run_artifact_path

    privacy_status = manifest.get("privacy", {}).get("status")
    if privacy_status not in PROOF_VIDEO_PRIVACY_ACCEPTED_STATUSES or manifest.get("review", {}).get("status") != "passed":
        raise RuntimeError("OpenCode response-media publication requires finalized proof privacy state and frame review")
    try:
        require_review_receipt_integrity(run_dir, manifest)
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    audio_status = manifest.get("narration_audio", {}).get("status")
    if audio_status not in {"passed", "not_required"}:
        raise RuntimeError("OpenCode response-media publication requires passed or intentionally disabled narration audio")
    if audio_status == "passed" and manifest.get("video_metadata", {}).get("has_audio") is not True:
        raise RuntimeError("OpenCode response-media publication requires the requested narration audio track")

    video_path = resolve_run_artifact_path(run_dir, str(manifest.get("video_path") or ""))
    if not video_path.is_file():
        raise RuntimeError("Reviewed proof video does not exist")

    alt = f"OpenMates proof video {manifest.get('spec_id', 'session-proof')}"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "opencode_response_media.py"),
        str(video_path),
    ]
    caption_artifact = manifest.get("caption_artifact") if isinstance(manifest.get("caption_artifact"), dict) else {}
    captions_value = str(caption_artifact.get("path") or "")
    if captions_value:
        captions_path = resolve_run_artifact_path(run_dir, captions_value)
        command.extend([
            "--captions",
            str(captions_path),
            "--captions-language",
            str(caption_artifact.get("language") or "und"),
            "--captions-label",
            str(caption_artifact.get("label") or "Captions"),
        ])
    command.extend(["--alt", alt, "--output", "json"])
    upload = subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
    if upload.returncode != 0:
        raise RuntimeError(upload.stderr.strip() or upload.stdout.strip() or "response-media upload failed")
    try:
        result = json.loads(upload.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"response-media upload returned invalid JSON: {exc}") from exc
    snippets = result.get("snippets") if isinstance(result, dict) else None
    if not isinstance(snippets, dict) or not snippets.get("html"):
        raise RuntimeError("response-media upload did not return an embeddable HTML snippet")
    snippet_html = str(snippets.get("html", ""))
    returned_video_url = str(result.get("url") or "")
    if (
        result.get("sha256") != (manifest.get("video_metadata") or {}).get("sha256")
        or not returned_video_url
        or html.escape(returned_video_url, quote=True) not in snippet_html
    ):
        raise RuntimeError("response-media upload did not return the reviewed video source")
    if int(manifest.get("schema_version") or 1) >= 2:
        returned_captions = result.get("captions") if isinstance(result.get("captions"), dict) else {}
        expected_caption_hash = str(caption_artifact.get("sha256") or "")
        returned_caption_url = str(returned_captions.get("url") or "")
        if (
            returned_captions.get("sha256") != expected_caption_hash
            or not returned_caption_url
            or html.escape(returned_caption_url, quote=True) not in snippet_html
            or "<track kind=\"captions\"" not in snippet_html
        ):
            raise RuntimeError("response-media upload did not return the reviewed caption track")

    publication = manifest.setdefault("publication", {})
    if not isinstance(publication, dict):
        raise RuntimeError("Manifest publication record must be a mapping")
    publication.update(
        {
            "status": "delivered",
            "delivery_kind": "opencode_response_media",
            "delivered_at": _now_iso(),
            "expires_in": result.get("expires_in"),
            "s3_key": result.get("key"),
            "snippet_html": snippets.get("html"),
            "snippet_markdown": snippets.get("markdown"),
            "url": result.get("url"),
            "captions": result.get("captions", {}),
        }
    )
    publication.pop("failure_reason", None)
    publication.pop("next_retry_at", None)
    (run_dir / "publication.json").write_text(
        json.dumps(publication, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _proof_video_blocker_media_record(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Return response-ready media metadata when a proof-video record is blocked."""

    try:
        from scripts.proof_video_workflow import proof_blocker_media
    except ModuleNotFoundError:
        from proof_video_workflow import proof_blocker_media

    review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
    review_status = str(review.get("status") or "pending")
    return proof_blocker_media(run_dir, manifest, review_status)


def cmd_proof_video(args: argparse.Namespace) -> None:
    """Produce, review, or publish narrated CLI and Playwright proof videos."""
    from spec_demo import (
        DemonstrationError,
        produce_cli_demonstration,
        produce_playwright_demonstration,
    )
    data = _load_sessions()
    session = data.get("sessions", {}).get(args.session)
    if session is None:
        raise DemonstrationError(f"Session {args.session} not found")
    if args.proof_action == "produce":
        command_argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
        if not command_argv:
            raise DemonstrationError("proof-video produce requires an explicit command after --")
        if not _command_invokes_openmates_cli(command_argv):
            raise DemonstrationError(
                "CLI proof videos are only allowed when the command visibly executes the OpenMates CLI. "
                "Use deployed Playwright, Apple, or ordinary test evidence for generic scripts and smoke helpers."
            )
        run_dir = args.run_dir or (
            PROJECT_ROOT / "test-results" / "proof-videos" / args.session / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        subject_commit = args.subject_commit or _current_git_sha(Path.cwd())
        result = produce_cli_demonstration(
            run_dir=run_dir,
            argv=command_argv,
            spec_id=args.proof_id,
            subject_commit=subject_commit,
            run_id=args.run_id or f"proof-{args.session}-{int(time.time())}",
            target_environment=args.target_environment,
            test_account_provenance=args.test_account_provenance,
            narration_id=args.narration_id,
            caption_text=args.caption,
            expected_proof=args.expected_proof,
            acceptance_criteria=args.acceptance_criterion,
            narration_audio_path=args.audio_path,
            narration_audio_provider=args.audio_provider,
            narration_audio_model=args.audio_model,
            narration_audio_voice=args.audio_voice,
            narration_audio_reused_from=args.audio_reused_from,
            timeout_seconds=getattr(args, "timeout_seconds", 120.0),
        )
        record = _upsert_proof_video_record(session, run_dir, result)
        _save_sessions(data)
        print(json.dumps({"status": "review_ready", "run_dir": str(run_dir), "privacy": result["privacy"]}, sort_keys=True))
        if record.get("problems"):
            print(json.dumps({"proof_video_pending": record["problems"]}, sort_keys=True))
        return
    if args.proof_action == "produce-playwright":
        try:
            from scripts.proof_video_workflow import (
                WorkflowError,
                approved_render_claims,
                record_contract_authorization,
                require_recorded_approval,
                resolve_deployed_run,
            )
        except ModuleNotFoundError:
            from proof_video_workflow import (
                WorkflowError,
                approved_render_claims,
                record_contract_authorization,
                require_recorded_approval,
                resolve_deployed_run,
            )
        try:
            record_contract_authorization(
                session_id=args.session,
                spec_name=args.spec_name,
                contract_path=args.contract_path,
            )
            approved_contract = require_recorded_approval(session_id=args.session, spec_name=args.spec_name, contract_path=args.contract_path)
            approved_claims = approved_render_claims(approved_contract, device_profile=args.device_profile)
            deployed_run = resolve_deployed_run(
                subject_commit=args.subject_commit,
                spec_name=args.spec_name,
                run_id=args.run_id,
                source_video=args.source_video,
            )
        except WorkflowError as exc:
            raise DemonstrationError(str(exc)) from exc
        persisted_artifact = str(deployed_run.get("artifact_path") or "")
        if not persisted_artifact or Path(persisted_artifact).resolve() != args.source_video.resolve():
            raise DemonstrationError("Playwright source video does not match the persisted deployed run artifact")
        run_dir = args.run_dir or (
            PROJECT_ROOT / "test-results" / "proof-videos" / args.session / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        source = {
            "source": str(deployed_run.get("source") or "scripts_tests"),
            "status": "passed",
            "command_or_spec": args.spec_name,
            "target": str(deployed_run.get("target") or args.target_environment),
            "deployment_reference": str(deployed_run.get("deployment_reference") or args.subject_commit),
            "run_id": args.run_id,
            "subject_commit": args.subject_commit,
            "artifact_path": str(args.source_video),
            "artifact_sha256": str(deployed_run.get("artifact_sha256") or ""),
            "test_account_provenance": args.test_account_provenance,
        }
        for timestamp_field in ("action_timestamps", "state_change_timestamps"):
            timestamps = deployed_run.get(timestamp_field)
            if isinstance(timestamps, list):
                source[timestamp_field] = timestamps
        state_change_timestamps_by_id = deployed_run.get("state_change_timestamps_by_id")
        if isinstance(state_change_timestamps_by_id, dict):
            source["state_change_timestamps_by_id"] = state_change_timestamps_by_id
        source_end_timestamp_seconds = getattr(args, "source_end_timestamp_seconds", None)
        if source_end_timestamp_seconds is None:
            source_end_timestamp_seconds = deployed_run.get("source_end_timestamp_seconds")
        if source_end_timestamp_seconds is not None:
            source["source_end_timestamp_seconds"] = float(source_end_timestamp_seconds)
        result = produce_playwright_demonstration(
            run_dir=run_dir,
            source_video=args.source_video,
            source=source,
            spec_id=args.proof_id,
            subject_commit=args.subject_commit,
            narration_id=args.narration_id,
            caption_text=approved_claims["caption_text"],
            expected_proof=approved_claims["expected_proof"],
            acceptance_criteria=approved_claims["acceptance_criteria"],
            proof_assertions=approved_claims["assertions"],
            proof_contract_hash=approved_claims["contract_hash"],
            proof_group_id="sha256:"
            + hashlib.sha256(
                f"{args.spec_name}\0{approved_claims['contract_hash']}".encode("utf-8")
            ).hexdigest(),
            narration_audio_path=args.audio_path,
            narration_audio_provider=args.audio_provider,
            narration_audio_model=args.audio_model,
            narration_audio_voice=args.audio_voice,
            narration_audio_reused_from=args.audio_reused_from,
            device_profile_name=args.device_profile,
            playback_rate=args.playback_rate,
            hold_last_frame_seconds=args.hold_last_frame_seconds,
            ready_timestamp_seconds=getattr(args, "ready_timestamp_seconds", None),
            demo_audio_path=args.demo_audio_path,
        )
        record = _upsert_proof_video_record(session, run_dir, result)
        _save_sessions(data)
        print(json.dumps({"status": "review_ready", "run_dir": str(run_dir), "privacy": result["privacy"]}, sort_keys=True))
        if record.get("problems"):
            print(json.dumps({"proof_video_pending": record["problems"]}, sort_keys=True))
        return
    run_dir = args.run_dir
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    try:
        result = _publish_proof_media_to_opencode_response(run_dir, manifest)
    except RuntimeError as exc:
        raise DemonstrationError(str(exc)) from exc
    _upsert_proof_video_record(session, run_dir, result)
    _save_sessions(data)
    publication = result["publication"]
    print(
        json.dumps(
            {
                "status": publication["status"],
                "delivery_kind": publication.get("delivery_kind"),
                "run_dir": str(run_dir),
                "snippet_html": publication.get("snippet_html"),
                "snippet_markdown": publication.get("snippet_markdown"),
            },
            sort_keys=True,
        )
    )


def _opencode_presence_store() -> PresenceStore:
    return PresenceStore(
        OPENCODE_PRESENCE_STATE_FILE,
        lock_path=OPENCODE_PRESENCE_LOCK_FILE,
        project_root=CONTROL_PLANE_ROOT,
    )


def _presence_identity_item(
    session_id: str,
    record: dict,
    durable_sessions: dict,
    child_roles: dict,
) -> dict:
    repository_session_id = ""
    durable = {}
    for candidate_id, candidate in durable_sessions.items():
        if candidate.get("opencode_session_id") == session_id:
            repository_session_id = candidate_id
            durable = candidate
            break
    marker = child_roles.get(session_id, {}) if isinstance(child_roles, dict) else {}
    parent_id = marker.get("parent_id") or record.get("parent_id", "")
    return {
        "opencode_session_id": session_id,
        "repository_session_id": repository_session_id,
        "parent_id": parent_id,
        "top_level_session_id": record.get("top_level_session_id") or parent_id or session_id,
        "child_role": marker.get("role") or record.get("child_role", "unknown"),
        "execution": record.get("execution", "unknown"),
        "attention": record.get("attention", "none"),
        "turn": record.get("turn", "none"),
        "task": durable.get("task", ""),
        "worktree": durable.get("worktree", {}),
        "workspace_state": durable.get("workspace_state", "unknown"),
        "auto_integration": durable.get("auto_integration", {}),
        "resource_wait": durable.get("resource_wait", {}),
        "paths": record.get("paths", []),
        "updated_at": record.get("updated_at", ""),
    }


def presence_status_view(
    durable: dict,
    presence: dict,
    *,
    include_all: bool = False,
    conflicts_only: bool = False,
    session_filter: str = "",
) -> dict:
    """Project durable identities onto current ephemeral OpenCode state."""
    durable_sessions = durable.get("sessions", {})
    child_roles = presence.get("child_roles", {})
    items = {
        session_id: _presence_identity_item(session_id, record, durable_sessions, child_roles)
        for session_id, record in presence.get("sessions", {}).items()
        if isinstance(record, dict)
    }
    view = {
        "working": [],
        "waiting_for_resource": [],
        "waiting_for_user": [],
        "idle_after_response": [],
        "stopped_or_failed": [],
        "conflicts": [],
        "diagnostics": presence.get("diagnostics", []),
    }
    infrastructure = durable.get("infrastructure", {}) if isinstance(durable.get("infrastructure"), dict) else {}
    docker_operations = list(infrastructure.get("docker_operations") or [])
    persistent_docker_operations = _list_persistent_docker_operations()
    if persistent_docker_operations:
        docker_operations = persistent_docker_operations
    active_docker_operation = _active_docker_operation_from_list(docker_operations)
    view["infrastructure"] = {
        "active_docker_operation": active_docker_operation,
        "test_leases": list((infrastructure.get("test_leases") or {}).values()),
        "recent_docker_operations": [
            operation for operation in docker_operations
            if isinstance(operation, dict) and operation.get("status") in DOCKER_OPERATION_TERMINAL_STATUSES
        ][-DOCKER_OPERATION_HISTORY_LIMIT:],
    }
    for item in items.values():
        resource_wait = item.get("resource_wait") if isinstance(item.get("resource_wait"), dict) else {}
        resource_wait_live = (
            resource_wait.get("status") == "waiting"
            and resource_wait.get("heartbeat_at")
            and _minutes_since(resource_wait["heartbeat_at"]) <= 3
        )
        if resource_wait_live:
            view["waiting_for_resource"].append(item)
        elif item["attention"].startswith("required_"):
            view["waiting_for_user"].append(item)
        elif item["execution"] in {"busy", "retrying"}:
            view["working"].append(item)
        elif item["execution"] == "idle" and item["turn"] == "completed":
            view["idle_after_response"].append(item)
        elif item["execution"] in {"stopped", "error"}:
            view["stopped_or_failed"].append(item)
    for section in ("working", "waiting_for_resource", "waiting_for_user", "idle_after_response", "stopped_or_failed"):
        view[section].sort(key=lambda item: item["opencode_session_id"])

    for path, lease in sorted(durable.get("edit_leases", {}).items()):
        owner = durable_sessions.get(lease.get("session_id", ""), {}) if isinstance(lease, dict) else {}
        owner_id = owner.get("opencode_session_id", "")
        if owner_id and items.get(owner_id, {}).get("execution") in {"busy", "retrying"}:
            view["conflicts"].append({"type": "edit_lease", "path": path, "owner_session_id": lease.get("session_id"), "opencode_session_id": owner_id})
    for key, claims in sorted(presence.get("task_claims", {}).items()):
        implementations = [claim for claim in claims if claim.get("role") == "implementation"]
        if implementations:
            view["conflicts"].append({"type": "task_claim", "key": key, "claims": implementations})

    if include_all:
        view["all"] = [
            {
                "repository_session_id": repository_session_id,
                "opencode_session_id": info.get("opencode_session_id", ""),
                "task": info.get("task", ""),
                "worktree": info.get("worktree", {}),
            }
            for repository_session_id, info in sorted(durable_sessions.items())
        ]
    if session_filter:
        selected_repository_id = session_filter if session_filter in durable_sessions else ""
        selected_open_code_id = ""
        if selected_repository_id:
            selected_open_code_id = durable_sessions[selected_repository_id].get("opencode_session_id", "")
        elif session_filter in items:
            selected_open_code_id = session_filter
            selected_repository_id = items[session_filter].get("repository_session_id", "")
        selected = items.get(selected_open_code_id)
        if selected is None and selected_repository_id:
            info = durable_sessions[selected_repository_id]
            selected = {
                "repository_session_id": selected_repository_id,
                "opencode_session_id": info.get("opencode_session_id", ""),
                "task": info.get("task", ""),
                "worktree": info.get("worktree", {}),
            }
        if selected is not None:
            selected = {**selected, "children": [item for item in items.values() if item.get("parent_id") == selected.get("opencode_session_id")]}
        view["session"] = selected
    if conflicts_only:
        return {"conflicts": view["conflicts"], "diagnostics": view["diagnostics"]}
    return view


def _safe_hours_since(iso_str: str) -> float | None:
    if not iso_str:
        return None
    try:
        return _hours_since(iso_str)
    except (TypeError, ValueError):
        return None


def _session_open_reference(item: dict[str, Any]) -> str:
    return str(item.get("repository_session_id") or item.get("opencode_session_id") or "")


def _session_display_task(item: dict[str, Any], titles: dict[str, str]) -> str:
    opencode_session_id = str(item.get("opencode_session_id") or "")
    return str(item.get("task") or titles.get(opencode_session_id) or "(untitled)")


def _sort_presence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def _append_presence_section(
    lines: list[str],
    title: str,
    items: list[dict[str, Any]],
    titles: dict[str, str],
    *,
    show_activity: bool = False,
    limit: int = COORDINATION_SESSION_LIMIT,
) -> None:
    lines.append(f"{title} ({len(items)}):")
    if not items:
        lines.append("  none")
        return
    visible = items[:limit]
    for item in visible:
        repository_session_id = str(item.get("repository_session_id") or "unbound")
        opencode_session_id = str(item.get("opencode_session_id") or "")
        state = "/".join(
            part for part in (str(item.get("execution") or "unknown"), str(item.get("turn") or "none")) if part
        )
        lines.append(
            f"  {repository_session_id}  {_opencode_chat_session_label(opencode_session_id)}  "
            f"{state}  {_session_display_task(item, titles)}"
        )
        if show_activity:
            lines.append(f"    Active task: {_opencode_current_activity_label(opencode_session_id)}")
        open_reference = _session_open_reference(item)
        if open_reference:
            lines.append(f"    Open: sessions.py chat read {open_reference}")
    if len(items) > len(visible):
        lines.append(f"  ... +{len(items) - len(visible)} more (run: sessions.py status)")


def _active_lock_lines(locks: dict[str, Any]) -> list[str]:
    active = []
    for lock_name, lock in sorted(locks.items()):
        if not isinstance(lock, dict) or lock.get("status") != "IN_PROGRESS":
            continue
        claimed_by = lock.get("claimed_by") or "unknown"
        since = lock.get("since") or "unknown"
        phase = f", phase {lock.get('phase')}" if lock.get("phase") else ""
        active.append(f"  {lock_name}: held by {claimed_by} since {since}{phase}")
    return active or ["  none"]


def _edit_lease_summary_lines(edit_leases: dict[str, Any]) -> list[str]:
    if not edit_leases:
        return ["  none"]
    by_owner: dict[str, int] = {}
    for lease in edit_leases.values():
        if not isinstance(lease, dict):
            continue
        owner = str(lease.get("session_id") or "unknown")
        by_owner[owner] = by_owner.get(owner, 0) + 1
    if not by_owner:
        return ["  none"]
    return [f"  {owner} holds {count} file{'s' if count != 1 else ''}" for owner, count in sorted(by_owner.items())]


def _format_coordination_section(session_id: str, data: dict[str, Any], view: dict[str, Any]) -> str:
    working = _sort_presence_items(list(view.get("working") or []))
    waiting_for_resource = _sort_presence_items(list(view.get("waiting_for_resource") or []))
    waiting = _sort_presence_items(list(view.get("waiting_for_user") or []))
    completed = _sort_presence_items(
        [
            item for item in list(view.get("idle_after_response") or [])
            if (hours := _safe_hours_since(str(item.get("updated_at") or ""))) is not None
            and hours <= COORDINATION_COMPLETED_HOURS
        ]
    )
    visible_session_ids = [
        str(item.get("opencode_session_id") or "")
        for item in [*working, *waiting_for_resource, *waiting, *completed]
        if item.get("opencode_session_id")
    ]
    titles = _opencode_session_titles(visible_session_ids)
    lines: list[str] = []
    _append_presence_section(lines, "Working now", working, titles, show_activity=True)
    lines.append("")
    _append_presence_section(lines, "Waiting for shared resource", waiting_for_resource, titles)
    lines.append("")
    _append_presence_section(lines, "Waiting for user", waiting, titles)
    lines.append("")
    _append_presence_section(lines, f"Completed in last {COORDINATION_COMPLETED_HOURS}h", completed, titles)
    lines.append("")
    lines.append("Locks:")
    lines.extend(_active_lock_lines(data.get("locks", {})))
    lines.append("")
    lines.append("Edit leases:")
    lines.extend(_edit_lease_summary_lines(data.get("edit_leases", {})))
    conflicts = view.get("conflicts") or []
    lines.append("")
    if conflicts:
        lines.append(f"Possible conflicts: {len(conflicts)} active claim(s); details: sessions.py status --conflicts")
    else:
        lines.append(f"Possible conflicts: none for session {session_id}")
    return _box_section("COORDINATION", lines)


def _format_status_session_card(selected: dict[str, Any] | None, locks: dict[str, Any], edit_leases: dict[str, Any]) -> str:
    if selected is None:
        return "Session: not found\n"
    opencode_session_id = str(selected.get("opencode_session_id") or "")
    titles = _opencode_session_titles([opencode_session_id])
    repository_session_id = str(selected.get("repository_session_id") or "unbound")
    execution = str(selected.get("execution") or "unknown")
    turn = str(selected.get("turn") or "none")
    attention = str(selected.get("attention") or "none")
    worktree = selected.get("worktree") if isinstance(selected.get("worktree"), dict) else {}
    worktree_status = worktree.get("status") or "none"
    worktree_path = worktree.get("path") or "none"
    active_locks = [name for name, lock in locks.items() if isinstance(lock, dict) and lock.get("status") == "IN_PROGRESS"]
    owned_leases = [path for path, lease in edit_leases.items() if isinstance(lease, dict) and lease.get("session_id") == repository_session_id]
    resource_wait = selected.get("resource_wait") if isinstance(selected.get("resource_wait"), dict) else {}
    if resource_wait.get("status") == "waiting" and resource_wait.get("heartbeat_at") and _minutes_since(resource_wait["heartbeat_at"]) <= 3:
        blocker = (
            f"waiting for {resource_wait.get('resource', 'shared resource')} "
            f"held by {resource_wait.get('owner_session_id') or '?'}"
        )
    elif active_locks:
        blocker = f"active lock(s): {', '.join(sorted(active_locks))}"
    elif attention.startswith("required_"):
        blocker = f"user input required ({attention})"
    else:
        blocker = "none"
    open_reference = repository_session_id if repository_session_id != "unbound" else opencode_session_id
    lines = [
        f"Session {repository_session_id}",
        f"  State: {execution}/{turn}; attention={attention}",
        f"  Task: {_session_display_task(selected, titles)}",
        f"  OpenCode: {opencode_session_id or 'unknown'}",
        f"  Worktree: {worktree_status}",
        f"  Path: {worktree_path}",
        f"  Current activity: {_opencode_current_activity_label(opencode_session_id) if execution in {'busy', 'retrying'} else 'none'}",
        f"  Current blocker: {blocker}",
        f"  Edit leases held: {len(owned_leases)}",
        f"  Open chat: sessions.py chat read {open_reference}" if open_reference else "  Open chat: unavailable",
    ]
    children = selected.get("children") or []
    if children:
        lines.append(f"  Child sessions: {len(children)}")
    return "\n".join(lines) + "\n"


def cmd_status(args: argparse.Namespace) -> None:
    """Show current OpenCode reality, with durable history available explicitly."""
    data = _load_sessions()
    _prune_stale(data)
    _prune_stale_locks(data)
    _prune_checkpoint_lock_files(data)
    _prune_stale_edit_leases(data)
    _prune_stale_resource_waits(data)
    _save_sessions(data)

    sessions = data.get("sessions", {})
    locks = data.get("locks", {})
    edit_leases = data.get("edit_leases", {})
    try:
        presence = _opencode_presence_store().snapshot()
    except PresenceStoreError as error:
        presence = {"sessions": {}, "task_claims": {}, "diagnostics": [{"code": "unavailable_store", "message": str(error)}]}
    view = presence_status_view(
        data,
        presence,
        include_all=getattr(args, "all", False),
        conflicts_only=getattr(args, "conflicts", False),
        session_filter=getattr(args, "session", "") or "",
    )

    # --json: emit raw sessions dict for machine consumers (e.g. opencode plugin)
    if getattr(args, "json", False):
        dirty_by_root: dict[Path, set[str]] = {}
        output = {"sessions": {}, "locks": locks, "edit_leases": edit_leases, "presence": presence, "live": view}
        for sid, info in sessions.items():
            root = _session_checkout_root(info)
            if root not in dirty_by_root:
                dirty_by_root[root] = _get_dirty_files(checkout_root=root)
            dirty_files = dirty_by_root[root]
            modified = info.get("modified_files", [])
            uncommitted = [f for f in modified if f in dirty_files]
            output["sessions"][sid] = {
                **info,
                "uncommitted_files": uncommitted,
                "has_uncommitted": bool(uncommitted),
            }
        print(json.dumps(output))
        return

    print("== LIVE SESSION STATUS ==")
    print()

    if view.get("session") is not None or getattr(args, "session", ""):
        print(_format_status_session_card(view.get("session"), locks, edit_leases), end="")
        print()
    elif getattr(args, "conflicts", False):
        print("Relevant active conflicts:")
        if view["conflicts"]:
            for conflict in view["conflicts"]:
                print(f"  - {json.dumps(conflict, sort_keys=True)}")
        else:
            print("  none")
        print()
    else:
        labels = (
            ("working", "Currently working"),
            ("waiting_for_resource", "Waiting for a shared resource"),
            ("waiting_for_user", "Waiting for required user input"),
            ("idle_after_response", "Idle after completed response"),
            ("stopped_or_failed", "Stopped or failed"),
        )
        for key, label in labels:
            print(f"{label} ({len(view[key])}):")
            for item in view[key]:
                repository = item.get("repository_session_id") or "unbound"
                task = f" - {item['task']}" if item.get("task") else ""
                print(f"  [{repository}] {item['opencode_session_id']} {item['execution']}/{item['turn']}{task}")
            if not view[key]:
                print("  none")
            print()

    if view.get("diagnostics"):
        print("Presence diagnostics:")
        for diagnostic in view["diagnostics"]:
            print(f"  - {diagnostic.get('code', 'unknown')}: {diagnostic.get('message', '')}")
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

    if getattr(args, "all", False):
        print(f"Durable and historical sessions ({len(sessions)}):")
        for sid, info in sorted(sessions.items()):
            writing = info.get("writing")
            mod_count = len(info.get("modified_files", []))
            writing_str = f" WRITING: {writing}" if writing else ""
            linked_task = info.get("task_id")
            task_str = f" [task: {linked_task}]" if linked_task else ""
            linear_id = info.get("linear_issue_id")
            linear_str = f" [{linear_id}]" if linear_id else ""
            worktree = info.get("worktree") if isinstance(info.get("worktree"), dict) else {}
            lifecycle = f" [worktree: {worktree.get('status', 'none')}]" if worktree else ""
            repo_str = f" [repo: {_session_repo_name(info)}]" if not _session_is_control_plane_repo(info) else ""
            print(
                f"  [{sid}] {info.get('task', '?')} "
                f"(touched: {mod_count} files, advisory){task_str}{linear_str}{repo_str}{lifecycle}{writing_str}"
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


def _product_runtime_diagnostics(checkout: Path = PRODUCT_RUNTIME_CHECKOUT) -> dict[str, Any]:
    """Classify managed-runtime dirtiness without mutating the checkout."""
    if not (checkout / ".git").exists():
        return {"exists": False, "dirty_files": [], "generated_only": False}
    dirty_files = sorted(_get_dirty_files(checkout_root=checkout))
    return {
        "exists": True,
        "dirty_files": dirty_files,
        "generated_only": bool(dirty_files) and set(dirty_files) <= PRODUCT_RUNTIME_GENERATED_PATHS,
    }


def cmd_doctor(args: argparse.Namespace) -> None:
    """Diagnose deploy blockers without mutating git state."""
    data = _load_sessions()
    _prune_stale(data)
    _prune_stale_locks(data)

    sessions = data.get("sessions", {})
    session_id = getattr(args, "session", None) or ""
    focus_session = sessions.get(session_id) if session_id else None
    checkout_root = _session_checkout_root(focus_session)
    dirty_files = sorted(_get_dirty_files(checkout_root=checkout_root))
    staged_files = sorted(_get_staged_files(checkout_root=checkout_root))
    git_summary = _get_git_status_summary(checkout_root=checkout_root)

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
            worktree_warnings = _session_worktree_warnings(session_id, sessions[session_id])
            if worktree_warnings:
                print("Worktree warnings:")
                for warning in worktree_warnings:
                    print(f"  - {warning}")
                print()
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

    runtime_diagnostics = _product_runtime_diagnostics()
    runtime_dirty = runtime_diagnostics["dirty_files"]
    print("Product runtime:")
    print(f"  Path: {PRODUCT_RUNTIME_CHECKOUT}")
    if not runtime_diagnostics["exists"]:
        print("  State: not initialized")
    elif not runtime_dirty:
        print("  State: clean")
    else:
        print(f"  State: dirty ({len(runtime_dirty)} file(s))")
        for path in runtime_dirty:
            print(f"    - {path}")
        if runtime_diagnostics["generated_only"]:
            rendered_paths = " ".join(runtime_dirty)
            print("  Classification: generated nightly storage-audit output")
            print("  Recovery scope: these files are reproducible from retained test artifacts")
            print(
                "  Reviewed recovery: git -C "
                f"{PRODUCT_RUNTIME_CHECKOUT} restore --source=HEAD -- {rendered_paths}"
            )
        else:
            print("  Classification: unrecognized; preserve and review before recovery")
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
            if _session_repo_id(other_info) != _session_repo_id(sessions.get(sid)):
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
            filepath = _relative_repo_path_for_session(raw, session)
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


def cmd_presence(args: argparse.Namespace) -> None:
    """Update/query ephemeral presence and atomically manage task intent."""
    store = _opencode_presence_store()
    action = args.presence_action
    try:
        if action == "update":
            payload = json.load(sys.stdin) if args.json_stdin else {}
            print(json.dumps(store.update(payload), sort_keys=True))
            return
        if action == "show":
            print(json.dumps(store.snapshot(expire=not args.no_expire), sort_keys=True))
            return
        if action == "child-role":
            print(json.dumps(store.set_child_role(
                args.session,
                args.parent,
                args.role,
                if_unset=args.if_unset,
            ), sort_keys=True))
            return
        if action == "claim-task":
            result = store.claim_task(args.spec, args.task, args.owner, role=args.role, ttl_seconds=args.ttl)
            print(json.dumps(result, sort_keys=True))
            return
        if action == "renew-task":
            result = store.renew_task(args.spec, args.task, args.owner, ttl_seconds=args.ttl)
            print(json.dumps(result, sort_keys=True))
            return
        if action == "release-task":
            print(json.dumps(store.release_task(args.spec, args.task, args.owner), sort_keys=True))
            return
    except TaskClaimConflict as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        sys.exit(2)
    except (PresenceStoreError, json.JSONDecodeError) as error:
        print(f"Presence error: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"Error: unknown presence action {action}", file=sys.stderr)
    sys.exit(1)


def _continuation_repository_session_id(data: dict, session_reference: str) -> str:
    """Resolve a repository session from either short or OpenCode identity."""
    if session_reference in data.get("sessions", {}):
        return session_reference
    for session_id, session in data.get("sessions", {}).items():
        if isinstance(session, dict) and session.get("opencode_session_id") == session_reference:
            return session_id
    return ""


def _openmates_task_external_context_hash(opencode_session_id: str) -> str:
    """Hash an external OpenCode identity before storing bridge metadata."""
    return hashlib.sha256(
        f"openmates-task-bridge-v1\0opencode\0{opencode_session_id}".encode("utf-8")
    ).hexdigest()


def _openmates_task_opencode_session_id(data: dict, session_reference: str) -> str:
    """Resolve a bound chat, or accept a validated new top-level chat identity."""
    repository_session_id = _continuation_repository_session_id(data, session_reference)
    if repository_session_id:
        opencode_session_id = str(
            data["sessions"][repository_session_id].get("opencode_session_id") or ""
        )
        if OPENCODE_SESSION_ID_RE.fullmatch(opencode_session_id):
            return opencode_session_id
    return session_reference if OPENCODE_SESSION_ID_RE.fullmatch(session_reference) else ""


def _run_openmates_task_cli(arguments: list[str]) -> dict:
    """Execute one trusted personal-profile Task CLI command and parse bounded JSON."""
    if not arguments or arguments[0] != "tasks":
        raise RuntimeError("Task bridge accepts only trusted openmates tasks commands")
    environment = dict(os.environ)
    environment.update({
        "OPENMATES_PROFILE": OPENMATES_TASK_BRIDGE_PROFILE,
        "OPENMATES_ACCOUNT_GUARD": "required",
        "OPENMATES_API_URL": OPENMATES_TASK_BRIDGE_API_URL,
        "OPENMATES_STATE_DIR": "",
    })
    try:
        result = subprocess.run(
            ["openmates", *arguments],
            cwd=str(CONTROL_PLANE_ROOT),
            env=environment,
            text=True,
            capture_output=True,
            timeout=OPENMATES_TASK_BRIDGE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"OpenMates Task CLI unavailable: {type(error).__name__}") from error
    if result.returncode != 0:
        raise RuntimeError(f"OpenMates Task CLI failed with exit status {result.returncode}")
    if len(result.stdout.encode("utf-8")) > OPENMATES_TASK_BRIDGE_MAX_JSON_BYTES:
        raise RuntimeError("OpenMates Task CLI returned an oversized JSON response")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("OpenMates Task CLI returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("OpenMates Task CLI returned a non-object JSON response")
    return payload


def _validated_openmates_task_records(payload: dict, opencode_session_id: str) -> list[dict]:
    """Validate and scope trusted CLI records without retaining decrypted text."""
    records = payload.get("tasks")
    if not isinstance(records, list):
        raise RuntimeError("OpenMates Task CLI JSON is missing tasks")
    if len(records) > 500:
        raise RuntimeError("OpenMates Task CLI returned too many Tasks")
    validated: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("OpenMates Task CLI returned an invalid Task record")
        task_id = record.get("task_id")
        short_id = record.get("short_id")
        status = record.get("status")
        version = record.get("version")
        if not isinstance(task_id, str) or not task_id or not isinstance(short_id, str) or not short_id:
            raise RuntimeError("OpenMates Task CLI returned a Task without stable identity")
        if not isinstance(status, str) or status not in {"backlog", "todo", "in_progress", "blocked", "done"}:
            raise RuntimeError(f"OpenMates Task CLI returned an invalid status for {short_id}")
        if not isinstance(version, int) or version < 1:
            raise RuntimeError(f"OpenMates Task CLI returned an invalid version for {short_id}")
        if record.get("source") == "workflow_run" or task_id.startswith(("workflow-run:", "workflow-schedule:")):
            continue
        external_chat = record.get("external_chat")
        if not isinstance(external_chat, dict):
            raise RuntimeError(f"OpenMates Task CLI returned missing external context for {short_id}")
        if external_chat.get("provider") != "opencode" or external_chat.get("id") != opencode_session_id:
            continue
        validated.append(dict(record))
    return validated


def _openmates_task_order(record: dict) -> tuple[int, str, str]:
    position = record.get("position")
    return (
        int(position) if isinstance(position, (int, float)) else 0,
        str(record.get("title") or ""),
        str(record.get("task_id") or ""),
    )


def _openmates_task_is_waiting(record: dict) -> bool:
    return (
        str(record.get("queue_state") or "").lower() in OPENMATES_TASK_WAIT_QUEUE_STATES
        or str(record.get("ai_execution_state") or "").lower() in OPENMATES_TASK_STOP_EXECUTION_STATES
    )


def _classify_openmates_task_snapshot(records: list[dict]) -> dict:
    """Return one deterministic fail-closed scheduling decision."""
    ordered = sorted(records, key=_openmates_task_order)
    ai_tasks = [record for record in ordered if record.get("assignee_type") == "ai"]
    active = [record for record in ai_tasks if record.get("status") == "in_progress"]
    if len(active) > 1:
        raise RuntimeError("OpenMates Task bridge found multiple active Tasks")
    selected: dict | None
    if active:
        selected = active[0]
        decision = "wait_blocked" if _openmates_task_is_waiting(selected) else "resume_active"
    else:
        blocked = [
            record for record in ai_tasks
            if record.get("status") == "blocked" or _openmates_task_is_waiting(record)
        ]
        runnable = [
            record for record in ai_tasks
            if record.get("status") in {"backlog", "todo"} and not _openmates_task_is_waiting(record)
        ]
        if blocked:
            selected = blocked[0]
            decision = "wait_blocked"
        elif runnable:
            selected = runnable[0]
            decision = "activate_next"
        else:
            selected = None
            decision = "no_work"
    remaining = [
        record for record in ordered
        if record.get("status") in OPENMATES_TASK_OPEN_STATUSES and record is not selected
    ]
    return {"decision": decision, "active": selected, "remaining": remaining}


def _openmates_task_context_from_payload(payload: dict, opencode_session_id: str) -> dict:
    """Build request-only plaintext context from trusted CLI JSON."""
    classified = _classify_openmates_task_snapshot(
        _validated_openmates_task_records(payload, opencode_session_id)
    )
    active = classified.get("active")
    active_context = None
    if isinstance(active, dict):
        active_context = {
            key: active.get(key)
            for key in (
                "task_id", "short_id", "title", "description", "latest_instruction",
                "status", "assignee_type", "queue_state", "blocked_reason_code",
                "blocked_reason", "ai_execution_state", "priority", "version",
            )
        }
    remaining = [
        {
            "short_id": str(record.get("short_id") or ""),
            "title": str(record.get("title") or ""),
            "status": str(record.get("status") or ""),
        }
        for record in classified.get("remaining", [])
    ]
    return {"decision": classified["decision"], "active": active_context, "remaining": remaining}


def _openmates_task_context(
    session_reference: str,
    *,
    cli_runner: Callable[[list[str]], dict] = _run_openmates_task_cli,
) -> dict:
    """Fetch one authoritative request-only Task snapshot for a top-level chat."""
    data = _load_sessions()
    opencode_session_id = _openmates_task_opencode_session_id(data, session_reference)
    if not opencode_session_id:
        return {"decision": "unbound", "active": None, "remaining": []}
    payload = cli_runner(["tasks", "list", "--external-chat", f"opencode:{opencode_session_id}", "--json"])
    return _openmates_task_context_from_payload(payload, opencode_session_id)


def _openmates_task_tool(
    session_reference: str,
    input_payload: dict,
    *,
    cli_runner: Callable[[list[str]], dict] = _run_openmates_task_cli,
) -> dict:
    """Execute one allowlisted typed Task operation scoped to a validated chat."""
    if not isinstance(input_payload, dict):
        raise RuntimeError("Task tool input must be a JSON object")
    action = input_payload.get("action")
    allowed_actions = {"context", "show", "create", "start", "edit", "block", "unblock", "done"}
    if action not in allowed_actions:
        raise RuntimeError(f"unsupported Task tool action: {action}")

    data = _load_sessions()
    opencode_session_id = _openmates_task_opencode_session_id(data, session_reference)
    if not opencode_session_id:
        raise RuntimeError("Task tool requires a valid top-level OpenCode session")
    scope = ["--external-chat", f"opencode:{opencode_session_id}"]

    def text_field(name: str, *, required: bool = False, maximum: int = 10000) -> str:
        value = input_payload.get(name)
        if value is None and not required:
            return ""
        if not isinstance(value, str) or (required and not value.strip()):
            raise RuntimeError(f"Task tool requires a non-empty {name}")
        value = value.strip() if name in {"task_id", "title", "reason_code"} else value
        if len(value) > maximum:
            raise RuntimeError(f"Task tool {name} exceeds {maximum} characters")
        return value

    if action == "context":
        payload = cli_runner(["tasks", "list", *scope, "--json"])
        return _openmates_task_context_from_payload(payload, opencode_session_id)

    if action == "create":
        command = ["tasks", "create", "--title", text_field("title", required=True, maximum=500)]
        description = text_field("description")
        if description:
            command.extend(["--description", description])
        # The Task API currently accepts external-context AI assignment as an
        # update but rejects it on create. Keep both allowlisted operations
        # explicit and return only the final AI-owned record.
        command.extend(["--assign", "user", *scope, "--json"])
        created = cli_runner(command).get("task")
        if not isinstance(created, dict) or not created.get("task_id"):
            raise RuntimeError("Task create returned an invalid record")
        return cli_runner([
            "tasks", "edit", str(created["task_id"]), "--assign", "ai", *scope, "--json",
        ])

    task_id = text_field("task_id", required=True, maximum=200)
    if action == "show":
        return cli_runner(["tasks", "show", task_id, *scope, "--json"])
    if action == "start":
        # The generic status mutation is supported for AI-owned external-chat
        # Tasks, while the specialized CLI `start` transition can reject that
        # otherwise valid ownership/context combination.
        return cli_runner(["tasks", "edit", task_id, "--status", "in_progress", *scope, "--json"])
    if action == "edit":
        command = ["tasks", "edit", task_id]
        title = text_field("title", maximum=500)
        description = text_field("description")
        status = input_payload.get("status")
        if title:
            command.extend(["--title", title])
        if description:
            command.extend(["--description", description])
        if status is not None:
            if status not in {"backlog", "todo", "in_progress", "blocked", "done"}:
                raise RuntimeError("Task tool received an invalid status")
            command.extend(["--status", str(status)])
        if len(command) == 3:
            raise RuntimeError("Task edit requires title, description, or status")
        command.extend([*scope, "--json"])
        return cli_runner(command)
    if action == "block":
        reason_code = text_field("reason_code", required=True, maximum=100)
        allowed_reasons = {
            "needs_user_input", "waiting_for_approval", "missing_credentials",
            "ambiguous_requirement", "external_dependency", "environment_unavailable",
            "verification_failed", "other",
        }
        if reason_code not in allowed_reasons:
            raise RuntimeError("Task tool received an invalid blocked reason code")
        command = ["tasks", "block", task_id, "--reason-code", reason_code]
        reason_text = text_field("reason_text")
        if reason_text:
            command.extend(["--reason-text", reason_text])
        command.extend([*scope, "--json"])
        return cli_runner(command)
    return cli_runner(["tasks", str(action), task_id, *scope, "--json"])


def _stage_openmates_task_reconciliation(session_reference: str, message_id: str) -> dict:
    """Persist one privacy-minimal completed-response boundary for later idle reconciliation."""
    if not message_id:
        raise RuntimeError("Task reconciliation requires a completed assistant message id")

    def mutate(data: dict) -> dict:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return {"staged": False, "reason": "unbound"}
        bridge = data["sessions"][repository_session_id].setdefault("task_bridge", {})
        if bridge.get("pending_message_id") == message_id or bridge.get("last_reconciled_message_id") == message_id:
            return {"staged": False, "reason": "duplicate"}
        bridge["pending_message_id"] = message_id
        bridge["pending_status"] = "ready"
        bridge["updated_at"] = _now_iso()
        return {"staged": True, "message_id": message_id}

    return _mutate_sessions(mutate)


def _claim_openmates_task_reconciliation(session_reference: str) -> dict | None:
    def mutate(data: dict) -> dict | None:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return None
        session = data["sessions"][repository_session_id]
        bridge = session.setdefault("task_bridge", {})
        message_id = bridge.get("pending_message_id")
        if not message_id or bridge.get("pending_status") != "ready":
            return None
        bridge["pending_status"] = "reconciling"
        bridge["updated_at"] = _now_iso()
        return {
            "repository_session_id": repository_session_id,
            "opencode_session_id": str(session.get("opencode_session_id") or ""),
            "message_id": str(message_id),
            "generation": int(bridge.get("generation") or 0) + 1,
        }

    return _mutate_sessions(mutate)


def _finish_openmates_task_reconciliation(
    session_reference: str,
    claim: dict,
    *,
    decision: str,
    task: dict | None,
) -> dict:
    def mutate(data: dict) -> dict:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return {"stored": False}
        bridge = data["sessions"][repository_session_id].setdefault("task_bridge", {})
        if bridge.get("pending_message_id") != claim["message_id"]:
            return {"stored": False, "reason": "superseded"}
        bridge.update({
            "external_context_hash": _openmates_task_external_context_hash(claim["opencode_session_id"]),
            "decision": decision,
            "task_id": str(task.get("task_id") or "") if task else "",
            "task_version": int(task.get("version") or 0) if task else 0,
            "generation": claim["generation"],
            "last_reconciled_message_id": claim["message_id"],
            "pending_message_id": "",
            "pending_status": "reconciled",
            "updated_at": _now_iso(),
        })
        return {"stored": True}

    return _mutate_sessions(mutate)


def _reconcile_openmates_tasks(
    session_reference: str,
    *,
    cli_runner: Callable[[list[str]], dict] = _run_openmates_task_cli,
) -> dict:
    """Reconcile one staged response and record at most one idempotent continuation."""
    claim = _claim_openmates_task_reconciliation(session_reference)
    if claim is None:
        return {"decision": "already_reconciled", "continuation": None}
    opencode_session_id = claim["opencode_session_id"]
    if not opencode_session_id:
        _finish_openmates_task_reconciliation(session_reference, claim, decision="unbound", task=None)
        return {"decision": "unbound", "continuation": None}
    try:
        payload = cli_runner(["tasks", "list", "--external-chat", f"opencode:{opencode_session_id}", "--json"])
        classified = _classify_openmates_task_snapshot(
            _validated_openmates_task_records(payload, opencode_session_id)
        )
        decision = classified["decision"]
        selected = classified.get("active")
        if decision == "activate_next" and isinstance(selected, dict):
            activated = cli_runner([
                "tasks", "edit", str(selected["task_id"]), "--status", "in_progress", "--json",
            ]).get("task")
            if not isinstance(activated, dict) or activated.get("task_id") != selected.get("task_id"):
                raise RuntimeError("OpenMates Task activation returned an invalid record")
            selected = activated
        continuation = None
        if decision in {"resume_active", "activate_next"} and isinstance(selected, dict):
            operation_key = ":".join([
                _openmates_task_external_context_hash(opencode_session_id),
                str(selected["task_id"]),
                str(selected["version"]),
                str(claim["generation"]),
            ])
            continuation = _record_session_continuation(
                session_reference,
                operation_type="task_ready",
                operation_key=operation_key,
                next_action=(
                    "Continue the active OpenMates Task from the request-only Task context. "
                    "Work on the smallest remaining step, then explicitly mark the Task done or block it with a reason."
                ),
            )
        _finish_openmates_task_reconciliation(
            session_reference,
            claim,
            decision=decision,
            task=selected if isinstance(selected, dict) else None,
        )
        return {"decision": decision, "continuation": continuation}
    except Exception:
        _finish_openmates_task_reconciliation(session_reference, claim, decision="failed_closed", task=None)
        raise


def cmd_task_bridge(args: argparse.Namespace) -> None:
    """Expose the privacy-minimal Task bridge to the verified OpenCode hook."""
    try:
        if args.task_bridge_action == "stage":
            result = _stage_openmates_task_reconciliation(args.session, args.message_id)
        elif args.task_bridge_action == "context":
            result = _openmates_task_context(args.session)
        elif args.task_bridge_action == "reconcile":
            result = _reconcile_openmates_tasks(args.session)
        elif args.task_bridge_action == "tool":
            result = _openmates_task_tool(args.session, json.load(sys.stdin))
        else:
            raise RuntimeError(f"unknown task bridge action: {args.task_bridge_action}")
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"Task bridge error: {error}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"task_bridge": result}, sort_keys=True))


def _opencode_ascending_message_id(*, timestamp_ms: int | None = None, entropy: str = "") -> str:
    """Create an OpenCode message ID that preserves chronological storage order.

    OpenCode streams messages by lexicographic ID, not by the database timestamp.
    Supplying a plain digest as ``messageID`` therefore corrupts the effective
    conversation order whenever that digest sorts after native IDs. Mirror the
    native 48-bit timestamp prefix and keep a stable base62 suffix for retries.
    """
    created_ms = int(timestamp_ms if timestamp_ms is not None else time.time_ns() // 1_000_000)
    # The native implementation writes the low 48 bits into a six-byte buffer.
    encoded_time = (created_ms * 0x1000 + 1) & ((1 << 48) - 1)
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    digest = hashlib.sha256((entropy or secrets.token_hex(16)).encode("utf-8")).digest()
    suffix = "".join(alphabet[value % len(alphabet)] for value in digest[:14])
    return f"msg_{encoded_time:012x}{suffix}"


def _record_session_continuation(
    session_reference: str,
    *,
    operation_type: str,
    operation_key: str,
    next_action: str,
) -> dict:
    """Persist one allowlisted continuation, replacing only the same operation."""
    if operation_type not in CONTINUATION_ALLOWED_TYPES:
        raise RuntimeError(f"unsupported continuation operation type: {operation_type}")
    if not operation_key or not next_action:
        raise RuntimeError("continuation requires operation key and next action")

    def mutate(data: dict) -> dict:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            raise RuntimeError(f"session not found for continuation: {session_reference}")
        session = data["sessions"][repository_session_id]
        now = _now_iso()
        current = session.get("continuation")
        if (
            isinstance(current, dict)
            and current.get("operation_type") == operation_type
            and current.get("operation_key") == operation_key
            and current.get("status") in {"ready", "delivering", "delivered"}
        ):
            return dict(current)
        record = {
            "operation_type": operation_type,
            "operation_key": operation_key,
            "next_action": next_action,
            "status": "ready",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
        }
        session["continuation"] = record
        return dict(record)

    return _mutate_sessions(mutate)


def _claim_session_continuation(session_reference: str) -> dict | None:
    """Claim one ready continuation and derive its idempotent OpenCode message ID."""
    def mutate(data: dict) -> dict | None:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return None
        session = data["sessions"][repository_session_id]
        record = session.get("continuation")
        if not isinstance(record, dict) or record.get("status") != "ready":
            return None
        attempts = int(record.get("attempts") or 0)
        if attempts >= CONTINUATION_MAX_DELIVERY_ATTEMPTS:
            record["status"] = "failed"
            record["updated_at"] = _now_iso()
            return None
        generation = attempts + 1
        identity = ":".join(
            [repository_session_id, str(record.get("operation_type")), str(record.get("operation_key")), str(generation)]
        )
        record["status"] = "delivering"
        record["attempts"] = generation
        record["message_id"] = _opencode_ascending_message_id(entropy=identity)
        record["updated_at"] = _now_iso()
        return {**record, "repository_session_id": repository_session_id}

    return _mutate_sessions(mutate)


def _finish_session_continuation(session_reference: str, *, delivered: bool) -> dict | None:
    """Acknowledge delivery or make a transport failure retryable once."""
    def mutate(data: dict) -> dict | None:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return None
        record = data["sessions"][repository_session_id].get("continuation")
        if not isinstance(record, dict) or record.get("status") != "delivering":
            return dict(record) if isinstance(record, dict) else None
        record["status"] = "delivered" if delivered else "ready"
        record["updated_at"] = _now_iso()
        return dict(record)

    return _mutate_sessions(mutate)


def _cancel_session_continuation(session_reference: str) -> bool:
    """Cancel a ready continuation after the chat already continued itself."""
    def mutate(data: dict) -> bool:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return False
        session = data["sessions"][repository_session_id]
        record = session.get("continuation")
        if not isinstance(record, dict) or record.get("status") != "ready":
            return False
        record["status"] = "cancelled"
        record["updated_at"] = _now_iso()
        return True

    return bool(_mutate_sessions(mutate))


def cmd_continuation(args: argparse.Namespace) -> None:
    """Record and deliver bounded deterministic OpenCode continuations."""
    try:
        if args.continuation_action == "record":
            result = _record_session_continuation(
                args.session,
                operation_type=args.operation_type,
                operation_key=args.operation_key,
                next_action=args.next_action,
            )
        elif args.continuation_action == "claim":
            result = _claim_session_continuation(args.session)
        elif args.continuation_action == "ack":
            result = _finish_session_continuation(args.session, delivered=True)
        elif args.continuation_action == "release":
            result = _finish_session_continuation(args.session, delivered=False)
        elif args.continuation_action == "cancel":
            result = {"cancelled": _cancel_session_continuation(args.session)}
        else:
            raise RuntimeError(f"unknown continuation action: {args.continuation_action}")
    except RuntimeError as exc:
        print(f"Continuation error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"continuation": result}, sort_keys=True))


def _record_session_media(
    session_reference: str,
    *,
    artifact_type: str,
    snippet: str,
    artifact_key: str = "",
    artifact_path: str = "",
    subject_commit: str = "",
    run_id: str = "",
) -> dict:
    """Persist a privacy-minimal response artifact until it is visibly delivered."""
    if artifact_type not in {"video", "figma_image", "figma_export"}:
        raise RuntimeError(f"unsupported response media type: {artifact_type}")
    if not snippet:
        raise RuntimeError("response media requires an exact snippet or delivery instruction")
    snippet_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
    stable_key = artifact_key or snippet_hash[:24]

    def mutate(data: dict) -> dict:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            raise RuntimeError(f"session not found for response media: {session_reference}")
        session = data["sessions"][repository_session_id]
        artifacts = session.setdefault("response_media", {})
        current = artifacts.get(stable_key)
        if isinstance(current, dict):
            if (
                current.get("status") in {"pending", "delivering"}
                and current.get("artifact_type") == "figma_export"
                and artifact_type == "figma_image"
            ):
                current.update({
                    "artifact_type": artifact_type,
                    "artifact_path": artifact_path or current.get("artifact_path", ""),
                    "snippet": snippet,
                    "snippet_hash": snippet_hash,
                    "subject_commit": subject_commit or current.get("subject_commit", ""),
                    "run_id": run_id or current.get("run_id", ""),
                    "status": "pending",
                    "updated_at": _now_iso(),
                })
            return dict(current)
        now = _now_iso()
        record = {
            "artifact_key": stable_key,
            "artifact_type": artifact_type,
            "artifact_path": artifact_path,
            "snippet": snippet,
            "snippet_hash": snippet_hash,
            "subject_commit": subject_commit,
            "run_id": run_id,
            "status": "pending" if MEDIA_AUTOMATION_ENABLED else "quarantined",
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
        }
        artifacts[stable_key] = record
        return dict(record)

    return _mutate_sessions(mutate)


def _canonical_response_media_text(value: object) -> str:
    text = str(value or "").replace('\\"', '"')
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _response_media_equivalence_key(record: dict) -> tuple[str, str]:
    artifact_type = str(record.get("artifact_type") or "")
    if artifact_type == "video":
        return artifact_type, _canonical_response_media_text(record.get("snippet"))
    if artifact_type == "figma_export":
        return artifact_type, str(record.get("artifact_path") or record.get("snippet") or "").strip()
    if artifact_type == "figma_image":
        return artifact_type, _canonical_response_media_text(record.get("snippet"))
    return artifact_type, str(record.get("artifact_key") or record.get("snippet") or "").strip()


def _fail_session_media(session_reference: str, artifact_key: str, *, reason: str = "") -> dict | None:
    """Retire an undeliverable media artifact without scheduling another prompt."""
    def mutate(data: dict) -> dict | None:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return None
        artifacts = data["sessions"][repository_session_id].get("response_media")
        record = artifacts.get(artifact_key) if isinstance(artifacts, dict) else None
        if not isinstance(record, dict):
            return None
        record["status"] = "failed"
        if reason:
            record["failure_reason"] = reason
        record["updated_at"] = _now_iso()
        return dict(record)

    return _mutate_sessions(mutate)


def _claim_session_media(session_reference: str) -> dict | None:
    """Claim the oldest pending media artifact with a deterministic message id."""
    if not MEDIA_AUTOMATION_ENABLED:
        return None

    def mutate(data: dict) -> dict | None:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return None
        artifacts = data["sessions"][repository_session_id].get("response_media")
        if not isinstance(artifacts, dict):
            return None
        all_records = [item for item in artifacts.values() if isinstance(item, dict)]
        delivered_keys = {
            _response_media_equivalence_key(item)
            for item in all_records
            if item.get("status") == "delivered"
        }
        candidates = sorted(
            (item for item in artifacts.values() if isinstance(item, dict) and item.get("status") == "pending"),
            key=lambda item: (str(item.get("created_at") or ""), str(item.get("artifact_key") or "")),
        )
        selected = []
        seen_pending = set()
        for item in candidates:
            equivalence_key = _response_media_equivalence_key(item)
            if equivalence_key in delivered_keys or equivalence_key in seen_pending:
                item["status"] = "failed"
                item["failure_reason"] = "duplicate response-media artifact"
                item["updated_at"] = _now_iso()
                continue
            seen_pending.add(equivalence_key)
            selected.append(item)
        candidates = selected
        if not candidates:
            return None
        record = candidates[0]
        attempts = int(record.get("attempts") or 0)
        if attempts >= MEDIA_DELIVERY_MAX_ATTEMPTS:
            record["status"] = "failed"
            record["updated_at"] = _now_iso()
            return None
        attempt = attempts + 1
        identity = f"{repository_session_id}:media:{record.get('artifact_key')}:{attempt}"
        record["attempts"] = attempt
        record["status"] = "delivering"
        record["message_id"] = _opencode_ascending_message_id(entropy=identity)
        record["updated_at"] = _now_iso()
        return {**record, "repository_session_id": repository_session_id}

    return _mutate_sessions(mutate)


def _quarantine_session_media(session_reference: str = "", *, reason: str = "recovery hotfix") -> dict:
    """Retire every undelivered legacy media record without deleting forensic state."""
    now = _now_iso()

    def mutate(data: dict) -> dict:
        repository_session_id = (
            _continuation_repository_session_id(data, session_reference)
            if session_reference
            else ""
        )
        if session_reference and not repository_session_id:
            raise RuntimeError(f"session not found for response media quarantine: {session_reference}")
        selected = (
            {repository_session_id: data["sessions"][repository_session_id]}
            if repository_session_id
            else data.get("sessions", {})
        )
        quarantined = 0
        sessions_changed = 0
        for session in selected.values():
            artifacts = session.get("response_media") if isinstance(session, dict) else None
            if not isinstance(artifacts, dict):
                continue
            changed = False
            for record in artifacts.values():
                if not isinstance(record, dict) or record.get("status") not in {"pending", "delivering"}:
                    continue
                record["status"] = "quarantined"
                record["quarantine_reason"] = reason
                record["quarantined_at"] = now
                record["updated_at"] = now
                quarantined += 1
                changed = True
            sessions_changed += int(changed)
        return {
            "quarantined": quarantined,
            "sessions_changed": sessions_changed,
            "reason": reason,
            "quarantined_at": now,
        }

    return _mutate_sessions(mutate)


def _finish_session_media(session_reference: str, artifact_key: str, *, delivered: bool) -> dict | None:
    """Acknowledge visible delivery or allow one bounded retry."""
    def mutate(data: dict) -> dict | None:
        repository_session_id = _continuation_repository_session_id(data, session_reference)
        if not repository_session_id:
            return None
        artifacts = data["sessions"][repository_session_id].get("response_media")
        record = artifacts.get(artifact_key) if isinstance(artifacts, dict) else None
        if not isinstance(record, dict):
            return None
        if delivered and record.get("status") in {"pending", "delivering"}:
            record["status"] = "delivered"
            record["updated_at"] = _now_iso()
        elif not delivered and record.get("status") == "delivering":
            record["status"] = "pending"
            if not delivered and int(record.get("attempts") or 0) >= MEDIA_DELIVERY_MAX_ATTEMPTS:
                record["status"] = "failed"
            record["updated_at"] = _now_iso()
        return dict(record)

    return _mutate_sessions(mutate)


def cmd_media(args: argparse.Namespace) -> None:
    """Record and deliver required OpenCode response media."""
    try:
        if args.media_action == "quarantine":
            result = _quarantine_session_media(args.session or "", reason=args.reason or "recovery hotfix")
        elif args.media_action == "record":
            result = _record_session_media(
                args.session,
                artifact_type=args.artifact_type,
                snippet=args.snippet,
                artifact_key=args.artifact_key or "",
                artifact_path=args.artifact_path or "",
                subject_commit=args.subject_commit or "",
                run_id=args.run_id or "",
            )
        elif args.media_action == "claim":
            result = _claim_session_media(args.session)
        elif args.media_action in {"ack", "release"}:
            result = _finish_session_media(
                args.session,
                args.artifact_key,
                delivered=args.media_action == "ack",
            )
        elif args.media_action == "fail":
            result = _fail_session_media(
                args.session,
                args.artifact_key,
                reason=args.reason or "",
            )
        else:
            raise RuntimeError(f"unknown media action: {args.media_action}")
    except RuntimeError as exc:
        print(f"Response media error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"media": result}, sort_keys=True))


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


def _read_env_values(path: Path) -> dict[str, str]:
    """Read runtime selectors without logging or mutating other environment values."""
    if not path.is_file():
        return {}
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _docker_compose_command(*args: str, checkout_root: Path = CONTROL_PLANE_ROOT) -> list[str]:
    compose_file = checkout_root / DOCKER_COMPOSE_FILE.relative_to(CONTROL_PLANE_ROOT)
    compose_override = checkout_root / DOCKER_COMPOSE_OVERRIDE.relative_to(CONTROL_PLANE_ROOT)
    command = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(compose_file),
    ]
    if compose_override.is_file():
        command.extend(["-f", str(compose_override)])
    runtime_env = _read_env_values(ENV_FILE)
    if runtime_env.get("OPENMATES_DEPLOYMENT_MODE") == "official_cloud":
        configured_overlay_path = runtime_env.get("OPENMATES_CLOUD_OVERLAY_PATH")
        overlay_root = Path(configured_overlay_path).expanduser().resolve() if configured_overlay_path else None
        overlay_compose_file = overlay_root / "docker-compose.openmatescloud.yml" if overlay_root else None
        overlay_ready = (
            runtime_env.get("OPENMATES_CLOUD_OVERLAY_ENABLED") == "true"
            and runtime_env.get("OPENMATES_CLOUD_OVERLAY_PACKAGE") == "OpenMatesCloud"
            and overlay_compose_file is not None
            and overlay_compose_file.is_file()
        )
        if not overlay_ready:
            raise RuntimeError(
                "official-cloud Docker restart requires the enabled OpenMatesCloud overlay and compose file"
            )
        command.extend(["-f", str(overlay_compose_file)])
    return [*command, *args]


def available_docker_services(checkout_root: Path = CONTROL_PLANE_ROOT) -> set[str]:
    rc, stdout, stderr = _run_cmd(
        _docker_compose_command("config", "--services", checkout_root=checkout_root),
        cwd=str(checkout_root),
    )
    if rc != 0:
        raise RuntimeError(f"Could not read Docker Compose services: {stderr or stdout}")
    return {line.strip() for line in stdout.splitlines() if line.strip()} - DOCKER_NON_RESTARTABLE_SERVICES


def available_docker_setup_services(checkout_root: Path = CONTROL_PLANE_ROOT) -> set[str]:
    rc, stdout, stderr = _run_cmd(
        _docker_compose_command("config", "--services", checkout_root=checkout_root),
        cwd=str(checkout_root),
    )
    if rc != 0:
        raise RuntimeError(f"Could not read Docker Compose services: {stderr or stdout}")
    return {line.strip() for line in stdout.splitlines() if line.strip()} & DOCKER_SETUP_SERVICES


def _docker_checkout_root(session_id: str) -> Path:
    session = _load_sessions().get("sessions", {}).get(session_id)
    if not isinstance(session, dict):
        raise RuntimeError(f"Docker restart session not found: {session_id}")
    return _ensure_product_runtime_checkout(refresh=False)


def _ensure_product_runtime_checkout(*, refresh: bool) -> Path:
    """Return the one clean checkout mounted by every product-code container."""
    PRODUCT_RUNTIME_STATE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PRODUCT_RUNTIME_STATE_LOCK_FILE.open("a+") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            checkout = PRODUCT_RUNTIME_CHECKOUT.resolve()
            if not (checkout / ".git").exists():
                checkout.parent.mkdir(parents=True, exist_ok=True)
                rc, _stdout, stderr = _run_cmd(
                    ["git", "fetch", "origin", "dev"],
                    cwd=str(CONTROL_PLANE_ROOT),
                    timeout=60,
                )
                if rc != 0:
                    raise RuntimeError(f"Could not fetch product runtime commit: {stderr}")
                rc, _stdout, stderr = _run_cmd(
                    ["git", "worktree", "add", "--detach", str(checkout), "origin/dev"],
                    cwd=str(CONTROL_PLANE_ROOT),
                    timeout=120,
                )
                if rc != 0:
                    raise RuntimeError(f"Could not create product runtime checkout: {stderr}")
            if _get_dirty_files(checkout_root=checkout):
                raise RuntimeError(f"Product runtime checkout is dirty: {checkout}")
            link_shared_worktree_resources(checkout)
            if refresh:
                rc, _stdout, stderr = _run_cmd(
                    ["git", "fetch", "origin", "dev"],
                    cwd=str(CONTROL_PLANE_ROOT),
                    timeout=60,
                )
                if rc != 0:
                    raise RuntimeError(f"Could not refresh product runtime commit: {stderr}")
                rc, _stdout, stderr = _run_cmd(
                    ["git", "merge", "--ff-only", "origin/dev"],
                    cwd=str(checkout),
                    timeout=60,
                )
                if rc != 0:
                    raise RuntimeError(f"Could not fast-forward product runtime checkout: {stderr}")
            return checkout
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)


def _load_product_runtime_state() -> dict:
    try:
        state = json.loads(PRODUCT_RUNTIME_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "services": {}}
    return state if isinstance(state, dict) and isinstance(state.get("services"), dict) else {"version": 1, "services": {}}


def _running_backend_mounts(checkout_root: Path) -> dict[str, dict[str, str]]:
    rc, stdout, _stderr = _run_cmd(
        _docker_compose_command("ps", "--services", "--status", "running", checkout_root=checkout_root),
        cwd=str(checkout_root),
    )
    if rc != 0:
        return {}
    mounted: dict[str, dict[str, str]] = {}
    for service in sorted({line.strip() for line in stdout.splitlines() if line.strip()}):
        rc, container_id, _stderr = _run_cmd(
            _docker_compose_command("ps", "-q", service, checkout_root=checkout_root),
            cwd=str(checkout_root),
        )
        container_id = container_id.strip()
        if rc != 0 or not container_id:
            continue
        rc, mounts_json, _stderr = _run_cmd(
            ["docker", "inspect", "--format", "{{json .Mounts}}", container_id],
            cwd=str(CONTROL_PLANE_ROOT),
        )
        if rc != 0:
            continue
        try:
            mounts = json.loads(mounts_json)
        except json.JSONDecodeError:
            continue
        backend_mount = next(
            (item for item in mounts if isinstance(item, dict) and item.get("Destination") == "/app/backend"),
            None,
        )
        if backend_mount:
            mounted[service] = {
                "container_id": container_id,
                "source": str(backend_mount.get("Source") or ""),
            }
    return mounted


def _incoherent_docker_services(checkout_root: Path, backend_tree: str) -> set[str]:
    state = _load_product_runtime_state().get("services") or {}
    expected_source = str((checkout_root / "backend").resolve())
    live_services = _running_backend_mounts(checkout_root)
    incoherent: set[str] = set()
    # A service previously managed by this runtime is incoherent when it is no
    # longer running too. This makes an interrupted Compose recreation
    # self-healing instead of silently accepting Created/stopped containers.
    for service in set(live_services) | set(state):
        live = live_services.get(service) or {}
        recorded = state.get(service) if isinstance(state.get(service), dict) else {}
        if (
            not live
            or
            Path(str(live.get("source") or "")).resolve() != Path(expected_source)
            or recorded.get("backend_tree") != backend_tree
            or recorded.get("container_id") != live.get("container_id")
        ):
            incoherent.add(service)
    return incoherent


def _coherent_docker_services(requested: list[str], checkout_root: Path, backend_tree: str) -> list[str]:
    """Expand a restart only when needed to eliminate mixed source generations."""
    return sorted(set(requested) | _incoherent_docker_services(checkout_root, backend_tree))


def _record_product_runtime_services(
    services: list[str],
    checkout_root: Path,
    source_commit: str,
    backend_tree: str,
) -> None:
    live = _running_backend_mounts(checkout_root)
    expected_source = (checkout_root / "backend").resolve()
    invalid = [
        service
        for service in services
        if service not in live or Path(str(live[service].get("source") or "")).resolve() != expected_source
    ]
    if invalid:
        raise RuntimeError(
            "Docker runtime mount coherence failed for: " + ", ".join(sorted(invalid))
        )
    with PRODUCT_RUNTIME_STATE_LOCK_FILE.open("a+") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            state = _load_product_runtime_state()
            for service in services:
                if service in live:
                    state["services"][service] = {
                        "commit": source_commit,
                        "backend_tree": backend_tree,
                        "container_id": live[service]["container_id"],
                        "source": live[service]["source"],
                        "verified_at": _now_iso(),
                    }
            temporary = PRODUCT_RUNTIME_STATE_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(PRODUCT_RUNTIME_STATE_FILE)
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)


def _docker_service_state(service: str, checkout_root: Path = CONTROL_PLANE_ROOT) -> dict:
    rc, container_id, stderr = _run_cmd(
        _docker_compose_command("ps", "-q", service, checkout_root=checkout_root),
        cwd=str(checkout_root),
    )
    container_id = container_id.strip()
    if rc != 0 or not container_id:
        return {"running": False, "health": "missing", "error": stderr.strip()}
    rc, stdout, stderr = _run_cmd(
        ["docker", "inspect", "--format", "{{json .State}}", container_id],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc != 0:
        return {
            "running": False,
            "health": "inspect_failed",
            "container_id": container_id,
            "error": stderr.strip(),
        }
    try:
        state = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "running": False,
            "health": "inspect_invalid",
            "container_id": container_id,
            "error": stdout.strip(),
        }
    health = str((state.get("Health") or {}).get("Status") or "none")
    return {
        "running": bool(state.get("Running")),
        "health": health,
        "container_id": container_id[:12],
        "status": str(state.get("Status") or "unknown"),
    }


def wait_for_docker_services_healthy(
    services: list[str],
    *,
    timeout: int,
    poll: int,
    checkout_root: Path = CONTROL_PLANE_ROOT,
    heartbeat=None,
) -> dict:
    deadline = time.time() + max(0, timeout)
    poll = max(1, poll)
    states = {}
    while True:
        states = {service: _docker_service_state(service, checkout_root) for service in services}
        if all(
            state.get("running") and state.get("health") in {"healthy", "none"}
            for state in states.values()
        ):
            return states
        if heartbeat:
            heartbeat()
        if time.time() >= deadline:
            summary = ", ".join(
                f"{service}={state.get('status', 'missing')}/{state.get('health', 'unknown')}"
                for service, state in states.items()
            )
            raise RuntimeError(f"Docker health verification timed out: {summary}")
        time.sleep(min(poll, max(1, int(deadline - time.time()))))


def _run_cmd_with_heartbeat(
    command: list[str],
    *,
    cwd: str,
    timeout: int,
    heartbeat,
    interval: int = 60,
):
    stop = threading.Event()
    heartbeat_errors = []

    def renew() -> None:
        while not stop.wait(max(0.01, interval)):
            try:
                heartbeat()
            except Exception as exc:
                heartbeat_errors.append(exc)
                stop.set()

    thread = threading.Thread(target=renew, name="docker-lock-heartbeat", daemon=True)
    thread.start()
    try:
        result = _run_cmd(command, cwd=cwd, timeout=timeout)
    finally:
        stop.set()
        thread.join(timeout=2)
    if heartbeat_errors:
        raise RuntimeError(f"Docker lock heartbeat failed: {heartbeat_errors[0]}")
    return result


def cmd_docker_restart(args: argparse.Namespace) -> None:
    """Drain dependent tests, restart allowlisted services, and verify health."""
    services = sorted(set(args.service))
    checkout_root = _docker_checkout_root(args.session)
    available = available_docker_services(checkout_root)
    invalid = sorted(set(services) - available)
    if invalid:
        raise RuntimeError(
            f"Services are not restartable: {', '.join(invalid)}. "
            f"Available services: {', '.join(sorted(available))}"
        )

    operation = request_docker_restart(args.session, services)
    lock_acquired = False
    persistent_coordination = _persistent_coordination_enabled()
    try:
        wait_for_docker_operation_admitted(operation["id"], timeout=args.timeout, poll=args.poll)
        if not persistent_coordination:
            _wait_and_acquire_session_lock(
                "docker_rebuild",
                args.session,
                phase="draining_tests",
                timeout=args.timeout,
                poll=args.poll,
                heartbeat=lambda: update_docker_operation(operation["id"], "admitted"),
            )
            lock_acquired = True

        def heartbeat() -> None:
            if not persistent_coordination:
                _acquire_session_lock("docker_rebuild", args.session, phase="draining_tests")
            update_docker_operation(operation["id"], "draining_tests")

        wait_for_docker_test_leases(
            operation["id"],
            timeout=args.timeout,
            poll=args.poll,
            heartbeat=heartbeat,
        )
        checkout_root = _ensure_product_runtime_checkout(refresh=True)
        source_commit = _current_git_sha(checkout_root)
        rc, backend_tree, stderr = _run_cmd(["git", "rev-parse", "HEAD:backend"], cwd=str(checkout_root))
        if rc != 0 or not backend_tree.strip():
            raise RuntimeError(f"Could not resolve product backend source generation: {stderr}")
        backend_tree = backend_tree.strip()
        incoherent_services = _incoherent_docker_services(checkout_root, backend_tree)
        coherent_services = sorted(set(services) | incoherent_services)
        added_services = sorted(set(coherent_services) - set(services))
        if added_services:
            print(
                "Expanding Docker restart to restore one source generation: " + ", ".join(added_services),
                flush=True,
            )
        services = coherent_services
        invalid = sorted(set(services) - available)
        if invalid:
            raise RuntimeError(f"Runtime-coherence services are not restartable: {', '.join(invalid)}")
        update_docker_operation(
            operation["id"],
            "restarting",
            waiting_for_tests=[],
            services=services,
            source_commit=source_commit,
            backend_tree=backend_tree,
        )
        if not persistent_coordination:
            _acquire_session_lock("docker_rebuild", args.session, phase="restarting")
        if getattr(args, "build", False):
            compose_args = ["up", "-d", "--no-deps", "--build", *services]
        elif incoherent_services:
            compose_args = ["up", "-d", "--no-deps", "--force-recreate", *services]
        else:
            compose_args = ["restart", *services]
        rc, stdout, stderr = _run_cmd_with_heartbeat(
            _docker_compose_command(*compose_args, checkout_root=checkout_root),
            cwd=str(checkout_root),
            timeout=max(120, args.timeout),
            heartbeat=lambda: (
                None if persistent_coordination else _acquire_session_lock("docker_rebuild", args.session, phase="restarting"),
                update_docker_operation(operation["id"], "restarting"),
            ),
        )
        if rc != 0:
            raise RuntimeError((stderr or stdout or "Docker Compose restart failed").strip())
        update_docker_operation(operation["id"], "verifying")
        if not persistent_coordination:
            _acquire_session_lock("docker_rebuild", args.session, phase="verifying")
        health = wait_for_docker_services_healthy(
            services,
            timeout=args.health_timeout,
            poll=args.poll,
            checkout_root=checkout_root,
            heartbeat=lambda: (
                None if persistent_coordination else _acquire_session_lock("docker_rebuild", args.session, phase="verifying"),
                update_docker_operation(operation["id"], "verifying"),
            ),
        )
        _record_product_runtime_services(services, checkout_root, source_commit, backend_tree)
        completed = update_docker_operation(operation["id"], "completed", health=health)
        print(
            f"Docker restart {completed['id']} completed for {', '.join(services)}; "
            "all services are running and healthy."
        )
    except BaseException as exc:
        try:
            update_docker_operation(
                operation["id"],
                "failed",
                error=str(exc) or type(exc).__name__,
            )
        except Exception:
            pass
        raise
    finally:
        if lock_acquired:
            _release_session_lock("docker_rebuild", released_by=args.session)


def cmd_docker_run_setup(args: argparse.Namespace) -> None:
    """Drain dependent tests and run allowlisted one-shot setup services."""
    services = sorted(set(args.service))
    checkout_root = _docker_checkout_root(args.session)
    available = available_docker_setup_services(checkout_root)
    invalid = sorted(set(services) - available)
    if invalid:
        raise RuntimeError(
            f"Services are not setup-runnable: {', '.join(invalid)}. "
            f"Available setup services: {', '.join(sorted(available))}"
        )

    operation = request_docker_restart(args.session, services)
    lock_acquired = False
    persistent_coordination = _persistent_coordination_enabled()
    try:
        wait_for_docker_operation_admitted(operation["id"], timeout=args.timeout, poll=args.poll)
        if not persistent_coordination:
            _wait_and_acquire_session_lock(
                "docker_rebuild",
                args.session,
                phase="draining_tests",
                timeout=args.timeout,
                poll=args.poll,
                heartbeat=lambda: update_docker_operation(operation["id"], "admitted"),
            )
            lock_acquired = True

        def heartbeat() -> None:
            if not persistent_coordination:
                _acquire_session_lock("docker_rebuild", args.session, phase="draining_tests")
            update_docker_operation(operation["id"], "draining_tests")

        wait_for_docker_test_leases(
            operation["id"],
            timeout=args.timeout,
            poll=args.poll,
            heartbeat=heartbeat,
        )
        checkout_root = _ensure_product_runtime_checkout(refresh=True)
        source_commit = _current_git_sha(checkout_root)
        rc, backend_tree, stderr = _run_cmd(["git", "rev-parse", "HEAD:backend"], cwd=str(checkout_root))
        if rc != 0 or not backend_tree.strip():
            raise RuntimeError(f"Could not resolve product backend source generation: {stderr}")

        update_docker_operation(
            operation["id"],
            "restarting",
            waiting_for_tests=[],
            services=services,
            source_commit=source_commit,
            backend_tree=backend_tree.strip(),
            action="run-setup",
        )
        if not persistent_coordination:
            _acquire_session_lock("docker_rebuild", args.session, phase="restarting")

        for service in services:
            compose_args = ["run", "--rm"]
            if getattr(args, "build", False):
                compose_args.append("--build")
            compose_args.append(service)
            rc, stdout, stderr = _run_cmd_with_heartbeat(
                _docker_compose_command(*compose_args, checkout_root=checkout_root),
                cwd=str(checkout_root),
                timeout=max(120, args.timeout),
                heartbeat=lambda: (
                    None if persistent_coordination else _acquire_session_lock("docker_rebuild", args.session, phase="restarting"),
                    update_docker_operation(operation["id"], "restarting"),
                ),
            )
            if rc != 0:
                raise RuntimeError((stderr or stdout or f"Docker setup run failed for {service}").strip())

        completed = update_docker_operation(operation["id"], "completed")
        print(
            f"Docker setup run {completed['id']} completed for {', '.join(services)}."
        )
    except BaseException as exc:
        try:
            update_docker_operation(
                operation["id"],
                "failed",
                error=str(exc) or type(exc).__name__,
            )
        except Exception:
            pass
        raise
    finally:
        if lock_acquired:
            _release_session_lock("docker_rebuild", released_by=args.session)


def cmd_docker(args: argparse.Namespace) -> None:
    try:
        if args.docker_action == "restart":
            cmd_docker_restart(args)
            return
        if args.docker_action == "run-setup":
            cmd_docker_run_setup(args)
            return
    except RuntimeError as exc:
        print(f"Docker operation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    raise RuntimeError(f"Unknown Docker action: {args.docker_action}")












def _health_lease_key(url: str) -> str:
    return f"api-health-{_health_url_key(url)}"


def _health_owner_key(session_id: str) -> str:
    """Use a restart-stable incident owner instead of a short-lived waiter PID."""
    return f"health-session:{session_id or 'manual'}"











def _active_lock_snapshot(lock_type: str) -> dict:
    """Return the active lock snapshot, or an empty dict when available/stale."""
    if lock_type == "docker_rebuild" and _persistent_coordination_enabled():
        operation = _persistent_active_docker_operation()
        if operation:
            return {
                "status": "IN_PROGRESS",
                "claimed_by": operation.get("session_id") or operation.get("id") or "persistent-docker",
                "phase": operation.get("status") or "queued",
                "since": operation.get("requested_at") or "",
                "last_updated": operation.get("updated_at") or operation.get("started_at") or operation.get("requested_at") or "",
                "commit_sha": "",
            }
        return {}
    data = _load_sessions()
    lock = data.get("locks", {}).get(lock_type, {})
    if _is_lock_active(lock, lock_type):
        return dict(lock)
    return {}


def _set_session_resource_wait(session_id: str, lock_type: str, lock: dict) -> None:
    """Publish a renewable, privacy-minimal resource wait for status consumers."""
    if not session_id:
        return

    def update(data: dict) -> None:
        sessions = data.setdefault("sessions", {})
        repository_session_id = session_id if session_id in sessions else next(
            (
                candidate_id
                for candidate_id, candidate in sessions.items()
                if isinstance(candidate, dict) and candidate.get("opencode_session_id") == session_id
            ),
            "",
        )
        if not repository_session_id:
            return
        session = sessions[repository_session_id]
        session["resource_wait"] = {
            "status": "waiting",
            "resource": lock_type,
            "owner_session_id": str(lock.get("claimed_by") or ""),
            "owner_phase": str(lock.get("phase") or ""),
            "heartbeat_at": _now_iso(),
            "waiter_pid": os.getpid(),
        }
        session["last_active"] = session["resource_wait"]["heartbeat_at"]

    _mutate_sessions(update)


def _clear_session_resource_wait(session_id: str, lock_type: str) -> None:
    """Clear only the matching wait so an older waiter cannot erase a newer one."""
    if not session_id:
        return

    def update(data: dict) -> None:
        for candidate_id, session in data.setdefault("sessions", {}).items():
            if candidate_id != session_id and session.get("opencode_session_id") != session_id:
                continue
            wait = session.get("resource_wait")
            if isinstance(wait, dict) and wait.get("resource") == lock_type and wait.get("waiter_pid") == os.getpid():
                session.pop("resource_wait", None)
            return

    _mutate_sessions(update)


def _prune_stale_resource_waits(data: dict) -> int:
    """Remove durable wait markers whose waiter died or stopped heartbeating."""
    removed = 0
    for session in data.get("sessions", {}).values():
        if not isinstance(session, dict):
            continue
        wait = session.get("resource_wait")
        if not isinstance(wait, dict) or wait.get("status") != "waiting":
            continue
        heartbeat_at = str(wait.get("heartbeat_at") or "")
        try:
            waiter_pid = int(wait.get("waiter_pid") or 0)
        except (TypeError, ValueError):
            waiter_pid = 0
        heartbeat_stale = not heartbeat_at or _minutes_since(heartbeat_at) > 3
        waiter_dead = waiter_pid > 0 and not _process_is_alive(waiter_pid)
        if heartbeat_stale or waiter_dead:
            session.pop("resource_wait", None)
            removed += 1
    return removed


def _health_url_key(url: str) -> str:
    """Return a compact sessions.json key for a health URL."""
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]


def _probe_health_url(url: str, *, timeout: int = API_HEALTH_PROBE_TIMEOUT_SECONDS) -> dict:
    """Probe a shared runtime health URL without raising on 5xx/connection errors."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OpenMates-sessions-health-wait/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:  # noqa: S310
            status_code = int(response.getcode() or 0)
            return {"ok": 200 <= status_code < 300, "status_code": status_code, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status_code": int(exc.code or 0), "error": str(exc.reason or exc)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status_code": 0, "error": str(getattr(exc, "reason", None) or exc)}


def _resource_wait_repository_session_id(data: dict, session_id: str) -> str:
    """Resolve a repository session id for wait/incident status if possible."""
    if not session_id:
        return ""
    sessions = data.setdefault("sessions", {})
    if session_id in sessions:
        return session_id
    for candidate_id, candidate in sessions.items():
        if isinstance(candidate, dict) and candidate.get("opencode_session_id") == session_id:
            return candidate_id
    return ""


def _health_incident_live(incident: dict | None) -> bool:
    """Return whether a health incident still has a live owner."""
    if not isinstance(incident, dict) or incident.get("status") != "investigating":
        return False
    heartbeat_at = str(incident.get("heartbeat_at") or "")
    heartbeat_stale = not heartbeat_at or (_minutes_since(heartbeat_at) * 60) > API_HEALTH_INCIDENT_STALE_SECONDS
    try:
        owner_pid = int(incident.get("owner_pid") or 0)
    except (TypeError, ValueError):
        owner_pid = 0
    owner_dead = (
        owner_pid > 0
        and incident.get("owner_host") == socket.gethostname()
        and not _process_is_alive(owner_pid)
    )
    return not heartbeat_stale and not owner_dead


def _claim_api_health_incident(session_id: str, url: str, probe: dict) -> dict:
    """Elect exactly one live chat to investigate a shared API health failure."""

    def mutate(data: dict) -> dict:
        incidents = _infrastructure_state(data).setdefault("health_incidents", {})
        key = _health_url_key(url)
        now = _now_iso()
        owner_session_id = _resource_wait_repository_session_id(data, session_id) or session_id or "manual"
        current = incidents.get(key)
        current_owner = str(current.get("owner_session_id") or "") if isinstance(current, dict) else ""
        same_owner = (
            isinstance(current, dict)
            and current_owner == owner_session_id
            and current.get("owner_host") == socket.gethostname()
        )
        if _health_incident_live(current) and not same_owner:
            current["last_observed_at"] = now
            current["last_status_code"] = int(probe.get("status_code") or 0)
            current["last_error"] = str(probe.get("error") or "")
            return {"owned": False, "incident": dict(current)}
        incident = {
            "status": "investigating",
            "url": url,
            "key": key,
            "owner_session_id": owner_session_id,
            "owner_pid": os.getpid(),
            "owner_host": socket.gethostname(),
            "claimed_at": str(current.get("claimed_at") or now) if isinstance(current, dict) and same_owner else now,
            "heartbeat_at": now,
            "last_status_code": int(probe.get("status_code") or 0),
            "last_error": str(probe.get("error") or ""),
        }
        incidents[key] = incident
        return {"owned": True, "incident": dict(incident)}

    return _mutate_sessions(mutate)


def _clear_api_health_incident(url: str) -> None:
    """Clear an API health incident once the shared health probe is green again."""

    def mutate(data: dict) -> None:
        incidents = _infrastructure_state(data).setdefault("health_incidents", {})
        incidents.pop(_health_url_key(url), None)

    _mutate_sessions(mutate)


def cmd_wait_lock(args: argparse.Namespace) -> None:
    """Wait for a shared lock to become available instead of verbally pausing."""
    lock_type = _normalize_lock_type(args.type)
    if lock_type not in ("docker_rebuild", "vercel_deploy"):
        print(f"Error: Unknown lock type '{args.type}'.", file=sys.stderr)
        sys.exit(1)

    follow = bool(getattr(args, "follow", False))
    timeout = args.timeout
    if timeout is None and not follow:
        timeout = _lock_stale_minutes(lock_type) * 60
    poll = max(1, args.poll)
    deadline = None if timeout is None else time.time() + max(0, timeout)
    last_report = 0.0
    last_owner_signature: tuple[str, str] | None = None

    try:
        while True:
            lock = _active_lock_snapshot(lock_type)
            if not lock:
                print(json.dumps({
                    "signal": "OPENMATES_WAIT_READY",
                    "resource": lock_type,
                    "session_id": args.session or "",
                    "operation_type": "resource_ready",
                    "operation_key": lock_type,
                    "next_action": "Continue the exact operation interrupted by this resource wait without redoing completed work.",
                }, sort_keys=True))
                print(f"Lock '{lock_type}' is available; continue the interrupted operation in this chat.")
                return

            _set_session_resource_wait(args.session or "", lock_type, lock)
            now = time.time()
            if deadline is not None and now >= deadline:
                print(_format_lock_block_message(lock_type, lock), file=sys.stderr)
                print(
                    f"Timed out after {timeout}s waiting for lock '{lock_type}'. "
                    "Do not force-unlock unless you have confirmed the other deploy/test is inactive.",
                    file=sys.stderr,
                )
                sys.exit(1)

            owner_signature = (str(lock.get("claimed_by") or ""), str(lock.get("phase") or ""))
            if owner_signature != last_owner_signature or last_report == 0.0 or now - last_report >= 60:
                commit = str(lock.get("commit_sha") or "")[:9]
                commit_text = f", commit {commit}" if commit else ""
                print(
                    f"Waiting for lock '{lock_type}' held by {lock.get('claimed_by', '?')}"
                    f"{commit_text}, phase {lock.get('phase', '?')}...",
                    flush=True,
                )
                last_report = now
                last_owner_signature = owner_signature

            sleep_for = poll if deadline is None else min(poll, max(1, int(deadline - now)))
            time.sleep(sleep_for)
    finally:
        _clear_session_resource_wait(args.session or "", lock_type)




def cmd_wait_health(args: argparse.Namespace) -> None:
    """Wait for shared API health or elect one chat to investigate a real incident."""
    url = (args.url or API_HEALTH_DEFAULT_URL).strip()
    follow = bool(getattr(args, "follow", False))
    timeout = args.timeout
    if timeout is None and not follow:
        timeout = API_HEALTH_INCIDENT_STALE_SECONDS
    poll = max(1, args.poll)
    probe_timeout = max(1, args.probe_timeout)
    deadline = None if timeout is None else time.time() + max(0, timeout)
    last_report = 0.0
    last_owner_signature: tuple[str, str] | None = None
    health_resource = "api_health"

    try:
        while True:
            probe = _probe_health_url(url, timeout=probe_timeout)
            if probe.get("ok"):
                _clear_api_health_incident(url)
                print(json.dumps({"signal": "OPENMATES_HEALTH_READY", "url": url, "session_id": args.session or ""}, sort_keys=True))
                print(f"Health URL {url} is ready; continue the interrupted operation in this chat.")
                return

            docker_lock = _active_lock_snapshot("docker_rebuild")
            if docker_lock:
                _set_session_resource_wait(args.session or "", health_resource, docker_lock)
                owner_signature = (
                    str(docker_lock.get("claimed_by") or ""),
                    str(docker_lock.get("phase") or ""),
                )
                owner_text = str(docker_lock.get("claimed_by") or "?")
                phase_text = str(docker_lock.get("phase") or "?")
                waiting_text = (
                    f"Waiting for API health {url}; Docker/runtime operation held by "
                    f"{owner_text}, phase {phase_text}. "
                    f"Last health status: {probe.get('status_code') or probe.get('error') or 'unavailable'}."
                )
            else:
                claim = _claim_api_health_incident(args.session or "", url, probe)
                incident = claim.get("incident") if isinstance(claim.get("incident"), dict) else {}
                if claim.get("owned"):
                    print(
                        json.dumps(
                            {
                                "signal": "OPENMATES_HEALTH_INVESTIGATE",
                                "url": url,
                                "session_id": incident.get("owner_session_id") or args.session or "",
                                "status_code": probe.get("status_code") or 0,
                                "error": probe.get("error") or "",
                            },
                            sort_keys=True,
                        )
                    )
                    print(
                        "No active Docker/runtime operation owns this health failure. "
                        "This chat is the single API-health investigator; diagnose or restart through "
                        "python3 scripts/sessions.py docker restart --session "
                        f"{args.session or '<repository-session-id>'} --service api [--build]. "
                        "Other chats should keep waiting for OPENMATES_HEALTH_READY.",
                    )
                    return
                _set_session_resource_wait(
                    args.session or "",
                    health_resource,
                    {
                        "claimed_by": incident.get("owner_session_id") or "api-health-investigator",
                        "phase": "health_investigating",
                    },
                )
                owner_signature = (
                    str(incident.get("owner_session_id") or ""),
                    "health_investigating",
                )
                waiting_text = (
                    f"Waiting for API health {url}; incident investigator is "
                    f"{incident.get('owner_session_id') or '?'}. "
                    f"Last health status: {probe.get('status_code') or probe.get('error') or 'unavailable'}."
                )

            now = time.time()
            if deadline is not None and now >= deadline:
                print(
                    f"Timed out after {timeout}s waiting for API health {url}. "
                    "If no Docker operation or health investigator is live, rerun wait-health so one chat can take over.",
                    file=sys.stderr,
                )
                sys.exit(1)

            if owner_signature != last_owner_signature or last_report == 0.0 or now - last_report >= 60:
                print(waiting_text, flush=True)
                last_report = now
                last_owner_signature = owner_signature

            sleep_for = poll if deadline is None else min(poll, max(1, int(deadline - now)))
            time.sleep(sleep_for)
    finally:
        _clear_session_resource_wait(args.session or "", health_resource)


def _wait_and_acquire_session_lock(
    lock_type: str,
    session_id: str,
    *,
    commit_sha: str = "",
    phase: str = "",
    timeout: int | None = None,
    poll: int = 30,
    heartbeat=None,
) -> bool:
    """Wait for a shared lock and acquire it in the same loop to avoid races."""
    if timeout is None:
        timeout = _lock_stale_minutes(lock_type) * 60
    poll = max(1, poll)
    deadline = time.time() + max(0, timeout)
    last_report = 0.0
    last_error = ""

    while True:
        try:
            return _acquire_session_lock(lock_type, session_id, commit_sha=commit_sha, phase=phase)
        except RuntimeError as exc:
            last_error = str(exc)
            if heartbeat:
                heartbeat()

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
    if any(VISUAL_SMOKE_PLAN_PATH_RE.search(f) for f in files):
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


def _proof_video_delivery_required() -> bool:
    return False


def _proof_video_runtime_files(files: list[str]) -> list[str]:
    has_test_recording_cleanup = any(
        f == "backend/core/api/app/routes/test_recordings.py"
        or f.startswith("frontend/apps/web_app/src/routes/tests/")
        for f in files
    )
    if has_test_recording_cleanup:
        files = [f for f in files if f not in PROOF_VIDEO_DEV_TEST_RECORDING_CLEANUP_PATHS]
    return [
        f
        for f in files
        if PROOF_VIDEO_PRODUCT_PATH_RE.search(f)
        and "/tests/" not in f
        and "/__tests__/" not in f
        and not f.endswith((".test.ts", ".spec.ts", ".md"))
    ]


def _playwright_spec_requires_proof_video(file: str) -> bool:
    try:
        text = (PROJECT_ROOT / file).read_text(encoding="utf-8")
    except OSError:
        return True
    match = PROOF_VIDEO_NOT_REQUIRED_RE.search(text)
    return not (match and match.group(1) in PROOF_VIDEO_NOT_REQUIRED_REASONS)


def _requires_proof_video(session: dict, files: list[str]) -> bool:
    if not files:
        return False
    if any(PROOF_VIDEO_EXAMPLE_CHAT_PATH_RE.search(f) for f in files):
        return True
    mode = str(session.get("mode") or "").strip().lower()
    if mode == "feature" and _proof_video_runtime_files(files):
        return True
    if mode == "testing":
        e2e_files = [f for f in files if PROOF_VIDEO_E2E_PATH_RE.search(f)]
        return any(_playwright_spec_requires_proof_video(f) for f in e2e_files)
    return False


def _proof_video_manifest_problems(
    manifest: dict,
    *,
    delivery_required: bool,
    run_dir: Path | None = None,
) -> list[str]:
    problems: list[str] = []
    if manifest.get("privacy", {}).get("status") not in PROOF_VIDEO_PRIVACY_ACCEPTED_STATUSES:
        problems.append("proof privacy state is not finalized")
    review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
    if review.get("status") != "passed":
        problems.append("frame review has not passed")
    elif run_dir is not None:
        try:
            try:
                from scripts.spec_demo import require_review_receipt_integrity
            except ModuleNotFoundError:
                from spec_demo import require_review_receipt_integrity

            publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
            require_review_receipt_integrity(
                run_dir,
                manifest,
                verify_video=publication.get("status") != "delivered",
            )
        except Exception as exc:
            problems.append(f"invalid frame-review receipt: {exc}")
    if not isinstance(review.get("attempt_count"), int) or review.get("attempt_count", 0) < 1:
        problems.append("missing review attempt count")
    audio = manifest.get("narration_audio") if isinstance(manifest.get("narration_audio"), dict) else {}
    video_metadata = manifest.get("video_metadata") if isinstance(manifest.get("video_metadata"), dict) else {}
    audio_status = audio.get("status")
    if audio_status not in {"passed", "not_required"}:
        problems.append("narration audio must be passed or intentionally disabled")
    if audio_status == "passed":
        if audio.get("provider") != "elevenlabs" or audio.get("model") != "eleven_flash_v2_5":
            problems.append("narration audio must use ElevenLabs eleven_flash_v2_5")
        if not str(audio.get("path") or "").strip() or not str(audio.get("sha256") or "").startswith("sha256:"):
            problems.append("narration audio provenance is incomplete")
        if video_metadata.get("has_audio") is not True:
            problems.append("rendered video is missing requested narration audio")
    device_profile = str(video_metadata.get("device_profile") or "")
    if device_profile:
        expected_size = PROOF_VIDEO_DEVICE_PROFILES.get(device_profile)
        if expected_size is None:
            problems.append(f"unknown proof-video device profile: {device_profile}")
        elif (video_metadata.get("width"), video_metadata.get("height")) != expected_size:
            problems.append(f"{device_profile} proof video must be {expected_size[0]}x{expected_size[1]}")
        if video_metadata.get("target_width") != video_metadata.get("width") or video_metadata.get("target_height") != video_metadata.get("height"):
            problems.append("proof-video target dimensions do not match rendered dimensions")
        black_bar = video_metadata.get("black_bar_scan_status")
        if not isinstance(black_bar, dict) or black_bar.get("status") != "passed":
            problems.append("proof-video black-bar scan has not passed")
    captions = manifest.get("captions")
    if not isinstance(captions, list) or not captions:
        problems.append("caption evidence is missing")
    publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
    if delivery_required and publication.get("status") != "delivered":
        problems.append("OpenCode response-media proof embed has not completed")
    return problems


def _proof_video_record_problems(record: dict, expected_commit: str | None) -> list[str]:
    problems: list[str] = []
    if record.get("status") not in PROOF_VIDEO_PASS_STATUSES:
        problems.append("record is not passed")
    if not _commit_matches(str(record.get("subject_commit") or ""), expected_commit):
        problems.append("subject commit does not match")
    manifest_value = str(record.get("manifest_path") or "").strip()
    if not manifest_value:
        problems.append("missing manifest_path")
        return problems
    manifest_path = Path(manifest_value)
    if not manifest_path.is_absolute():
        manifest_path = PROJECT_ROOT / manifest_path
    if not manifest_path.is_file():
        problems.append("manifest_path does not exist")
        return problems
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"could not parse manifest: {exc}")
        return problems
    problems.extend(
        _proof_video_manifest_problems(
            manifest,
            delivery_required=_proof_video_delivery_required(),
            run_dir=manifest_path.parent,
        )
    )
    return problems


def _latest_proof_video_record(session: dict, expected_commit: str | None = None) -> dict | None:
    records = session.get("proof_videos")
    if not isinstance(records, list):
        return None
    for record in reversed(records):
        if isinstance(record, dict) and not _proof_video_record_problems(record, expected_commit):
            return record
    return None


def _pending_proof_video_records_requiring_proof(session: dict) -> list[dict]:
    records = session.get("proof_video_pending")
    if not isinstance(records, list):
        return []
    requiring_proof: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        files = record.get("files")
        if not isinstance(files, list) or not all(isinstance(file, str) for file in files):
            requiring_proof.append(record)
            continue
        if _requires_proof_video(session, files):
            requiring_proof.append(record)
    return requiring_proof


def _proof_video_manifest_record(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
    privacy = manifest.get("privacy") if isinstance(manifest.get("privacy"), dict) else {}
    publication = manifest.get("publication") if isinstance(manifest.get("publication"), dict) else {}
    audio = manifest.get("narration_audio") if isinstance(manifest.get("narration_audio"), dict) else {}
    delivery_required = _proof_video_delivery_required()
    manifest_problems = _proof_video_manifest_problems(
        manifest,
        delivery_required=delivery_required,
        run_dir=run_dir,
    )
    record = {
        "status": "passed" if not manifest_problems else "pending",
        "proof_id": manifest.get("spec_id", "session-proof"),
        "run_dir": str(run_dir),
        "manifest_path": str(run_dir / "manifest.json"),
        "subject_commit": str(manifest.get("subject_commit") or ""),
        "privacy_status": privacy.get("status", "pending"),
        "review_status": review.get("status", "pending"),
        "review_run_id": review.get("run_id", ""),
        "review_attempts": review.get("attempt_count", 0),
        "audio_status": audio.get("status", "pending"),
        "audio_provider": audio.get("provider", ""),
        "audio_model": audio.get("model", ""),
        "publication_status": publication.get("status", "pending"),
        "delivery_required": delivery_required,
        "problems": manifest_problems,
        "timestamp": _now_iso(),
    }
    blocker_media = _proof_video_blocker_media_record(run_dir, manifest)
    if blocker_media:
        record["blocker_media"] = blocker_media
    return record


def _upsert_proof_video_record(session: dict, run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    record = _proof_video_manifest_record(run_dir, manifest)
    subject_commit = record.get("subject_commit")
    pending = session.get("proof_video_pending")
    if subject_commit and isinstance(pending, list):
        pending[:] = [existing for existing in pending if not isinstance(existing, dict) or existing.get("subject_commit") != subject_commit]
    records = session.setdefault("proof_videos", [])
    if not isinstance(records, list):
        session["proof_videos"] = records = []
    run_dir_text = str(run_dir)
    for index, existing in enumerate(records):
        if isinstance(existing, dict) and existing.get("run_dir") == run_dir_text:
            records[index] = record
            return record
    records.append(record)
    return record


def _enforce_proof_video_end_gate(
    sid: str,
    session: dict,
    files: list[str],
    *,
    commit_sha: str | None = None,
) -> None:
    if not _requires_proof_video(session, files):
        return
    expected_commit = commit_sha or _current_head()
    if _latest_proof_video_record(session, expected_commit):
        print("Proof video gate: PASSED")
        return
    if not _pending_proof_video_records_requiring_proof(session) and _latest_proof_video_record(session):
        print("Proof video gate: PASSED")
        return
    print("PROOF VIDEO REQUIRED — session cannot be ended yet.", file=sys.stderr)
    print("This session changed a product feature, example chat, or actively-debugged E2E proof surface.", file=sys.stderr)
    print("Create a captioned proof video with bounded frame review:", file=sys.stderr)
    print("  python3 scripts/proof_video_workflow.py start --current --spec <name>.spec.ts", file=sys.stderr)
    sys.exit(1)


def _record_proof_video_deploy_pending(
    sid: str,
    session: dict,
    files: list[str],
    *,
    commit_sha: str | None = None,
) -> None:
    if not _requires_proof_video(session, files):
        return
    expected_commit = commit_sha or _current_head()
    if _latest_proof_video_record(session, expected_commit):
        print("Proof video gate: PASSED")
        return
    record = {
        "status": "pending",
        "subject_commit": expected_commit,
        "files": sorted(files),
        "timestamp": _now_iso(),
        "next_action": "python3 scripts/proof_video_workflow.py start --current --spec <name>.spec.ts",
    }

    def update(data: dict) -> None:
        latest_session = data.get("sessions", {}).get(sid)
        if not isinstance(latest_session, dict):
            return
        records = latest_session.setdefault("proof_video_pending", [])
        if not isinstance(records, list):
            latest_session["proof_video_pending"] = records = []
        records[:] = [existing for existing in records if not isinstance(existing, dict) or existing.get("subject_commit") != expected_commit]
        records.append(record)

    _mutate_sessions(update)
    print("DEPLOYED BUT PROOF VIDEO REQUIRED — session cannot be marked complete yet.", file=sys.stderr)
    print("This deploy changed a product feature, example chat, or actively-debugged E2E proof surface.", file=sys.stderr)
    print("Create a captioned proof video with bounded frame review:", file=sys.stderr)
    print("  python3 scripts/proof_video_workflow.py start --current --spec <name>.spec.ts", file=sys.stderr)
    print("Then rerun session completion after the proof video is recorded.", file=sys.stderr)


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
        or f.startswith("frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/")
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


SPECIFICATION_GATE_MIN_TIMEOUT_SECONDS = 60
SPECIFICATION_GATE_MAX_TIMEOUT_SECONDS = 600


def _specification_gate_timeout_seconds(relevant_file_count: int) -> int:
    """Return a bounded timeout for Specification checks over large migrations."""
    return min(
        SPECIFICATION_GATE_MAX_TIMEOUT_SECONDS,
        max(SPECIFICATION_GATE_MIN_TIMEOUT_SECONDS, SPECIFICATION_GATE_MIN_TIMEOUT_SECONDS + max(0, relevant_file_count)),
    )


def _run_specification_gate(files: list[str], *, session_id: str, checkout_root: Path) -> None:
    """Block unresolved changed tests and unapproved Specification bundle hashes."""
    relevant = [
        path
        for path in files
        if path.startswith("specifications/")
        or path.startswith("docs/plans/") and Path(path).name == "plan.yml"
        or path.endswith((".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx", ".spec.js", ".test.js", "Tests.swift", "_test.py"))
        or Path(path).name.startswith("test_") and path.endswith(".py")
    ]
    if not relevant:
        return
    script = checkout_root / "scripts" / "specifications.py"
    if not script.exists():
        raise RuntimeError("Specification gate unavailable: scripts/specifications.py is missing")
    cmd = [
        sys.executable,
        str(script),
        "check-changed",
        *relevant,
        "--session",
        session_id,
        "--repo-root",
        str(checkout_root),
        "--approvals-file",
        str(CONTROL_PLANE_ROOT / "scripts" / ".specifications-approvals-state.json"),
    ]
    timeout_seconds = _specification_gate_timeout_seconds(len(relevant))
    try:
        result = subprocess.run(cmd, cwd=str(checkout_root), capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"SPECIFICATION GATE TIMEOUT — check-changed exceeded {timeout_seconds}s "
            f"for {len(relevant)} changed file(s)."
        ) from exc
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "Specification gate failed"
        raise RuntimeError(f"SPECIFICATION GATE FAILED\n{detail.strip()}")
    print("Specification gate: PASSED")


SPECIFICATION_GENERATED_FILES = (
    "specifications/generated/registry.yml",
    "specifications/generated/assertion-index.yml",
    "specifications/generated/coverage.yml",
)


def _should_regenerate_specification_artifacts(files: list[str]) -> bool:
    """Return True when deploy inputs can change Specification-generated artifacts."""

    return any(
        path.startswith("specifications/")
        or path.startswith("docs/plans/") and Path(path).name == "plan.yml"
        or path.endswith((".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx", ".spec.js", ".test.js", "Tests.swift", "_test.py"))
        or Path(path).name.startswith("test_") and path.endswith(".py")
        for path in files
    )


def _regenerate_specification_artifacts_for_deploy(files: list[str], *, checkout_root: Path) -> list[str]:
    """Regenerate and stage Specification artifacts inside a disposable deploy checkout."""

    if not _should_regenerate_specification_artifacts(files):
        return []
    script = checkout_root / "scripts" / "specifications.py"
    if not script.exists():
        raise RuntimeError("Specification generation unavailable: scripts/specifications.py is missing")
    print("Regenerating Specification artifacts for integration checkout...")
    rc, stdout, stderr = _run_cmd(
        [sys.executable, str(script), "generate", "--repo-root", str(checkout_root)],
        cwd=str(checkout_root),
        timeout=120,
    )
    if rc != 0:
        detail = stderr or stdout or "Specification artifact generation failed"
        raise RuntimeError(detail)
    rc, _stdout, stderr = _run_cmd(
        ["git", "add", "--", *SPECIFICATION_GENERATED_FILES],
        cwd=str(checkout_root),
    )
    if rc != 0:
        raise RuntimeError(f"Could not stage Specification-generated artifacts: {stderr}")
    staged = _get_staged_files(checkout_root=checkout_root)
    generated = [path for path in SPECIFICATION_GENERATED_FILES if path in staged]
    if generated:
        print("Specification artifacts: REGENERATED")
    else:
        print("Specification artifacts: CURRENT")
    return generated


def _run_deploy_gates(
    files: list[str],
    *,
    checkout_root: Path,
    no_verify: bool,
    skip_tests_reason: str | None,
    require_parity: bool,
    session_id: str | None = None,
) -> None:
    """Run source-dependent deploy gates against one authoritative checkout."""
    if session_id:
        _run_specification_gate(files, session_id=session_id, checkout_root=checkout_root)

    _enforce_embed_registry_validation(files, checkout_root=checkout_root)

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
    checkout_root = _session_checkout_root(session)

    worktree_metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None
    dirty_files = _get_dirty_files(checkout_root=checkout_root)
    try:
        to_commit, selector = _resolve_deploy_selection(
            session,
            exclude=exclude,
            use_staged=bool(getattr(args, "use_staged", False)),
            only=list(getattr(args, "only", None) or []),
        )
    except RuntimeError as exc:
        print(f"DEPLOY PLAN FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
    manifest = _build_deploy_manifest(sid, session, to_commit, selector=selector)
    tracked_but_clean = [f for f in modified if f not in dirty_files]
    dirty_but_untracked = [f for f in dirty_files if f not in modified]
    excluded = [f for f in modified if f in exclude]

    print("== DEPLOYMENT PLAN ==")
    print(f"Session: {sid}")
    print(f"Task: {session.get('task', '?')}")
    print(f"Selector: {selector}")
    print(f"Manifest: {manifest['manifest_id']}")
    if manifest["patch_id"]:
        print(f"Patch: {manifest['patch_id']}")
    if not _session_is_control_plane_repo(session):
        print(f"Repo: {_session_repo_name(session)} ({_session_repo_branch(session)})")
        print(f"Checkout: {checkout_root}")
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
            if _session_repo_id(other_info) != _session_repo_id(session):
                continue
            for of in other_info.get("modified_files", []):
                file_tracking[of] = other_sid

        print("Warning — dirty files NOT tracked by this session:")
        for f in sorted(dirty_but_untracked):
            tracked_session = file_tracking.get(f)
            tag = f"  [also tracked by: {tracked_session}; advisory]" if tracked_session else ""
            print(f"  ? {f}{tag}")
        print()

    # Deployment planning must stay a quick, non-blocking preview. The deploy
    # command and pre-commit hook run the authoritative lint gate; running the
    # same potentially multi-minute lint here caused callers with ordinary tool
    # timeouts to be killed mid-turn and left OpenCode tool records stale.
    if to_commit:
        lint_flags = _get_lint_flags(to_commit)
        if lint_flags and _session_is_control_plane_repo(session):
            print("Lint: DEFERRED (authoritative blocking gate runs during deploy)")
        elif lint_flags:
            print(f"Lint: SKIPPED ({_session_repo_name(session)} has no OpenMates lint_changed.sh gate)")
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
    related = _find_related_docs(modified) if _session_is_control_plane_repo(session) else []
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
    if source_files and _session_is_control_plane_repo(session):
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


def _runtime_epoch_identity() -> str:
    """Return a non-secret product runtime identity when one is recorded."""
    try:
        payload = json.loads(PRODUCT_RUNTIME_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    for key in ("runtime_epoch", "deployed_commit", "commit", "revision"):
        value = str(payload.get(key) or "")
        if value:
            return value
    return ""


def cmd_verify_prepared(args: argparse.Namespace) -> None:
    """Run one allowlisted exact-patch profile without installing in its worktree."""
    data = _load_sessions()
    session = data.get("sessions", {}).get(args.session)
    if not isinstance(session, dict):
        raise RuntimeError(f"Session {args.session} not found")
    files, selector = _resolve_deploy_selection(
        session,
        exclude=set(),
        use_staged=bool(args.use_staged),
        only=list(args.only or []),
    )
    if not files:
        raise RuntimeError("Prepared verification requires a non-empty exact session patch")
    manifest = _build_deploy_manifest(args.session, session, files, selector=selector)
    expected_manifest = str(args.expected_manifest_id or "")
    if expected_manifest and expected_manifest != manifest["manifest_id"]:
        raise RuntimeError(
            "Prepared verification manifest changed; rerun prepare-deploy and use its current manifest ID"
        )

    if args.profile == "installed-cli-identity":
        result = {
            "status": "inspected",
            "profile": args.profile,
            "base_commit": str((session.get("worktree") or {}).get("base_commit") or ""),
            "patch_id": manifest["patch_id"],
            "manifest_id": manifest["manifest_id"],
            "lockfile_identity": _prepared_dependency_identity(_session_checkout_root(session)),
            "runtime_epoch": _runtime_epoch_identity(),
            "cli": _installed_cli_identity(
                _session_checkout_root(session),
                executable=str(args.executable or ""),
            ),
        }
        print(json.dumps(result, sort_keys=True))
        return

    profile = PREPARED_VERIFICATION_PROFILES.get(args.profile)
    if profile is None:
        raise RuntimeError(f"Unknown prepared verification profile: {args.profile}")
    metadata = session.get("worktree") if isinstance(session.get("worktree"), dict) else None
    if not metadata:
        raise RuntimeError("Prepared verification requires a managed session worktree")
    prepared_base = _fetch_origin_dev_commit()
    integration = _prepare_integration_worktree(
        args.session,
        metadata,
        files,
        manifest["patch_id"],
        prepared_base,
    )
    checkout = Path(integration["path"])
    try:
        lockfile_identity = _link_prepared_dependencies(
            checkout,
            CONTROL_PLANE_ROOT,
            list(profile["dependency_paths"]),
        )
        command = list(profile["command"])
        completed = subprocess.run(
            command,
            cwd=str(checkout),
            capture_output=True,
            text=True,
            timeout=int(profile["timeout"]),
            check=False,
            env={**os.environ, "CI": "1"},
        )
        result = {
            "status": "passed" if completed.returncode == 0 else "failed",
            "profile": args.profile,
            "base_commit": prepared_base,
            "patch_id": manifest["patch_id"],
            "manifest_id": manifest["manifest_id"],
            "lockfile_identity": lockfile_identity,
            "runtime_epoch": _runtime_epoch_identity(),
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
        }
        print(json.dumps(result, sort_keys=True))
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)
    finally:
        _remove_integration_worktree(integration)


def _fetch_origin_dev_commit() -> str:
    """Fetch and return the exact current origin/dev commit."""
    rc, _stdout, stderr = _run_cmd(["git", "fetch", "origin", "dev"], cwd=str(CONTROL_PLANE_ROOT))
    if rc != 0:
        raise RuntimeError(f"Could not fetch origin/dev: {stderr}")
    rc, stdout, stderr = _run_cmd(["git", "rev-parse", "origin/dev"], cwd=str(CONTROL_PLANE_ROOT))
    if rc != 0 or not stdout:
        raise RuntimeError(f"Could not resolve origin/dev: {stderr}")
    return stdout.strip()


def _required_control_plane_deploy_protocol_version(origin_ref: str) -> int:
    """Read the deploy protocol required by origin/dev, defaulting legacy refs to v1."""
    rc, stdout, stderr = _run_cmd(
        ["git", "show", f"{origin_ref}:{CONTROL_PLANE_DEPLOY_PROTOCOL_FILE}"],
        cwd=str(CONTROL_PLANE_ROOT),
    )
    if rc != 0:
        commit_rc, _commit_stdout, commit_stderr = _run_cmd(
            ["git", "cat-file", "-e", f"{origin_ref}^{{commit}}"],
            cwd=str(CONTROL_PLANE_ROOT),
        )
        if commit_rc == 0:
            return 1
        raise RuntimeError(f"Could not inspect control-plane deploy protocol at {origin_ref}: {stderr or commit_stderr}")
    try:
        version = int(stdout.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"Malformed control-plane deploy protocol in {CONTROL_PLANE_DEPLOY_PROTOCOL_FILE}: {stdout!r}"
        ) from exc
    if version < 1:
        raise RuntimeError(
            f"Malformed control-plane deploy protocol in {CONTROL_PLANE_DEPLOY_PROTOCOL_FILE}: {stdout!r}"
        )
    return version


def _enforce_control_plane_deploy_protocol_compatible(origin_ref: str) -> None:
    required = _required_control_plane_deploy_protocol_version(origin_ref)
    if required > CONTROL_PLANE_DEPLOY_PROTOCOL_VERSION:
        raise RuntimeError(
            f"origin/dev requires control-plane deploy protocol v{required}, "
            f"but this runtime supports v{CONTROL_PLANE_DEPLOY_PROTOCOL_VERSION}. "
            "Restart OpenCode onto the current control plane before deploying."
        )


def _fast_forward_control_plane(commit_hash: str) -> None:
    """Advance the local dev checkout after a successful integration push."""
    if not commit_hash:
        raise RuntimeError("Cannot fast-forward the control plane without a commit hash")
    current = _current_git_sha(CONTROL_PLANE_ROOT)
    if current == commit_hash:
        return
    rc, _stdout, stderr = _run_cmd(
        ["git", "merge", "--ff-only", commit_hash],
        cwd=str(CONTROL_PLANE_ROOT),
        timeout=300,
    )
    if rc != 0 or _current_git_sha(CONTROL_PLANE_ROOT) != commit_hash:
        raise RuntimeError(
            "Integration pushed successfully, but the local control-plane checkout could not fast-forward: "
            f"{stderr or 'HEAD did not reach the pushed commit'}"
        )


def _control_plane_sync_warning(commit_hash: str) -> str:
    """Describe local checkout lag without mutating or downgrading a pushed deploy."""
    if not commit_hash or _current_git_sha(CONTROL_PLANE_ROOT) == commit_hash:
        return ""
    return (
        "LOCAL CONTROL-PLANE CHECKOUT STALE — informational only; deployment_affected=false. "
        f"The commit was pushed successfully as {commit_hash}. Preserve unrelated dirty files and "
        "update this local checkout separately when convenient."
    )


def _integration_commit_message(args: argparse.Namespace, session: dict) -> str:
    """Build the existing deploy commit message without checkout side effects."""
    commit_msg = str(getattr(args, "title", "") or "")
    message = str(getattr(args, "message", "") or "")
    if message:
        commit_msg += "\n\n" + message
    linked_task_id = session.get("task_id")
    if linked_task_id:
        linked_task = _load_task(linked_task_id)
        if linked_task:
            task_summary = linked_task.get("summary", "").strip()
            if task_summary:
                commit_msg += "\n\n" + task_summary
    trailers = list(getattr(args, "trailer", None) or [])
    invalid = [trailer for trailer in trailers if not trailer.strip() or "\n" in trailer or "\r" in trailer]
    if invalid:
        raise RuntimeError("--trailer values must each be one non-empty line")
    if trailers:
        commit_msg += "\n\n" + "\n".join(trailer.strip() for trailer in trailers)
    return commit_msg


def _validate_specification_commit_message(files: list[str], message: str) -> None:
    governed = [
        path
        for path in files
        if path.startswith("specifications/") and Path(path).name in {"specification.yml", "examples.yml"}
    ]
    if not governed:
        return
    missing = [
        trailer
        for trailer in ("Specifications:", "Assertions:", "Plan:", "Specification-Impact:")
        if trailer not in message
    ]
    if missing:
        raise RuntimeError(
            "Specification-governed commit is missing required trailers: "
            + ", ".join(missing)
            + '. Use repeatable one-line arguments such as --trailer "Specifications: feature.example@1" '
            + '--trailer "Assertions: example.behavior" --trailer "Plan: example" '
            + '--trailer "Specification-Impact: implementation-only"; do not use ANSI-C shell quoting.'
        )


def _preflight_deploy_commit_message(args: argparse.Namespace, session: dict, files: list[str]) -> str:
    """Reject deterministic commit-message errors before expensive deploy gates."""
    message = _integration_commit_message(args, session)
    _validate_specification_commit_message(files, message)
    return message


def _bootstrap_integration_for_files(checkout_root: Path, files: list[str]) -> None:
    """Provide ignored frontend prerequisites only when selected files need them."""
    if not (_has_frontend_files(files) or _should_validate_embed_registry(files)):
        return
    result = bootstrap_session_worktree(checkout_root)
    if result.get("status") != "ready":
        raise RuntimeError(
            f"Integration bootstrap failed ({result.get('reason', 'unknown')}): "
            f"{result.get('message', 'no detail')}"
        )


def _sync_deployed_files_to_source(
    source_metadata: dict,
    checkout_root: Path,
    files: list[str],
    patch_files: list[str],
    expected_patch_id: str,
) -> str:
    """Copy deployed paths and advance the source base when remaining work is independent."""
    source_root = Path(str(source_metadata.get("path") or ""))
    try:
        if _worktree_patch_id(source_metadata, patch_files) != expected_patch_id:
            return "Source worktree changed during deploy; deployed files were not synchronized."
        source_head = _worktree_head(source_root)
        rc, deployed_commit, stderr = _run_cmd(
            ["git", "rev-parse", "HEAD"],
            cwd=str(checkout_root),
        )
        if rc != 0 or not deployed_commit.strip():
            return f"Deployed files were not synchronized because the deployed commit could not be resolved: {stderr}"
        deployed_commit = deployed_commit.strip()

        rc, changed_output, stderr = _run_cmd(
            ["git", "diff", "--name-only", "-z", source_head, "--"],
            cwd=str(source_root),
        )
        if rc != 0:
            return f"Deployed files were not synchronized because source changes could not be inspected: {stderr}"
        changed_before = {
            path for path in changed_output.split("\0") if path
        } | _worktree_untracked_files(source_metadata)
        selected = set(files)
        remaining = sorted(changed_before - selected)

        rc, staged_output, stderr = _run_cmd(
            ["git", "diff", "--cached", "--name-only", "-z", source_head, "--"],
            cwd=str(source_root),
        )
        if rc != 0:
            return f"Deployed files were not synchronized because staged source changes could not be inspected: {stderr}"
        staged_remaining = {path for path in staged_output.split("\0") if path} - selected

        can_advance = not staged_remaining
        if can_advance:
            rc, _stdout, _stderr = _run_cmd(
                ["git", "merge-base", "--is-ancestor", source_head, deployed_commit],
                cwd=str(source_root),
            )
            can_advance = rc == 0
        if can_advance and remaining:
            can_advance = not _selected_paths_changed_between_refs(
                source_root,
                source_head,
                deployed_commit,
                remaining,
            )

        for relative_path in files:
            deployed_path = checkout_root / relative_path
            source_path = source_root / relative_path
            if deployed_path.is_file():
                source_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = source_path.with_name(f".{source_path.name}.{os.getpid()}.deploy-sync")
                shutil.copy2(deployed_path, temporary)
                temporary.replace(source_path)
            elif source_path.exists() or source_path.is_symlink():
                source_path.unlink()
        # A partial deploy can advance too when no remaining path changed in the
        # deployed ancestry. The mixed reset preserves the undeployed bytes, and
        # the targeted restore refreshes only paths that were clean beforehand.
        if can_advance:
            rc, upstream_output, stderr = _run_cmd(
                ["git", "diff", "--name-only", "-z", source_head, deployed_commit, "--"],
                cwd=str(source_root),
            )
            if rc != 0:
                return f"Deployed files were synchronized, but upstream paths could not be inspected: {stderr}"
            refresh_paths = sorted(
                {path for path in upstream_output.split("\0") if path} - set(remaining)
            )
            rc, _stdout, stderr = _run_cmd(
                ["git", "reset", "--mixed", deployed_commit],
                cwd=str(source_root),
                timeout=120,
            )
            if rc != 0:
                return (
                    "Deployed files were synchronized, but the source worktree could not be advanced safely: "
                    f"{stderr}"
                )
            restore_paths = []
            deleted_paths = []
            for relative_path in refresh_paths:
                rc, _stdout, _stderr = _run_cmd(
                    ["git", "cat-file", "-e", f"{deployed_commit}:{relative_path}"],
                    cwd=str(source_root),
                )
                (restore_paths if rc == 0 else deleted_paths).append(relative_path)
            if restore_paths:
                rc, _stdout, stderr = _run_cmd(
                    [
                        "git",
                        "restore",
                        "--source=HEAD",
                        "--worktree",
                        "--",
                        *(f":(literal){path}" for path in restore_paths),
                    ],
                    cwd=str(source_root),
                    timeout=120,
                )
                if rc != 0:
                    return (
                        "The source worktree base advanced, but clean upstream paths could not be refreshed: "
                        f"{stderr}"
                    )
            for relative_path in deleted_paths:
                stale_path = source_root / relative_path
                if stale_path.is_file() or stale_path.is_symlink():
                    stale_path.unlink()
                elif stale_path.exists():
                    return (
                        "The source worktree base advanced, but an upstream-deleted path is not a file: "
                        f"{relative_path}"
                    )
    except (OSError, RuntimeError) as exc:
        return f"Could not synchronize deployed files into the source worktree: {exc}"
    return ""


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
    control_plane_warning = ""
    source_sync_warning = ""

    try:
        prepared_base = _fetch_origin_dev_commit()
        _enforce_control_plane_deploy_protocol_compatible(prepared_base)
        prepare_args = (
            sid,
            worktree_metadata,
            to_commit,
            patch_id,
            prepared_base,
        )
        checkpoint_commit = str(getattr(args, "expected_checkpoint_commit", "") or "")
        if not checkpoint_commit:
            checkpoint_commit = _create_worktree_checkpoint_commit(
                sid,
                worktree_metadata,
                to_commit,
                patch_id,
            )
        integration = _prepare_integration_worktree(*prepare_args, checkpoint_commit=checkpoint_commit)

        while True:
            checkout_root = Path(integration["path"])
            _bootstrap_integration_for_files(checkout_root, to_commit)
            generated_specification_files = _regenerate_specification_artifacts_for_deploy(
                to_commit,
                checkout_root=checkout_root,
            )
            commit_files = sorted(set(to_commit).union(generated_specification_files))
            _run_deploy_gates(
                commit_files,
                checkout_root=checkout_root,
                no_verify=no_verify,
                skip_tests_reason=skip_tests_reason,
                require_parity=require_parity,
                session_id=sid,
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
            _enforce_control_plane_deploy_protocol_compatible(final_base)
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
                set(commit_files),
                context="before integration commit",
                checkout_root=checkout_root,
            ):
                raise RuntimeError("Integration staged-file validation failed")

            commit_message = _preflight_deploy_commit_message(args, session, commit_files)
            commit_cmd = ["git", "commit", "-m", commit_message]
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
            source_sync_warning = _sync_deployed_files_to_source(
                worktree_metadata,
                checkout_root,
                commit_files,
                to_commit,
                patch_id,
            )
            control_plane_warning = _control_plane_sync_warning(commit_hash_full)
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
    if control_plane_warning:
        print(control_plane_warning, file=sys.stderr)
    if source_sync_warning:
        print(source_sync_warning, file=sys.stderr)
    commit_hash = commit_hash_full[:7]
    print()
    print("== DEPLOYED ==")
    print(f"Commit: {commit_hash}")
    print(f"Files: {len(to_commit)}")
    for relative_path in sorted(to_commit):
        print(f"  {relative_path}")
    print("Branch: dev")
    _print_deployed_commit_handoff(commit_hash_full)

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
        _enforce_proof_video_end_gate(sid, latest_session, to_commit, commit_sha=commit_hash_full)
        try:
            finalize_session_worktree(sid, target_ref=commit_hash_full)
        except RuntimeError as exc:
            print(f"DEPLOYED BUT SESSION FINALIZATION BLOCKED — {exc}", file=sys.stderr)
            print(f"Retry after resolving residual work: python3 scripts/sessions.py end --session {sid}", file=sys.stderr)
            sys.exit(1)
        _linear_complete_session(sid, latest_session, commit_sha=commit_hash)
        print(f"\nSession {sid} ended.")
    else:
        latest_data = _load_sessions()
        latest_session = latest_data.get("sessions", {}).get(sid, session)
        _record_proof_video_deploy_pending(
            sid,
            latest_session,
            to_commit,
            commit_sha=commit_hash_full,
        )


def _run_openmatescloud_deploy_gates(files: list[str], *, checkout_root: Path, no_verify: bool) -> None:
    """Run the lightweight gate that belongs to the private cloud overlay repo."""
    relevant = any(
        path == "docker-compose.openmatescloud.yml"
        or path == "backend/tests/test_overlay_compose.py"
        or path.startswith("backend/openmatescloud/")
        for path in files
    )
    if not relevant:
        return
    if no_verify:
        print("OpenMatesCloud overlay pytest: SKIPPED (--no-verify)")
        return
    test_path = checkout_root / "backend" / "tests" / "test_overlay_compose.py"
    if not test_path.is_file():
        raise RuntimeError(f"OpenMatesCloud overlay pytest is missing: {test_path}")
    print("Running OpenMatesCloud overlay pytest...")
    rc, stdout, stderr = _run_cmd(
        [sys.executable, "-m", "pytest", "backend/tests/test_overlay_compose.py"],
        cwd=str(checkout_root),
        timeout=120,
    )
    if rc != 0:
        detail = stderr or stdout or "pytest failed"
        raise RuntimeError(f"OpenMatesCloud overlay pytest failed: {detail}")
    print("OpenMatesCloud overlay pytest: PASSED")


def _run_external_repo_deploy_gates(session: dict, files: list[str], *, checkout_root: Path, no_verify: bool) -> None:
    if _session_repo_id(session) == OPENMATESCLOUD_REPO_ID:
        _run_openmatescloud_deploy_gates(files, checkout_root=checkout_root, no_verify=no_verify)


def _deploy_external_repo(args: argparse.Namespace, session: dict, to_commit: list[str], dirty_but_untracked: list[str]) -> None:
    """Commit selected files in an allowlisted sibling checkout and push its branch."""
    sid = args.session
    repo = _session_repo_metadata(session)
    lock_type = f"{repo['repo_id']}_deploy"
    acquired_lock = _wait_and_acquire_session_lock(
        lock_type,
        sid,
        phase="deploying_sibling_repo",
        timeout=getattr(args, "lock_timeout", None),
        poll=getattr(args, "lock_poll", 30),
    )
    if not acquired_lock:
        raise RuntimeError(f"{repo['repo_name']} deploy lock is already held by session {sid}")
    try:
        return _deploy_external_repo_locked(args, session, to_commit, dirty_but_untracked, repo=repo)
    finally:
        _release_session_lock(lock_type, released_by=sid)


def _deploy_external_repo_locked(
    args: argparse.Namespace,
    session: dict,
    to_commit: list[str],
    dirty_but_untracked: list[str],
    *,
    repo: dict[str, str],
) -> None:
    """Run a sibling checkout deploy while the repo-scoped deploy lock is held."""
    _validate_session_repo(repo)
    checkout_root = Path(repo["repo_root"]).resolve()
    branch = repo["repo_branch"]
    remote = repo["repo_remote"]
    no_verify = getattr(args, "no_verify", False)
    use_staged = getattr(args, "use_staged", False)

    if dirty_but_untracked:
        print("Warning — dirty files NOT tracked by this session (will not be committed):")
        for f in sorted(dirty_but_untracked):
            print(f"  ? {f}")
        print()

    if not to_commit:
        git_summary = _get_git_status_summary(checkout_root=checkout_root)
        if git_summary.get("unpushed", 0) > 0:
            rc, commit_hash_full, stderr = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(checkout_root))
            if rc != 0:
                raise RuntimeError(f"Could not resolve {_session_repo_name(session)} HEAD: {stderr}")
            commit_hash_full = commit_hash_full.strip()
            commit_hash = commit_hash_full[:7]
            print(f"No files to commit; pushing {git_summary['unpushed']} existing commit(s) to {remote} {branch}...")
            _validate_session_repo(repo)
            rc, _stdout, stderr = _run_cmd(
                ["git", "push", remote, f"HEAD:refs/heads/{branch}"],
                cwd=str(checkout_root),
                timeout=300,
            )
            if rc != 0:
                raise RuntimeError(f"git push failed: {stderr}")
            print()
            print("== DEPLOYED ==")
            print(f"Repo: {_session_repo_name(session)}")
            print(f"Commit: {commit_hash}")
            print("Files: 0 (resumed previous deploy push)")
            print(f"Branch: {branch}")
            return
        raise RuntimeError("No files to commit.")

    _run_external_repo_deploy_gates(session, to_commit, checkout_root=checkout_root, no_verify=no_verify)
    _validate_session_repo(repo)

    staged_files = _get_staged_files(checkout_root=checkout_root)
    foreign_staged = [f for f in staged_files if f not in to_commit]
    if foreign_staged:
        raise RuntimeError(
            "staged files outside this session; aborting to preserve the shared index: "
            + ", ".join(sorted(foreign_staged))
        )

    if use_staged:
        staged_files = _get_staged_files(checkout_root=checkout_root)
        missing_staged = [f for f in to_commit if f not in staged_files]
        if missing_staged:
            raise RuntimeError("--use-staged requires staged changes for: " + ", ".join(sorted(missing_staged)))
        print(f"Using pre-staged changes for {len(to_commit)} tracked file(s)")
    else:
        files_to_add = [f for f in to_commit if (checkout_root / f).exists()]
        deleted_files = [f for f in to_commit if not (checkout_root / f).exists()]
        if deleted_files:
            print(f"Staging {len(deleted_files)} deleted file(s)...")
            rc, _stdout, stderr = _run_cmd(
                ["git", "rm", "--cached", "--ignore-unmatch", "--", *deleted_files],
                cwd=str(checkout_root),
            )
            if rc != 0:
                raise RuntimeError(f"git rm failed: {stderr}")
        if files_to_add:
            print(f"Adding {len(files_to_add)} file(s)...")
            rc, _stdout, stderr = _run_cmd(["git", "add", "--", *files_to_add], cwd=str(checkout_root))
            if rc != 0:
                raise RuntimeError(f"git add failed: {stderr}")
        print(f"Staging complete: {len(files_to_add)} added, {len(deleted_files)} deleted")

    if not _validate_staged_deploy_files(set(to_commit), context="before external repo commit", checkout_root=checkout_root):
        raise RuntimeError("staged-file validation failed")

    _validate_session_repo(repo)
    commit_msg = _integration_commit_message(args, session)
    commit_cmd = ["git", "commit", "-m", commit_msg]
    if no_verify:
        commit_cmd.append("--no-verify")
    print(f"Committing {_session_repo_name(session)}: {args.title}")
    rc, _stdout, stderr = _run_cmd(commit_cmd, cwd=str(checkout_root), timeout=300)
    if rc != 0:
        raise RuntimeError(f"git commit failed: {stderr}")

    rc, commit_hash_full, stderr = _run_cmd(["git", "rev-parse", "HEAD"], cwd=str(checkout_root))
    commit_hash_full = commit_hash_full.strip()
    if rc != 0 or not commit_hash_full:
        raise RuntimeError(f"Could not resolve commit hash: {stderr}")

    _validate_session_repo(repo)
    print(f"Pushing to {remote} {branch}...")
    rc, _stdout, stderr = _run_cmd(
        ["git", "push", remote, f"HEAD:refs/heads/{branch}"],
        cwd=str(checkout_root),
        timeout=300,
    )
    if rc != 0:
        raise RuntimeError(f"git push failed: {stderr}")

    print()
    print("== DEPLOYED ==")
    print(f"Repo: {_session_repo_name(session)}")
    print(f"Commit: {commit_hash_full[:7]}")
    print(f"Files: {len(to_commit)}")
    for f in sorted(to_commit):
        print(f"  {f}")
    print(f"Branch: {branch}")


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
    is_control_plane_repo = _session_is_control_plane_repo(session)
    worktree_metadata = session.get("worktree") if is_control_plane_repo and isinstance(session.get("worktree"), dict) else None
    checkout_root = _session_checkout_root(session)

    use_staged = bool(getattr(args, "use_staged", False))
    dirty_files = _get_dirty_files(checkout_root=checkout_root)
    try:
        to_commit, selector = _resolve_deploy_selection(
            session,
            exclude=exclude,
            use_staged=use_staged,
            only=list(getattr(args, "only", None) or []),
        )
    except RuntimeError as exc:
        print(f"{_session_repo_name(session).upper()} DEPLOY FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        validate_product_session_deploy_paths(to_commit, session=session)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    try:
        _preflight_deploy_commit_message(args, session, to_commit)
    except RuntimeError as exc:
        print(f"WORKTREE DEPLOY FAILED — {exc}", file=sys.stderr)
        sys.exit(1)
    manifest = _build_deploy_manifest(sid, session, to_commit, selector=selector)
    expected_manifest_id = str(getattr(args, "expected_manifest_id", "") or "")
    if expected_manifest_id and manifest["manifest_id"] != expected_manifest_id:
        print(
            "WORKTREE DEPLOY BLOCKED — deploy manifest changed after preview. "
            "Run prepare-deploy again and retry with its new manifest ID.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Deploy manifest: {manifest['manifest_id']} ({selector}, {len(to_commit)} source file(s))")
    dirty_but_untracked = [f for f in dirty_files if f not in modified and f not in exclude]
    worktree_patch_id = _worktree_patch_id(worktree_metadata, to_commit) if worktree_metadata and to_commit else ""
    expected_patch_id = str(getattr(args, "expected_patch_id", "") or "")
    expected_checkpoint_commit = str(getattr(args, "expected_checkpoint_commit", "") or "")
    if expected_patch_id and worktree_patch_id != expected_patch_id:
        print(
            "WORKTREE DEPLOY BLOCKED — checkpoint patch changed before integration. "
            "Create a new checkpoint and retry.",
            file=sys.stderr,
        )
        sys.exit(1)
    if expected_checkpoint_commit:
        auto = session.get("auto_integration") if isinstance(session.get("auto_integration"), dict) else {}
        if (
            auto.get("patch_id") != expected_patch_id
            or auto.get("checkpoint_commit") != expected_checkpoint_commit
            or not _checkpoint_ref_matches(sid, auto)
        ):
            print(
                "WORKTREE DEPLOY BLOCKED — checkpoint metadata or retained ref changed before integration.",
                file=sys.stderr,
            )
            sys.exit(1)
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
        if _session_repo_id(other_info) != _session_repo_id(session):
            continue
        for of in other_info.get("modified_files", []):
            file_tracking[of] = other_sid

    if not is_control_plane_repo:
        try:
            _deploy_external_repo(args, session, to_commit, dirty_but_untracked)
        except RuntimeError as exc:
            print(f"{_session_repo_name(session).upper()} DEPLOY FAILED — {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "end_session", False):
            cmd_end(argparse.Namespace(
                session=sid,
                force=False,
                skip_visual_smoke_reason=getattr(args, "skip_visual_smoke_reason", None),
            ))
        return

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

            try:
                _enforce_control_plane_deploy_protocol_compatible(_fetch_origin_dev_commit())
            except RuntimeError as exc:
                if deploy_lock_held:
                    _release_session_lock("vercel_deploy", released_by=sid)
                print(f"CONTROL-PLANE DEPLOY PROTOCOL GATE FAILED — {exc}", file=sys.stderr)
                sys.exit(1)

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
            _print_deployed_commit_handoff(commit_hash_full)
            _maybe_start_verification_session(args, sid, commit_hash_full)

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
                _enforce_proof_video_end_gate(
                    sid,
                    latest_session,
                    modified or _get_unpushed_files(),
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
            else:
                latest_data = _load_sessions()
                latest_session = latest_data.get("sessions", {}).get(sid, session)
                _record_proof_video_deploy_pending(
                    sid,
                    latest_session,
                    modified or _get_unpushed_files(),
                    commit_sha=commit_hash_full,
                )
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

    if worktree_metadata and to_commit:
        validate_worktree_binding_mode(session)
        _deploy_native_worktree(args, session, worktree_metadata, to_commit, worktree_patch_id)
        return

    # Contract/test traceability is never bypassed by --skip-tests or --no-verify.
    _run_specification_gate(to_commit, session_id=sid, checkout_root=PROJECT_ROOT)

    _enforce_embed_registry_validation(to_commit)

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

    try:
        _enforce_control_plane_deploy_protocol_compatible(_fetch_origin_dev_commit())
    except RuntimeError as exc:
        if deploy_lock_held:
            _release_session_lock("vercel_deploy", released_by=sid)
        print(f"CONTROL-PLANE DEPLOY PROTOCOL GATE FAILED — {exc}", file=sys.stderr)
        sys.exit(1)

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
        # The authoritative exact-set check immediately before commit covers
        # both missing and foreign staged paths. Avoid a second partial check
        # here that can race with another session and report the wrong cause.
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

    _validate_specification_commit_message(to_commit, commit_msg)

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
    try:
        _enforce_control_plane_deploy_protocol_compatible(_fetch_origin_dev_commit())
    except RuntimeError as exc:
        if deploy_lock_held:
            _release_session_lock("vercel_deploy", released_by=sid)
        print(f"CONTROL-PLANE DEPLOY PROTOCOL GATE FAILED — {exc}", file=sys.stderr)
        print("Commit was created locally but not pushed.", file=sys.stderr)
        sys.exit(1)
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
    _print_deployed_commit_handoff(commit_hash_full)
    _maybe_start_verification_session(args, sid, commit_hash_full)

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
        _enforce_proof_video_end_gate(sid, latest_session, to_commit, commit_sha=commit_hash_full)
        try:
            finalize_session_worktree(sid, target_ref=commit_hash_full)
        except RuntimeError as exc:
            print(f"DEPLOYED BUT SESSION FINALIZATION BLOCKED — {exc}", file=sys.stderr)
            print(f"Retry after resolving residual work: python3 scripts/sessions.py end --session {sid}", file=sys.stderr)
            sys.exit(1)
        _linear_complete_session(sid, latest_session, commit_sha=commit_hash)
        print(f"\nSession {sid} ended.")
    else:
        latest_data = _load_sessions()
        latest_session = latest_data.get("sessions", {}).get(sid, session)
        _record_proof_video_deploy_pending(
            sid,
            latest_session,
            to_commit,
            commit_sha=commit_hash_full,
        )


def cmd_worktree(args: argparse.Namespace) -> None:
    """Manage automatic local session worktrees."""
    if args.worktree_action == "root-dirty":
        try:
            result = list_root_dirty_files(path_prefix=args.path_prefix or "")
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.worktree_action == "import-root":
        try:
            result = import_root_dirty_file(
                args.file,
                session_id=args.session or "",
                opencode_session_id=args.opencode_session or "",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, sort_keys=True))
        return
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
    if args.worktree_action == "repair":
        try:
            result = repair_worktree_routing(args.opencode_session)
        except (RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, sort_keys=True))
        return
    if args.worktree_action == "refresh-base":
        try:
            result = refresh_session_worktree_base(args.session)
        except (RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(result, sort_keys=True))
        return
    if args.worktree_action == "checkpoint":
        try:
            result = checkpoint_session_worktree(args.opencode_session, event=args.event)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(result, sort_keys=True))
        return
    if args.worktree_action == "activate":
        try:
            result = activate_session_worktree(args.opencode_session)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(result, sort_keys=True))
        return
    if args.worktree_action == "auto-integrate":
        try:
            result = auto_integrate_checkpoints(dry_run=args.dry_run)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["blocked"]:
            sys.exit(1)
        return
    if args.worktree_action == "expire":
        try:
            report = expire_managed_worktrees(max_age_hours=args.max_age_hours)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print("== WORKTREE HARD EXPIRY ==")
            print(f"Maximum age: {report['max_age_hours']} hours")
            print(f"Inspected: {report['inspected']}")
            print(f"Deleted: {len(report['deleted'])}")
            print(f"Retained: {len(report['retained'])}")
            for failure in report["failures"]:
                print(f"  ! {failure['path']}: {failure['error']}")
        if report["failures"]:
            sys.exit(1)
        return
    if args.worktree_action == "cleanup":
        if args.idle_hours < WORKTREE_CLEANUP_IDLE_HOURS:
            print(
                f"Error: --idle-hours below {WORKTREE_CLEANUP_IDLE_HOURS} is not allowed for worktree cleanup",
                file=sys.stderr,
            )
            sys.exit(2)
        deleted = cleanup_session_worktrees(idle_hours=args.idle_hours)
        print(f"Deleted safely classified stale worktrees: {len(deleted)}")
        for session_id in deleted:
            print(f"  - {session_id}")
        return
    if args.worktree_action == "deduplicate-chats":
        try:
            report = deduplicate_chat_worktrees(
                target_ref=args.target,
                apply=args.apply,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print("== WORKTREE CHAT DEDUPLICATION ==")
            print(f"Target: {report['target_ref']} ({report['target_commit'][:10]})")
            print(f"Duplicate chats: {report['duplicate_chat_count']}")
            print(f"Planned removals: {len(report['remove'])}")
            print(f"Deleted: {len(report['deleted'])}")
            print(f"Checkpointed: {len(report['checkpointed'])}")
            print(f"Blocked: {len(report['blocked'])}")
            print(f"Unknown lineage: {len(report['lineage_unknown'])}")
            for item in report["blocked"]:
                print(f"  ! {item['session_id']}: {item['reason']}")
        if report["blocked"]:
            sys.exit(1)
        return
    if args.worktree_action == "reconcile":
        if args.idle_hours < WORKTREE_CLEANUP_IDLE_HOURS and not args.only:
            print(
                f"Error: --idle-hours below {WORKTREE_CLEANUP_IDLE_HOURS} requires at least one --only SESSION_ID",
                file=sys.stderr,
            )
            sys.exit(2)
        approved_obsolete = set(args.approve_obsolete or [])
        only_session_ids = set(args.only or [])
        unscoped_approvals = sorted(approved_obsolete - only_session_ids)
        if unscoped_approvals:
            required_scope = " ".join(f"--only {session_id}" for session_id in unscoped_approvals)
            print(
                f"Error: every --approve-obsolete ID requires matching scope: {required_scope}",
                file=sys.stderr,
            )
            sys.exit(2)
        persist_scheduler_health = args.apply_safe and not only_session_ids
        try:
            if persist_scheduler_health:
                _write_worktree_reconciliation_started(args.target)
            report = reconcile_session_worktrees(
                target_ref=args.target,
                idle_hours=args.idle_hours,
                apply_safe=args.apply_safe,
                approved_obsolete=approved_obsolete,
                only_session_ids=only_session_ids,
            )
            if persist_scheduler_health:
                _write_worktree_reconciliation_report(report)
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


def cmd_specification(args: argparse.Namespace) -> None:
    """Run current Specification workflow tooling against one routed worktree."""
    if args.specification_action != "approval-pdf":
        print(f"Unknown Specification action: {args.specification_action}", file=sys.stderr)
        sys.exit(2)
    try:
        data = _load_sessions()
        session_id = _resolve_session_id(data, session_id=args.session)
        checkout_root = _session_checkout_root(data["sessions"][session_id]).resolve()
        if Path(args.bundle).is_absolute():
            raise ValueError("Specification bundle must be a repository-relative path")
        relative_bundle = _canonical_stored_repo_path(args.bundle)
        bundle = (checkout_root / relative_bundle).resolve()
        bundle.relative_to(checkout_root)

        # Import from the immutable current control plane, but bind all source
        # and Git-baseline reads to the selected session checkout.
        from scripts import specification_approval_pdf

        original_specification_root = specification_approval_pdf.specifications.REPO_ROOT
        original_module_root = specification_approval_pdf.REPO_ROOT
        specification_approval_pdf.specifications.REPO_ROOT = checkout_root
        specification_approval_pdf.REPO_ROOT = checkout_root
        command = [str(bundle), "--baseline-ref", args.baseline_ref]
        if args.new_specification:
            command.append("--new-specification")
        if args.no_upload:
            command.append("--no-upload")
        if args.dry_run_upload:
            command.append("--dry-run-upload")
        if args.json:
            command.append("--json")
        try:
            result = specification_approval_pdf.main(command)
        finally:
            specification_approval_pdf.specifications.REPO_ROOT = original_specification_root
            specification_approval_pdf.REPO_ROOT = original_module_root
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    if result:
        sys.exit(result)



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
    print(f"Workspace state: {session.get('workspace_state', 'unknown')}")
    auto_integration = session.get("auto_integration")
    if isinstance(auto_integration, dict) and auto_integration.get("status"):
        print(f"Auto-integration: {auto_integration.get('status')}")
        if auto_integration.get("block_reason"):
            print(f"Auto-integration reason: {auto_integration.get('block_reason')}")
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
        if isinstance(session.get("worktree"), dict):
            uncommitted = _session_deploy_files(session, set())
        else:
            dirty_files = _get_dirty_files(checkout_root=_session_checkout_root(session))
            uncommitted = [f for f in modified if f in dirty_files]
        committed = [f for f in modified if f not in set(uncommitted)]

        if uncommitted:
            print(f"Deploy status: PENDING ({len(uncommitted)} file(s) not yet committed)")
            for f in sorted(uncommitted):
                print(f"  ! {f}")
            print()
            print("  Deploy command:")
            print(f"    python3 scripts/sessions.py deploy --session {sid} --title \"type: description\" --message \"body\" --end")
        elif committed:
            # Try to get the most recent commit SHA that touched any of these files
            rc, sha, _ = _run_cmd(["git", "log", "-1", "--format=%h", "--"] + committed, cwd=str(_session_checkout_root(session)))
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
    if not _session_is_control_plane_repo(session):
        print(f"Lint: SKIPPED ({_session_repo_name(session)} has no OpenMates lint_changed.sh gate)")
        return

    rc, stdout, stderr = _run_lint(modified, checkout_root=_session_checkout_root(session))
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
        "{parent}/tests/test_{stem}.py",
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

    # Infrastructure modules sometimes share a behavioral contract test whose
    # filename cannot be inferred from the source stem. Keep that relationship
    # explicit and reviewable instead of falling back to a broad name match.
    source_path = root / filepath
    if suffix == ".py" and source_path.is_file():
        try:
            source_header = "\n".join(source_path.read_text(encoding="utf-8").splitlines()[:40])
        except OSError:
            source_header = ""
        for declared in re.findall(r"^# test-file:\s*(\S+)\s*$", source_header, flags=re.MULTILINE):
            declared_path = Path(declared)
            if ".." in declared_path.parts or declared_path.is_absolute():
                continue
            if (root / declared_path).is_file() and declared not in result["unit_tests"]:
                result["unit_tests"].append(declared)

    # Also search for any test file containing the stem name. Prune generated
    # and managed-worktree roots before descending: Path.glob("**/...") walks
    # every session checkout and made this deploy gate scale by worktree count.
    test_glob_patterns = [
        f"**/__tests__/*{stem}*",
        f"**/test_{stem}*",
        f"**/*{stem}*.test.*",
        f"**/*{stem}*.spec.*",
    ]
    excluded_test_roots = {
        ".agent-worktrees",
        ".git",
        ".openmates-agent-worktrees",
        ".svelte-kit",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "test-results",
    }
    # Exact sibling/directive matches are authoritative for Python. A global
    # substring scan for generic stems such as api.py otherwise pulls unrelated
    # product suites (for example api_key_scopes) into a control-plane deploy.
    if suffix != ".py" or not result["unit_tests"]:
        for current, directories, names in os.walk(root):
            directories[:] = [name for name in directories if name not in excluded_test_roots]
            current_path = Path(current)
            for name in names:
                match = current_path / name
                relative = match.relative_to(root)
                if not any(relative.match(pattern) for pattern in test_glob_patterns):
                    continue
                rel = str(match.relative_to(root))
                if rel not in result["unit_tests"]:
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


def _opencode_chat_session_label(session_id: str) -> str:
    return session_id[:12] if session_id else "unknown"


def _append_indented_block(lines: list[str], text: str, *, prefix: str = "      ") -> None:
    if not text:
        return
    for line in text.splitlines() or [text]:
        lines.append(f"{prefix}{line}")


def _format_opencode_chat_text(view: dict[str, Any]) -> str:
    sessions = view.get("sessions") or []
    root = sessions[0] if sessions else {}
    lines = [
        "== OPENCODE CHAT ==",
        f"Session: {view.get('session_id')}",
        f"Title: {root.get('title') or '(untitled)'}",
        f"Directory: {root.get('directory') or 'unknown'}",
        f"Updated: {root.get('time_updated') or 'unknown'}",
    ]
    if view.get("resolved_repository_session_id"):
        lines.append(f"Resolved repo session: {view['resolved_repository_session_id']}")
    if view.get("project_directory_from_url"):
        lines.append(f"URL project: {view['project_directory_from_url']}")
    if view.get("query"):
        lines.append(f"Query: {view['query']}")
    child_sessions = [session for session in sessions if session.get("parent_session_id")]
    lines.append(f"Included sessions: {len(sessions)} ({len(child_sessions)} child)")
    lines.append(f"Messages: {view.get('message_count', 0)}; parts: {view.get('part_count', 0)}")

    repository_sessions = view.get("repository_sessions") or []
    if repository_sessions:
        lines.extend(["", "Repository session mappings:"])
        for item in repository_sessions:
            worktree = item.get("worktree") or {}
            file_count = item.get("modified_file_count", len(item.get("modified_files") or []))
            lines.append(
                f"  - {item.get('repository_session_id')}: {item.get('task') or '(no task)'} "
                f"[{item.get('mode') or 'unknown'}; worktree={worktree.get('status') or 'unknown'}; files={file_count}]"
            )

    attachments = [item for item in (view.get("attachments") or []) if item.get("extractable")]
    if attachments:
        lines.extend(["", "Attachments:"])
        lines.append(f"  Extract: {view.get('attachment_extract_command')}")
        for item in attachments[:10]:
            size = f", {item['byte_count']} bytes" if item.get("byte_count") is not None else ""
            lines.append(
                f"  - {item.get('part_id')}: {item.get('filename') or '(unnamed)'} "
                f"({item.get('mime') or 'unknown'}{size})"
            )
        if len(attachments) > 10:
            lines.append(f"  ... +{len(attachments) - 10} more")

    issues = view.get("issue_signals") or []
    signal_mode = view.get("signal_mode") or "actionable"
    signal_title = "Issue signals (all):" if signal_mode == "all" else "Actionable signals:"
    lines.extend(["", signal_title])
    if issues:
        for issue in issues:
            tool = f" tool={issue['tool']}" if issue.get("tool") else ""
            text = f": {issue.get('text')}" if issue.get("text") else ""
            lines.append(
                f"  - {issue.get('kind')} session={_opencode_chat_session_label(str(issue.get('session_id') or ''))}{tool}{text}"
            )
    else:
        lines.append("  none")
    suppressed = int(view.get("suppressed_signal_count") or 0)
    if signal_mode != "all" and suppressed:
        lines.append(f"  Suppressed broad grep/read/text signals: {suppressed} (show with --signals all)")

    if child_sessions:
        lines.extend(["", "Child sessions:"])
        visible_children = child_sessions[:OPENCODE_CHAT_TEXT_CHILD_SESSION_LIMIT]
        for session in visible_children:
            lines.append(
                f"  - {session.get('session_id')}: {session.get('title') or '(untitled)'} "
                f"parent={session.get('parent_session_id')} updated={session.get('time_updated')}"
            )
        hidden_children = len(child_sessions) - len(visible_children)
        if hidden_children > 0:
            lines.append(f"  ... {hidden_children} more child sessions omitted from text output; use --json for the full list")

    lines.extend(["", "Transcript:"])
    for message in view.get("messages") or []:
        metadata = []
        if message.get("agent"):
            metadata.append(f"agent={message['agent']}")
        if message.get("model"):
            metadata.append(f"model={message['model']}")
        if message.get("finish"):
            metadata.append(f"finish={message['finish']}")
        metadata_text = f" ({', '.join(metadata)})" if metadata else ""
        lines.append(
            f"[{message.get('time_created')}] "
            f"{str(message.get('role') or 'unknown').upper()} "
            f"session={_opencode_chat_session_label(str(message.get('session_id') or ''))}{metadata_text}"
        )
        parts = message.get("parts") or []
        if not parts:
            lines.append("    (no retained parts)")
            continue
        for part in parts:
            marker = "*" if part.get("matched") else "-"
            part_type = part.get("type")
            if part_type == "text":
                phase = f" phase={part['phase']}" if part.get("phase") else ""
                lines.append(f"    {marker} text{phase}:")
                _append_indented_block(lines, str(part.get("text") or ""))
                continue
            if part_type == "tool":
                title = f" title={part['title']}" if part.get("title") else ""
                lines.append(
                    f"    {marker} tool {part.get('tool') or 'unknown'} "
                    f"status={part.get('status') or 'unknown'}{title}"
                )
                if part.get("error"):
                    _append_indented_block(lines, f"error: {part['error']}")
                if part.get("output_preview"):
                    _append_indented_block(lines, f"output: {part['output_preview']}")
                if part.get("output") is not None:
                    _append_indented_block(lines, f"output: {_bounded_opencode_text(part['output'], OPENCODE_CHAT_TOOL_OUTPUT_PREVIEW_CHARS, {'fields': False})}")
                continue
            lines.append(f"    {marker} {part_type or 'part'}: {part}")

    truncated = view.get("truncated") or {}
    if any(truncated.values()):
        labels = ", ".join(key for key, value in truncated.items() if value)
        lines.extend(["", f"Truncated: {labels}"])
    return "\n".join(lines) + "\n"


def _format_recent_opencode_chats(result: dict[str, Any]) -> str:
    lines = [
        "== RECENT OPENCODE CHATS ==",
        f"Window: {result.get('days')} day(s); limit: {result.get('limit')}",
    ]
    chats = result.get("chats") or []
    if not chats:
        lines.append("No recent top-level OpenCode chats found.")
        return "\n".join(lines) + "\n"
    for chat in chats:
        repository = chat.get("repository_session_id") or "unbound"
        opencode_session_id = str(chat.get("opencode_session_id") or "")
        label = _opencode_chat_session_label(opencode_session_id)
        title = chat.get("task") or chat.get("title") or "(untitled)"
        child_text = f", {chat.get('child_count')} child" if chat.get("child_count") else ""
        lines.append(
            f"  {repository}  {label}  {chat.get('state') or 'unknown'}  "
            f"{chat.get('time_updated') or 'unknown'}{child_text}  {title}"
        )
        lines.append(f"    Open: {chat.get('inspect_command')}")
    return "\n".join(lines) + "\n"


def cmd_opencode_chat(args: argparse.Namespace) -> None:
    """Read or search a local OpenCode chat transcript by session ID or web URL."""
    if getattr(args, "opencode_chat_action", "") == "recent":
        try:
            result = list_recent_opencode_chats(
                days=getattr(args, "days", 3),
                limit=getattr(args, "limit", 20),
                db_path=getattr(args, "db", None),
            )
        except (FileNotFoundError, ValueError, sqlite3.Error) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
            return
        print(_format_recent_opencode_chats(result), end="")
        return

    if getattr(args, "opencode_chat_action", "") == "attachments":
        try:
            result = extract_opencode_chat_attachments(
                args.reference,
                out_dir=getattr(args, "out", None),
                include_children=not getattr(args, "no_children", False),
                part_ids=set(getattr(args, "part_id", None) or []) or None,
                db_path=getattr(args, "db", None),
                dry_run=getattr(args, "list", False),
            )
        except (FileNotFoundError, LookupError, ValueError, sqlite3.Error, binascii.Error) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
            return
        print("== OPENCODE ATTACHMENTS ==")
        print(f"Session: {result.get('session_id')}")
        print(f"Database: {result.get('database')}")
        print(f"Output: {result.get('out_dir')}")
        attachments = result.get("attachments") or []
        saved = result.get("saved") or []
        if not attachments:
            print("No retained OpenCode file/image attachments found.")
            return
        if getattr(args, "list", False):
            for item in attachments:
                marker = "extractable" if item.get("extractable") else item.get("source") or "unknown"
                size = f", {item['byte_count']} bytes" if item.get("byte_count") is not None else ""
                print(f"- {item.get('part_id')}: {item.get('filename') or '(unnamed)'} ({item.get('mime') or 'unknown'}{size}; {marker})")
            print(f"Extract: {_opencode_attachment_extract_command(str(result.get('session_id')))}")
            return
        if not saved:
            print("No extractable data-URL attachments were saved.")
            return
        for item in saved:
            print(f"- {item.get('part_id')}: {item.get('path')}")
        return

    query = getattr(args, "query", None)
    if isinstance(query, list):
        query = " ".join(query)
    try:
        view = read_opencode_chat(
            args.reference,
            query=query,
            include_children=not getattr(args, "no_children", False),
            include_tool_output=getattr(args, "include_tool_output", False),
            signal_mode=getattr(args, "signals", "actionable"),
            max_messages=getattr(args, "max_messages", OPENCODE_CHAT_DEFAULT_MAX_MESSAGES),
            max_parts_per_message=getattr(args, "max_parts_per_message", OPENCODE_CHAT_DEFAULT_MAX_PARTS_PER_MESSAGE),
            max_part_chars=getattr(args, "max_part_chars", OPENCODE_CHAT_DEFAULT_MAX_PART_CHARS),
            db_path=getattr(args, "db", None),
        )
    except (FileNotFoundError, LookupError, ValueError, sqlite3.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "json", False):
        print(json.dumps(view, indent=2, ensure_ascii=False, sort_keys=True))
        return
    print(_format_opencode_chat_text(view), end="")


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


def _print_deployed_commit_handoff(commit_sha: str) -> None:
    """Print one unambiguous subject-commit handoff after a successful dev push."""

    if not commit_sha:
        return
    print(f"Full commit: {commit_sha}")
    print(
        "Verify deployed spec: python3 scripts/tests.py run --spec <name>.spec.ts "
        f"--gate-deploy --expected-commit {commit_sha}"
    )
    print(json.dumps({
        "signal": "OPENMATES_CONTINUATION_READY",
        "operation_type": "deployment_ready",
        "operation_key": commit_sha,
        "next_action": "Continue with the exact-commit verification required for this deployment without repeating implementation or local gates.",
    }, sort_keys=True))


def _maybe_start_verification_session(args: argparse.Namespace, source_session_id: str, commit_sha: str) -> None:
    """Start a fresh verification session after deploy when explicitly requested."""

    if not getattr(args, "start_verification_session", False):
        return
    short_commit = commit_sha[:9] if commit_sha else "unknown"
    task = f"Verify deploy {short_commit} from session {source_session_id}"
    print()
    print("== VERIFICATION HANDOFF ==")
    print(f"Expected commit: {commit_sha or 'unknown'}")
    print(f"Starting verification session for follow-up Docker/test evidence: {task}")
    cmd_start(argparse.Namespace(
        mode="testing",
        task=task,
        issue=None,
        chat=None,
        embed=None,
        logs=None,
        user=None,
        debug_id=None,
        vercel=False,
        run_id=None,
        since_last_deploy=False,
        task_id=None,
        linear_issue=None,
        opencode_session=None,
    ))
    print(f"Next test commands should use --expected-commit {commit_sha or '<commit>'}.")


def cmd_spawn_chat(args: argparse.Namespace) -> None:
    """Spawn a new persisted OpenCode chat visible in the existing Web sidebar."""
    # Resolve prompt text
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.is_file():
            print(f"Error: prompt file not found: {args.prompt_file}", file=sys.stderr)
            sys.exit(1)
        prompt = prompt_path.read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
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
    elif permission_mode == "execute-readonly":
        mode_prefix = (
            "IMPORTANT: This is an EXECUTE-READONLY session. "
            "You may run repository Bash/status commands and inspect files, but you MUST NOT edit, write, "
            "create, delete, deploy, commit, apply patches, or modify files. "
            "Produce findings, root-cause evidence, or a handoff only.\n\n"
        )
    else:
        if getattr(args, "no_deploy_instructions", False):
            mode_prefix = (
                "IMPORTANT: This is an EXECUTE session. "
                "You have full access to read, edit, and create files. "
                "Investigate the issue and implement the fix directly. "
                "Do not deploy, commit, merge, or push; leave changes for the coordinator to harvest.\n\n"
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
                # Mark In Progress + retain the existing compatibility label.
                update_issue_status(issue_data["id"], "In Progress")
                add_label(issue_data["id"], issue_data.get("label_ids", []))
                # Post pickup comment
                post_comment(
                    issue_data["id"],
                    f"**OpenCode session started:** `{session_name}`\n\n"
                    f"**Mode:** {permission_mode}\n"
                    f"**OpenCode Web:** visible in the project sidebar when the run starts."
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
                    f"  and post a final comment with the OpenCode session ID, any commit SHA,\n"
                    f"  verification evidence, and the next exact command if follow-up is needed.\n"
                )
            else:
                print(f"Warning: Could not fetch Linear issue {linear_issue_id}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Linear integration failed: {e}", file=sys.stderr)

    prompt = mode_prefix + prompt + linear_suffix

    try:
        from _zellij_utils import find_opencode_session_id, spawn_opencode_session
    except ImportError:
        # Add scripts dir to path for import
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from _zellij_utils import find_opencode_session_id, spawn_opencode_session

    created_after_ms = int(time.time() * 1000)
    success = spawn_opencode_session(
        session_name=session_name,
        prompt=prompt,
        cwd=str(CONTROL_PLANE_ROOT),
        permission_mode=permission_mode,
    )

    if success:
        if permission_mode == "execute":
            mode_label = "execute (full access, auto-approved)"
        elif permission_mode == "execute-readonly":
            mode_label = "execute-readonly (Bash/status allowed, edits prohibited)"
        else:
            mode_label = "plan (research only)"
        opencode_session_id = find_opencode_session_id(
            session_name,
            str(CONTROL_PLANE_ROOT),
            created_after_ms=created_after_ms,
            attempts=6,
        )
        print(f"OpenCode chat spawned: {session_name}")
        print(f"Mode: {mode_label}")
        if opencode_session_id:
            print(f"OpenCode session: {opencode_session_id}")
            print(f"Web chat: {opencode_chat_url(opencode_session_id)}")
            print(f"Inspect: python3 scripts/sessions.py chat read {opencode_session_id}")
        else:
            print("OpenCode session: pending; use `opencode session list -n 10 --format json` to resolve it.")
        print("Visible in the existing OpenCode Web project sidebar; no Zellij session was created.")
    else:
        print("Error: failed to spawn OpenCode chat. Is the OpenCode server running?", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# restore — Resume interrupted OpenCode sessions
# ---------------------------------------------------------------------------


def _opencode_api_json(path: str, timeout: int = 15) -> Any:
    separator = "&" if "?" in path else "?"
    routed_path = f"{path}{separator}{urllib.parse.urlencode({'directory': str(CONTROL_PLANE_ROOT)})}"
    request = urllib.request.Request(f"{OPENCODE_SERVER_URL}{routed_path}", method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.load(response)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _opencode_resume_profile(session_id: str) -> dict[str, Any]:
    messages = _opencode_api_json(
        f"/session/{urllib.parse.quote(session_id, safe='')}/message?limit=10"
    )
    if not isinstance(messages, list):
        return {}
    for message in reversed(messages):
        info = message.get("info") if isinstance(message, dict) else None
        if not isinstance(info, dict) or info.get("role") != "assistant":
            continue
        return {
            "agent": info.get("agent"),
            "provider_id": info.get("providerID"),
            "model_id": info.get("modelID"),
            "variant": info.get("variant"),
        }
    return {}


def capture_opencode_restart_manifest(path: Path) -> dict[str, Any]:
    """Persist every busy top-level chat before an intentional server restart."""
    statuses = _opencode_api_json("/session/status")
    if not isinstance(statuses, dict):
        raise RuntimeError("OpenCode returned invalid session status data; restart capture aborted")

    captured: list[dict[str, Any]] = []
    for session_id, status in statuses.items():
        status_type = status.get("type") if isinstance(status, dict) else None
        if status_type not in OPENCODE_RESTART_ACTIVE_STATUSES:
            continue
        session = _opencode_api_json(f"/session/{urllib.parse.quote(str(session_id), safe='')}")
        if not isinstance(session, dict) or session.get("id") != session_id:
            raise RuntimeError(f"Could not resolve active OpenCode session {session_id}; restart capture aborted")
        if session.get("parentID"):
            continue

        profile = _opencode_resume_profile(str(session_id))
        agent = str(profile.get("agent") or "plan")
        captured.append({
            "session_id": str(session_id),
            "title": str(session.get("title") or "(untitled session)"),
            "directory": str(session.get("directory") or CONTROL_PLANE_ROOT),
            "updated_before_restart": int((session.get("time") or {}).get("updated") or 0),
            "status_before_restart": status_type,
            "permission_mode": "plan" if agent == "plan" else "execute",
            "provider_id": profile.get("provider_id"),
            "model_id": profile.get("model_id"),
            "variant": profile.get("variant"),
            "resume_sent_at": None,
            "resume_verified_at": None,
        })

    manifest = {
        "version": 1,
        "captured_at": _now_iso(),
        "server_url": OPENCODE_SERVER_URL,
        "sessions": sorted(captured, key=lambda item: item["session_id"]),
    }
    _write_json_atomic(path, manifest)
    return manifest


def _restore_prompt(restore: dict[str, Any], prompt: str) -> str:
    return (
        f"Restore preflight selected repository session {restore['repository_session_id'] or 'unmapped'}; "
        f"worktree advanced to current origin/dev: {str(restore['advanced']).lower()}. "
        "For every shared Docker or test operation, use the current routed coordinator: "
        "python3 scripts/sessions.py <command>. Do not access the root checkout or another managed worktree. "
        "A temporary shared lock is not a terminal blocker: run the intended canonical command directly so it queues, "
        "or run `python3 scripts/sessions.py wait-lock --session <repository-session-id> --type <docker|vercel> "
        "--follow --poll 10` with a long tool timeout, wait for OPENMATES_WAIT_READY, and continue in this same response.\n\n"
        + prompt
    )


def resume_opencode_restart_manifest(path: Path) -> dict[str, Any]:
    """Resume each captured chat once and durably record accepted continuations."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read OpenCode restart manifest {path}: {exc}") from exc
    sessions = manifest.get("sessions")
    if manifest.get("version") != 1 or not isinstance(sessions, list):
        raise RuntimeError(f"Unsupported OpenCode restart manifest: {path}")

    scripts_dir = str(PROJECT_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from _zellij_utils import resume_opencode_session

    for entry in sessions:
        if not isinstance(entry, dict) or not entry.get("session_id"):
            raise RuntimeError(f"Invalid session entry in OpenCode restart manifest: {path}")
        if entry.get("resume_sent_at"):
            continue
        session_id = str(entry["session_id"])
        restore = prepare_opencode_restore(session_id)
        accepted = resume_opencode_session(
            session_name=f"restart-{session_id[:8]}",
            opencode_session_id=session_id,
            cwd=restore["cwd"],
            prompt=_restore_prompt(
                restore,
                "The OpenCode server was intentionally restarted while this turn was running. "
                "Continue the interrupted turn from its existing state and finish the original task. "
                "Do not restart the task or repeat completed work.",
            ),
            permission_mode=str(entry.get("permission_mode") or "plan"),
            provider_id=entry.get("provider_id"),
            model_id=entry.get("model_id"),
            variant=entry.get("variant"),
        )
        if not accepted:
            raise RuntimeError(f"OpenCode rejected continuation for {session_id}; manifest retained at {path}")
        entry["resume_sent_at"] = _now_iso()
        _write_json_atomic(path, manifest)

    deadline = time.monotonic() + 20
    pending = {entry["session_id"] for entry in sessions if not entry.get("resume_verified_at")}
    while pending and time.monotonic() < deadline:
        statuses = _opencode_api_json("/session/status")
        for entry in sessions:
            session_id = entry["session_id"]
            if session_id not in pending:
                continue
            status = statuses.get(session_id) if isinstance(statuses, dict) else None
            current = _opencode_api_json(f"/session/{urllib.parse.quote(session_id, safe='')}")
            updated = int((current.get("time") or {}).get("updated") or 0) if isinstance(current, dict) else 0
            if (isinstance(status, dict) and status.get("type") in OPENCODE_RESTART_ACTIVE_STATUSES) or updated > int(entry.get("updated_before_restart") or 0):
                entry["resume_verified_at"] = _now_iso()
                pending.remove(session_id)
                _write_json_atomic(path, manifest)
        if pending:
            time.sleep(0.5)
    if pending:
        joined = ", ".join(sorted(pending))
        raise RuntimeError(f"Continuation was sent but not verified for: {joined}. Inspect manifest {path}; do not resend blindly.")
    return manifest


def cmd_opencode_restart(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest).expanduser().resolve()
    try:
        if args.restart_action == "capture":
            manifest = capture_opencode_restart_manifest(manifest_path)
            print(f"Captured {len(manifest['sessions'])} busy top-level OpenCode session(s): {manifest_path}")
            for entry in manifest["sessions"]:
                print(f"  {entry['session_id']}  {entry['title']}")
        else:
            manifest = resume_opencode_restart_manifest(manifest_path)
            print(f"Verified {len(manifest['sessions'])} resumed OpenCode session(s): {manifest_path}")
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _discover_interrupted_sessions(
    max_age_hours: int = 24,
    limit: int = 15,
) -> list[dict]:
    """List recent OpenCode sessions that can be resumed."""
    try:
        result = subprocess.run(
            ["opencode", "session", "list", "-n", str(limit), "--format", "json"],
            cwd=str(CONTROL_PLANE_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        sessions = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    discovered = []
    for session in sessions if isinstance(sessions, list) else []:
        if not isinstance(session, dict) or not session.get("id"):
            continue
        updated = datetime.fromtimestamp(float(session.get("updated") or 0) / 1000, tz=timezone.utc)
        if updated < cutoff:
            continue
        title = str(session.get("title") or "(untitled session)")
        discovered.append({
            "session_id": str(session["id"]),
            "last_modified": updated.strftime("%Y-%m-%d %H:%M"),
            "first_user_msg": title,
            "last_assistant_msg": title,
            "likely_complete": False,
        })
    return discovered


def cmd_git_stats(args: argparse.Namespace) -> None:
    """Delegate to scripts/git_stats.py for commit-activity and quality analytics."""
    script = Path(__file__).parent / "git_stats.py"
    cmd = [sys.executable, str(script), "--since", args.since, "--hotspots", str(args.hotspots)]
    if args.author:
        cmd += ["--author", args.author]
    if args.json:
        cmd += ["--json"]
    os.execvp(cmd[0], cmd)


def prepare_opencode_restore(opencode_session_id: str) -> dict[str, Any]:
    """Validate routing and safely advance a resumable worktree to origin/dev."""
    data = _load_sessions()
    def matches_for(open_code_session_id: str) -> list[tuple[str, dict]]:
        return [
            (session_id, session)
            for session_id, session in data.get("sessions", {}).items()
            if isinstance(session, dict) and session.get("opencode_session_id") == open_code_session_id
        ]

    matches = matches_for(opencode_session_id)
    if not matches:
        for parent_opencode_session_id in _opencode_parent_chain(opencode_session_id):
            matches = matches_for(parent_opencode_session_id)
            if matches:
                break
    if not matches:
        return {"cwd": str(CONTROL_PLANE_ROOT), "repository_session_id": "", "advanced": False}
    if len(matches) != 1:
        raise RuntimeError(f"OpenCode session {opencode_session_id} matches multiple repository sessions")
    repository_session_id, session = matches[0]
    worktree = session.get("worktree") if isinstance(session.get("worktree"), dict) else {}
    restore_worktree_status = worktree.get("status")
    worktree_path = Path(str(worktree.get("path") or ""))
    if not worktree_path or not _existing_direct_managed_worktree(worktree_path):
        raise RuntimeError(
            f"Restore blocked: repository session {repository_session_id} has an invalid or missing managed worktree. "
            f"Run `python3 scripts/sessions.py worktree repair --opencode-session {opencode_session_id}` first."
        )
    # A restore starts a new live turn. Invalidate any checkpoint that became
    # eligible while this chat was idle before fetching or advancing its base.
    with _worktree_checkpoint_lock(repository_session_id):
        _mutate_sessions(
            lambda sessions_data: _store_session_worktree_active(
                sessions_data, repository_session_id, _now_iso()
            )
        )
    advanced = False
    if restore_worktree_status in {"active", "merged"}:
        rc, porcelain, stderr = _run_cmd(["git", "status", "--porcelain"], cwd=str(worktree_path))
        if rc != 0:
            raise RuntimeError(f"Restore preflight could not inspect {worktree_path}: {stderr}")
        rc, _stdout, stderr = _run_cmd(["git", "fetch", "origin", "dev"], cwd=str(worktree_path))
        if rc != 0:
            raise RuntimeError(f"Restore preflight could not fetch origin/dev: {stderr}")
        rc, target_commit, stderr = _run_cmd(["git", "rev-parse", "refs/remotes/origin/dev"], cwd=str(worktree_path))
        if rc != 0:
            raise RuntimeError(f"Restore preflight could not resolve origin/dev: {stderr}")
        current_head = _current_git_sha(worktree_path)
        rc, _stdout, stderr = _run_cmd(["git", "merge-base", "--is-ancestor", current_head, target_commit], cwd=str(worktree_path))
        if rc != 0:
            raise RuntimeError("Restore blocked: the worktree diverged from origin/dev; preserve it and reconcile manually. " + stderr)
        rc, upstream_output, stderr = _run_cmd(
            ["git", "diff", "--name-only", current_head, target_commit, "--"], cwd=str(worktree_path)
        )
        if rc != 0:
            raise RuntimeError(f"Restore preflight could not compare upstream changes: {stderr}")
        local_paths = {
            path
            for line in porcelain.splitlines()
            for path in line[3:].split(" -> ")
            if path
        }
        upstream_paths = {line.strip() for line in upstream_output.splitlines() if line.strip()}
        conflicts = sorted(local_paths.intersection(upstream_paths))
        if conflicts:
            if restore_worktree_status == "active":
                # An interrupted active chat may own genuine pending edits on
                # paths that advanced upstream. Preserve that exact checkout so
                # the chat can reconcile its own task context after recovery.
                link_shared_worktree_resources(worktree_path)
                return {
                    "cwd": str(worktree_path),
                    "repository_session_id": repository_session_id,
                    "advanced": False,
                    "preserved_conflicts": conflicts,
                }
            integration = worktree.get("integration") if isinstance(worktree.get("integration"), dict) else {}
            if restore_worktree_status != "merged" or integration.get("status") != "merged":
                raise RuntimeError(
                    "Restore blocked: local work overlaps changes in origin/dev: " + ", ".join(conflicts)
                )
            recovery_path = worktree_path.with_name(
                f"{worktree_path.name}.recovery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            )
            worktree_path.rename(recovery_path)
            _run_cmd(["git", "worktree", "prune"])
            rc, _stdout, stderr = _run_cmd(["git", "worktree", "add", str(worktree_path), target_commit])
            if rc != 0:
                if recovery_path.exists() and not worktree_path.exists():
                    recovery_path.rename(worktree_path)
                raise RuntimeError(f"Restore preflight could not recreate merged worktree: {stderr}")

            def record_recreated(sessions_data: dict) -> None:
                current = sessions_data["sessions"][repository_session_id]
                current_worktree = current["worktree"]
                current_worktree["base_commit"] = target_commit
                current_worktree["status"] = "active"
                current_worktree["recovered_from"] = str(recovery_path)
                current_worktree["recovered_at"] = _now_iso()
                current_worktree["last_active"] = current_worktree["recovered_at"]
                current["last_active"] = current_worktree["last_active"]
                current["binding_mode"] = "worktree_routed"

            _mutate_sessions(record_recreated)
            link_shared_worktree_resources(worktree_path)
            return {"cwd": str(worktree_path), "repository_session_id": repository_session_id, "advanced": True}
        if current_head != target_commit:
            rc, _stdout, stderr = _run_cmd(["git", "switch", "--detach", target_commit], cwd=str(worktree_path))
            if rc != 0:
                raise RuntimeError(f"Restore preflight could not advance the worktree: {stderr}")

        def update(sessions_data: dict) -> None:
            current = sessions_data["sessions"][repository_session_id]
            current_worktree = current["worktree"]
            current_worktree["base_commit"] = target_commit
            current_worktree["status"] = "active"
            current_worktree["last_active"] = _now_iso()
            current["last_active"] = current_worktree["last_active"]
            current["binding_mode"] = "worktree_routed"

        _mutate_sessions(update)
        advanced = current_head != target_commit
    link_shared_worktree_resources(worktree_path)
    return {"cwd": str(worktree_path), "repository_session_id": repository_session_id, "advanced": advanced}


def cmd_restore(args: argparse.Namespace) -> None:
    """Send a continuation prompt to an existing OpenCode session.

    Resumes the session through the OpenCode Web runner and sends a continuation prompt.
    If --list is passed, discovers and prints recent interrupted sessions.
    """
    scripts_dir = str(PROJECT_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from _zellij_utils import resume_opencode_session

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

    # Resolve short IDs against recent OpenCode sessions.
    if not session_id.startswith("ses_") or len(session_id) < 20:
        matches = [
            session["session_id"]
            for session in _discover_interrupted_sessions(max_age_hours=24 * 365, limit=1000)
            if session["session_id"].startswith(session_id)
        ]
        if len(matches) == 1:
            session_id = matches[0]
        elif len(matches) > 1:
            print(f"Error: ambiguous prefix '{session_id}' matches {len(matches)} sessions:", file=sys.stderr)
            for match in matches:
                print(f"  {match}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Error: no session found matching '{session_id}'.", file=sys.stderr)
            sys.exit(1)

    # Keep the name argument as a diagnostic title for compatibility with older callers.
    restore_name = getattr(args, "name", None) or f"restore-{session_id[:8]}"
    prompt = getattr(args, "prompt", None) or (
        "The server crashed and this session was interrupted. "
        "Continue where you left off."
    )

    try:
        restore = prepare_opencode_restore(session_id)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    prompt = _restore_prompt(restore, prompt)

    profile = _opencode_resume_profile(session_id) if getattr(args, "mode", "plan") != "plan" else {}
    success = resume_opencode_session(
        session_name=restore_name,
        opencode_session_id=session_id,
        cwd=restore["cwd"],
        prompt=prompt,
        permission_mode=getattr(args, "mode", "plan"),
        provider_id=profile.get("provider_id"),
        model_id=profile.get("model_id"),
        variant=profile.get("variant"),
    )

    if success:
        print(f"Continuation sent: {restore_name}")
        print(f"OpenCode session: {session_id}")
        print(f"Web chat: {opencode_chat_url(session_id)}")
        print(f"Inspect: python3 scripts/sessions.py chat read {session_id}")
    else:
        print("Error: failed to send continuation. Is the OpenCode server running?", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenMates agent session lifecycle manager"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Start a new session")
    p_start.add_argument(
        "--mode", "-m",
        required=True,
        choices=(*VALID_MODES, *MODE_ALIASES),
        type=lambda value: MODE_ALIASES.get(value, value),
        help="Session mode: 'feature' (new functionality), 'bug' (debugging), "
        "'docs' (documentation), 'question' (codebase questions). "
        "Controls which context sections are shown.",
    )
    p_start.add_argument("--task", "-t", help="Task description")
    p_start.add_argument(
        "--repo",
        default=DEFAULT_REPO_ID,
        choices=sorted(REPO_ALIASES),
        help="Repository to work in (default: openmates; use openmatescloud for the private sibling overlay repo).",
    )
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

    # proof-video
    p_proof_video = sub.add_parser(
        "proof-video",
        help="Produce, review, and upload exact proof videos for OpenCode response embedding",
    )
    proof_actions = p_proof_video.add_subparsers(dest="proof_action", required=True)
    p_proof_produce = proof_actions.add_parser("produce", help="Capture and render an exact CLI command")
    p_proof_produce.add_argument("--session", "-s", required=True, help="Session ID")
    p_proof_produce.add_argument("--run-dir", type=Path)
    p_proof_produce.add_argument("--proof-id", default="session-proof")
    p_proof_produce.add_argument("--subject-commit")
    p_proof_produce.add_argument("--run-id")
    p_proof_produce.add_argument("--target-environment", default="OpenMates dev API")
    p_proof_produce.add_argument(
        "--test-account-provenance",
        default="OpenMates CLI stored session; authentication credentials are not rendered",
    )
    p_proof_produce.add_argument("--narration-id", default="NARR-1")
    p_proof_produce.add_argument("--caption", required=True)
    p_proof_produce.add_argument("--expected-proof", required=True)
    p_proof_produce.add_argument("--acceptance-criterion", action="append", required=True)
    p_proof_produce.add_argument("--audio-path", type=Path, help="Optional ElevenLabs narration audio file")
    p_proof_produce.add_argument("--audio-provider", default="elevenlabs")
    p_proof_produce.add_argument("--audio-model", default="eleven_flash_v2_5")
    p_proof_produce.add_argument("--audio-voice", default="warm_neutral")
    p_proof_produce.add_argument("--audio-reused-from", default="")
    p_proof_produce.add_argument("--timeout-seconds", type=float, default=120.0)
    p_proof_produce.add_argument("argv", nargs=argparse.REMAINDER)
    p_proof_playwright = proof_actions.add_parser(
        "produce-playwright",
        help="Narrate a passing deployed Playwright test recording",
    )
    p_proof_playwright.add_argument("--session", "-s", required=True, help="Session ID")
    p_proof_playwright.add_argument("--run-dir", type=Path)
    p_proof_playwright.add_argument("--source-video", type=Path, required=True)
    p_proof_playwright.add_argument("--proof-id", default="playwright-proof")
    p_proof_playwright.add_argument("--subject-commit", required=True)
    p_proof_playwright.add_argument("--run-id", required=True)
    p_proof_playwright.add_argument("--spec-name", required=True)
    p_proof_playwright.add_argument("--contract-path", type=Path, required=True)
    p_proof_playwright.add_argument("--target-environment", required=True)
    p_proof_playwright.add_argument("--test-account-provenance", required=True)
    p_proof_playwright.add_argument("--narration-id", default="NARR-1")
    p_proof_playwright.add_argument("--caption", required=True)
    p_proof_playwright.add_argument("--expected-proof", required=True)
    p_proof_playwright.add_argument("--acceptance-criterion", action="append", required=True)
    p_proof_playwright.add_argument("--audio-path", type=Path, help="Optional ElevenLabs narration audio file")
    p_proof_playwright.add_argument("--audio-provider", default="elevenlabs")
    p_proof_playwright.add_argument("--audio-model", default="eleven_flash_v2_5")
    p_proof_playwright.add_argument("--audio-voice", default="warm_neutral")
    p_proof_playwright.add_argument("--audio-reused-from", default="")
    p_proof_playwright.add_argument(
        "--device-profile",
        choices=["web-phone", "web-laptop", "apple-iphone-portrait", "apple-ipad-landscape"],
        help="Require exact source and output dimensions for this proof-video surface.",
    )
    p_proof_playwright.add_argument(
        "--playback-rate",
        type=float,
        default=1.0,
        help="Retiming factor for the visible Playwright recording; values below 1 slow the flow down.",
    )
    p_proof_playwright.add_argument(
        "--hold-last-frame-seconds",
        type=float,
        default=0.0,
        help="Clone the final frame for a readable end-state hold before review.",
    )
    p_proof_playwright.add_argument(
        "--ready-timestamp-seconds",
        type=float,
        help="Trim the Playwright recording from this explicit capture-ready timestamp minus the fixed lead.",
    )
    p_proof_playwright.add_argument(
        "--source-end-timestamp-seconds",
        type=float,
        help="Trim the Playwright recording at this explicit source timestamp after the proof-relevant state.",
    )
    p_proof_playwright.add_argument(
        "--demo-audio-path",
        type=Path,
        help="Optional product audio fixture to preserve playback audio when it is part of the proof.",
    )
    p_proof_publish = proof_actions.add_parser("publish", help="Upload a passed proof for OpenCode response embedding")
    p_proof_publish.add_argument("--session", "-s", required=True, help="Session ID")
    p_proof_publish.add_argument("--run-dir", type=Path, required=True)

    # status
    p_status = sub.add_parser("status", help="Show current session state")
    p_status.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON (for machine consumers, e.g. opencode plugin)",
    )
    p_status.add_argument("--all", action="store_true", help="Include durable and historical repository sessions")
    p_status.add_argument("--conflicts", action="store_true", help="Show only relevant active path and task conflicts")
    p_status.add_argument("--session", help="Show one repository/OpenCode identity chain")

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

    p_opencode_chat = sub.add_parser(
        "opencode-chat",
        help="Read or search local OpenCode chat transcripts by session ID or web URL",
    )
    p_opencode_chat_sub = p_opencode_chat.add_subparsers(dest="opencode_chat_action", required=True)

    def add_opencode_chat_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("reference", help="OpenCode session ID, short repository session ID, or code.dev.openmates.org chat URL")
        parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text")
        parser.add_argument("--no-children", action="store_true", help="Do not include child/subagent sessions")
        parser.add_argument("--include-tool-output", action="store_true", help="Include bounded completed tool inputs/outputs")
        parser.add_argument("--signals", choices=sorted(OPENCODE_CHAT_SIGNAL_MODES), default="actionable", help="Signal detail to show; default hides broad grep/read/text noise")
        parser.add_argument("--max-messages", type=int, default=OPENCODE_CHAT_DEFAULT_MAX_MESSAGES)
        parser.add_argument("--max-parts-per-message", type=int, default=OPENCODE_CHAT_DEFAULT_MAX_PARTS_PER_MESSAGE)
        parser.add_argument("--max-part-chars", type=int, default=OPENCODE_CHAT_DEFAULT_MAX_PART_CHARS)
        parser.add_argument("--db", type=Path, help="Override OpenCode SQLite database path")

    def add_opencode_recent_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--days", type=int, default=3, help="Look back this many days")
        parser.add_argument("--limit", type=int, default=20, help="Maximum top-level chats to list")
        parser.add_argument("--json", action="store_true", help="Emit structured JSON")
        parser.add_argument("--db", type=Path, help="Override OpenCode SQLite database path")

    p_opencode_chat_read = p_opencode_chat_sub.add_parser("read", help="Read a bounded chat transcript")
    add_opencode_chat_args(p_opencode_chat_read)
    p_opencode_chat_read.add_argument("--query", help="Only show messages whose message or part JSON contains this text")
    p_opencode_chat_search = p_opencode_chat_sub.add_parser("search", help="Search inside a bounded chat transcript")
    add_opencode_chat_args(p_opencode_chat_search)
    p_opencode_chat_search.add_argument("query", nargs="+", help="Search text")
    p_opencode_chat_recent = p_opencode_chat_sub.add_parser("recent", help="List recent top-level OpenCode chats")
    add_opencode_recent_args(p_opencode_chat_recent)
    p_opencode_chat_attachments = p_opencode_chat_sub.add_parser("attachments", help="Extract retained uploaded files/images from a chat")
    p_opencode_chat_attachments.add_argument("reference", help="OpenCode session ID, short repository session ID, or code.dev.openmates.org chat URL")
    p_opencode_chat_attachments.add_argument("--out", type=Path, help="Directory to write extracted files; defaults to /tmp/opencode/opencode-attachments-<session>")
    p_opencode_chat_attachments.add_argument("--list", action="store_true", help="List attachments without writing files")
    p_opencode_chat_attachments.add_argument("--json", action="store_true", help="Emit structured JSON")
    p_opencode_chat_attachments.add_argument("--no-children", action="store_true", help="Do not include child/subagent sessions")
    p_opencode_chat_attachments.add_argument("--part-id", action="append", help="Extract only this OpenCode part ID; repeat for multiple IDs")
    p_opencode_chat_attachments.add_argument("--db", type=Path, help="Override OpenCode SQLite database path")

    p_chat = sub.add_parser(
        "chat",
        help="Alias for opencode-chat read/search",
    )
    p_chat_sub = p_chat.add_subparsers(dest="opencode_chat_action", required=True)
    p_chat_read = p_chat_sub.add_parser("read", help="Read a bounded OpenCode chat transcript")
    add_opencode_chat_args(p_chat_read)
    p_chat_read.add_argument("--query", help="Only show messages whose message or part JSON contains this text")
    p_chat_search = p_chat_sub.add_parser("search", help="Search inside a bounded OpenCode chat transcript")
    add_opencode_chat_args(p_chat_search)
    p_chat_search.add_argument("query", nargs="+", help="Search text")
    p_chat_recent = p_chat_sub.add_parser("recent", help="List recent top-level OpenCode chats")
    add_opencode_recent_args(p_chat_recent)
    p_chat_attachments = p_chat_sub.add_parser("attachments", help="Extract retained uploaded files/images from a chat")
    p_chat_attachments.add_argument("reference", help="OpenCode session ID, short repository session ID, or code.dev.openmates.org chat URL")
    p_chat_attachments.add_argument("--out", type=Path, help="Directory to write extracted files; defaults to /tmp/opencode/opencode-attachments-<session>")
    p_chat_attachments.add_argument("--list", action="store_true", help="List attachments without writing files")
    p_chat_attachments.add_argument("--json", action="store_true", help="Emit structured JSON")
    p_chat_attachments.add_argument("--no-children", action="store_true", help="Do not include child/subagent sessions")
    p_chat_attachments.add_argument("--part-id", action="append", help="Extract only this OpenCode part ID; repeat for multiple IDs")
    p_chat_attachments.add_argument("--db", type=Path, help="Override OpenCode SQLite database path")

    p_presence = sub.add_parser("presence", help="Manage ephemeral OpenCode presence and task intent")
    p_presence_sub = p_presence.add_subparsers(dest="presence_action", required=True)
    p_presence_update = p_presence_sub.add_parser("update", help="Apply one allowlisted lifecycle update")
    p_presence_update.add_argument("--json-stdin", action="store_true", required=True)
    p_presence_show = p_presence_sub.add_parser("show", help="Show privacy-minimal presence JSON")
    p_presence_show.add_argument("--no-expire", action="store_true", help="Do not project stale live entries to unknown")
    p_presence_role = p_presence_sub.add_parser("child-role", help="Set an explicit OpenCode child role")
    p_presence_role.add_argument("--session", required=True, help="Child OpenCode session ID")
    p_presence_role.add_argument("--parent", required=True, help="Parent OpenCode session ID")
    p_presence_role.add_argument("--role", required=True, choices=["read_only", "reviewer", "writable"])
    p_presence_role.add_argument("--if-unset", action="store_true", help="Keep an existing explicit child role")
    for action in ("claim-task", "renew-task", "release-task"):
        p_presence_task = p_presence_sub.add_parser(action)
        p_presence_task.add_argument("--spec", required=True, help="Repository-relative executable spec path")
        p_presence_task.add_argument("--task", required=True, help="Executable spec task ID")
        p_presence_task.add_argument("--owner", required=True, help="Owning OpenCode session ID")
        if action == "claim-task":
            p_presence_task.add_argument("--role", required=True, choices=["implementation", "reviewer", "read_only"])
        if action != "release-task":
            p_presence_task.add_argument("--ttl", type=int, default=900, help="Renewable claim TTL in seconds")

    p_task_bridge = sub.add_parser("task-bridge", help="Bridge trusted OpenMates Task JSON into OpenCode")
    p_task_bridge_sub = p_task_bridge.add_subparsers(dest="task_bridge_action", required=True)
    p_task_bridge_stage = p_task_bridge_sub.add_parser(
        "stage", help="Stage one completed response for idle reconciliation"
    )
    p_task_bridge_stage.add_argument("--session", required=True, help="Top-level OpenCode session ID")
    p_task_bridge_stage.add_argument("--message-id", required=True, help="Completed assistant message ID")
    for action in ("context", "reconcile"):
        p_task_bridge_action = p_task_bridge_sub.add_parser(action)
        p_task_bridge_action.add_argument("--session", required=True, help="Top-level OpenCode session ID")
    p_task_bridge_tool = p_task_bridge_sub.add_parser("tool", help="Execute one typed Task operation")
    p_task_bridge_tool.add_argument("--session", required=True, help="Top-level OpenCode session ID")
    p_task_bridge_tool.add_argument("--json-stdin", action="store_true", required=True)

    p_continuation = sub.add_parser("continuation", help="Manage bounded deterministic chat continuations")
    p_continuation_sub = p_continuation.add_subparsers(dest="continuation_action", required=True)
    p_continuation_record = p_continuation_sub.add_parser("record", help="Record one ready allowlisted operation")
    p_continuation_record.add_argument("--session", required=True, help="Repository or OpenCode session ID")
    p_continuation_record.add_argument("--operation-type", required=True, choices=sorted(CONTINUATION_ALLOWED_TYPES))
    p_continuation_record.add_argument("--operation-key", required=True)
    p_continuation_record.add_argument("--next-action", required=True)
    for action in ("claim", "ack", "release", "cancel"):
        p_continuation_action = p_continuation_sub.add_parser(action)
        p_continuation_action.add_argument("--session", required=True, help="Repository or OpenCode session ID")

    p_media = sub.add_parser("media", help="Manage durable response-media delivery")
    p_media_sub = p_media.add_subparsers(dest="media_action", required=True)
    p_media_quarantine = p_media_sub.add_parser("quarantine", help="Quarantine undelivered legacy media records")
    p_media_quarantine.add_argument("--session", default="", help="Optional repository or OpenCode session ID")
    p_media_quarantine.add_argument("--reason", default="recovery hotfix")
    p_media_record = p_media_sub.add_parser("record", help="Record one pending response artifact")
    p_media_record.add_argument("--session", required=True, help="Repository or OpenCode session ID")
    p_media_record.add_argument(
        "--artifact-type", required=True, choices=["video", "figma_image", "figma_export"]
    )
    p_media_record.add_argument("--artifact-key", default="")
    p_media_record.add_argument("--artifact-path", default="")
    p_media_record.add_argument("--snippet", required=True)
    p_media_record.add_argument("--subject-commit", default="")
    p_media_record.add_argument("--run-id", default="")
    p_media_claim = p_media_sub.add_parser("claim")
    p_media_claim.add_argument("--session", required=True, help="Repository or OpenCode session ID")
    for action in ("ack", "release"):
        p_media_finish = p_media_sub.add_parser(action)
        p_media_finish.add_argument("--session", required=True, help="Repository or OpenCode session ID")
        p_media_finish.add_argument("--artifact-key", required=True)
    p_media_fail = p_media_sub.add_parser("fail")
    p_media_fail.add_argument("--session", required=True, help="Repository or OpenCode session ID")
    p_media_fail.add_argument("--artifact-key", required=True)
    p_media_fail.add_argument("--reason", default="")

    p_docker = sub.add_parser("docker", help="Run coordinated Docker operations")
    p_docker_sub = p_docker.add_subparsers(dest="docker_action", required=True)
    p_docker_restart = p_docker_sub.add_parser("restart", help="Drain dependent tests and restart services")
    p_docker_restart.add_argument("--session", "-s", required=True, help="Requesting sessions.py ID")
    p_docker_restart.add_argument(
        "--service",
        action="append",
        required=True,
        help="Compose service to restart; repeat for multiple services",
    )
    p_docker_restart.add_argument(
        "--build",
        action="store_true",
        help="Rebuild images and recreate services with Compose up -d --build",
    )
    p_docker_restart.add_argument(
        "--timeout",
        type=int,
        default=DOCKER_RESTART_DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait for the Docker lock and dependent tests",
    )
    p_docker_restart.add_argument("--poll", type=int, default=5, help="Seconds between lease and health checks")
    p_docker_restart.add_argument(
        "--health-timeout",
        type=int,
        default=DOCKER_HEALTH_DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait for restarted services to become healthy",
    )
    p_docker_setup = p_docker_sub.add_parser("run-setup", help="Drain dependent tests and run setup services")
    p_docker_setup.add_argument("--session", "-s", required=True, help="Requesting sessions.py ID")
    p_docker_setup.add_argument(
        "--service",
        action="append",
        required=True,
        help="Setup service to run; repeat for multiple services",
    )
    p_docker_setup.add_argument(
        "--build",
        action="store_true",
        help="Build the setup image before running the service",
    )
    p_docker_setup.add_argument(
        "--timeout",
        type=int,
        default=DOCKER_RESTART_DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait for the Docker lock and dependent tests",
    )
    p_docker_setup.add_argument("--poll", type=int, default=5, help="Seconds between lease checks")

    p_worktree = sub.add_parser("worktree", help="Manage automatic local session worktrees")
    p_worktree_sub = p_worktree.add_subparsers(dest="worktree_action", required=True)
    p_worktree_root_dirty = p_worktree_sub.add_parser(
        "root-dirty", help="List safe dirty files in the canonical root without exposing contents"
    )
    p_worktree_root_dirty.add_argument("--path-prefix", default="", help="Optional repository-relative prefix")
    p_worktree_import_root = p_worktree_sub.add_parser(
        "import-root", help="Import one explicitly selected dirty root file into a clean session path"
    )
    import_identity = p_worktree_import_root.add_mutually_exclusive_group(required=True)
    import_identity.add_argument("--session", "-s", help="sessions.py session ID")
    import_identity.add_argument("--opencode-session", help="Top-level OpenCode session ID")
    p_worktree_import_root.add_argument("--file", required=True, help="Exact repository-relative dirty root file")
    p_worktree_ensure = p_worktree_sub.add_parser("ensure", help="Create or show this session's worktree")
    p_worktree_ensure.add_argument("--session", "-s", required=True, help="Session ID")
    p_worktree_binding = p_worktree_sub.add_parser("binding", help="Record an OpenCode native-binding result")
    p_worktree_binding.add_argument("--opencode-session", required=True, help="OpenCode session ID")
    p_worktree_binding.add_argument("--mode", required=True, choices=["native", "pilot_fallback"])
    p_worktree_binding.add_argument("--directory", help="Canonical native session directory")
    p_worktree_binding.add_argument("--reason", help="Stable pilot fallback reason")
    p_worktree_repair = p_worktree_sub.add_parser("repair", help="Reconstruct root-hosted OpenCode worktree routing")
    p_worktree_repair.add_argument("--opencode-session", required=True, help="Top-level OpenCode session ID")
    p_worktree_refresh_base = p_worktree_sub.add_parser(
        "refresh-base",
        help="Refresh recorded base after a managed worktree was safely fast-forwarded to origin/dev",
    )
    p_worktree_refresh_base.add_argument("--session", "-s", required=True, help="Session ID")
    p_worktree_checkpoint = p_worktree_sub.add_parser("checkpoint", help="Checkpoint an idle or closed mutating OpenCode session")
    p_worktree_checkpoint.add_argument("--opencode-session", required=True, help="Top-level OpenCode session ID")
    p_worktree_checkpoint.add_argument("--event", required=True, choices=["idle", "closed"])
    p_worktree_activate = p_worktree_sub.add_parser(
        "activate", help="Invalidate an idle checkpoint when a chat starts a new user turn"
    )
    p_worktree_activate.add_argument("--opencode-session", required=True, help="Top-level OpenCode session ID")
    p_worktree_auto_integrate = p_worktree_sub.add_parser("auto-integrate", help="Integrate eligible checkpointed work through normal deploy gates")
    p_worktree_auto_integrate.add_argument("--dry-run", action="store_true", help="List eligible checkpoints without deploying")
    p_worktree_expire = p_worktree_sub.add_parser(
        "expire", help="Unconditionally delete managed worktrees at the hard maximum age"
    )
    p_worktree_expire.add_argument(
        "--max-age-hours",
        type=int,
        default=WORKTREE_HARD_MAX_AGE_HOURS,
        help=f"Hard maximum worktree age (minimum/default: {WORKTREE_HARD_MAX_AGE_HOURS})",
    )
    p_worktree_expire.add_argument("--format", choices=["text", "json"], default="text")
    p_worktree_cleanup = p_worktree_sub.add_parser("cleanup", help="Delete safely classified stale worktrees")
    p_worktree_cleanup.add_argument(
        "--idle-hours",
        type=int,
        default=WORKTREE_CLEANUP_IDLE_HOURS,
        help="Hours before safely classified stale worktrees may be deleted (default: 48)",
    )
    p_worktree_deduplicate = p_worktree_sub.add_parser(
        "deduplicate-chats",
        help="Keep only the newest source worktree for each top-level OpenCode chat",
    )
    p_worktree_deduplicate.add_argument("--target", default="origin/dev", help="Exact integration ref")
    p_worktree_deduplicate.add_argument("--apply", action="store_true", help="Checkpoint and remove older duplicates")
    p_worktree_deduplicate.add_argument("--format", choices=["text", "json"], default="text")
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

    p_specification = sub.add_parser("specification", help="Run current Specification tooling against a session worktree")
    p_specification_sub = p_specification.add_subparsers(dest="specification_action", required=True)
    p_specification_approval = p_specification_sub.add_parser(
        "approval-pdf",
        help="Render and publish an exact-fingerprint approval PDF from current tooling",
    )
    p_specification_approval.add_argument("--session", "-s", required=True, help="sessions.py session ID")
    p_specification_approval.add_argument("--bundle", required=True, help="Repository-relative Specification bundle")
    p_specification_approval.add_argument("--baseline-ref", default="HEAD", help="Worktree Git ref used to highlight changes")
    p_specification_approval.add_argument("--new-specification", action="store_true", help="Allow a bundle absent from the baseline")
    p_specification_approval.add_argument("--no-upload", action="store_true", help="Generate without publishing")
    p_specification_approval.add_argument("--dry-run-upload", action="store_true", help="Use a fake media upload")
    p_specification_approval.add_argument("--json", action="store_true", help="Print structured output")

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
        "--follow",
        action="store_true",
        help="Keep following owner transitions until release (no default timeout)",
    )
    p_wait_lock.add_argument(
        "--poll",
        type=int,
        default=30,
        help="Seconds between checks (default: 30)",
    )

    # wait-health
    p_wait_health = sub.add_parser(
        "wait-health",
        help="Wait for shared API health or elect one incident investigator",
    )
    p_wait_health.add_argument(
        "--session", "-s", help="Session ID waiting for API health"
    )
    p_wait_health.add_argument(
        "--url",
        default=os.getenv("OPENMATES_API_HEALTH_URL", API_HEALTH_DEFAULT_URL),
        help=f"Health URL to probe (default: {API_HEALTH_DEFAULT_URL})",
    )
    p_wait_health.add_argument(
        "--timeout",
        type=int,
        help="Seconds to wait before failing (default: health incident stale timeout)",
    )
    p_wait_health.add_argument(
        "--follow",
        action="store_true",
        help="Keep following Docker/incident owner transitions until health is ready",
    )
    p_wait_health.add_argument(
        "--poll",
        type=int,
        default=30,
        help="Seconds between checks (default: 30)",
    )
    p_wait_health.add_argument(
        "--probe-timeout",
        type=int,
        default=API_HEALTH_PROBE_TIMEOUT_SECONDS,
        help=f"Seconds for each HTTP health probe (default: {API_HEALTH_PROBE_TIMEOUT_SECONDS})",
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
    p_prep.add_argument(
        "--use-staged",
        action="store_true",
        dest="use_staged",
        help="Use exactly the staged session file set for the deployment plan.",
    )
    p_prep.add_argument(
        "--only",
        nargs="+",
        help="Use exactly these tracked dirty session files for the deployment plan.",
    )

    p_verify_prepared = sub.add_parser(
        "verify-prepared",
        help="Run an allowlisted exact-patch check using shared lockfile-compatible dependencies",
    )
    p_verify_prepared.add_argument("--session", "-s", required=True, help="Session ID")
    p_verify_prepared.add_argument(
        "--profile",
        required=True,
        choices=[*sorted(PREPARED_VERIFICATION_PROFILES), "installed-cli-identity"],
        help="Fixed validation command or read-only installed CLI inspection",
    )
    p_verify_prepared.add_argument("--only", nargs="+", help="Verify exactly these tracked dirty files")
    p_verify_prepared.add_argument(
        "--use-staged", action="store_true", help="Verify exactly the staged session file set"
    )
    p_verify_prepared.add_argument(
        "--expected-manifest-id", help="Require the immutable manifest printed by prepare-deploy"
    )
    p_verify_prepared.add_argument(
        "--executable", help="Installed CLI executable to inspect (identity profile only)"
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
        "--trailer",
        action="append",
        default=[],
        help="Append one safe single-line commit trailer; repeat for contract provenance",
    )
    p_deploy.add_argument(
        "--exclude",
        "-e",
        nargs="*",
        help="File paths to exclude",
    )
    p_deploy.add_argument(
        "--only",
        nargs="+",
        help="Deploy exactly these tracked dirty session files. Mutually exclusive with --use-staged.",
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
        help="Use exactly the already staged tracked session file set. The source "
        "worktree file contents are applied in isolated integration.",
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
        "--expected-patch-id",
        dest="expected_patch_id",
        help=argparse.SUPPRESS,
    )
    p_deploy.add_argument(
        "--expected-manifest-id",
        dest="expected_manifest_id",
        help="Require the immutable manifest printed by prepare-deploy.",
    )
    p_deploy.add_argument(
        "--expected-checkpoint-commit",
        dest="expected_checkpoint_commit",
        help=argparse.SUPPRESS,
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
    p_deploy.add_argument(
        "--start-verification-session",
        action="store_true",
        dest="start_verification_session",
        help="After a successful deploy, start a fresh testing session for commit-bound Docker/test evidence.",
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
        help="Spawn a persisted OpenCode chat in the existing Web sidebar",
    )
    p_spawn.add_argument(
        "--prompt",
        help="Prompt text to send to OpenCode",
    )
    p_spawn.add_argument(
        "--prompt-file",
        help="Path to a prompt file",
    )
    p_spawn.add_argument(
        "--name", "-n",
        help="Session name (default: auto-generated from timestamp)",
    )
    p_spawn.add_argument(
        "--mode",
        choices=["plan", "execute", "execute-readonly"],
        default="plan",
        help="Permission mode: 'plan' (read-only, default), "
        "'execute-readonly' (Bash/status allowed, edits prohibited), or "
        "'execute' (full edit access with auto-approved permissions)",
    )
    p_spawn.add_argument(
        "--linear-issue", "--linear",
        metavar="ISSUE_ID",
        help="Linear issue to link (e.g., OPE-42). Auto-marks In Progress, "
        "adds claude-is-working label, and injects Linear update instructions.",
    )
    p_spawn.add_argument(
        "--no-deploy-instructions",
        action="store_true",
        help="For coordinator-owned execute workers, omit generic deploy guidance and tell the worker not to deploy.",
    )

    # restore
    p_restore = sub.add_parser(
        "restore",
        help="Send a continuation prompt to an existing OpenCode session",
    )
    p_restore.add_argument(
        "session_id",
        nargs="?",
        help="OpenCode session ID (or prefix) to resume",
    )
    p_restore.add_argument(
        "--list", "-l",
        action="store_true",
        help="Discover and list recent interrupted sessions",
    )
    p_restore.add_argument(
        "--name", "-n",
        help="Diagnostic launch title (default: restore-<id-prefix>)",
    )
    p_restore.add_argument(
        "--mode",
        choices=["plan", "execute"],
        default="plan",
        help="Permission mode for the resumed session (default: plan)",
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

    p_opencode_restart = sub.add_parser(
        "opencode-restart",
        help="Capture or resume the exact busy top-level chat set around a server restart",
    )
    p_opencode_restart_sub = p_opencode_restart.add_subparsers(dest="restart_action", required=True)
    for restart_action in ("capture", "resume"):
        p_restart_action = p_opencode_restart_sub.add_parser(restart_action)
        p_restart_action.add_argument("--manifest", required=True, help="Durable restart manifest path")

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
        "proof-video": cmd_proof_video,
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
        "opencode-chat": cmd_opencode_chat,
        "chat": cmd_opencode_chat,
        "presence": cmd_presence,
        "task-bridge": cmd_task_bridge,
        "continuation": cmd_continuation,
        "media": cmd_media,
        "docker": cmd_docker,
        "worktree": cmd_worktree,
        "specification": cmd_specification,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
        "wait-lock": cmd_wait_lock,
        "wait-health": cmd_wait_health,
        "prepare-deploy": cmd_prepare_deploy,
        "verify-prepared": cmd_verify_prepared,
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
        "opencode-restart": cmd_opencode_restart,
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
