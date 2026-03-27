#!/usr/bin/env python3
"""
scripts/_daily_meeting_helper.py

Daily standup meeting orchestrator — gathers data from 10 sources, spawns
3 parallel Claude subagent sessions (health, work, linear) to summarize,
then launches the main meeting session with the compact reports.

Architecture context: See .claude/plans/binary-orbiting-thacker.md

Commands:
    gather          Gather all data and run subagents (writes .tmp/ reports)
    run-meeting     Full pipeline: gather → subagents → main meeting session
    dry-run         Gather data and print what would be sent (no Claude sessions)
    auto-confirm    Apply proposed priorities to Linear (called by timer)

State file: scripts/.daily-meeting-state.json
Subagent outputs: scripts/.tmp/daily-meeting-{health,work,linear}.md

Data sources:
    A. git log (24h)                    — subprocess
    B. test-results/last-run.json       — file read
    C. /v1/status (provider health)     — HTTP request
    D. OpenObserve errors (dev + prod)  — docker exec debug.py
    E. check-file-sizes.sh --ci         — subprocess
    F. Nightly job state files          — file reads
    G. Workflow review (session quality) — import from _workflow_review_helper
    H. User-reported issues             — import from _issues_checker
    I. Linear tasks                     — gathered by linear subagent (MCP)
    J. Milestone state                  — file read (.planning/)

Importable from other helpers:
    gather_all_data(project_root: str, yesterday: str) → dict
"""

import glob as glob_mod
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

from _claude_utils import run_claude_session


# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TMP_DIR = SCRIPTS_DIR / ".tmp"
STATE_FILE = SCRIPTS_DIR / ".daily-meeting-state.json"
TEST_RESULTS_DIR = PROJECT_ROOT / "test-results"

# Prompt templates
PROMPT_HEALTH = SCRIPTS_DIR / "prompts" / "daily-meeting-health.md"
PROMPT_WORK = SCRIPTS_DIR / "prompts" / "daily-meeting-work.md"
PROMPT_LINEAR = SCRIPTS_DIR / "prompts" / "daily-meeting-linear.md"
PROMPT_MEETING = SCRIPTS_DIR / "prompts" / "daily-meeting.md"

# Internal API for provider status
INTERNAL_API_URL = os.environ.get("INTERNAL_API_URL", "http://localhost:8000")

# Auto-confirm timeout (seconds) — 70 minutes
AUTO_CONFIRM_TIMEOUT = 70 * 60

LOG_PREFIX = "[daily-meeting]"


# ── State management ─────────────────────────────────────────────────────────

def load_meeting_state() -> dict:
    """Load previous meeting state, or return empty state."""
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception as e:
            print(f"{LOG_PREFIX} WARNING: could not load state: {e}", file=sys.stderr)
    return {
        "last_meeting": None,
        "date": None,
        "priorities": [],
        "confirmed_by": None,
        "confirmed_at": None,
        "session_id": None,
        "data_failures": [],
        "auto_created_tasks": [],
    }


def save_meeting_state(state: dict) -> None:
    """Atomically save meeting state."""
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_FILE)
    print(f"{LOG_PREFIX} State saved: {STATE_FILE}")


# ── Data gathering functions ─────────────────────────────────────────────────

def _safe_read(path: Path, label: str) -> str:
    """Read a file, returning a DATA UNAVAILABLE marker on failure."""
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return f"[DATA UNAVAILABLE: {label} — file not found: {path}]"
    except Exception as e:
        return f"[DATA UNAVAILABLE: {label} — {e}]"


def _safe_json_read(path: Path, label: str) -> str:
    """Read a JSON file and return pretty-printed content."""
    try:
        if path.is_file():
            data = json.loads(path.read_text())
            return json.dumps(data, indent=2)
        return f"[DATA UNAVAILABLE: {label} — file not found]"
    except Exception as e:
        return f"[DATA UNAVAILABLE: {label} — {e}]"


def gather_git_log(project_root: str) -> str:
    """Source A: git commits from the last 24 hours."""
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "log", "--since=24 hours ago",
             "--oneline", "--stat", "--no-color"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        return output if output else "(No commits in the last 24 hours.)"
    except Exception as e:
        return f"[DATA UNAVAILABLE: git log — {e}]"


