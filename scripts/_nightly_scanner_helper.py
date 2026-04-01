#!/usr/bin/env python3
"""
scripts/_nightly_scanner_helper.py

Shared Python helper for nightly-quick-wins.sh and nightly-pattern-consistency.sh.

Manages scope selection (recent changes + rotating sector), previous findings
carry-forward, prompt template rendering, and Claude session execution.

Both scanners share the same lifecycle:
  1. Determine scope (7-day changes + rotating sector based on day of week)
  2. Load previous findings from output JSON (carry forward unresolved items)
  3. Render prompt template with scope and findings context
  4. Run Claude in plan mode (Haiku) with Write tool access for incremental output
  5. Write nightly report summary

Commands:
    run-quick-wins          Run the quick-wins scanner
    run-pattern-consistency  Run the pattern-consistency scanner

Environment variables (set by shell wrappers):
    DRY_RUN             — "true" to skip Claude, print prompt only
    PROJECT_ROOT        — absolute path to repo root
    TODAY_DATE          — current date as YYYY-MM-DD
    PROMPT_TEMPLATE_PATH — path to the relevant prompt template
    SCAN_TYPE           — "quick-wins" or "pattern-consistency"

Not intended to be called directly; use nightly-quick-wins.sh or
nightly-pattern-consistency.sh.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Append scripts/ to path so we can import sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _claude_utils import run_claude_session
from _nightly_report import write_nightly_report


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Haiku model for cost efficiency
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Soft limit: 25 minutes. Hard kill: 30 minutes (1800s).
SOFT_LIMIT_MINUTES = 25
HARD_KILL_SECONDS = 1800

# Rotating sector schedule (day of week → sector name + glob paths)
# 0=Monday, 1=Tuesday, ..., 4=Friday, 5=Saturday, 6=Sunday
SECTOR_SCHEDULE = {
    0: {
        "name": "Frontend components",
        "paths": [
            "frontend/packages/ui/src/components/",
            "frontend/apps/web_app/src/lib/components/",
        ],
    },
    1: {
        "name": "Backend services",
        "paths": [
            "backend/core/api/app/services/",
            "backend/core/api/app/routes/",
        ],
    },
    2: {
        "name": "Embeds",
        "paths": [
            "frontend/packages/ui/src/components/embeds/",
            "backend/core/api/app/services/embed_service.py",
            "backend/shared/python_schemas/embed_schemas.py",
        ],
    },
    3: {
        "name": "Stores and frontend services",
        "paths": [
            "frontend/packages/ui/src/stores/",
            "frontend/packages/ui/src/services/",
        ],
    },
    4: {
        "name": "Full scan (Friday)",
        "paths": [
            "frontend/",
            "backend/",
        ],
    },
    # Weekend: repeat Monday/Tuesday sectors (unlikely to run, but safe default)
    5: {
        "name": "Frontend components (weekend)",
        "paths": [
            "frontend/packages/ui/src/components/",
        ],
    },
    6: {
        "name": "Backend services (weekend)",
        "paths": [
            "backend/core/api/app/services/",
        ],
    },
}

# Output file paths (relative to project root)
OUTPUT_FILES = {
    "quick-wins": "logs/nightly-reports/quick-wins.json",
    "pattern-consistency": "logs/nightly-reports/pattern-inconsistencies.json",
}

# Nightly report job names (for write_nightly_report)
REPORT_JOB_NAMES = {
    "quick-wins": "quick-wins",
    "pattern-consistency": "pattern-consistency",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_current_sha(project_root: str) -> str:
    """Get the short HEAD SHA."""
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get_recent_changes(project_root: str, days: int = 7) -> str:
    """Get files changed in the last N days."""
    try:
        result = subprocess.run(
            [
                "git", "-C", project_root, "log",
                "--name-only", "--pretty=format:",
                f"--since={days} days ago",
            ],
            capture_output=True, text=True, timeout=15,
        )
        files = sorted(set(
            f.strip() for f in result.stdout.strip().splitlines() if f.strip()
        ))
        if not files:
            return "(no files changed in the last 7 days)"
        return "\n".join(files)
    except Exception as e:
        print(f"[scanner] WARNING: git log failed: {e}", file=sys.stderr)
        return "(could not retrieve recent changes)"


def _get_day_of_week() -> int:
    """Return day of week as integer (0=Monday, 6=Sunday)."""
    return datetime.now(timezone.utc).weekday()


def _get_sector(day: int) -> dict:
    """Return the rotating sector for a given day of week."""
    return SECTOR_SCHEDULE.get(day, SECTOR_SCHEDULE[0])


def _load_previous_findings(project_root: str, scan_type: str) -> str:
    """Load previous findings from the output JSON file for carry-forward."""
    output_path = Path(project_root) / OUTPUT_FILES[scan_type]
    if not output_path.is_file():
        return "(none — first run)"

    try:
        data = json.loads(output_path.read_text())
        items = data.get("details", {}).get("items", [])
        if not items:
            return "(none — previous run found no issues)"

        lines = []
        for item in items:
            title = item.get("title", "Untitled")
            category = item.get("category", "unknown")
            files = ", ".join(item.get("files", []))
            days = item.get("days_pending", 0)
            score = item.get("priority_score", 0)
            lines.append(
                f"- [{category}] {title} (files: {files}, "
                f"priority: {score}, pending: {days}d)"
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"[scanner] WARNING: could not load previous findings: {e}", file=sys.stderr)
        return "(could not parse previous findings)"


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_scanner(scan_type: str) -> None:
    """Run either the quick-wins or pattern-consistency scanner.

    Args:
        scan_type: One of "quick-wins" or "pattern-consistency".
    """
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = os.environ.get("PROJECT_ROOT", "")
    today_date = os.environ.get("TODAY_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE_PATH", "")

    if not project_root:
        print(f"[{scan_type}] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)

    log_prefix = f"[{scan_type}]"
    current_sha = _get_current_sha(project_root)
    day_of_week = _get_day_of_week()
    sector = _get_sector(day_of_week)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    print(f"{log_prefix} HEAD: {current_sha}")
    print(f"{log_prefix} Day: {day_names[day_of_week]} → sector: {sector['name']}")

    # Gather scope
    recent_changes = _get_recent_changes(project_root)
    sector_paths = "\n".join(sector["paths"])
    previous_findings = _load_previous_findings(project_root, scan_type)

    # Load prompt template
    if not prompt_template_path or not os.path.isfile(prompt_template_path):
        print(f"{log_prefix} ERROR: Prompt template not found: {prompt_template_path}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_template_path) as f:
        prompt_template = f.read()

    # Current time for the JSON output
    now_time = datetime.now(timezone.utc).strftime("%H:%M:%S")

    # Render prompt
    prompt = (
        prompt_template
        .replace("{{DATE}}", today_date)
        .replace("{{GIT_SHA}}", current_sha)
        .replace("{{DAY_OF_WEEK}}", day_names[day_of_week])
        .replace("{{RECENT_CHANGES}}", recent_changes)
        .replace("{{SECTOR_NAME}}", sector["name"])
        .replace("{{SECTOR_PATHS}}", sector_paths)
        .replace("{{PREVIOUS_FINDINGS}}", previous_findings)
        .replace("{{TIME}}", now_time)
    )

    if dry_run:
        print(f"{log_prefix} DRY RUN — would run Claude with the following prompt:")
        print("-" * 60)
        print(prompt[:3000])
        print(f"... ({len(prompt)} chars total)")
        print("-" * 60)
        return

    # Ensure output directory exists
    output_path = Path(project_root) / OUTPUT_FILES[scan_type]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    session_title = f"{scan_type}: {sector['name'].lower()} {today_date}"
    print(f"{log_prefix} Starting Claude {scan_type} session (Haiku, plan mode)...")

    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=project_root,
        log_prefix=log_prefix,
        agent="plan",
        timeout=HARD_KILL_SECONDS,
        allowed_tools=["Write"],
        job_type=scan_type,
        model=HAIKU_MODEL,
        kill_on_exit=True,
    )

    # Check if Claude wrote the output file (incremental writes)
    items_found = 0
    if output_path.is_file():
        try:
            data = json.loads(output_path.read_text())
            items_found = len(data.get("details", {}).get("items", []))
        except Exception:
            pass

    timed_out = returncode == 124

    # Write nightly report summary (consumed by daily meeting auto-discovery)
    job_name = REPORT_JOB_NAMES[scan_type]
    write_nightly_report(
        job=job_name,
        status="ok" if (returncode == 0 or timed_out) else "error",
        summary=(
            f"{scan_type.replace('-', ' ').title()} scan completed "
            f"(HEAD {current_sha}, sector: {sector['name']}). "
            f"{items_found} item(s) found."
            f"{' Reached 30-min time limit.' if timed_out else ''}"
        ),
        details={
            "date": today_date,
            "head_sha": current_sha,
            "session_id": session_id,
            "sector_scanned": sector["name"],
            "items_found": items_found,
            "timed_out": timed_out,
        },
    )

    if returncode != 0 and not timed_out:
        print(f"{log_prefix} WARNING: session exited with code {returncode}", file=sys.stderr)
        sys.exit(returncode)

    if timed_out:
        print(f"{log_prefix} Session reached 30-minute time limit (hard kill).")

    print(f"{log_prefix} Scan complete. {items_found} item(s) found.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            f"Usage: {sys.argv[0]} <run-quick-wins|run-pattern-consistency>",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    if command == "run-quick-wins":
        run_scanner("quick-wins")
    elif command == "run-pattern-consistency":
        run_scanner("pattern-consistency")
    else:
        print(f"[scanner] Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
