#!/usr/bin/env python3
"""
scripts/_daily_meeting_helper.py

Daily standup meeting orchestrator — gathers data from 10 sources and launches
the main meeting session with the data injected directly into the prompt.

No subagents: the meeting session reads nightly reports and live data directly,
avoiding a redundant summarization layer that added latency and failure risk.

Commands:
    run-meeting     Full pipeline: gather data → start main meeting session
    dry-run         Gather data and print the meeting prompt (no Claude session)
    auto-confirm    Apply proposed priorities to Linear (called by timer)
    spawn-planning  Spawn planning sessions for confirmed priorities

State file: scripts/.daily-meeting-state.json

Data sources:
    A. git log (24h)                    — subprocess
    B. test-results/last-run.json       — file read
    C. /v1/status (provider health)     — HTTP request
    D. OpenObserve errors (dev + prod)  — docker exec debug.py
    E. check-file-sizes.sh --ci         — subprocess
    F. Nightly job state files          — file reads (logs/nightly-reports/)
    G. Workflow review (session quality) — import from _workflow_review_helper
    H. User-reported issues             — docker exec debug_issue.py (Vault key)
    I. Linear tasks                     — queried live by meeting session (MCP)
    J. Milestone state                  — file read (.planning/)
    K. Server stats                     — docker exec server_stats_query.py

Importable from other helpers:
    gather_all_data(project_root: str, yesterday: str) → dict
"""

import json
import os
import subprocess
import sys
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

# Main meeting prompt template
PROMPT_MEETING = SCRIPTS_DIR / "prompts" / "daily-meeting.md"
PROMPT_PLANNING = SCRIPTS_DIR / "prompts" / "daily-planning-task.md"

# Internal API for provider status
INTERNAL_API_URL = os.environ.get("INTERNAL_API_URL", "http://localhost:8000")

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
             "--oneline", "--no-color"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if not output:
            return "(No commits in the last 24 hours.)"
        if len(output) > 5000:
            lines = output.splitlines()
            output = "\n".join(lines[:80]) + f"\n\n[...{len(lines) - 80} more commits truncated...]"
        return output
    except Exception as e:
        return f"[DATA UNAVAILABLE: git log — {e}]"


def gather_test_results() -> dict:
    """Source B: test results from last run."""
    try:
        last_run_path = TEST_RESULTS_DIR / "last-run.json"
        if last_run_path.is_file():
            full_data = json.loads(last_run_path.read_text())
            compact = {
                "run_id": full_data.get("run_id"),
                "git_sha": full_data.get("git_sha"),
                "git_branch": full_data.get("git_branch"),
                "duration_seconds": full_data.get("duration_seconds"),
                "summary": full_data.get("summary", {}),
                "suites": {},
            }
            for suite_name, suite_data in full_data.get("suites", {}).items():
                failed_tests = [
                    {"name": t["name"], "status": t["status"],
                     "error": (t.get("error") or "")[:300]}
                    for t in suite_data.get("tests", [])
                    if t.get("status") != "passed"
                ]
                compact["suites"][suite_name] = {
                    "status": suite_data.get("status"),
                    "total_tests": len(suite_data.get("tests", [])),
                    "failed_tests": failed_tests,
                }
            summary = json.dumps(compact, indent=2)
        else:
            summary = "[DATA UNAVAILABLE: test summary — file not found]"
    except Exception as e:
        summary = f"[DATA UNAVAILABLE: test summary — {e}]"

    try:
        failed_path = TEST_RESULTS_DIR / "last-failed-tests.json"
        if failed_path.is_file():
            failed_data = json.loads(failed_path.read_text())
            if isinstance(failed_data, list):
                capped = []
                for t in failed_data[:10]:
                    capped.append({
                        "name": t.get("name", "?"),
                        "status": t.get("status", "?"),
                        "error": (t.get("error") or "")[:500],
                    })
                failed = json.dumps(capped, indent=2)
            else:
                failed = json.dumps(failed_data, indent=2)[:5000]
        else:
            failed = "(No failed tests file found.)"
    except Exception as e:
        failed = f"[DATA UNAVAILABLE: failed tests — {e}]"

    # Gather failed test .md reports (with screenshots)
    failed_reports = []
    reports_dir = TEST_RESULTS_DIR / "reports" / "failed"
    if reports_dir.is_dir():
        for md_path in sorted(reports_dir.glob("*.md")):
            content = _safe_read(md_path, f"failed report {md_path.name}")
            if len(content) > 4000:
                content = content[:4000] + "\n\n[...truncated...]"
            failed_reports.append(f"### {md_path.name}\n\n{content}")

    # Coverage
    def _extract_coverage_summary(path: Path, label: str) -> str:
        try:
            if not path.is_file():
                return f"({label}: no coverage file)"
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                total = data.get("total", data.get("summary", {}))
                if total:
                    return json.dumps(total, indent=2)
                return json.dumps({k: type(v).__name__ for k, v in data.items()})
            return str(data)[:500]
        except Exception as e:
            return f"[DATA UNAVAILABLE: {label} — {e}]"

    vitest_cov = _extract_coverage_summary(
        TEST_RESULTS_DIR / "coverage" / "vitest-coverage.json", "vitest coverage"
    )
    pytest_cov = _extract_coverage_summary(
        TEST_RESULTS_DIR / "coverage" / "pytest-coverage.json", "pytest coverage"
    )

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
        "--since", "1440",
        "--sql", (
            'SELECT message, service, level, COUNT(*) as count FROM "default" '
            "WHERE compose_project = 'openmates-core' "
            "AND (level = 'ERROR' OR level = 'CRITICAL' "
            "OR LOWER(message) LIKE '%traceback%') "
            "GROUP BY message, service, level ORDER BY count DESC LIMIT 15"
        ),
        "--json", "--quiet-health",
    ]
    if production:
        cmd.append("--prod")

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


