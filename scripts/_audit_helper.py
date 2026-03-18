#!/usr/bin/env python3
"""
scripts/_audit_helper.py

Python helper for weekly-codebase-audit.sh.

Determines which files changed since the last audit, loads the prompt template,
substitutes placeholders, and runs opencode to perform the "top 5 improvements" audit.

Commands:
    run-audit    Run the codebase health audit

State file format (scripts/.audit-state.json):
{
  "last_audit_date": "2026-03-17",
  "last_audit_sha": "abc1234",
  "last_audit_summary": "1. Security: ...\n2. Performance: ...",
  "last_session_url": "https://opencode.ai/s/..."
}

Environment variables (set by weekly-codebase-audit.sh):
    FORCE               — "true" to ignore last audit SHA (analyse all recent changes)
    DRY_RUN             — "true" to skip opencode, just print prompt
    PROJECT_ROOT        — absolute path to repo root
    TODAY_DATE          — current date as YYYY-MM-DD
    AUDIT_STATE_FILE    — absolute path to scripts/.audit-state.json
    PROMPT_TEMPLATE_PATH — absolute path to scripts/prompts/codebase-audit.md

Not intended to be called directly by users; use weekly-codebase-audit.sh instead.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state(state_file: str) -> dict:
    """Load audit state file, returning empty state if missing or corrupt."""
    empty: dict = {
        "last_audit_date": None,
        "last_audit_sha": None,
        "last_audit_summary": "N/A (first audit)",
        "last_session_url": None,
    }
    if not os.path.isfile(state_file):
        return empty
    try:
        with open(state_file) as f:
            data = json.load(f)
        # Ensure all expected keys are present
        for k, v in empty.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        print(f"[audit] WARNING: could not load state file: {e} — starting fresh.", file=sys.stderr)
        return empty


def _save_state(state_file: str, data: dict) -> None:
    """Save audit state atomically."""
    tmp_path = state_file + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, state_file)
    print(f"[audit] State file updated: {state_file}")


def _get_current_sha(project_root: str) -> str:
    """Return the current HEAD short SHA."""
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get_recent_git_log(project_root: str) -> str:
    """Return the last 2 weeks of commits as a compact oneline log."""
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "log", "--oneline", "--since=14 days ago"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() or "(no commits in the last 14 days)"
    except Exception as e:
        print(f"[audit] WARNING: git log failed: {e}", file=sys.stderr)
        return "(could not retrieve git log)"


def run_audit() -> None:
    """Main entry point: build prompt from recent git log and run opencode audit."""
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = os.environ.get("PROJECT_ROOT", "")
    today_date = os.environ.get("TODAY_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    state_file = os.environ.get("AUDIT_STATE_FILE", "")
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE_PATH", "")

    if not project_root:
        print("[audit] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)

    if not state_file:
        print("[audit] ERROR: AUDIT_STATE_FILE not set.", file=sys.stderr)
        sys.exit(1)

    # Load state
    state = _load_state(state_file)
    last_date = state.get("last_audit_date") or "first run"
    last_summary = state.get("last_audit_summary") or "N/A (first audit)"

    current_sha = _get_current_sha(project_root)
    git_log = _get_recent_git_log(project_root)

    print(f"[audit] Running codebase health audit (HEAD {current_sha}, last audit: {last_date})")

    # Load prompt template
    if not prompt_template_path or not os.path.isfile(prompt_template_path):
        print(f"[audit] ERROR: Prompt template not found at {prompt_template_path}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_template_path) as f:
        prompt_template = f.read()

    # Substitute placeholders
    prompt = (
        prompt_template
        .replace("{{DATE}}", today_date)
        .replace("{{GIT_SHA}}", current_sha)
        .replace("{{LAST_AUDIT_DATE}}", last_date)
        .replace("{{LAST_AUDIT_SUMMARY}}", last_summary)
        .replace("{{GIT_LOG}}", git_log)
    )

    if dry_run:
        print("[audit] DRY RUN — would run opencode with the following prompt:")
        print("-" * 60)
        print(prompt[:3000])
        print(f"... ({len(prompt)} chars total)")
        print("-" * 60)
        # Still update state so next run picks up from current SHA
        state["last_audit_date"] = today_date
        state["last_audit_sha"] = current_sha
        _save_state(state_file, state)
        return

    session_title = f"audit: codebase health {today_date}"
    cmd = [
        "opencode", "run",
        "--attach", "http://localhost:4096",
        "--agent", "plan",
        "--share",
        "--model", "anthropic/claude-sonnet-4-6",
        "--title", session_title,
        "--dir", project_root,
        prompt,
    ]

    print(f"[audit] Starting opencode audit session (HEAD {current_sha})...")

    # Cron runs with a minimal PATH that excludes ~/.npm-global/bin where opencode lives.
    run_env = os.environ.copy()
    run_env["PATH"] = "/home/superdev/.npm-global/bin:" + run_env.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minutes max
            env=run_env,
        )

        combined_output = result.stdout + result.stderr

        # Extract share URL
        share_url = None
        for line in combined_output.splitlines():
            for token in line.split():
                if "opncd.ai/share/" in token:
                    share_url = token.strip()
                    break
            if share_url:
                break

        if share_url:
            print(f"[audit] opencode session: {share_url}")
        else:
            print("[audit] WARNING: opencode ran but no share URL found in output.", file=sys.stderr)

        if result.returncode != 0:
            print(f"[audit] WARNING: opencode exited with code {result.returncode}", file=sys.stderr)

        # Extract a brief summary from the opencode output to store in state
        # (first 500 chars of stdout as a rough proxy for the findings summary)
        session_summary = result.stdout.strip()[:500] if result.stdout.strip() else "No summary available."

        # Update state
        state["last_audit_date"] = today_date
        state["last_audit_sha"] = current_sha
        state["last_audit_summary"] = session_summary
        state["last_session_url"] = share_url
        _save_state(state_file, state)

    except subprocess.TimeoutExpired:
        print("[audit] WARNING: opencode timed out after 30 minutes.", file=sys.stderr)
        # Still update state so we don't re-audit all the same files next time
        state["last_audit_date"] = today_date
        state["last_audit_sha"] = current_sha
        _save_state(state_file, state)
    except FileNotFoundError:
        print("[audit] ERROR: opencode binary not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[audit] ERROR: opencode failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <run-audit>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command == "run-audit":
        run_audit()
    else:
        print(f"[audit] Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