def gather_test_results() -> dict:
    """Source B: test results from last run."""
    summary = _safe_json_read(TEST_RESULTS_DIR / "last-run.json", "test summary")
    failed = _safe_json_read(TEST_RESULTS_DIR / "last-failed-tests.json", "failed tests")

    # Gather failed test .md reports (with screenshots)
    failed_reports = []
    reports_dir = TEST_RESULTS_DIR / "reports" / "failed"
    if reports_dir.is_dir():
        for md_path in sorted(reports_dir.glob("*.md")):
            content = _safe_read(md_path, f"failed report {md_path.name}")
            # Cap each report at 4000 chars to avoid context explosion
            if len(content) > 4000:
                content = content[:4000] + "\n\n[...truncated...]"
            failed_reports.append(f"### {md_path.name}\n\n{content}")

    # Coverage
    vitest_cov = _safe_json_read(
        TEST_RESULTS_DIR / "coverage" / "vitest-coverage.json", "vitest coverage"
    )
    pytest_cov = _safe_json_read(
        TEST_RESULTS_DIR / "coverage" / "pytest-coverage.json", "pytest coverage"
    )

    # Prod smoke
    prod_smoke = _safe_json_read(
        TEST_RESULTS_DIR / "last-run-prod-smoke.json", "production smoke tests"
    )

    return {
        "summary": summary,
        "failed": failed,
        "failed_reports": "\n\n---\n\n".join(failed_reports) if failed_reports else "(No failed test reports found.)",
        "coverage": f"**Vitest:**\n{vitest_cov}\n\n**Pytest:**\n{pytest_cov}",
        "prod_smoke": prod_smoke,
    }


def gather_provider_health() -> str:
    """Source C: provider health from /v1/status endpoint."""
    url = f"{INTERNAL_API_URL.rstrip('/')}/v1/status"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Extract unhealthy/degraded services
        lines = []
        groups = data.get("groups", [])
        all_healthy = True

        for group in groups:
            group_name = group.get("name", "Unknown")
            services = group.get("services", [])
            for svc in services:
                status = svc.get("status", "unknown")
                if status not in ("healthy", "operational"):
                    all_healthy = False
                    name = svc.get("name", "unknown")
                    error = svc.get("error", "")
                    response_time = svc.get("response_time_ms", "")
                    lines.append(
                        f"- **{group_name} / {name}**: {status}"
                        + (f" — {error}" if error else "")
                        + (f" ({response_time}ms)" if response_time else "")
                    )

        if all_healthy:
            total_services = sum(len(g.get("services", [])) for g in groups)
            return f"All {total_services} services healthy."
        return "\n".join(lines)

    except Exception as e:
        return f"[DATA UNAVAILABLE: provider health — {e}]"


def gather_openobserve_errors(production: bool = False) -> str:
    """Source D: top errors from OpenObserve via debug.py."""
    env_label = "production" if production else "dev"
    cmd = [
        "docker", "exec", "api", "python",
        "/app/backend/scripts/debug.py", "logs",
        "--o2",
        "--sql", (
            'SELECT log, COUNT(*) as count FROM "default" '
            "WHERE compose_project = 'openmates-core' "
            "AND (LOWER(log) LIKE '%error%' OR LOWER(log) LIKE '%exception%' "
            "OR LOWER(log) LIKE '%traceback%') "
            "GROUP BY log ORDER BY count DESC LIMIT 10"
        ),
        "--json", "--quiet-health",
    ]
    if production:
        cmd.append("--production")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()[:500]
            return f"[DATA UNAVAILABLE: OpenObserve {env_label} — exit code {result.returncode}: {stderr}]"
        return output if output else f"(No errors found in OpenObserve {env_label} in the last 24h.)"
    except subprocess.TimeoutExpired:
        return f"[DATA UNAVAILABLE: OpenObserve {env_label} — query timed out after 60s]"
    except Exception as e:
        return f"[DATA UNAVAILABLE: OpenObserve {env_label} — {e}]"


def gather_large_files(project_root: str) -> str:
    """Source E: large file check via check-file-sizes.sh --ci."""
    script = os.path.join(project_root, "scripts", "check-file-sizes.sh")
    try:
        result = subprocess.run(
            ["bash", script, "--ci"],
            capture_output=True, text=True, timeout=30,
            cwd=project_root,
        )
        output = result.stdout.strip()
        if result.returncode == 0:
            return output if output else "No new large file violations."
        # returncode 1 = new violations found
        return output if output else "Large file check returned violations but no output."
    except Exception as e:
        return f"[DATA UNAVAILABLE: large file check — {e}]"