def gather_server_stats() -> str:
    """Source K: server stats from Directus (users, revenue, engagement, data health)."""
    cmd = [
        "docker", "exec", "api", "python3",
        "/app/backend/scripts/server_stats_query.py",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()[:500]
            return f"[DATA UNAVAILABLE: server stats — exit code {result.returncode}: {stderr}]"
        return output if output else "(No server stats available.)"
    except subprocess.TimeoutExpired:
        return "[DATA UNAVAILABLE: server stats — query timed out after 30s]"
    except Exception as e:
        return f"[DATA UNAVAILABLE: server stats — {e}]"


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
        return output if output else "Large file check returned violations but no output."
    except Exception as e:
        return f"[DATA UNAVAILABLE: large file check — {e}]"


def gather_nightly_state_files() -> dict:
    """Source F: auto-discover all nightly job reports from logs/nightly-reports/.

    Each cron job writes a standardized JSON report via _nightly_report.py.
    Returns a dict with per-job text summaries and a "_consolidated" key.
    """
    from _nightly_report import read_all_reports

    reports = read_all_reports()

    if not reports:
        return {
            "_consolidated": "(No nightly reports found in logs/nightly-reports/.)",
        }

    result: dict[str, str] = {}
    consolidated_lines: list[str] = []

    for job_name, report in sorted(reports.items()):
        status = report.get("status", "unknown")
        summary = report.get("summary", "No summary.")
        ran_at = report.get("ran_at", "unknown")
        details = report.get("details", {})
        disclosure = report.get("security_disclosure")

        lines = [f"Status: {status}", f"Last run: {ran_at}", f"Summary: {summary}"]
        if details:
            details_str = json.dumps(details, indent=2)
            if len(details_str) > 1000:
                details_str = details_str[:1000] + "\n  ...(truncated)"
            lines.append(f"Details:\n{details_str}")
        if disclosure:
            risk = disclosure.get("risk_summary", "")
            packages = disclosure.get("packages_updated", [])
            if risk:
                lines.append(f"Security disclosure: {risk}")
            if packages:
                for pkg in packages[:10]:
                    pkg_line = (
                        f"  - {pkg.get('name', '?')}: {pkg.get('severity', '?')} "
                        f"({pkg.get('ghsa_id', '?')}) — {pkg.get('summary', '')[:100]}"
                    )
                    lines.append(pkg_line)

        result[job_name] = "\n".join(lines)

        status_emoji = {"ok": "OK", "warning": "WARN", "error": "ERR", "skipped": "SKIP"}.get(
            status, status.upper()
        )
        consolidated_lines.append(f"- **{job_name}** [{status_emoji}]: {summary}")

    result["_consolidated"] = "\n".join(consolidated_lines)
    return result


def gather_session_quality(yesterday: str) -> str:
    """Source G: session quality data from workflow review helper."""
    try:
        from _workflow_review_helper import build_session_digests
        digest_text, count, chars = build_session_digests(yesterday, verbose=False)
        if count == 0:
            return "(No relevant Claude Code sessions found for yesterday.)"
        MAX_SESSION_CHARS = 8000
        if len(digest_text) > MAX_SESSION_CHARS:
            digest_text = digest_text[:MAX_SESSION_CHARS] + "\n\n[...truncated for daily meeting...]"
        return f"({count} sessions, {chars:,} chars total)\n\n{digest_text}"
    except Exception as e:
        return f"[DATA UNAVAILABLE: session quality — {e}]"


def gather_user_issues(project_root: str) -> str:
    """Source H: user-reported issues via debug_issue.py inside Docker."""
    cmd = [
        "docker", "exec", "api", "python",
        "/app/backend/scripts/debug_issue.py",
        "--list", "--json", "--list-limit", "15",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()[:300]
            return f"[DATA UNAVAILABLE: user issues — docker exec exit code {result.returncode}: {stderr}]"

        output = result.stdout.strip()
        if not output:
            return "No user-reported issues in the last 24h."

        data = json.loads(output)
        issues = data.get("issues", [])
        if not issues:
            return "No user-reported issues in the last 24h."

        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)
        lines = []
        for issue in issues:
            created_str = issue.get("created_at") or issue.get("timestamp", "")
            if created_str:
                try:
                    created_clean = str(created_str).replace("Z", "+00:00")
                    created_at = datetime.fromisoformat(created_clean)
                    if created_at < since_dt:
                        continue
                except (ValueError, TypeError):
                    pass

            issue_id = issue.get("id", "?")
            title = issue.get("title") or issue.get("decrypted", {}).get("title", "(no title)")
            desc = (issue.get("description") or issue.get("decrypted", {}).get("description", "") or "")[:200]
            lines.append(f"- **{issue_id}**: {title}\n  {desc}")

        if not lines:
            return "No user-reported issues in the last 24h."
        return "\n".join(lines)

    except subprocess.TimeoutExpired:
        return "[DATA UNAVAILABLE: user issues — docker exec timed out after 30s]"
    except json.JSONDecodeError as e:
        return f"[DATA UNAVAILABLE: user issues — invalid JSON from debug_issue.py: {e}]"
    except Exception as e:
        return f"[DATA UNAVAILABLE: user issues — {e}]"


def gather_milestone_state() -> str:
    """Source J: milestone state from .planning/."""
    planning_dir = PROJECT_ROOT / ".planning"

    project_md = planning_dir / "PROJECT.md"
    if project_md.is_file():
        content = project_md.read_text(errors="replace")
        if len(content) > 3000:
            content = content[:3000] + "\n\n[...truncated...]"
        return content

    config = planning_dir / "config.json"
    if config.is_file():
        return _safe_json_read(config, "planning config")

    return "(No milestone state found in .planning/ directory.)"


def gather_all_data(project_root: str, yesterday: str) -> dict:
    """Gather all data sources in parallel where possible.

    Returns a dict with all gathered data, ready for prompt injection.
    """
    data = {}
    failures = []

    print(f"{LOG_PREFIX} Gathering data from 11 sources...")

    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {
            pool.submit(gather_git_log, project_root): "git_log",
            pool.submit(gather_test_results): "test_results",
            pool.submit(gather_provider_health): "provider_health",
            pool.submit(gather_openobserve_errors, False): "openobserve_dev",
            pool.submit(gather_openobserve_errors, True): "openobserve_prod",
            pool.submit(gather_large_files, project_root): "large_files",
            pool.submit(gather_user_issues, project_root): "user_issues",
            pool.submit(gather_session_quality, yesterday): "session_quality",
            pool.submit(gather_server_stats): "server_stats",
        }

        for future in as_completed(futures):
            key = futures[future]
            try:
                data[key] = future.result()
            except Exception as e:
                data[key] = f"[DATA UNAVAILABLE: {key} — {e}]"
                failures.append(key)

    # Sequential: fast file reads
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


# ── Meeting prompt builder ───────────────────────────────────────────────────

def build_meeting_prompt(data: dict, today: str, yesterday: str) -> str:
    """Build the main meeting prompt with all gathered data injected directly.

    Instead of reading subagent reports, the meeting session receives
    all raw data inline — nightly reports, test results, health, etc.
    """
    template = PROMPT_MEETING.read_text()

    test = data.get("test_results", {})
    nightly = data.get("nightly_states", {})
    prev_state = data.get("previous_state", {})

    # Format yesterday's priorities
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

    # Nightly reports: consolidated + security details
    nightly_text = nightly.get("_consolidated", "N/A")
    for job_name, job_text in sorted(nightly.items()):
        if job_name.startswith("_"):
            continue
        if "Security disclosure:" in job_text:
            nightly_text += f"\n\n#### {job_name} (security details)\n{job_text}"

    # Data failures
    failures = data.get("_failures", [])
    failures_text = ", ".join(failures) if failures else "none"

    return (
        template
        .replace("{{DATE}}", today)
        .replace("{{YESTERDAY}}", yesterday)
        .replace("{{YESTERDAY_PRIORITIES}}", yesterday_priorities)
        .replace("{{GIT_LOG}}", data.get("git_log", "N/A"))
        .replace("{{NIGHTLY_REPORTS}}", nightly_text)
        .replace("{{SESSION_QUALITY}}", data.get("session_quality", "N/A"))
        .replace("{{USER_ISSUES}}", data.get("user_issues", "N/A"))
        .replace("{{TEST_SUMMARY}}", test.get("summary", "N/A") if isinstance(test, dict) else str(test))
        .replace("{{FAILED_TESTS}}", test.get("failed_reports", "N/A") if isinstance(test, dict) else "N/A")
        .replace("{{COVERAGE}}", test.get("coverage", "N/A") if isinstance(test, dict) else "N/A")
        .replace("{{PROD_SMOKE}}", test.get("prod_smoke", "N/A") if isinstance(test, dict) else "N/A")
        .replace("{{PROVIDER_HEALTH}}", data.get("provider_health", "N/A"))
        .replace("{{OPENOBSERVE_DEV}}", data.get("openobserve_dev", "N/A"))
        .replace("{{OPENOBSERVE_PROD}}", data.get("openobserve_prod", "N/A"))
        .replace("{{LARGE_FILES}}", data.get("large_files", "N/A"))
        .replace("{{SERVER_STATS}}", data.get("server_stats", "N/A"))
        .replace("{{MILESTONE_STATE}}", data.get("milestone_state", "N/A"))
        .replace("{{DATA_FAILURES}}", failures_text)
    )


# ── Main meeting session ─────────────────────────────────────────────────────

def run_meeting_session(data: dict, today: str, yesterday: str) -> tuple[int, str | None]:
    """Run the main meeting Claude session (interactive).

    Returns (returncode, session_id).
    """
    session_title = f"daily-meeting {today}"
    prompt = build_meeting_prompt(data, today, yesterday)

    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(PROJECT_ROOT),
        log_prefix=LOG_PREFIX,
        agent=None,
        timeout=1800,
        job_type="daily-meeting",
        context_summary="Daily standup meeting — review, health, priorities",
        linear_task=False,
    )

    return returncode, session_id


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_dry_run(yesterday: str) -> None:
    """Gather data and print the meeting prompt (no Claude session)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"{LOG_PREFIX} DRY RUN — gathering data for {today} (reviewing {yesterday})")

    data = gather_all_data(str(PROJECT_ROOT), yesterday)

    print(f"\n{'=' * 70}")
    print("MEETING PROMPT (first 5000 chars):")
    print("=" * 70)
    prompt = build_meeting_prompt(data, today, yesterday)
    print(prompt[:5000])
    if len(prompt) > 5000:
        print(f"\n... ({len(prompt) - 5000:,} more chars)")

    print(f"\n{'=' * 70}")
    print(f"Total prompt length: {len(prompt):,} chars")
    print(f"Data failures: {data['_failures']}")
    print(f"Previous priorities: {data['previous_state'].get('priorities', [])}")
    print("=" * 70)


def cmd_run_meeting(yesterday: str) -> None:
    """Full pipeline: gather data → start main meeting session."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"{LOG_PREFIX} Starting daily meeting for {today}...")

    data = gather_all_data(str(PROJECT_ROOT), yesterday)

    print(f"{LOG_PREFIX} Starting meeting session...")
    returncode, session_id = run_meeting_session(data, today, yesterday)

    if session_id:
        print(f"CLAUDE_SESSION_ID:{session_id}")
        print(f"{LOG_PREFIX} Resume command: claude resume --dangerous {session_id}")

    if returncode != 0:
        print(f"{LOG_PREFIX} Meeting session exited with code {returncode}", file=sys.stderr)
        sys.exit(returncode)


