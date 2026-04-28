#!/usr/bin/env python3
"""
scripts/run_tests.py

Unified test orchestrator for OpenMates.

Replaces: run-tests.sh, run-tests-daily.sh, run-tests-worker.sh,
          ci/trigger_parallel_specs.sh

Runs pytest and vitest locally (fast), dispatches Playwright E2E specs
to GitHub Actions via playwright-spec.yml in batches of N (default 20),
polls for completion, aggregates results, and sends notifications.

Usage:
    python3 scripts/run_tests.py                           # full suite
    python3 scripts/run_tests.py --spec chat-flow.spec.ts  # single spec
    python3 scripts/run_tests.py --only-failed             # rerun failures
    python3 scripts/run_tests.py --suite pytest             # just pytest
    python3 scripts/run_tests.py --suite vitest             # just vitest
    python3 scripts/run_tests.py --suite playwright         # just E2E
    python3 scripts/run_tests.py --daily                   # cron mode (3 AM nightly)
    python3 scripts/run_tests.py --daily --force            # skip commit check
    python3 scripts/run_tests.py --hourly-dev              # hourly dev smoke (4 specs)
    python3 scripts/run_tests.py --hourly-prod             # hourly prod smoke
    python3 scripts/run_tests.py --hourly-dev --dry-run-notify  # test Discord wiring
    python3 scripts/run_tests.py --max-concurrent 10       # override batch size
    python3 scripts/run_tests.py --no-fail-fast            # run all batches

Architecture: docs/architecture/test-orchestration.md
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test-results"
SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
LOCKFILE = Path("/tmp/openmates-daily-tests.lock")
LOCKFILE_HOURLY_DEV = Path("/tmp/openmates-hourly-dev-tests.lock")
LOCKFILE_HOURLY_PROD = Path("/tmp/openmates-hourly-prod-tests.lock")
# Written by the Claude Code docker-restart-marker hook whenever a
# `docker compose down/restart/stop` command is detected. Hourly smoke
# runs check this file and skip if Docker was restarted too recently.
DOCKER_RESTART_MARKER = Path("/tmp/openmates-last-docker-restart")
DOCKER_GRACE_MINUTES = 10  # skip smoke runs for 10 min after a restart
# After this many consecutive suppressed ticks (same failure hash), the
# summary is re-posted even though nothing changed, so the Discord channel
# doesn't go silent for hours during a prolonged outage.
RENOTIFY_AFTER_TICKS = 3
WORKFLOW_NAME = "playwright-spec.yml"
PROD_SMOKE_WORKFLOW = "prod-smoke.yml"
GH_REPO = "glowingkitty/OpenMates"
GH_BRANCH = "dev"
MAX_ACCOUNTS = 20
POLL_INTERVAL = 15  # seconds between status checks
RUN_TIMEOUT = 1800  # 30 min max per batch
PROD_SMOKE_RUN_TIMEOUT = 1800  # 30 min — prod-smoke.yml has its own 25-min job cap
VITEST_TIMEOUT = 300  # seconds — vitest must complete in 5 min or be killed
MAX_ERROR_SNIPPET = 600
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

# Hourly dev smoke spec list — kept SHORT on purpose. See OPE-349 + the
# tests/dev-smoke/README.md for the policy. Anything that isn't a core user
# flow that must keep working belongs in the nightly run, not here.
HOURLY_DEV_SPECS: list[str] = [
    # Order determines test-account slot: specs[i] → account (i+1).
    # chat-flow is first so it uses testacct1 (known healthy) — testacct4 has
    # accumulated broken chat state that stalls DB init during login.
    # dev-smoke doesn't use account credentials, so it can safely run on any slot.
    "chat-flow.spec.ts",
    "settings-buy-credits-stripe.spec.ts",
    "signup-flow-polar.spec.ts",
    "dev-smoke/dev-smoke-reachability.spec.ts",
]

# Where each hourly mode parks its result archives + heartbeat marker.
HOURLY_DEV_DIR = RESULTS_DIR / "hourly-dev"
HOURLY_PROD_DIR = RESULTS_DIR / "hourly-prod"
HOURLY_ARCHIVE_RETENTION_DAYS = 7


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
    retries: int = 0
    flaky: bool = False
    # Structured Playwright data for MD reports
    playwright_errors: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    screenshot_paths: list[str] = field(default_factory=list)
    video_paths: list[str] = field(default_factory=list)
    video_artifact_name: Optional[str] = None
    github_run_url: Optional[str] = None


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
    summary: dict  # {total, passed, failed, skipped, not_started}
    suites: dict  # {suite_name: SuiteResult as dict}
    flags: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

    print(f"\nTop flaky tests ({len(ranked)} total):\n")
    print(f"{'Rate':>6}  {'Flaky/Total':>12}  {'Last Flaky':<12}  Test")
    print(f"{'─' * 6}  {'─' * 12}  {'─' * 12}  {'─' * 40}")
    for key, flaky, total, rate, last_date in ranked[:15]:
        print(f"{rate:5.0%}   {flaky:>4}/{total:<6}  {last_date:<12}  {key}")
    print()


def _log(msg: str, level: str = "INFO") -> None:
    """Print a timestamped log line."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    prefix = {"INFO": "  ", "WARN": "⚠ ", "ERROR": "✗ ", "OK": "✓ "}.get(level, "  ")
    print(f"[{ts}] {prefix}{msg}", flush=True)


def _git_info() -> tuple[str, str]:
    """Return (short_sha, branch)."""
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


def _read_env_file() -> dict[str, str]:
    """Read .env file from project root."""
    env_path = PROJECT_ROOT / ".env"
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