def gather_nightly_state_files() -> dict:
    """Source F: nightly job state files."""
    return {
        "dependabot": _safe_json_read(
            SCRIPTS_DIR / "dependabot-processed.json", "dependabot state"
        ),
        "dead_code": _safe_json_read(
            SCRIPTS_DIR / ".dead-code-removal-state.json", "dead code state"
        ),
        "security": _safe_json_read(
            PROJECT_ROOT / ".claude" / "security-audit-state.json", "security audit state"
        ),
        "audit": _safe_json_read(
            SCRIPTS_DIR / ".audit-state.json", "codebase audit state"
        ),
    }


def gather_session_quality(yesterday: str) -> str:
    """Source G: session quality data from workflow review helper."""
    try:
        # Import from sibling helper
        from _workflow_review_helper import build_session_digests
        digest_text, count, chars = build_session_digests(yesterday, verbose=False)
        if count == 0:
            return "(No relevant Claude Code sessions found for yesterday.)"
        return f"({count} sessions, {chars:,} chars extracted)\n\n{digest_text}"
    except Exception as e:
        return f"[DATA UNAVAILABLE: session quality — {e}]"


def gather_user_issues(project_root: str) -> str:
    """Source H: user-reported issues from admin debug API."""
    try:
        from _issues_checker import fetch_open_issues, get_admin_api_key
        admin_key = get_admin_api_key(project_root)
        if not admin_key:
            return "[DATA UNAVAILABLE: user issues — admin API key not configured]"
        issues = fetch_open_issues(admin_key, lookback_hours=24)
        if not issues:
            return "No user-reported issues in the last 24h."
        lines = []
        for issue in issues[:15]:
            issue_id = issue.get("id", "?")
            title = issue.get("title", "(no title)")
            desc = (issue.get("description", "") or "")[:200]
            lines.append(f"- **{issue_id}**: {title}\n  {desc}")
        return "\n".join(lines)
    except Exception as e:
        return f"[DATA UNAVAILABLE: user issues — {e}]"


def gather_milestone_state() -> str:
    """Source J: milestone state from .planning/."""
    planning_dir = PROJECT_ROOT / ".planning"

    # Try PROJECT.md first
    project_md = planning_dir / "PROJECT.md"
    if project_md.is_file():
        content = project_md.read_text(errors="replace")
        # Cap at 3000 chars — milestone overview should be at the top
        if len(content) > 3000:
            content = content[:3000] + "\n\n[...truncated...]"
        return content

    # Fallback: check config.json
    config = planning_dir / "config.json"
    if config.is_file():
        return _safe_json_read(config, "planning config")

    return "(No milestone state found in .planning/ directory.)"


def gather_all_data(project_root: str, yesterday: str) -> dict:
    """
    Gather all 10 data sources in parallel where possible.

    Returns a dict with keys matching the subagent template placeholders.
    """
    data = {}
    failures = []

    print(f"{LOG_PREFIX} Gathering data from 10 sources...")

    # Run independent data sources in parallel
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(gather_git_log, project_root): "git_log",
            pool.submit(gather_test_results): "test_results",
            pool.submit(gather_provider_health): "provider_health",
            pool.submit(gather_openobserve_errors, False): "openobserve_dev",
            pool.submit(gather_openobserve_errors, True): "openobserve_prod",
            pool.submit(gather_large_files, project_root): "large_files",
            pool.submit(gather_user_issues, project_root): "user_issues",
            pool.submit(gather_session_quality, yesterday): "session_quality",
        }

        for future in as_completed(futures):
            key = futures[future]
            try:
                data[key] = future.result()
            except Exception as e:
                data[key] = f"[DATA UNAVAILABLE: {key} — {e}]"
                failures.append(key)

    # Sequential: nightly state files (fast file reads)
    data["nightly_states"] = gather_nightly_state_files()
    data["milestone_state"] = gather_milestone_state()

    # Load previous meeting state
    data["previous_state"] = load_meeting_state()

    # Track failures
    for key, value in data.items():
        if isinstance(value, str) and value.startswith("[DATA UNAVAILABLE:"):
            if key not in failures:
                failures.append(key)
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, str) and sub_value.startswith("[DATA UNAVAILABLE:"):
                    failures.append(f"{key}.{sub_key}")

    data["_failures"] = failures
    print(f"{LOG_PREFIX} Data gathered. Failures: {len(failures)} ({', '.join(failures) if failures else 'none'})")

    return data