def cmd_auto_confirm() -> None:
    """Apply proposed priorities from the meeting to Linear.

    Called by the auto-confirm timer after 70 minutes if the user didn't join.
    Reads the meeting summary to extract proposed tasks.
    """
    state = load_meeting_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if state.get("date") == today and state.get("confirmed_by"):
        print(f"{LOG_PREFIX} Priorities already confirmed for {today} by {state['confirmed_by']} — skipping.")
        return

    # Look for today's meeting summary
    import re
    summary_file = TMP_DIR / f"daily-meeting-summary-{today}.md"
    if not summary_file.is_file():
        print(f"{LOG_PREFIX} WARNING: Meeting summary not found at {summary_file}", file=sys.stderr)
        print(f"{LOG_PREFIX} Auto-confirm skipped — no meeting ran today.", file=sys.stderr)
        return

    report_content = summary_file.read_text()

    # Parse OPE-XX IDs from the priorities section
    proposed_ids = re.findall(r'OPE-\d+', report_content)
    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for pid in proposed_ids:
        if pid not in seen:
            seen.add(pid)
            unique_ids.append(pid)
    proposed_ids = unique_ids[:10]

    if not proposed_ids:
        print(f"{LOG_PREFIX} WARNING: Could not extract proposed priorities from meeting summary.")
        print(f"{LOG_PREFIX} Auto-confirm skipped — manual confirmation needed.")
        return

    print(f"{LOG_PREFIX} Auto-confirming priorities: {', '.join(proposed_ids)}")

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


