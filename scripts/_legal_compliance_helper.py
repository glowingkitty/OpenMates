#!/usr/bin/env python3
"""
scripts/_legal_compliance_helper.py

Python helper for legal-compliance-scan.sh.

Runs the twice-weekly legal & compliance scan via a Claude Code session:
  - Monday (full scan): re-evaluates the entire codebase against Tier 1–4
    regulatory frameworks, re-reads the gdpr-audit.md baseline, produces a
    fresh Top 10 recommendations list.
  - Thursday (delta scan): analyzes git commits since the last full scan,
    reasons about their legal implications, updates the Top 10.

The Claude session (driven by the `legal-compliance-auditor` agent defined
at .claude/agents/legal-compliance-auditor.md) writes its outputs directly:
  - logs/nightly-reports/legal-compliance.json   (picked up by daily meeting)
  - docs/architecture/compliance/top-10-recommendations.md
  - scripts/.legal-compliance-state.json
  - (optionally) appends to docs/architecture/compliance/gdpr-audit.md

This helper only:
  1. Loads state
  2. Gathers context (git log, acknowledgments, prior Top 10, baseline audit path)
  3. Substitutes placeholders into the appropriate prompt template
  4. Invokes run_claude_session()
  5. Writes a fallback nightly report if the Claude session failed before
     writing its own

Commands:
    run-full-scan    Run the Monday full scan
    run-delta-scan   Run the Thursday commit-delta scan
    dry-run-full     Print the full scan prompt and exit (no Claude invocation)
    dry-run-delta    Print the delta scan prompt and exit

Environment variables (set by legal-compliance-scan.sh):
    DRY_RUN               — "true" to skip claude, just print prompt
    PROJECT_ROOT          — absolute path to repo root
    TODAY_DATE            — current date as YYYY-MM-DD
    STATE_FILE            — absolute path to scripts/.legal-compliance-state.json
    FULL_PROMPT_PATH      — absolute path to scripts/prompts/legal-compliance-full.md
    DELTA_PROMPT_PATH     — absolute path to scripts/prompts/legal-compliance-delta.md
    ACKNOWLEDGMENTS_PATH  — absolute path to docs/architecture/compliance/acknowledgments.yml

Not intended to be called directly by users; use legal-compliance-scan.sh.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _claude_utils import run_claude_session  # noqa: E402
from _nightly_report import write_nightly_report  # noqa: E402


# Session timeouts (seconds)
FULL_SCAN_TIMEOUT = 2700   # 45 min
DELTA_SCAN_TIMEOUT = 1200  # 20 min

# Git log window for delta scan — look back a generous amount in case a full
# scan was missed; the Claude agent is told the last_full_scan_sha so it can
# scope more precisely within this window.
DELTA_LOG_MAX_COMMITS = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state(state_file: str) -> dict:
    """Load state file, returning empty state if missing or corrupt."""
    empty: dict = {
        "last_full_scan_date": None,
        "last_full_scan_sha": None,
        "last_delta_scan_date": None,
        "last_delta_scan_sha": None,
        "prior_top_10": [],
        "dismissed_counts": {},
    }
    if not os.path.isfile(state_file):
        return empty
    try:
        with open(state_file) as f:
            data = json.load(f)
        for k, v in empty.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        print(
            f"[legal-compliance] WARNING: could not load state file: {e} — starting fresh.",
            file=sys.stderr,
        )
        return empty


def _get_current_sha(project_root: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get_git_log_since(project_root: str, since_sha: str | None) -> str:
    """Return oneline git log since a SHA (or last 14 days if no SHA)."""
    try:
        if since_sha:
            cmd = [
                "git", "-C", project_root, "log", "--oneline",
                f"{since_sha}..HEAD", f"--max-count={DELTA_LOG_MAX_COMMITS}",
            ]
        else:
            cmd = [
                "git", "-C", project_root, "log", "--oneline",
                "--since=14 days ago", f"--max-count={DELTA_LOG_MAX_COMMITS}",
            ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip() or "(no commits in the window)"
    except Exception as e:
        print(f"[legal-compliance] WARNING: git log failed: {e}", file=sys.stderr)
        return "(could not retrieve git log)"


def _get_git_diff_summary(project_root: str, since_sha: str | None) -> str:
    """Return a compact per-file diff summary (file + lines added/removed)."""
    try:
        if since_sha:
            cmd = ["git", "-C", project_root, "diff", "--stat", f"{since_sha}..HEAD"]
        else:
            cmd = ["git", "-C", project_root, "diff", "--stat", "HEAD~20..HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = result.stdout.strip()
        # Cap to avoid prompt explosion
        lines = out.splitlines()
        if len(lines) > 300:
            lines = lines[:300] + [f"... ({len(lines) - 300} more lines truncated)"]
        return "\n".join(lines) or "(no file changes in the window)"
    except Exception as e:
        print(f"[legal-compliance] WARNING: git diff --stat failed: {e}", file=sys.stderr)
        return "(could not retrieve diff summary)"


def _load_acknowledgments(path: str) -> str:
    if not os.path.isfile(path):
        return "# (acknowledgments file not found — treat as empty)\n"
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        print(
            f"[legal-compliance] WARNING: could not read acknowledgments: {e}",
            file=sys.stderr,
        )
        return "# (acknowledgments file unreadable — treat as empty)\n"


def _prior_top_10_json(state: dict) -> str:
    prior = state.get("prior_top_10", [])
    try:
        return json.dumps(prior, indent=2)
    except Exception:
        return "[]"


def _build_prompt(scan_type: str, env: dict) -> str:
    """Build the final prompt string from the appropriate template."""
    project_root = env["PROJECT_ROOT"]
    today_date = env["TODAY_DATE"]
    state_file = env["STATE_FILE"]
    acknowledgments_path = env["ACKNOWLEDGMENTS_PATH"]

    if scan_type == "full":
        template_path = env["FULL_PROMPT_PATH"]
    elif scan_type == "delta":
        template_path = env["DELTA_PROMPT_PATH"]
    else:
        raise ValueError(f"Unknown scan_type: {scan_type}")

    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Prompt template not found: {template_path}")

    with open(template_path) as f:
        template = f.read()

    state = _load_state(state_file)
    current_sha = _get_current_sha(project_root)
    acknowledgments_yaml = _load_acknowledgments(acknowledgments_path)
    prior_top_10 = _prior_top_10_json(state)

    last_full_date = state.get("last_full_scan_date") or "(never)"
    last_full_sha = state.get("last_full_scan_sha") or "(none)"
    last_delta_date = state.get("last_delta_scan_date") or "(never)"
    last_delta_sha = state.get("last_delta_scan_sha") or "(none)"

    # Git log scope differs by scan type
    if scan_type == "full":
        git_log = _get_git_log_since(project_root, state.get("last_full_scan_sha"))
        git_diff_summary = ""  # not used in full scan template
    else:
        # Delta scan: since last full scan (not last delta — we want the full
        # window of changes since the last deep re-evaluation)
        git_log = _get_git_log_since(project_root, state.get("last_full_scan_sha"))
        git_diff_summary = _get_git_diff_summary(project_root, state.get("last_full_scan_sha"))

    prompt = (
        template
        .replace("{{DATE}}", today_date)
        .replace("{{GIT_SHA}}", current_sha)
        .replace("{{LAST_FULL_SCAN_DATE}}", last_full_date)
        .replace("{{LAST_FULL_SCAN_SHA}}", last_full_sha)
        .replace("{{LAST_DELTA_SCAN_DATE}}", last_delta_date)
        .replace("{{LAST_DELTA_SCAN_SHA}}", last_delta_sha)
        .replace("{{ACKNOWLEDGMENTS_YAML}}", acknowledgments_yaml)
        .replace("{{PRIOR_TOP_10_JSON}}", prior_top_10)
        .replace("{{GIT_LOG}}", git_log)
        .replace("{{GIT_DIFF_SUMMARY}}", git_diff_summary)
    )
    return prompt


def _get_env() -> dict:
    required = [
        "PROJECT_ROOT", "TODAY_DATE", "STATE_FILE",
        "FULL_PROMPT_PATH", "DELTA_PROMPT_PATH", "ACKNOWLEDGMENTS_PATH",
    ]
    env = {}
    missing = []
    for key in required:
        val = os.environ.get(key, "")
        if not val:
            missing.append(key)
        env[key] = val
    if missing:
        print(
            f"[legal-compliance] ERROR: missing env vars: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return env


def _run_scan(scan_type: str) -> None:
    env = _get_env()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    prompt = _build_prompt(scan_type, env)

    if dry_run:
        print(f"[legal-compliance] DRY RUN ({scan_type}) — prompt follows:")
        print("-" * 60)
        print(prompt[:4000])
        print(f"... ({len(prompt)} chars total)")
        print("-" * 60)
        return

    current_sha = _get_current_sha(env["PROJECT_ROOT"])
    session_title = f"legal-compliance: {scan_type} scan {env['TODAY_DATE']}"
    timeout = FULL_SCAN_TIMEOUT if scan_type == "full" else DELTA_SCAN_TIMEOUT

    print(
        f"[legal-compliance] Starting {scan_type} scan "
        f"(HEAD {current_sha}, timeout {timeout}s)..."
    )

    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=env["PROJECT_ROOT"],
        log_prefix="[legal-compliance]",
        agent=None,  # build mode — agent needs Write/Edit to produce output files
        timeout=timeout,
        job_type="legal-compliance",
        context_summary=f"{scan_type} scan at HEAD {current_sha}",
        linear_task=False,
        kill_on_exit=True,
    )

    # If the Claude session failed before writing its own nightly report,
    # write a fallback error report so the daily meeting notices the failure.
    report_path = (
        Path(env["PROJECT_ROOT"])
        / "logs" / "nightly-reports" / "legal-compliance.json"
    )
    if returncode != 0 or not report_path.is_file():
        write_nightly_report(
            job="legal-compliance",
            status="error",
            summary=(
                f"Legal compliance {scan_type} scan FAILED "
                f"(exit {returncode}). Session: {session_id or 'N/A'}."
            ),
            details={
                "scan_type": scan_type,
                "head_sha": current_sha,
                "session_id": session_id,
                "exit_code": returncode,
                "error": "Claude session did not complete or did not write its own report.",
            },
        )

    if returncode != 0:
        sys.exit(returncode)

    print(
        f"[legal-compliance] {scan_type} scan complete. "
        f"Session: {session_id or 'N/A'}"
    )


def run_full_scan() -> None:
    _run_scan("full")


def run_delta_scan() -> None:
    _run_scan("delta")


def dry_run_full() -> None:
    os.environ["DRY_RUN"] = "true"
    _run_scan("full")


def dry_run_delta() -> None:
    os.environ["DRY_RUN"] = "true"
    _run_scan("delta")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            f"Usage: {sys.argv[0]} <run-full-scan|run-delta-scan|dry-run-full|dry-run-delta>",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]
    if command == "run-full-scan":
        run_full_scan()
    elif command == "run-delta-scan":
        run_delta_scan()
    elif command == "dry-run-full":
        dry_run_full()
    elif command == "dry-run-delta":
        dry_run_delta()
    else:
        print(f"[legal-compliance] Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