# ── Subagent prompt builders ─────────────────────────────────────────────────

def build_health_prompt(data: dict, today: str) -> str:
    """Build the health subagent prompt from gathered data."""
    template = PROMPT_HEALTH.read_text()
    test = data.get("test_results", {})

    return (
        template
        .replace("{{DATE}}", today)
        .replace("{{TEST_SUMMARY}}", test.get("summary", "N/A") if isinstance(test, dict) else str(test))
        .replace("{{FAILED_TESTS}}", test.get("failed_reports", "N/A") if isinstance(test, dict) else "N/A")
        .replace("{{COVERAGE}}", test.get("coverage", "N/A") if isinstance(test, dict) else "N/A")
        .replace("{{PROD_SMOKE}}", test.get("prod_smoke", "N/A") if isinstance(test, dict) else "N/A")
        .replace("{{PROVIDER_HEALTH}}", data.get("provider_health", "N/A"))
        .replace("{{OPENOBSERVE_DEV}}", data.get("openobserve_dev", "N/A"))
        .replace("{{OPENOBSERVE_PROD}}", data.get("openobserve_prod", "N/A"))
        .replace("{{LARGE_FILES}}", data.get("large_files", "N/A"))
    )


def build_work_prompt(data: dict, today: str, yesterday: str) -> str:
    """Build the work subagent prompt from gathered data."""
    template = PROMPT_WORK.read_text()
    nightly = data.get("nightly_states", {})

    return (
        template
        .replace("{{DATE}}", today)
        .replace("{{YESTERDAY}}", yesterday)
        .replace("{{GIT_LOG}}", data.get("git_log", "N/A"))
        .replace("{{DEPENDABOT_STATE}}", nightly.get("dependabot", "N/A"))
        .replace("{{DEAD_CODE_STATE}}", nightly.get("dead_code", "N/A"))
        .replace("{{SECURITY_STATE}}", nightly.get("security", "N/A"))
        .replace("{{AUDIT_STATE}}", nightly.get("audit", "N/A"))
        .replace("{{SESSION_DIGESTS}}", data.get("session_quality", "N/A"))
        .replace("{{USER_ISSUES}}", data.get("user_issues", "N/A"))
    )


def build_linear_prompt(data: dict, today: str, yesterday: str) -> str:
    """Build the linear subagent prompt from gathered data.

    Note: The linear subagent uses MCP tools to query Linear directly,
    so we only inject the milestone state and previous priorities here.
    The template placeholders for Linear data are filled by the subagent.
    """
    template = PROMPT_LINEAR.read_text()
    prev_state = data.get("previous_state", {})
    priorities = prev_state.get("priorities", [])

    if priorities:
        priority_lines = []
        for p in priorities:
            priority_lines.append(
                f"- {p.get('linear_id', '?')}: {p.get('title', '?')} "
                f"(status at selection: {p.get('status_at_selection', '?')})"
            )
        yesterday_priorities = "\n".join(priority_lines)
    else:
        yesterday_priorities = "(No daily priorities were set yesterday.)"

    return (
        template
        .replace("{{DATE}}", today)
        .replace("{{YESTERDAY}}", yesterday)
        .replace("{{YESTERDAY_PRIORITIES}}", yesterday_priorities)
        .replace("{{ACTIVE_TASKS}}", "(Use Linear MCP tools to query all active tasks: mcp__linear__list_issues with status filter)")
        .replace("{{RECENTLY_COMPLETED}}", "(Use Linear MCP tools to query recently completed tasks)")
        .replace("{{MILESTONE_STATE}}", data.get("milestone_state", "N/A"))
    )


def build_meeting_prompt(today: str, yesterday: str, session_id: str) -> str:
    """Build the main meeting session prompt."""
    template = PROMPT_MEETING.read_text()
    return (
        template
        .replace("{{DATE}}", today)
        .replace("{{YESTERDAY}}", yesterday)
        .replace("{{SESSION_ID}}", session_id or "unknown")
    )


# ── Subagent runner ──────────────────────────────────────────────────────────