# ── Spawn planning sessions ─────────────────────────────────────────────────


def build_planning_prompt(issue_data: dict, meeting_summary: str, today: str) -> str:
    """Fill the planning prompt template with Linear issue data and meeting context."""
    template = PROMPT_PLANNING.read_text()

    comments_text = "(No comments.)"
    if issue_data.get("comments"):
        lines = []
        for c in issue_data["comments"]:
            lines.append(f"**{c['author']}** ({c['created_at'][:10]}):\n{c['body']}")
        comments_text = "\n\n---\n\n".join(lines)

    return (
        template
        .replace("{{LINEAR_ID}}", issue_data.get("identifier", "?"))
        .replace("{{TASK_TITLE}}", issue_data.get("title", "?"))
        .replace("{{TASK_DESCRIPTION}}", issue_data.get("description") or "(No description.)")
        .replace("{{TASK_COMMENTS}}", comments_text)
        .replace("{{TASK_STATUS}}", issue_data.get("state", "?"))
        .replace("{{TASK_LABELS}}", ", ".join(issue_data.get("labels", [])) or "none")
        .replace("{{MEETING_CONTEXT}}", meeting_summary or "(No meeting context available.)")
        .replace("{{DATE}}", today)
    )


def cmd_spawn_planning() -> None:
    """Spawn planning sessions for today's confirmed priorities."""
    from _zellij_utils import spawn_claude_session, count_active_sessions, MAX_CONCURRENT_SESSIONS

    state = load_meeting_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if state.get("date") != today:
        print(f"{LOG_PREFIX} No confirmed priorities for today ({today}). Run the meeting first.", file=sys.stderr)
        sys.exit(1)

    priorities = state.get("priorities", [])
    if not priorities:
        print(f"{LOG_PREFIX} No priorities in state file.", file=sys.stderr)
        sys.exit(1)

    meeting_summary = ""
    summary_pattern = TMP_DIR / f"daily-meeting-summary-{today}.md"
    if summary_pattern.is_file():
        meeting_summary = summary_pattern.read_text(errors="replace")[:3000]

    try:
        from _linear_client import get_issue_with_comments
    except ImportError:
        print(f"{LOG_PREFIX} WARNING: _linear_client not available — spawning with minimal context.", file=sys.stderr)
        get_issue_with_comments = None

    spawned = []
    skipped = []
    for priority in priorities:
        linear_id = priority.get("linear_id", "")
        if not linear_id:
            continue

        active = count_active_sessions()
        if active >= MAX_CONCURRENT_SESSIONS:
            skipped.append(linear_id)
            print(
                f"{LOG_PREFIX} Skipping {linear_id} — "
                f"{active} active sessions (max {MAX_CONCURRENT_SESSIONS})"
            )
            continue

        session_name = f"plan-{linear_id}-{today}"
        print(f"{LOG_PREFIX} Spawning planning session for {linear_id}...")

        issue_data = None
        if get_issue_with_comments:
            issue_data = get_issue_with_comments(linear_id)

        if not issue_data:
            issue_data = {
                "identifier": linear_id,
                "title": priority.get("title", "Unknown"),
                "description": "",
                "state": priority.get("status_at_selection", "Unknown"),
                "labels": [],
                "comments": [],
            }

        prompt = build_planning_prompt(issue_data, meeting_summary, today)
        prompt_file = TMP_DIR / f"planning-prompt-{linear_id}.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        rel_path = prompt_file.relative_to(PROJECT_ROOT)
        claude_prompt = f"Read {rel_path} in full and follow all the instructions precisely."

        success = spawn_claude_session(
            session_name=session_name,
            prompt=claude_prompt,
            cwd=str(PROJECT_ROOT),
            permission_mode="plan",
        )

        if success:
            spawned.append((linear_id, session_name))
            print(f"{LOG_PREFIX}   → {session_name} (attach: zellij attach {session_name})")
        else:
            print(f"{LOG_PREFIX}   → FAILED to spawn for {linear_id}", file=sys.stderr)

    print(f"\n{LOG_PREFIX} Spawned {len(spawned)}/{len(priorities)} planning sessions.")
    if skipped:
        print(f"{LOG_PREFIX} Skipped {len(skipped)} due to session cap ({MAX_CONCURRENT_SESSIONS}): {', '.join(skipped)}")
        print(f"{LOG_PREFIX} Use /next-task or sessions.py spawn-chat to pick these up later.")
    if spawned:
        print(f"{LOG_PREFIX} Web UI: http://localhost:8082")
        for linear_id, name in spawned:
            print(f"{LOG_PREFIX}   zellij attach {name}")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    override_date = os.environ.get("MEETING_DATE", "")
    if override_date:
        yesterday = override_date
    else:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    if not args:
        print(f"Usage: {sys.argv[0]} <dry-run|run-meeting|auto-confirm|spawn-planning>", file=sys.stderr)
        sys.exit(1)

    command = args[0]
    if command == "dry-run":
        cmd_dry_run(yesterday)
    elif command == "run-meeting":
        cmd_run_meeting(yesterday)
    elif command == "auto-confirm":
        cmd_auto_confirm()
    elif command == "spawn-planning":
        cmd_spawn_planning()
    else:
        print(f"{LOG_PREFIX} Unknown command: {command}", file=sys.stderr)
        print(f"Usage: {sys.argv[0]} <dry-run|run-meeting|auto-confirm|spawn-planning>", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