class GitHubActionsClient:
    """Wraps the `gh` CLI for workflow dispatch and status polling."""

    def __init__(self) -> None:
        self._check_gh()

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

    def dispatch_spec(self, spec: str, account: int, use_mocks: bool = True) -> Optional[int]:
        """
        Dispatch a single spec workflow run.
        Returns the run ID or None on failure.
        """
        # Record the latest run ID before dispatch so we can find the new one
        pre_ids = self._recent_run_ids(limit=5)

        # playwright-spec.yml: lightweight 1-job workflow per spec
        rc = subprocess.run(
            ["gh", "workflow", "run", WORKFLOW_NAME,
             "--repo", GH_REPO,
             "--ref", GH_BRANCH,
             "-f", f"spec={spec}",
             "-f", f"account={account}",
             "-f", f"use_mocks={'true' if use_mocks else 'false'}"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            _log(f"Dispatch failed for {spec}: {rc.stderr.strip()}", "ERROR")
            return None

        # Wait for GitHub to register the run, then find its ID
        for attempt in range(6):
            time.sleep(2)
            new_ids = self._recent_run_ids(limit=10)
            fresh = [rid for rid in new_ids if rid not in pre_ids]
            if fresh:
                return fresh[0]  # Most recent new run

        _log(f"Could not capture run ID for {spec} after dispatch", "WARN")
        return None

    def _recent_run_ids(self, limit: int = 5, workflow: str = WORKFLOW_NAME) -> list[int]:
        """Get the most recent run IDs for a workflow."""
        rc = subprocess.run(
            ["gh", "run", "list",
             "--repo", GH_REPO,
             "--workflow", workflow,
             "--limit", str(limit),
             "--json", "databaseId"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            return []
        try:
            return [r["databaseId"] for r in json.loads(rc.stdout)]
        except (json.JSONDecodeError, KeyError):
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
        rc = subprocess.run(
            ["gh", "run", "view", str(run_id),
             "--repo", GH_REPO,
             "--log-failed"],
            capture_output=True, text=True,
            timeout=30,
        )
        if rc.returncode != 0 or not rc.stdout.strip():
            return None

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
                "Cannot find module", "ERR_MODULE_NOT_FOUND",
            ]):
                capture = True
            if capture:
                error_lines.append(text.strip())
                if len(error_lines) >= 15:
                    break

        if error_lines:
            return "\n".join(error_lines)[:MAX_ERROR_SNIPPET]

        # Fallback: return last N non-empty lines (usually contains the failure reason)
        tail = [ln.split("\t")[-1].strip() if "\t" in ln else ln.strip()
                for ln in lines[-20:] if ln.strip()]
        if tail:
            return "\n".join(tail[-10:])[:MAX_ERROR_SNIPPET]

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
    ) -> None:
        self.client = client
        self.specs = specs
        self.batch_size = batch_size
        self.fail_fast = fail_fast
        self.use_mocks = use_mocks

    def run_all_batches(self) -> SuiteResult:
        """Execute all specs in batches. Returns aggregated SuiteResult."""
        if not self.specs:
            return SuiteResult(status="skipped", reason="no specs to run")

        all_results: list[SpecResult] = []
        total_batches = (len(self.specs) + self.batch_size - 1) // self.batch_size
        suite_start = time.time()

        for batch_idx in range(total_batches):
            start = batch_idx * self.batch_size
            end = min(start + self.batch_size, len(self.specs))
            batch_specs = self.specs[start:end]

            print()
            _log(f"Batch {batch_idx + 1}/{total_batches}: {len(batch_specs)} specs")

            batch_results = self._run_batch(batch_specs, batch_idx)
            all_results.extend(batch_results)

            # Check for failures (batch-level fail-fast)
            batch_failures = [r for r in batch_results if r.status == "failed"]
            if batch_failures and self.fail_fast and batch_idx < total_batches - 1:
                remaining_specs = self.specs[end:]
                _log(
                    f"{len(batch_failures)} failure(s) in batch {batch_idx + 1} — "
                    f"skipping {len(remaining_specs)} remaining specs (fail-fast)",
                    "WARN",
                )
                for spec in remaining_specs:
                    all_results.append(SpecResult(
                        name=spec, file=spec, status="not_started",
                        error=f"Skipped: fail-fast after batch {batch_idx + 1}",
                    ))
                break

        duration = time.time() - suite_start
        tests = [self._spec_result_to_dict(r) for r in all_results]
        has_failures = any(r.status == "failed" for r in all_results)

        return SuiteResult(
            status="failed" if has_failures else "passed",
            tests=tests,
            duration_seconds=round(duration, 1),
        )

    def _run_batch(self, specs: list[str], batch_idx: int) -> list[SpecResult]:
        """Dispatch and wait for a single batch of specs."""
        # Dispatch all specs in this batch
        dispatched: list[tuple[str, int, int]] = []  # (spec, account, run_id)
        dispatch_errors: list[SpecResult] = []

        for i, spec in enumerate(specs):
            account = (batch_idx * self.batch_size + i) % MAX_ACCOUNTS + 1
            _log(f"  Dispatching {spec} (account {account})")

            run_id = self.client.dispatch_spec(spec, account, self.use_mocks)
            if run_id is None:
                # Retry once
                time.sleep(5)
                run_id = self.client.dispatch_spec(spec, account, self.use_mocks)

            if run_id is None:
                dispatch_errors.append(SpecResult(
                    name=spec, file=spec, status="failed",
                    error="Failed to dispatch workflow after retry",
                ))
            else:
                dispatched.append((spec, account, run_id))

            # Small delay between dispatches to avoid rate limiting
            if (i + 1) % 5 == 0:
                time.sleep(1)

        if not dispatched:
            return dispatch_errors

        # Wait for all dispatched runs
        run_ids = [rid for _, _, rid in dispatched]
        _log(f"  Waiting for {len(run_ids)} runs...")
        statuses = self.client.wait_for_runs(run_ids, self.fail_fast)
        print()  # Clear the polling line

        # Collect results
        results: list[SpecResult] = list(dispatch_errors)
        artifact_dir = Path(tempfile.mkdtemp(prefix="pw-artifacts-"))

        for spec, account, rid in dispatched:
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

            art_name = f"playwright-{spec.replace('/', '-')}"
            art_path = self.client.download_artifact(rid, art_name, artifact_dir)
            if art_path:
                # playwright.json may be at top level or under test-results/
                pw_json = art_path / "playwright.json"
                if not pw_json.is_file():
                    pw_json = art_path / "test-results" / "playwright.json"
                if pw_json.is_file():
                    extracted_err, pw_errors, pw_steps = (
                        self._extract_structured_data_from_playwright_json(pw_json)
                    )
                    if extracted_err and status == "failed":
                        error = extracted_err

                # Persist artifacts (screenshots, traces, playwright.json)
                self._persist_failure_artifacts(spec, art_path)
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

            icon = {"passed": "✓", "failed": "✗", "timeout": "⏱", "not_started": "⊘"}.get(status, "?")
            _log(f"  {icon} {spec} (run {rid})", "OK" if status == "passed" else "ERROR")

            results.append(SpecResult(
                name=spec, file=spec, status=status,
                error=error, run_id=rid, account=account,
                playwright_errors=pw_errors,
                steps=pw_steps,
                screenshot_paths=screenshot_paths,
                video_paths=video_paths,
                video_artifact_name=art_name if video_paths else None,
                github_run_url=f"https://github.com/{GH_REPO}/actions/runs/{rid}" if rid else None,
            ))

        # Cleanup artifact dir
        shutil.rmtree(artifact_dir, ignore_errors=True)
        return results

    @staticmethod
    def _extract_structured_data_from_playwright_json(
        pw_json: Path,
    ) -> tuple[Optional[str], list[dict], list[dict]]:
        """Extract error message, structured errors, and step data from Playwright JSON.

        Handles nested suites (suites can contain both specs and child suites).

        Returns:
            (first_error_string, playwright_errors_list, steps_list)
        """
        first_error: Optional[str] = None
        errors: list[dict] = []
        steps: list[dict] = []

        def _process_result(result: dict) -> None:
            nonlocal first_error
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

        return first_error, errors, steps

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
        if r.retries > 0:
            d["retries"] = r.retries
        if r.flaky:
            d["flaky"] = True
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
        if r.github_run_url:
            d["github_run_url"] = r.github_run_url
        return d


# ---------------------------------------------------------------------------
# ResultAggregator
# ---------------------------------------------------------------------------

class ResultAggregator:
    """Merges results from all suites into the standard last-run.json format."""

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
                elif st == "not_started":
                    not_started += 1
                else:
                    skipped += 1

        return RunResult(
            run_id=run_id,
            git_sha=git_sha,
            git_branch=git_branch,
            environment=environment,
            duration_seconds=round(duration, 1),
            summary={"total": total, "passed": passed, "failed": failed,
                      "skipped": skipped, "not_started": not_started},
            suites=suites_dict,
            flags=flags,
        )

    @staticmethod
    def save(result: RunResult) -> None:
        """Save results to test-results/."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

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

        # Write timestamped run file
        ts = result.run_id.replace(":", "").replace("-", "")
        run_file = RESULTS_DIR / f"run-{ts}.json"
        _safe_write_json(run_file, data)

        # Write last-run.json (always overwritten)
        _safe_write_json(RESULTS_DIR / "last-run.json", data)

        _log(f"Results saved to {run_file.name} and last-run.json")

    @staticmethod
    def load_failed_specs() -> list[str]:
        """Load previously failed spec files from last-run.json."""
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
                if t.get("status") == "failed":
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

        if self.brevo_api_key:
            self._send_via_brevo(subject, body)
        elif self.internal_token:
            self._send_via_internal_api("dispatch-test-start-email", {
                "recipient_email": self.admin_email,
                "environment": environment,
                "trigger_type": "Scheduled (daily)",
                "git_sha": git_sha,
                "git_branch": git_branch,
                "started_at": started_at,
            })
        else:
            _log("No email credentials available — skipping start email", "WARN")

    def send_summary_email(self, result: RunResult) -> None:
        """Send test summary email after run completes, plus Discord fallback.

        The email and Discord sends are INDEPENDENT: neither awaits the other
        and neither's failure aborts the other. This is the whole point of the
        dual-channel notification pattern.
        """
        s = result.summary
        status = "All tests passed" if s["failed"] == 0 else f"{s['failed']} of {s['total']} tests failed"
        subject = f"[OpenMates] {status} ({result.environment})"

        # --- Email path (existing) ---
        if not self.admin_email:
            _log("ADMIN_NOTIFY_EMAIL not set — skipping summary email", "WARN")
        else:
            # Build HTML email body
            html = self._build_summary_html(result)
            text = self._build_summary_text(result)

            if self.brevo_api_key:
                self._send_via_brevo(subject, text, html)
            elif self.internal_token:
                # Fall back to internal API
                payload = self._build_internal_api_payload(result)
                self._send_via_internal_api("dispatch-test-summary-email", payload)
            else:
                _log("No email credentials available — skipping summary email", "WARN")

        # --- Discord fallback (OPE-76) ---
        # Fires for EVERY run — nightly success gives a visible heartbeat so we
        # notice if the whole pipeline goes quiet. Failures get a louder ping.
        self._send_summary_to_discord(result)

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

    def _send_via_brevo(self, subject: str, text: str, html: Optional[str] = None) -> None:
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
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            _log(f"Brevo email failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
        except Exception as e:
            _log(f"Brevo email failed: {e}", "ERROR")

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
    ) -> None:
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
            return

        s = result.summary
        all_passed = s["failed"] == 0

        # Hourly modes silence green runs to avoid channel flooding.
        if all_passed and not post_on_success:
            _log(f"Discord ({mode_label}): green run, suppressed (post_on_success=False)")
            return

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
                    if t.get("status") != "failed":
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
                    return
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
                f"{s['failed']} failed{elapsed_h}"
            )
        else:
            title_emoji = "✅" if all_passed else "❌"
            status_suffix = "all passed" if all_passed else f"{s['failed']} failed"
            title = f"{title_emoji} {result.environment} {mode_label} — {status_suffix}"

        # Build a compact description listing up to the first 10 failed tests
        # AND their error snippets so readers can act on the alert without
        # leaving Discord. Each entry: name + per-test GH Actions run link
        # (when present) + a fenced code block with the truncated error.
        failed_blocks: list[str] = []
        max_failures_shown = 5  # keep description well under 4096 chars
        max_error_chars = 500   # per failure
        for suite_name, suite_data in result.suites.items():
            for t in suite_data.get("tests", []):
                if t.get("status") != "failed":
                    continue
                name = t.get("file", t.get("name", "?"))
                err = (t.get("error") or "").strip()
                rid = t.get("run_id")
                # Header line: suite/test name + optional [logs] link.
                if rid:
                    rid_url = f"https://github.com/{GH_REPO}/actions/runs/{rid}"
                    header = f"• `{suite_name}` — **{name}** — [logs]({rid_url})"
                else:
                    header = f"• `{suite_name}` — **{name}**"
                if err:
                    if len(err) > max_error_chars:
                        err = err[:max_error_chars - 3].rstrip() + "..."
                    # Strip backticks so they don't break the fenced block.
                    err_safe = err.replace("```", "ʼʼʼ")
                    failed_blocks.append(f"{header}\n```\n{err_safe}\n```")
                else:
                    failed_blocks.append(header)
                if len(failed_blocks) >= max_failures_shown:
                    break
            if len(failed_blocks) >= max_failures_shown:
                break

        remaining = max(0, s["failed"] - len(failed_blocks))
        if remaining > 0:
            failed_blocks.append(f"…and {remaining} more failure(s)")

        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        description_parts = [
            f"**Total:** {s['total']}   **Passed:** {s['passed']}   "
            f"**Failed:** {s['failed']}   **Skipped:** {s['skipped']}",
            f"**Duration:** {dur_min}m {dur_sec}s   **Git:** `{result.git_sha[:8]}@{result.git_branch}`",
        ]
        if run_url:
            description_parts.append(f"**Run:** [GitHub Actions]({run_url})")
        if failed_blocks:
            description_parts.append("")
            description_parts.append("**Failures:**")
            description_parts.extend(failed_blocks)

        description = "\n".join(description_parts)
        # Discord caps description at 4096 chars
        if len(description) > 4000:
            description = description[:3997] + "..."

        embed: dict = {
            "title": title,
            "description": description,
            "color": color,
        }
        if run_url:
            embed["url"] = run_url

        payload = {
            "username": "OpenMates Server",
            "avatar_url": "https://openmates.org/favicon.png",
            "embeds": [embed],
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
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            _log(f"Discord summary POST failed: HTTP {e.code} — {err_body[:300]}", "ERROR")
        except Exception as e:
            _log(f"Discord summary POST failed: {e}", "ERROR")

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

        # Mark the last checkpoint as ❌ for failed tests.
        if test.get("status") == "failed" and groups:
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
        failed_tests = [t for t in suite_data.get("tests", []) if t.get("status") == "failed"]

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
            embeds, files = self._build_md_style_test_message(
                t, suite_name, result.run_id, screenshots_root,
            )
            if not embeds:
                # Nothing to send for this test (no screenshots / no step log).
                # The lightweight summary already named it as failed, so we
                # don't bother spamming an empty card.
                continue

            test_key = _compute_test_key(suite_name, t)
            error_hash = _compute_error_hash(t)
            current_failure_keys.add(test_key)

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

    def _send_via_internal_api(self, endpoint: str, payload: dict) -> None:
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
        except Exception as e:
            _log(f"Internal API email dispatch failed: {e}", "WARN")

    def _build_summary_html(self, result: RunResult) -> str:
        """Build a simple HTML email for test results."""
        s = result.summary
        status_color = "#22c55e" if s["failed"] == 0 else "#ef4444"
        status_text = "ALL PASSED" if s["failed"] == 0 else f"{s['failed']} FAILED"

        # Collect failed tests — prefer structured Playwright errors over GHA logs
        failed_rows = ""
        for suite_name, suite_data in result.suites.items():
            for t in suite_data.get("tests", []):
                if t.get("status") == "failed":
                    # Use first structured Playwright error if available
                    pw_errors = t.get("playwright_errors", [])
                    if pw_errors:
                        error = (pw_errors[0].get("message") or "")[:500].replace("<", "&lt;")
                    else:
                        error = (t.get("error") or "")[:300].replace("<", "&lt;")
                    name = t.get("file", t.get("name", "?"))
                    failed_rows += (
                        f"<tr><td style='padding:4px 8px'>{suite_name}</td>"
                        f"<td style='padding:4px 8px'>{name}</td>"
                        f"<td style='padding:4px 8px;font-size:12px;color:#888'>"
                        f"<pre style='margin:0;white-space:pre-wrap;max-width:500px'>{error}</pre>"
                        f"</td></tr>"
                    )

        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        html = f"""<html><body style="font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:20px">
<h2 style="color:{status_color}">{status_text}</h2>
<table style="border-collapse:collapse;margin:12px 0">
<tr><td style="padding:4px 12px 4px 0;color:#888">Total</td><td><b>{s['total']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#22c55e">Passed</td><td><b>{s['passed']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#ef4444">Failed</td><td><b>{s['failed']}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Skipped</td><td>{s['skipped']}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Not started</td><td>{s.get('not_started', 0)}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Duration</td><td>{dur_min}m {dur_sec}s</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Git</td><td>{result.git_sha}@{result.git_branch}</td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#888">Environment</td><td>{result.environment}</td></tr>
</table>"""

        if failed_rows:
            html += f"""<h3 style="color:#ef4444;margin-top:20px">Failed Tests</h3>
<table style="border-collapse:collapse;width:100%;font-size:13px">
<tr style="color:#888"><th style="text-align:left;padding:4px 8px">Suite</th><th style="text-align:left;padding:4px 8px">Test</th><th style="text-align:left;padding:4px 8px">Error</th></tr>
{failed_rows}
</table>"""

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
            f"Skipped: {s['skipped']}  Not started: {s.get('not_started', 0)}",
            f"Duration: {dur_min}m {dur_sec}s",
            f"Git: {result.git_sha}@{result.git_branch}",
            "",
        ]

        if s["failed"] > 0:
            lines.append("Failed Tests:")
            lines.append("-" * 40)
            for suite_name, suite_data in result.suites.items():
                for t in suite_data.get("tests", []):
                    if t.get("status") == "failed":
                        name = t.get("file", t.get("name", "?"))
                        # Prefer structured Playwright error
                        pw_errors = t.get("playwright_errors", [])
                        if pw_errors:
                            error = (pw_errors[0].get("message") or "")[:400]
                        else:
                            error = (t.get("error") or "")[:200]
                        lines.append(f"  [{suite_name}] {name}")
                        if error:
                            lines.append(f"    {error}")
            lines.append("")

        return "\n".join(lines)

    def _build_internal_api_payload(self, result: RunResult) -> dict:
        """Build payload for /internal/dispatch-test-summary-email."""
        payload = self._build_openobserve_payload(result)
        payload["recipient_email"] = self.admin_email
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
            suite_not_started = sum(1 for t in tests if t.get("status") == "not_started")
            suites_list.append({
                "name": suite_name,
                "total": len(tests),
                "passed": suite_passed,
                "failed": suite_failed,
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
                if t.get("status") == "failed":
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
    _log(f"Archived hourly-dev run to {archive_path.relative_to(PROJECT_ROOT)}")

    s = result.summary
    print()
    print("=" * 60)
    icon = "✓" if s["failed"] == 0 else "✗"
    dur_min = int(result.duration_seconds // 60)
    dur_sec = int(result.duration_seconds % 60)
    print(f"  {icon} hourly-dev: {s['passed']}/{s['total']} passed, "
          f"{s['failed']} failed   ({dur_min}m {dur_sec}s)")
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

    return 1 if s["failed"] > 0 else 0


# prod-smoke.yml writes one playwright JSON file per spec into the artifact:
# test-results/{reachability,signup}.json. We use these as the source of
# truth for per-spec status. Step `conclusion` is unreliable here because
# every step uses `continue-on-error: true && exit 0`, so all step
# conclusions are `success` even when the underlying spec failed.
PROD_SMOKE_SPECS: list[tuple[str, str, str]] = [
    # (key, human-readable label, spec filename)
    ("reachability", "reachability spec", "prod-smoke-reachability.spec.ts"),
    (
        "signup",
        "signup + gift card + chat + login + history + chat + delete spec",
        "prod-smoke-signup-giftcard-chat.spec.ts",
    ),
]


def _parse_prod_smoke_artifact(art_path: Path) -> list[dict]:
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
    # artifact was unpacked. Try both.
    candidates = [
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

    base: Optional[Path] = next((c for c in candidates if c.is_dir()), None)
    if base is None:
        return []

    out: list[dict] = []
    for spec_key, spec_label, spec_filename in PROD_SMOKE_SPECS:
        json_path = base / f"{spec_key}.json"
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


def run_hourly_prod_mode(notification: NotificationService, force: bool) -> int:
    """Hourly prod smoke: dispatch the existing prod-smoke.yml workflow once
    and report its result. The workflow internally runs all 3 prod specs.
    """
    if not force and _docker_restarted_recently():
        _log(
            f"Docker restarted within the last {DOCKER_GRACE_MINUTES} min "
            "— skipping hourly-prod smoke run to avoid false failures"
        )
        return 0

    git_sha, git_branch = _git_info()
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print()
    print("=" * 60)
    print("  OpenMates Hourly Smoke — PROD")
    print("=" * 60)
    _log(f"Git: {git_sha}@{git_branch}")
    _log(f"Workflow: {PROD_SMOKE_WORKFLOW}")
    print()

    client = GitHubActionsClient()
    pre_ids = client._recent_run_ids(limit=5, workflow=PROD_SMOKE_WORKFLOW)

    new_run_id: Optional[int] = None
    suite_result: Optional[SuiteResult] = None  # set by failure paths OR by artifact parser
    conclusion: str = "unknown"

    rc = subprocess.run(
        ["gh", "workflow", "run", PROD_SMOKE_WORKFLOW,
         "--repo", GH_REPO, "--ref", GH_BRANCH],
        capture_output=True, text=True,
    )
    if rc.returncode != 0:
        _log(f"Dispatch failed: {rc.stderr.strip()[:200]}", "ERROR")
        # Build a synthetic failure result so the Discord path still fires.
        suite_result = SuiteResult(
            status="failed",
            tests=[{"name": "prod-smoke-dispatch", "status": "failed",
                    "duration_seconds": 0,
                    "error": f"Dispatch failed: {rc.stderr.strip()[:200]}"}],
        )
    else:
        # Find the new run ID
        time.sleep(5)
        for _ in range(10):
            post_ids = client._recent_run_ids(limit=10, workflow=PROD_SMOKE_WORKFLOW)
            fresh = [rid for rid in post_ids if rid not in pre_ids]
            if fresh:
                new_run_id = fresh[0]
                break
            time.sleep(3)

        if new_run_id is None:
            _log("Could not find dispatched prod-smoke run", "ERROR")
            suite_result = SuiteResult(
                status="failed",
                tests=[{"name": "prod-smoke-dispatch", "status": "failed",
                        "duration_seconds": 0,
                        "error": "Could not find dispatched workflow run"}],
            )
        else:
            _log(f"Waiting for prod-smoke run {new_run_id}...")
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
        spec_results = _parse_prod_smoke_artifact(art_path) if art_path else []
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
        suites={"prod-smoke": suite_result},
        run_id=run_id,
        git_sha=git_sha,
        git_branch=git_branch,
        environment="production",
        duration=0.0,  # we don't time the GH workflow itself
        flags={"mode": "hourly-prod", "force": force},
    )

    archive_path = _archive_hourly_run(HOURLY_PROD_DIR, result)
    _log(f"Archived hourly-prod run to {archive_path.relative_to(PROJECT_ROOT)}")

    s = result.summary
    print()
    print("=" * 60)
    icon = "✓" if s["failed"] == 0 else "✗"
    print(f"  {icon} hourly-prod: {s['passed']}/{s['total']} passed, "
          f"{s['failed']} failed")
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

    post_on_success = force or _heartbeat_should_fire(HOURLY_PROD_DIR)
    state_file = HOURLY_PROD_DIR / DISCORD_STATE_FILE_NAME
    try:
        # Lightweight summary first (overview of which specs failed +
        # clickable links). Skipped automatically when the failure set is
        # unchanged from the last tick (dedup'd via state file).
        notification._send_summary_to_discord(
            result,
            webhook_url=notification.discord_webhook_prod_smoke,
            mode_label="prod hourly",
            post_on_success=post_on_success,
            env_var_name="DISCORD_WEBHOOK_PROD_SMOKE",
            run_url=run_url,
            state_file=state_file,
            suite_name_for_dedup="prod-smoke",
        )
        # Always call the per-test sender so recoveries get reported
        # and the state file gets pruned even on a green tick. When
        # there are no current failures and no screenshots, the call
        # is essentially a no-op + recovery scan.
        notification.send_per_test_md_messages(
            result,
            webhook_url=notification.discord_webhook_prod_smoke,
            suite_name="prod-smoke",
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

    return 1 if s["failed"] > 0 else 0


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
        failed_tests = [t for t in tests if t.get("status") == "failed"]
        skipped_tests = [t for t in tests if t.get("status") not in ("passed", "failed")]
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
        self.only_failed = args.only_failed
        self.daily = args.daily
        self.force = args.force
        self.environment = args.environment
        self.max_concurrent = args.max_concurrent
        self.fail_fast = not args.no_fail_fast
        self.use_mocks = not args.no_mocks
        self.dry_run = args.dry_run

        self.git_sha, self.git_branch = _git_info()
        self.run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.notification = NotificationService()

    def run(self) -> int:
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
        if self.only_failed:
            _log("Mode: --only-failed (rerunning previous failures)")
        print()

        # Daily mode: commit gate + lockfile
        if self.daily:
            if not self._daily_gate():
                return 0

        # Send start notification
        if self.daily:
            self.notification.send_start_email(self.git_sha, self.git_branch, self.environment)

        start_time = time.time()
        suites: dict[str, SuiteResult] = {}

        # Archive previous failure screenshots before starting a new run
        screenshots_dir = RESULTS_DIR / "screenshots"
        if screenshots_dir.is_dir():
            # Move current screenshots to date-stamped archive (preserves history)
            current_dir = screenshots_dir / "current"
            if current_dir.is_dir() and any(current_dir.iterdir()):
                prev_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                archive_dest = screenshots_dir / prev_date
                if archive_dest.is_dir():
                    shutil.rmtree(archive_dest, ignore_errors=True)
                current_dir.rename(archive_dest)
                _log(f"Archived previous screenshots to screenshots/{prev_date}/")

        # Run all suites via GitHub Actions (prevents dev server overload)
        if self.suite in ("all", "vitest"):
            suites["vitest"] = self._run_unit_suite_via_gha("vitest.yml", "vitest-results") if not self.dry_run else SuiteResult(status="skipped", reason="dry run")

        if self.suite in ("all", "pytest"):
            suites["pytest_unit"] = self._run_unit_suite_via_gha("pytest-unit.yml", "pytest-results") if not self.dry_run else SuiteResult(status="skipped", reason="dry run")

        # Run Playwright via GitHub Actions
        if self.suite in ("all", "playwright"):
            suites["playwright"] = self._run_playwright()

        # Aggregate results
        duration = time.time() - start_time
        flags = {
            "suite": self.suite,
            "only_failed": self.only_failed,
            "fail_fast": self.fail_fast,
            "use_mocks": self.use_mocks,
        }

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
            self._sync_obsidian_test_results()

        # Print summary
        self._print_summary(result)

        # Daily mode: post-run tasks
        if self.daily and not self.dry_run:
            self._daily_post_run(result)

        return 1 if result.summary["failed"] > 0 else 0

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

        # Record pre-dispatch run IDs to find the new one
        pre_ids = client._recent_run_ids(limit=5, workflow=workflow_file)

        rc = subprocess.run(
            ["gh", "workflow", "run", workflow_file,
             "--repo", GH_REPO, "--ref", GH_BRANCH],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            _log(f"  {suite_label}: dispatch failed: {rc.stderr.strip()[:200]}", "ERROR")
            return SuiteResult(
                status="failed",
                tests=[{"name": f"{suite_label}-dispatch", "status": "failed",
                        "duration_seconds": 0, "error": f"Dispatch failed: {rc.stderr.strip()[:200]}"}],
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
                tests=[{"name": f"{suite_label}-dispatch", "status": "failed",
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
            if not all_tests and conclusion != "success":
                # Fallback: no parseable results but the run failed
                log_error = client.get_failed_job_error(run_id)
                all_tests = [{"name": f"{suite_label}-run", "status": "failed",
                              "duration_seconds": 0, "error": log_error or f"Run failed: {conclusion}"}]
        elif conclusion != "success":
            log_error = client.get_failed_job_error(run_id)
            all_tests = [{"name": f"{suite_label}-run", "status": "failed",
                          "duration_seconds": 0, "error": log_error or f"Run failed: {conclusion}"}]

        # Recalculate overall status from actual test results
        if all_tests:
            has_failures = any(t.get("status") == "failed" for t in all_tests)
            overall_status = "failed" if has_failures else "passed"

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
                            msgs = ar.get("failureMessages", [])
                            if msgs:
                                entry["error"] = msgs[0][:MAX_ERROR_SNIPPET]
                        all_tests.append(entry)

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

    def _run_playwright(self) -> SuiteResult:
        """Run Playwright specs via GitHub Actions."""
        specs = self._discover_specs()
        if not specs:
            return SuiteResult(status="skipped", reason="no specs to run")

        _log(f"Playwright: {len(specs)} spec(s) via GitHub Actions (batch size: {self.max_concurrent})")

        if self.dry_run:
            _log("Dry run — would dispatch these specs:")
            for s in specs:
                print(f"    {s}")
            return SuiteResult(status="skipped", reason="dry run")

        client = GitHubActionsClient()
        runner = BatchRunner(
            client=client,
            specs=specs,
            batch_size=self.max_concurrent,
            fail_fast=self.fail_fast,
            use_mocks=self.use_mocks,
        )
        result = runner.run_all_batches()

        # Aggregate storage-audit snapshots from this run into cookies.yml.
        # Skipped for single-spec runs (--spec) since coverage is intentionally
        # narrow and would prune entries from other flows. The merger never
        # clobbers human-maintained fields (purpose / consent_exempt / etc).
        if not self.spec:
            self._merge_cookie_audits()

        return result

    @staticmethod
    def _merge_cookie_audits() -> None:
        """Run scripts/merge_storage_audits.py to update cookies.yml."""
        merger = PROJECT_ROOT / "scripts" / "merge_storage_audits.py"
        if not merger.is_file():
            return
        try:
            proc = subprocess.run(
                [sys.executable, str(merger)],
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

    # Specs excluded from daily / all-spec runs.
    # These are utility specs (e.g. account provisioning) that should only be
    # triggered manually via --spec.
    EXCLUDED_SPECS = {
        "create-test-account.spec.ts",
    }

    def _discover_specs(self) -> list[str]:
        """Find which specs to run."""
        if self.spec:
            return [self.spec]

        if self.only_failed:
            failed = ResultAggregator.load_failed_specs()
            # Filter to only .spec.ts files
            specs = [f for f in failed if f.endswith(".spec.ts")]
            if specs:
                _log(f"Found {len(specs)} previously failed spec(s)")
            return specs

        # All specs, minus excluded utility specs
        spec_files = sorted(SPEC_DIR.glob("*.spec.ts"))
        return [f.name for f in spec_files if f.name not in self.EXCLUDED_SPECS]

    def _daily_gate(self) -> bool:
        """Check if daily run should proceed. Returns False to skip."""
        # Env gate
        if _get_env("E2E_DAILY_RUN_ENABLED", self.notification.dot_env) != "true":
            _log("E2E_DAILY_RUN_ENABLED is not set — skipping test run")
            _log("Set E2E_DAILY_RUN_ENABLED=true on the dev server to enable tests")
            return False

        # Commit-activity gate
        if not self.force:
            try:
                commits = subprocess.check_output(
                    ["git", "-C", str(PROJECT_ROOT), "log", "--oneline", "--since=24 hours ago"],
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()
                count = len(commits.splitlines()) if commits else 0
            except Exception:
                count = 0

            if count == 0:
                _log("No git commits in the last 24 hours — skipping test run")
                _log("Use --force to run regardless")
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

        # Archive daily result
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archive = RESULTS_DIR / f"daily-run-{today}.json"
        last_run = RESULTS_DIR / "last-run.json"
        if last_run.is_file():
            shutil.copy2(str(last_run), str(archive))
            _log(f"Archived to {archive.name}")

        # Prune old archives (keep last 30)
        archives = sorted(RESULTS_DIR.glob("daily-run-*.json"), reverse=True)
        for old in archives[30:]:
            old.unlink(missing_ok=True)

        # Prune old screenshot archives (keep last 30 days)
        screenshots_dir = RESULTS_DIR / "screenshots"
        if screenshots_dir.is_dir():
            date_dirs = sorted(
                [d for d in screenshots_dir.iterdir()
                 if d.is_dir() and d.name != "current" and len(d.name) == 10],
                reverse=True,
            )
            for old_dir in date_dirs[30:]:
                shutil.rmtree(old_dir, ignore_errors=True)
                _log(f"Pruned old screenshot archive: {old_dir.name}")

        # Start claude analysis on failures (reuse helper)
        if result.summary["failed"] > 0:
            helper = PROJECT_ROOT / "scripts" / "_daily_runner_helper.py"
            if helper.is_file():
                _log("Starting claude analysis for failures...")
                subprocess.run(
                    [sys.executable, str(helper), "start-claude-analysis"],
                    env={**os.environ, "RESULTS_DIR": str(RESULTS_DIR)},
                )

        # Send summary email
        _log("Sending summary email...")
        self.notification.send_summary_email(result)

    def _print_summary(self, result: RunResult) -> None:
        """Print a formatted summary."""
        s = result.summary
        dur_min = int(result.duration_seconds // 60)
        dur_sec = int(result.duration_seconds % 60)

        print()
        print("=" * 60)
        status_icon = "✓" if s["failed"] == 0 else "✗"
        print(f"  {status_icon} Summary")
        print("=" * 60)
        print(f"  Total: {s['total']}  Passed: {s['passed']}  Failed: {s['failed']}  "
              f"Skipped: {s['skipped']}  Not started: {s.get('not_started', 0)}")
        print(f"  Duration: {dur_min}m {dur_sec}s")
        print(f"  Git: {result.git_sha}@{result.git_branch}")

        if s["failed"] > 0:
            print()
            print("  Failed tests:")
            for suite_name, suite_data in result.suites.items():
                for t in suite_data.get("tests", []):
                    if t.get("status") == "failed":
                        name = t.get("file", t.get("name", "?"))
                        error = (t.get("error") or "")[:120]
                        print(f"    [{suite_name}] {name}: {error}")

        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenMates unified test orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--suite", choices=["all", "vitest", "pytest", "playwright"], default="all",
                        help="Suite to run (default: all)")
    parser.add_argument("--spec", type=str, default=None,
                        help="Run a single Playwright spec (e.g., chat-flow.spec.ts)")
    parser.add_argument("--only-failed", action="store_true",
                        help="Rerun only tests that failed in last-run.json")
    parser.add_argument("--daily", action="store_true",
                        help="Daily cron mode (commit gate, emails, OpenObserve)")
    parser.add_argument("--hourly-dev", action="store_true",
                        help="Hourly DEV smoke (4 specs, post on failure to "
                             "DISCORD_WEBHOOK_DEV_SMOKE). See OPE-349.")
    parser.add_argument("--hourly-prod", action="store_true",
                        help="Hourly PROD smoke (dispatches prod-smoke.yml, "
                             "posts on failure to DISCORD_WEBHOOK_PROD_SMOKE).")
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
    parser.add_argument("--no-fail-fast", action="store_true",
                        help="Don't stop on first batch failure")
    parser.add_argument("--no-mocks", action="store_true",
                        help="Run with real LLM calls instead of mocks")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without executing")
    parser.add_argument("--flaky-report", action="store_true",
                        help="Show top flaky tests from history and exit")

    args = parser.parse_args()

    if args.flaky_report:
        _print_flaky_report()
        return 0

    # Reject incompatible mode combinations early so the user gets a clear
    # error instead of weird half-runs.
    mode_flags = sum(int(x) for x in (args.daily, args.hourly_dev, args.hourly_prod))
    if mode_flags > 1:
        _log("Pass at most one of: --daily, --hourly-dev, --hourly-prod", "ERROR")
        return 2

    # Always source .env into the process so cron jobs (which only run via
    # bash with `set -a && . .env`) and direct invocations both work.
    dot_env = _read_env_file()
    for k, v in dot_env.items():
        if k not in os.environ:
            os.environ[k] = v

    # --dry-run-notify: short-circuit before any spec dispatch.
    if args.dry_run_notify:
        notification = NotificationService()
        if args.hourly_dev:
            return run_dry_run_notify_mode(notification, "hourly-dev")
        if args.hourly_prod:
            return run_dry_run_notify_mode(notification, "hourly-prod")
        if args.daily:
            return run_dry_run_notify_mode(notification, "daily")
        _log("--dry-run-notify requires one of: --daily, --hourly-dev, --hourly-prod", "ERROR")
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
            return run_hourly_dev_mode(NotificationService(), force=args.force)
        finally:
            if lock_fd:
                lock_fd.close()

    # --hourly-prod: separate lockfile (same rationale as --hourly-dev).
    if args.hourly_prod:
        lock_fd = None
        try:
            lock_fd = open(LOCKFILE_HOURLY_PROD, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _log("Another --hourly-prod run is in progress — skipping this hour")
            return 0
        try:
            return run_hourly_prod_mode(NotificationService(), force=args.force)
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
            return 0

    try:
        orchestrator = TestOrchestrator(args)
        return orchestrator.run()
    finally:
        if lock_fd:
            lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())
