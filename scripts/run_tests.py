#!/usr/bin/env python3
"""
scripts/run_tests.py

Execution engine for OpenMates tests.

Prefer `python3 scripts/tests.py run ...` for manual and agent-triggered test
runs. That control-plane wrapper records current state, history, and failure
leases before delegating here.

Replaces: run-tests.sh, run-tests-daily.sh, run-tests-worker.sh,
          ci/trigger_parallel_specs.sh

Runs pytest and vitest locally (fast), dispatches Playwright E2E specs
to GitHub Actions via playwright-spec.yml in batches of N (default 20),
polls for completion, aggregates results, and sends notifications.

Usage:
    python3 scripts/tests.py run                           # full suite
    python3 scripts/tests.py run --spec chat-flow.spec.ts  # single spec
    python3 scripts/tests.py run --only-failed             # rerun failures
    python3 scripts/tests.py run --suite pytest            # just pytest
    python3 scripts/tests.py run --suite vitest            # just vitest
    python3 scripts/tests.py run --suite playwright        # just browser E2E
    python3 scripts/tests.py run --suite cli               # just CLI integration
    python3 scripts/tests.py run --suite apple             # just Apple Remote checks
    python3 scripts/tests.py run --daily                   # cron mode (3 AM nightly)
    python3 scripts/tests.py run --daily --force           # skip commit check
    python3 scripts/tests.py run --hourly-dev              # hourly dev smoke (4 specs)
    python3 scripts/tests.py run --hourly-prod             # free hourly prod smoke (legacy alias)
    python3 scripts/tests.py run --prod-paid-chat          # paid prod chat smoke (scheduled slots)
    python3 scripts/tests.py run --prod-app-skill          # prod CLI app-skill smoke (daily slot)
    python3 scripts/tests.py run --hourly-dev --dry-run-notify  # test Discord wiring
    python3 scripts/tests.py run --max-concurrent 10       # override batch size
    python3 scripts/tests.py run --no-fail-fast            # run all batches

Architecture: docs/architecture/test-orchestration.md
"""

from __future__ import annotations

import argparse
import fcntl
import asyncio
import base64
import hashlib
import importlib.util
import json
import math
import mimetypes
import os
import re
import signal
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from collections import deque
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

try:
    from scripts import sessions as session_control
    from scripts import daily_ai_cache_backfill
    from scripts import daily_ai_test_policy
    from scripts.spec_demo import sweep_publications as _sweep_spec_demo_publications
except ModuleNotFoundError:
    import sessions as session_control
    import daily_ai_cache_backfill
    import daily_ai_test_policy
    from spec_demo import sweep_publications as _sweep_spec_demo_publications

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _resolve_control_plane_root(checkout_root: Path) -> Path:
    """Resolve the main checkout that owns shared local credentials and config."""
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
RESULTS_DIR = PROJECT_ROOT / "test-results"
STORAGE_AUDIT_CANDIDATE_DIR = RESULTS_DIR / "storage-audit-candidate"
TEST_RECORDINGS_DIR = RESULTS_DIR / "recordings" / "latest"
DAILY_ARTIFACT_RETENTION_DAYS = 7
SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
LOCKFILE = Path("/tmp/openmates-daily-tests.lock")
LOCKFILE_HOURLY_DEV = Path("/tmp/openmates-hourly-dev-tests.lock")
LOCKFILE_HOURLY_PROD = Path("/tmp/openmates-hourly-prod-tests.lock")
LOCKFILE_PROD_PAID_CHAT = Path("/tmp/openmates-prod-paid-chat-tests.lock")
LOCKFILE_PROD_APP_SKILL = Path("/tmp/openmates-prod-app-skill-tests.lock")
# Written by the Claude Code docker-restart-marker hook whenever a
# `docker compose down/restart/stop` command is detected. Hourly smoke
# runs check this file and skip if Docker was restarted too recently.
DOCKER_RESTART_MARKER = Path("/tmp/openmates-last-docker-restart")
DOCKER_GRACE_MINUTES = 10  # skip smoke runs for 10 min after a restart
# After this many consecutive suppressed ticks (same failure hash), the
# summary is re-posted even though nothing changed, so the Discord channel
# doesn't go silent for hours during a prolonged outage.
RENOTIFY_AFTER_TICKS = 3
ESSENTIAL_FAILURE_SUBJECT = "URGENT: Essential services seem to be broken"
ESSENTIAL_TEST_KEYWORDS = ("signup", "login", "chat-flow")
WORKFLOW_NAME = "playwright-spec.yml"
PROOF_VIDEO_PROFILES = {"web-laptop", "web-phone"}
CLI_INTEGRATION_SPEC = "__cli_integration_code_docs__"
PROD_SMOKE_WORKFLOW = "prod-smoke.yml"
PROD_SMOKE_SUITE_FREE_HOURLY = "free-hourly"
PROD_SMOKE_SUITE_PAID_CHAT = "paid-chat"
PROD_SMOKE_SUITE_APP_SKILL_WEB_SEARCH = "app-skill-web-search"
GH_REPO = "glowingkitty/OpenMates"
GH_BRANCH = "dev"
MAX_ACCOUNTS = 27
ACCOUNT_PREFLIGHT_SPEC = "test-account-preflight.spec.ts"
PROVISION_AUTH_ACCOUNTS_SPEC = "cli-provision-auth-accounts.spec.ts"
PLAYWRIGHT_ACCOUNT_NOT_REQUIRED_MARKER = "// playwright-account: not_required reason=isolated_component_preview"
ACCOUNT_FREE_WORKFLOW_ACCOUNT = 0
PLAYWRIGHT_ACCOUNT_LEASE_HELD_ENV = "OPENMATES_PLAYWRIGHT_ACCOUNT_LEASE_HELD"
E2E_GIFT_CARD_REDEMPTION_SPEC = "settings-gift-card-redemption.spec.ts"
E2E_GIFT_CARD_REDEMPTION_CREDITS = 321
E2E_GIFT_CARD_SEED_RETRIES = 5
E2E_GIFT_CARD_CODE_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
E2E_CREDIT_GUARD_DEFAULT_MINIMUM = 20_000
E2E_CREDIT_GUARD_DEFAULT_TARGET = 50_000
BACKEND_LIVE_MOCK_PREFLIGHT_CONTAINERS = (
    "api",
    "app-ai-worker",
    "workflow-worker",
    "task-worker",
    "user-tasks-worker",
    "reminder-worker",
    "app-images-worker",
    "app-videos-worker",
)
BACKEND_LIVE_MOCK_CONDITIONAL_CONTAINERS = frozenset({
    "workflow-worker",
    "user-tasks-worker",
    "reminder-worker",
    "app-images-worker",
    "app-videos-worker",
})
BACKEND_LIVE_MOCK_PREFLIGHT_NAME = "backend-live-mock-preflight"
BACKEND_LIVE_MOCK_PREFLIGHT_FILE = "scripts/run_tests.py"
BACKEND_LIVE_MOCK_PREFLIGHT_DISABLED_VALUES = {"0", "false", "False", "no", "NO"}
RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC = {
    "account-recovery-flow.spec.ts": 14,
    "backup-code-login-flow.spec.ts": 15,
    "backup-codes-settings.spec.ts": 16,
    "cli-created-account-login.spec.ts": 17,
    "recovery-key-login-flow.spec.ts": 17,
    "recovery-key-settings.spec.ts": 18,
    "settings-change-email.spec.ts": 19,
    "api-keys-flow.spec.ts": 20,
}
RESERVED_PLAYWRIGHT_ACCOUNT_SLOTS = frozenset(RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC.values())
NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS = tuple(
    slot for slot in range(1, MAX_ACCOUNTS + 1)
    if slot not in RESERVED_PLAYWRIGHT_ACCOUNT_SLOTS
)
CREDENTIAL_UPDATE_ARTIFACT_NAMES = frozenset({"new_otp_key.txt", "api_key.txt"})
POLL_INTERVAL = 15  # seconds between status checks
DAILY_STATUS_INTERVAL_SECONDS = 30 * 60
DAILY_AI_BACKFILL_PATH_ENV_VARS = (
    "DAILY_AI_CANDIDATE_ROOT",
    "DAILY_AI_RUNTIME_CACHE_ROOT",
    "DAILY_AI_CLAIM_ROOT",
    "DAILY_AI_SOURCE_ROOT",
)
RUN_TIMEOUT = 1800  # 30 min max per batch
PROD_SMOKE_RUN_TIMEOUT = 1800  # 30 min — prod-smoke.yml has its own 25-min job cap
VITEST_TIMEOUT = 300  # seconds — vitest must complete in 5 min or be killed
VERCEL_WAIT_TIMEOUT = 1200  # 20 min max to wait for dev deployment before E2E specs
VERCEL_WAIT_POLL_INTERVAL = 15
APPLE_REMOTE_TIMEOUT = 7200  # seconds — Xcode test/build runs can be slow on the remote Mac
ACCOUNT_PREFLIGHT_CACHE_TTL_SECONDS = 15 * 60
ACCOUNT_PREFLIGHT_CACHE_PATH = CONTROL_PLANE_ROOT / "test-results" / "account-preflight-cache.json"
ACCOUNT_PREFLIGHT_CACHE_LOCK_PATH = Path("/tmp/openmates-account-preflight-cache.lock")
SINGLE_SPEC_PREFLIGHT_FALLBACK_LIMIT = 3
MAX_ERROR_SNIPPET = 600
GITHUB_DISPATCH_RATE_LIMIT_RESERVE = 25
GITHUB_MUTATING_REQUEST_INTERVAL_SECONDS = 1.0
GITHUB_DISPATCH_INCIDENT_KEY = "infrastructure::github-actions-dispatch"
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
TEST_RECORDINGS_BUCKET_KEY = "test_recordings"
TEST_RECORDINGS_S3_PREFIX = "latest"
VERCEL_API = "https://api.vercel.com"
APPLE_REMOTE_NIGHTLY_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sync-repo", ("sync-repo", "--branch", GH_BRANCH)),
    ("test-ios", ("test-ios", "--simulator", "iPhone 17")),
    ("test-macos", ("test-macos",)),
    (
        "verify-watch-startup",
        ("verify-watch-startup", "--simulator", "Apple Watch Series 11 (46mm)", "--duration", "60"),
    ),
)

# Hourly dev smoke spec list — kept SHORT on purpose. See OPE-349 + the
# tests/dev-smoke/README.md for the policy. Anything that isn't a core user
# flow that must keep working belongs in the nightly run, not here.
CORE_JOURNEY_SPECS: list[str] = [
    # Order determines test-account slot: specs[i] → account (i+1).
    # chat-flow is first so it uses testacct1 (known healthy) — testacct4 has
    # accumulated broken chat state that stalls DB init during login.
    # dev-smoke doesn't use account credentials, so it can safely run on any slot.
    "chat-flow.spec.ts",
    "settings-buy-credits-stripe-managed.spec.ts",
    "signup-flow-stripe-managed.spec.ts",
    "dev-smoke/dev-smoke-reachability.spec.ts",
]
CORE_JOURNEY_ACCOUNT_SLOTS = (2, 3, 5, 6)
HOURLY_DEV_SPECS = CORE_JOURNEY_SPECS

# The promotion gate is intentionally broader than the hourly smoke. Filename
# patterns make new signup and billing specs release-blocking by default.
RELEASE_GATE_SPEC_PATTERNS = (
    "*signup*.spec.ts",
    "buy-credits-flow.spec.ts",
    "saved-payment-invoice-flow.spec.ts",
    "settings-buy-credits-*.spec.ts",
    "settings-gift-card-*.spec.ts",
    "settings-support-*.spec.ts",
    "usage-token-breakdown.spec.ts",
)
RELEASE_GATE_BASE_SPECS = (
    "chat-flow.spec.ts",
    "dev-smoke/dev-smoke-reachability.spec.ts",
)
RELEASE_GATE_EXCLUDED_PREFIXES = ("prod-smoke/",)
RELEASE_GATE_ACCOUNT_SLOTS = (2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 21, 22, 23, 24, 25, 26, 27)
RELEASE_GATE_MAX_ACCOUNT_WAVES = 2


def discover_release_gate_specs() -> list[str]:
    """Return core availability plus every signup and billing E2E spec."""
    related_specs = {
        path.relative_to(SPEC_DIR).as_posix()
        for pattern in RELEASE_GATE_SPEC_PATTERNS
        for path in SPEC_DIR.rglob(pattern)
    }
    related_specs = {
        spec for spec in related_specs
        if not spec.startswith(RELEASE_GATE_EXCLUDED_PREFIXES)
    }
    return [*RELEASE_GATE_BASE_SPECS, *sorted(related_specs - set(RELEASE_GATE_BASE_SPECS))]


RELEASE_GATE_SPECS = discover_release_gate_specs()

CRITICAL_TEST_CATEGORIES = frozenset({"billing", "signup_auth", "core_chat"})
CORE_CHAT_CRITICAL_SPEC_PATTERNS = ("*chat*.spec.ts",)
CRITICAL_TEST_REGISTRY: tuple[dict[str, object], ...] = (
    {"spec": "chat-flow.spec.ts", "category": "core_chat", "reason": "Primary authenticated chat journey.", "active": True},
    {"spec": "anonymous-free-chat.spec.ts", "category": "core_chat", "reason": "Primary anonymous chat journey.", "active": True},
    {"spec": "signup-2fa-reconnect-preview.spec.ts", "category": "signup_auth", "reason": "Signup reconnect and 2FA recovery.", "active": True},
    {"spec": "signup-flow-bank-transfer.spec.ts", "category": "signup_auth", "reason": "Signup with bank-transfer billing setup.", "active": True},
    {"spec": "signup-flow-passkey.spec.ts", "category": "signup_auth", "reason": "Passkey signup and authentication.", "active": True},
    {"spec": "signup-flow-stripe-eu.spec.ts", "category": "signup_auth", "reason": "EU Stripe signup journey.", "active": True},
    {"spec": "signup-flow-stripe-managed.spec.ts", "category": "signup_auth", "reason": "Managed Stripe signup journey.", "active": True},
    {"spec": "signup-free-testing-credits.spec.ts", "category": "signup_auth", "reason": "Free-credit signup entitlement.", "active": True},
    {"spec": "signup-skip-2fa-flow.spec.ts", "category": "signup_auth", "reason": "Signup path without optional 2FA.", "active": True},
    {"spec": "buy-credits-flow.spec.ts", "category": "billing", "reason": "Primary credit purchase journey.", "active": True},
    {"spec": "referral-signup-purchase.spec.ts", "category": "billing", "reason": "Referral attribution through purchase.", "active": True},
    {"spec": "saved-payment-invoice-flow.spec.ts", "category": "billing", "reason": "Saved payment and invoice journey.", "active": True},
    {"spec": "settings-buy-credits-bank-transfer.spec.ts", "category": "billing", "reason": "Settings bank-transfer purchase.", "active": True},
    {"spec": "settings-buy-credits-stripe-eu.spec.ts", "category": "billing", "reason": "Settings EU Stripe purchase.", "active": True},
    {"spec": "settings-buy-credits-stripe-managed.spec.ts", "category": "billing", "reason": "Settings managed Stripe purchase.", "active": True},
    {"spec": "settings-gift-card-bank-transfer.spec.ts", "category": "billing", "reason": "Gift-card bank-transfer journey.", "active": True},
    {"spec": "settings-gift-card-redemption.spec.ts", "category": "billing", "reason": "Gift-card redemption and credit application.", "active": True},
    {"spec": "settings-support-bank-transfer.spec.ts", "category": "billing", "reason": "Support payment by bank transfer.", "active": True},
    {"spec": "settings-support-stripe.spec.ts", "category": "billing", "reason": "Support payment by Stripe.", "active": True},
    {"spec": "usage-token-breakdown.spec.ts", "category": "billing", "reason": "Usage and charged-token accounting.", "active": True},
)

REVIEWED_BROAD_CHAT_SPECS = frozenset({
    "apple-chat-history-contracts.spec.ts",
    "apple-chat-ui-contracts.spec.ts",
    "apple-cross-client-chat.spec.ts",
    "background-chat-notification.spec.ts",
    "chat-error-report-consent.spec.ts",
    "chat-header-navigation-order.spec.ts",
    "chat-key-wrapper-migration.spec.ts",
    "chat-management-flow.spec.ts",
    "chat-rendering-parity-oracle.spec.ts",
    "chat-replay-demo-mode.spec.ts",
    "chat-response-processing-ui.spec.ts",
    "chat-scroll-streaming.spec.ts",
    "chat-search-flow.spec.ts",
    "chat-settings-flow.spec.ts",
    "chat-streaming-render-performance.spec.ts",
    "chat-sync-empty-indexeddb-recovery.spec.ts",
    "cli-workflows-ai-chat-real.spec.ts",
    "daily-inspiration-chat-flow.spec.ts",
    "example-chat-clone.spec.ts",
    "example-chat-logout-preserve.spec.ts",
    "example-chat-settings-usage.spec.ts",
    "example-chat-speech.spec.ts",
    "example-chats-load.spec.ts",
    "explain-in-new-chat.spec.ts",
    "focus-mode-example-chats.spec.ts",
    "hidden-chats-flow.spec.ts",
    "import-chats.spec.ts",
    "long-chat-history.spec.ts",
    "models3d-example-chat.spec.ts",
    "new-chat-pinned-sort.spec.ts",
    "prod-smoke/prod-smoke-signup-giftcard-chat.spec.ts",
    "recent-chats-dedup.spec.ts",
    "reminder-new-chat.spec.ts",
    "reminder-same-chat.spec.ts",
    "seo-demo-chat.spec.ts",
    "share-chat-flow.spec.ts",
    "shared-chat-embed-assets.spec.ts",
    "shared-chat-open.spec.ts",
    "show-more-chats-flow.spec.ts",
    "stop-new-chat-draft.spec.ts",
    "sub-chats-flow.spec.ts",
    "sub-chats-real-inference.spec.ts",
    "task-workflow-example-chats.spec.ts",
    "tasks-chat-settings-parity.spec.ts",
    "unauthenticated-chat-navigation.spec.ts",
    "webhook-incoming-chat.spec.ts",
})
CRITICAL_TEST_REGISTRY = (
    *CRITICAL_TEST_REGISTRY,
    *tuple(
        {
            "spec": spec,
            "category": "core_chat",
            "reason": "Reviewed as specialized broad chat coverage rather than a primary critical journey.",
            "active": False,
        }
        for spec in sorted(REVIEWED_BROAD_CHAT_SPECS)
    ),
)


def audit_critical_test_registry() -> list[str]:
    """Return deterministic registry defects without dispatching tests."""
    issues: list[str] = []
    seen: set[str] = set()
    classified_specs: set[str] = set()
    for entry in CRITICAL_TEST_REGISTRY:
        spec = str(entry.get("spec") or "")
        category = str(entry.get("category") or "")
        reason = str(entry.get("reason") or "").strip()
        if not isinstance(entry.get("active"), bool):
            issues.append(f"invalid active flag for {spec}")
        if not spec or spec in seen:
            issues.append(f"duplicate or empty critical spec: {spec or '<empty>'}")
        seen.add(spec)
        classified_specs.add(spec)
        if category not in CRITICAL_TEST_CATEGORIES:
            issues.append(f"invalid critical category for {spec}: {category}")
        if not reason:
            issues.append(f"missing critical reason for {spec}")
        if not (SPEC_DIR / spec).is_file():
            issues.append(f"classified critical-candidate spec is missing: {spec}")

    likely_critical = set(RELEASE_GATE_SPECS) - {"dev-smoke/dev-smoke-reachability.spec.ts"}
    likely_critical.update(
        path.relative_to(SPEC_DIR).as_posix()
        for pattern in CORE_CHAT_CRITICAL_SPEC_PATTERNS
        for path in SPEC_DIR.rglob(pattern)
    )
    for spec in sorted(likely_critical - classified_specs):
        issues.append(f"likely critical spec is unclassified: {spec}")
    return issues


def daily_playwright_phases(all_specs: list[str]) -> dict[str, list[str]]:
    """Partition a daily Playwright run into ordered critical and broad phases."""
    available = set(all_specs)
    critical = [
        str(entry["spec"])
        for entry in CRITICAL_TEST_REGISTRY
        if entry.get("active") is True and entry["spec"] in available
    ]
    critical_set = set(critical)
    return {
        "critical": critical,
        "broad": [spec for spec in all_specs if spec not in critical_set],
    }


def execute_daily_playwright_phases(
    phases: dict[str, list[str]],
    run_phase: Callable[[str, list[str]], SuiteResult],
    registry_issues: Optional[list[str]] = None,
) -> dict[str, SuiteResult]:
    """Execute all daily phases even when registry metadata needs repair."""
    results = {
        "critical": run_phase("critical", phases["critical"]),
        "broad": run_phase("broad", phases["broad"]),
    }
    if registry_issues:
        reason = "; ".join(registry_issues)
        results["registry"] = SuiteResult(
            status="failed",
            tests=[{
                "name": "critical-test-registry",
                "file": "scripts/run_tests.py",
                "status": "infrastructure_incident",
                "error": reason,
            }],
            reason=reason,
        )
    return results


def print_core_journey_matrix() -> None:
    """Print the canonical release-gate matrix for GitHub Actions."""
    if len(RELEASE_GATE_SPECS) > len(RELEASE_GATE_ACCOUNT_SLOTS) * RELEASE_GATE_MAX_ACCOUNT_WAVES:
        raise RuntimeError(
            "Release gate requires more specs than the configured serialized account capacity"
        )
    matrix = {
        "include": [
            {
                "spec": spec,
                "account": str(RELEASE_GATE_ACCOUNT_SLOTS[index % len(RELEASE_GATE_ACCOUNT_SLOTS)]),
            }
            for index, spec in enumerate(RELEASE_GATE_SPECS)
        ]
    }
    print(json.dumps(matrix, separators=(",", ":")))

# Where each hourly mode parks its result archives + heartbeat marker.
HOURLY_DEV_DIR = RESULTS_DIR / "hourly-dev"
HOURLY_PROD_DIR = RESULTS_DIR / "hourly-prod"
PROD_PAID_CHAT_DIR = RESULTS_DIR / "prod-paid-chat"
PROD_APP_SKILL_DIR = RESULTS_DIR / "prod-app-skill"
HOURLY_ARCHIVE_RETENTION_DAYS = 7
BERLIN_TZ = ZoneInfo("Europe/Berlin")
PROD_FREE_HOURLY_START_HOUR = 6
PROD_FREE_HOURLY_END_HOUR = 23
PROD_PAID_CHAT_HOURS = frozenset({7, 13, 19})
PROD_APP_SKILL_HOURS = frozenset({9})
ACCOUNT_IMPORT_TEST_CATALOG = (
    "account-import: backend parser/limits/scan/fail-closed pytest",
    "account-import: frontend CLI parser/client node test",
    "account-import: npm SDK import parity node test",
    "account-import: pip SDK import parity pytest",
    "account-import: real dev CLI verifier script",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SpecResult:
    """Result of a single test (unit test or E2E spec)."""
    name: str
    status: str  # passed | failed | not_started | skipped | timeout | dispatch_error | result_unknown
    duration_seconds: float = 0.0
    error: Optional[str] = None
    file: Optional[str] = None
    run_id: Optional[int] = None
    account: Optional[int] = None
    account_email: Optional[str] = None
    retries: int = 0
    flaky: bool = False
    attempt_statuses: list[str] = field(default_factory=list)
    # Structured Playwright data for MD reports
    playwright_errors: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    screenshot_paths: list[str] = field(default_factory=list)
    video_paths: list[str] = field(default_factory=list)
    video_artifact_name: Optional[str] = None
    proof_timeline_path: Optional[str] = None
    github_run_url: Optional[str] = None
    debug_artifacts: list[str] = field(default_factory=list)
    debug_output_summary: Optional[str] = None
    environment_blocker: Optional[str] = None
    test_key: Optional[str] = None
    parent_incident_key: Optional[str] = None


@dataclass
class SuiteResult:
    """Result of a test suite (e.g., vitest, pytest, playwright)."""
    status: str  # passed | failed | error | skipped
    tests: list[dict] = field(default_factory=list)
    duration_seconds: float = 0.0
    reason: Optional[str] = None


@dataclass
class RunResult:
    """Aggregated results across all suites."""
    run_id: str
    git_sha: str
    git_branch: str
    environment: str
    duration_seconds: float
    summary: dict  # {total, passed, failed, dispatch_error, skipped, not_started}
    suites: dict  # {suite_name: SuiteResult as dict}
    flags: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SeededGiftCard:
    spec: str
    code: str
    directus_id: str
    credits_value: int


@dataclass
class DispatchCircuit:
    """Thread-safe one-way circuit for a run-wide GitHub dispatch incident."""
    is_open: bool = False
    incident_code: str = ""
    reset_at: Optional[int] = None
    _incident_claimed: bool = False
    _remaining_requests: Optional[int] = None
    _budget_configured: bool = False
    _next_mutating_request_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def wait_for_mutating_request_slot(self) -> None:
        """Globally serialize GitHub workflow dispatches across worker threads."""
        with self._lock:
            now = time.monotonic()
            scheduled_at = max(now, self._next_mutating_request_at)
            self._next_mutating_request_at = scheduled_at + GITHUB_MUTATING_REQUEST_INTERVAL_SECONDS
        delay = scheduled_at - now
        if delay > 0:
            time.sleep(delay)

    def _open_locked(self, incident_code: str, reset_at: Optional[int]) -> bool:
        if self.is_open:
            return False
        self.is_open = True
        self.incident_code = incident_code
        self.reset_at = reset_at
        return True

    def open_rate_limit(self, reset_at: Optional[int] = None) -> bool:
        with self._lock:
            return self._open_locked("github_actions_rate_limit", reset_at)

    def open_budget_unknown(self) -> bool:
        with self._lock:
            if self._budget_configured:
                return False
            return self._open_locked("github_actions_budget_unknown", None)

    def configure_budget(self, remaining: int, reset_at: Optional[int]) -> None:
        with self._lock:
            if self._budget_configured:
                return
            self._remaining_requests = remaining
            self.reset_at = reset_at
            self._budget_configured = True

    def reserve_requests(self, count: int) -> bool:
        """Atomically reserve dispatch calls while preserving the safety floor."""
        with self._lock:
            if self.is_open:
                return False
            if not self._budget_configured or self._remaining_requests is None:
                self._open_locked("github_actions_budget_unknown", None)
                return False
            if self._remaining_requests - count < GITHUB_DISPATCH_RATE_LIMIT_RESERVE:
                self._open_locked("github_actions_rate_limit", self.reset_at)
                return False
            self._remaining_requests -= count
            return True

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "open": self.is_open,
                "incident_code": self.incident_code,
                "reset_at": self.reset_at,
            }

    def claim_incident(self) -> bool:
        """Return True once so parallel suites emit one parent incident."""
        with self._lock:
            if not self.is_open or self._incident_claimed:
                return False
            self._incident_claimed = True
            return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROBLEM_STATUSES = {
    "failed",
    "dispatch_error",
    "timeout",
    "result_unknown",
    "not_started",
    "infrastructure_incident",
    "blocked_by_parent",
}


def _is_problem_status(status: str) -> bool:
    """Return True for statuses that should page/alert operators."""
    return status in PROBLEM_STATUSES


def _problem_count(summary: dict) -> int:
    """Count all alert-worthy problems, including GitHub dispatch failures."""
    return (
        int(summary.get("failed", 0))
        + int(summary.get("dispatch_error", 0))
        + int(summary.get("timeout", 0))
        + int(summary.get("result_unknown", 0))
        + int(summary.get("not_started", 0))
        + int(summary.get("infrastructure_incident", 0))
        + int(summary.get("blocked_by_parent", 0))
    )


def _exit_code_for_summary(summary: dict) -> int:
    """Fail the runner for every status that requires operator attention."""
    return 1 if _problem_count(summary) > 0 else 0


def _is_github_rate_limit_error(detail: str) -> bool:
    normalized = detail.lower()
    return "rate limit" in normalized and ("403" in normalized or "exceeded" in normalized)


def github_dispatch_error_category(detail: str) -> str:
    """Reduce provider output to a stable category safe for logs and artifacts."""
    normalized = detail.lower()
    if _is_github_rate_limit_error(detail):
        return "rate_limited"
    if "401" in normalized or "unauthorized" in normalized or "authentication" in normalized:
        return "authentication_failed"
    if "403" in normalized or "permission" in normalized or "forbidden" in normalized:
        return "permission_denied"
    if "timeout" in normalized or "timed out" in normalized:
        return "transport_timeout"
    return "workflow_dispatch_failed"


def _problem_summary_label(summary: dict) -> str:
    """Human-readable compact label for alert titles."""
    parts = []
    if summary.get("failed", 0):
        parts.append(f"{summary['failed']} failed")
    if summary.get("dispatch_error", 0):
        count = summary["dispatch_error"]
        parts.append(f"{count} dispatch {'error' if count == 1 else 'errors'}")
    if summary.get("timeout", 0):
        parts.append(f"{summary['timeout']} timed out")
    if summary.get("result_unknown", 0):
        parts.append(f"{summary['result_unknown']} unknown")
    if summary.get("not_started", 0):
        parts.append(f"{summary['not_started']} not started")
    return ", ".join(parts) if parts else "all passed"


CRITICAL_PRODUCT_AREA_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Billing & payments",
        ("billing", "payment", "stripe", "credit", "invoice", "purchase", "bank transfer", "usage"),
    ),
    (
        "Signup & authentication",
        (
            "signup", "sign up", "login", "log in", "recovery key", "backup code",
            "passkey", "2fa", "change email", "force logout", "account delete",
            "delete account", "authentication",
        ),
    ),
    (
        "Core chat",
        ("chat", "composer", "encryption", "chat sync", "recent chats"),
    ),
)

PRODUCT_AREA_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    CRITICAL_PRODUCT_AREA_RULES[1],
    CRITICAL_PRODUCT_AREA_RULES[0],
    CRITICAL_PRODUCT_AREA_RULES[2],
    ("Apps & skills", ("skill", "apps api", "focus mode", "daily inspiration", "reminder")),
    ("Workflows, tasks & plans", ("workflow", "task", "plan")),
    ("Embeds & files", ("embed", "pdf", "paste", "source quote", "detail")),
    ("Sharing & collaboration", ("share", "team", "project", "referral")),
    ("Settings & account", ("settings", "account", "session", "language", "translation")),
)
DEFAULT_PRODUCT_AREA = "Platform & quality"


def _matches_product_area(searchable: str, keywords: tuple[str, ...]) -> bool:
    """Match whole normalized words or phrases in a test identifier."""
    normalized = " " + re.sub(r"[^a-z0-9]+", " ", searchable.lower()).strip() + " "
    return any(f" {keyword} " in normalized for keyword in keywords)


def _primary_product_area(searchable: str) -> str:
    """Return the single display group used for a failed file."""
    for area_name, keywords in PRODUCT_AREA_RULES:
        if _matches_product_area(searchable, keywords):
            return area_name
    return DEFAULT_PRODUCT_AREA


def _build_discord_failure_embeds(
    suites: dict,
    color: int,
    truncate_descriptions: bool = True,
) -> list[dict]:
    """Build one product-area-grouped Discord embed per failing suite."""
    suite_failures: list[tuple[str, int, dict[str, int], dict[str, list[str]]]] = []
    for suite_name, suite_data in suites.items():
        failed_file_counts: dict[str, int] = {}
        failed_file_searchable: dict[str, list[str]] = {}
        failure_count = 0
        for test in (suite_data or {}).get("tests", []):
            if not _is_problem_status(test.get("status", "")):
                continue
            failure_count += 1
            test_file = test.get("file") or test.get("name") or "unknown"
            # Pytest node IDs identify a test after the file with `::`.
            test_file = str(test_file).split("::", 1)[0]
            failed_file_counts[test_file] = failed_file_counts.get(test_file, 0) + 1
            failed_file_searchable.setdefault(test_file, []).append(
                str(test.get("name") or test_file)
            )
        if failure_count:
            suite_failures.append(
                (suite_name, failure_count, failed_file_counts, failed_file_searchable)
            )

    suite_failures.sort(key=lambda suite: (-suite[1], suite[0]))
    embeds: list[dict] = []
    for suite_name, failure_count, failed_file_counts, failed_file_searchable in suite_failures:
        category_label = suite_name.replace("_", " ").capitalize()
        file_label = "file" if len(failed_file_counts) == 1 else "files"
        suite_failure_label = "failure" if failure_count == 1 else "failures"
        title = (
            f"{category_label} · {failure_count} {suite_failure_label} · "
            f"{len(failed_file_counts)} {file_label}"
        )

        lines = ["**Critical product areas**"]
        for area_name, keywords in CRITICAL_PRODUCT_AREA_RULES:
            matching_files = sum(
                _matches_product_area(
                    f"{test_file} {' '.join(failed_file_searchable[test_file])}", keywords
                )
                for test_file in failed_file_counts
            )
            status_icon = "🔴" if matching_files else "🟢"
            failed_file_label = "failed file" if matching_files == 1 else "failed files"
            lines.append(f"{status_icon} {area_name}: **{matching_files}** {failed_file_label}")

        grouped_files: dict[str, list[tuple[str, int]]] = {}
        for test_file, count in failed_file_counts.items():
            searchable = f"{test_file} {' '.join(failed_file_searchable[test_file])}"
            area_name = _primary_product_area(searchable)
            grouped_files.setdefault(area_name, []).append((test_file, count))

        lines.extend(["", "**Files by product area**"])
        area_order = [area_name for area_name, _keywords in PRODUCT_AREA_RULES]
        area_order.append(DEFAULT_PRODUCT_AREA)
        for area_name in area_order:
            area_files = grouped_files.get(area_name, [])
            if not area_files:
                continue
            area_failures = sum(count for _test_file, count in area_files)
            failure_label = "failure" if area_failures == 1 else "failures"
            area_file_label = "file" if len(area_files) == 1 else "files"
            lines.append(
                f"**{area_name} · {area_failures} {failure_label} · "
                f"{len(area_files)} {area_file_label}**"
            )
            for test_file, count in sorted(area_files):
                count_suffix = f" — {count} failures" if count > 1 else ""
                lines.append(f"• `{test_file}`{count_suffix}")

        description = (
            _fit_discord_description(lines)
            if truncate_descriptions
            else "\n".join(lines)
        )
        embeds.append({
            "title": title,
            "description": description,
            "color": color,
        })
    return embeds


def _plain_notification_text(value: str) -> str:
    """Remove Discord markdown while preserving the grouped report structure."""
    return (
        value.replace("**", "")
        .replace("`", "")
        .replace("🔴", "FAIL")
        .replace("🟢", "OK")
        .replace("•", "-")
    )


def _cache_backfill_notification_line(result: RunResult) -> str | None:
    """Render structural cache-backfill state without forwarding failure details."""
    backfill = result.flags.get("cache_backfill")
    if not isinstance(backfill, dict):
        return None
    status = str(backfill.get("status") or "unknown")
    spec = str(backfill.get("spec") or "")
    group = str(backfill.get("cache_group") or "")
    suffix = f" ({spec}, {group})" if spec and group else ""
    return f"Cache backfill: {status}{suffix}"


def _limit_discord_failure_embeds(embeds: list[dict], color: int) -> list[dict]:
    """Reserve one Discord embed for the run summary and report overflow."""
    max_detail_embeds = DISCORD_MAX_EMBEDS - 1
    if len(embeds) <= max_detail_embeds:
        return embeds

    visible = embeds[:max_detail_embeds - 1]
    omitted = embeds[max_detail_embeds - 1:]
    omitted_lines = [f"• {embed['title']}" for embed in omitted]
    visible.append({
        "title": f"{len(omitted)} more failing suites",
        "description": _fit_discord_description(omitted_lines),
        "color": color,
    })
    return visible


def _fit_discord_description(lines: list[str], max_chars: Optional[int] = None) -> str:
    """Fit whole summary lines within Discord's description limit."""
    if max_chars is None:
        max_chars = DISCORD_DESCRIPTION_MAX_CHARS
    description = "\n".join(lines)
    if len(description) <= max_chars:
        return description

    prior_omitted = 0
    content_lines = []
    for line in lines:
        omission_match = re.match(r"^…and (\d+) more failed files;", line)
        if omission_match:
            prior_omitted += int(omission_match.group(1))
        else:
            content_lines.append(line)

    total_file_lines = prior_omitted + sum(line.startswith("• `") for line in content_lines)
    fitted: list[str] = []
    included_file_lines = 0
    for line in content_lines:
        next_file_count = included_file_lines + int(line.startswith("• `"))
        omitted = total_file_lines - next_file_count
        omission_line = f"…and {omitted} more failed files; see the full test report."
        candidate = "\n".join([*fitted, line, omission_line])
        if len(candidate) > max_chars:
            break
        fitted.append(line)
        included_file_lines = next_file_count

    omitted = total_file_lines - included_file_lines
    fitted.append(f"…and {omitted} more failed files; see the full test report.")
    return "\n".join(fitted)


def _fit_discord_embed_total(embeds: list[dict]) -> list[dict]:
    """Keep the full Discord message within its aggregate embed text cap."""
    fitted = [dict(embed) for embed in embeds]

    def total_chars() -> int:
        return sum(
            len(str(embed.get("title", ""))) + len(str(embed.get("description", "")))
            for embed in fitted
        )

    overage = total_chars() - DISCORD_EMBED_TOTAL_MAX_CHARS
    if overage <= 0:
        return fitted

    # Detail embeds start after the run summary. Trim longest file lists first,
    # retaining enough space for each suite's critical-area block.
    detail_indexes = sorted(
        range(1, len(fitted)),
        key=lambda index: len(str(fitted[index].get("description", ""))),
        reverse=True,
    )
    for index in detail_indexes:
        if overage <= 0:
            break
        description = str(fitted[index].get("description", ""))
        minimum_chars = min(len(description), DISCORD_MIN_DETAIL_DESCRIPTION_CHARS)
        reducible = len(description) - minimum_chars
        if reducible <= 0:
            continue
        target_chars = len(description) - min(overage, reducible)
        fitted[index]["description"] = _fit_discord_description(
            description.splitlines(), target_chars
        )
        overage = total_chars() - DISCORD_EMBED_TOTAL_MAX_CHARS
    return fitted


def _apple_remote_commands_for_nightly() -> list[tuple[str, tuple[str, ...]]]:
    """Return serialized Apple Remote commands for the nightly suite."""
    raw = os.getenv("OPENMATES_APPLE_REMOTE_NIGHTLY_COMMANDS", "").strip()
    if not raw:
        return list(APPLE_REMOTE_NIGHTLY_COMMANDS)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log(f"Invalid OPENMATES_APPLE_REMOTE_NIGHTLY_COMMANDS JSON: {exc}; using defaults", "WARN")
        return list(APPLE_REMOTE_NIGHTLY_COMMANDS)

    if not isinstance(parsed, list):
        _log("OPENMATES_APPLE_REMOTE_NIGHTLY_COMMANDS must be a JSON list; using defaults", "WARN")
        return list(APPLE_REMOTE_NIGHTLY_COMMANDS)

    commands: list[tuple[str, tuple[str, ...]]] = []
    for index, entry in enumerate(parsed, start=1):
        label = f"apple-remote-{index}"
        command: object = entry
        if isinstance(entry, dict):
            label = str(entry.get("name") or label)
            command = entry.get("command")
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            _log(f"Ignoring invalid Apple Remote command entry #{index}", "WARN")
            continue
        commands.append((label, tuple(command)))
    return commands


def _print_test_catalog() -> None:
    """Print deterministic catalog entries used by spec evidence checks."""
    for entry in ACCOUNT_IMPORT_TEST_CATALOG:
        print(entry)


def _test_recording_slug(spec_name: str) -> str:
    """Return a stable URL/S3-safe slug for a Playwright spec file."""
    slug = spec_name.replace(".spec.ts", "").replace(".test.ts", "")
    slug = slug.replace("/", "-").replace("\\", "-")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", slug).strip("-._")
    return slug or "unknown"


def _print_flaky_report() -> None:
    """Print top flaky tests from flaky-history.json."""
    history_path = RESULTS_DIR / "flaky-history.json"
    if not history_path.is_file():
        print("No flaky history found (test-results/flaky-history.json)")
        return

    with open(history_path) as f:
        history = json.load(f)

    tests = history.get("tests", {})
    if not tests:
        print("No test history recorded yet.")
        return

    # Sort by flaky_count descending, then by flakiness rate
    ranked = []
    for key, entry in tests.items():
        total = entry.get("total_runs", 0)
        flaky = entry.get("flaky_count", 0)
        if total > 0 and flaky > 0:
            rate = flaky / total
            ranked.append((key, flaky, total, rate, entry.get("last_flaky_date", "?")))

    if not ranked:
        print("No flaky tests detected in history.")
        return

    ranked.sort(key=lambda x: (-x[3], -x[1]))  # rate desc, then count desc

    print(f"\nTop flaky tests ({len(ranked)} total, ADVISORY):\n")
    print(f"{'Rate':>6}  {'Flaky/Total':>12}  {'Last Flaky':<12}  Test")
    print(f"{'─' * 6}  {'─' * 12}  {'─' * 12}  {'─' * 40}")
    for key, flaky, total, rate, last_date in ranked[:15]:
        print(f"{rate:5.0%}   {flaky:>4}/{total:<6}  {last_date:<12}  {key}")
    print()


def record_flake_history(run_data: dict) -> None:
    """Persist bounded retry metrics without errors, logs, or test contents."""
    run_id = str(run_data.get("run_id") or "")
    if not run_id:
        return
    history_path = RESULTS_DIR / "flaky-history.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.is_file() else {}
    except (json.JSONDecodeError, OSError):
        history = {}
    recorded_run_ids = set(history.get("recorded_run_ids") or [])
    if run_id in recorded_run_ids:
        return

    tests = history.setdefault("tests", {})
    for suite_name, suite in (run_data.get("suites") or {}).items():
        if suite_name != "playwright" or not isinstance(suite, dict):
            continue
        for test in suite.get("tests") or []:
            if not isinstance(test, dict):
                continue
            name = str(test.get("file") or test.get("name") or "")
            if not name:
                continue
            entry = tests.setdefault(f"playwright::{name}", {"total_runs": 0, "flaky_count": 0})
            entry["total_runs"] = int(entry.get("total_runs", 0)) + 1
            entry["last_run_id"] = run_id
            entry["last_status"] = str(test.get("status") or "unknown")
            attempt_statuses = [str(status) for status in test.get("attempt_statuses") or []]
            if attempt_statuses:
                entry["last_attempt_statuses"] = attempt_statuses
            if test.get("flaky"):
                entry["flaky_count"] = int(entry.get("flaky_count", 0)) + 1
                entry["last_flaky_date"] = datetime.now(timezone.utc).date().isoformat()

    history["schema_version"] = 1
    history["recorded_run_ids"] = sorted([*recorded_run_ids, run_id])[-500:]
    _safe_write_json(history_path, history)


def _load_tests_control_module():
    """Load scripts/tests.py lazily so this runner can reuse its control plane."""
    tests_script = PROJECT_ROOT / "scripts" / "tests.py"
    if not tests_script.is_file():
        raise RuntimeError("scripts/tests.py is missing")
    spec = importlib.util.spec_from_file_location("openmates_tests_control", tests_script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scripts/tests.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _record_unified_test_state(
    data: dict,
    *,
    source: str = "scripts_tests",
    workflow: str = "",
) -> None:
    """Update scripts/tests.py state files without making this runner depend on it."""
    try:
        module = _load_tests_control_module()
    except RuntimeError:
        return
    module.record_run_result(data, source=source, workflow=workflow)


def _test_control_source_for_flags(flags: dict) -> tuple[str, str]:
    """Return the canonical control-plane source for one runner result."""
    if flags.get("daily"):
        return "daily_runner", "daily"
    return "scripts_tests", ""


def _generate_e2e_gift_card_code() -> str:
    """Return a short, human-enterable gift-card code matching production rules."""
    return "-".join(
        "".join(secrets.choice(E2E_GIFT_CARD_CODE_CHARSET) for _ in range(4))
        for _ in range(3)
    )


def _seed_e2e_gift_card(spec: str) -> SeededGiftCard:
    """Create a disposable dev gift card in Directus for a real redemption spec."""
    module = _load_tests_control_module()
    store = module.DirectusTestControlStore()
    last_error: Optional[Exception] = None
    for _attempt in range(E2E_GIFT_CARD_SEED_RETRIES):
        code = _generate_e2e_gift_card_code()
        notes = (
            f"E2E disposable gift-card redemption fixture for {spec}; "
            f"seeded {datetime.now(timezone.utc).isoformat()} by scripts/run_tests.py."
        )
        try:
            created = store._request(
                "POST",
                "/items/gift_cards",
                data={
                    "code": code,
                    "credits_value": E2E_GIFT_CARD_REDEMPTION_CREDITS,
                    "notes": notes,
                },
            )
        except RuntimeError as exc:
            last_error = exc
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                continue
            raise RuntimeError(f"Could not seed dev gift card for {spec}: {exc}") from exc

        if not isinstance(created, dict) or not created.get("id"):
            raise RuntimeError(f"Directus returned an invalid gift-card seed response for {spec}")

        card = SeededGiftCard(
            spec=spec,
            code=code,
            directus_id=str(created["id"]),
            credits_value=E2E_GIFT_CARD_REDEMPTION_CREDITS,
        )
        _log(f"Seeded disposable dev gift card for {spec} (Directus ID {card.directus_id})")
        return card

    raise RuntimeError(f"Could not seed a unique dev gift card for {spec}: {last_error}")


def _cleanup_e2e_gift_cards(cards: dict[str, SeededGiftCard]) -> None:
    """Best-effort removal of unredeemed disposable dev gift cards."""
    if not cards:
        return
    try:
        module = _load_tests_control_module()
        store = module.DirectusTestControlStore()
    except RuntimeError as exc:
        _log(f"Disposable gift-card cleanup skipped: {exc}", "WARN")
        return

    for card in cards.values():
        try:
            store._request("DELETE", f"/items/gift_cards/{urllib.parse.quote(card.directus_id)}")
            _log(f"Deleted unredeemed disposable gift card for {card.spec} (Directus ID {card.directus_id})")
        except RuntimeError as exc:
            detail = str(exc)
            if "404" in detail or "not found" in detail.lower():
                continue
            _log(f"Disposable gift-card cleanup failed for {card.spec}: {detail[:200]}", "WARN")


def _seed_playwright_fixtures_for_specs(
    specs: list[str],
    environment: str,
) -> dict[str, SeededGiftCard]:
    """Seed per-run fixtures that must exist before a GitHub-hosted spec starts."""
    if environment != "development":
        return {}
    if E2E_GIFT_CARD_REDEMPTION_SPEC not in specs:
        return {}
    return {
        E2E_GIFT_CARD_REDEMPTION_SPEC: _seed_e2e_gift_card(E2E_GIFT_CARD_REDEMPTION_SPEC),
    }


def _log(msg: str, level: str = "INFO") -> None:
    """Print a timestamped log line."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    prefix = {"INFO": "  ", "WARN": "⚠ ", "ERROR": "✗ ", "OK": "✓ "}.get(level, "  ")
    print(f"[{ts}] {prefix}{msg}", flush=True)


def _git_info() -> tuple[str, str]:
    """Return (short_sha, branch)."""
    subject_commit = os.environ.get("OPENMATES_TEST_SUBJECT_COMMIT", "").strip()
    if subject_commit:
        return subject_commit[:9], "dev"

    sha = "unknown"
    branch = "unknown"
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        branch = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        pass
    return sha, branch


def _daily_git_info(current_git_sha: str, current_git_branch: str) -> tuple[str, str]:
    """Use the latest remote dev commit for delayed cron runs."""
    if os.environ.get("OPENMATES_TEST_SUBJECT_COMMIT", "").strip():
        return current_git_sha, current_git_branch

    remote_ref = f"origin/{GH_BRANCH}"
    try:
        subprocess.run(
            [
                "git", "-C", str(PROJECT_ROOT), "fetch", "--quiet", "origin",
                f"+{GH_BRANCH}:refs/remotes/{remote_ref}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        remote_sha = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", remote_ref],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception as exc:
        _log(f"Could not refresh {remote_ref} for daily subject commit: {exc}", "WARN")
        return current_git_sha, current_git_branch

    if not remote_sha:
        return current_git_sha, current_git_branch

    remote_short = remote_sha[:9]
    if current_git_sha != remote_short:
        _log(
            f"Daily run using {remote_ref} {remote_short} instead of local {current_git_sha}@{current_git_branch}",
            "WARN",
        )
    return remote_short, GH_BRANCH


def _full_git_sha(git_ref: str) -> str:
    """Resolve a display ref to the full commit SHA required by actions/checkout."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", git_ref],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return git_ref


@dataclass(frozen=True)
class DailyCacheBackfillPaths:
    """Explicit host paths shared by preflight, recording, replay, and promotion."""

    candidate_root: Path
    runtime_cache_root: Path
    claim_base: Path
    claim_root: Path
    source_root: Path


class DailyRunInterrupted(BaseException):
    """Raised from a terminal signal so daily finalization can still notify."""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        self.signal_name = signal.Signals(signum).name
        super().__init__(f"daily runner interrupted by {self.signal_name}")


@contextmanager
def _daily_terminal_signal_handlers(enabled: bool):
    """Convert terminal signals into a normal daily failure-finalization path."""

    if not enabled or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}

    def interrupt(signum: int, _frame: object) -> None:
        raise DailyRunInterrupted(signum)

    try:
        for signum in previous:
            signal.signal(signum, interrupt)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _resolve_daily_cache_backfill_paths(run_date: date) -> DailyCacheBackfillPaths:
    """Resolve one checkout-independent path set and reject inferred fallbacks."""

    configured = {name: os.getenv(name, "").strip() for name in DAILY_AI_BACKFILL_PATH_ENV_VARS}
    missing = [name for name, value in configured.items() if not value]
    if missing:
        raise daily_ai_cache_backfill.BackfillValidationError(
            "daily cache backfill requires explicit paths: " + ", ".join(missing)
        )
    paths = {name: Path(value).expanduser() for name, value in configured.items()}
    relative = [name for name, path in paths.items() if not path.is_absolute()]
    if relative:
        raise daily_ai_cache_backfill.BackfillValidationError(
            "daily cache backfill paths must be absolute: " + ", ".join(relative)
        )
    resolved = {name: path.resolve() for name, path in paths.items()}
    candidate_root = resolved["DAILY_AI_CANDIDATE_ROOT"]
    runtime_cache_root = resolved["DAILY_AI_RUNTIME_CACHE_ROOT"]
    claim_base = resolved["DAILY_AI_CLAIM_ROOT"]
    source_root = resolved["DAILY_AI_SOURCE_ROOT"]
    if candidate_root == runtime_cache_root:
        raise daily_ai_cache_backfill.BackfillValidationError("candidate and runtime cache roots must differ")
    if claim_base == candidate_root or candidate_root in claim_base.parents:
        raise daily_ai_cache_backfill.BackfillValidationError("claim root must stay outside the candidate mount")
    return DailyCacheBackfillPaths(
        candidate_root=candidate_root,
        runtime_cache_root=runtime_cache_root,
        claim_base=claim_base,
        claim_root=claim_base / f"daily-{run_date.strftime('%Y%m%d')}",
        source_root=source_root,
    )


def _probe_writable_directory(path: Path, label: str) -> None:
    """Prove host write access without creating a claim or retaining content."""

    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".backfill-preflight-{uuid4().hex}"
    try:
        with probe.open("x", encoding="utf-8") as handle:
            handle.write("{}\n")
    except OSError as exc:
        raise daily_ai_cache_backfill.BackfillValidationError(f"{label} is not host-writable") from exc
    finally:
        probe.unlink(missing_ok=True)


def _source_root_commit(source_root: Path) -> str:
    """Resolve the source checkout's deployed dev commit for promotion pinning."""

    try:
        fetch = subprocess.run(
            ["git", "fetch", "origin", "dev:refs/remotes/origin/dev"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if fetch.returncode != 0:
            return ""
        return subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "origin/dev"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _daily_cache_backfill_preflight(git_ref: str, run_date: date) -> dict[str, object]:
    """Validate the zero-paid control path without claiming or dispatching."""

    try:
        paths = _resolve_daily_cache_backfill_paths(run_date)
        if not paths.candidate_root.is_dir():
            raise daily_ai_cache_backfill.BackfillValidationError("candidate cache root is missing")
        if not os.access(paths.candidate_root, os.R_OK | os.X_OK):
            raise daily_ai_cache_backfill.BackfillValidationError("candidate cache root is not readable")
        _probe_writable_directory(paths.runtime_cache_root, "runtime cache root")
        _probe_writable_directory(paths.claim_base, "claim root")
        if not (paths.source_root / "scripts" / "sessions.py").is_file():
            raise daily_ai_cache_backfill.BackfillValidationError("source root lacks scripts/sessions.py")
        full_sha = _full_git_sha(git_ref)
        if not re.fullmatch(r"[a-f0-9]{40}", full_sha):
            raise daily_ai_cache_backfill.BackfillValidationError("deployed commit did not resolve to a full SHA")
        if _source_root_commit(paths.source_root) != full_sha:
            raise daily_ai_cache_backfill.BackfillValidationError("source root is not pinned to the deployed dev commit")
        claim_phase = "none"
        claim_path = paths.claim_root / "backfill-claim.json"
        if claim_path.is_file():
            try:
                claim = json.loads(claim_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise daily_ai_cache_backfill.BackfillValidationError("daily claim is unreadable") from exc
            claim_phase = str(claim.get("phase") or "invalid")
        return {
            "status": "passed",
            "full_commit_sha": full_sha,
            "claim_phase": claim_phase,
            "candidate_dispatches": 0,
            "paid_provider_calls": 0,
        }
    except daily_ai_cache_backfill.BackfillValidationError as exc:
        return {
            "status": "failed",
            "detail": str(exc),
            "candidate_dispatches": 0,
            "paid_provider_calls": 0,
        }


def _cache_backfill_suite(result: dict[str, object]) -> SuiteResult:
    """Represent backfill as a real suite so failures affect daily status."""

    status = str(result.get("status") or "failed")
    test_status = (
        "passed"
        if status in {"promoted", "runtime_promoted"}
        else "skipped"
        if status == "skipped"
        else "failed"
    )
    test: dict[str, object] = {
        "name": str(result.get("spec") or "daily-cache-backfill"),
        "file": "scripts/daily_ai_cache_backfill.py",
        "status": test_status,
        "duration_seconds": 0,
    }
    if test_status == "failed":
        test["error"] = "Cache backfill failed; inspect the content-free run receipt"
    return SuiteResult(status=test_status, tests=[test], duration_seconds=0)


def _read_env_file() -> dict[str, str]:
    """Read .env from the shared control-plane checkout."""
    env_path = CONTROL_PLANE_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if not env_path.is_file():
        return env_vars
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip surrounding quotes
                value = value.strip().strip("'\"")
                env_vars[key.strip()] = value
    return env_vars


def _get_env(key: str, dot_env: Optional[dict] = None, default: str = "") -> str:
    """Get env var from environment or .env fallback."""
    val = os.environ.get(key, "")
    if not val and dot_env:
        val = dot_env.get(key, "")
    return val or default


def _docker_container_env(container: str, key: str) -> tuple[Optional[str], Optional[str]]:
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "printenv", key],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return None, "docker CLI is unavailable"
    except subprocess.TimeoutExpired:
        return None, f"docker exec {container} printenv {key} timed out"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"{key} is unset").strip()
        return None, detail[:200]
    return proc.stdout.strip(), None


def _is_missing_docker_container_error(error: str) -> bool:
    normalized = error.lower()
    return "no such container" in normalized or "no container" in normalized


def _development_backend_live_mock_preflight_error() -> Optional[str]:
    if os.getenv("OPENMATES_E2E_BACKEND_MOCK_PREFLIGHT", "1") in BACKEND_LIVE_MOCK_PREFLIGHT_DISABLED_VALUES:
        _log("Backend live-mock preflight disabled via OPENMATES_E2E_BACKEND_MOCK_PREFLIGHT", "WARN")
        return None

    problems: list[str] = []
    for container in BACKEND_LIVE_MOCK_PREFLIGHT_CONTAINERS:
        server_environment, server_error = _docker_container_env(container, "SERVER_ENVIRONMENT")
        if server_error and _is_missing_docker_container_error(server_error):
            if container in BACKEND_LIVE_MOCK_CONDITIONAL_CONTAINERS:
                _log(
                    f"Backend live-mock preflight skipped absent conditional worker {container}; "
                    "specs that require its queue may still fail.",
                    "WARN",
                )
                continue
            problems.append(f"{container}: container is not running ({server_error})")
            continue

        values: dict[str, str] = {}
        read_errors: set[str] = set()
        if server_error:
            problems.append(f"{container}: cannot read SERVER_ENVIRONMENT ({server_error})")
            read_errors.add("SERVER_ENVIRONMENT")
        else:
            values["SERVER_ENVIRONMENT"] = server_environment or ""

        for key in ("SERVER_ENVIRONMENT", "MOCK_EXTERNAL_APIS"):
            if key == "SERVER_ENVIRONMENT":
                continue
            value, error = _docker_container_env(container, key)
            if error:
                problems.append(f"{container}: cannot read {key} ({error})")
                read_errors.add(key)
                continue
            values[key] = value or ""

        server_env = values.get("SERVER_ENVIRONMENT", "").strip().lower()
        mock_external_apis = values.get("MOCK_EXTERNAL_APIS", "").strip()
        if "SERVER_ENVIRONMENT" not in read_errors and server_env in {"", "production", "prod"}:
            problems.append(f"{container}: SERVER_ENVIRONMENT={values.get('SERVER_ENVIRONMENT') or '<unset>'}")
        if "MOCK_EXTERNAL_APIS" not in read_errors and mock_external_apis != "true":
            problems.append(f"{container}: MOCK_EXTERNAL_APIS={mock_external_apis or '<unset>'}")

    if not problems:
        return None

    joined = "; ".join(problems)
    return (
        "Backend live-mock preflight failed. Playwright was about to dispatch with "
        "cached live mocks enabled, but dev backend containers would ignore live-mock markers: "
        f"{joined}. Set MOCK_EXTERNAL_APIS=true, restart the affected dev services, or run "
        "with --no-mocks for an intentional real-provider run."
    )


def _vercel_project_config() -> tuple[str, str]:
    """Return (team_id, project_id) for the web app Vercel project."""
    project_json = CONTROL_PLANE_ROOT / "frontend" / "apps" / "web_app" / ".vercel" / "project.json"
    if not project_json.is_file():
        raise RuntimeError(f"Vercel project config not found: {project_json}")
    try:
        data = json.loads(project_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read Vercel project config: {exc}") from exc

    team_id = str(data.get("orgId", ""))
    project_id = str(data.get("projectId", ""))
    if not team_id or not project_id:
        raise RuntimeError("Vercel project config is missing orgId or projectId")
    return team_id, project_id


def _vercel_api_get(path: str, token: str, params: dict[str, str | int]) -> dict:
    """GET a Vercel API endpoint using stdlib urllib."""
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{VERCEL_API}{path}?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _vercel_api_post(
    path: str,
    token: str,
    params: dict[str, str | int],
    payload: dict,
) -> dict:
    """POST JSON to the Vercel REST API."""
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{VERCEL_API}{path}?{query}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _redeploy_vercel_deployment(token: str, team_id: str, deployment_id: str) -> dict:
    """Request one fresh build for a canceled development deployment."""
    return _vercel_api_post(
        "/v13/deployments",
        token,
        {"teamId": team_id, "forceNew": 1},
        {"deploymentId": deployment_id},
    )


def _latest_vercel_deployment_for_sha(
    token: str,
    team_id: str,
    project_id: str,
    git_sha: str,
) -> Optional[dict]:
    """Return the newest dev deployment for the current git SHA, if Vercel has seen it."""
    data = _vercel_api_get(
        "/v6/deployments",
        token,
        {
            "teamId": team_id,
            "projectId": project_id,
            "limit": 20,
        },
    )
    for deployment in data.get("deployments", []):
        meta = deployment.get("meta", {})
        if meta.get("githubCommitRef") != GH_BRANCH:
            continue
        deployed_sha = str(meta.get("githubCommitSha", ""))
        if deployed_sha.startswith(git_sha) or git_sha.startswith(deployed_sha):
            return deployment
    return None


def _deployment_matches_commit(deployment: dict, git_sha: str, *, exact: bool) -> bool:
    """Return whether a deployment can prove the requested commit mode."""
    if not exact:
        state = str(deployment.get("state", deployment.get("readyState", ""))).upper()
        return state == "READY"
    deployed_sha = str((deployment.get("meta") or {}).get("githubCommitSha", ""))
    requested = str(git_sha or "")
    return bool(requested and deployed_sha and (deployed_sha.startswith(requested) or requested.startswith(deployed_sha)))


def _requested_commit_is_stale_dev_ancestor(git_sha: str) -> bool:
    """Return true only when Git proves the requested commit predates origin/dev."""
    try:
        requested = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", git_sha],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        current_dev = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "origin/dev"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not requested or not current_dev or requested == current_dev:
            return False
        return subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "merge-base", "--is-ancestor", requested, current_dev],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _wait_for_vercel_deployment(git_sha: str, dot_env: dict[str, str]) -> tuple[bool, str]:
    """Block Playwright dispatch until Vercel has deployed the current dev commit."""
    if _get_env("OPENMATES_SKIP_VERCEL_WAIT", dot_env).lower() == "true":
        _log("OPENMATES_SKIP_VERCEL_WAIT=true — skipping Vercel wait", "WARN")
        return True, ""

    token = _get_env("VERCEL_TOKEN", dot_env)
    if not token:
        reason = "VERCEL_TOKEN is required before running development Playwright specs"
        _log(reason, "ERROR")
        return False, reason

    try:
        team_id, project_id = _vercel_project_config()
    except RuntimeError as exc:
        reason = str(exc)
        _log(reason, "ERROR")
        return False, reason

    timeout = int(_get_env("OPENMATES_VERCEL_WAIT_TIMEOUT", dot_env, str(VERCEL_WAIT_TIMEOUT)))
    poll_interval = int(
        _get_env("OPENMATES_VERCEL_WAIT_POLL_INTERVAL", dot_env, str(VERCEL_WAIT_POLL_INTERVAL))
    )
    deadline = time.time() + timeout
    last_status = "not found"
    redeploy_attempted = False
    canceled_deployment_id: Optional[str] = None

    _log(f"Waiting for Vercel dev deployment for commit {git_sha} before Playwright specs...")
    while time.time() < deadline:
        try:
            deployment = _latest_vercel_deployment_for_sha(token, team_id, project_id, git_sha)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_status = f"Vercel API error: {exc}"
            _log(last_status, "WARN")
            time.sleep(poll_interval)
            continue

        if deployment is None:
            if last_status == "not found" and _requested_commit_is_stale_dev_ancestor(git_sha):
                reason = (
                    f"No Vercel deployment exists for stale dev ancestor {git_sha}. "
                    "Verify the relevant files are unchanged, then rerun against current origin/dev; "
                    "waiting cannot create a deployment for an older commit."
                )
                _log(reason, "ERROR")
                return False, reason
            if last_status != "not found":
                _log("Vercel deployment not visible yet")
            last_status = "not found"
            time.sleep(poll_interval)
            continue

        deploy_id = deployment.get("uid", deployment.get("id", "unknown"))
        state = str(deployment.get("state", deployment.get("readyState", "unknown"))).upper()
        if state != last_status:
            _log(f"Vercel deployment {deploy_id}: {state}")
            last_status = state

        if state == "READY":
            _log("Vercel deployment is Ready — dispatching Playwright specs", "OK")
            return True, ""
        error_message = str(deployment.get("errorMessage") or "").strip()
        detail = f": {error_message}" if error_message else ""
        if state == "CANCELED":
            if redeploy_attempted:
                # Vercel can briefly return the old canceled deployment while
                # the replacement is being created. Wait for a different result.
                if str(deploy_id) == canceled_deployment_id:
                    time.sleep(poll_interval)
                    continue
                reason = f"Vercel deployment {deploy_id} is CANCELED after one retry{detail}"
                _log(reason, "ERROR")
                return False, reason
            try:
                _redeploy_vercel_deployment(token, team_id, str(deploy_id))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                reason = f"Vercel deployment {deploy_id} is CANCELED and retry failed: {exc}{detail}"
                _log(reason, "ERROR")
                return False, reason
            redeploy_attempted = True
            canceled_deployment_id = str(deploy_id)
            last_status = "redeploy requested"
            _log(f"Vercel deployment {deploy_id} is CANCELED; requested one retry", "WARN")
        elif state == "ERROR":
            reason = f"Vercel deployment {deploy_id} is ERROR{detail}"
            _log(reason, "ERROR")
            return False, reason

        time.sleep(poll_interval)

    reason = f"Timed out after {timeout}s waiting for Vercel deployment for {git_sha} (last status: {last_status})"
    _log(reason, "ERROR")
    return False, reason


def _not_started_playwright_specs(specs: list[str], reason: str) -> list[dict]:
    """Preserve every undispatched spec in the daily result instead of hiding it."""
    return [
        {
            "name": spec,
            "status": "not_started",
            "duration_seconds": 0,
            "error": reason,
        }
        for spec in specs
    ]


def _validate_requested_playwright_spec(spec_name: str, deployed_git_ref: str | None = None) -> str:
    """Return a dispatch-blocking error for specs absent from the tested source."""
    if not spec_name.endswith(".spec.ts"):
        return f"Playwright specs must end with .spec.ts: {spec_name}"

    spec_path = (SPEC_DIR / spec_name).resolve()
    try:
        spec_path.relative_to(SPEC_DIR.resolve())
    except ValueError:
        return f"Spec path escapes Playwright spec directory: {spec_name}"

    if not deployed_git_ref and not spec_path.is_file():
        try:
            display_path = str(spec_path.relative_to(PROJECT_ROOT))
        except ValueError:
            display_path = str(spec_path)
        return f"Spec file not found: {display_path}"

    try:
        rel_path = str(spec_path.relative_to(PROJECT_ROOT))
    except ValueError:
        return f"Spec file is outside the repository: {spec_path}"

    # Exact/deployed-commit runs execute in GitHub Actions from this ref. The
    # immutable control runtime may legitimately predate a newly deployed spec,
    # so its working tree must not override the requested commit's tree.
    if deployed_git_ref:
        deployed = subprocess.run(
            ["git", "cat-file", "-e", f"{deployed_git_ref}:{rel_path}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if deployed.returncode == 0:
            return ""
        return f"Spec file not found at deployed commit {deployed_git_ref}: {rel_path}"

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel_path],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if tracked.returncode != 0:
        return (
            f"Spec file is untracked and cannot run in GitHub Actions until deployed: {rel_path}. "
            "Track it in the active session and deploy with scripts/sessions.py deploy first."
        )

    return ""


def _read_playwright_spec_source(spec_name: str, deployed_git_ref: str | None = None) -> str:
    """Return the selected committed spec source, or empty text to fail closed."""
    spec_path = (SPEC_DIR / spec_name).resolve()
    try:
        rel_path = spec_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return ""

    if deployed_git_ref:
        committed = subprocess.run(
            ["git", "show", f"{deployed_git_ref}:{rel_path}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return committed.stdout if committed.returncode == 0 else ""

    try:
        return spec_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _playwright_spec_requires_account(spec_name: str, deployed_git_ref: str | None = None) -> bool:
    """Return False only for the exact committed isolated-component opt-out marker."""
    source = _read_playwright_spec_source(spec_name, deployed_git_ref)
    return PLAYWRIGHT_ACCOUNT_NOT_REQUIRED_MARKER not in source.splitlines()


def _playwright_account_requirements_for_specs(
    specs: list[str],
    deployed_git_ref: str | None = None,
) -> dict[str, bool]:
    """Map specs to the fail-closed account requirement used for dispatch."""
    return {
        spec: _playwright_spec_requires_account(spec, deployed_git_ref)
        for spec in specs
    }


def _safe_write_json(path: Path, data: dict) -> None:
    """Write JSON, removing existing file first to avoid permission issues."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# Discord multipart constants — used by _send_summary_to_discord when
# screenshots are attached. Discord webhooks accept up to 10 files; the
# free-tier per-file cap is 25 MB but each guild has a 25 MB combined cap
# unless boosted. Be conservative: cap to 5 files at 2 MB each.
DISCORD_MAX_ATTACHMENTS = 5
DISCORD_MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
DISCORD_DESCRIPTION_MAX_CHARS = 4000
DISCORD_MAX_EMBEDS = 10
DISCORD_EMBED_TOTAL_MAX_CHARS = 6000
DISCORD_MIN_DETAIL_DESCRIPTION_CHARS = 300

# ---------------------------------------------------------------------------
# Discord per-test deduplication state (OPE-349 follow-up)
# ---------------------------------------------------------------------------
#
# Architecture:
# - Per hourly mode (`hourly-dev`, `hourly-prod`) we maintain a small JSON
#   state file under that mode's archive dir. The file maps a stable
#   per-test key to:
#       { message_id, error_hash, first_seen, last_seen, count, summary_hash,
#         summary_message_id }
# - On each tick:
#       1. Compute the current set of {test_key: error_hash} from this run.
#       2. For each currently-failing test:
#            * If state has the same key + same error_hash → repeat. PATCH the
#              existing message in place with an updated counter footer.
#            * If state has the key but a DIFFERENT error_hash → the failure
#              mode changed; treat as new. POST a fresh message and replace
#              the state entry.
#            * If state has no entry → first sight. POST and save.
#       3. Any state entries whose key is NOT in the current failure set are
#          recoveries — post a single "✅ recovered" line and drop the entry.
# - The lightweight summary embed is also dedup'd: state stores a hash of
#   the failure set + the summary message id. On a repeat tick where the
#   failure set is unchanged AND there are no recoveries, we skip the
#   summary post entirely so we don't spam the channel.
#
# State file retention: 7 days after `last_seen` so dead entries (e.g. tests
# that were renamed or removed) eventually get garbage-collected.

DISCORD_STATE_RETENTION_DAYS = 7
DISCORD_STATE_FILE_NAME = "discord-state.json"


def _compute_test_key(suite_name: str, test: dict) -> str:
    """Stable identity for a single test across runs.

    Uses suite + the most descriptive name field available. We intentionally
    do NOT include error or status — those change between repeats.
    """
    name = test.get("file") or test.get("name") or test.get("title") or "?"
    return f"{suite_name}::{name}"


def _normalize_error(error: str) -> str:
    """Normalise an error string for hashing.

    Strips ANSI codes, timestamps, run IDs, file paths and excess
    whitespace so two runs of the same underlying failure produce the
    same hash even when the surrounding noise drifts.
    """
    if not error:
        return ""
    # Strip ANSI escape codes
    s = re.sub(r"\x1b\[[0-9;]*m", "", error)
    # Strip ISO timestamps (2026-04-08T12:34:56[.789][Z])
    s = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?", "<TS>", s)
    # Strip run IDs / numeric ids that appear inline
    s = re.sub(r"\b\d{8,}\b", "<ID>", s)
    # Strip absolute paths so /home/runner/... vs /tmp/... don't differ.
    # Allow optional :line[:col] suffix so we collapse "foo.ts:42:7" too.
    s = re.sub(r"/[\w\-./]+\.(ts|js|py|spec\.ts)(:\d+)?(:\d+)?", "<PATH>", s)
    # Strip remaining standalone line:col fragments that appeared without
    # a leading slash (Playwright sometimes prints `at line 42:7`).
    s = re.sub(r":\d+(:\d+)?\b", ":<LN>", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _compute_error_hash(test: dict) -> str:
    """SHA-256 of the normalised error so we can detect 'same test, same error'.

    Considers both the structured Playwright error message and the plain
    `error` field for backend / non-Playwright tests.
    """
    pw = test.get("playwright_errors") or []
    parts: list[str] = []
    if pw:
        msg = (pw[0].get("message") or "").strip()
        if msg:
            parts.append(msg)
    err = (test.get("error") or "").strip()
    if err and err not in parts:
        parts.append(err)
    if not parts:
        return ""
    normalized = _normalize_error("\n".join(parts))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _compute_failure_set_hash(state_keys_now: dict[str, str]) -> str:
    """Hash of the current {test_key: error_hash} mapping.

    Used to decide whether to skip the lightweight summary embed: if this
    matches the previously stored hash AND there are no recoveries, the
    summary would just be a duplicate of what's already in the channel.
    """
    if not state_keys_now:
        return ""
    encoded = json.dumps(state_keys_now, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _load_discord_state(state_file: Path) -> dict:
    """Load the per-mode Discord dedup state.

    Returns an empty skeleton when the file is missing or unreadable so
    callers can always rely on the structure being present.
    """
    if not state_file.is_file():
        return {"tests": {}, "summary": {}}
    try:
        with open(state_file) as f:
            data = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {"tests": {}, "summary": {}}
    if not isinstance(data, dict):
        return {"tests": {}, "summary": {}}
    data.setdefault("tests", {})
    data.setdefault("summary", {})
    return data


def _save_discord_state(state_file: Path, state: dict) -> None:
    """Atomically write the state file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(state_file.suffix + ".tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        tmp.replace(state_file)
    except OSError as e:
        _log(f"Failed to write discord state to {state_file}: {e}", "WARN")


def _prune_discord_state(state: dict, retention_days: int = DISCORD_STATE_RETENTION_DAYS) -> dict:
    """Drop entries whose `last_seen` is older than the retention window.

    Stops state files from accumulating ghost entries for tests that were
    renamed, removed, or stayed green long enough that their recovery
    message has already been posted.
    """
    cutoff = time.time() - retention_days * 86400
    tests = state.get("tests", {}) or {}
    keep: dict = {}
    for k, entry in tests.items():
        last_seen = entry.get("last_seen", "")
        try:
            ts = datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            ).timestamp()
        except (ValueError, TypeError):
            ts = 0
        if ts >= cutoff:
            keep[k] = entry
    state["tests"] = keep
    return state


def _build_multipart_body(
    payload_json: dict,
    files: list[tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Build a multipart/form-data body for a Discord webhook with attachments.

    Discord requires the JSON payload under the field name `payload_json`
    and each attached file under `files[N]` with a `filename`. Returns
    `(body_bytes, content_type)` ready to feed into urllib.request.

    Stdlib-only because run_tests.py intentionally avoids extra deps so it
    can run on a vanilla Python install on the dev server cron.

    Args:
        payload_json: The JSON-serialisable Discord webhook payload.
        files: List of `(field_name, content_bytes, filename)` tuples. Use
               `field_name = "files[N]"` to follow Discord's convention.
    """
    # A boundary is any token that doesn't appear in the body. uuid-like is fine.
    boundary = f"----openmates-{int(time.time())}-{os.getpid()}"
    crlf = b"\r\n"
    parts: list[bytes] = []

    # payload_json field
    parts.append(f"--{boundary}".encode())
    parts.append(b'Content-Disposition: form-data; name="payload_json"')
    parts.append(b"Content-Type: application/json")
    parts.append(b"")
    parts.append(json.dumps(payload_json).encode("utf-8"))

    # File fields
    for field_name, content_bytes, filename in files:
        parts.append(f"--{boundary}".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{filename}"'.encode()
        )
        # Sniff content-type from extension (PNG for *.png, default octet-stream).
        ct = "image/png" if filename.lower().endswith(".png") else (
            "image/webp" if filename.lower().endswith(".webp") else (
                "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg"))
                else "application/octet-stream"
            )
        )
        parts.append(f"Content-Type: {ct}".encode())
        parts.append(b"")
        parts.append(content_bytes)

    parts.append(f"--{boundary}--".encode())
    parts.append(b"")

    body = crlf.join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


# ---------------------------------------------------------------------------
# GitHubActionsClient
# ---------------------------------------------------------------------------

def _matching_dispatched_run_id(runs: list[dict], dispatch_token: str) -> Optional[int]:
    """Return the run ID whose workflow title contains the dispatch token."""
    for run in runs:
        display_title = str(run.get("displayTitle") or "")
        if dispatch_token not in display_title:
            continue
        try:
            return int(run["databaseId"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _configured_preflight_accounts(results: list[SpecResult]) -> list[dict]:
    """Build a de-duplicated credit-guard payload from preflight results."""
    accounts_by_email: dict[str, dict] = {}
    for result in results:
        if not result.account_email:
            continue
        normalized_email = result.account_email.strip().lower()
        account = accounts_by_email.setdefault(
            normalized_email,
            {"slot": result.account, "email": result.account_email, "slots": []},
        )
        if result.account and result.account not in account["slots"]:
            account["slots"].append(result.account)

    payload: list[dict] = []
    for account in sorted(
        accounts_by_email.values(),
        key=lambda item: min(item["slots"] or [item.get("slot") or 999]),
    ):
        slots = account.pop("slots")
        if slots:
            account["slot"] = min(slots)
        payload.append(account)
    return payload


class GitHubActionsClient:
    """Wraps the `gh` CLI for workflow dispatch and status polling."""

    def __init__(self, git_sha: Optional[str] = None) -> None:
        self.last_dispatch_error: Optional[str] = None
        self.git_sha = git_sha
        self.dispatch_circuit = DispatchCircuit()
        self._check_gh()

    def refresh_dispatch_budget(self, required_requests: int) -> dict[str, object]:
        """Open the circuit before bulk dispatch when GitHub core budget is insufficient."""
        rc = subprocess.run(
            ["gh", "api", "rate_limit", "--jq", ".resources.core"],
            capture_output=True,
            text=True,
        )
        if rc.returncode != 0:
            self.dispatch_circuit.open_budget_unknown()
            self.last_dispatch_error = "GitHub Actions request budget could not be verified"
            return self.dispatch_circuit.snapshot()
        try:
            budget = json.loads(rc.stdout)
            remaining = int(budget.get("remaining"))
            reset_at = int(budget.get("reset"))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            self.dispatch_circuit.open_budget_unknown()
            self.last_dispatch_error = "GitHub Actions request budget metadata was invalid"
            return self.dispatch_circuit.snapshot()
        self.dispatch_circuit.configure_budget(remaining, reset_at)
        if not self.dispatch_circuit.reserve_requests(required_requests):
            self.last_dispatch_error = "GitHub Actions request budget is insufficient for this dispatch phase"
        return {**self.dispatch_circuit.snapshot(), "remaining": remaining}

    def _check_gh(self) -> None:
        """Verify gh CLI is available and authenticated."""
        if not shutil.which("gh"):
            _log("gh CLI not found. Install: https://cli.github.com/", "ERROR")
            sys.exit(1)
        rc = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True,
        )
        if rc.returncode != 0:
            _log("gh not authenticated. Run: gh auth login", "ERROR")
            sys.exit(1)

    def dispatch_spec(
        self,
        spec: str,
        account: int,
        use_mocks: bool = True,
        record_live_fixtures: bool = False,
        create_account_slot: Optional[int] = None,
        allow_credential_updates: bool = True,
        seeded_gift_card_code: Optional[str] = None,
        proof_video_profile: str = "",
        daily_ai_run_id: str = "",
        requires_account: bool = True,
    ) -> Optional[int]:
        """
        Dispatch a single spec workflow run.
        Returns the run ID or None on failure.
        """
        dispatch_token = self.request_spec_dispatch(
            spec,
            account,
            use_mocks,
            record_live_fixtures,
            create_account_slot=create_account_slot,
            allow_credential_updates=allow_credential_updates,
            seeded_gift_card_code=seeded_gift_card_code,
            proof_video_profile=proof_video_profile,
            daily_ai_run_id=daily_ai_run_id,
            requires_account=requires_account,
        )
        if dispatch_token is None:
            return None
        return self.resolve_dispatch_tokens({dispatch_token: spec}).get(dispatch_token)

    def request_spec_dispatch(
        self,
        spec: str,
        account: int,
        use_mocks: bool = True,
        record_live_fixtures: bool = False,
        create_account_slot: Optional[int] = None,
        allow_credential_updates: bool = True,
        seeded_gift_card_code: Optional[str] = None,
        proof_video_profile: str = "",
        daily_ai_run_id: str = "",
        requires_account: bool = True,
    ) -> Optional[str]:
        """Submit a workflow without serially waiting for GitHub's run ID."""
        self.last_dispatch_error = None
        if self.dispatch_circuit.is_open:
            self.last_dispatch_error = "GitHub Actions dispatch circuit is open"
            return None
        dispatch_token = f"rt-{os.getpid()}-{time.time_ns()}-{account}"

        # playwright-spec.yml: lightweight 1-job workflow per spec
        command = [
            "gh", "workflow", "run", WORKFLOW_NAME,
            "--repo", GH_REPO,
            "--ref", GH_BRANCH,
            "-f", f"spec={spec}",
            "-f", f"account={account}",
            "-f", f"use_mocks={'true' if use_mocks else 'false'}",
            "-f", f"use_live_mocks={'true' if use_mocks else 'false'}",
            "-f", f"record_live_fixtures={'true' if record_live_fixtures else 'false'}",
            "-f", f"allow_credential_updates={'true' if allow_credential_updates else 'false'}",
            "-f", f"requires_account={'true' if requires_account else 'false'}",
            "-f", f"dispatch_token={dispatch_token}",
        ]
        if self.git_sha:
            command.extend(["-f", f"checkout_ref={self.git_sha}"])
        if create_account_slot is not None:
            command.extend(["-f", f"create_account_slot={create_account_slot}"])
        if seeded_gift_card_code:
            command.extend(["-f", f"seeded_gift_card_code={seeded_gift_card_code}"])
        if proof_video_profile:
            command.extend(["-f", f"proof_video_profile={proof_video_profile}"])
        if daily_ai_run_id:
            command.extend(["-f", f"daily_ai_run_id={daily_ai_run_id}"])

        self.dispatch_circuit.wait_for_mutating_request_slot()
        rc = subprocess.run(
            command,
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            detail = (rc.stderr or rc.stdout or "unknown gh workflow error").strip()
            if _is_github_rate_limit_error(detail):
                self.dispatch_circuit.open_rate_limit()
                self.last_dispatch_error = "GitHub Actions rate limit blocked workflow dispatch"
            else:
                category = github_dispatch_error_category(detail)
                self.last_dispatch_error = f"GitHub Actions workflow dispatch failed ({category})"
            _log(f"Dispatch failed for {spec}: {self.last_dispatch_error}", "ERROR")
            return None
        return dispatch_token

    def resolve_dispatch_tokens(self, pending: dict[str, str]) -> dict[str, int]:
        """Resolve many dispatch tokens with one workflow-list query per poll."""
        resolved: dict[str, int] = {}
        for _attempt in range(6):
            if not pending:
                break
            time.sleep(2)
            runs = self._recent_runs(limit=max(50, min(100, len(pending) * 3)))
            if self.last_dispatch_error:
                break
            for token in list(pending):
                run_id = _matching_dispatched_run_id(runs, token)
                if run_id is not None:
                    resolved[token] = run_id
                    pending.pop(token)
        for token, spec in pending.items():
            _log(f"Could not capture run ID for {spec} after dispatch", "WARN")
        if pending and not self.last_dispatch_error:
            self.last_dispatch_error = "Workflow dispatched, but GitHub did not expose a new run ID in time"
        return resolved

    def _recent_runs(self, limit: int = 5, workflow: str = WORKFLOW_NAME) -> list[dict]:
        """Get runs directly without the extra workflow-list lookup from `gh run list`."""
        workflow_id = urllib.parse.quote(workflow, safe="")
        rc = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{GH_REPO}/actions/workflows/{workflow_id}/runs?per_page={limit}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if rc.returncode != 0:
            detail = (rc.stderr or rc.stdout or "GitHub workflow-runs query failed").strip()
            if _is_github_rate_limit_error(detail):
                self.dispatch_circuit.open_rate_limit()
                self.last_dispatch_error = "GitHub Actions rate limit blocked workflow run discovery"
            else:
                self.last_dispatch_error = (
                    f"GitHub Actions workflow run discovery failed ({github_dispatch_error_category(detail)})"
                )
            _log(self.last_dispatch_error, "ERROR")
            return []
        try:
            data = json.loads(rc.stdout)
        except json.JSONDecodeError:
            self.last_dispatch_error = "GitHub Actions workflow run discovery returned invalid JSON"
            return []
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        if not isinstance(runs, list):
            self.last_dispatch_error = "GitHub Actions workflow run discovery returned an invalid payload"
            return []
        return [
            {
                "databaseId": run.get("id"),
                "displayTitle": run.get("display_title") or run.get("name") or "",
            }
            for run in runs
            if isinstance(run, dict)
        ]

    def _recent_run_ids(self, limit: int = 5, workflow: str = WORKFLOW_NAME) -> list[int]:
        """Get the most recent run IDs for a workflow."""
        try:
            return [int(r["databaseId"]) for r in self._recent_runs(limit, workflow)]
        except (KeyError, TypeError, ValueError):
            return []

    def poll_run(self, run_id: int) -> dict:
        """Get status/conclusion for a single run."""
        rc = subprocess.run(
            ["gh", "run", "view", str(run_id),
             "--repo", GH_REPO,
             "--json", "status,conclusion,name,updatedAt"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            return {"status": "unknown", "conclusion": None}
        try:
            return json.loads(rc.stdout)
        except json.JSONDecodeError:
            return {"status": "unknown", "conclusion": None}

    def wait_for_runs(
        self, run_ids: list[int], fail_fast: bool = True,
        poll_interval: int = POLL_INTERVAL, timeout: int = RUN_TIMEOUT,
    ) -> dict[int, dict]:
        """
        Poll until all runs complete. Returns {run_id: {status, conclusion}}.

        With fail_fast=True (batch-level): waits for the entire batch to finish,
        then reports. Does NOT cancel mid-batch — just prevents next batch from
        starting if any failures occurred.
        """
        start = time.time()
        results: dict[int, dict] = {}

        while time.time() - start < timeout:
            all_done = True
            for rid in run_ids:
                if rid in results and results[rid].get("status") == "completed":
                    continue
                data = self.poll_run(rid)
                results[rid] = data
                if data.get("status") != "completed":
                    all_done = False

            if all_done:
                return results

            # Progress update
            completed = sum(1 for r in results.values() if r.get("status") == "completed")
            passed = sum(1 for r in results.values() if r.get("conclusion") == "success")
            failed = sum(1 for r in results.values() if r.get("conclusion") == "failure")
            print(
                f"\r  Polling: {completed}/{len(run_ids)} done "
                f"({passed} passed, {failed} failed)...",
                end="", flush=True,
            )
            time.sleep(poll_interval)

        # Timeout — cancel remaining runs
        print()
        _log(f"Batch timed out after {timeout}s", "WARN")
        for rid in run_ids:
            if results.get(rid, {}).get("status") != "completed":
                self.cancel_run(rid)
                results[rid] = {"status": "completed", "conclusion": "timed_out"}
        return results

    def cancel_run(self, run_id: int) -> None:
        """Cancel a workflow run."""
        subprocess.run(
            ["gh", "run", "cancel", str(run_id), "--repo", GH_REPO],
            capture_output=True,
        )

    def get_failed_job_error(self, run_id: int) -> Optional[str]:
        """Extract error details from a failed run's job logs via `gh run view --log-failed`.
        Returns a trimmed error snippet or None."""
        context_lines: list[str] = []
        jobs = subprocess.run(
            ["gh", "run", "view", str(run_id), "--repo", GH_REPO, "--json", "jobs"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if jobs.returncode == 0 and jobs.stdout.strip():
            try:
                payload = json.loads(jobs.stdout)
            except json.JSONDecodeError:
                payload = {}
            for job in payload.get("jobs") or []:
                if job.get("conclusion") not in {"failure", "timed_out", "cancelled"}:
                    continue
                if job.get("name"):
                    context_lines.append(f"Failed job: {job['name']} ({job.get('conclusion')})")
                for step in job.get("steps") or []:
                    if step.get("conclusion") in {"failure", "timed_out", "cancelled"} and step.get("name"):
                        context_lines.append(f"Failed step: {step['name']} ({step.get('conclusion')})")
                break

        rc = subprocess.run(
            ["gh", "run", "view", str(run_id),
             "--repo", GH_REPO,
             "--log-failed"],
            capture_output=True, text=True,
            timeout=30,
        )
        if rc.returncode != 0 or not rc.stdout.strip():
            return "\n".join(context_lines)[:MAX_ERROR_SNIPPET] if context_lines else None

        lines = rc.stdout.strip().splitlines()

        # Look for Playwright-style error lines (assertions, timeouts, etc.)
        error_lines: list[str] = []
        capture = False
        for line in lines:
            # Strip the GitHub Actions job/step prefix (e.g. "run-playwright\tRun tests\t")
            text = line.split("\t")[-1] if "\t" in line else line

            # Start capturing at error indicators
            if any(kw in text for kw in [
                "Error:", "FAILED", "expect(", "Timeout", "AssertionError",
                "Error: locator", "waiting for", "error TS",
                "Cannot find module", "ERR_MODULE_NOT_FOUND", "##[error]",
                "Process completed with exit code", "Test timeout",
            ]):
                capture = True
            if capture:
                error_lines.append(text.strip())
                if len(error_lines) >= 15:
                    break

        if error_lines:
            return "\n".join([*context_lines, *error_lines])[:MAX_ERROR_SNIPPET]

        # Fallback: return last N non-empty lines (usually contains the failure reason)
        tail = [ln.split("\t")[-1].strip() if "\t" in ln else ln.strip()
                for ln in lines[-20:] if ln.strip()]
        if tail:
            return "\n".join([*context_lines, *tail[-10:]])[:MAX_ERROR_SNIPPET]

        return None

    def download_artifact(self, run_id: int, artifact_name: str, dest_dir: Path) -> Optional[Path]:
        """Download a run's artifact with retry. Returns path to downloaded dir or None."""
        dest = dest_dir / str(run_id)
        dest.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            rc = subprocess.run(
                ["gh", "run", "download", str(run_id),
                 "--repo", GH_REPO,
                 "--name", artifact_name,
                 "--dir", str(dest)],
                capture_output=True, text=True,
            )
            if rc.returncode == 0:
                return dest
            if attempt < 2:
                _log(f"Artifact download attempt {attempt + 1} failed for run {run_id}: "
                     f"{rc.stderr.strip()[:200]}", "WARN")
                time.sleep(10)
        _log(f"Artifact download failed after 3 attempts for run {run_id}: "
             f"{rc.stderr.strip()[:200]}", "ERROR")
        return None


def _effective_playwright_batch_size(
    requested_batch_size: int,
    normal_account_slots: tuple[int, ...] = NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS,
) -> int:
    """Keep each batch from assigning the same normal account twice."""
    if not normal_account_slots:
        return 0
    if requested_batch_size <= 0:
        return len(normal_account_slots)
    return min(requested_batch_size, len(normal_account_slots))


def _account_for_spec_in_batch(
    spec: str,
    normal_index: int,
    normal_account_slots: tuple[int, ...] = NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS,
) -> int:
    """Return the reserved account for mutating specs, otherwise a normal slot."""
    reserved_account = RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC.get(spec)
    if reserved_account is not None:
        return reserved_account
    if not normal_account_slots:
        raise ValueError("At least one normal Playwright account slot is required")
    return normal_account_slots[normal_index % len(normal_account_slots)]


def _cached_preflight_slots(now: float | None = None) -> set[int]:
    current = time.time() if now is None else now
    ACCOUNT_PREFLIGHT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACCOUNT_PREFLIGHT_CACHE_LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            payload = json.loads(ACCOUNT_PREFLIGHT_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        slots = payload.get("slots") if isinstance(payload, dict) else {}
        if not isinstance(slots, dict):
            return set()
        return {
            int(slot)
            for slot, checked_at in slots.items()
            if str(slot).isdigit() and current - float(checked_at or 0) <= ACCOUNT_PREFLIGHT_CACHE_TTL_SECONDS
        }


def _update_preflight_cache(passed_slots: set[int], failed_slots: set[int] | None = None) -> None:
    ACCOUNT_PREFLIGHT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACCOUNT_PREFLIGHT_CACHE_LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            payload = json.loads(ACCOUNT_PREFLIGHT_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        slots = payload.get("slots") if isinstance(payload, dict) else None
        slots = dict(slots) if isinstance(slots, dict) else {}
        now = time.time()
        for slot in passed_slots:
            slots[str(slot)] = now
        for slot in failed_slots or set():
            slots.pop(str(slot), None)
        temporary = ACCOUNT_PREFLIGHT_CACHE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps({"slots": slots}, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, ACCOUNT_PREFLIGHT_CACHE_PATH)


def build_playwright_dispatch_plan(
    specs: list[str],
    batch_size: int,
    normal_account_slots: tuple[int, ...] = NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS,
    requires_account_by_spec: Optional[dict[str, bool]] = None,
) -> list[tuple[int, str, int]]:
    """Build (batch_index, spec, account) tuples using the credential-isolation policy."""
    account_requirements = {
        spec: requires_account_by_spec.get(spec, True)
        if requires_account_by_spec is not None else True
        for spec in specs
    }
    effective_batch_size = _effective_playwright_batch_size(batch_size, normal_account_slots)
    if effective_batch_size <= 0:
        if specs and all(not requires_account for requires_account in account_requirements.values()):
            return [(0, spec, ACCOUNT_FREE_WORKFLOW_ACCOUNT) for spec in specs]
        return []
    plan: list[tuple[int, str, int]] = []
    batch_idx = 0
    normal_index = 0
    account_required_specs_in_batch = 0
    for spec in specs:
        requires_account = account_requirements[spec]
        if requires_account and account_required_specs_in_batch >= effective_batch_size:
            batch_idx += 1
            normal_index = 0
            account_required_specs_in_batch = 0
        if requires_account:
            account = _account_for_spec_in_batch(spec, normal_index, normal_account_slots)
            account_required_specs_in_batch += 1
            if spec not in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC:
                normal_index += 1
        else:
            account = ACCOUNT_FREE_WORKFLOW_ACCOUNT
        plan.append((batch_idx, spec, account))
    return plan


def _preflight_accounts_for_specs(
    specs: list[str],
    batch_size: int,
    requires_account_by_spec: Optional[dict[str, bool]] = None,
) -> list[int]:
    """Preflight only account slots that the pending Playwright plan can use."""
    return list(dict.fromkeys(
        account
        for _batch_index, _spec, account in build_playwright_dispatch_plan(
            specs,
            batch_size,
            requires_account_by_spec=requires_account_by_spec,
        )
        if account != ACCOUNT_FREE_WORKFLOW_ACCOUNT
    ))


def _passed_preflight_slots(results: list[SpecResult]) -> frozenset[int]:
    """Return account slots that completed the preflight login successfully."""
    return frozenset(
        result.account
        for result in results
        if result.account is not None and result.status == "passed"
    )


def _passed_normal_preflight_slots(results: list[SpecResult]) -> tuple[int, ...]:
    """Return healthy normal account slots in stable dispatch order."""
    passed_slots = _passed_preflight_slots(results)
    return tuple(slot for slot in NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS if slot in passed_slots)


def _single_spec_fallback_accounts(failed_account: int) -> list[int]:
    """Bound failover so one unhealthy slot cannot fan out to every account."""
    return [
        slot
        for slot in NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS
        if slot != failed_account
    ][:SINGLE_SPEC_PREFLIGHT_FALLBACK_LIMIT]


def _apply_preflight_account_availability(
    specs: list[str],
    preflight_results: list[SpecResult],
    requires_account_by_spec: Optional[dict[str, bool]] = None,
) -> tuple[list[str], list[SpecResult], tuple[int, ...], Optional[str]]:
    """Filter out specs whose reserved account is unavailable.

    Normal account slots are interchangeable, so missing optional normal slots
    should reduce concurrency rather than abort the entire Playwright suite.
    Reserved slots are tied to credential-mutating specs and must block only the
    specs that require them.
    """
    passed_slots = _passed_preflight_slots(preflight_results)
    normal_slots = tuple(slot for slot in NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS if slot in passed_slots)
    uses_normal_slots = any(
        (requires_account_by_spec.get(spec, True) if requires_account_by_spec is not None else True)
        and spec not in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC
        for spec in specs
    )
    missing_normal_slots = (
        tuple(slot for slot in NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS if slot not in passed_slots)
        if uses_normal_slots else ()
    )
    blocked: list[SpecResult] = []
    runnable: list[str] = []

    for spec in specs:
        requires_account = (
            requires_account_by_spec.get(spec, True)
            if requires_account_by_spec is not None else True
        )
        if not requires_account:
            runnable.append(spec)
            continue
        reserved_slot = RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC.get(spec)
        if reserved_slot is not None and reserved_slot not in passed_slots:
            blocked.append(SpecResult(
                name=spec,
                file=spec,
                status="failed",
                error=f"Reserved Playwright account slot {reserved_slot} failed or was not configured in preflight",
                account=reserved_slot,
            ))
            continue
        runnable.append(spec)

    reason_parts: list[str] = []
    if missing_normal_slots:
        reason_parts.append(
            "Unavailable normal account slot(s): " + ", ".join(str(slot) for slot in missing_normal_slots)
        )
    if blocked:
        blocked_labels = ", ".join(f"{result.file} (slot {result.account})" for result in blocked)
        reason_parts.append("Blocked reserved-account spec(s): " + blocked_labels)
    reason = "; ".join(reason_parts) if reason_parts else None
    return runnable, blocked, normal_slots, reason


# ---------------------------------------------------------------------------
# BatchRunner
# ---------------------------------------------------------------------------

class BatchRunner:
    """Dispatches Playwright specs to GitHub Actions in batches."""

    def __init__(
        self,
        client: GitHubActionsClient,
        specs: list[str],
        batch_size: int = 20,
        fail_fast: bool = True,
        use_mocks: bool = True,
        record_live_fixtures: bool = False,
        normal_account_slots: tuple[int, ...] = NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS,
        create_account_slot: Optional[int] = None,
        allow_credential_updates: bool = True,
        seeded_gift_cards: Optional[dict[str, SeededGiftCard]] = None,
        proof_video_profile: str = "",
        daily_ai_run_id: str = "",
        requires_account_by_spec: Optional[dict[str, bool]] = None,
        progress_callback: Optional[Callable[[SuiteResult], None]] = None,
        coordinate_accounts: bool | None = None,
    ) -> None:
        self.client = client
        self.specs = specs
        self.batch_size = batch_size
        self.fail_fast = fail_fast
        self.use_mocks = use_mocks
        self.record_live_fixtures = record_live_fixtures
        self.normal_account_slots = normal_account_slots
        self.create_account_slot = create_account_slot
        self.allow_credential_updates = allow_credential_updates
        self.seeded_gift_cards = seeded_gift_cards or {}
        self.proof_video_profile = proof_video_profile
        self.daily_ai_run_id = daily_ai_run_id
        self.requires_account_by_spec = requires_account_by_spec or {}
        self.progress_callback = progress_callback
        external_account_lease_held = os.environ.get(PLAYWRIGHT_ACCOUNT_LEASE_HELD_ENV) == "1"
        self.coordinate_accounts = (
            isinstance(client, GitHubActionsClient) and not external_account_lease_held
            if coordinate_accounts is None
            else coordinate_accounts
        )

    def _spec_requires_account(self, spec: str) -> bool:
        return self.requires_account_by_spec.get(spec, True)

    @staticmethod
    def _suite_from_results(results: list[SpecResult], duration_seconds: float) -> SuiteResult:
        tests = [BatchRunner._spec_result_to_dict(result) for result in results]
        has_failures = any(_is_problem_status(result.status) for result in results)
        all_skipped = bool(results) and all(result.status == "skipped" for result in results)
        return SuiteResult(
            status="skipped" if all_skipped else "failed" if has_failures else "passed",
            tests=tests,
            duration_seconds=round(duration_seconds, 1),
        )

    def _emit_progress(self, all_results: list[SpecResult], suite_start: float) -> None:
        if self.progress_callback is not None:
            self.progress_callback(self._suite_from_results(all_results, time.time() - suite_start))

    def _dispatch_circuit_snapshot(self) -> dict[str, object]:
        circuit = getattr(self.client, "dispatch_circuit", None)
        return circuit.snapshot() if circuit is not None else {"open": False}

    @staticmethod
    def _dispatch_blocked_result(spec: str) -> SpecResult:
        return SpecResult(
            name=spec,
            file=spec,
            status="blocked_by_parent",
            error="Blocked by GitHub Actions dispatch infrastructure incident",
            parent_incident_key=GITHUB_DISPATCH_INCIDENT_KEY,
        )

    def _dispatch_incident_result(self) -> SpecResult:
        snapshot = self._dispatch_circuit_snapshot()
        return SpecResult(
            name="github-actions-dispatch",
            file="scripts/run_tests.py",
            status="infrastructure_incident",
            error=str(snapshot.get("incident_code") or "github_actions_dispatch_unavailable"),
            test_key=GITHUB_DISPATCH_INCIDENT_KEY,
        )

    def _claim_dispatch_incident_result(self) -> list[SpecResult]:
        circuit = getattr(self.client, "dispatch_circuit", None)
        if circuit is None or not circuit.claim_incident():
            return []
        return [self._dispatch_incident_result()]

    def run_all_batches(self) -> SuiteResult:
        """Continuously refill independent account lanes until every spec finishes."""
        if not self.specs:
            return SuiteResult(status="skipped", reason="no specs to run")

        all_results: list[SpecResult] = []
        effective_batch_size = _effective_playwright_batch_size(self.batch_size, self.normal_account_slots)
        if effective_batch_size <= 0:
            if all(not self._spec_requires_account(spec) for spec in self.specs):
                effective_batch_size = self.batch_size if self.batch_size > 0 else len(self.specs)
            else:
                return SuiteResult(status="failed", reason="no available normal Playwright account slots")
        suite_start = time.time()
        refresh_budget = getattr(self.client, "refresh_dispatch_budget", None)
        if callable(refresh_budget):
            refresh_budget(len(self.specs))
        if self._dispatch_circuit_snapshot().get("open"):
            return self._suite_from_results(
                [*self._claim_dispatch_incident_result(), *[self._dispatch_blocked_result(spec) for spec in self.specs]],
                time.time() - suite_start,
            )
        pending = deque(enumerate(self.specs))
        completed: dict[int, SpecResult] = {}
        state_lock = threading.Lock()
        stop_dispatch = threading.Event()
        worker_slots = self.normal_account_slots[:min(effective_batch_size, len(self.specs))]
        if not worker_slots:
            worker_slots = (ACCOUNT_FREE_WORKFLOW_ACCOUNT,) * min(effective_batch_size, len(self.specs))

        _log(f"Dynamic Playwright queue: {len(self.specs)} specs across {len(worker_slots)} account workers")

        def worker(preferred_account: int) -> None:
            while not stop_dispatch.is_set():
                with state_lock:
                    if self._dispatch_circuit_snapshot().get("open"):
                        stop_dispatch.set()
                        return
                    if not pending:
                        return
                    spec_index, spec = pending.popleft()
                batch_results = self._run_batch(
                    [spec],
                    spec_index,
                    account_overrides=[preferred_account],
                )
                result = batch_results[0] if batch_results else SpecResult(
                    name=spec,
                    file=spec,
                    status="dispatch_error",
                    error="Dynamic worker returned no result",
                )
                if self._dispatch_circuit_snapshot().get("open") and result.status == "dispatch_error":
                    result = self._dispatch_blocked_result(spec)
                with state_lock:
                    completed[spec_index] = result
                    ordered_progress = [completed[index] for index in sorted(completed)]
                    self._emit_progress(ordered_progress, suite_start)
                    if self.fail_fast and result.status == "failed":
                        stop_dispatch.set()
                    if self._dispatch_circuit_snapshot().get("open"):
                        stop_dispatch.set()

        with ThreadPoolExecutor(max_workers=len(worker_slots), thread_name_prefix="playwright-account") as executor:
            futures = [executor.submit(worker, account) for account in worker_slots]
            for future in futures:
                future.result()

        if pending:
            for spec_index, spec in pending:
                completed[spec_index] = (
                    self._dispatch_blocked_result(spec)
                    if self._dispatch_circuit_snapshot().get("open")
                    else SpecResult(
                        name=spec,
                        file=spec,
                        status="not_started",
                        error="Skipped: fail-fast after an earlier dynamic account lane failed",
                    )
                )
        all_results = [completed[index] for index in sorted(completed)]
        if self._dispatch_circuit_snapshot().get("open"):
            all_results = [*self._claim_dispatch_incident_result(), *all_results]
        self._emit_progress(all_results, suite_start)
        return self._suite_from_results(all_results, time.time() - suite_start)

    def _run_batch(
        self,
        specs: list[str],
        batch_idx: int,
        account_overrides: Optional[list[int]] = None,
    ) -> list[SpecResult]:
        """Dispatch and wait for a single batch of specs."""
        # Dispatch all specs in this batch
        dispatched: list[tuple[str, int, int, bool]] = []  # (spec, account, run_id, requires_account)
        pending_dispatches: dict[str, tuple[str, int, bool]] = {}
        dispatch_errors: list[SpecResult] = []
        normal_account_index = 0
        account_leases: dict[int, tuple[str, set[str]]] = {}
        lease_owner = os.environ.get("OPENCODE_SESSION_ID", "scheduled-test-runner")

        def claim_account(preferred: int, *, reserved: bool) -> int:
            if not self.coordinate_accounts:
                return preferred
            if preferred in account_leases:
                return preferred
            candidates = [preferred] if reserved else [
                *self.normal_account_slots[self.normal_account_slots.index(preferred):],
                *self.normal_account_slots[:self.normal_account_slots.index(preferred)],
            ]
            while True:
                for candidate in candidates:
                    if candidate in account_leases:
                        continue
                    lease_id = f"playwright-account-{candidate}-{uuid4().hex[:10]}"
                    resources = {f"playwright-account:{candidate}"}
                    try:
                        session_control.acquire_test_resource_lease(
                            lease_id,
                            lease_owner,
                            resources,
                            timeout=0,
                            poll=1,
                            mode="exclusive",
                        )
                    except RuntimeError:
                        continue
                    account_leases[candidate] = (lease_id, resources)
                    return candidate
                _log("All eligible Playwright accounts are busy; waiting for a released lane", "WARN")
                time.sleep(5)

        def release_account_leases() -> None:
            for lease_id, _resources in account_leases.values():
                try:
                    session_control.release_test_resource_lease(lease_id)
                except RuntimeError as exc:
                    _log(f"Could not release Playwright account lease {lease_id}: {exc}", "WARN")

        for i, spec in enumerate(specs):
            requires_account = self._spec_requires_account(spec)
            if not requires_account:
                account = ACCOUNT_FREE_WORKFLOW_ACCOUNT
            elif spec in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC:
                account = RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC[spec]
            elif account_overrides is not None:
                account = account_overrides[i]
            elif spec == ACCOUNT_PREFLIGHT_SPEC:
                account = i + 1
            else:
                account = _account_for_spec_in_batch(spec, normal_account_index, self.normal_account_slots)
            if requires_account and spec not in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC and spec != ACCOUNT_PREFLIGHT_SPEC:
                normal_account_index += 1
            if requires_account and spec != ACCOUNT_PREFLIGHT_SPEC:
                account = claim_account(
                    account,
                    reserved=spec in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC,
                )
            account_label = f"account {account}" if requires_account else "account-free"
            _log(f"  Dispatching {spec} ({account_label})")

            create_account_slot = self.create_account_slot if requires_account and spec == PROVISION_AUTH_ACCOUNTS_SPEC else None
            seeded_gift_card = self.seeded_gift_cards.get(spec) if requires_account else None
            allow_credential_updates = self.allow_credential_updates and requires_account
            if hasattr(self.client, "request_spec_dispatch"):
                dispatch_token = self.client.request_spec_dispatch(
                    spec,
                    account,
                    self.use_mocks,
                    self.record_live_fixtures,
                    create_account_slot=create_account_slot,
                    allow_credential_updates=allow_credential_updates,
                    seeded_gift_card_code=seeded_gift_card.code if seeded_gift_card else None,
                    proof_video_profile=self.proof_video_profile,
                    daily_ai_run_id=self.daily_ai_run_id,
                    requires_account=requires_account,
                )
            else:
                run_id = self.client.dispatch_spec(
                    spec,
                    account,
                    self.use_mocks,
                    self.record_live_fixtures,
                    create_account_slot=create_account_slot,
                    allow_credential_updates=allow_credential_updates,
                    seeded_gift_card_code=seeded_gift_card.code if seeded_gift_card else None,
                    proof_video_profile=self.proof_video_profile,
                    daily_ai_run_id=self.daily_ai_run_id,
                    requires_account=requires_account,
                )
                dispatch_token = f"immediate:{run_id}" if run_id is not None else None
            circuit = getattr(self.client, "dispatch_circuit", None)
            retry_admitted = True
            if dispatch_token is None and circuit is not None:
                retry_admitted = circuit.reserve_requests(1)
            if (
                dispatch_token is None
                and not self.record_live_fixtures
                and not self._dispatch_circuit_snapshot().get("open")
                and retry_admitted
            ):
                # Retry once
                time.sleep(5)
                if hasattr(self.client, "request_spec_dispatch"):
                    dispatch_token = self.client.request_spec_dispatch(
                        spec,
                        account,
                        self.use_mocks,
                        self.record_live_fixtures,
                        create_account_slot=create_account_slot,
                        allow_credential_updates=allow_credential_updates,
                        seeded_gift_card_code=seeded_gift_card.code if seeded_gift_card else None,
                        proof_video_profile=self.proof_video_profile,
                        daily_ai_run_id=self.daily_ai_run_id,
                        requires_account=requires_account,
                    )
                else:
                    run_id = self.client.dispatch_spec(
                        spec,
                        account,
                        self.use_mocks,
                        self.record_live_fixtures,
                        create_account_slot=create_account_slot,
                        allow_credential_updates=allow_credential_updates,
                        seeded_gift_card_code=seeded_gift_card.code if seeded_gift_card else None,
                        proof_video_profile=self.proof_video_profile,
                        daily_ai_run_id=self.daily_ai_run_id,
                        requires_account=requires_account,
                    )
                    dispatch_token = f"immediate:{run_id}" if run_id is not None else None

            if dispatch_token is None:
                dispatch_errors.append(SpecResult(
                    name=spec, file=spec, status="dispatch_error",
                    error=self.client.last_dispatch_error or "Failed to dispatch workflow after retry",
                ))
            else:
                pending_dispatches[dispatch_token] = (spec, account, requires_account)

        immediate = {
            token: int(token.partition(":")[2])
            for token in pending_dispatches
            if token.startswith("immediate:")
        }
        unresolved = {
            token: spec
            for token, (spec, _account, _requires_account) in pending_dispatches.items()
            if token not in immediate
        }
        resolved = {
            **immediate,
            **(self.client.resolve_dispatch_tokens(unresolved) if unresolved else {}),
        }
        for token, (spec, account, requires_account) in pending_dispatches.items():
            run_id = resolved.get(token)
            if run_id is None:
                dispatch_errors.append(SpecResult(
                    name=spec,
                    file=spec,
                    status="dispatch_error",
                    error=self.client.last_dispatch_error or "Workflow run ID was not resolved",
                ))
            else:
                dispatched.append((spec, account, run_id, requires_account))

        if not dispatched:
            release_account_leases()
            return dispatch_errors

        lease_heartbeat_stop = threading.Event()

        def renew_account_leases() -> None:
            while not lease_heartbeat_stop.wait(session_control.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, resources in account_leases.values():
                    try:
                        session_control.renew_test_resource_lease(
                            lease_id,
                            lease_owner,
                            resources,
                            mode="exclusive",
                        )
                    except RuntimeError as exc:
                        _log(f"Playwright account lease renewal failed: {exc}", "ERROR")
                        return

        lease_heartbeat = threading.Thread(
            target=renew_account_leases,
            name="playwright-account-lease-heartbeat",
            daemon=True,
        )
        lease_heartbeat.start()

        # Wait for all dispatched runs
        run_ids = [rid for _, _, rid, _requires_account in dispatched]
        _log(f"  Waiting for {len(run_ids)} runs...")
        statuses = self.client.wait_for_runs(run_ids, self.fail_fast)
        print()  # Clear the polling line

        # Collect results
        results: list[SpecResult] = list(dispatch_errors)
        artifact_dir = Path(tempfile.mkdtemp(prefix="pw-artifacts-"))

        for spec, account, rid, requires_account in dispatched:
            status_data = statuses.get(rid, {})
            conclusion = status_data.get("conclusion", "unknown")

            if conclusion == "success":
                status = "passed"
                error = None
            elif conclusion == "timed_out":
                status = "timeout"
                error = "Run timed out"
            elif conclusion == "cancelled":
                status = "not_started"
                error = "Run was cancelled"
            else:
                status = "failed"
                error = f"GitHub Actions conclusion: {conclusion}"

            # Download artifact for error details, screenshots, and step data.
            # Download for ALL statuses (not just failed) so MD reports can
            # include steps and screenshots for passed tests too.
            pw_errors: list[dict] = []
            pw_steps: list[dict] = []
            screenshot_paths: list[str] = []
            video_paths: list[str] = []
            proof_timeline_path: Optional[str] = None
            debug_artifacts: list[str] = []
            debug_output_summary: Optional[str] = None
            environment_blocker: Optional[str] = None
            account_email: Optional[str] = None
            retries = 0
            flaky = False
            attempt_statuses: list[str] = []

            art_name = f"playwright-{spec.replace('/', '-')}"
            art_path = self.client.download_artifact(rid, art_name, artifact_dir)
            if art_path:
                # playwright.json may be at top level or under test-results/
                pw_json = art_path / "playwright.json"
                if not pw_json.is_file():
                    pw_json = art_path / "test-results" / "playwright.json"
                if pw_json.is_file():
                    extracted_err, pw_errors, pw_steps, pw_result_statuses = (
                        self._extract_structured_data_from_playwright_json(pw_json)
                    )
                    attempt_summary = self._playwright_attempt_summary(pw_json)
                    pw_result_statuses = attempt_summary["terminal_statuses"]
                    retries = int(attempt_summary["retries"])
                    flaky = bool(attempt_summary["flaky"])
                    attempt_statuses = list(attempt_summary["attempt_statuses"])
                    account_email = self._extract_account_email_from_playwright_json(pw_json)
                    if status == "passed" and pw_result_statuses:
                        non_passing_statuses = {
                            result_status
                            for result_status in pw_result_statuses
                            if result_status not in {"passed", "skipped"}
                        }
                        if all(result_status == "skipped" for result_status in pw_result_statuses):
                            status = "skipped"
                            error = "Playwright spec skipped all tests"
                        elif non_passing_statuses:
                            status = "failed"
                            status_summary = ", ".join(sorted(non_passing_statuses))
                            error = extracted_err or f"Playwright JSON reported non-passing result(s): {status_summary}"
                    if extracted_err and status == "failed":
                        error = extracted_err
                    debug_summary = self._persist_playwright_debug_outputs(spec, pw_json)
                    debug_artifacts = list(debug_summary.get("artifact_paths") or [])
                    debug_output_summary = str(debug_summary.get("summary") or "") or None
                    environment_blocker = self._environment_blocker_from_text(
                        "\n".join(part for part in [error or "", debug_output_summary or ""] if part)
                    )

                # Persist artifacts (screenshots, traces, playwright.json)
                self._persist_failure_artifacts(spec, art_path)
                self._persist_credential_update_artifacts(spec, art_path)
                proof_timeline_path = self._persist_recording_artifacts(spec, art_path)
                video_paths = self._collect_video_paths(art_path)

                # Collect screenshot paths relative to test-results/
                spec_name = spec.replace(".spec.ts", "")
                ss_dir = RESULTS_DIR / "screenshots" / "current" / spec_name
                if ss_dir.is_dir():
                    screenshot_paths = sorted(
                        str(p.relative_to(RESULTS_DIR))
                        for p in ss_dir.iterdir()
                        if p.suffix in (".png", ".webp")
                    )

            # Fallback for failed tests: fetch job logs if no Playwright error found
            if status == "failed" and error == f"GitHub Actions conclusion: {conclusion}":
                log_error = self.client.get_failed_job_error(rid)
                if log_error:
                    error = log_error

            icon = {
                "passed": "✓",
                "failed": "✗",
                "dispatch_error": "!",
                "timeout": "⏱",
                "not_started": "⊘",
            }.get(status, "?")
            _log(f"  {icon} {spec} (run {rid})", "OK" if status == "passed" else "ERROR")
            if requires_account and status not in {"passed", "skipped"}:
                _update_preflight_cache(set(), {account})

            results.append(SpecResult(
                name=spec, file=spec, status=status,
                error=error, run_id=rid, account=account if requires_account else None, account_email=account_email,
                retries=retries, flaky=flaky, attempt_statuses=attempt_statuses,
                playwright_errors=pw_errors,
                steps=pw_steps,
                screenshot_paths=screenshot_paths,
                video_paths=video_paths,
                video_artifact_name=art_name if video_paths else None,
                proof_timeline_path=proof_timeline_path,
                github_run_url=f"https://github.com/{GH_REPO}/actions/runs/{rid}" if rid else None,
                debug_artifacts=debug_artifacts,
                debug_output_summary=debug_output_summary,
                environment_blocker=environment_blocker,
            ))

        # Cleanup artifact dir
        shutil.rmtree(artifact_dir, ignore_errors=True)
        lease_heartbeat_stop.set()
        lease_heartbeat.join(timeout=1)
        release_account_leases()
        return results

    @staticmethod
    def _extract_structured_data_from_playwright_json(
        pw_json: Path,
    ) -> tuple[Optional[str], list[dict], list[dict], list[str]]:
        """Extract error message, structured errors, and step data from Playwright JSON.

        Handles nested suites (suites can contain both specs and child suites).

        Returns:
            (first_error_string, playwright_errors_list, steps_list)
        """
        first_error: Optional[str] = None
        errors: list[dict] = []
        steps: list[dict] = []
        result_statuses: list[str] = []

        def _process_result(result: dict) -> None:
            nonlocal first_error
            result_status = str(result.get("status", ""))
            if result_status:
                result_statuses.append(result_status)
            # Extract steps with pass/fail status
            for step in result.get("steps", []):
                step_entry: dict = {
                    "title": step.get("title", ""),
                    "duration_ms": step.get("duration", 0),
                    "status": "failed" if step.get("error") else "passed",
                }
                if step.get("error"):
                    err = step["error"]
                    step_entry["error"] = (
                        err.get("message", str(err))
                        if isinstance(err, dict) else str(err)
                    )
                steps.append(step_entry)

            # Extract attachments (screenshots)
            attachments = []
            for att in result.get("attachments", []):
                if att.get("contentType", "").startswith("image/"):
                    attachments.append({
                        "name": att.get("name", ""),
                        "path": att.get("path", ""),
                    })

            # Extract errors from non-passed results
            if result.get("status") != "passed":
                err = result.get("error", {})
                if isinstance(err, dict):
                    msg = err.get("message", "")
                    stack = err.get("stack", "")
                elif isinstance(err, str):
                    msg = err
                    stack = ""
                else:
                    msg = ""
                    stack = ""

                if msg:
                    if first_error is None:
                        first_error = msg[:MAX_ERROR_SNIPPET]
                    errors.append({
                        "message": msg,
                        "stack": stack[:1000] if stack else "",
                        "attachments": attachments,
                    })

        def _walk_suite(suite: dict) -> None:
            """Recursively walk nested suites to find all specs and tests."""
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    for result in test.get("results", []):
                        _process_result(result)
            # Recurse into nested suites
            for child_suite in suite.get("suites", []):
                _walk_suite(child_suite)

        try:
            with open(pw_json) as f:
                data = json.load(f)

            for suite in data.get("suites", []):
                _walk_suite(suite)

            # Check top-level errors (e.g. compilation errors)
            for err in data.get("errors", []):
                msg = err.get("message", "")
                if msg:
                    if first_error is None:
                        first_error = msg[:MAX_ERROR_SNIPPET]
                    errors.append({"message": msg, "stack": "", "attachments": []})

        except Exception as e:
            _log(f"Failed to parse playwright.json: {e}", "WARN")

        return first_error, errors, steps, result_statuses

    @staticmethod
    def _playwright_attempt_summary(pw_json: Path) -> dict[str, object]:
        """Normalize terminal Playwright attempts while preserving flake evidence."""
        terminal_statuses: list[str] = []
        attempt_statuses: list[str] = []
        retries = 0
        flaky = False

        def process_suite(suite: dict) -> None:
            nonlocal retries, flaky
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    results = test.get("results", [])
                    if not results:
                        continue
                    statuses = [str(result.get("status") or "") for result in results if result.get("status")]
                    attempt_statuses.extend(statuses)
                    if not statuses:
                        continue
                    has_retry_metadata = any("retry" in result for result in results)
                    terminal_index = max(
                        range(len(results)),
                        key=lambda index: int(results[index].get("retry", index) or 0),
                    ) if has_retry_metadata else len(results) - 1
                    terminal_status = str(results[terminal_index].get("status") or "")
                    if terminal_status:
                        terminal_statuses.append(terminal_status)
                    retries += max(0, len(results) - 1)
                    if terminal_status == "passed" and any(
                        status not in {"passed", "skipped"} for status in statuses[:terminal_index]
                    ):
                        flaky = True
            for child_suite in suite.get("suites", []):
                process_suite(child_suite)

        try:
            with pw_json.open(encoding="utf-8") as handle:
                data = json.load(handle)
            for suite in data.get("suites", []):
                process_suite(suite)
        except (json.JSONDecodeError, OSError) as exc:
            _log(f"Failed to summarize Playwright attempts: {exc}", "WARN")

        return {
            "terminal_statuses": terminal_statuses,
            "attempt_statuses": attempt_statuses,
            "retries": retries,
            "flaky": flaky,
        }

    @staticmethod
    def _extract_account_email_from_playwright_json(pw_json: Path) -> Optional[str]:
        """Extract the configured test account email from preflight stdout."""
        marker = 'meta={"email":"'

        def _walk_suite(suite: dict) -> Optional[str]:
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    for result in test.get("results", []):
                        for entry in result.get("stdout", []):
                            text = str(entry.get("text", ""))
                            if marker in text:
                                return text.split(marker, 1)[1].split('"}', 1)[0]
            for child_suite in suite.get("suites", []):
                email = _walk_suite(child_suite)
                if email:
                    return email
            return None

        try:
            with open(pw_json) as f:
                data = json.load(f)
            for suite in data.get("suites", []):
                email = _walk_suite(suite)
                if email:
                    return email
        except Exception as e:
            _log(f"Failed to extract preflight account email: {e}", "WARN")
        return None

    @staticmethod
    def _environment_blocker_from_text(text: str) -> Optional[str]:
        normalized = " ".join((text or "").lower().split())
        markers = (
            "approved_device_required",
            "new device detected",
            "device not approved",
            "a new device attempted to use your api key",
            "please review and approve it in developer settings",
        )
        if any(marker in normalized for marker in markers):
            return "api_key_device_approval_required"
        return None

    @staticmethod
    def _persist_playwright_debug_outputs(spec: str, pw_json: Path) -> dict[str, object]:
        """Persist full per-attempt stdout/stderr and compact summaries."""
        spec_name = spec.replace(".spec.ts", "")
        dest = RESULTS_DIR / "debug" / "current" / spec_name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        artifact_paths: list[str] = []
        summary_parts: list[str] = []

        def write_artifact(name: str, content: str) -> None:
            path = dest / name
            path.write_text(content, encoding="utf-8", errors="replace")
            artifact_paths.append(str(path.relative_to(RESULTS_DIR)))

        def entry_text(entries: object) -> str:
            if not isinstance(entries, list):
                return ""
            chunks: list[str] = []
            for entry in entries:
                if isinstance(entry, dict):
                    chunks.append(str(entry.get("text") or ""))
                else:
                    chunks.append(str(entry))
            return "".join(chunks)

        def process_suite(suite: dict) -> None:
            for spec_entry in suite.get("specs", []):
                for test_index, test in enumerate(spec_entry.get("tests", []), start=1):
                    for result_index, result in enumerate(test.get("results", []), start=1):
                        retry = result.get("retry", result_index - 1)
                        prefix = f"attempt-{test_index}-{retry}"
                        stdout_text = entry_text(result.get("stdout"))
                        stderr_text = entry_text(result.get("stderr"))
                        if stdout_text:
                            write_artifact(f"{prefix}-stdout.txt", stdout_text)
                            summary_parts.append(stdout_text[-4000:])
                        if stderr_text:
                            write_artifact(f"{prefix}-stderr.txt", stderr_text)
                            summary_parts.append(stderr_text[-4000:])
                        write_artifact(
                            f"{prefix}-result.json",
                            json.dumps(result, indent=2, sort_keys=True),
                        )
            for child_suite in suite.get("suites", []):
                process_suite(child_suite)

        try:
            data = json.loads(pw_json.read_text(encoding="utf-8"))
            for suite in data.get("suites", []):
                process_suite(suite)
        except (json.JSONDecodeError, OSError) as exc:
            _log(f"Failed to persist Playwright debug outputs: {exc}", "WARN")

        return {
            "artifact_paths": artifact_paths,
            "summary": "\n".join(summary_parts)[-MAX_ERROR_SNIPPET * 4:],
        }

    @staticmethod
    def _persist_failure_artifacts(spec: str, art_path: Path) -> None:
        """Copy screenshots, traces, and reports from a test's artifacts to
        test-results/screenshots/current/{spec-name}/ for MD report generation.

        Also copies any storage-audit JSON files from the spec's
        test-results/storage-audits/ subdirectory into the canonical
        repo-level test-results/storage-audits/ directory so that
        scripts/merge_storage_audits.py can aggregate them after the run.
        """
        spec_name = spec.replace(".spec.ts", "")
        dest = RESULTS_DIR / "screenshots" / "current" / spec_name
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for root, _dirs, files in os.walk(art_path):
            for fname in files:
                if fname.endswith((".png", ".webp", ".json")):
                    src = Path(root) / fname
                    shutil.copy2(src, dest / fname)
                    copied += 1
        if copied:
            _log(f"    Saved {copied} artifact(s) to test-results/screenshots/current/{spec_name}/")

        # Storage audit snapshots — written by tests/helpers/cookie-audit.ts
        # into frontend/apps/web_app/test-results/storage-audits/. The full
        # artifact tree is uploaded by playwright-spec.yml so we walk it for
        # any storage-audits/*.json files and copy them to the repo-level dir.
        audit_dest = RESULTS_DIR / "storage-audits"
        audit_dest.mkdir(parents=True, exist_ok=True)
        audit_copied = 0
        for root, _dirs, files in os.walk(art_path):
            if Path(root).name != "storage-audits":
                continue
            for fname in files:
                if fname.endswith(".json"):
                    shutil.copy2(Path(root) / fname, audit_dest / fname)
                    audit_copied += 1
        if audit_copied:
            _log(f"    Saved {audit_copied} storage-audit snapshot(s) to test-results/storage-audits/")

    @staticmethod
    def _persist_credential_update_artifacts(spec: str, art_path: Path) -> None:
        """Copy generated credential-update files outside screenshot directories."""
        spec_name = spec.replace(".spec.ts", "")
        dest = RESULTS_DIR / "credential-updates" / spec_name
        copied = 0
        for root, _dirs, files in os.walk(art_path):
            for fname in files:
                if fname not in CREDENTIAL_UPDATE_ARTIFACT_NAMES:
                    continue
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(root) / fname, dest / fname)
                copied += 1
        if copied:
            _log(f"    Saved {copied} credential update artifact(s) to test-results/credential-updates/{spec_name}/")

    @staticmethod
    def _collect_video_paths(art_path: Path) -> list[str]:
        """Return video paths inside a downloaded GitHub Actions artifact.

        Videos can become large quickly, so we intentionally do not persist them
        into `test-results/` or Obsidian. The artifact path is stored only as
        metadata so a human can find the recording in the GitHub artifact.
        """
        video_paths: list[str] = []
        for root, _dirs, files in os.walk(art_path):
            for fname in files:
                if not fname.lower().endswith((".webm", ".mp4")):
                    continue
                src = Path(root) / fname
                try:
                    video_paths.append(src.relative_to(art_path).as_posix())
                except ValueError:
                    video_paths.append(src.name)
        return sorted(video_paths)

    @staticmethod
    def _persist_recording_artifacts(spec: str, art_path: Path) -> Optional[str]:
        """Copy the latest video, screenshots, and raw metadata for /tests."""
        slug = _test_recording_slug(spec)
        dest = TEST_RECORDINGS_DIR / slug
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        screenshots_dest = dest / "screenshots"
        videos_dest = dest / "videos"
        screenshots_dest.mkdir(parents=True, exist_ok=True)
        videos_dest.mkdir(parents=True, exist_ok=True)

        video_sources: list[Path] = []
        screenshot_sources: list[Path] = []
        raw_json_sources: list[Path] = []
        step_log_source: Optional[Path] = None

        for root, _dirs, files in os.walk(art_path):
            root_path = Path(root)
            if "previous_run" in root_path.parts:
                continue
            for fname in files:
                src = root_path / fname
                lower_name = fname.lower()
                if lower_name.endswith((".webm", ".mp4")):
                    video_sources.append(src)
                elif lower_name.endswith((".png", ".webp")):
                    screenshot_sources.append(src)
                elif lower_name == "step-log.json":
                    step_log_source = src
                elif lower_name == "playwright.json":
                    raw_json_sources.append(src)

        copied_videos: list[str] = []
        video_records: list[dict[str, str]] = []
        for src in sorted(video_sources, key=lambda p: p.as_posix()):
            parent_slug = _test_recording_slug(src.parent.name)
            video_name = f"videos/{parent_slug}{src.suffix.lower()}"
            target = dest / video_name
            if target.exists():
                target = videos_dest / f"{parent_slug}-{hashlib.sha1(src.as_posix().encode()).hexdigest()[:8]}{src.suffix.lower()}"
                video_name = f"videos/{target.name}"
            shutil.copy2(src, target)
            copied_videos.append(video_name)
            video_records.append({"file": video_name, "source": src.as_posix()})

        copied_screenshots: list[str] = []
        screenshot_records: list[dict[str, str]] = []
        for src in sorted(screenshot_sources, key=lambda p: p.name):
            target = screenshots_dest / src.name
            if target.exists():
                stem = target.stem
                suffix = target.suffix
                target = screenshots_dest / f"{stem}-{hashlib.sha1(str(src).encode()).hexdigest()[:8]}{suffix}"
            shutil.copy2(src, target)
            copied_name = f"screenshots/{target.name}"
            copied_screenshots.append(copied_name)
            screenshot_records.append({"file": copied_name, "source": src.as_posix()})

        thumbnail = None
        thumbnail_source = "none"
        step_screenshots = [p for p in copied_screenshots if "test-failed" not in p.lower()]
        thumbnail_candidates = step_screenshots or copied_screenshots
        if thumbnail_candidates:
            thumb_source_rel = thumbnail_candidates[len(thumbnail_candidates) // 2]
            thumb_source = dest / thumb_source_rel
            thumbnail = f"thumbnail{thumb_source.suffix.lower()}"
            shutil.copy2(thumb_source, dest / thumbnail)
            thumbnail_source = "fallback"

        if step_log_source:
            shutil.copy2(step_log_source, dest / "step-log.json")
        if raw_json_sources:
            shutil.copy2(raw_json_sources[0], dest / "playwright.json")

        proof_timeline_path: Optional[Path] = None
        proof_video_file: Optional[str] = None
        if raw_json_sources:
            report = json.loads(raw_json_sources[0].read_text(encoding="utf-8"))
            timing_sources = list(art_path.rglob("playwright-video-timing.json"))
            if len(timing_sources) != 1:
                raise RuntimeError("Playwright artifact requires one finalized video timing manifest")
            timing_manifest = json.loads(timing_sources[0].read_text(encoding="utf-8"))
            if timing_manifest.get("schema_version") != 1 or not isinstance(timing_manifest.get("videos"), list):
                raise RuntimeError("Playwright finalized video timing manifest is invalid")
            finalized_at_by_suffix: dict[str, float] = {}
            for timing_record in timing_manifest["videos"]:
                if not isinstance(timing_record, dict) or not isinstance(timing_record.get("path"), str):
                    raise RuntimeError("Playwright finalized video timing record is invalid")
                finalized_at_value = timing_record.get("finalized_at_epoch_ms")
                if (
                    not isinstance(finalized_at_value, (int, float))
                    or isinstance(finalized_at_value, bool)
                    or not math.isfinite(finalized_at_value)
                ):
                    raise RuntimeError("Playwright finalized video timestamp is invalid")
                suffix = str(timing_record["path"]).split("test-results/", 1)[-1]
                if suffix in finalized_at_by_suffix:
                    raise RuntimeError("Playwright finalized video timing path is duplicated")
                finalized_at_by_suffix[suffix] = float(finalized_at_value)
            proof_attachment_groups: list[dict[str, object]] = []
            thumbnail_requests: list[dict[str, object]] = []

            def collect_explicit_thumbnails(value: object) -> None:
                if isinstance(value, dict):
                    results = value.get("results")
                    if isinstance(results, list):
                        candidates: list[tuple[str, dict[str, object]]] = []
                        for result in results:
                            if not isinstance(result, dict):
                                continue
                            attachments = result.get("attachments")
                            if not isinstance(attachments, list):
                                continue
                            matches = [
                                item
                                for item in attachments
                                if isinstance(item, dict)
                                and item.get("name") == "openmates-test-thumbnail-metadata"
                                and item.get("contentType") == "application/vnd.openmates.test-thumbnail+json"
                            ]
                            if len(matches) > 1:
                                raise RuntimeError("Playwright result contains multiple explicit test thumbnails")
                            if matches:
                                proof_timelines = [
                                    item
                                    for item in attachments
                                    if isinstance(item, dict)
                                    and item.get("contentType") == "application/vnd.openmates.proof-timeline+json"
                                ]
                                if len(proof_timelines) > 1:
                                    raise RuntimeError("Explicit test thumbnail result contains multiple proof timelines")
                                video_attachments = [
                                    item
                                    for item in attachments
                                    if isinstance(item, dict)
                                    and str(item.get("contentType") or "").startswith("video/")
                                ]
                                if len(video_attachments) != 1:
                                    raise RuntimeError("Explicit test thumbnail requires one result video")
                                candidates.append((str(result.get("status") or ""), {
                                    "metadata": matches[0],
                                    "video": video_attachments[0],
                                    "proof_timeline": proof_timelines[0] if proof_timelines else None,
                                    "start_time": result.get("startTime"),
                                    "duration_ms": result.get("duration"),
                                }))
                        if candidates:
                            selected = next(
                                (attachment for status, attachment in reversed(candidates) if status == "passed"),
                                candidates[-1][1],
                            )
                            thumbnail_requests.append(selected)
                    for key, child in value.items():
                        if key != "results":
                            collect_explicit_thumbnails(child)
                elif isinstance(value, list):
                    for child in value:
                        collect_explicit_thumbnails(child)

            def collect_timeline_attachments(value: object) -> None:
                if isinstance(value, dict):
                    results = value.get("results")
                    if isinstance(results, list):
                        candidates: list[dict[str, object]] = []
                        for result in results:
                            if not isinstance(result, dict) or not isinstance(result.get("attachments"), list):
                                continue
                            group = [item for item in result["attachments"] if isinstance(item, dict)]
                            if any(
                                item.get("contentType") == "application/vnd.openmates.proof-timeline+json"
                                for item in group
                            ):
                                candidates.append({
                                    "attachments": group,
                                    "status": result.get("status"),
                                    "start_time": result.get("startTime"),
                                    "duration_ms": result.get("duration"),
                                })
                        if candidates:
                            proof_attachment_groups.append(next(
                                (candidate for candidate in reversed(candidates) if candidate.get("status") == "passed"),
                                candidates[-1],
                            ))
                    for key, child in value.items():
                        if key == "results":
                            continue
                        collect_timeline_attachments(child)
                elif isinstance(value, list):
                    for child in value:
                        collect_timeline_attachments(child)

            collect_explicit_thumbnails(report)
            collect_timeline_attachments(report)
            artifact_files = [path for path in art_path.rglob("*") if path.is_file()]
            proof_result = next(
                (group for group in reversed(proof_attachment_groups) if group.get("status") == "passed"),
                proof_attachment_groups[-1] if proof_attachment_groups else {},
            )
            if len(proof_attachment_groups) > 1:
                raise RuntimeError("Playwright report contains ambiguous proof timeline test groups")
            proof_group = proof_result.get("attachments") if isinstance(proof_result.get("attachments"), list) else []
            if len(thumbnail_requests) > 1:
                raise RuntimeError("Playwright report contains multiple explicit test thumbnails")
            if thumbnail_requests:
                request = thumbnail_requests[0]
                explicit_thumbnail = request["metadata"]
                if not isinstance(explicit_thumbnail, dict):
                    raise RuntimeError("Explicit test thumbnail metadata is invalid")
                body = explicit_thumbnail.get("body")
                attachment_path = explicit_thumbnail.get("path")
                if isinstance(body, str):
                    metadata_bytes = base64.b64decode(body, validate=True)
                elif isinstance(attachment_path, str):
                    attachment_name = Path(attachment_path).name
                    sources = [path for path in artifact_files if path.name == attachment_name]
                    if len(sources) != 1:
                        raise RuntimeError("Explicit test thumbnail metadata file is missing")
                    metadata_bytes = sources[0].read_bytes()
                else:
                    raise RuntimeError("Explicit test thumbnail metadata has no content")
                metadata = json.loads(metadata_bytes.decode("utf-8"))
                if metadata.get("schema_version") != 2:
                    raise RuntimeError("Explicit test thumbnail metadata schema must be version 2")
                viewport = metadata.get("viewport")
                clip = metadata.get("clip")
                if not isinstance(viewport, dict) or not isinstance(clip, dict):
                    raise RuntimeError("Explicit test thumbnail geometry is invalid")
                geometry = [viewport.get("width"), viewport.get("height"), clip.get("x"), clip.get("y"), clip.get("width"), clip.get("height")]
                if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in geometry):
                    raise RuntimeError("Explicit test thumbnail geometry must use non-negative integers")
                if viewport["width"] <= 0 or viewport["height"] <= 0 or clip["width"] <= 0 or clip["height"] <= 0:
                    raise RuntimeError("Explicit test thumbnail geometry must be positive")
                if clip["x"] + clip["width"] > viewport["width"] or clip["y"] + clip["height"] > viewport["height"]:
                    raise RuntimeError("Explicit test thumbnail crop exceeds the recorded viewport")
                video_attachment = request.get("video")
                video_attachment_path = video_attachment.get("path") if isinstance(video_attachment, dict) else None
                if not isinstance(video_attachment_path, str):
                    raise RuntimeError("Explicit test thumbnail video path is missing")
                video_attachment_suffix = video_attachment_path.split("test-results/", 1)[-1]
                matching_video_records = [
                    record
                    for record in video_records
                    if str(record.get("source") or "").split("test-results/", 1)[-1] == video_attachment_suffix
                ]
                if len(matching_video_records) != 1:
                    raise RuntimeError("Explicit test thumbnail video artifact is missing or ambiguous")
                video_record = matching_video_records[0]
                video_path = dest / str(video_record["file"])
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if probe.returncode != 0:
                    raise RuntimeError(f"Explicit test thumbnail video probe failed: {probe.stderr.strip()}")
                video_duration = float(probe.stdout.strip())
                captured_at_value = metadata.get("captured_at_epoch_ms")
                if (
                    not isinstance(captured_at_value, (int, float))
                    or isinstance(captured_at_value, bool)
                    or not math.isfinite(captured_at_value)
                ):
                    raise RuntimeError("Explicit test thumbnail timestamp is invalid")
                captured_at_ms = float(captured_at_value)
                finalized_at_epoch_ms = finalized_at_by_suffix.get(video_attachment_suffix)
                if finalized_at_epoch_ms is None:
                    raise RuntimeError("Explicit test thumbnail finalized video timestamp is missing")
                video_start_epoch_ms = finalized_at_epoch_ms - video_duration * 1000
                timestamp = (captured_at_ms - video_start_epoch_ms) / 1000
                if not math.isfinite(timestamp) or timestamp < 0 or timestamp >= video_duration:
                    raise RuntimeError("Explicit test thumbnail timestamp is outside the completed video")
                thumbnail = "thumbnail.png"
                video_filter = (
                    f"scale={viewport['width']}:{viewport['height']}:flags=lanczos,"
                    f"crop={clip['width']}:{clip['height']}:{clip['x']}:{clip['y']},"
                    "scale=1280:800:flags=lanczos"
                )
                extraction = subprocess.run(
                    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path), "-ss", f"{timestamp:.3f}", "-frames:v", "1", "-vf", video_filter, str(dest / thumbnail)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if extraction.returncode != 0 or not (dest / thumbnail).is_file():
                    raise RuntimeError(f"Explicit test thumbnail video extraction failed: {extraction.stderr.strip()}")
                thumbnail_source = "video_frame"
            for item in proof_group:
                attachment_path = item.get("path")
                if not str(item.get("contentType") or "").startswith("video/") or not isinstance(attachment_path, str):
                    continue
                attachment_suffix = attachment_path.split("test-results/", 1)[-1]
                matches = [
                    record
                    for record in video_records
                    if str(record.get("source") or "").split("test-results/", 1)[-1] == attachment_suffix
                ]
                if len(matches) != 1:
                    raise RuntimeError("Playwright proof video artifact is missing or ambiguous")
                proof_video_file = str(matches[0].get("file") or "") or None
                break
            timeline_attachments = [
                item
                for item in proof_group
                if item.get("contentType") == "application/vnd.openmates.proof-timeline+json"
            ]
            if len(timeline_attachments) > 1:
                raise RuntimeError("Playwright proof result contains multiple timeline attachments")
            proof_frame_attachments: dict[str, dict[str, object]] = {}
            for item in proof_group:
                name = item.get("name")
                if item.get("contentType") != "image/png" or not isinstance(name, str) or not name.startswith(
                    "openmates-proof-frame-"
                ):
                    continue
                if name in proof_frame_attachments:
                    raise RuntimeError(f"Playwright proof result contains duplicate frame attachment: {name}")
                proof_frame_attachments[name] = item
            for attachment in timeline_attachments:
                proof_timeline_path = dest / "proof-timeline.json"
                body = attachment.get("body")
                attachment_path = attachment.get("path")
                if isinstance(body, str):
                    proof_timeline_path.write_bytes(base64.b64decode(body, validate=True))
                    break
                if not isinstance(attachment_path, str):
                    proof_timeline_path = None
                    continue
                attachment_name = Path(attachment_path).name
                sources = [path for path in artifact_files if path.name == attachment_name]
                if len(sources) != 1:
                    proof_timeline_path = None
                    continue
                shutil.copy2(sources[0], proof_timeline_path)
                break

            if proof_timeline_path is not None:
                timeline_payload = json.loads(proof_timeline_path.read_text(encoding="utf-8"))
                checkpoint_frames = timeline_payload.get("checkpoint_frames")
                if not isinstance(checkpoint_frames, list) or not checkpoint_frames:
                    raise RuntimeError("Spec proof timeline is missing checkpoint frame attachments")
                frames_dest = dest / "proof-frames"
                frames_dest.mkdir(parents=True, exist_ok=True)
                proof_video_duration: Optional[float] = None
                map_proof_timestamp: Optional[Callable[[object, str], float]] = None
                if timeline_payload.get("schema_version") == 2:
                    if not proof_video_file:
                        raise RuntimeError("Spec proof checkpoint video is missing")
                    probe = subprocess.run(
                        [
                            "ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(dest / proof_video_file),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if probe.returncode != 0:
                        raise RuntimeError(f"Spec proof video probe failed: {probe.stderr.strip()}")
                    proof_video_duration = float(probe.stdout.strip())
                    proof_video_record = next(
                        (record for record in video_records if record.get("file") == proof_video_file),
                        None,
                    )
                    if proof_video_record is None:
                        raise RuntimeError("Spec proof video source metadata is missing")
                    proof_video_suffix = str(proof_video_record.get("source") or "").split("test-results/", 1)[-1]
                    proof_finalized_at_epoch_ms = finalized_at_by_suffix.get(proof_video_suffix)
                    if proof_finalized_at_epoch_ms is None:
                        raise RuntimeError("Spec proof finalized video timestamp is missing")
                    proof_video_start_epoch_ms = proof_finalized_at_epoch_ms - proof_video_duration * 1000

                    def to_video_timestamp(value: object, label: str) -> float:
                        if (
                            not isinstance(value, (int, float))
                            or isinstance(value, bool)
                            or not math.isfinite(value)
                        ):
                            raise RuntimeError(f"Spec proof {label} timestamp is invalid")
                        timestamp = (float(value) - proof_video_start_epoch_ms) / 1000
                        if timestamp < 0 or timestamp >= proof_video_duration:
                            raise RuntimeError(f"Spec proof {label} timestamp is outside the completed video")
                        return timestamp

                    map_proof_timestamp = to_video_timestamp
                    for event in timeline_payload.get("events") or []:
                        if not isinstance(event, dict):
                            raise RuntimeError("Spec proof timeline event metadata is invalid")
                        if event.get("kind") == "action":
                            event["start_ms"] = round(to_video_timestamp(event.get("start_at_epoch_ms"), "action start") * 1000)
                            event["end_ms"] = round(to_video_timestamp(event.get("end_at_epoch_ms"), "action end") * 1000)
                        else:
                            event["at_ms"] = round(to_video_timestamp(event.get("captured_at_epoch_ms"), "event") * 1000)
                    for assertion in timeline_payload.get("assertion_results") or []:
                        if not isinstance(assertion, dict):
                            raise RuntimeError("Spec proof assertion result metadata is invalid")
                        assertion["at_ms"] = round(to_video_timestamp(
                            assertion.get("captured_at_epoch_ms"), "assertion"
                        ) * 1000)
                for frame_record in checkpoint_frames:
                    if not isinstance(frame_record, dict):
                        raise RuntimeError("Spec proof checkpoint frame metadata is invalid")
                    checkpoint = str(frame_record.get("checkpoint") or "")
                    attachment_name = str(frame_record.get("attachment_name") or "")
                    if not re.fullmatch(r"[A-Za-z0-9._-]+", checkpoint):
                        raise RuntimeError("Spec proof checkpoint frame has an invalid checkpoint id")
                    attachment = proof_frame_attachments.get(attachment_name)
                    target = frames_dest / f"{checkpoint}.png"
                    if attachment is None:
                        captured_at_ms = frame_record.get("captured_at_epoch_ms")
                        if map_proof_timestamp is None:
                            raise RuntimeError(f"Spec proof checkpoint frame timestamp is invalid: {checkpoint}")
                        timestamp = map_proof_timestamp(captured_at_ms, f"checkpoint {checkpoint}")
                        frame_record["at_ms"] = round(timestamp * 1000)
                        extraction = subprocess.run(
                            [
                                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                                "-i", str(dest / proof_video_file), "-ss", f"{timestamp:.3f}",
                                "-frames:v", "1", str(target),
                            ],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if extraction.returncode != 0 or not target.is_file():
                            raise RuntimeError(
                                f"Spec proof checkpoint video extraction failed: {checkpoint}: {extraction.stderr.strip()}"
                            )
                        frame_bytes = target.read_bytes()
                    else:
                        frame_body = attachment.get("body")
                        frame_path = attachment.get("path")
                        if isinstance(frame_body, str):
                            frame_bytes = base64.b64decode(frame_body, validate=True)
                        elif isinstance(frame_path, str):
                            attachment_basename = Path(frame_path).name
                            frame_sources = [path for path in artifact_files if path.name == attachment_basename]
                            if len(frame_sources) != 1:
                                raise RuntimeError(f"Spec proof checkpoint frame file is missing: {checkpoint}")
                            frame_bytes = frame_sources[0].read_bytes()
                        else:
                            raise RuntimeError(f"Spec proof checkpoint frame has no content: {checkpoint}")
                        expected_hash = frame_record.get("sha256")
                        actual_hash = f"sha256:{hashlib.sha256(frame_bytes).hexdigest()}"
                        if actual_hash != expected_hash:
                            raise RuntimeError(f"Spec proof checkpoint frame hash changed: {checkpoint}")
                        target.write_bytes(frame_bytes)
                    actual_hash = f"sha256:{hashlib.sha256(frame_bytes).hexdigest()}"
                    frame_record["sha256"] = actual_hash
                    frame_record["path"] = str(target.resolve())
                proof_timeline_path.write_text(
                    json.dumps(timeline_payload, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )

        meta = {
            "spec": spec,
            "slug": slug,
            "video_files": copied_videos,
            "video_records": video_records,
            "screenshot_files": copied_screenshots,
            "screenshot_records": screenshot_records,
            "thumbnail_file": thumbnail,
            "thumbnail_source": thumbnail_source,
            "proof_timeline_file": proof_timeline_path.name if proof_timeline_path else None,
            "proof_video_file": proof_video_file,
        }
        (dest / "artifact-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return str(proof_timeline_path) if proof_timeline_path else None

    @staticmethod
    def _spec_result_to_dict(r: SpecResult) -> dict:
        """Convert SpecResult to the dict format used in last-run.json."""
        d: dict = {
            "name": r.name,
            "status": r.status,
            "duration_seconds": r.duration_seconds,
        }
        if r.error:
            d["error"] = r.error
        if r.file:
            d["file"] = r.file
        if r.run_id:
            d["run_id"] = r.run_id
        if r.account:
            d["account"] = r.account
        if r.retries > 0:
            d["retries"] = r.retries
        if r.flaky:
            d["flaky"] = True
        if r.attempt_statuses:
            d["attempt_statuses"] = r.attempt_statuses
        if r.playwright_errors:
            d["playwright_errors"] = r.playwright_errors
        if r.steps:
            d["steps"] = r.steps
        if r.screenshot_paths:
            d["screenshot_paths"] = r.screenshot_paths
        if r.video_paths:
            d["video_paths"] = r.video_paths
        if r.video_artifact_name:
            d["video_artifact_name"] = r.video_artifact_name
        if r.proof_timeline_path:
            d["proof_timeline_path"] = r.proof_timeline_path
        if r.github_run_url:
            d["github_run_url"] = r.github_run_url
        if r.debug_artifacts:
            d["debug_artifacts"] = r.debug_artifacts
        if r.debug_output_summary:
            d["debug_output_summary"] = r.debug_output_summary
        if r.environment_blocker:
            d["environment_blocker"] = r.environment_blocker
        if r.test_key:
            d["test_key"] = r.test_key
        if r.parent_incident_key:
            d["parent_incident_key"] = r.parent_incident_key
        return d


# ---------------------------------------------------------------------------
# ResultAggregator
# ---------------------------------------------------------------------------

class ResultAggregator:
    """Merges results from all suites into the standard last-run.json format."""

    @staticmethod
    def to_dict(result: RunResult) -> dict:
        return {
            "run_id": result.run_id,
            "git_sha": result.git_sha,
            "git_branch": result.git_branch,
            "flags": result.flags,
            "duration_seconds": result.duration_seconds,
            "summary": result.summary,
            "suites": result.suites,
            "environment": result.environment,
        }

    @staticmethod
    def build_run_result(
        suites: dict[str, SuiteResult],
        run_id: str,
        git_sha: str,
        git_branch: str,
        environment: str,
        duration: float,
        flags: dict,
    ) -> RunResult:
        total = passed = failed = skipped = not_started = 0
        dispatch_error = timeout = result_unknown = 0
        infrastructure_incident = blocked_by_parent = 0
        suites_dict = {}

        for name, suite in suites.items():
            suite_dict = {
                "status": suite.status,
                "tests": suite.tests,
                "duration_seconds": suite.duration_seconds,
            }
            if suite.reason:
                suite_dict["reason"] = suite.reason
            suites_dict[name] = suite_dict

            for t in suite.tests:
                total += 1
                st = t.get("status", "")
                if st == "passed":
                    passed += 1
                elif st == "failed":
                    failed += 1
                elif st == "dispatch_error":
                    dispatch_error += 1
                elif st == "timeout":
                    timeout += 1
                elif st == "result_unknown":
                    result_unknown += 1
                elif st == "not_started":
                    not_started += 1
                elif st == "infrastructure_incident":
                    infrastructure_incident += 1
                elif st == "blocked_by_parent":
                    blocked_by_parent += 1
                else:
                    skipped += 1

        return RunResult(
            run_id=run_id,
            git_sha=git_sha,
            git_branch=git_branch,
            environment=environment,
            duration_seconds=round(duration, 1),
            summary={
                "total": total,
                "passed": passed,
                "failed": failed,
                "dispatch_error": dispatch_error,
                "timeout": timeout,
                "result_unknown": result_unknown,
                "executed_product_failed": failed + timeout + result_unknown,
                "infrastructure_incident": infrastructure_incident,
                "blocked_by_parent": blocked_by_parent,
                "skipped": skipped,
                "not_started": not_started,
            },
            suites=suites_dict,
            flags=flags,
        )

    @staticmethod
    def save(result: RunResult) -> None:
        """Save results to test-results/."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        data = ResultAggregator.to_dict(result)

        # Write timestamped run file
        ts = result.run_id.replace(":", "").replace("-", "")
        run_file = RESULTS_DIR / f"run-{ts}.json"
        _safe_write_json(run_file, data)

        # Write last-run.json (always overwritten)
        _safe_write_json(RESULTS_DIR / "last-run.json", data)
        (RESULTS_DIR / "last-run-progress.json").unlink(missing_ok=True)
        record_flake_history(data)
        try:
            source, workflow = _test_control_source_for_flags(result.flags)
            _record_unified_test_state(data, source=source, workflow=workflow)
        except Exception as exc:
            _log(f"Could not update unified test state: {exc}", "WARN")

        _log(f"Results saved to {run_file.name} and last-run.json")

    @staticmethod
    def save_progress(result: RunResult) -> None:
        """Persist partial results without replacing the final run artifact."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        data = ResultAggregator.to_dict(result)
        data["flags"] = {**dict(data.get("flags") or {}), "in_progress": True}
        _safe_write_json(RESULTS_DIR / "last-run-progress.json", data)
        try:
            source, workflow = _test_control_source_for_flags(data["flags"])
            _record_unified_test_state(data, source=source, workflow=workflow)
        except Exception as exc:
            _log(f"Could not update unified test progress: {exc}", "WARN")

    @staticmethod
    def load_failed_specs() -> list[str]:
        """Load previously failed spec files from last-run.json."""
        seeded_failed = os.getenv("OPENMATES_ONLY_FAILED_FILES_JSON")
        if seeded_failed:
            try:
                decoded = json.loads(seeded_failed)
            except json.JSONDecodeError:
                decoded = []
            if isinstance(decoded, list):
                return [str(item) for item in decoded if str(item)]

        last_run = RESULTS_DIR / "last-run.json"
        if not last_run.is_file():
            _log("No last-run.json found — cannot use --only-failed", "ERROR")
            sys.exit(1)

        with open(last_run) as f:
            data = json.load(f)

        failed = []
        for suite_data in data.get("suites", {}).values():
            if not isinstance(suite_data, dict):
                continue
            for t in suite_data.get("tests", []):
                if _is_problem_status(t.get("status", "")):
                    f_name = t.get("file", t.get("name", ""))
                    if f_name:
                        failed.append(f_name)
        return failed


# ---------------------------------------------------------------------------
# NotificationService
# ---------------------------------------------------------------------------

class NotificationService:
    """Sends email and Discord notifications and pushes to OpenObserve.

    Discord is a fallback notification channel added in OPE-76 to guarantee
    test run failures surface even when the email path (Brevo / internal API)
    silently breaks — which is exactly what happened with the 2026-04-06 nightly
    summary that never arrived. Email and Discord sends are independent: a
    failure in one must never block the other.
    """

    def __init__(self) -> None:
        self.dot_env = _read_env_file()
        self.coordinate_runtime = True
        self.admin_email = _get_env("ADMIN_NOTIFY_EMAIL", self.dot_env)
        self.internal_token = _get_env("INTERNAL_API_SHARED_TOKEN", self.dot_env)
        self.brevo_api_key = _get_env("BREVO_API_KEY", self.dot_env)
        self.internal_api_url = _get_env(
            "INTERNAL_API_URL", self.dot_env, "http://localhost:8000"
        ).rstrip("/")
        # Discord webhooks — one per cron channel so each can be muted/routed
        # independently in Discord. Optional — unset means "skip Discord entirely"
        # for that channel (preserves no-Discord behavior on unconfigured machines).
        # See OPE-349 for the per-channel split rationale.
        self.discord_webhook_url = _get_env(
            "DISCORD_WEBHOOK_DEV_NIGHTLY", self.dot_env
        )
        self.discord_webhook_dev_smoke = _get_env(
            "DISCORD_WEBHOOK_DEV_SMOKE", self.dot_env
        )
        self.discord_webhook_prod_smoke = _get_env(
            "DISCORD_WEBHOOK_PROD_SMOKE", self.dot_env
        )

    def send_start_email(self, git_sha: str, git_branch: str, environment: str) -> None:
        """Notify admin that a test run has started."""
        if not self.admin_email:
            _log("ADMIN_NOTIFY_EMAIL not set — skipping start email", "WARN")
            return

        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        subject = f"[OpenMates] Test run started ({environment})"
        body = (
            f"Test run started at {started_at}\n"
            f"Environment: {environment}\n"
            f"Git: {git_sha}@{git_branch}\n"
            f"Trigger: {'Scheduled (daily)' if os.environ.get('DAILY_RUN_ENVIRONMENT') else 'Manual'}"
        )

        self._send_email(subject, body, "dispatch-test-start-email", {
            "recipient_email": self.admin_email,
            "environment": environment,
            "trigger_type": "Scheduled (daily)" if os.environ.get("DAILY_RUN_ENVIRONMENT") else "Manual",
            "git_sha": git_sha,
            "git_branch": git_branch,
            "started_at": started_at,
        })

    def send_daily_discord_status(
        self,
        git_sha: str,
        git_branch: str,
        environment: str,
        run_id: str,
        elapsed_seconds: float,
        phase: str,
        *,
        started: bool = False,
    ) -> None:
        """Post a non-fatal start or running status update for the daily run."""
        if not self.discord_webhook_url:
            _log("DISCORD_WEBHOOK_DEV_NIGHTLY not set — skipping daily Discord status", "DEBUG")
            return

        elapsed_minutes = max(0, int(elapsed_seconds // 60))
        title = (
            f"▶️ {environment} nightly — started"
            if started
            else f"⏳ {environment} nightly — still running"
        )
        description = (
            f"**Run ID:** `{run_id}`\n"
            f"**Phase:** {phase}\n"
            f"**Elapsed:** {elapsed_minutes}m\n"
            f"**Git:** `{git_sha[:8]}@{git_branch}`"
        )
        payload = {
            "username": "OpenMates Server",
            "avatar_url": "https://openmates.org/favicon.png",
            "embeds": [{"title": title, "description": description, "color": 0x3B82F6}],
        }
        try:
            request = urllib.request.Request(
                self.discord_webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "OpenMates-TestRunner/1.0 (https://github.com/glowingkitty/OpenMates)",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            _log("Daily Discord start posted" if started else "Daily Discord 30-minute status posted")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace") if error.fp else ""
            _log(f"Daily Discord status POST failed: HTTP {error.code} — {body[:300]}", "ERROR")
        except Exception as error:
            _log(f"Daily Discord status POST failed: {error}", "ERROR")

    def send_daily_skip_notification(
        self,
        git_sha: str,
        git_branch: str,
        environment: str,
        run_id: str,
        reason: str,
    ) -> None:
        """Post a visible terminal status when no daily tests are dispatched."""
        if not self.discord_webhook_url:
            _log("DISCORD_WEBHOOK_DEV_NIGHTLY not set — skipping daily skip notification", "DEBUG")
            return

        payload = {
            "username": "OpenMates Server",
            "avatar_url": "https://openmates.org/favicon.png",
            "embeds": [{
                "title": f"⏭️ {environment} nightly — skipped",
                "description": (
                    f"**Reason:** {reason}\n"
                    "**Tests dispatched:** none\n"
                    f"**Run ID:** `{run_id}`\n"
                    f"**Git:** `{git_sha[:8]}@{git_branch}`"
                ),
                "color": 0xF59E0B,
            }],
        }
        try:
            request = urllib.request.Request(
                self.discord_webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "OpenMates-TestRunner/1.0 (https://github.com/glowingkitty/OpenMates)",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            _log("Daily Discord skip notification posted")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace") if error.fp else ""
            _log(f"Daily Discord skip notification POST failed: HTTP {error.code} — {body[:300]}", "ERROR")
        except Exception as error:
            _log(f"Daily Discord skip notification POST failed: {error}", "ERROR")

    def send_summary_email(self, result: RunResult) -> bool:
        """Send test summary email after run completes, plus Discord fallback.

        The email and Discord sends are INDEPENDENT: neither awaits the other
        and neither's failure aborts the other. This is the whole point of the
        dual-channel notification pattern.
        """
        s = result.summary
        problem_count = _problem_count(s)
        status = "All tests passed" if problem_count == 0 else _problem_summary_label(s)
        subject = f"[OpenMates] {status} ({result.environment})"

        email_receipt = {"configured": False, "status": "unconfigured", "transport": "none"}
        if not self.admin_email:
            _log("ADMIN_NOTIFY_EMAIL not set — skipping summary email", "WARN")
        else:
            # Build HTML email body
            html = self._build_summary_html(result)
            text = self._build_summary_text(result)

            payload = self._build_internal_api_payload(result)
            if self.brevo_api_key:
                try:
                    provider_accepted = bool(self._send_via_brevo(subject, text, html))
                except Exception as exc:
                    provider_accepted = False
                    _log(f"Brevo summary notification failed: {type(exc).__name__}", "ERROR")
                if provider_accepted:
                    email_receipt = {"configured": True, "status": "provider_accepted", "transport": "brevo"}
                elif self.internal_token:
                    try:
                        queued = bool(self._send_via_internal_api("dispatch-test-summary-email", payload))
                    except Exception as exc:
                        queued = False
                        _log(f"Internal summary queue failed: {type(exc).__name__}", "WARN")
                    email_receipt = {
                        "configured": True,
                        "status": "queued_unconfirmed" if queued else "failed",
                        "transport": "internal_api",
                    }
                else:
                    email_receipt = {"configured": True, "status": "failed", "transport": "brevo"}
            elif self.internal_token:
                try:
                    queued = bool(self._send_via_internal_api("dispatch-test-summary-email", payload))
                except Exception as exc:
                    queued = False
                    _log(f"Internal summary queue failed: {type(exc).__name__}", "WARN")
                email_receipt = {
                    "configured": True,
                    "status": "queued_unconfirmed" if queued else "failed",
                    "transport": "internal_api",
                }
            else:
                _log("No email credentials available — skipping summary email", "WARN")

        try:
            discord_delivered = bool(self._send_summary_to_discord(result))
        except Exception as exc:
            discord_delivered = False
            _log(f"Discord summary notification failed: {type(exc).__name__}", "ERROR")
        discord_configured = bool(self.discord_webhook_url)
        discord_receipt = {
            "configured": discord_configured,
            "status": "provider_accepted" if discord_delivered else "failed" if discord_configured else "unconfigured",
            "transport": "webhook" if discord_configured else "none",
        }

        result.flags["email_delivered"] = email_receipt["status"] == "provider_accepted"
        result.flags["discord_delivered"] = discord_delivered
        result.flags["notification_channels"] = {
            "email": email_receipt,
            "discord": discord_receipt,
        }

        try:
            self.send_urgent_essential_failure_email(result)
        except Exception as exc:
            _log(f"Urgent essential-flow notification failed: {type(exc).__name__}", "ERROR")
        configured_receipts = [email_receipt, discord_receipt]
        return all(
            receipt["status"] == "provider_accepted"
            for receipt in configured_receipts
            if receipt["configured"]
        ) and any(receipt["configured"] for receipt in configured_receipts)

    def send_urgent_essential_failure_email(self, result: RunResult) -> None:
        """Send a separate admin email when signup, login, or chat flow fails."""
        essential_failed = self._essential_failed_tests(result)
        if not essential_failed:
            return

        if not self.admin_email:
            _log("ADMIN_NOTIFY_EMAIL not set — skipping urgent essential-flow email", "WARN")
            return

        urgent_result = RunResult(
            run_id=result.run_id,
            git_sha=result.git_sha,
            git_branch=result.git_branch,
            environment=result.environment,
            duration_seconds=result.duration_seconds,
            summary={
                "total": len(essential_failed),
                "passed": 0,
                "failed": len(essential_failed),
                "dispatch_error": 0,
                "timeout": 0,
                "result_unknown": 0,
                "skipped": 0,
                "not_started": 0,
            },
            suites=self._essential_failed_suites(result, essential_failed),
        )

        if self.brevo_api_key:
            html = self._build_summary_html(urgent_result)
            text = self._build_summary_text(urgent_result)
            self._send_via_brevo(ESSENTIAL_FAILURE_SUBJECT, text, html)
        elif self.internal_token:
            payload = self._build_internal_api_payload(urgent_result)
            payload["subject_override"] = ESSENTIAL_FAILURE_SUBJECT
            self._send_via_internal_api("dispatch-test-summary-email", payload)
        else:
            _log("No email credentials available — skipping urgent essential-flow email", "WARN")

    def send_prod_failure_email(self, result: RunResult, mode_label: str, run_url: Optional[str] = None) -> None:
        """Send a production smoke failure email from the dev-server runner."""
        if _problem_count(result.summary) == 0:
            return
        if not self.admin_email:
            _log("ADMIN_NOTIFY_EMAIL not set — cannot send prod smoke failure email", "ERROR")
            return

        subject = f"[OpenMates] {mode_label} FAILED"
        text = self._build_summary_text(result)
        if run_url:
            text = f"{text}\nGitHub Actions run: {run_url}\n"
        html = self._build_summary_html(result)
        if run_url:
            html = html.replace(
                "</body></html>",
                f'<p><a href="{run_url}" style="color:#60a5fa">View GitHub Actions run</a></p></body></html>',
            )

        if self.brevo_api_key:
            self._send_via_brevo(subject, text, html)
        elif self.internal_token:
            payload = self._build_internal_api_payload(result)
            payload["subject_override"] = subject
            payload["run_url"] = run_url
            self._send_via_internal_api("dispatch-test-summary-email", payload)
        else:
            _log("No email credentials available — cannot send prod smoke failure email", "ERROR")

    def push_to_openobserve(self, result: RunResult) -> None:
        """Push test run summary to OpenObserve via internal API."""
        if not self.internal_token:
            _log("INTERNAL_API_SHARED_TOKEN not set — skipping OpenObserve push", "WARN")
            return

        payload = self._build_openobserve_payload(result)
        url = f"{self.internal_api_url}/internal/openobserve/push-test-run"

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": self.internal_token,
            }, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            _log("OpenObserve push succeeded")
        except Exception as e:
            _log(f"OpenObserve push failed: {e} (non-fatal)", "WARN")

    def split_results(self) -> None:
        """Split last-run.json into passed/failed JSON files (reuses _daily_runner_helper)."""
        helper = PROJECT_ROOT / "scripts" / "_daily_runner_helper.py"
        if helper.is_file():
            subprocess.run(
                [sys.executable, str(helper), "split-results"],
                env={**os.environ, "RESULTS_DIR": str(RESULTS_DIR)},
            )

    # --- Private methods ---

    def _send_email(self, subject: str, text: str, endpoint: str, payload: dict) -> bool:
        """Send a non-summary email through the best configured transport."""
        if getattr(self, "brevo_api_key", ""):
            return self._send_via_brevo(subject, text)
        if getattr(self, "internal_token", ""):
            return self._send_via_internal_api(endpoint, payload)
        _log("No email credentials available — skipping email", "WARN")
        return False

    def _send_via_brevo(self, subject: str, text: str, html: Optional[str] = None) -> bool:
        """Send email directly via Brevo API."""
        payload = {
            "sender": {"name": "OpenMates", "email": "noreply@openmates.org"},
            "to": [{"email": self.admin_email}],
            "subject": subject,
            "textContent": text,
            "headers": {
                "Precedence": "bulk",
                "Auto-Submitted": "auto-generated",
            },
        }
        if html:
            payload["htmlContent"] = html

        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(BREVO_API_URL, data=body, headers={
                "accept": "application/json",
                "api-key": self.brevo_api_key,
                "content-type": "application/json",
            }, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            _log(f"Email sent via Brevo to {self.admin_email}")
            return True
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            _log(f"Brevo email failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
        except Exception as e:
            _log(f"Brevo email failed: {e}", "ERROR")
        return False

    def _is_essential_test(self, test_entry: dict, suite_name: str = "") -> bool:
        searchable = " ".join(
            str(test_entry.get(key, ""))
            for key in ("file", "name", "suite")
        )
        searchable = f"{suite_name} {searchable}".lower()
        return any(keyword in searchable for keyword in ESSENTIAL_TEST_KEYWORDS)

    def _essential_failed_tests(self, result: RunResult) -> list[tuple[str, dict]]:
        essential_failed = []
        for suite_name, suite_data in result.suites.items():
            for test_entry in suite_data.get("tests", []):
                if _is_problem_status(test_entry.get("status", "")) and self._is_essential_test(test_entry, suite_name):
                    essential_failed.append((suite_name, test_entry))
        return essential_failed

    def _essential_failed_suites(
        self,
        result: RunResult,
        essential_failed: list[tuple[str, dict]],
    ) -> dict:
        suites: dict = {}
        for suite_name, test_entry in essential_failed:
            if suite_name not in suites:
                original_suite = result.suites.get(suite_name, {})
                suites[suite_name] = {
                    **original_suite,
                    "status": "failed",
                    "tests": [],
                }
            suites[suite_name]["tests"].append(test_entry)
        return suites

    def _send_summary_to_discord(
        self,
        result: RunResult,
        webhook_url: Optional[str] = None,
        mode_label: str = "nightly",
        post_on_success: bool = True,
        env_var_name: str = "DISCORD_WEBHOOK_DEV_NIGHTLY",
        run_url: Optional[str] = None,
        screenshots: Optional[list[Path]] = None,
        state_file: Optional[Path] = None,
        suite_name_for_dedup: Optional[str] = None,
    ) -> bool:
        """Post a test run summary to a Discord webhook.

        Independent of the email path — catches and logs all errors rather than
        raising, so a dead webhook URL or network hiccup never blocks the
        cron runner. Uses stdlib urllib to avoid introducing an httpx dependency.

        Args:
            result: Aggregated run result.
            webhook_url: Discord webhook to post to. Defaults to the nightly
                webhook for backwards compatibility with the existing daily flow.
            mode_label: Short label for the embed title (e.g. "nightly",
                "dev hourly", "prod hourly"). Defaults to "nightly".
            post_on_success: When False, the helper short-circuits if there
                are zero failures — used by the hourly modes so a green run
                stays silent and we don't flood Discord.
            env_var_name: Name of the env var, only used in the "missing
                webhook" log line so the operator knows what to set.
        """
        # Backwards-compat: when no explicit webhook is passed, fall back to
        # the original nightly webhook so existing --daily callers behave
        # exactly as before this refactor.
        if webhook_url is None:
            webhook_url = self.discord_webhook_url

        if not webhook_url:
            _log(f"{env_var_name} not set — skipping Discord summary", "DEBUG")
            return False

        s = result.summary
        problem_count = _problem_count(s)
        all_passed = problem_count == 0

        # Hourly modes silence green runs to avoid channel flooding.
        if all_passed and not post_on_success:
            _log(f"Discord ({mode_label}): green run, suppressed (post_on_success=False)")
            return True

        # Dedup: skip the summary entirely on a repeat tick where the
        # exact same set of tests is failing with the exact same root
        # cause AND no recoveries have happened. The per-test detail
        # messages get PATCHed in place by send_per_test_md_messages so
        # the operator already sees the latest screenshots/timings; a
        # fresh summary post would just be channel noise.
        #
        # State layout: state["summary"] = {
        #   "hash": "<sha>", "last_seen": "<iso>", "suppressed_count": N
        # }
        # After RENOTIFY_AFTER_TICKS consecutive suppressed ticks we re-post
        # a "still failing" reminder so the channel doesn't go silent for
        # hours during a prolonged outage.
        new_summary_hash: Optional[str] = None
        is_renotify = False
        if state_file is not None and suite_name_for_dedup is not None:
            current_keys: dict[str, str] = {}
            for sname, sdata in result.suites.items():
                for t in (sdata or {}).get("tests", []):
                    if not _is_problem_status(t.get("status", "")):
                        continue
                    current_keys[_compute_test_key(sname, t)] = _compute_error_hash(t)
            new_summary_hash = _compute_failure_set_hash(current_keys)
            existing_state = _load_discord_state(state_file)
            prev = existing_state.get("summary", {}) or {}
            prev_hash = prev.get("hash", "")
            prev_suppressed = int(prev.get("suppressed_count", 0))
            # Same failure set as last tick: either suppress or re-notify.
            if (
                new_summary_hash
                and new_summary_hash == prev_hash
                and not all_passed
            ):
                new_suppressed = prev_suppressed + 1
                if new_suppressed < RENOTIFY_AFTER_TICKS:
                    # Still within the quiet window — suppress and save count.
                    if state_file is not None:
                        try:
                            s_state = _load_discord_state(state_file)
                            s_state.setdefault("summary", {})["suppressed_count"] = new_suppressed
                            _save_discord_state(state_file, s_state)
                        except Exception as e:
                            _log(f"Discord summary state write failed: {e}", "WARN")
                    _log(
                        f"Discord ({mode_label}): same failure set "
                        f"({new_summary_hash}) — summary suppressed "
                        f"({new_suppressed}/{RENOTIFY_AFTER_TICKS - 1})"
                    )
                    return True
                else:
                    # Quiet window exhausted — let the post through as a
                    # "still failing" reminder and reset the counter.
                    is_renotify = True

        # Red for failures, green for all-passed — matches the email HTML.
        color = 0x22C55E if all_passed else 0xEF4444
        if is_renotify:
            title_emoji = "⚠️"
            # Compute elapsed time since the last summary post.
            elapsed_h = ""
            try:
                last_post = (existing_state.get("summary", {}) or {}).get("last_seen", "")
                if last_post:
                    last_dt = datetime.strptime(last_post, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    elapsed_sec = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    elapsed_h = f", still failing after ~{max(1, int(elapsed_sec / 3600))}h"
            except Exception:
                elapsed_h = ", still failing"
            title = (
                f"{title_emoji} {result.environment} {mode_label} — "
                f"{_problem_summary_label(s)}{elapsed_h}"
            )
        else:
            title_emoji = "✅" if all_passed else "❌"
            status_suffix = _problem_summary_label(s)
            title = f"{title_emoji} {result.environment} {mode_label} — {status_suffix}"

        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        description_parts = [
            f"**Total:** {s['total']}   **Passed:** {s['passed']}   "
            f"**Failed:** {s['failed']}   **Dispatch errors:** {s.get('dispatch_error', 0)}   "
            f"**Skipped:** {s['skipped']}",
            f"**Duration:** {dur_min}m {dur_sec}s   **Git:** `{result.git_sha[:8]}@{result.git_branch}`",
        ]
        cache_backfill_line = _cache_backfill_notification_line(result)
        if cache_backfill_line:
            description_parts.append(f"**{cache_backfill_line}**")
        if run_url:
            description_parts.append(f"**Run:** [GitHub Actions]({run_url})")
        description = _fit_discord_description(description_parts)

        embed: dict = {
            "title": title,
            "description": description,
            "color": color,
        }
        if run_url:
            embed["url"] = run_url

        embeds = [embed]
        if problem_count:
            failure_embeds = _build_discord_failure_embeds(result.suites, color)
            embeds.extend(_limit_discord_failure_embeds(failure_embeds, color))
        embeds = _fit_discord_embed_total(embeds)

        payload = {
            "username": "OpenMates Server",
            "avatar_url": "https://openmates.org/favicon.png",
            "embeds": embeds,
        }

        # Collect attachments. Each path on disk is read into memory once,
        # capped at DISCORD_MAX_ATTACHMENT_BYTES per file and DISCORD_MAX_ATTACHMENTS
        # total. Files that don't exist or are oversized are silently skipped
        # so a single bad path can't break the whole notification path.
        attachments: list[tuple[str, bytes, str]] = []
        if screenshots:
            for idx, src in enumerate(screenshots):
                if len(attachments) >= DISCORD_MAX_ATTACHMENTS:
                    break
                try:
                    src_path = Path(src)
                    if not src_path.is_file():
                        continue
                    size = src_path.stat().st_size
                    if size > DISCORD_MAX_ATTACHMENT_BYTES:
                        _log(
                            f"Discord: skipping {src_path.name} "
                            f"({size // 1024} KB > {DISCORD_MAX_ATTACHMENT_BYTES // 1024} KB cap)",
                            "WARN",
                        )
                        continue
                    with open(src_path, "rb") as fh:
                        content = fh.read()
                    # filename must be unique across the multipart so prefix
                    # with the spec-folder name (the parent dir holds the spec name).
                    parent = src_path.parent.name or "screenshot"
                    safe_name = f"{parent}-{src_path.name}".replace("/", "-")
                    attachments.append((f"files[{idx}]", content, safe_name))
                except Exception as e:
                    _log(f"Discord: failed to read screenshot {src}: {e}", "WARN")
                    continue

        # Build the request body — JSON when no attachments, multipart otherwise.
        # Identify ourselves with a non-default User-Agent: Cloudflare (Discord's
        # edge) blocks the default `Python-urllib/*` UA with error 1010. See OPE-349.
        ua = "OpenMates-TestRunner/1.0 (https://github.com/glowingkitty/OpenMates)"
        try:
            if attachments:
                body, content_type = _build_multipart_body(payload, attachments)
                req = urllib.request.Request(
                    webhook_url,
                    data=body,
                    headers={"Content-Type": content_type, "User-Agent": ua},
                    method="POST",
                )
            else:
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    webhook_url,
                    data=body,
                    headers={"Content-Type": "application/json", "User-Agent": ua},
                    method="POST",
                )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            attached_note = f" (+{len(attachments)} screenshot(s))" if attachments else ""
            _log(f"Discord summary posted ({mode_label}){attached_note}")
            # Persist the new summary fingerprint so the next tick can
            # detect "nothing changed" and skip. Best-effort: a write
            # failure is logged but never breaks the cron run.
            if state_file is not None and new_summary_hash is not None:
                try:
                    persisted = _load_discord_state(state_file)
                    persisted["summary"] = {
                        "hash": new_summary_hash,
                        "last_seen": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "suppressed_count": 0,  # reset after every actual post
                    }
                    _save_discord_state(state_file, persisted)
                except Exception as state_err:
                    _log(f"Discord summary state write failed: {state_err}", "WARN")
            return True
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            _log(f"Discord summary POST failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
        except Exception as e:
            _log(f"Discord summary POST failed: {e}", "ERROR")
        return False

    def post_dry_run_notify(
        self,
        webhook_url: str,
        mode_label: str,
        env_var_name: str,
    ) -> bool:
        """Post a one-shot ✅ test embed to verify a webhook is wired correctly.

        Returns True on success, False otherwise. Never raises — same fallback
        contract as `_send_summary_to_discord`.
        """
        if not webhook_url:
            _log(f"{env_var_name} not set — cannot dry-run notify", "ERROR")
            return False

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "username": "OpenMates Server",
            "avatar_url": "https://openmates.org/favicon.png",
            "embeds": [
                {
                    "title": f"✅ {mode_label} — webhook test",
                    "description": (
                        f"This is a `--dry-run-notify` smoke test. If you can read "
                        f"this in the right channel, the webhook is wired up.\n\n"
                        f"**When:** `{ts}`\n"
                        f"**Env var:** `{env_var_name}`"
                    ),
                    "color": 0x22C55E,
                }
            ],
        }
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    # See _send_summary_to_discord — Cloudflare blocks the
                    # default Python-urllib UA with error 1010 (OPE-349).
                    "User-Agent": "OpenMates-TestRunner/1.0 (https://github.com/glowingkitty/OpenMates)",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            _log(f"Dry-run notify posted to {env_var_name}", "OK")
            return True
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            _log(f"Dry-run notify failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
            return False
        except Exception as e:
            _log(f"Dry-run notify failed: {e}", "ERROR")
            return False

    # ─── Discord per-test MD-style messages (OPE-349) ──────────────────────
    #
    # In addition to the lightweight summary embed (`_send_summary_to_discord`)
    # we send ONE message per failed test that mirrors the structure of the
    # per-test markdown reports in test-results/reports/failed/*.md:
    #
    #   • Embeds are split into "step groups" — each group is N step
    #     checkpoints followed by 1 screenshot. The checkpoints become the
    #     embed's `description`; the screenshot becomes the embed's `image`.
    #     This gives a visual flow of "text → image → text → image" because
    #     each embed renders as its own card stacked vertically in Discord.
    #   • The final embed (red) carries the failure error message + the
    #     test-failed-*.png Playwright wrote at exit time.
    #   • Crucially, embeds do NOT share a `url` — that would cause Discord
    #     to "gallery-merge" them (descriptions stack at the top, images
    #     collapse to a grid below), defeating the interleaving.
    #
    # Source data lives under test-results/screenshots/current/<spec-name>/:
    #   step-log.json     — ordered list of {type: checkpoint|screenshot, ...}
    #   <step>.png        — inline step screenshots referenced by step-log
    #   test-failed-*.png — final failure shots Playwright took on exit
    #
    # Discord limits respected:
    #   • ≤ 10 embeds per message  → MD_DISCORD_MAX_EMBEDS = 10
    #   • ≤ 10 attachments         → matches embed count
    #   • ≤ 4096 chars per description (we truncate)
    #   • ≤ 25 MB total body, 2 MB per file (DISCORD_MAX_ATTACHMENT_BYTES)

    MD_DISCORD_MAX_EMBEDS = 10
    MD_NOISE_PREFIXES = ("Captured step screenshot", "Archived prior screenshots")

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Strip ANSI escape sequences (Playwright wraps locator names in
        terminal colour codes that render as garbage in Discord)."""
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def _build_md_style_test_message(
        self,
        test: dict,
        suite_name: str,
        run_id: str,
        screenshots_root: Path,
    ) -> tuple[list[dict], list[tuple[str, bytes, str]]]:
        """Build the per-test embeds + multipart files for one failed test.

        Returns `(embeds, files)`. Caller is responsible for posting them
        via _post_discord_multipart.

        Returns empty lists if there's nothing useful to send (no
        screenshots and no step log) — caller can fall back to skipping
        this test entirely.
        """
        name = test.get("file") or test.get("name", "unknown")
        spec_name = name.replace(".spec.ts", "").replace(".test.ts", "")
        spec_dir = screenshots_root / spec_name

        # Try to load the step log; if absent we'll fall back to filename
        # parsing in _build_steps_from_filenames.
        step_log: list[dict] = []
        step_log_path = spec_dir / "step-log.json"
        if step_log_path.is_file():
            try:
                with open(step_log_path) as f:
                    step_log = json.load(f) or []
            except (json.JSONDecodeError, OSError):
                step_log = []

        # Resolve absolute paths for screenshot_paths (which are stored
        # relative to RESULTS_DIR in the test dict).
        screenshot_paths_abs: list[Path] = []
        for ss_rel in test.get("screenshot_paths", []) or []:
            p = RESULTS_DIR / ss_rel
            if p.is_file():
                screenshot_paths_abs.append(p)

        # Bail out if we have neither a step log nor any screenshots.
        if not step_log and not screenshot_paths_abs:
            return [], []

        # Group: each group = (list of checkpoint strings, optional screenshot Path).
        groups: list[dict] = []
        current_checkpoints: list[str] = []
        display_num = 0

        if step_log:
            filtered = [
                e for e in step_log
                if not (
                    e.get("type") == "checkpoint"
                    and e.get("message", "").startswith(self.MD_NOISE_PREFIXES)
                )
            ]
            for entry in filtered:
                et = entry.get("type", "checkpoint")
                msg = entry.get("message", "")
                if et == "checkpoint":
                    display_num += 1
                    current_checkpoints.append(f"`{display_num:>2}.` ✅ {msg}")
                elif et == "screenshot":
                    screenshot_file = entry.get("screenshot", "")
                    if screenshot_file:
                        p = spec_dir / screenshot_file
                        if p.is_file():
                            groups.append({
                                "checkpoints": current_checkpoints,
                                "screenshot": (msg or screenshot_file, p),
                            })
                            current_checkpoints = []
            if current_checkpoints:
                groups.append({"checkpoints": current_checkpoints, "screenshot": None})
        else:
            # No step log — synthesize groups from non-failure screenshot
            # filenames so the operator still gets visual context. Each
            # screenshot becomes its own group with a single derived caption.
            for p in screenshot_paths_abs:
                fname = p.name.lower()
                if fname.startswith("test-failed") or fname.startswith("test-finished"):
                    continue  # those go in the final failure embed
                caption = re.sub(r"^[a-z]+-?\d*-", "", p.stem).replace("-", " ")
                display_num += 1
                groups.append({
                    "checkpoints": [f"`{display_num:>2}.` ✅ {caption}"],
                    "screenshot": (caption, p),
                })

        # Mark the last checkpoint as ❌ for failed or infrastructure-error tests.
        if _is_problem_status(test.get("status", "")) and groups:
            for g in reversed(groups):
                if g["checkpoints"]:
                    last = g["checkpoints"][-1]
                    g["checkpoints"][-1] = last.replace(" ✅ ", " ❌ ", 1)
                    break

        # Find any test-failed-*.png screenshots (final failure state).
        failure_pngs = [
            p for p in screenshot_paths_abs
            if p.name.lower().startswith("test-failed")
        ]
        # Also pick them up directly from the spec dir if they're not
        # serialized into screenshot_paths (some workflows skip the relpath).
        if not failure_pngs and spec_dir.is_dir():
            failure_pngs = sorted(spec_dir.glob("test-failed-*.png"))

        # Trim groups to fit the per-message embed cap, reserving 1 slot for
        # the final failure embed (if any). When there are too many groups,
        # collapse the oldest checkpoints into a single text-only opening
        # embed so the operator still sees the early steps.
        failure_slot = 1 if failure_pngs else 0
        group_budget = self.MD_DISCORD_MAX_EMBEDS - failure_slot
        if len(groups) > group_budget:
            keep = groups[-(group_budget - 1):]
            dropped = groups[: -(group_budget - 1)]
            collapsed: list[str] = []
            for g in dropped:
                collapsed.extend(g["checkpoints"])
            collapsed.append(f"*…{len(dropped)} earlier step group(s) collapsed for length…*")
            groups = [{"checkpoints": collapsed, "screenshot": None}] + keep

        # Build embeds + multipart file fields.
        embeds: list[dict] = []
        files: list[tuple[str, bytes, str]] = []
        status = test.get("status", "unknown")
        # Pull a sensible error string out of the test dict (preferring the
        # first structured Playwright error if present).
        pw_errors = test.get("playwright_errors") or []
        error_msg = ""
        if pw_errors:
            error_msg = (pw_errors[0].get("message", "") or "").strip()
        if not error_msg:
            error_msg = (test.get("error") or "").strip()
        error_msg = self._strip_ansi(error_msg)

        for gi, g in enumerate(groups):
            chunks: list[str] = []
            if gi == 0:
                status_icon = "❌" if status == "failed" else "⚠️"
                chunks.append(f"## {status_icon} {name} — {status.upper()}")
                chunks.append(f"*Suite: {suite_name}   |   Run: {run_id}*")
                chunks.append("")
            chunks.extend(g["checkpoints"])
            description = "\n".join(chunks)
            if len(description) > 4000:
                description = description[:3997] + "..."

            # Last (text-side) embed gets the red colour to mark where the
            # failure happened. Earlier embeds get amber so they read as
            # "in progress" up until the failure point.
            is_last_text = gi == len(groups) - 1
            color = 0xEF4444 if is_last_text and status == "failed" else 0xFB923C
            embed: dict = {"description": description, "color": color}

            if g["screenshot"]:
                caption, src_path = g["screenshot"]
                try:
                    size = src_path.stat().st_size
                    if size <= DISCORD_MAX_ATTACHMENT_BYTES:
                        idx = len(files)
                        safe_name = f"step-{gi:02d}-{src_path.name}".replace("/", "-")
                        files.append((f"files[{idx}]", src_path.read_bytes(), safe_name))
                        embed["image"] = {"url": f"attachment://{safe_name}"}
                except OSError:
                    pass

            embeds.append(embed)

        # Final failure embed: error message + test-failed-*.png at the bottom.
        if failure_pngs and len(embeds) < self.MD_DISCORD_MAX_EMBEDS:
            fp = failure_pngs[0]
            chunks = []
            if error_msg:
                err = error_msg if len(error_msg) <= 1500 else error_msg[:1497].rstrip() + "..."
                err = err.replace("```", "ʼʼʼ")
                chunks.append("**💥 Final state — error:**")
                chunks.append("```")
                chunks.append(err)
                chunks.append("```")
            else:
                chunks.append("**💥 Final state**")

            embed = {"description": "\n".join(chunks), "color": 0xEF4444}
            try:
                if fp.stat().st_size <= DISCORD_MAX_ATTACHMENT_BYTES:
                    idx = len(files)
                    safe_name = f"failure-{fp.name}"
                    files.append((f"files[{idx}]", fp.read_bytes(), safe_name))
                    embed["image"] = {"url": f"attachment://{safe_name}"}
            except OSError:
                pass
            embeds.append(embed)

        return embeds, files

    def _post_discord_multipart(
        self,
        webhook_url: str,
        embeds: list[dict],
        files: list[tuple[str, bytes, str]],
        return_message_id: bool = False,
    ) -> "bool | Optional[str]":
        """POST a multipart Discord message with retry-on-429.

        When `return_message_id=False` (default — backwards compatible),
        returns True on success / False on failure.

        When `return_message_id=True`, returns the Discord `message.id`
        string on success or None on failure. The webhook URL is augmented
        with `?wait=true` so Discord blocks until the message is created
        and returns its full JSON (we need the id to PATCH it later for
        the dedup workflow).

        Never raises — same fallback contract as the other Discord
        helpers. Reads `Retry-After` on 429 and retries once.
        """
        failure_return = None if return_message_id else False
        if not webhook_url or not embeds:
            return failure_return

        payload = {
            "username": "OpenMates Server",
            "avatar_url": "https://openmates.org/favicon.png",
            "embeds": embeds,
        }
        body, content_type = _build_multipart_body(payload, files)
        ua = "OpenMates-TestRunner/1.0 (https://github.com/glowingkitty/OpenMates)"

        # When the caller wants the message id back we must append
        # ?wait=true so Discord blocks until the message exists and returns
        # the full message object (otherwise we get a 204 No Content).
        post_url = webhook_url
        if return_message_id and "?wait=" not in post_url:
            sep = "&" if "?" in post_url else "?"
            post_url = f"{post_url}{sep}wait=true"

        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    post_url, data=body,
                    headers={"Content-Type": content_type, "User-Agent": ua},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                if return_message_id:
                    try:
                        msg = json.loads(raw.decode("utf-8")) if raw else {}
                        return str(msg.get("id") or "") or None
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        return None
                return True
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    # Discord returns Retry-After in seconds (sometimes
                    # fractional). Sleep + retry once.
                    retry_after_raw = e.headers.get("Retry-After", "1") if e.headers else "1"
                    try:
                        retry_after = float(retry_after_raw)
                    except ValueError:
                        retry_after = 1.0
                    _log(f"Discord 429 — sleeping {retry_after:.1f}s and retrying", "WARN")
                    time.sleep(min(retry_after + 0.25, 30))
                    continue
                err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
                _log(f"Discord per-test POST failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
                return failure_return
            except Exception as e:
                _log(f"Discord per-test POST failed: {e}", "ERROR")
                return failure_return
        return failure_return

    def _patch_discord_multipart(
        self,
        webhook_url: str,
        message_id: str,
        embeds: list[dict],
        files: list[tuple[str, bytes, str]],
    ) -> bool:
        """PATCH an existing webhook message in place.

        Used by the per-test dedup workflow: when a previously-failing test
        is still failing with the same root cause, we update the existing
        message (incrementing the counter footer + refreshing screenshots)
        instead of posting a new one.

        Endpoint: `PATCH /webhooks/{id}/{token}/messages/{message_id}`.
        Multipart body is identical to POST, but uploading new files
        replaces the message's attachments entirely (Discord behaviour
        when no `attachments` array is referenced in the payload).

        Returns True on success, False otherwise. Never raises.
        """
        if not webhook_url or not message_id or not embeds:
            return False

        # Build the message-edit URL — strip any trailing query string from
        # the webhook URL first so we can append `/messages/{id}` cleanly.
        base_url = webhook_url.split("?", 1)[0].rstrip("/")
        patch_url = f"{base_url}/messages/{message_id}"

        payload = {
            "embeds": embeds,
            # Username/avatar are NOT supported on PATCH (the original
            # message keeps the identity it was created with), so we omit
            # them deliberately. Sending them would not error but would
            # silently waste bytes.
        }
        body, content_type = _build_multipart_body(payload, files)
        ua = "OpenMates-TestRunner/1.0 (https://github.com/glowingkitty/OpenMates)"

        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    patch_url, data=body,
                    headers={"Content-Type": content_type, "User-Agent": ua},
                    method="PATCH",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp.read()
                return True
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    retry_after_raw = e.headers.get("Retry-After", "1") if e.headers else "1"
                    try:
                        retry_after = float(retry_after_raw)
                    except ValueError:
                        retry_after = 1.0
                    _log(f"Discord 429 (PATCH) — sleeping {retry_after:.1f}s and retrying", "WARN")
                    time.sleep(min(retry_after + 0.25, 30))
                    continue
                # 404 means the message we tried to edit no longer exists
                # (deleted by hand, channel cleared, etc.). Caller should
                # treat this as "fall back to a fresh POST".
                err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
                if e.code == 404:
                    _log(f"Discord PATCH 404 — message {message_id} gone, will repost", "WARN")
                else:
                    _log(f"Discord PATCH failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
                return False
            except Exception as e:
                _log(f"Discord PATCH failed: {e}", "ERROR")
                return False
        return False

    @staticmethod
    def _annotate_embeds_with_counter(
        embeds: list[dict],
        first_seen: str,
        last_seen: str,
        count: int,
    ) -> None:
        """Add a dedup-counter footer to the LAST embed in the list, in place.

        On a fresh failure (count == 1) the footer is just `🆕 First seen
        HH:MM UTC`. On repeats it becomes `🔁 Repeated N× • since HH:MM
        UTC • last HH:MM UTC` so the operator can see at a glance both how
        long the failure has been live and when the most recent tick was.
        """
        if not embeds:
            return
        try:
            first_short = first_seen.split("T")[1][:5] + " UTC" if "T" in first_seen else first_seen
            last_short = last_seen.split("T")[1][:5] + " UTC" if "T" in last_seen else last_seen
        except (IndexError, AttributeError):
            first_short = first_seen or "?"
            last_short = last_seen or "?"
        if count <= 1:
            footer_text = f"🆕 First seen {first_short}"
        else:
            footer_text = (
                f"🔁 Repeated {count}× • since {first_short} • last {last_short}"
            )
        embeds[-1]["footer"] = {"text": footer_text}

    def send_per_test_md_messages(
        self,
        result: RunResult,
        webhook_url: str,
        suite_name: str,
        screenshots_root: Path,
        env_var_name: str,
        state_file: Optional[Path] = None,
    ) -> tuple[int, int, int]:
        """Send one MD-style multi-embed message per failed test, with dedup.

        Returns `(posted, edited, recovered)`:
            posted    — number of NEW messages posted (first failure or
                        failure with a different root cause)
            edited    — number of existing messages PATCHed (repeat with
                        same error)
            recovered — number of recovery messages posted for tests that
                        passed after previously failing

        When `state_file` is provided, dedup is active:
            * On first sight of a failing test → POST and store
              {message_id, error_hash, first_seen, last_seen, count=1}
            * On repeat with same error_hash → PATCH the existing message
              in place; bump count + last_seen.
            * On repeat with a different error_hash → treat as new failure;
              POST a fresh message and replace the entry.
            * Tests in the state file but NOT in the current failure set
              are recoveries — post a single line and drop the entry.

        Caller orchestration: call _send_summary_to_discord first (the
        overview), then this method (the per-test detail).
        """
        if not webhook_url:
            _log(f"{env_var_name} not set — skipping per-test Discord detail", "DEBUG")
            return (0, 0, 0)

        suite_data = result.suites.get(suite_name, {}) or {}
        failed_tests = [
            t for t in suite_data.get("tests", [])
            if _is_problem_status(t.get("status", ""))
        ]

        # Load state once. When state_file is None, dedup is disabled and
        # we behave like the original implementation (always POST).
        state: dict = {"tests": {}, "summary": {}}
        if state_file is not None:
            state = _load_discord_state(state_file)
            state = _prune_discord_state(state)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        posted = 0
        edited = 0
        recovered = 0

        # ─── 1. Process current failures (POST or PATCH) ────────────────────
        current_failure_keys: set[str] = set()
        for t in failed_tests:
            test_key = _compute_test_key(suite_name, t)
            current_failure_keys.add(test_key)
            embeds, files = self._build_md_style_test_message(
                t, suite_name, result.run_id, screenshots_root,
            )
            if not embeds:
                # Nothing to send for this test (no screenshots / no step log).
                # The lightweight summary already named it as failed, so we
                # don't bother spamming an empty card.
                continue

            error_hash = _compute_error_hash(t)

            existing = state.get("tests", {}).get(test_key) if state_file else None
            same_error = (
                existing is not None
                and existing.get("error_hash") == error_hash
                and error_hash != ""
            )

            if same_error:
                # Repeat with same root cause → PATCH the existing message
                # in place after annotating with the bumped counter.
                new_count = int(existing.get("count", 1)) + 1
                first_seen = existing.get("first_seen", now_iso)
                self._annotate_embeds_with_counter(
                    embeds,
                    first_seen=first_seen,
                    last_seen=now_iso,
                    count=new_count,
                )
                ok = self._patch_discord_multipart(
                    webhook_url, str(existing.get("message_id", "")), embeds, files
                )
                if ok:
                    edited += 1
                    state["tests"][test_key] = {
                        **existing,
                        "last_seen": now_iso,
                        "count": new_count,
                    }
                    time.sleep(0.25)
                else:
                    # PATCH failed (e.g. message deleted) — fall back to a
                    # fresh POST so the operator still sees the failure.
                    self._annotate_embeds_with_counter(
                        embeds, first_seen=now_iso, last_seen=now_iso, count=1
                    )
                    msg_id = self._post_discord_multipart(
                        webhook_url, embeds, files, return_message_id=True
                    )
                    if msg_id:
                        posted += 1
                        state["tests"][test_key] = {
                            "message_id": msg_id,
                            "error_hash": error_hash,
                            "first_seen": now_iso,
                            "last_seen": now_iso,
                            "count": 1,
                        }
                        time.sleep(0.25)
            else:
                # First sight OR error fingerprint changed (different root
                # cause) → fresh POST.
                self._annotate_embeds_with_counter(
                    embeds, first_seen=now_iso, last_seen=now_iso, count=1
                )
                msg_id = self._post_discord_multipart(
                    webhook_url, embeds, files, return_message_id=True
                ) if state_file else self._post_discord_multipart(
                    webhook_url, embeds, files
                )
                # When dedup is disabled (state_file is None), msg_id is a
                # bool — treat True as "posted, no id to track".
                if state_file is None:
                    if msg_id:
                        posted += 1
                        time.sleep(0.25)
                else:
                    if msg_id:
                        posted += 1
                        state["tests"][test_key] = {
                            "message_id": msg_id,
                            "error_hash": error_hash,
                            "first_seen": now_iso,
                            "last_seen": now_iso,
                            "count": 1,
                        }
                        time.sleep(0.25)

        # ─── 2. Process recoveries (tests in state but not failing now) ────
        if state_file is not None:
            recovered_entries = []
            for k, entry in list(state.get("tests", {}).items()):
                if k in current_failure_keys:
                    continue
                # Only count recoveries for tests in this suite — leave
                # entries from other suites alone.
                if not k.startswith(f"{suite_name}::"):
                    continue
                recovered_entries.append((k, entry))

            for k, entry in recovered_entries:
                # Strip "{suite_name}::" prefix for the human label.
                human = k.split("::", 1)[1] if "::" in k else k
                count = int(entry.get("count", 1))
                first_seen = entry.get("first_seen", "")
                first_short = (
                    first_seen.split("T")[1][:5] + " UTC"
                    if "T" in first_seen else (first_seen or "?")
                )
                description = (
                    f"**{human}** is green again.\n"
                    f"Failed **{count}×** since `{first_short}`."
                )
                recovery_embed = {
                    "description": description,
                    "color": 0x22C55E,
                    "footer": {"text": "✅ Recovery"},
                }
                ok = self._post_discord_multipart(
                    webhook_url, [recovery_embed], []
                )
                if ok:
                    recovered += 1
                    # Drop the entry — recovery message is one-shot, we
                    # don't track it after this. If it fails again, it'll
                    # come back as a fresh first-sight POST.
                    state["tests"].pop(k, None)
                    time.sleep(0.25)

            # Persist state for next tick.
            _save_discord_state(state_file, state)

        if posted or edited or recovered:
            _log(
                f"Discord per-test: {posted} new, {edited} updated, "
                f"{recovered} recovered"
            )
        return (posted, edited, recovered)

    def _send_via_internal_api(self, endpoint: str, payload: dict) -> bool:
        """Send via internal API as fallback."""
        url = f"{self.internal_api_url}/internal/{endpoint}"
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": self.internal_token,
            }, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            _log(f"Email dispatched via internal API ({endpoint})")
            return True
        except Exception as e:
            _log(f"Internal API email dispatch failed: {e}", "WARN")
            return False

    def _build_summary_html(self, result: RunResult) -> str:
        """Build a simple HTML email for test results."""
        s = result.summary
        problem_count = _problem_count(s)
        status_color = "#22c55e" if problem_count == 0 else "#ef4444"
        status_text = "ALL PASSED" if problem_count == 0 else _problem_summary_label(s).upper()

        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)
        git_ref = escape(f"{result.git_sha}@{result.git_branch}")
        environment = escape(str(result.environment))

        html = f"""<html><body style="font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:20px">
<h2 style="color:{status_color}">{status_text}</h2>
<table style="border-collapse:collapse;margin:12px 0">
<tr><td style="padding:4px 12px 4px 0;color:#888">Total</td><td><b>{s['total']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#22c55e">Passed</td><td><b>{s['passed']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#ef4444">Failed</td><td><b>{s['failed']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#ef4444">Dispatch errors</td><td><b>{s.get('dispatch_error', 0)}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Skipped</td><td>{s['skipped']}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Not started</td><td>{s.get('not_started', 0)}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Duration</td><td>{dur_min}m {dur_sec}s</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Git</td><td>{git_ref}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Environment</td><td>{environment}</td></tr>
</table>"""
        cache_backfill_line = _cache_backfill_notification_line(result)
        if cache_backfill_line:
            html += f"<p>{escape(cache_backfill_line)}</p>"

        if problem_count:
            html += '<h3 style="color:#ef4444;margin-top:20px">Failures by suite and product area</h3>'
            failure_embeds = _build_discord_failure_embeds(
                result.suites,
                color=0xEF4444,
                truncate_descriptions=False,
            )
            for failure_embed in failure_embeds:
                title = escape(str(failure_embed["title"]))
                description = escape(
                    _plain_notification_text(str(failure_embed["description"]))
                )
                html += (
                    f'<h4 style="margin:18px 0 6px">{title}</h4>'
                    f'<pre style="margin:0;white-space:pre-wrap;font-size:13px">'
                    f'{description}</pre>'
                )

        html += "</body></html>"
        return html

    def _build_summary_text(self, result: RunResult) -> str:
        """Build plain-text email for test results."""
        s = result.summary
        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        lines = [
            f"Test Run Summary ({result.environment})",
            f"{'=' * 40}",
            f"Total: {s['total']}  Passed: {s['passed']}  Failed: {s['failed']}  "
            f"Dispatch errors: {s.get('dispatch_error', 0)}  Skipped: {s['skipped']}  "
            f"Not started: {s.get('not_started', 0)}",
            f"Duration: {dur_min}m {dur_sec}s",
            f"Git: {result.git_sha}@{result.git_branch}",
            "",
        ]
        cache_backfill_line = _cache_backfill_notification_line(result)
        if cache_backfill_line:
            lines.extend([cache_backfill_line, ""])

        if _problem_count(s) > 0:
            lines.append("Failures by suite and product area:")
            lines.append("-" * 40)
            failure_embeds = _build_discord_failure_embeds(
                result.suites,
                color=0xEF4444,
                truncate_descriptions=False,
            )
            for failure_embed in failure_embeds:
                lines.append(str(failure_embed["title"]))
                lines.append(_plain_notification_text(str(failure_embed["description"])))
                lines.append("")
            lines.append("")

        return "\n".join(lines)

    def _build_internal_api_payload(self, result: RunResult) -> dict:
        """Build payload for /internal/dispatch-test-summary-email."""
        payload = self._build_openobserve_payload(result)
        payload["recipient_email"] = self.admin_email
        problem_count = _problem_count(result.summary)
        problem_label = _problem_summary_label(result.summary)
        status_label = "All tests passed" if problem_count == 0 else problem_label
        payload["subject_override"] = f"[OpenMates] {status_label} ({result.environment})"
        payload["summary_copy"] = {
            "header_failure": problem_label,
            "status_failure": problem_label.upper(),
        }
        payload["failure_groups"] = [
            {
                "title": str(group["title"]),
                "description": _plain_notification_text(str(group["description"])),
            }
            for group in _build_discord_failure_embeds(
                result.suites,
                color=0xEF4444,
                truncate_descriptions=True,
            )
        ]
        return payload

    def _build_openobserve_payload(self, result: RunResult) -> dict:
        """Build the normalized payload for OpenObserve."""
        s = result.summary
        suites_list = []
        failed_tests = []
        all_tests = []

        for suite_name, suite_data in result.suites.items():
            tests = suite_data.get("tests", [])
            suite_passed = sum(1 for t in tests if t.get("status") == "passed")
            suite_failed = sum(1 for t in tests if t.get("status") == "failed")
            suite_dispatch_error = sum(1 for t in tests if t.get("status") == "dispatch_error")
            suite_not_started = sum(1 for t in tests if t.get("status") == "not_started")
            suites_list.append({
                "name": suite_name,
                "total": len(tests),
                "passed": suite_passed,
                "failed": suite_failed,
                "dispatch_error": suite_dispatch_error,
                "not_started": suite_not_started,
                "status": suite_data.get("status", "unknown"),
            })
            for t in tests:
                all_tests.append({
                    "suite": suite_name,
                    "name": t.get("name", t.get("file", "")),
                    "status": t.get("status", "unknown"),
                    "duration_seconds": t.get("duration_seconds", 0),
                })
                if _is_problem_status(t.get("status", "")):
                    error = (t.get("error") or "")[:MAX_ERROR_SNIPPET]
                    failed_tests.append({
                        "suite": suite_name,
                        "name": t.get("name", t.get("file", "")),
                        "error": error or None,
                    })

        return {
            "environment": result.environment,
            "run_id": result.run_id,
            "git_sha": result.git_sha,
            "git_branch": result.git_branch,
            "duration_seconds": int(result.duration_seconds),
            "total": s["total"],
            "passed": s["passed"],
            "failed": s["failed"],
            "dispatch_error": s.get("dispatch_error", 0),
            "timeout": s.get("timeout", 0),
            "result_unknown": s.get("result_unknown", 0),
            "skipped": s["skipped"],
            "not_started": s.get("not_started", 0),
            "suites": suites_list,
            "failed_tests": failed_tests,
            "all_tests": all_tests,
        }


# ---------------------------------------------------------------------------
# Hourly smoke modes (OPE-349)
#
# Both --hourly-dev and --hourly-prod are triggered by the dev server's local
# crontab. They are intentionally separate from --daily because:
#   • They have a different goal: catch urgent breakage within an hour, not
#     full-suite coverage.
#   • They use a different (much shorter) spec list.
#   • They have a different Discord routing (per-channel webhook).
#   • They never run the commit-activity gate — failures within the active
#     window must always alert.
#
# We do NOT use the GitHub Actions `schedule:` cron for any test workflow:
# we have repeatedly observed it silently skipping runs under load. Local
# cron + workflow_dispatch is reliable.
# ---------------------------------------------------------------------------

def _archive_hourly_run(archive_dir: Path, result: RunResult) -> Path:
    """Persist a single hourly run to test-results/hourly-{dev,prod}/.

    Filename pattern: run-<UTC-timestamp>.json. Also writes last-run.json
    inside the same dir for quick "did the latest run pass?" lookups.
    Prunes archives older than HOURLY_ARCHIVE_RETENTION_DAYS files.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = result.run_id.replace(":", "").replace("-", "")
    run_file = archive_dir / f"run-{ts}.json"
    data = {
        "run_id": result.run_id,
        "git_sha": result.git_sha,
        "git_branch": result.git_branch,
        "flags": result.flags,
        "duration_seconds": result.duration_seconds,
        "summary": result.summary,
        "suites": result.suites,
        "environment": result.environment,
    }
    _safe_write_json(run_file, data)
    _safe_write_json(archive_dir / "last-run.json", data)

    # Prune: keep N most-recent run-*.json files (~7 days at 11 runs/day = 77).
    keep = HOURLY_ARCHIVE_RETENTION_DAYS * 24
    archives = sorted(archive_dir.glob("run-*.json"), reverse=True)
    for old in archives[keep:]:
        old.unlink(missing_ok=True)

    return run_file


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _heartbeat_should_fire(archive_dir: Path) -> bool:
    """Return True at most once per UTC day.

    Used by hourly modes so a green run posts a single "still alive" embed
    each day even though we suppress all other green runs. Without this the
    channel could go silent for weeks and we'd never notice the cron itself
    had stopped firing.

    Marker is a small file at archive_dir/.heartbeat-YYYY-MM-DD; we touch it
    on the first call of each UTC day and skip on every subsequent call.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    marker = archive_dir / f".heartbeat-{today}"
    if marker.is_file():
        return False
    # Prune yesterday's markers so the directory stays tidy.
    for old in archive_dir.glob(".heartbeat-*"):
        if old.name != marker.name:
            old.unlink(missing_ok=True)
    marker.touch()
    return True


def _docker_restarted_recently(grace_minutes: int = DOCKER_GRACE_MINUTES) -> bool:
    """Return True if Docker was restarted within the last `grace_minutes`.

    The marker file DOCKER_RESTART_MARKER is written by the Claude Code
    docker-restart-marker hook (PostToolUse on Bash) whenever a
    `docker compose down/restart/stop` command is detected. Hourly smoke
    runs call this to avoid false-failure notifications from infra churn.
    """
    if not DOCKER_RESTART_MARKER.is_file():
        return False
    try:
        raw = DOCKER_RESTART_MARKER.read_text().strip()
        restart_dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_sec = (datetime.now(timezone.utc) - restart_dt).total_seconds()
        return age_sec < grace_minutes * 60
    except Exception:
        return False


def run_hourly_dev_mode(notification: NotificationService, force: bool) -> int:
    """Hourly dev smoke: dispatch the 4 core specs, post to Discord on failure.

    `force=True` (used for manual one-shot runs) bypasses the green-run silence
    so the operator can verify Discord wiring without breaking a spec on purpose.
    """
    if not force and _docker_restarted_recently():
        _log(
            f"Docker restarted within the last {DOCKER_GRACE_MINUTES} min "
            "— skipping hourly-dev smoke run to avoid false failures"
        )
        return 0

    git_sha, git_branch = _git_info()
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print()
    print("=" * 60)
    print("  OpenMates Hourly Smoke — DEV")
    print("=" * 60)
    _log(f"Git: {git_sha}@{git_branch}")
    _log(f"Specs: {len(HOURLY_DEV_SPECS)} ({', '.join(HOURLY_DEV_SPECS)})")
    print()

    start = time.time()
    client = GitHubActionsClient()
    runner = BatchRunner(
        client=client,
        specs=HOURLY_DEV_SPECS,
        batch_size=len(HOURLY_DEV_SPECS),  # one batch — small list
        fail_fast=False,                    # always run all 4, surface every failure
        use_mocks=True,
        normal_account_slots=CORE_JOURNEY_ACCOUNT_SLOTS,
    )
    suite_result = runner.run_all_batches()
    duration = time.time() - start

    result = ResultAggregator.build_run_result(
        suites={"playwright": suite_result},
        run_id=run_id,
        git_sha=git_sha,
        git_branch=git_branch,
        environment="development",
        duration=duration,
        flags={"mode": "hourly-dev", "force": force},
    )

    archive_path = _archive_hourly_run(HOURLY_DEV_DIR, result)
    _log(f"Archived hourly-dev run to {_display_path(archive_path)}")

    s = result.summary
    print()
    print("=" * 60)
    problem_count = _problem_count(s)
    icon = "✓" if problem_count == 0 else "✗"
    dur_min = int(result.duration_seconds // 60)
    dur_sec = int(result.duration_seconds % 60)
    print(f"  {icon} hourly-dev: {s['passed']}/{s['total']} passed, "
          f"{_problem_summary_label(s)}   ({dur_min}m {dur_sec}s)")
    print("=" * 60)
    print()

    # Decide whether to ping Discord. On forced runs we always post (so the
    # operator gets confirmation). Otherwise: post on failure, plus one daily
    # heartbeat for green runs.
    post_on_success = force or _heartbeat_should_fire(HOURLY_DEV_DIR)

    # Dedup state file: persists per-test message ids and the summary
    # fingerprint so repeat ticks PATCH the existing messages instead of
    # spamming new ones. Lives next to the run archives.
    state_file = HOURLY_DEV_DIR / DISCORD_STATE_FILE_NAME

    # Send the lightweight summary embed first (one message: overview of
    # which specs failed + clickable [logs] links), then per-test detail
    # messages (PATCH on repeat, fresh POST on first sight, recovery line
    # when a previously failing test goes green).
    notification._send_summary_to_discord(
        result,
        webhook_url=notification.discord_webhook_dev_smoke,
        mode_label="dev hourly",
        post_on_success=post_on_success,
        env_var_name="DISCORD_WEBHOOK_DEV_SMOKE",
        state_file=state_file,
        suite_name_for_dedup="playwright",
    )
    # Always call the per-test sender — even with zero current failures it
    # may still need to post recovery messages for tests that just turned
    # green AND prune the state file.
    notification.send_per_test_md_messages(
        result,
        webhook_url=notification.discord_webhook_dev_smoke,
        suite_name="playwright",
        screenshots_root=RESULTS_DIR / "screenshots" / "current",
        env_var_name="DISCORD_WEBHOOK_DEV_SMOKE",
        state_file=state_file,
    )

    return 1 if problem_count > 0 else 0


# prod-smoke.yml writes one JSON file per selected suite into the artifact:
# test-results/{reachability,paid-chat,app-skill-web-search}.json. We use these
# as the source of truth for per-suite status. Step `conclusion` is unreliable
# here because selected steps use `continue-on-error: true && exit 0`, so step
# conclusions are `success` even when the underlying command failed.
PROD_SMOKE_SPECS: list[tuple[str, str, str]] = [
    # (key, human-readable label, spec filename)
    ("reachability", "reachability spec", "prod-smoke-reachability.spec.ts"),
    ("paid-chat", "CLI paid chat smoke", "verify_prod_cli_smoke.py"),
    ("app-skill-web-search", "CLI web-search app-skill smoke", "verify_prod_cli_smoke.py"),
]
PROD_SMOKE_SPECS_BY_SUITE: dict[str, list[tuple[str, str, str]]] = {
    PROD_SMOKE_SUITE_FREE_HOURLY: [PROD_SMOKE_SPECS[0]],
    PROD_SMOKE_SUITE_PAID_CHAT: [PROD_SMOKE_SPECS[1]],
    PROD_SMOKE_SUITE_APP_SKILL_WEB_SEARCH: [PROD_SMOKE_SPECS[2]],
}


def _parse_prod_smoke_artifact(
    art_path: Path,
    specs: Optional[list[tuple[str, str, str]]] = None,
) -> list[dict]:
    """Parse per-spec results from a downloaded prod-smoke artifact.

    Returns one dict per spec in the order they ran:
        {"name": <human label>, "status": "passed"|"failed",
         "error": <error snippet or empty>, "passed": int, "failed": int}

    Empty/missing/unparseable JSON files mean playwright crashed before
    producing any test output (e.g. config load error) — treated as
    `failed` with an empty error so the caller falls back to the job-level
    log snippet for the actual cause.

    Returns an empty list when the artifact is missing entirely so the
    caller can fall back to the conclusion-based single-test path.
    """
    if not art_path or not art_path.is_dir():
        return []

    # The JSON files live under one of these locations depending on how the
    # artifact was unpacked. GitHub flattens uploaded directory contents in
    # some cases, so the artifact root itself is a valid candidate.
    candidates = [
        art_path,
        art_path / "test-results",
        art_path / f"prod-smoke-results-{art_path.name}" / "test-results",
    ]
    # Also walk one level down in case the artifact name is unknown.
    if not any(c.is_dir() for c in candidates):
        for child in art_path.iterdir():
            if child.is_dir():
                inner = child / "test-results"
                if inner.is_dir():
                    candidates.append(inner)
                    break

    candidate_dirs = [c for c in candidates if c.is_dir()]
    if not candidate_dirs:
        return []

    out: list[dict] = []
    for spec_key, spec_label, spec_filename in (specs or PROD_SMOKE_SPECS):
        json_path = next(
            (candidate / f"{spec_key}.json" for candidate in candidate_dirs if (candidate / f"{spec_key}.json").is_file()),
            candidate_dirs[0] / f"{spec_key}.json",
        )
        if not json_path.is_file() or json_path.stat().st_size == 0:
            out.append({
                "key": spec_key,
                "filename": spec_filename,
                "name": spec_label,
                "status": "failed",
                "error": "",  # caller will substitute the job log snippet
                "passed": 0,
                "failed": 1,
            })
            continue

        # The file may have non-JSON prefix from the `list` reporter — find
        # the first `{` and try to parse from there.
        try:
            raw = json_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out.append({
                "name": spec_label, "status": "failed",
                "error": "", "passed": 0, "failed": 1,
            })
            continue

        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            brace = raw.find("{")
            if brace >= 0:
                try:
                    data = json.loads(raw[brace:])
                except json.JSONDecodeError:
                    data = None

        if not isinstance(data, dict):
            out.append({
                "key": spec_key,
                "filename": spec_filename,
                "name": spec_label, "status": "failed",
                "error": (raw.strip().splitlines()[-1][:300] if raw.strip() else ""),
                "passed": 0, "failed": 1,
            })
            continue

        # CLI verifier JSON: {status, scenarios: {name: {status, error?}}}
        if "scenarios" in data and data.get("status") in {"passed", "failed"}:
            scenarios = data.get("scenarios") if isinstance(data.get("scenarios"), dict) else {}
            failed_scenarios = [
                (name, value)
                for name, value in scenarios.items()
                if isinstance(value, dict) and value.get("status") != "passed"
            ]
            first_error = ""
            if failed_scenarios:
                scenario_name, scenario_data = failed_scenarios[0]
                first_error = str(scenario_data.get("error") or f"{scenario_name} failed")
            passed_count = sum(
                1
                for value in scenarios.values()
                if isinstance(value, dict) and value.get("status") == "passed"
            )
            failed_count = len(failed_scenarios)
            out.append({
                "key": spec_key,
                "filename": spec_filename,
                "name": spec_label,
                "status": "passed" if data.get("status") == "passed" else "failed",
                "error": first_error,
                "passed": passed_count,
                "failed": failed_count,
            })
            continue

        # Playwright JSON: stats.expected = passed, stats.unexpected = failed
        stats = data.get("stats", {}) or {}
        expected = int(stats.get("expected", 0) or 0)
        unexpected = int(stats.get("unexpected", 0) or 0)

        # Pull the first failure message if available.
        first_error = ""
        if unexpected > 0:
            for suite in data.get("suites", []) or []:
                for spec in suite.get("specs", []) or []:
                    for t in spec.get("tests", []) or []:
                        for r in (t.get("results") or []):
                            if r.get("status") in ("failed", "timedOut"):
                                err = (r.get("error", {}) or {}).get("message", "")
                                if err:
                                    first_error = err.strip()
                                    break
                        if first_error:
                            break
                    if first_error:
                        break
                if first_error:
                    break

        status = "passed" if unexpected == 0 and expected > 0 else "failed"
        out.append({
            "key": spec_key,
            "filename": spec_filename,
            "name": spec_label,
            "status": status,
            "error": first_error,
            "passed": expected,
            "failed": unexpected,
        })

    return out


def _berlin_now() -> datetime:
    return datetime.now(BERLIN_TZ)


def _skip_outside_prod_schedule(
    *,
    force: bool,
    mode_label: str,
    allowed_hours: Optional[frozenset[int]] = None,
    hour_range: Optional[tuple[int, int]] = None,
) -> bool:
    if force:
        return False
    now = _berlin_now()
    if allowed_hours is not None and now.hour not in allowed_hours:
        _log(
            f"Skipping {mode_label}: Berlin hour {now.hour:02d} is outside "
            f"scheduled hours {sorted(allowed_hours)}"
        )
        return True
    if hour_range is not None:
        start_hour, end_hour = hour_range
        if now.hour < start_hour or now.hour > end_hour:
            _log(
                f"Skipping {mode_label}: Berlin hour {now.hour:02d} is outside "
                f"{start_hour:02d}:00-{end_hour:02d}:59"
            )
            return True
    return False


def _run_prod_smoke_suite(
    notification: NotificationService,
    *,
    force: bool,
    suite: str,
    archive_dir: Path,
    mode_flag: str,
    mode_label: str,
    display_title: str,
    dry_run: bool = False,
) -> int:
    """Dispatch one selected prod-smoke.yml suite and notify from dev server."""
    git_sha, git_branch = _git_info()
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print()
    print("=" * 60)
    print(f"  {display_title}")
    print("=" * 60)
    _log(f"Git: {git_sha}@{git_branch}")
    _log(f"Workflow: {PROD_SMOKE_WORKFLOW} suite={suite}")
    print()

    if dry_run:
        _log("Dry run — would dispatch production smoke workflow")
        print(f"    gh workflow run {PROD_SMOKE_WORKFLOW} --repo {GH_REPO} --ref {GH_BRANCH} -f suite={suite}")
        return 0

    client = GitHubActionsClient()
    pre_ids = client._recent_run_ids(limit=5, workflow=PROD_SMOKE_WORKFLOW)
    dispatch_token = f"prod-{suite}-{os.getpid()}-{time.time_ns()}"

    new_run_id: Optional[int] = None
    suite_result: Optional[SuiteResult] = None  # set by failure paths OR by artifact parser
    conclusion: str = "unknown"

    rc = subprocess.run(
        ["gh", "workflow", "run", PROD_SMOKE_WORKFLOW,
         "--repo", GH_REPO, "--ref", GH_BRANCH,
         "-f", f"suite={suite}",
         "-f", f"dispatch_token={dispatch_token}"],
        capture_output=True, text=True,
    )
    if rc.returncode != 0:
        detail = (rc.stderr or rc.stdout or "unknown gh workflow error").strip()[:500]
        _log(f"Dispatch failed: {detail[:200]}", "ERROR")
        # Build a synthetic failure result so the Discord path still fires.
        suite_result = SuiteResult(
            status="failed",
            tests=[{"name": "prod-smoke-dispatch", "status": "dispatch_error",
                    "duration_seconds": 0,
                    "error": f"Dispatch failed: {detail}"}],
        )
    else:
        # Find the exact dispatched run by token. Multiple prod suites can be
        # scheduled in the same Berlin hour, so selecting the newest run is
        # race-prone.
        for _ in range(15):
            new_run_id = _matching_dispatched_run_id(
                client._recent_runs(limit=30, workflow=PROD_SMOKE_WORKFLOW),
                dispatch_token,
            )
            if new_run_id is not None:
                break
            time.sleep(2)
        if new_run_id is None:
            post_ids = client._recent_run_ids(limit=10, workflow=PROD_SMOKE_WORKFLOW)
            fresh = [rid for rid in post_ids if rid not in pre_ids]
            if len(fresh) == 1:
                new_run_id = fresh[0]

        if new_run_id is None:
            _log("Could not find dispatched prod-smoke run", "ERROR")
            suite_result = SuiteResult(
                status="failed",
                tests=[{"name": "prod-smoke-dispatch", "status": "dispatch_error",
                        "duration_seconds": 0,
                        "error": "Could not find dispatched workflow run"}],
            )
        else:
            _log(f"Waiting for prod-smoke run {new_run_id} ({suite})...")
            statuses = client.wait_for_runs(
                [new_run_id], fail_fast=False,
                timeout=PROD_SMOKE_RUN_TIMEOUT,
            )
            print()  # clear polling line
            status_data = statuses.get(new_run_id, {})
            conclusion = status_data.get("conclusion", "unknown")
            _log(f"prod-smoke run {new_run_id} → {conclusion}")

    # ─── Result building (artifact-driven) ──────────────────────────────────
    # Download the prod-smoke artifact so we can read the per-spec playwright
    # JSON files AND pull failure screenshots in a single round trip. This
    # block runs unconditionally when we have a run ID and no early failure
    # path already produced a synthetic suite_result.
    artifact_dir: Optional[Path] = None
    art_path: Optional[Path] = None
    spec_results: list[dict] = []
    log_snippet = ""

    if new_run_id is not None and suite_result is None:
        artifact_dir = Path(tempfile.mkdtemp(prefix="prod-smoke-artifact-"))
        art_path = client.download_artifact(
            new_run_id, f"prod-smoke-results-{new_run_id}", artifact_dir
        )
        selected_specs = PROD_SMOKE_SPECS_BY_SUITE.get(suite, PROD_SMOKE_SPECS)
        spec_results = _parse_prod_smoke_artifact(art_path, selected_specs) if art_path else []
        # Job-level log snippet — used when an individual spec's JSON is
        # empty/missing (the spec crashed before producing structured output).
        if conclusion != "success":
            log_snippet = client.get_failed_job_error(new_run_id) or ""

        if spec_results:
            tests: list[dict] = []
            for sr in spec_results:
                t: dict = {
                    "name": sr["name"],
                    "status": sr["status"],
                    "duration_seconds": 0,
                    # Use the per-spec filename so the per-test detail
                    # sender can derive a screenshot directory name from it
                    # (it strips .spec.ts and looks under <root>/<base>/).
                    "file": sr.get("filename", "prod-smoke.yml"),
                    "run_id": new_run_id,
                }
                if sr["status"] == "failed":
                    # Prefer the per-spec error from the playwright JSON;
                    # fall back to the job-level log snippet when the JSON
                    # was empty (e.g. config-load crash).
                    t["error"] = sr.get("error") or log_snippet or (
                        f"prod-smoke conclusion: {conclusion}"
                    )
                tests.append(t)
            has_fail = any(t["status"] == "failed" for t in tests)
            suite_result = SuiteResult(
                status="failed" if has_fail else "passed",
                tests=tests,
            )
        else:
            # Artifact missing entirely — preserve the conclusion-based
            # single-test fallback so we never silently drop a notification.
            if conclusion == "success":
                suite_result = SuiteResult(
                    status="passed",
                    tests=[{"name": "prod-smoke", "status": "passed",
                            "duration_seconds": 0, "file": "prod-smoke.yml",
                            "run_id": new_run_id}],
                )
            else:
                suite_result = SuiteResult(
                    status="failed",
                    tests=[{"name": "prod-smoke", "status": "failed",
                            "duration_seconds": 0, "file": "prod-smoke.yml",
                            "run_id": new_run_id,
                            "error": log_snippet or f"prod-smoke conclusion: {conclusion}"}],
                )

    result = ResultAggregator.build_run_result(
        suites={suite: suite_result},
        run_id=run_id,
        git_sha=git_sha,
        git_branch=git_branch,
        environment="production",
        duration=0.0,  # we don't time the GH workflow itself
        flags={"mode": mode_flag, "suite": suite, "force": force},
    )

    archive_path = _archive_hourly_run(archive_dir, result)
    _log(f"Archived {mode_flag} run to {_display_path(archive_path)}")

    s = result.summary
    problem_count = _problem_count(s)
    print()
    print("=" * 60)
    icon = "✓" if problem_count == 0 else "✗"
    print(f"  {icon} {mode_flag}: {s['passed']}/{s['total']} passed, "
          f"{_problem_summary_label(s)}")
    print("=" * 60)
    print()

    # Stage any failure screenshots from the artifact under a temporary
    # per-spec screenshots root that matches the layout the MD-style sender
    # expects: <root>/<spec-base-name>/test-failed-1.png. Playwright stores
    # failure shots under frontend/apps/web_app/test-results/<test-id>/, so
    # we walk those, group by which spec key appears in the path, and copy
    # them into the per-spec subdir using the spec filename's base.
    staged_root: Optional[Path] = None
    if art_path and spec_results:
        staged_root = Path(tempfile.mkdtemp(prefix="prod-smoke-staged-"))
        for sr in spec_results:
            if sr.get("status") != "failed":
                continue
            spec_key = sr.get("key", "")
            spec_filename = sr.get("filename", "")
            if not spec_key or not spec_filename:
                continue
            spec_base = spec_filename.replace(".spec.ts", "")
            spec_subdir = staged_root / spec_base
            spec_subdir.mkdir(parents=True, exist_ok=True)
            # Walk the artifact for any PNG/webp whose path mentions the
            # spec key (case-insensitive). Test-failed shots get a stable
            # name; other PNGs preserve theirs.
            for img in sorted(list(art_path.rglob("*.png")) + list(art_path.rglob("*.webp"))):
                try:
                    rel_str = str(img.relative_to(art_path)).lower()
                except ValueError:
                    rel_str = str(img).lower()
                if spec_key not in rel_str:
                    continue
                dest = spec_subdir / img.name
                try:
                    shutil.copy2(str(img), str(dest))
                except OSError:
                    continue

    run_url = (
        f"https://github.com/{GH_REPO}/actions/runs/{new_run_id}"
        if new_run_id
        else None
    )

    # Production notifications are failure-only. Use --dry-run-notify to test
    # webhook wiring instead of sending green heartbeat messages from cron.
    post_on_success = False
    state_file = archive_dir / DISCORD_STATE_FILE_NAME
    if problem_count > 0 and not notification.discord_webhook_prod_smoke:
        _log("DISCORD_WEBHOOK_PROD_SMOKE not set — cannot send prod smoke Discord failure", "ERROR")
    try:
        # Lightweight summary first (overview of which specs failed +
        # clickable links). Skipped automatically when the failure set is
        # unchanged from the last tick (dedup'd via state file).
        notification._send_summary_to_discord(
            result,
            webhook_url=notification.discord_webhook_prod_smoke,
            mode_label=mode_label,
            post_on_success=post_on_success,
            env_var_name="DISCORD_WEBHOOK_PROD_SMOKE",
            run_url=run_url,
            state_file=state_file,
            suite_name_for_dedup=suite,
        )
        notification.send_prod_failure_email(result, mode_label, run_url)
        # Always call the per-test sender so recoveries get reported
        # and the state file gets pruned even on a green tick. When
        # there are no current failures and no screenshots, the call
        # is essentially a no-op + recovery scan.
        notification.send_per_test_md_messages(
            result,
            webhook_url=notification.discord_webhook_prod_smoke,
            suite_name=suite,
            # staged_root may be None on a fully-green run; pass a
            # non-existent path so the per-test builder simply finds
            # nothing and the recovery scan still runs.
            screenshots_root=staged_root or (PROJECT_ROOT / "test-results" / "_no_screens"),
            env_var_name="DISCORD_WEBHOOK_PROD_SMOKE",
            state_file=state_file,
        )
    finally:
        if artifact_dir:
            shutil.rmtree(artifact_dir, ignore_errors=True)
        if staged_root:
            shutil.rmtree(staged_root, ignore_errors=True)

    return 1 if problem_count > 0 else 0


def run_hourly_prod_mode(notification: NotificationService, force: bool, dry_run: bool = False) -> int:
    """Backward-compatible alias for the free production hourly smoke."""
    return run_prod_free_hourly_mode(notification, force=force, dry_run=dry_run)


def run_prod_free_hourly_mode(notification: NotificationService, force: bool, dry_run: bool = False) -> int:
    """Free prod smoke: hourly between 06:00 and 23:59 Berlin time."""
    if _skip_outside_prod_schedule(
        force=force,
        mode_label="prod-free-hourly",
        hour_range=(PROD_FREE_HOURLY_START_HOUR, PROD_FREE_HOURLY_END_HOUR),
    ):
        return 0
    return _run_prod_smoke_suite(
        notification,
        force=force,
        suite=PROD_SMOKE_SUITE_FREE_HOURLY,
        archive_dir=HOURLY_PROD_DIR,
        mode_flag="prod-free-hourly",
        mode_label="prod free hourly",
        display_title="OpenMates Free Hourly Smoke — PROD",
        dry_run=dry_run,
    )


def run_prod_paid_chat_mode(notification: NotificationService, force: bool, dry_run: bool = False) -> int:
    """Paid prod chat smoke: three Berlin-time slots per day."""
    if _skip_outside_prod_schedule(
        force=force,
        mode_label="prod-paid-chat",
        allowed_hours=PROD_PAID_CHAT_HOURS,
    ):
        return 0
    return _run_prod_smoke_suite(
        notification,
        force=force,
        suite=PROD_SMOKE_SUITE_PAID_CHAT,
        archive_dir=PROD_PAID_CHAT_DIR,
        mode_flag="prod-paid-chat",
        mode_label="prod paid chat",
        display_title="OpenMates Paid Chat Smoke — PROD",
        dry_run=dry_run,
    )


def run_prod_app_skill_mode(notification: NotificationService, force: bool, dry_run: bool = False) -> int:
    """Production app-skill smoke: direct CLI web-search command, daily by default."""
    if _skip_outside_prod_schedule(
        force=force,
        mode_label="prod-app-skill",
        allowed_hours=PROD_APP_SKILL_HOURS,
    ):
        return 0
    return _run_prod_smoke_suite(
        notification,
        force=force,
        suite=PROD_SMOKE_SUITE_APP_SKILL_WEB_SEARCH,
        archive_dir=PROD_APP_SKILL_DIR,
        mode_flag="prod-app-skill",
        mode_label="prod app-skill",
        display_title="OpenMates App-Skill Smoke — PROD",
        dry_run=dry_run,
    )


def run_dry_run_notify_mode(notification: NotificationService, mode: str) -> int:
    """Send a one-shot test embed to verify a Discord webhook is wired.

    `mode` selects which webhook + label to use:
        "daily"        → DISCORD_WEBHOOK_DEV_NIGHTLY
        "hourly-dev"   → DISCORD_WEBHOOK_DEV_SMOKE
        "hourly-prod"  → DISCORD_WEBHOOK_PROD_SMOKE
    """
    if mode == "daily":
        ok = notification.post_dry_run_notify(
            notification.discord_webhook_url,
            "dev nightly",
            "DISCORD_WEBHOOK_DEV_NIGHTLY",
        )
    elif mode == "hourly-dev":
        ok = notification.post_dry_run_notify(
            notification.discord_webhook_dev_smoke,
            "dev hourly",
            "DISCORD_WEBHOOK_DEV_SMOKE",
        )
    elif mode == "hourly-prod":
        ok = notification.post_dry_run_notify(
            notification.discord_webhook_prod_smoke,
            "prod hourly",
            "DISCORD_WEBHOOK_PROD_SMOKE",
        )
    else:
        _log(f"Unknown --dry-run-notify mode: {mode}", "ERROR")
        return 2
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# ReportGenerator — structured MD reports per test
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generates per-test markdown reports in test-results/reports/.

    Each test gets its own MD file in either success/ or failed/ with:
    - Status, date, duration metadata
    - Steps with pass/fail icons and duration
    - Inline screenshots per step
    - Full error details for failed steps
    """

    REPORTS_DIR = RESULTS_DIR / "reports"

    # Suites that get per-test MD files (E2E with screenshots/steps)
    E2E_SUITES = {"playwright"}

    def generate(self, result: RunResult) -> None:
        """Generate MD files for all tests in the latest run.

        E2E tests (playwright): per-test MD files in success/ and failed/.
        Unit tests (vitest, pytest): single summary MD per suite.

        Only cleans reports for suites present in this run — so a vitest-only
        rerun won't wipe playwright reports generated by the daily run.
        """
        success_dir = self.REPORTS_DIR / "success"
        failed_dir = self.REPORTS_DIR / "failed"

        # Archive existing daily reports before overwriting.
        # If reports/failed/ has content and a daily-run JSON exists for today,
        # copy reports to reports/daily-YYYY-MM-DD/ so they survive reruns.
        if failed_dir.is_dir() and any(failed_dir.iterdir()):
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            daily_archive = self.REPORTS_DIR / f"daily-{today}"
            if not daily_archive.is_dir():
                daily_archive.mkdir(parents=True, exist_ok=True)
                for subdir_name in ("failed", "success"):
                    src = self.REPORTS_DIR / subdir_name
                    dst = daily_archive / subdir_name
                    if src.is_dir():
                        shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                _log(f"Archived daily reports to reports/daily-{today}/")

        success_dir.mkdir(parents=True, exist_ok=True)
        failed_dir.mkdir(parents=True, exist_ok=True)

        # Remove only reports for suites in this run (not all reports)
        suites_in_run = set(result.suites.keys())
        if suites_in_run & self.E2E_SUITES:
            # E2E suites write per-spec .md — remove old ones from both dirs
            for d in (success_dir, failed_dir):
                for f in d.iterdir():
                    if f.suffix == ".md":
                        f.unlink()
        for suite_name in suites_in_run - self.E2E_SUITES:
            # Unit suites write <suite>-summary.md — remove only that file
            summary = self.REPORTS_DIR / f"{suite_name}-summary.md"
            summary.unlink(missing_ok=True)

        generated = 0
        for suite_name, suite_data in result.suites.items():
            tests = suite_data.get("tests", [])

            if suite_name in self.E2E_SUITES:
                # Per-test MD files for E2E suites
                for test in tests:
                    name = test.get("file") or test.get("name", "unknown")
                    status = test.get("status", "unknown")
                    target_dir = failed_dir if status == "failed" else success_dir
                    safe_name = name.replace("/", "-").replace("\\", "-")
                    md_name = safe_name.replace(".spec.ts", "").replace(".test.ts", "") + ".md"

                    content = self._build_test_md(test, result.run_id, suite_name)
                    (target_dir / md_name).write_text(content, encoding="utf-8")
                    generated += 1
            else:
                # Single summary MD for unit test suites
                content = self._build_unit_summary_md(
                    suite_name, tests, result.run_id
                )
                (self.REPORTS_DIR / f"{suite_name}-summary.md").write_text(
                    content, encoding="utf-8"
                )
                generated += 1

        _log(f"Generated {generated} MD report(s) in test-results/reports/")

    def _build_test_md(self, test: dict, run_id: str, suite_name: str) -> str:
        """Build markdown content for a single test.

        Uses step-log.json (written by logCheckpoint/takeStepScreenshot) to
        reconstruct the execution timeline with checkpoints and inline screenshots.
        Falls back to screenshot-filename parsing if no step log exists.
        """
        name = test.get("file") or test.get("name", "unknown")
        status = test.get("status", "unknown")
        error = test.get("error", "")
        pw_errors = test.get("playwright_errors", [])
        screenshot_paths = test.get("screenshot_paths", [])
        spec_name = name.replace(".spec.ts", "").replace(".test.ts", "")

        status_icon = "PASSED" if status == "passed" else "FAILED"
        lines: list[str] = [
            f"# {name}",
            "",
            f"**Status:** {status_icon} | **Date:** {run_id} | **Suite:** {suite_name}",
            "",
            "---",
            "",
        ]

        # Try to load step-log.json for this spec
        step_log = self._load_step_log(spec_name)

        if step_log:
            lines.append("## Steps")
            lines.append("")
            self._render_steps_from_log(
                lines, step_log, spec_name, status, pw_errors, error, screenshot_paths
            )
        elif screenshot_paths:
            # Fallback: reconstruct steps from screenshot filenames
            lines.append("## Steps")
            lines.append("")
            self._render_steps_from_screenshots(
                lines, screenshot_paths, spec_name, status, pw_errors, error
            )
        elif status != "not_started":
            lines.append("*No step data available (artifact not downloaded)*")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _load_step_log(spec_name: str) -> Optional[list[dict]]:
        """Load step-log.json from the spec's artifact directory."""
        ss_dir = RESULTS_DIR / "screenshots" / "current" / spec_name
        step_log_path = ss_dir / "step-log.json"
        if step_log_path.is_file():
            try:
                with open(step_log_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return None

    @staticmethod
    def _render_steps_from_log(
        lines: list[str],
        step_log: list[dict],
        spec_name: str,
        status: str,
        pw_errors: list[dict],
        error: str,
        screenshot_paths: list[str],
    ) -> None:
        """Render step log entries as interleaved checkpoints + screenshots."""
        ss_dir_rel = f"screenshots/current/{spec_name}"

        # Filter out noise entries:
        # - "Captured step screenshot." — the screenshot entry already represents it
        # - "Archived prior screenshots" — test infrastructure, not a test step
        noise_prefixes = ("Captured step screenshot", "Archived prior screenshots")
        filtered = [
            e for e in step_log
            if not (e.get("type") == "checkpoint"
                    and e.get("message", "").startswith(noise_prefixes))
        ]

        display_num = 0
        for i, entry in enumerate(filtered):
            entry_type = entry.get("type", "checkpoint")
            message = entry.get("message", "")
            is_last = i == len(filtered) - 1

            if entry_type == "checkpoint":
                display_num += 1
                icon = "❌" if is_last and status == "failed" else "✅"
                lines.append(f"{display_num}. {message} {icon}")
                lines.append("")
            elif entry_type == "screenshot":
                screenshot_file = entry.get("screenshot", "")
                if screenshot_file:
                    lines.append(
                        f"   ![{message}](../../{ss_dir_rel}/{screenshot_file})"
                    )
                    lines.append("")

        # Append error + failure screenshot at the end for failed tests
        if status == "failed":
            err_msg = ""
            if pw_errors:
                err_msg = pw_errors[0].get("message", "")
            elif error:
                err_msg = error

            if err_msg:
                lines.append("**Error:**")
                lines.append("```")
                lines.append(err_msg.strip())
                lines.append("```")
                lines.append("")

            # Append test-failed-*.png screenshots
            for ss_path in screenshot_paths:
                fname = Path(ss_path).name.lower()
                if fname.startswith("test-failed"):
                    lines.append(f"![{Path(ss_path).stem}](../../{ss_path})")
                    lines.append("")

    @staticmethod
    def _render_steps_from_screenshots(
        lines: list[str],
        screenshot_paths: list[str],
        spec_name: str,
        status: str,
        pw_errors: list[dict],
        error: str,
    ) -> None:
        """Fallback: reconstruct steps from screenshot filenames."""
        import re

        step_screenshots = []
        failure_screenshots = []
        for ss_path in screenshot_paths:
            fname = Path(ss_path).name.lower()
            if fname.startswith("test-failed") or fname.startswith("test-finished"):
                failure_screenshots.append(ss_path)
            else:
                step_screenshots.append(ss_path)

        # Parse step number and label from filename: {prefix}-{NN}-{label}.png
        for ss_path in step_screenshots:
            fname = Path(ss_path).stem
            match = re.search(r"-(\d+)-(.+)$", fname)
            if match:
                step_num = int(match.group(1))
                label = match.group(2).replace("-", " ").title()
            else:
                step_num = 0
                label = fname.replace("-", " ").title()

            icon = "✅"
            lines.append(f"{step_num}. {label} {icon}")
            lines.append(f"   ![{label}](../../{ss_path})")
            lines.append("")

        # Error + failure screenshots for failed tests
        if status == "failed":
            err_msg = ""
            if pw_errors:
                err_msg = pw_errors[0].get("message", "")
            elif error:
                err_msg = error

            if err_msg:
                lines.append("**Error:**")
                lines.append("```")
                lines.append(err_msg.strip())
                lines.append("```")
                lines.append("")

            for ss_path in failure_screenshots:
                if "test-failed" in Path(ss_path).name.lower():
                    lines.append(f"![{Path(ss_path).stem}](../../{ss_path})")
                    lines.append("")

    @staticmethod
    def _build_unit_summary_md(
        suite_name: str, tests: list[dict], run_id: str
    ) -> str:
        """Build a single summary MD for a unit test suite (vitest/pytest).

        Groups failures with full error output, lists passed tests compactly.
        """
        total = len(tests)
        passed_tests = [t for t in tests if t.get("status") == "passed"]
        failed_tests = [t for t in tests if _is_problem_status(t.get("status", ""))]
        skipped_tests = [
            t for t in tests
            if t.get("status") != "passed" and not _is_problem_status(t.get("status", ""))
        ]
        passed = len(passed_tests)
        failed = len(failed_tests)

        status_text = f"**{passed}/{total} passed**" if failed == 0 else f"**{failed} failed** | {passed} passed"
        lines: list[str] = [
            f"# Unit Test Report — {suite_name}",
            "",
            f"**Date:** {run_id} | {status_text} | {total} total",
            "",
            "---",
            "",
        ]

        # Failed tests — full detail
        if failed_tests:
            lines.append("## Failed")
            lines.append("")
            for t in failed_tests:
                name = t.get("name") or t.get("file", "?")
                error = t.get("error", "")
                # Use structured Playwright errors if available (unlikely for unit tests)
                pw_errors = t.get("playwright_errors", [])
                if pw_errors:
                    error = pw_errors[0].get("message", error)

                lines.append(f"### {name}")
                lines.append("")
                if error:
                    lines.append("```")
                    # Limit error output to 50 lines to keep reports readable
                    error_lines = error.strip().splitlines()
                    for err_line in error_lines[:50]:
                        lines.append(err_line)
                    if len(error_lines) > 50:
                        lines.append(f"... ({len(error_lines) - 50} more lines)")
                    lines.append("```")
                else:
                    lines.append("*No error details available*")
                lines.append("")

        # Passed tests — compact list
        if passed_tests:
            lines.append(f"## Passed ({passed})")
            lines.append("")
            passed_names = [t.get("name") or t.get("file", "?") for t in passed_tests]
            # Group by file prefix for readability
            lines.append(", ".join(passed_names))
            lines.append("")

        # Skipped tests
        if skipped_tests:
            lines.append(f"## Skipped ({len(skipped_tests)})")
            lines.append("")
            skipped_names = [t.get("name") or t.get("file", "?") for t in skipped_tests]
            lines.append(", ".join(skipped_names))
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# TestRecordingPublisher — manifests + S3 upload for /tests
# ---------------------------------------------------------------------------

class TestRecordingPublisher:
    """Builds latest Playwright recording manifests and uploads them to S3."""

    INDEX_FILE = TEST_RECORDINGS_DIR / "index.json"

    def publish(self, result: RunResult) -> None:
        """Publish latest Playwright recording bundles for browser viewing."""
        playwright_suite = result.suites.get("playwright")
        if not isinstance(playwright_suite, dict):
            return

        tests = playwright_suite.get("tests", [])
        if not tests:
            return

        TEST_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        manifests = []
        for test in tests:
            for manifest in self._build_manifests(test, result):
                slug = manifest["slug"]
                bundle_dir = TEST_RECORDINGS_DIR / slug
                bundle_dir.mkdir(parents=True, exist_ok=True)
                (bundle_dir / "manifest.json").write_text(
                    json.dumps(manifest, indent=2), encoding="utf-8"
                )
                manifests.append(self._index_entry(manifest))

        index = {
            "run_id": result.run_id,
            "git_sha": result.git_sha,
            "git_branch": result.git_branch,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tests": sorted(manifests, key=lambda item: item["title"]),
        }
        self.INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")
        self._upload_latest_bundles()

    def _build_manifests(self, test: dict, result: RunResult) -> list[dict]:
        spec = test.get("file") or test.get("name")
        if not spec:
            return []

        slug = _test_recording_slug(spec)
        bundle_dir = TEST_RECORDINGS_DIR / slug
        if not bundle_dir.is_dir():
            return []

        artifact_meta = self._read_json(bundle_dir / "artifact-meta.json") or {}
        video_file = (artifact_meta.get("video_files") or [None])[0]
        video_records = artifact_meta.get("video_records") or []
        thumbnail_file = artifact_meta.get("thumbnail_file")
        screenshot_files = artifact_meta.get("screenshot_files") or []
        screenshot_records = artifact_meta.get("screenshot_records") or []

        child_manifests = self._build_playwright_result_manifests(
            bundle_dir=bundle_dir,
            test=test,
            result=result,
            spec=spec,
            spec_slug=slug,
            video_records=video_records,
            screenshot_records=screenshot_records,
        )
        if child_manifests:
            return child_manifests

        safe_name = spec.replace("/", "-").replace("\\", "-")
        md_name = safe_name.replace(".spec.ts", "").replace(".test.ts", "") + ".md"
        report_dir = "failed" if test.get("status") == "failed" else "success"
        report_source = ReportGenerator.REPORTS_DIR / report_dir / md_name
        report_file = None
        if report_source.is_file():
            report_file = "report.md"
            shutil.copy2(report_source, bundle_dir / report_file)

        steps = self._build_steps(bundle_dir, test, slug, screenshot_files, screenshot_records)
        assets = self._build_assets(slug, video_file, thumbnail_file, report_file, screenshot_files)

        return [{
            "spec": spec,
            "slug": slug,
            "title": spec.replace(".spec.ts", ""),
            "status": test.get("status", "unknown"),
            "run_id": result.run_id,
            "git_sha": result.git_sha,
            "git_branch": result.git_branch,
            "duration_seconds": test.get("duration_seconds", 0),
            "github_run_url": test.get("github_run_url"),
            "error": test.get("error"),
            "assets": assets,
            "steps": steps,
        }]

    @staticmethod
    def _read_json(path: Path) -> Optional[dict | list]:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @classmethod
    def _build_playwright_result_manifests(
        cls,
        *,
        bundle_dir: Path,
        test: dict,
        result: RunResult,
        spec: str,
        spec_slug: str,
        video_records: list[dict],
        screenshot_records: list[dict],
    ) -> list[dict]:
        playwright_results = cls._playwright_results(bundle_dir / "playwright.json")
        if len(playwright_results) <= 1 or not video_records:
            return []

        manifests = []
        for index, item in enumerate(playwright_results, start=1):
            video_file = cls._file_for_attachment(item.get("video_source"), video_records)
            if not video_file:
                continue
            screenshot_file = cls._file_for_attachment(item.get("screenshot_source"), screenshot_records)
            child_slug = f"{spec_slug}--{_test_recording_slug(item['title'])}"
            screenshot_key = f"{TEST_RECORDINGS_S3_PREFIX}/{spec_slug}/{screenshot_file}" if screenshot_file else None
            step = {
                "index": 1,
                "type": "playwright_test",
                "title": item["title"],
                "status": item.get("status"),
                "duration_seconds": item.get("duration_seconds", 0),
                "timestamp": item.get("timestamp"),
                "video_time_seconds": 0,
            }
            if screenshot_file:
                step["screenshot_file"] = screenshot_file
                step["screenshot_key"] = screenshot_key
            if item.get("error"):
                step["error"] = item["error"]

            manifests.append({
                "spec": spec,
                "slug": child_slug,
                "title": item["title"],
                "status": item.get("status") or test.get("status", "unknown"),
                "run_id": result.run_id,
                "git_sha": result.git_sha,
                "git_branch": result.git_branch,
                "duration_seconds": item.get("duration_seconds", 0),
                "github_run_url": test.get("github_run_url"),
                "error": item.get("error"),
                "assets": {
                    "video_key": f"{TEST_RECORDINGS_S3_PREFIX}/{spec_slug}/{video_file}",
                    "thumbnail_key": screenshot_key,
                    "report_key": None,
                    "screenshot_keys": [screenshot_key] if screenshot_key else [],
                },
                "steps": [step],
                "source_spec_slug": spec_slug,
                "source_result_index": index,
            })
        return manifests

    @classmethod
    def _playwright_results(cls, playwright_json: Path) -> list[dict]:
        data = cls._read_json(playwright_json)
        if not isinstance(data, dict):
            return []

        results: list[dict] = []

        def walk_suite(suite: dict) -> None:
            for spec in suite.get("specs", []):
                title = spec.get("title") or spec.get("file") or "Playwright test"
                for playwright_test in spec.get("tests", []):
                    for playwright_result in playwright_test.get("results", []):
                        image_source = None
                        video_source = None
                        for attachment in playwright_result.get("attachments", []):
                            content_type = str(attachment.get("contentType", ""))
                            if content_type.startswith("image/") and not image_source:
                                image_source = attachment.get("path")
                            elif content_type.startswith("video/") and not video_source:
                                video_source = attachment.get("path")
                        error = playwright_result.get("error")
                        results.append({
                            "title": title,
                            "status": playwright_result.get("status"),
                            "duration_seconds": round(float(playwright_result.get("duration", 0)) / 1000, 2),
                            "timestamp": playwright_result.get("startTime"),
                            "screenshot_source": image_source,
                            "video_source": video_source,
                            "error": error.get("message", str(error)) if isinstance(error, dict) else error,
                        })
            for child in suite.get("suites", []):
                walk_suite(child)

        for suite in data.get("suites", []):
            if isinstance(suite, dict):
                walk_suite(suite)
        return results

    @staticmethod
    def _file_for_attachment(attachment_path: Optional[str], records: list[dict]) -> Optional[str]:
        if not attachment_path:
            return None
        attachment_suffix = str(attachment_path).split("test-results/", 1)[-1]
        for record in records:
            source = record.get("source", "") if isinstance(record, dict) else ""
            if source == attachment_path or source.endswith(attachment_suffix):
                return record.get("file")
        return None

    def _build_steps(
        self,
        bundle_dir: Path,
        test: dict,
        slug: str,
        screenshot_files: list[str],
        screenshot_records: list[dict],
    ) -> list[dict]:
        step_log = self._read_json(bundle_dir / "step-log.json")
        if isinstance(step_log, list) and step_log:
            return self._steps_from_log(step_log, slug)
        playwright_steps = self._steps_from_playwright(test)
        if playwright_steps:
            return playwright_steps
        json_steps = self._steps_from_playwright_json(
            bundle_dir / "playwright.json", slug, screenshot_files, screenshot_records
        )
        if json_steps:
            return json_steps
        return self._steps_from_screenshots(slug, screenshot_files)

    @staticmethod
    def _steps_from_log(step_log: list[dict], slug: str) -> list[dict]:
        first_ts = None
        noise_prefixes = ("Captured step screenshot", "Archived prior screenshots")
        screenshot_steps: list[dict] = []
        checkpoint_steps: list[dict] = []
        for entry in step_log:
            entry_type = entry.get("type", "checkpoint")
            message = entry.get("message", "")
            if entry_type == "checkpoint" and message.startswith(noise_prefixes):
                continue

            timestamp = entry.get("timestamp")
            if timestamp and first_ts is None:
                first_ts = timestamp
            video_time = _seconds_between(first_ts, timestamp) if first_ts and timestamp else None
            screenshot = entry.get("screenshot")

            if entry_type == "screenshot" and screenshot:
                screenshot_steps.append({
                    "index": len(screenshot_steps) + 1,
                    "type": "screenshot",
                    "title": message or Path(screenshot).stem.replace("-", " ").title(),
                    "timestamp": timestamp,
                    "video_time_seconds": video_time,
                    "screenshot_key": f"{TEST_RECORDINGS_S3_PREFIX}/{slug}/screenshots/{screenshot}",
                    "screenshot_file": f"screenshots/{screenshot}",
                })
                continue

            checkpoint_steps.append({
                "index": len(checkpoint_steps) + 1,
                "type": entry_type,
                "title": message if message and not message.startswith(noise_prefixes) else f"Step {len(checkpoint_steps) + 1}",
                "timestamp": timestamp,
                "video_time_seconds": video_time,
            })
        return screenshot_steps or checkpoint_steps

    @staticmethod
    def _steps_from_playwright(test: dict) -> list[dict]:
        steps = []
        elapsed = 0.0
        for idx, step in enumerate(test.get("steps") or [], start=1):
            duration_s = round(float(step.get("duration_ms", 0)) / 1000, 2)
            steps.append({
                "index": idx,
                "type": "playwright_step",
                "title": step.get("title", ""),
                "status": step.get("status"),
                "duration_seconds": duration_s,
                "video_time_seconds": round(elapsed, 2),
                "error": step.get("error"),
            })
            elapsed += duration_s
        return steps

    @classmethod
    def _steps_from_playwright_json(
        cls,
        playwright_json: Path,
        slug: str,
        screenshot_files: list[str],
        screenshot_records: list[dict],
    ) -> list[dict]:
        data = cls._read_json(playwright_json)
        if not isinstance(data, dict):
            return []

        results: list[dict] = []

        def walk_suite(suite: dict) -> None:
            for spec in suite.get("specs", []):
                title = spec.get("title") or spec.get("file") or "Playwright test"
                for test in spec.get("tests", []):
                    for result in test.get("results", []):
                        results.append({"title": title, "result": result})
            for child in suite.get("suites", []):
                walk_suite(child)

        for suite in data.get("suites", []):
            if isinstance(suite, dict):
                walk_suite(suite)

        if not results:
            return []

        first_start = next(
            (item["result"].get("startTime") for item in results if item["result"].get("startTime")),
            None,
        )
        steps = []
        for index, item in enumerate(results, start=1):
            result = item["result"]
            duration_s = round(float(result.get("duration", 0)) / 1000, 2)
            step: dict = {
                "index": index,
                "type": "playwright_test",
                "title": item["title"],
                "status": result.get("status"),
                "duration_seconds": duration_s,
                "timestamp": result.get("startTime"),
                "video_time_seconds": _seconds_between(first_start, result.get("startTime")),
            }
            error = result.get("error")
            if error:
                step["error"] = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            screenshot_file = cls._screenshot_for_playwright_result(
                result, screenshot_files, screenshot_records, index - 1
            )
            if screenshot_file:
                step["screenshot_file"] = screenshot_file
                step["screenshot_key"] = f"{TEST_RECORDINGS_S3_PREFIX}/{slug}/{screenshot_file}"
            steps.append(step)
        return steps

    @staticmethod
    def _screenshot_for_playwright_result(
        result: dict,
        screenshot_files: list[str],
        screenshot_records: list[dict],
        fallback_index: int,
    ) -> Optional[str]:
        attachment_path = None
        for attachment in result.get("attachments", []):
            if str(attachment.get("contentType", "")).startswith("image/"):
                attachment_path = attachment.get("path")
                break

        if attachment_path:
            for record in screenshot_records:
                source = record.get("source", "") if isinstance(record, dict) else ""
                if source == attachment_path or source.endswith(str(attachment_path).split("test-results/", 1)[-1]):
                    return record.get("file")

        if fallback_index < len(screenshot_files):
            return screenshot_files[fallback_index]
        return None

    @staticmethod
    def _steps_from_screenshots(slug: str, screenshot_files: list[str]) -> list[dict]:
        steps = []
        for index, screenshot_file in enumerate(screenshot_files, start=1):
            label = Path(screenshot_file).stem.replace("-", " ").title()
            steps.append({
                "index": index,
                "type": "screenshot",
                "title": label,
                "screenshot_file": screenshot_file,
                "screenshot_key": f"{TEST_RECORDINGS_S3_PREFIX}/{slug}/{screenshot_file}",
            })
        return steps

    @staticmethod
    def _build_assets(
        slug: str,
        video_file: Optional[str],
        thumbnail_file: Optional[str],
        report_file: Optional[str],
        screenshot_files: list[str],
    ) -> dict:
        def key_for(file_name: Optional[str]) -> Optional[str]:
            if not file_name:
                return None
            return f"{TEST_RECORDINGS_S3_PREFIX}/{slug}/{file_name}"

        return {
            "video_key": key_for(video_file),
            "thumbnail_key": key_for(thumbnail_file),
            "report_key": key_for(report_file),
            "screenshot_keys": [key_for(path) for path in screenshot_files if key_for(path)],
        }

    @staticmethod
    def _index_entry(manifest: dict) -> dict:
        return {
            "spec": manifest["spec"],
            "slug": manifest["slug"],
            "title": manifest["title"],
            "status": manifest["status"],
            "run_id": manifest["run_id"],
            "duration_seconds": manifest["duration_seconds"],
            "error": manifest.get("error"),
            "assets": {
                "thumbnail_key": manifest.get("assets", {}).get("thumbnail_key"),
                "video_key": manifest.get("assets", {}).get("video_key"),
            },
        }

    def _upload_latest_bundles(self) -> None:
        try:
            asyncio.run(self._upload_latest_bundles_async())
        except Exception as e:
            _log(f"Test recording S3 upload skipped/failed: {e}", "WARN")

    async def _upload_latest_bundles_async(self) -> None:
        # Direct script execution sets sys.path[0] to scripts/, not the repo
        # root.  Keep the backend package importable in the nightly cron.
        project_root_text = str(PROJECT_ROOT)
        if project_root_text not in sys.path:
            sys.path.insert(0, project_root_text)
        try:
            from backend.core.api.app.services.s3.service import S3UploadService
            from backend.core.api.app.utils.secrets_manager import SecretsManager
        except Exception as e:
            raise RuntimeError(f"could not import S3 dependencies: {e}") from e

        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        s3_service = S3UploadService(secrets_manager)
        await s3_service.initialize()
        if not s3_service.client:
            raise RuntimeError("S3 service is unavailable")

        uploaded, deleted = await _upload_recording_files(TEST_RECORDINGS_DIR, s3_service)
        _log(f"Uploaded {uploaded} test recording artifact(s) to S3")
        _log(f"Removed {deleted} confirmed-upload local recording bundle(s)")


async def _upload_recording_files(root: Path, s3_service: object) -> tuple[int, int]:
    """Upload a complete snapshot, then delete its local bundle directories.

    Any upload exception exits before cleanup, preserving the entire local
    snapshot for the scheduled retry. This ordering is the deletion safety
    boundary.
    """
    uploaded = 0
    uploaded_keys: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        object_key = f"{TEST_RECORDINGS_S3_PREFIX}/{rel_path}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        await s3_service.upload_file(  # type: ignore[attr-defined]
            TEST_RECORDINGS_BUCKET_KEY,
            object_key,
            path.read_bytes(),
            content_type,
        )
        uploaded += 1
        uploaded_keys.add(object_key)
    await _prune_stale_recording_files(s3_service, uploaded_keys)
    return uploaded, _delete_uploaded_recording_bundles(root)


async def _prune_stale_recording_files(s3_service: object, desired_keys: set[str]) -> int:
    """Delete remote latest/ recording objects that are not in the new snapshot."""

    client = getattr(s3_service, "client", None)
    if client is None:
        raise RuntimeError("S3 service is unavailable")
    try:
        from backend.core.api.app.services.s3.config import get_bucket_name
    except Exception as exc:
        raise RuntimeError(f"could not import S3 bucket config: {exc}") from exc

    environment = str(getattr(s3_service, "environment", "development"))
    bucket_name = get_bucket_name(TEST_RECORDINGS_BUCKET_KEY, environment)
    prefix = f"{TEST_RECORDINGS_S3_PREFIX}/"
    stale_keys: list[str] = []
    continuation_token = None
    while True:
        request = {"Bucket": bucket_name, "Prefix": prefix}
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        response = await asyncio.to_thread(client.list_objects_v2, **request)
        for item in response.get("Contents", []) or []:
            key = item.get("Key") if isinstance(item, dict) else None
            if isinstance(key, str) and key not in desired_keys:
                stale_keys.append(key)
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")
        if not continuation_token:
            break

    for key in stale_keys:
        await s3_service.delete_file(TEST_RECORDINGS_BUCKET_KEY, key)  # type: ignore[attr-defined]
    return len(stale_keys)


def _delete_uploaded_recording_bundles(root: Path) -> int:
    """Remove only bundle directories after the complete upload loop succeeds.

    The caller invokes this after every S3 upload has returned successfully.
    The small index is retained for local diagnostics; source artifacts remain
    available through GitHub Actions and uploaded bundles through S3.
    """
    if not root.is_dir():
        return 0
    deleted = 0
    for path in root.iterdir():
        if not path.is_dir():
            continue
        shutil.rmtree(path)
        deleted += 1
    return deleted


def _seconds_between(first_iso: Optional[str], current_iso: Optional[str]) -> Optional[float]:
    if not first_iso or not current_iso:
        return None
    try:
        first = datetime.fromisoformat(first_iso.replace("Z", "+00:00"))
        current = datetime.fromisoformat(current_iso.replace("Z", "+00:00"))
        return max(0.0, round((current - first).total_seconds(), 2))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Local suite runners
# ---------------------------------------------------------------------------

def run_vitest() -> SuiteResult:
    """Run vitest unit tests locally."""
    _log("Running vitest...")
    suite_start = time.time()

    # Find vitest directories
    ui_dir = PROJECT_ROOT / "frontend" / "packages" / "ui"
    vitest_runs: list[tuple[Path, str]] = []

    if (ui_dir / "vitest.simple.config.ts").is_file():
        vitest_runs.append((ui_dir, "--config vitest.simple.config.ts"))

    # Auto-discover additional vitest dirs
    for pkg_json_path in sorted((PROJECT_ROOT / "frontend").glob("**/package.json")):
        if "node_modules" in str(pkg_json_path):
            continue
        pkg_dir = pkg_json_path.parent
        if pkg_dir == ui_dir:
            continue
        try:
            with open(pkg_json_path) as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "vitest" not in deps:
                continue
            # Check for test files
            test_files = list(pkg_dir.glob("src/**/*.test.ts"))
            if not test_files:
                continue
            config_flag = ""
            if (pkg_dir / "vitest.config.ts").is_file():
                config_flag = "--config vitest.config.ts"
            vitest_runs.append((pkg_dir, config_flag))
        except (json.JSONDecodeError, OSError):
            continue

    if not vitest_runs:
        return SuiteResult(status="skipped", reason="no vitest dirs found")

    all_tests: list[dict] = []
    overall_status = "passed"

    for vdir, config_flag in vitest_runs:
        rel = vdir.relative_to(PROJECT_ROOT)
        _log(f"  vitest in {rel}")

        cmd = f"npx vitest run {config_flag} --reporter=json".split()
        try:
            rc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(vdir), timeout=VITEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            _log(f"  vitest timed out after {VITEST_TIMEOUT}s in {rel}", "WARN")
            overall_status = "failed"
            all_tests.append({
                "name": f"{rel}/vitest-timeout",
                "status": "failed",
                "duration_seconds": VITEST_TIMEOUT,
                "error": f"vitest timed out after {VITEST_TIMEOUT}s — likely a deadlock in crypto/jsdom tests",
            })
            continue

        # Parse JSON from output (may have non-JSON prefix)
        raw = rc.stdout
        json_start = raw.find("{")
        json_end = raw.rfind("}")

        if json_start >= 0 and json_end > json_start:
            try:
                data = json.loads(raw[json_start:json_end + 1])
                for tf in data.get("testResults", []):
                    for ar in tf.get("assertionResults", []):
                        name = ar.get("fullName", ar.get("title", "unknown"))
                        status = "passed" if ar.get("status") == "passed" else "failed"
                        test_dur = ar.get("duration", 0) / 1000.0
                        entry: dict = {
                            "name": name,
                            "status": status,
                            "duration_seconds": round(test_dur, 3),
                        }
                        if status == "failed":
                            overall_status = "failed"
                            msgs = ar.get("failureMessages", [])
                            if msgs:
                                entry["error"] = msgs[0][:MAX_ERROR_SNIPPET]
                        all_tests.append(entry)
            except json.JSONDecodeError:
                pass

        if not all_tests and rc.returncode != 0:
            overall_status = "failed"
            all_tests.append({
                "name": f"{rel}/vitest-run",
                "status": "failed",
                "duration_seconds": 0,
                "error": (rc.stderr or rc.stdout)[:MAX_ERROR_SNIPPET] or f"vitest exited with code {rc.returncode}",
            })

    duration = time.time() - suite_start
    _log(f"  vitest: {sum(1 for t in all_tests if t['status'] == 'passed')}/{len(all_tests)} passed ({duration:.1f}s)")

    return SuiteResult(
        status=overall_status,
        tests=all_tests,
        duration_seconds=round(duration, 1),
    )


def run_pytest(include_integration: bool = False) -> SuiteResult:
    """Run pytest unit tests locally."""
    _log("Running pytest...")
    suite_start = time.time()

    # Find pytest binary
    venv_python = PROJECT_ROOT / "backend" / ".venv" / "bin" / "python3"
    if not venv_python.is_file():
        venv_python = Path("/OpenMates/.venv/bin/python3")
    if not venv_python.is_file():
        return SuiteResult(status="error", reason="Python venv not found")

    marker_expr = "not benchmark"
    if not include_integration:
        marker_expr = "not integration and not benchmark"

    # Check if pytest-json-report is available
    json_report = Path(tempfile.mktemp(suffix=".json"))
    check_plugin = subprocess.run(
        [str(venv_python), "-c", "import pytest_jsonreport"],
        capture_output=True, text=True,
    )
    has_json_report = check_plugin.returncode == 0

    tests_dir = PROJECT_ROOT / "backend" / "tests"
    cmd = [
        str(venv_python), "-m", "pytest",
        str(tests_dir),
        "-m", marker_expr,
        "-v", "--tb=short", "--color=no",
        "--ignore=" + str(tests_dir / "fixtures"),
        "--ignore=" + str(tests_dir / "test_encryption_service.py"),
        "--ignore=" + str(tests_dir / "test_integration_encryption.py"),
    ]
    # Ignore model comparison tests that have broken imports (missing tiktoken)
    for p in tests_dir.glob("test_model_comparison_*.py"):
        cmd.append("--ignore=" + str(p))
    if has_json_report:
        cmd += [f"--json-report-file={json_report}", "--json-report"]

    rc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))

    all_tests: list[dict] = []
    overall_status = "passed"

    # Try parsing JSON report (if pytest-json-report was available)
    if has_json_report and json_report.is_file():
        try:
            with open(json_report) as f:
                data = json.load(f)
            for t in data.get("tests", []):
                name = t.get("nodeid", "unknown")
                outcome = t.get("outcome", "")
                duration = t.get("duration", 0)
                entry: dict = {
                    "name": name,
                    "status": "passed" if outcome == "passed" else "failed" if outcome == "failed" else "skipped",
                    "duration_seconds": round(duration, 3),
                }
                if outcome == "failed":
                    overall_status = "failed"
                    call = t.get("call", {})
                    longrepr = call.get("longrepr", "")
                    if longrepr:
                        entry["error"] = str(longrepr)[:MAX_ERROR_SNIPPET]
                all_tests.append(entry)
        except (json.JSONDecodeError, OSError):
            pass
        finally:
            json_report.unlink(missing_ok=True)

    # Fallback: parse verbose pytest output (test::name PASSED/FAILED lines)
    if not all_tests:
        for line in rc.stdout.splitlines():
            # Match lines like: backend/tests/test_foo.py::test_bar PASSED
            m = re.match(r"^(\S+::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)", line)
            if m:
                name = m.group(1)
                result_str = m.group(2)
                status = "passed" if result_str == "PASSED" else "failed" if result_str in ("FAILED", "ERROR") else "skipped"
                entry = {"name": name, "status": status, "duration_seconds": 0}
                if status == "failed":
                    overall_status = "failed"
                all_tests.append(entry)

        # If still no tests parsed, create a single entry from exit code
        if not all_tests:
            if rc.returncode != 0:
                overall_status = "failed"
                all_tests.append({
                    "name": "pytest-run",
                    "status": "failed",
                    "duration_seconds": 0,
                    "error": (rc.stdout + "\n" + rc.stderr)[:MAX_ERROR_SNIPPET] or f"pytest exited with code {rc.returncode}",
                })
            else:
                all_tests.append({
                    "name": "pytest-unit-suite",
                    "status": "passed",
                    "duration_seconds": 0,
                })

    duration = time.time() - suite_start
    passed_count = sum(1 for t in all_tests if t["status"] == "passed")
    _log(f"  pytest: {passed_count}/{len(all_tests)} passed ({duration:.1f}s)")

    return SuiteResult(
        status=overall_status,
        tests=all_tests,
        duration_seconds=round(duration, 1),
    )


# ---------------------------------------------------------------------------
# TestOrchestrator
# ---------------------------------------------------------------------------

class TestOrchestrator:
    """Main orchestrator — coordinates all test suites."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.suite = args.suite
        self.spec = args.spec
        self.core_journeys = args.core_journeys
        self.critical_journeys = getattr(args, "critical_journeys", False)
        self.only_failed = args.only_failed
        self.daily = args.daily
        self.backfill_only = getattr(args, "daily_cache_backfill_only", False)
        self.force = args.force
        self.environment = args.environment
        self.max_concurrent = args.max_concurrent
        self.account = args.account
        self.create_account_slot = args.create_account_slot
        self.fail_fast = not args.no_fail_fast
        self.use_mocks = not args.no_mocks
        self.record_live_fixtures = args.record_live_fixtures
        self.proof_video_profile = args.proof_video_profile
        self.dry_run = args.dry_run
        self.dot_env = _read_env_file()
        self.only_failed_synthetic_files: tuple[str, ...] = ()
        selected_labels = os.getenv("OPENMATES_CAMPAIGN_TEST_LABELS_JSON", "")
        try:
            decoded_labels = json.loads(selected_labels) if selected_labels else []
        except json.JSONDecodeError:
            decoded_labels = []
        self.campaign_test_labels = [str(label) for label in decoded_labels] if isinstance(decoded_labels, list) else []

        self.git_sha, self.git_branch = _git_info()
        if self.daily and self.environment == "development":
            self.git_sha, self.git_branch = _daily_git_info(self.git_sha, self.git_branch)
        self.run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.notification = NotificationService()
        self.current_phase = "starting"
        self._progress_suites: dict[str, SuiteResult] = {}
        self._progress_start_time = 0.0
        self._daily_status_stop = threading.Event()
        self._daily_status_thread: Optional[threading.Thread] = None
        self.github_dispatch_circuit = DispatchCircuit()

    def _share_dispatch_circuit(self, client: object) -> DispatchCircuit:
        circuit = getattr(self, "github_dispatch_circuit", None)
        if circuit is None:
            circuit = DispatchCircuit()
            self.github_dispatch_circuit = circuit
        try:
            setattr(client, "dispatch_circuit", circuit)
        except AttributeError:
            pass
        return circuit

    def _send_daily_status_updates(self, start_time: float) -> None:
        """Post Discord status every 30 minutes until the daily run finishes."""
        next_update = start_time + DAILY_STATUS_INTERVAL_SECONDS
        while not self._daily_status_stop.wait(max(0, next_update - time.monotonic())):
            self.notification.send_daily_discord_status(
                self.git_sha,
                self.git_branch,
                self.environment,
                self.run_id,
                time.monotonic() - start_time,
                self.current_phase,
            )
            next_update += DAILY_STATUS_INTERVAL_SECONDS

    def _start_daily_status_updates(self, start_time: float) -> None:
        """Post the start status, start the heartbeat, then dispatch email."""
        self.notification.send_daily_discord_status(
            self.git_sha,
            self.git_branch,
            self.environment,
            self.run_id,
            0,
            self.current_phase,
            started=True,
        )
        self._daily_status_thread = threading.Thread(
            target=self._send_daily_status_updates,
            args=(start_time,),
            name="daily-test-discord-status",
            daemon=True,
        )
        self._daily_status_thread.start()
        self.notification.send_start_email(self.git_sha, self.git_branch, self.environment)

    def _stop_daily_status_updates(self) -> None:
        """Stop any heartbeat before a completion summary can be posted."""
        self._daily_status_stop.set()
        if self._daily_status_thread and self._daily_status_thread is not threading.current_thread():
            self._daily_status_thread.join(timeout=35)

    def run(self) -> int:
        """Execute the run and turn fatal daily errors into terminal results."""
        with _daily_terminal_signal_handlers(self.daily and not self.dry_run):
            try:
                return self._run()
            except DailyRunInterrupted as exc:
                phase = getattr(self, "current_phase", "unknown")
                _log(f"Daily runner interrupted during {phase}: {exc.signal_name}", "ERROR")
                return self._finalize_daily_runner_failure(exc)
            except Exception as exc:
                if not self.daily or self.dry_run:
                    raise
                phase = getattr(self, "current_phase", "unknown")
                _log(f"Daily runner crashed during {phase}: {type(exc).__name__}: {exc}", "ERROR")
                return self._finalize_daily_runner_failure(exc)
            finally:
                self._stop_daily_status_updates()

    def _result_flags(self, *, in_progress: bool = False, progress_phase: str = "") -> dict:
        flags = {
            "suite": self.suite,
            "daily": self.daily,
            "only_failed": self.only_failed,
            "fail_fast": self.fail_fast,
            "use_mocks": self.use_mocks,
            "record_live_fixtures": self.record_live_fixtures,
        }
        if in_progress:
            flags["in_progress"] = True
        if progress_phase:
            flags["progress_phase"] = progress_phase
        critical_phase = getattr(self, "critical_phase", None)
        if critical_phase:
            flags["critical_phase"] = critical_phase
        cache_backfill = getattr(self, "cache_backfill", None)
        if cache_backfill:
            flags["cache_backfill"] = cache_backfill
        return flags

    def _run_daily_cache_backfill(self) -> dict[str, object]:
        """Backfill one receipt-proven cache candidate without blocking the suite."""
        run_date = datetime.now(timezone.utc).date()
        plan = daily_ai_test_policy.daily_backfill_plan(run_date)
        if plan is None:
            return {"status": "skipped", "reason": "no_backfill_pending_specs"}
        preflight = _daily_cache_backfill_preflight(self.git_sha, run_date)
        if preflight.get("status") != "passed":
            return {
                "status": "failed",
                "spec": plan.spec,
                "cache_group": plan.cache_group,
                "detail": str(preflight.get("detail") or "backfill preflight failed"),
            }
        if self.environment != "development":
            return {
                "status": "failed",
                "spec": plan.spec,
                "cache_group": plan.cache_group,
                "detail": "automatic cache backfill is only supported in development",
            }
        if _get_env("OPENMATES_SKIP_VERCEL_WAIT", self.dot_env).lower() == "true":
            return {
                "status": "failed",
                "spec": plan.spec,
                "cache_group": plan.cache_group,
                "detail": "automatic cache backfill cannot skip the Vercel deployment gate",
            }
        deployment_ready, deployment_reason = _wait_for_vercel_deployment(
            str(preflight["full_commit_sha"]), self.dot_env
        )
        if not deployment_ready:
            return {
                "status": "failed",
                "spec": plan.spec,
                "cache_group": plan.cache_group,
                "detail": deployment_reason or "Vercel deployment was not ready before cache backfill",
            }
        paths = _resolve_daily_cache_backfill_paths(run_date)
        run_root = paths.candidate_root / plan.candidate_run_id

        client = GitHubActionsClient(git_sha=str(preflight["full_commit_sha"]))

        def dispatch(spec: str, record: bool, candidate_run_id: str) -> tuple[dict[str, object], Path]:
            run_id = client.dispatch_spec(
                spec,
                account=NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS[0],
                use_mocks=True,
                record_live_fixtures=record,
                daily_ai_run_id=candidate_run_id,
            )
            if run_id is None:
                raise daily_ai_cache_backfill.BackfillValidationError(
                    client.last_dispatch_error or "candidate dispatch failed"
                )
            outcome = client.wait_for_runs([run_id], fail_fast=True).get(run_id, {})
            if outcome.get("conclusion") != "success":
                raise daily_ai_cache_backfill.BackfillValidationError("candidate Playwright run did not pass")
            return daily_ai_cache_backfill.build_receipt(
                run_root, plan, mode="record" if record else "replay"
            )

        deployed_commit: list[str] = []

        def persist(expected_cache_sha256: str) -> str:
            commit = daily_ai_cache_backfill.deploy_candidate_cache(
                paths.source_root,
                paths.runtime_cache_root / plan.cache_group,
                plan,
                expected_cache_sha256,
            )
            deployed_commit.append(commit)
            return commit

        result = daily_ai_cache_backfill.run_backfill(
            plan,
            dispatch=dispatch,
            runtime_cache_root=paths.runtime_cache_root,
            source_cache_root=None,
            claim_root=paths.claim_root,
            candidate_run_root=run_root,
            persist=persist,
        )
        if result.get("status") == "runtime_promoted" and deployed_commit:
            return {**result, "status": "promoted", "commit_sha": deployed_commit[0]}
        return result

    def _save_progress_snapshot(
        self,
        suites: dict[str, SuiteResult],
        start_time: float,
        phase: str,
    ) -> None:
        if self.dry_run or not suites:
            return
        result = ResultAggregator.build_run_result(
            suites=suites,
            run_id=self.run_id,
            git_sha=self.git_sha,
            git_branch=self.git_branch,
            environment=self.environment,
            duration=time.time() - start_time,
            flags=self._result_flags(in_progress=True, progress_phase=phase),
        )
        ResultAggregator.save_progress(result)

    def _save_playwright_progress_snapshot(self, playwright_result: SuiteResult) -> None:
        self._save_progress_snapshot(
            {**self._progress_suites, "playwright": playwright_result},
            self._progress_start_time,
            "Playwright",
        )

    def _finalize_daily_runner_failure(self, exc: BaseException) -> int:
        """Persist and notify an orchestration failure instead of going silent."""
        interrupted = isinstance(exc, DailyRunInterrupted)
        suites = dict(self._progress_suites)
        suites["orchestration"] = SuiteResult(
            status="failed",
            tests=[{
                "name": "daily-runner",
                "file": "scripts/run_tests.py",
                "status": "failed",
                "duration_seconds": 0,
                "error": f"{type(exc).__name__}: {exc}"[:MAX_ERROR_SNIPPET],
            }],
            duration_seconds=0,
            reason=(
                f"Runner interrupted during {getattr(self, 'current_phase', 'unknown')}"
                if interrupted
                else f"Runner crashed during {getattr(self, 'current_phase', 'unknown')}"
            ),
        )
        flags = self._result_flags()
        if interrupted:
            flags["runner_interrupted"] = True
            flags["interrupt_signal"] = exc.signal_name
        else:
            flags["runner_crashed"] = True
        result = ResultAggregator.build_run_result(
            suites=suites,
            run_id=self.run_id,
            git_sha=self.git_sha,
            git_branch=self.git_branch,
            environment=self.environment,
            duration=max(0, time.time() - self._progress_start_time),
            flags=flags,
        )
        ResultAggregator.save(result)
        self._stop_daily_status_updates()
        result.flags["notifications_complete"] = bool(self.notification.send_summary_email(result))
        ResultAggregator.save(result)
        return 1

    def _run(self) -> int:
        """Execute the test run. Returns exit code (0=pass, 1=fail)."""
        print()
        print("=" * 60)
        print("  OpenMates Test Orchestrator")
        print("=" * 60)
        _log(f"Suite: {self.suite} | Environment: {self.environment}")
        _log(f"Git: {self.git_sha}@{self.git_branch}")
        _log(f"Run ID: {self.run_id}")
        if self.spec:
            _log(f"Single spec: {self.spec}")
        if self.account is not None:
            _log(f"Pinned Playwright account: {self.account}")
        if self.create_account_slot is not None:
            _log(f"Create account slot: {self.create_account_slot}")
        if self.only_failed:
            _log("Mode: --only-failed (rerunning previous failures)")
        print()

        # Daily mode: commit gate + lockfile
        if self.daily:
            if not self._daily_gate():
                return 0

        start_time = time.time()
        status_start_time = time.monotonic()
        if self.daily and not self.dry_run:
            self._start_daily_status_updates(status_start_time)
        suites: dict[str, SuiteResult] = {}
        self._progress_suites = suites
        self._progress_start_time = start_time
        backfill_only = getattr(self, "backfill_only", False)

        # Archive previous failure screenshots before starting a new run
        screenshots_dir = RESULTS_DIR / "screenshots"
        if not self.dry_run and screenshots_dir.is_dir():
            # Move current screenshots to date-stamped archive (preserves history)
            current_dir = screenshots_dir / "current"
            if current_dir.is_dir() and any(current_dir.iterdir()):
                prev_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                archive_dest = screenshots_dir / prev_date
                if archive_dest.is_dir():
                    shutil.rmtree(archive_dest, ignore_errors=True)
                current_dir.rename(archive_dest)
                _log(f"Archived previous screenshots to screenshots/{prev_date}/")

        parallel_daily = self.daily and not backfill_only and not self.spec and self.suite == "all" and not self.dry_run
        parallel_futures: dict[str, Future[SuiteResult]] = {}
        executor: ThreadPoolExecutor | None = None
        if parallel_daily:
            # GitHub unit workflows and the single-lane remote Mac use separate
            # capacity. Starting them together shortens the nightly critical
            # path without increasing Xcode/simulator concurrency on the Mac.
            executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="nightly-suite")
            parallel_futures = {
                "vitest": executor.submit(self._run_unit_suite_via_gha, "vitest.yml", "vitest-results"),
                "pytest_unit": executor.submit(self._run_unit_suite_via_gha, "pytest-unit.yml", "pytest-results"),
                "apple_remote": executor.submit(self._run_apple_remote_nightly),
            }

        try:
            if not backfill_only and not parallel_daily and not self.spec and self.suite in ("all", "vitest"):
                self.current_phase = "vitest"
                suites["vitest"] = self._run_unit_suite_via_gha("vitest.yml", "vitest-results") if not self.dry_run else SuiteResult(status="skipped", reason="dry run")
                self._save_progress_snapshot(suites, start_time, "vitest")

            if not backfill_only and not parallel_daily and not self.spec and self.suite in ("all", "pytest"):
                self.current_phase = "pytest"
                suites["pytest_unit"] = self._run_unit_suite_via_gha("pytest-unit.yml", "pytest-results") if not self.dry_run else SuiteResult(status="skipped", reason="dry run")
                self._save_progress_snapshot(suites, start_time, "pytest")

            if not backfill_only and not self.spec and self.suite in ("all", "cli"):
                self.current_phase = "CLI integration"
                suites["cli"] = self._run_cli_integration()
                self._save_progress_snapshot(suites, start_time, "CLI integration")

            if self.daily and not self.spec and self.suite == "all":
                self.current_phase = "cache backfill"
                self.cache_backfill = (
                    {"status": "skipped", "reason": "dry_run"}
                    if self.dry_run
                    else self._run_daily_cache_backfill()
                )
                suites["cache_backfill"] = _cache_backfill_suite(self.cache_backfill)
                if self.cache_backfill.get("status") == "failed":
                    _log(f"Daily cache backfill failed: {self.cache_backfill.get('detail', 'unknown error')}", "ERROR")
                self._save_progress_snapshot(suites, start_time, "cache backfill")

            if not backfill_only and self.suite in ("all", "playwright"):
                self.current_phase = "Playwright"
                suites["playwright"] = self._run_playwright()
                self._save_progress_snapshot(suites, start_time, "Playwright")

            if not backfill_only and not parallel_daily and not self.spec and (self.suite == "apple" or (self.daily and self.suite == "all")):
                self.current_phase = "Apple remote"
                suites["apple_remote"] = self._run_apple_remote_nightly()
                self._save_progress_snapshot(suites, start_time, "Apple remote")

            for suite_name, future in parallel_futures.items():
                self.current_phase = f"collecting {suite_name}"
                suites[suite_name] = future.result()
                self._save_progress_snapshot(suites, start_time, self.current_phase)
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=False)

        # Aggregate results
        self.current_phase = "finalizing results"
        duration = time.time() - start_time
        flags = self._result_flags()

        result = ResultAggregator.build_run_result(
            suites=suites,
            run_id=self.run_id,
            git_sha=self.git_sha,
            git_branch=self.git_branch,
            environment=self.environment,
            duration=duration,
            flags=flags,
        )

        # Save results
        if not self.dry_run:
            ResultAggregator.save(result)
            # Always generate MD reports (useful for single-spec debugging too)
            ReportGenerator().generate(result)
            TestRecordingPublisher().publish(result)
            self._sync_obsidian_test_results()

        # Print summary
        self._print_summary(result)

        # Daily mode: post-run tasks
        if self.daily and not self.dry_run:
            self._stop_daily_status_updates()
            self._daily_post_run(result)

        return _exit_code_for_summary(result.summary)

    def _sync_obsidian_test_results(self) -> None:
        """Best-effort sync of latest test status into the local Obsidian vault."""
        script = PROJECT_ROOT / "scripts" / "sync_obsidian_test_results.py"
        if not script.is_file():
            return

        rc = subprocess.run(
            [sys.executable, str(script)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if rc.returncode == 0:
            if rc.stdout.strip():
                _log(rc.stdout.strip())
            return

        _log(
            f"Obsidian test-result sync skipped/failed: {(rc.stderr or rc.stdout).strip()[:300]}",
            "WARN",
        )

    def _run_apple_remote_nightly(self) -> SuiteResult:
        """Run Apple Remote nightly checks serially on the remote Mac."""
        commands = _apple_remote_commands_for_nightly()
        if not commands:
            return SuiteResult(status="skipped", reason="no Apple Remote nightly commands configured")

        script = PROJECT_ROOT / "scripts" / "apple_remote.py"
        if not script.is_file():
            return SuiteResult(
                status="failed",
                tests=[{
                    "name": "apple-remote-script",
                    "file": "scripts/apple_remote.py",
                    "status": "failed",
                    "duration_seconds": 0,
                    "error": "scripts/apple_remote.py is missing",
                }],
                reason="apple_remote.py missing",
            )

        subject_commit = _full_git_sha(self.git_sha)
        pinned_commands: list[tuple[str, tuple[str, ...]]] = []
        for name, remote_args in commands:
            args = list(remote_args)
            if name == "sync-repo" and subject_commit:
                args.extend(["--commit", subject_commit])
            elif name in {"test-ios", "test-macos", "verify-watch-startup"} and subject_commit:
                args.extend(["--expected-commit", subject_commit])
            pinned_commands.append((name, tuple(args)))
        commands = pinned_commands

        _log(f"Apple Remote: {len(commands)} command(s), serialized on one 8 GB Mac lane")
        if self.dry_run:
            for name, remote_args in commands:
                print(f"    {name}: python3 scripts/apple_remote.py {' '.join(remote_args)}")
            return SuiteResult(status="skipped", reason="dry run")

        tests: list[dict] = []
        suite_started = time.time()
        timeout = int(os.getenv("OPENMATES_APPLE_REMOTE_TIMEOUT", str(APPLE_REMOTE_TIMEOUT)))
        for name, remote_args in commands:
            command_text = f"python3 scripts/apple_remote.py {' '.join(remote_args)}"
            _log(f"  Apple Remote: {name}...")
            started = time.time()
            entry = {
                "name": name,
                "file": "scripts/apple_remote.py",
                "command": command_text,
                "duration_seconds": 0,
            }
            try:
                proc = subprocess.run(
                    [sys.executable, str(script), *remote_args],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                entry["duration_seconds"] = round(time.time() - started, 1)
                entry["exit_code"] = proc.returncode
                if proc.returncode == 0:
                    entry["status"] = "passed"
                    _log(f"  Apple Remote: {name} passed ({entry['duration_seconds']}s)", "OK")
                else:
                    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
                    entry["status"] = "failed"
                    entry["error"] = output[:MAX_ERROR_SNIPPET] if output else f"{command_text} exited {proc.returncode}"
                    _log(f"  Apple Remote: {name} failed with exit {proc.returncode}", "ERROR")
            except subprocess.TimeoutExpired as exc:
                output = "\n".join(part for part in (exc.stdout, exc.stderr) if isinstance(part, str)).strip()
                entry["duration_seconds"] = round(time.time() - started, 1)
                entry["status"] = "failed"
                entry["error"] = output[:MAX_ERROR_SNIPPET] if output else f"{command_text} timed out after {timeout}s"
                _log(f"  Apple Remote: {name} timed out after {timeout}s", "ERROR")
            tests.append(entry)

        return SuiteResult(
            status="failed" if any(test.get("status") == "failed" for test in tests) else "passed",
            tests=tests,
            duration_seconds=round(time.time() - suite_started, 1),
        )

    def _run_unit_suite_via_gha(self, workflow_file: str, artifact_name: str) -> SuiteResult:
        """Dispatch a unit test workflow to GitHub Actions, wait, download results.

        Args:
            workflow_file: GHA workflow filename (e.g. "vitest.yml")
            artifact_name: Name of the uploaded artifact (e.g. "vitest-results")

        Returns:
            SuiteResult with parsed test results from the JSON artifact.
        """
        suite_label = workflow_file.replace(".yml", "")
        _log(f"  {suite_label}: dispatching to GitHub Actions...")

        client = GitHubActionsClient()
        circuit = self._share_dispatch_circuit(client)
        refresh_budget = getattr(client, "refresh_dispatch_budget", None)
        if callable(refresh_budget):
            refresh_budget(1)
        if circuit.is_open:
            tests = []
            if circuit.claim_incident():
                tests.append({
                    "name": "github-actions-dispatch",
                    "file": "scripts/run_tests.py",
                    "status": "infrastructure_incident",
                    "duration_seconds": 0,
                    "error": circuit.incident_code,
                    "test_key": GITHUB_DISPATCH_INCIDENT_KEY,
                })
            tests.append({
                "name": f"{suite_label}-dispatch",
                "status": "blocked_by_parent",
                "duration_seconds": 0,
                "error": "Blocked by GitHub Actions dispatch infrastructure incident",
                "parent_incident_key": GITHUB_DISPATCH_INCIDENT_KEY,
            })
            return SuiteResult(status="failed", tests=tests)

        # Record pre-dispatch run IDs to find the new one
        pre_ids = client._recent_run_ids(limit=5, workflow=workflow_file)

        dispatch_command = [
            "gh", "workflow", "run", workflow_file,
            "--repo", GH_REPO,
            "--ref", GH_BRANCH,
            "-f", f"checkout_ref={_full_git_sha(getattr(self, 'git_sha', ''))}",
        ]
        if self.campaign_test_labels and workflow_file in {"pytest-unit.yml", "vitest.yml"}:
            input_name = "test_targets_json" if workflow_file == "pytest-unit.yml" else "test_files_json"
            dispatch_command.extend(["-f", f"{input_name}={json.dumps(self.campaign_test_labels, separators=(',', ':'))}"])
        circuit.wait_for_mutating_request_slot()
        rc = subprocess.run(
            dispatch_command,
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            detail = (rc.stderr or rc.stdout or "unknown gh workflow error").strip()[:500]
            if _is_github_rate_limit_error(detail):
                circuit.open_rate_limit()
                tests = []
                if circuit.claim_incident():
                    tests.append({
                        "name": "github-actions-dispatch",
                        "file": "scripts/run_tests.py",
                        "status": "infrastructure_incident",
                        "duration_seconds": 0,
                        "error": circuit.incident_code,
                        "test_key": GITHUB_DISPATCH_INCIDENT_KEY,
                    })
                tests.append({
                    "name": f"{suite_label}-dispatch",
                    "status": "blocked_by_parent",
                    "duration_seconds": 0,
                    "error": "Blocked by GitHub Actions dispatch infrastructure incident",
                    "parent_incident_key": GITHUB_DISPATCH_INCIDENT_KEY,
                })
                _log(f"  {suite_label}: GitHub Actions dispatch rate-limited", "ERROR")
                return SuiteResult(status="failed", tests=tests)
            category = github_dispatch_error_category(detail)
            safe_error = f"GitHub Actions workflow dispatch failed ({category})"
            _log(f"  {suite_label}: {safe_error}", "ERROR")
            return SuiteResult(
                status="failed",
                tests=[{"name": f"{suite_label}-dispatch", "status": "dispatch_error",
                        "duration_seconds": 0, "error": safe_error}],
            )

        # Find the new run ID
        time.sleep(5)
        run_id = None
        for attempt in range(10):
            post_ids = client._recent_run_ids(limit=10, workflow=workflow_file)
            new_ids = [rid for rid in post_ids if rid not in pre_ids]
            if new_ids:
                run_id = new_ids[0]
                break
            time.sleep(3)

        if not run_id:
            _log(f"  {suite_label}: could not find dispatched run", "ERROR")
            return SuiteResult(
                status="failed",
                tests=[{"name": f"{suite_label}-dispatch", "status": "dispatch_error",
                        "duration_seconds": 0, "error": "Could not find dispatched workflow run"}],
            )

        _log(f"  {suite_label}: waiting for run {run_id}...")
        statuses = client.wait_for_runs([run_id], fail_fast=False)

        status_data = statuses.get(run_id, {})
        conclusion = status_data.get("conclusion", "unknown")
        _log(f"  {suite_label}: run {run_id} → {conclusion}")

        # Download artifact with JSON results
        artifact_dir = Path(tempfile.mkdtemp(prefix=f"{suite_label}-artifacts-"))
        art_path = client.download_artifact(run_id, artifact_name, artifact_dir)

        all_tests: list[dict] = []
        overall_status = "passed" if conclusion == "success" else "failed"

        if art_path:
            all_tests = self._parse_unit_test_artifact(art_path, suite_label)

        if conclusion != "success" and not any(
            _is_problem_status(test.get("status", "")) for test in all_tests
        ):
            log_error = client.get_failed_job_error(run_id)
            all_tests.append({"name": f"{suite_label}-run", "status": "failed",
                              "duration_seconds": 0, "error": log_error or f"Run failed: {conclusion}"})

        if any(_is_problem_status(test.get("status", "")) for test in all_tests):
            overall_status = "failed"

        shutil.rmtree(artifact_dir, ignore_errors=True)

        passed = sum(1 for t in all_tests if t.get("status") == "passed")
        _log(f"  {suite_label}: {passed}/{len(all_tests)} passed")

        return SuiteResult(status=overall_status, tests=all_tests)

    @staticmethod
    def _parse_unit_test_artifact(art_path: Path, suite_label: str) -> list[dict]:
        """Parse unit test results from downloaded GHA artifact.

        Handles both vitest JSON (testResults[].assertionResults[]) and
        pytest-json-report (tests[]) formats.
        """
        all_tests: list[dict] = []

        # Find all JSON result files
        json_files = sorted(art_path.rglob("*.json"))

        for jf in json_files:
            try:
                raw = jf.read_text(encoding="utf-8", errors="replace")
                # Vitest/pytest JSON output may have non-JSON prefix (SvelteKit warnings).
                # Try direct parse first, then look for known JSON markers.
                data = None
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    # Look for vitest marker: "numTotalTestSuites"
                    # or pytest marker: "tests"
                    for marker in ('"numTotalTestSuites"', '"created"'):
                        idx = raw.find(marker)
                        if idx >= 0:
                            brace_idx = raw.rfind("{", 0, idx)
                            json_end = raw.rfind("}")
                            if brace_idx >= 0 and json_end > brace_idx:
                                try:
                                    data = json.loads(raw[brace_idx:json_end + 1])
                                    break
                                except json.JSONDecodeError:
                                    continue
                if data is None:
                    continue
            except (json.JSONDecodeError, OSError):
                continue

            # Vitest format: { testResults: [{ assertionResults: [...] }] }
            if "testResults" in data:
                for tf in data.get("testResults", []):
                    assertion_results = tf.get("assertionResults", [])
                    for ar in assertion_results:
                        name = ar.get("fullName", ar.get("title", "unknown"))
                        status = "passed" if ar.get("status") == "passed" else "failed"
                        test_dur = ar.get("duration", 0) / 1000.0
                        entry: dict = {
                            "name": name,
                            "status": status,
                            "duration_seconds": round(test_dur, 3),
                        }
                        if tf.get("name"):
                            entry["file"] = tf["name"]
                        if status == "failed":
                            msgs = ar.get("failureMessages", [])
                            if msgs:
                                entry["error"] = msgs[0][:MAX_ERROR_SNIPPET]
                        all_tests.append(entry)
                    if tf.get("status") == "failed" and not assertion_results:
                        name = tf.get("name", "unknown")
                        all_tests.append({
                            "name": name,
                            "file": name,
                            "status": "failed",
                            "duration_seconds": 0,
                            "error": str(tf.get("message") or "Vitest suite failed during collection")[:MAX_ERROR_SNIPPET],
                        })

            # Pytest-json-report format: { tests: [{ nodeid, outcome, call: { longrepr } }] }
            elif "tests" in data:
                for t in data.get("tests", []):
                    name = t.get("nodeid", "unknown")
                    outcome = t.get("outcome", "")
                    duration = t.get("duration", 0)
                    entry = {
                        "name": name,
                        "status": "passed" if outcome == "passed" else "failed" if outcome == "failed" else "skipped",
                        "duration_seconds": round(duration, 3),
                    }
                    if outcome == "failed":
                        call = t.get("call", {})
                        longrepr = call.get("longrepr", "")
                        if longrepr:
                            entry["error"] = str(longrepr)[:MAX_ERROR_SNIPPET]
                    all_tests.append(entry)

        for txt_file in sorted(art_path.rglob("cli-account-import-tests.txt")):
            try:
                content = txt_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parsed_node_tests = 0
            expected_node_tests = None
            for line in content.splitlines():
                summary_match = re.match(r"^ℹ tests (\d+)$", line)
                if summary_match:
                    expected_node_tests = int(summary_match.group(1))
                    continue
                match = re.match(r"^\s{2}([✔✖])\s+(.+?)\s+\(([\d.]+)ms\)$", line)
                if not match:
                    continue
                parsed_node_tests += 1
                status = "passed" if match.group(1) == "✔" else "failed"
                entry = {
                    "name": match.group(2),
                    "status": status,
                    "duration_seconds": round(float(match.group(3)) / 1000, 3),
                }
                if status == "failed":
                    entry["error"] = "Node test failed; see cli-account-import-tests.txt"
                all_tests.append(entry)
            if expected_node_tests is not None and parsed_node_tests != expected_node_tests:
                all_tests.append({
                    "name": "cli-account-import-results",
                    "status": "failed",
                    "duration_seconds": 0,
                    "error": f"Parsed {parsed_node_tests} of {expected_node_tests} Node test results",
                })

        # Fallback: parse pytest verbose text output (test::name PASSED/FAILED lines)
        if not all_tests:
            for txt_file in sorted(art_path.rglob("*.txt")):
                try:
                    content = txt_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line in content.splitlines():
                    m = re.match(r"^(\S+::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)", line)
                    if m:
                        name = m.group(1)
                        result_str = m.group(2)
                        status = ("passed" if result_str == "PASSED"
                                  else "failed" if result_str in ("FAILED", "ERROR")
                                  else "skipped")
                        all_tests.append({"name": name, "status": status, "duration_seconds": 0})

        return all_tests

    @contextmanager
    def _dev_runtime_read_lease(self, phase: str):
        if (
            not getattr(self, "coordinate_runtime", False)
            or self.environment == "production"
            or os.environ.get("OPENMATES_DOCKER_TEST_LEASE_HELD") == "1"
        ):
            yield
            return
        lease_id = f"runner-{phase}-{os.getpid()}-{uuid4().hex[:8]}"
        owner = os.environ.get("OPENCODE_SESSION_ID", "local-test-runner")
        resources = {session_control.DOCKER_RESOURCE_DEV_STACK}
        session_control.acquire_test_resource_lease(
            lease_id,
            owner,
            resources,
            mode="shared",
        )
        stop = threading.Event()

        def heartbeat() -> None:
            while not stop.wait(session_control.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                session_control.renew_test_resource_lease(lease_id, owner, resources, mode="shared")

        thread = threading.Thread(target=heartbeat, name=f"{phase}-runtime-lease", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=1)
            session_control.release_test_resource_lease(lease_id)

    def _run_playwright(self) -> SuiteResult:
        with self._dev_runtime_read_lease("playwright"):
            return self._run_playwright_with_runtime()

    def _run_playwright_with_runtime(self) -> SuiteResult:
        """Run Playwright specs via GitHub Actions."""
        try:
            specs = self._discover_specs()
        except RuntimeError as exc:
            reason = str(exc)
            return SuiteResult(
                status="failed",
                tests=[{
                    "name": self.spec or "playwright-spec-discovery",
                    "file": self.spec or "playwright-spec-discovery",
                    "status": "dispatch_error",
                    "duration_seconds": 0,
                    "error": reason,
                }],
                reason=reason,
            )
        only_failed = bool(getattr(self, "only_failed", False))
        only_failed_synthetic_files = getattr(self, "only_failed_synthetic_files", set())
        clear_backend_mock_preflight = (
            only_failed
            and BACKEND_LIVE_MOCK_PREFLIGHT_FILE in only_failed_synthetic_files
        )

        if not specs and not clear_backend_mock_preflight:
            return SuiteResult(status="skipped", reason="no specs to run")

        account_requirements_ref = self.git_sha if self.environment == "development" else None
        requires_account_by_spec = _playwright_account_requirements_for_specs(
            specs,
            account_requirements_ref,
        )
        account_free_specs = [spec for spec in specs if not requires_account_by_spec.get(spec, True)]
        if account_free_specs:
            _log(
                "Playwright account-free dispatch: "
                f"{len(account_free_specs)} spec(s) skip account preflight and credentials"
            )

        effective_batch_size = _effective_playwright_batch_size(self.max_concurrent)
        _log(f"Playwright: {len(specs)} spec(s) via GitHub Actions (batch size: {effective_batch_size})")

        if self.dry_run:
            _log("Dry run — would dispatch these specs:")
            plan_account_slots = (self.account,) if self.account is not None else NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS
            for _batch_idx, spec, account in build_playwright_dispatch_plan(
                specs,
                self.max_concurrent,
                plan_account_slots,
                requires_account_by_spec,
            ):
                if not requires_account_by_spec.get(spec, True):
                    print(f"    account-free  {spec}")
                    continue
                reserved = " reserved" if spec in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC else ""
                print(f"    account {account:02d}{reserved}  {spec}")
            return SuiteResult(status="skipped", reason="dry run")

        synthetic_preflight_results: list[dict] = []
        if self.environment == "development" and self.use_mocks:
            backend_mock_error = _development_backend_live_mock_preflight_error()
            if backend_mock_error:
                return SuiteResult(
                    status="failed",
                    tests=[
                        {
                            "name": BACKEND_LIVE_MOCK_PREFLIGHT_NAME,
                            "file": BACKEND_LIVE_MOCK_PREFLIGHT_FILE,
                            "status": "failed",
                            "duration_seconds": 0,
                            "error": backend_mock_error,
                        },
                        *_not_started_playwright_specs(specs, backend_mock_error),
                    ],
                    reason=backend_mock_error,
                )
            if clear_backend_mock_preflight:
                synthetic_preflight_results.append({
                    "name": BACKEND_LIVE_MOCK_PREFLIGHT_NAME,
                    "file": BACKEND_LIVE_MOCK_PREFLIGHT_FILE,
                    "status": "passed",
                    "duration_seconds": 0,
                })

        if not specs:
            return SuiteResult(
                status="passed" if synthetic_preflight_results else "skipped",
                tests=synthetic_preflight_results,
                reason=None if synthetic_preflight_results else "no specs to run",
            )

        if self.environment == "development":
            deployment_ready, deployment_reason = _wait_for_vercel_deployment(self.git_sha, self.dot_env)
            if deployment_ready:
                deployment_reason = ""
            else:
                gate_error = deployment_reason or "Vercel deployment was not ready before Playwright dispatch"
                return SuiteResult(
                    status="failed",
                    tests=[
                        {
                            "name": "vercel-deployment-gate",
                            "status": "failed",
                            "duration_seconds": 0,
                            "error": gate_error,
                        },
                        *_not_started_playwright_specs(specs, gate_error),
                    ],
                    reason=gate_error,
                )

        client = GitHubActionsClient(
            git_sha=_full_git_sha(self.git_sha) if self.environment == "development" else None,
        )
        self._share_dispatch_circuit(client)

        blocked_preflight_results: list[SpecResult] = []
        preflight_reason: Optional[str] = None
        normal_account_slots = NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS
        account_required_specs = [spec for spec in specs if requires_account_by_spec.get(spec, True)]

        if not self.spec:
            if account_required_specs:
                preflight_accounts = _preflight_accounts_for_specs(
                    specs,
                    self.max_concurrent,
                    requires_account_by_spec,
                )
                preflight = self._run_account_preflight(client, accounts=preflight_accounts)
                preflight_results = [self._dict_to_spec_result(test) for test in preflight.tests]
                specs, blocked_preflight_results, normal_account_slots, preflight_reason = (
                    _apply_preflight_account_availability(
                        specs,
                        preflight_results,
                        requires_account_by_spec,
                    )
                )
                account_required_specs = [spec for spec in specs if requires_account_by_spec.get(spec, True)]
                if not normal_account_slots and account_required_specs:
                    return SuiteResult(
                        status="failed",
                        tests=[BatchRunner._spec_result_to_dict(result) for result in blocked_preflight_results],
                        duration_seconds=preflight.duration_seconds,
                        reason=(preflight_reason or "No available normal Playwright account slots"),
                    )
                if preflight_reason:
                    _log(f"Account preflight limited dispatch: {preflight_reason}", "WARN")
            else:
                _log("Playwright account preflight skipped: all selected specs are account-free")
        elif self.spec == ACCOUNT_PREFLIGHT_SPEC and self.account is not None:
            return self._run_account_preflight(client, accounts=[self.account])
        elif self.spec and self.spec != ACCOUNT_PREFLIGHT_SPEC:
            if not requires_account_by_spec.get(self.spec, True):
                if self.account is not None:
                    _log(f"{self.spec} is account-free; ignoring --account {self.account}", "WARN")
            else:
                reserved_account = RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC.get(self.spec)
                if self.account is not None and reserved_account is not None and self.account != reserved_account:
                    return SuiteResult(
                        status="failed",
                        tests=[{
                            "name": self.spec,
                            "status": "failed",
                            "duration_seconds": 0,
                            "error": f"{self.spec} requires reserved account slot {reserved_account}; received --account {self.account}",
                        }],
                        reason=f"Reserved-account spec requires slot {reserved_account}",
                    )

                account = self.account if self.account is not None else _account_for_spec_in_batch(self.spec, 0)
                preflight = self._run_account_preflight(client, accounts=[account])
                if preflight.status == "failed":
                    if self.account is not None or self.spec in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC:
                        return preflight

                    fallback_accounts = _single_spec_fallback_accounts(account)
                    fallback_preflight = self._run_account_preflight(client, accounts=fallback_accounts)
                    fallback_slots = _passed_normal_preflight_slots([
                        self._dict_to_spec_result(test)
                        for test in fallback_preflight.tests
                    ])
                    if not fallback_slots:
                        return SuiteResult(
                            status="failed",
                            tests=[*preflight.tests, *fallback_preflight.tests],
                            duration_seconds=round(preflight.duration_seconds + fallback_preflight.duration_seconds, 1),
                            reason="No healthy normal Playwright account slots after single-spec preflight fallback",
                        )

                    normal_account_slots = (fallback_slots[0],)
                    preflight_reason = (
                        f"Selected normal account slot {account} failed preflight; "
                        f"using fallback slot {fallback_slots[0]} for {self.spec}"
                    )
                    _log(preflight_reason, "WARN")
                else:
                    normal_account_slots = (account,)

        try:
            seeded_gift_cards = _seed_playwright_fixtures_for_specs(specs, self.environment)
        except RuntimeError as exc:
            fixture_error = str(exc)
            return SuiteResult(
                status="failed",
                tests=[
                    {
                        "name": "playwright-fixture-seed",
                        "file": "scripts/run_tests.py",
                        "status": "failed",
                        "duration_seconds": 0,
                        "error": fixture_error,
                    },
                    *_not_started_playwright_specs(specs, fixture_error),
                ],
                reason=fixture_error,
            )

        runner = BatchRunner(
            client=client,
            specs=specs,
            batch_size=self.max_concurrent,
            fail_fast=self.fail_fast,
            use_mocks=self.use_mocks,
            record_live_fixtures=self.record_live_fixtures,
            normal_account_slots=normal_account_slots,
            create_account_slot=self.create_account_slot,
            allow_credential_updates=not bool(getattr(self, "core_journeys", False)),
            seeded_gift_cards=seeded_gift_cards,
            proof_video_profile=self.proof_video_profile,
            daily_ai_run_id=(
                f"daily_canary_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
                if getattr(self, "daily", False)
                else ""
            ),
            requires_account_by_spec=requires_account_by_spec,
            progress_callback=self._save_playwright_progress_snapshot,
            coordinate_accounts=self.account is None,
        )

        try:
            if getattr(self, "daily", False) and not self.spec:
                registry_issues = audit_critical_test_registry()
                phases = daily_playwright_phases(specs)

                def run_daily_phase(phase: str, phase_specs: list[str]) -> SuiteResult:
                    self.current_phase = f"Playwright {phase}"
                    runner.specs = phase_specs
                    runner.fail_fast = False
                    return runner.run_all_batches()

                phase_results = execute_daily_playwright_phases(phases, run_daily_phase, registry_issues)
                critical_result = phase_results["critical"]
                self.critical_phase = {
                    "status": "failed" if registry_issues else critical_result.status,
                    "spec_count": len(phases["critical"]),
                }
                if registry_issues:
                    self.critical_phase["reason"] = "registry_audit_failed"
                broad_result = phase_results["broad"]
                registry_result = phase_results.get("registry")
                combined_tests = [
                    *(registry_result.tests if registry_result else []),
                    *critical_result.tests,
                    *broad_result.tests,
                ]
                incident_seen = False
                deduplicated_tests = []
                for test in combined_tests:
                    if test.get("status") == "infrastructure_incident":
                        if incident_seen:
                            continue
                        incident_seen = True
                    deduplicated_tests.append(test)
                result = SuiteResult(
                    status="failed" if any(_is_problem_status(str(test.get("status") or "")) for test in deduplicated_tests) else "passed",
                    tests=deduplicated_tests,
                    duration_seconds=round(critical_result.duration_seconds + broad_result.duration_seconds, 1),
                    reason=registry_result.reason if registry_result else None,
                )
            else:
                result = runner.run_all_batches()
        finally:
            _cleanup_e2e_gift_cards(seeded_gift_cards)

        if blocked_preflight_results:
            result.tests = [
                BatchRunner._spec_result_to_dict(blocked_result)
                for blocked_result in blocked_preflight_results
            ] + result.tests
            result.status = "failed"
        if synthetic_preflight_results:
            result.tests = synthetic_preflight_results + result.tests
        if preflight_reason:
            result.reason = (
                f"{preflight_reason}; {result.reason}"
                if result.reason else preflight_reason
            )

        # Aggregate storage-audit snapshots into review candidates outside the
        # tracked checkout. Runtime/test worktrees must remain immutable.
        # Skipped for single-spec runs (--spec) since coverage is intentionally
        # narrow and would not produce a representative inventory. The merger
        # preserves unobserved entries and human-maintained fields.
        if not self.spec:
            self._merge_cookie_audits()

        return result

    def _run_cli_integration(self) -> SuiteResult:
        with self._dev_runtime_read_lease("cli"):
            return self._run_cli_integration_with_runtime()

    def _run_cli_integration_with_runtime(self) -> SuiteResult:
        """Run CLI integration checks through a registered GitHub Actions workflow.

        GitHub only allows dispatching workflow files that already exist on the
        repository default branch. Reusing the registered single-spec workflow
        keeps `--suite cli` first-class on dev branches while the workflow step
        runs the standalone CLI script rather than Playwright.
        """
        _log("CLI integration: dispatching via GitHub Actions...")

        if self.dry_run:
            _log(f"Dry run — would dispatch {CLI_INTEGRATION_SPEC}")
            return SuiteResult(status="skipped", reason="dry run")

        client = GitHubActionsClient(
            git_sha=_full_git_sha(self.git_sha) if self.environment == "development" else None,
        )
        self._share_dispatch_circuit(client)
        account = NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS[0]
        preflight_reason: Optional[str] = None
        preflight_duration = 0.0
        preflight = self._run_account_preflight(client, accounts=[account])
        preflight_duration += preflight.duration_seconds
        if preflight.status == "failed":
            fallback_accounts = _single_spec_fallback_accounts(account)
            fallback_preflight = self._run_account_preflight(client, accounts=fallback_accounts)
            preflight_duration += fallback_preflight.duration_seconds
            fallback_slots = _passed_normal_preflight_slots([
                self._dict_to_spec_result(test)
                for test in fallback_preflight.tests
            ])
            if not fallback_slots:
                return SuiteResult(
                    status="failed",
                    tests=[*preflight.tests, *fallback_preflight.tests],
                    duration_seconds=round(preflight.duration_seconds + fallback_preflight.duration_seconds, 1),
                    reason="No healthy normal Playwright account slots for CLI integration",
                )

            preflight_reason = (
                f"Selected normal account slot {account} failed preflight; "
                f"using fallback slot {fallback_slots[0]} for CLI integration"
            )
            _log(preflight_reason, "WARN")
            account = fallback_slots[0]

        run_id = client.dispatch_spec(
            CLI_INTEGRATION_SPEC,
            account=account,
            use_mocks=self.use_mocks,
            record_live_fixtures=self.record_live_fixtures,
        )
        if run_id is None:
            detail = client.last_dispatch_error or "Could not dispatch CLI integration workflow"
            return SuiteResult(
                status="failed",
                tests=[{
                    "name": "cli-integration-dispatch",
                    "status": "dispatch_error",
                    "duration_seconds": 0,
                    "error": detail,
                }],
            )

        _log(f"  CLI integration: waiting for run {run_id}...")
        statuses = client.wait_for_runs([run_id], fail_fast=False)
        conclusion = statuses.get(run_id, {}).get("conclusion", "unknown")
        _log(f"  CLI integration: run {run_id} → {conclusion}")

        artifact_dir = Path(tempfile.mkdtemp(prefix="cli-integration-artifacts-"))
        artifact_name = f"playwright-{CLI_INTEGRATION_SPEC.replace('/', '-')}"
        artifact_path = client.download_artifact(run_id, artifact_name, artifact_dir)

        tests: list[dict] = []
        if artifact_path:
            tests = self._parse_unit_test_artifact(artifact_path, "cli-integration")

        if not tests:
            log_error = client.get_failed_job_error(run_id)
            tests = [{
                "name": "cli-integration-run",
                "status": "failed" if conclusion != "success" else "error",
                "duration_seconds": 0,
                "error": log_error or f"CLI integration produced no parseable result artifact; run conclusion: {conclusion}",
            }]

        has_failures = any(_is_problem_status(test.get("status", "")) for test in tests)
        overall_status = "failed" if conclusion != "success" or has_failures else "passed"
        shutil.rmtree(artifact_dir, ignore_errors=True)

        if overall_status == "passed":
            tests = [{
                "name": ACCOUNT_PREFLIGHT_SPEC,
                "file": ACCOUNT_PREFLIGHT_SPEC,
                "status": "passed",
                "duration_seconds": round(preflight_duration, 1),
            }, *tests]

        passed = sum(1 for test in tests if test.get("status") == "passed")
        _log(f"  CLI integration: {passed}/{len(tests)} passed")

        result = SuiteResult(status=overall_status, tests=tests)
        if preflight_reason:
            result.reason = preflight_reason
        return result

    @staticmethod
    def _dict_to_spec_result(data: dict) -> SpecResult:
        """Rehydrate a serialized spec result for account-planning helpers."""
        return SpecResult(
            name=str(data.get("name", "")),
            file=data.get("file"),
            status=str(data.get("status", "")),
            duration_seconds=float(data.get("duration_seconds", 0) or 0),
            error=data.get("error"),
            run_id=data.get("run_id"),
            account=data.get("account"),
            account_email=data.get("account_email"),
        )

    def _run_account_preflight(
        self,
        client: GitHubActionsClient,
        accounts: Optional[list[int]] = None,
    ) -> SuiteResult:
        """Validate each configured persistent E2E account before normal specs."""
        started = time.time()
        target_accounts = accounts or list(range(1, MAX_ACCOUNTS + 1))
        cache_allowed = self.spec not in RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC
        cached_slots = _cached_preflight_slots() if cache_allowed else set()
        cached_accounts = [account for account in target_accounts if account in cached_slots]
        pending_accounts = [account for account in target_accounts if account not in cached_slots]
        _log(
            f"Playwright account preflight: {len(target_accounts)} account slot(s) "
            f"({len(cached_accounts)} cached, {len(pending_accounts)} live)"
        )
        runner = BatchRunner(
            client=client,
            specs=[ACCOUNT_PREFLIGHT_SPEC] * len(target_accounts),
            batch_size=len(target_accounts),
            fail_fast=False,
            use_mocks=self.use_mocks,
        )
        results = [
            SpecResult(
                name=ACCOUNT_PREFLIGHT_SPEC,
                file=ACCOUNT_PREFLIGHT_SPEC,
                status="passed",
                account=account,
                duration_seconds=0,
            )
            for account in cached_accounts
        ]
        live_results = runner._run_batch(
            [ACCOUNT_PREFLIGHT_SPEC] * len(pending_accounts),
            0,
            account_overrides=pending_accounts,
        ) if pending_accounts else []
        results.extend(live_results)
        if self._repair_missing_preflight_account_ids(live_results):
            _log("Playwright account preflight: rerunning repaired account slot(s)")
            live_results = runner._run_batch(
                [ACCOUNT_PREFLIGHT_SPEC] * len(pending_accounts),
                0,
                account_overrides=pending_accounts,
            )
            results = [result for result in results if result.account in cached_accounts] + live_results
        failures = [r for r in results if r.status != "passed"]
        if failures:
            failed_slots = ", ".join(str(r.account) for r in failures)
            _log(f"Account preflight failed for slot(s): {failed_slots}", "ERROR")
        else:
            failed_slots = ""
            _log("Account preflight passed", "OK")

        credit_guard_error = self._ensure_preflight_account_credits(results)
        if credit_guard_error:
            return SuiteResult(
                status="failed",
                tests=[runner._spec_result_to_dict(r) for r in results],
                duration_seconds=round(time.time() - started, 1),
                reason=credit_guard_error,
            )

        _update_preflight_cache(
            {int(result.account) for result in results if result.status == "passed" and result.account is not None},
            {int(result.account) for result in failures if result.account is not None},
        )

        return SuiteResult(
            status="failed" if failures else "passed",
            tests=[runner._spec_result_to_dict(r) for r in results],
            duration_seconds=round(time.time() - started, 1),
            reason=f"Account preflight failed for slot(s): {failed_slots}" if failures else None,
        )

    def _repair_missing_preflight_account_ids(self, results: list[SpecResult]) -> bool:
        """Repair configured E2E accounts that fail preflight due to missing account_id."""
        if self.environment != "development":
            return False

        missing_account_id_results = [
            result for result in results
            if result.status != "passed"
            and "users.account_id" in " ".join(
                part for part in (result.error, result.debug_output_summary) if part
            )
        ]
        if not missing_account_id_results:
            return False

        accounts = _configured_preflight_accounts(missing_account_id_results)
        if not accounts:
            _log("E2E account_id repair skipped: failed preflight did not expose configured account email", "WARN")
            return False

        script_path = PROJECT_ROOT / "backend" / "scripts" / "repair_test_account_account_ids.py"
        try:
            script_source = script_path.read_text(encoding="utf-8")
        except OSError as exc:
            _log(f"E2E account_id repair skipped: repair script unavailable: {exc}", "ERROR")
            return False

        runner_source = (
            "import json, os, runpy, sys, tempfile\n"
            "payload = json.load(sys.stdin)\n"
            "with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as handle:\n"
            "    handle.write(payload['script'])\n"
            "    script_path = handle.name\n"
            "try:\n"
            "    sys.argv = [script_path, '--accounts-json', json.dumps(payload['accounts'])]\n"
            "    runpy.run_path(script_path, run_name='__main__')\n"
            "finally:\n"
            "    os.unlink(script_path)\n"
        )
        try:
            proc = subprocess.run(
                ["docker", "exec", "-i", "api", "python", "-c", runner_source],
                input=json.dumps({"script": script_source, "accounts": accounts}),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log(f"E2E account_id repair failed to execute: {exc}", "ERROR")
            return False
        output = (proc.stdout or "").strip()
        if output:
            for line in output.splitlines():
                _log(f"E2E account_id repair: {line}")
        if proc.returncode != 0:
            detail = (proc.stderr or output or "unknown error").strip()[:MAX_ERROR_SNIPPET]
            _log(f"E2E account_id repair failed: {detail}", "ERROR")
            return False
        return True

    @staticmethod
    def _ensure_preflight_account_credits(results: list[SpecResult]) -> Optional[str]:
        """Top up configured E2E accounts discovered by account preflight."""
        if os.getenv("OPENMATES_E2E_CREDIT_GUARD", "1") in {"0", "false", "False"}:
            _log("E2E credit guard disabled via OPENMATES_E2E_CREDIT_GUARD", "WARN")
            return None

        accounts = _configured_preflight_accounts(results)
        missing_slots = [str(r.account) for r in results if r.account and not r.account_email]
        if missing_slots:
            _log(
                "E2E credit guard: no configured credentials discovered for slot(s): "
                + ", ".join(missing_slots),
                "WARN",
            )
        if not accounts:
            _log("E2E credit guard: no configured accounts discovered", "WARN")
            return None

        minimum = int(os.getenv("OPENMATES_E2E_CREDIT_MINIMUM", str(E2E_CREDIT_GUARD_DEFAULT_MINIMUM)))
        target = int(os.getenv("OPENMATES_E2E_CREDIT_TARGET", str(E2E_CREDIT_GUARD_DEFAULT_TARGET)))
        script_path = PROJECT_ROOT / "backend" / "scripts" / "top_up_test_account_credits.py"
        try:
            script_source = script_path.read_text(encoding="utf-8")
        except OSError as exc:
            detail = f"credit guard script unavailable: {exc}"
            _log(f"E2E credit guard failed: {detail}", "ERROR")
            return f"E2E credit guard failed: {detail}"

        proc = subprocess.run(
            [
                "docker", "exec", "-i", "api", "python", "-",
                "--accounts-json", json.dumps(accounts),
                "--minimum", str(minimum),
                "--target", str(target),
            ],
            input=script_source,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output = (proc.stdout or "").strip()
        if output:
            for line in output.splitlines():
                _log(f"E2E credit guard: {line}")
        if proc.returncode != 0:
            detail = (proc.stderr or output or "unknown error").strip()[:MAX_ERROR_SNIPPET]
            _log(f"E2E credit guard failed: {detail}", "ERROR")
            return f"E2E credit guard failed: {detail}"
        return None

    @staticmethod
    def _merge_cookie_audits() -> None:
        """Generate reviewable storage inventories without dirtying source."""
        merger = PROJECT_ROOT / "scripts" / "merge_storage_audits.py"
        if not merger.is_file():
            return
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(merger),
                    "--output-dir",
                    str(STORAGE_AUDIT_CANDIDATE_DIR),
                    "--retain-unobserved",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
            # Merger writes its summary to stderr.
            if proc.stderr:
                for line in proc.stderr.rstrip().splitlines():
                    _log(line)
            if proc.returncode != 0:
                _log(f"merge_storage_audits exited {proc.returncode}", "WARN")
        except Exception as e:
            _log(f"merge_storage_audits failed to run: {e}", "WARN")

    # Canonical policy also keeps costly real-inference scenarios manual-only.
    EXCLUDED_SPECS = daily_ai_test_policy.excluded_specs()

    def _discover_specs(self) -> list[str]:
        """Find which specs to run."""
        if self.spec:
            validation_error = _validate_requested_playwright_spec(
                self.spec,
                getattr(self, "git_sha", None),
            )
            if validation_error:
                raise RuntimeError(validation_error)
            return [self.spec]

        if self.core_journeys:
            return list(RELEASE_GATE_SPECS)

        if self.critical_journeys:
            issues = audit_critical_test_registry()
            if issues:
                raise RuntimeError("; ".join(issues))
            return [str(entry["spec"]) for entry in CRITICAL_TEST_REGISTRY if entry.get("active") is True]

        if self.only_failed:
            failed = ResultAggregator.load_failed_specs()
            self.only_failed_synthetic_files = tuple(f for f in failed if not f.endswith(".spec.ts"))
            # Filter to only .spec.ts files
            specs = [f for f in failed if f.endswith(".spec.ts")]
            if specs:
                _log(f"Found {len(specs)} previously failed spec(s)")
            return specs

        # All ordinary specs, minus manual utility/proof/expensive policy entries.
        spec_files = sorted(SPEC_DIR.glob("*.spec.ts"))
        specs = daily_ai_test_policy.discover_specs(
            (file.name for file in spec_files), spec_dir=SPEC_DIR
        )
        if not self.daily:
            return specs

        canaries = daily_ai_test_policy.daily_plan(
            (file.name for file in spec_files),
            datetime.now(timezone.utc).date(),
            scheduled=True,
            record_mode=self.record_live_fixtures,
        )
        return [*specs, *(spec for spec in canaries.selected if spec not in specs)]

    def _daily_gate(self) -> bool:
        """Check if daily run should proceed. Returns False to skip."""
        # Env gate
        if _get_env("E2E_DAILY_RUN_ENABLED", self.notification.dot_env) != "true":
            _log("E2E_DAILY_RUN_ENABLED is not set — skipping test run")
            _log("Set E2E_DAILY_RUN_ENABLED=true on the dev server to enable tests")
            self.notification.send_daily_skip_notification(
                self.git_sha,
                self.git_branch,
                self.environment,
                self.run_id,
                "E2E_DAILY_RUN_ENABLED is disabled.",
            )
            return False

        # Commit-activity gate
        if not self.force:
            try:
                commits = subprocess.check_output(
                    [
                        "git", "-C", str(PROJECT_ROOT), "log", "--oneline",
                        "--since=24 hours ago", self.git_sha if self.git_sha != "unknown" else "HEAD",
                    ],
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()
                count = len(commits.splitlines()) if commits else 0
            except Exception:
                count = 0

            if count == 0:
                _log("No git commits in the last 24 hours — skipping test run")
                _log("Use --force to run regardless")
                self.notification.send_daily_skip_notification(
                    self.git_sha,
                    self.git_branch,
                    self.environment,
                    self.run_id,
                    "No git commits in the last 24 hours.",
                )
                return False
            _log(f"Found {count} commit(s) in last 24 hours — proceeding")

        return True

    def _daily_post_run(self, result: RunResult) -> None:
        """Post-run tasks for daily mode: split results, archive, reports, notify."""
        # Split results
        self.notification.split_results()

        # Generate structured MD reports
        _log("Generating MD reports...")
        ReportGenerator().generate(result)

        # Push to OpenObserve
        _log("Pushing to OpenObserve...")
        self.notification.push_to_openobserve(result)

        # Bound daily JSON and screenshot growth to one week. The canonical
        # latest results remain separate from these dated archives.
        archives = sorted(RESULTS_DIR.glob("daily-run-*.json"), reverse=True)
        for old in archives[DAILY_ARTIFACT_RETENTION_DAYS:]:
            old.unlink(missing_ok=True)

        # Prune old screenshot archives (keep last 7 daily snapshots).
        screenshots_dir = RESULTS_DIR / "screenshots"
        if screenshots_dir.is_dir():
            date_dirs = sorted(
                [d for d in screenshots_dir.iterdir()
                 if d.is_dir() and d.name != "current" and len(d.name) == 10],
                reverse=True,
            )
            for old_dir in date_dirs[DAILY_ARTIFACT_RETENTION_DAYS:]:
                shutil.rmtree(old_dir, ignore_errors=True)
                _log(f"Pruned old screenshot archive: {old_dir.name}")

        # Keep daily runs notification-only. Follow-up fixing must be started
        # separately so one day's remediation can never hold tomorrow's lock.
        _log("Sending summary email...")
        result.flags["notifications_complete"] = bool(self.notification.send_summary_email(result))
        ResultAggregator.save(result)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archive = RESULTS_DIR / f"daily-run-{today}.json"
        last_run = RESULTS_DIR / "last-run.json"
        if last_run.is_file():
            shutil.copy2(str(last_run), str(archive))
            _log(f"Archived to {archive.name}")
        if _problem_count(result.summary) > 0:
            _log("Daily auto-fix disabled; use scripts/auto_fix_failed_tests.py manually if needed")

    def _print_summary(self, result: RunResult) -> None:
        """Print a formatted summary."""
        s = result.summary
        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        print()
        print("=" * 60)
        problem_count = _problem_count(s)
        status_icon = "✓" if problem_count == 0 else "✗"
        print(f"  {status_icon} Summary")
        print("=" * 60)
        print(f"  Total: {s['total']}  Passed: {s['passed']}  Failed: {s['failed']}  "
              f"Dispatch errors: {s.get('dispatch_error', 0)}  Skipped: {s['skipped']}  "
              f"Not started: {s.get('not_started', 0)}")
        print(f"  Duration: {dur_min}m {dur_sec}s")
        print(f"  Git: {result.git_sha}@{result.git_branch}")

        if problem_count > 0:
            print()
            print("  Failed tests / dispatch errors:")
            for suite_name, suite_data in result.suites.items():
                for t in suite_data.get("tests", []):
                    if _is_problem_status(t.get("status", "")):
                        name = t.get("file", t.get("name", "?"))
                        error = (t.get("error") or "")[:120]
                        print(f"    [{suite_name}] {name}: {error}")

        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_with_dev_stack_lease(args, callback):
    del args
    return callback()


def _maintain_spec_demo_publications(now: datetime | None = None) -> dict[str, int]:
    """Retry or expire pending demo publications in every managed worktree."""
    totals = {"scanned": 0, "retried": 0, "delivered": 0, "expired_deleted": 0}
    roots = [CONTROL_PLANE_ROOT / "test-results/spec-demos"]
    worktree_root = CONTROL_PLANE_ROOT / ".openmates-agent-worktrees"
    if worktree_root.is_dir():
        roots.extend(path / "test-results/spec-demos" for path in worktree_root.iterdir() if path.is_dir())
    for root in roots:
        try:
            result = _sweep_spec_demo_publications(
                root,
                now=now or datetime.now(timezone.utc),
            )
        except Exception as exc:
            _log(f"Spec demonstration publication maintenance failed for {root}: {exc}", "WARN")
            continue
        for key in totals:
            totals[key] += result[key]
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenMates unified test orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--suite", choices=["all", "vitest", "pytest", "cli", "playwright", "apple"], default="all",
                        help="Suite to run (default: all)")
    parser.add_argument("--spec", type=str, default=None,
                        help="Run a single Playwright spec (e.g., chat-flow.spec.ts)")
    parser.add_argument("--only-failed", action="store_true",
                        help="Rerun only tests that failed in last-run.json")
    parser.add_argument("--daily", action="store_true",
                        help="Daily cron mode (commit gate, emails, OpenObserve)")
    parser.add_argument("--daily-cache-backfill-only", action="store_true",
                        help="Run only the bounded daily cache backfill with normal terminal notifications")
    parser.add_argument("--daily-cache-backfill-preflight", action="store_true",
                        help="Validate cache paths, commit pinning, and claims without dispatching or spending")
    parser.add_argument("--hourly-dev", action="store_true",
                        help="Hourly DEV smoke (4 specs, post on failure to "
                             "DISCORD_WEBHOOK_DEV_SMOKE). See OPE-349.")
    parser.add_argument("--core-journeys", action="store_true",
                        help="Run the canonical release core journeys through normal commit-pinned orchestration")
    parser.add_argument("--critical-journeys", action="store_true",
                        help="Run the audited daily critical billing, signup/auth, and core-chat registry")
    parser.add_argument("--hourly-prod", action="store_true",
                        help="Hourly PROD smoke (dispatches prod-smoke.yml, "
                             "free reachability suite; legacy alias for --prod-free-hourly).")
    parser.add_argument("--prod-free-hourly", action="store_true",
                        help="Free production smoke, hourly between 06:00 and 23:59 Europe/Berlin.")
    parser.add_argument("--prod-paid-chat", action="store_true",
                        help="Paid production CLI chat smoke, scheduled at 07:00, 13:00, and 19:00 Europe/Berlin.")
    parser.add_argument("--prod-app-skill", action="store_true",
                        help="Production CLI app-skill smoke for web search, scheduled once daily by default.")
    parser.add_argument("--dry-run-notify", action="store_true",
                        help="Send a one-shot ✅ test embed to the Discord "
                             "webhook of the chosen mode (--daily / --hourly-dev "
                             "/ --hourly-prod) and exit. Used to verify wiring.")
    parser.add_argument("--force", action="store_true",
                        help="Skip commit-activity check in --daily mode; in "
                             "hourly modes, force a Discord post on green runs.")
    parser.add_argument("--environment", choices=["development", "production"], default="development",
                        help="Target environment (default: development)")
    parser.add_argument("--max-concurrent", type=int, default=20,
                        help="Max concurrent GitHub Actions runners (default: 20)")
    parser.add_argument("--account", type=int, choices=range(1, MAX_ACCOUNTS + 1), metavar=f"1-{MAX_ACCOUNTS}", default=None,
                        help="Pin a single Playwright spec to a specific GitHub Actions test-account slot")
    parser.add_argument("--create-account-slot", type=int, choices=range(14, 21), metavar="14-20", default=None,
                        help="Provision a reserved auth-test account slot via cli-provision-auth-accounts.spec.ts")
    parser.add_argument("--no-fail-fast", action="store_true",
                        help="Don't stop on first batch failure")
    parser.add_argument("--no-mocks", action="store_true",
                        help="Run with real LLM calls instead of mocks")
    parser.add_argument("--record-live-fixtures", action="store_true",
                        help="Dispatch Playwright with TEST_LIVE_RECORD markers instead of replaying live-mock fixtures")
    parser.add_argument("--proof-video-profile", choices=sorted(PROOF_VIDEO_PROFILES), default="",
                        help="Capture Playwright video at an exact proof-video device profile size")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without executing")
    parser.add_argument("--flaky-report", action="store_true",
                        help="Show top flaky tests from history and exit")
    parser.add_argument("--list", action="store_true",
                        help="List deterministic test catalog entries and exit")
    parser.add_argument("--list-core-journeys", action="store_true",
                        help="Print the canonical core-journey GitHub Actions matrix as JSON and exit")

    args = parser.parse_args()

    if args.flaky_report:
        _print_flaky_report()
        return 0

    if args.list:
        _print_test_catalog()
        return 0

    if args.list_core_journeys:
        print_core_journey_matrix()
        return 0

    # Reject incompatible mode combinations early so the user gets a clear
    # error instead of weird half-runs.
    mode_flags = sum(int(x) for x in (
        args.daily,
        args.hourly_dev,
        args.hourly_prod,
        args.prod_free_hourly,
        args.prod_paid_chat,
        args.prod_app_skill,
        args.core_journeys,
        args.critical_journeys,
    ))
    if mode_flags > 1:
        _log(
            "Pass at most one of: --daily, --hourly-dev, --hourly-prod, "
            "--prod-free-hourly, --prod-paid-chat, --prod-app-skill, --core-journeys, --critical-journeys",
            "ERROR",
        )
        return 2
    non_daily_modes = any((
        args.hourly_dev,
        args.hourly_prod,
        args.prod_free_hourly,
        args.prod_paid_chat,
        args.prod_app_skill,
        args.core_journeys,
        args.critical_journeys,
    ))
    dedicated_mode_conflict = any((
        args.suite != "all",
        args.spec,
        args.only_failed,
        args.dry_run_notify,
        args.no_mocks,
        args.record_live_fixtures,
        args.proof_video_profile,
        args.dry_run,
        args.account is not None,
        args.create_account_slot is not None,
    ))
    if args.daily_cache_backfill_preflight and (mode_flags or dedicated_mode_conflict):
        _log("--daily-cache-backfill-preflight cannot be combined with test execution modes", "ERROR")
        return 2
    if args.daily_cache_backfill_only and (non_daily_modes or dedicated_mode_conflict):
        _log("--daily-cache-backfill-only cannot be combined with another test selection", "ERROR")
        return 2
    if args.daily_cache_backfill_only:
        args.daily = True
        args.suite = "all"
    if args.core_journeys and args.spec:
        _log("--core-journeys cannot be combined with --spec", "ERROR")
        return 2
    if args.critical_journeys and args.spec:
        _log("--critical-journeys cannot be combined with --spec", "ERROR")
        return 2
    if args.account is not None and not args.spec:
        _log("--account requires --spec so one GitHub Actions run maps to one explicit test-account slot", "ERROR")
        return 2
    if args.create_account_slot is not None and args.spec != PROVISION_AUTH_ACCOUNTS_SPEC:
        _log("--create-account-slot requires --spec cli-provision-auth-accounts.spec.ts", "ERROR")
        return 2
    if args.core_journeys:
        args.suite = "playwright"
    if args.critical_journeys:
        args.suite = "playwright"
    if args.no_mocks and args.record_live_fixtures:
        _log("--record-live-fixtures requires live-mock markers; do not combine it with --no-mocks", "ERROR")
        return 2
    if args.daily and args.record_live_fixtures:
        _log("--daily cannot use --record-live-fixtures; scheduled record mode is forbidden", "ERROR")
        return 2

    # Always source .env into the process so cron jobs (which only run via
    # bash with `set -a && . .env`) and direct invocations both work.
    dot_env = _read_env_file()
    for k, v in dot_env.items():
        if k not in os.environ:
            os.environ[k] = v

    if args.daily_cache_backfill_preflight:
        git_sha, git_branch = _git_info()
        git_sha, _git_branch = _daily_git_info(git_sha, git_branch)
        result = _daily_cache_backfill_preflight(git_sha, datetime.now(timezone.utc).date())
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") == "passed" else 1

    if args.hourly_dev or args.daily:
        maintenance = _maintain_spec_demo_publications()
        if maintenance["retried"] or maintenance["expired_deleted"]:
            _log(f"Spec demonstration publication maintenance: {maintenance}")

    # --dry-run-notify: short-circuit before any spec dispatch.
    if args.dry_run_notify:
        notification = NotificationService()
        if args.hourly_dev:
            return run_dry_run_notify_mode(notification, "hourly-dev")
        if args.hourly_prod:
            return run_dry_run_notify_mode(notification, "hourly-prod")
        if args.prod_free_hourly or args.prod_paid_chat or args.prod_app_skill:
            return run_dry_run_notify_mode(notification, "hourly-prod")
        if args.daily:
            return run_dry_run_notify_mode(notification, "daily")
        _log(
            "--dry-run-notify requires one of: --daily, --hourly-dev, --hourly-prod, "
            "--prod-free-hourly, --prod-paid-chat, --prod-app-skill",
            "ERROR",
        )
        return 2

    # --hourly-dev: separate lockfile so it never collides with --daily or
    # --hourly-prod, and exits cleanly if the previous hour is still running.
    if args.hourly_dev:
        lock_fd = None
        try:
            lock_fd = open(LOCKFILE_HOURLY_DEV, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _log("Another --hourly-dev run is in progress — skipping this hour")
            return 0
        try:
            return _run_with_dev_stack_lease(
                args,
                lambda: run_hourly_dev_mode(NotificationService(), force=args.force),
            )
        finally:
            if lock_fd:
                lock_fd.close()

    # --hourly-prod / --prod-free-hourly: separate lockfile (same rationale as --hourly-dev).
    if args.hourly_prod or args.prod_free_hourly:
        lock_fd = None
        try:
            lock_fd = open(LOCKFILE_HOURLY_PROD, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _log("Another prod free-hourly run is in progress — skipping this tick")
            return 0
        try:
            return run_prod_free_hourly_mode(NotificationService(), force=args.force, dry_run=args.dry_run)
        finally:
            if lock_fd:
                lock_fd.close()

    if args.prod_paid_chat:
        lock_fd = None
        try:
            lock_fd = open(LOCKFILE_PROD_PAID_CHAT, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _log("Another prod paid-chat run is in progress — skipping this tick")
            return 0
        try:
            return run_prod_paid_chat_mode(NotificationService(), force=args.force, dry_run=args.dry_run)
        finally:
            if lock_fd:
                lock_fd.close()

    if args.prod_app_skill:
        lock_fd = None
        try:
            lock_fd = open(LOCKFILE_PROD_APP_SKILL, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _log("Another prod app-skill run is in progress — skipping this tick")
            return 0
        try:
            return run_prod_app_skill_mode(NotificationService(), force=args.force, dry_run=args.dry_run)
        finally:
            if lock_fd:
                lock_fd.close()

    # Daily mode: acquire lockfile
    lock_fd = None
    if args.daily:
        try:
            lock_fd = open(LOCKFILE, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _log("Another instance is already running — exiting")
            git_sha, git_branch = _git_info()
            NotificationService().send_daily_skip_notification(
                git_sha,
                git_branch,
                args.environment,
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "Another daily test instance still holds the runner lock.",
            )
            return 0

    try:
        orchestrator = TestOrchestrator(args)
        return _run_with_dev_stack_lease(args, orchestrator.run)
    finally:
        if lock_fd:
            lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())