def run_subagent(name: str, prompt: str, today: str) -> tuple[str, int, str | None]:
    """
    Run a subagent Claude session and return (name, returncode, session_id).

    The subagent writes its report to scripts/.tmp/daily-meeting-{name}.md.
    """
    session_title = f"daily-meeting-{name} {today}"

    # For the linear subagent, we need MCP access (Linear tools), so use plan
    # mode with allowed tools. Health and work subagents are pure data summaries.
    if name == "linear":
        allowed_tools = [
            "Read", "Grep", "Glob",
            "mcp__linear__list_issues",
            "mcp__linear__get_issue",
            "mcp__linear__save_issue",
            "mcp__linear__save_comment",
        ]
    else:
        allowed_tools = ["Read", "Grep", "Glob"]

    # Wrap the prompt to tell the subagent where to write its report
    output_path = f"scripts/.tmp/daily-meeting-{name}.md"
    wrapped_prompt = (
        f"{prompt}\n\n---\n\n"
        f"**IMPORTANT:** Write your complete report to `{output_path}` using the Write tool. "
        f"This file will be read by the main meeting session."
    )

    returncode, session_id = run_claude_session(
        prompt=wrapped_prompt,
        session_title=session_title,
        project_root=str(PROJECT_ROOT),
        log_prefix=f"{LOG_PREFIX}[{name}]",
        agent="plan",
        allowed_tools=allowed_tools + ["Write"],
        timeout=300,
        job_type=None,  # No email for subagents
    )

    return name, returncode, session_id


def run_subagents(data: dict, today: str, yesterday: str) -> dict:
    """
    Run all 3 subagents in parallel. Returns dict of {name: success_bool}.
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    prompts = {
        "health": build_health_prompt(data, today),
        "work": build_work_prompt(data, today, yesterday),
        "linear": build_linear_prompt(data, today, yesterday),
    }

    results = {}
    print(f"{LOG_PREFIX} Spawning 3 subagents in parallel...")

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(run_subagent, name, prompt, today): name
            for name, prompt in prompts.items()
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                agent_name, rc, sid = future.result()
                success = rc == 0
                results[agent_name] = success
                status = "OK" if success else f"FAILED (exit {rc})"
                print(f"{LOG_PREFIX} Subagent '{agent_name}': {status}")
            except Exception as e:
                results[name] = False
                print(f"{LOG_PREFIX} Subagent '{name}' exception: {e}", file=sys.stderr)

    # Write fallback reports for failed subagents
    for name, success in results.items():
        report_path = TMP_DIR / f"daily-meeting-{name}.md"
        if not success and not report_path.is_file():
            report_path.write_text(
                f"## {name.title()} Report — {today}\n\n"
                f"[SUBAGENT FAILED: The {name} subagent did not complete successfully. "
                f"Data may be partially available in the raw gathered data.]\n"
            )

    return results


# ── Main meeting session ─────────────────────────────────────────────────────

def run_meeting_session(today: str, yesterday: str) -> tuple[int, str | None]:
    """
    Run the main meeting Claude session (interactive, Opus).

    Returns (returncode, session_id).
    """
    session_title = f"daily-meeting {today}"
    prompt = build_meeting_prompt(today, yesterday, session_id="(will be set after start)")

    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(PROJECT_ROOT),
        log_prefix=LOG_PREFIX,
        # Main meeting runs in build mode (not plan) so it can write state file
        # and use Linear MCP tools for label management
        agent=None,
        timeout=1800,
        job_type="daily-meeting",
        context_summary="Daily standup meeting — review, health, priorities",
    )

    return returncode, session_id


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_dry_run(yesterday: str) -> None:
    """Gather data and print what would be sent, without starting Claude sessions."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"{LOG_PREFIX} DRY RUN — gathering data for {today} (reviewing {yesterday})")

    data = gather_all_data(str(PROJECT_ROOT), yesterday)

    print(f"\n{'=' * 70}")
    print("HEALTH SUBAGENT PROMPT (first 3000 chars):")
    print("=" * 70)
    health_prompt = build_health_prompt(data, today)
    print(health_prompt[:3000])
    if len(health_prompt) > 3000:
        print(f"\n... ({len(health_prompt) - 3000:,} more chars)")

    print(f"\n{'=' * 70}")
    print("WORK SUBAGENT PROMPT (first 3000 chars):")
    print("=" * 70)
    work_prompt = build_work_prompt(data, today, yesterday)
    print(work_prompt[:3000])
    if len(work_prompt) > 3000:
        print(f"\n... ({len(work_prompt) - 3000:,} more chars)")

    print(f"\n{'=' * 70}")
    print("LINEAR SUBAGENT PROMPT (first 3000 chars):")
    print("=" * 70)
    linear_prompt = build_linear_prompt(data, today, yesterday)
    print(linear_prompt[:3000])

    print(f"\n{'=' * 70}")
    print(f"Data failures: {data['_failures']}")
    print(f"Previous priorities: {data['previous_state'].get('priorities', [])}")
    print("=" * 70)


def cmd_gather(yesterday: str) -> None:
    """Gather data and run subagents (writes .tmp/ reports)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"{LOG_PREFIX} Phase 1: Gathering data for {today}...")

    data = gather_all_data(str(PROJECT_ROOT), yesterday)

    print(f"{LOG_PREFIX} Phase 2: Running subagents...")
    results = run_subagents(data, today, yesterday)

    success_count = sum(1 for v in results.values() if v)
    print(f"{LOG_PREFIX} Subagents complete: {success_count}/3 succeeded")


def cmd_run_meeting(yesterday: str) -> None:
    """Full pipeline: gather → subagents → main meeting session."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"{LOG_PREFIX} Starting daily meeting for {today}...")

    # Phase 1 + 2: gather and run subagents
    data = gather_all_data(str(PROJECT_ROOT), yesterday)
    subagent_results = run_subagents(data, today, yesterday)

    success_count = sum(1 for v in subagent_results.values() if v)
    print(f"{LOG_PREFIX} Subagents: {success_count}/3 succeeded. Starting main meeting...")

    # Phase 3: main meeting session
    returncode, session_id = run_meeting_session(today, yesterday)

    if session_id:
        print(f"CLAUDE_SESSION_ID:{session_id}")
        print(f"{LOG_PREFIX} Resume command: claude resume --dangerous {session_id}")

    if returncode != 0:
        print(f"{LOG_PREFIX} Meeting session exited with code {returncode}", file=sys.stderr)
        sys.exit(returncode)


def cmd_auto_confirm() -> None:
    """
    Apply proposed priorities from the meeting to Linear.

    Called by the auto-confirm timer after 70 minutes if the user didn't join.
    Reads the Linear report, extracts proposed tasks, and applies labels via
    the Linear API directly (no Claude session needed).
    """
    state = load_meeting_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if priorities were already confirmed today
    if state.get("date") == today and state.get("confirmed_by"):
        print(f"{LOG_PREFIX} Priorities already confirmed for {today} by {state['confirmed_by']} — skipping.")
        return

    # Read the linear subagent report to extract proposed priorities
    linear_report = TMP_DIR / "daily-meeting-linear.md"
    if not linear_report.is_file():
        print(f"{LOG_PREFIX} ERROR: Linear report not found at {linear_report}", file=sys.stderr)
        sys.exit(1)

    report_content = linear_report.read_text()

    # Parse OPE-XX IDs from the "Proposed Top 3" section
    import re
    proposed_ids = re.findall(r'\*\*OPE-\d+:', report_content)
    proposed_ids = [pid.strip("*:") for pid in proposed_ids[:3]]

    if not proposed_ids:
        print(f"{LOG_PREFIX} WARNING: Could not extract proposed priorities from Linear report.")
        print(f"{LOG_PREFIX} Auto-confirm skipped — manual confirmation needed.")
        return

    print(f"{LOG_PREFIX} Auto-confirming priorities: {', '.join(proposed_ids)}")

    # Update state with auto-confirmed priorities
    state["date"] = today
    state["last_meeting"] = datetime.now(timezone.utc).isoformat()
    state["priorities"] = [
        {"linear_id": pid, "title": "(auto-confirmed)", "status_at_selection": "unknown"}
        for pid in proposed_ids
    ]
    state["confirmed_by"] = "auto"
    state["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    save_meeting_state(state)

    print(f"{LOG_PREFIX} Auto-confirm complete. Linear labels should be applied in next meeting session.")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    # Default to yesterday in UTC
    override_date = os.environ.get("MEETING_DATE", "")
    if override_date:
        yesterday = override_date
    else:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    if not args:
        print(f"Usage: {sys.argv[0]} <dry-run|gather|run-meeting|auto-confirm>", file=sys.stderr)
        sys.exit(1)

    command = args[0]
    if command == "dry-run":
        cmd_dry_run(yesterday)
    elif command == "gather":
        cmd_gather(yesterday)
    elif command == "run-meeting":
        cmd_run_meeting(yesterday)
    elif command == "auto-confirm":
        cmd_auto_confirm()
    else:
        print(f"{LOG_PREFIX} Unknown command: {command}", file=sys.stderr)
        print(f"Usage: {sys.argv[0]} <dry-run|gather|run-meeting|auto-confirm>", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
