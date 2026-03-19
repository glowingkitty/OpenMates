#!/usr/bin/env python3
"""
scripts/_issues_checker.py

Nightly open issue checker — called by nightly-issues-check.sh.

Fetches open user-reported issues from the admin debug API, checks whether each
issue has been addressed in recent git commits (by searching commit messages for
the issue ID), then starts an opencode analysis session for any unresolved issues.

Commands:
    check-issues    Fetch open issues, check git history, dispatch opencode if needed

Architecture:
    - Issues are stored in Directus and exposed via GET /v1/admin/debug/issues
    - The admin debug API requires a user API key with admin privileges (Bearer token)
    - Key is read from SECRET__ADMIN__DEBUG_CLI__API_KEY — same var used by
      triage_issues.py and imported into Vault by vault-setup
    - Git commit messages are expected to reference issue IDs (e.g. "fix: ... (issue abc123)")
    - opencode is invoked with --share to produce a shareable analysis session URL
    - The session URL is logged to stdout for the calling shell script

Env vars (read from .env automatically — sourced by nightly-issues-check.sh):
    SECRET__ADMIN__DEBUG_CLI__API_KEY — admin user API key (required)
    INTERNAL_API_URL                  — base URL for the API (default: http://localhost:8000)

Not intended to be called directly by users; use nightly-issues-check.sh instead.
"""

import json
import os
import subprocess

from _opencode_utils import run_opencode_session
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Maximum number of issues to include in a single opencode session
MAX_ISSUES_IN_PROMPT = 15

# How far back to look for open issues (hours)
ISSUES_LOOKBACK_HOURS = 24

# Full URL for the issues endpoint — matches debug_utils.PROD_API_URL convention.
# The admin debug API key is only registered on the production Directus instance.
ISSUES_API_URL = "https://api.openmates.org/v1/admin/debug/issues"

# Env var name — same key used by triage_issues.py and vault-setup
# (.env → vault-setup imports it as kv/data/providers/admin debug_cli__api_key)
ADMIN_KEY_ENV_VAR = "SECRET__ADMIN__DEBUG_CLI__API_KEY"


def _read_env_file(project_root: str) -> dict:
    """Read key=value pairs from .env at project root. Does not modify os.environ."""
    env_path = os.path.join(project_root, ".env")
    env_vars: dict = {}
    if not os.path.isfile(env_path):
        return env_vars
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip surrounding quotes that .env files sometimes include
                env_vars[key.strip()] = value.strip().strip('"').strip("'")
    return env_vars


def _fetch_open_issues(admin_api_key: str) -> list[dict]:
    """
    Fetch open (unprocessed) issues from the admin debug API.

    Returns a list of issue dicts with at least: id, title, description, created_at.
    Filters to issues created in the last ISSUES_LOOKBACK_HOURS hours.
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=ISSUES_LOOKBACK_HOURS)

    url = ISSUES_API_URL + "?include_processed=false&limit=100"

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {admin_api_key}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(
            f"[issues-checker] ERROR fetching issues: HTTP {e.code} — {err_body[:300]}",
            file=sys.stderr,
        )
        return []
    except Exception as e:
        print(f"[issues-checker] ERROR fetching issues: {e}", file=sys.stderr)
        return []

    issues = data.get("issues", [])

    # Filter to issues created within the lookback window
    recent_issues = []
    for issue in issues:
        created_at_str = issue.get("created_at", "")
        if not created_at_str:
            # Include if we can't parse the date (conservative)
            recent_issues.append(issue)
            continue
        try:
            # Handle both "2026-03-17T04:00:00.000Z" and "2026-03-17T04:00:00Z"
            created_at_str_clean = created_at_str.replace("Z", "+00:00")
            created_at = datetime.fromisoformat(created_at_str_clean)
            if created_at >= since_dt:
                recent_issues.append(issue)
        except ValueError:
            recent_issues.append(issue)

    print(f"[issues-checker] Found {len(recent_issues)} open issue(s) from the past {ISSUES_LOOKBACK_HOURS}h")
    return recent_issues


def _check_issue_in_git(issue_id: str, project_root: str) -> str | None:
    """
    Check whether a git commit references the given issue ID in its message.

    Searches all commits (not limited by date) since the issue could have been
    fixed any time after it was reported.

    Returns the commit SHA if found, or None.
    """
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "log", "--all", "--oneline", f"--grep={issue_id}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if output:
            # Return the first matching commit SHA
            first_line = output.splitlines()[0]
            return first_line.split()[0]
        return None
    except Exception as e:
        print(f"[issues-checker] WARNING: git log search failed for issue {issue_id}: {e}", file=sys.stderr)
        return None


def check_issues() -> None:
    """
    Main command: fetch open issues, filter unresolved, start opencode session if needed.
    """
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent

    dot_env = _read_env_file(str(project_root))

    admin_api_key = os.environ.get(ADMIN_KEY_ENV_VAR) or dot_env.get(ADMIN_KEY_ENV_VAR, "")
    if not admin_api_key:
        print(
            f"[issues-checker] ERROR: {ADMIN_KEY_ENV_VAR} not set — cannot fetch issues.\n"
            f"  → Add it to .env as: {ADMIN_KEY_ENV_VAR}=sk-api-xxxxx\n"
            "  → Generate the API key: admin user → Settings → API Keys",
            file=sys.stderr,
        )
        sys.exit(1)

    # Fetch open issues from the past 24h
    issues = _fetch_open_issues(admin_api_key)

    if not issues:
        print("[issues-checker] No open issues in the past 24h — nothing to do.")
        return

    # Check each issue against git history
    unresolved = []
    resolved_count = 0

    for issue in issues:
        issue_id = issue.get("id", "")
        if not issue_id:
            unresolved.append(issue)
            continue

        commit_sha = _check_issue_in_git(issue_id, str(project_root))
        if commit_sha:
            print(f"[issues-checker] Issue {issue_id} resolved via commit {commit_sha} — skipping.")
            resolved_count += 1
        else:
            print(f"[issues-checker] Issue {issue_id} NOT found in git history — flagging as unresolved.")
            unresolved.append(issue)

    print(
        f"[issues-checker] Summary: {len(issues)} total, "
        f"{resolved_count} resolved in git, {len(unresolved)} unresolved."
    )

    if not unresolved:
        print("[issues-checker] All open issues have been addressed in git commits — done.")
        return

    # Cap to avoid prompt size explosion
    issues_for_prompt = unresolved[:MAX_ISSUES_IN_PROMPT]

    # Load and populate the prompt template
    prompt_template_path = script_dir / "prompts" / "issues-investigation.md"
    if not prompt_template_path.is_file():
        print(
            f"[issues-checker] ERROR: prompt template not found at {prompt_template_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    prompt_template = prompt_template_path.read_text()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get recent git log for context
    try:
        git_log_result = subprocess.run(
            ["git", "-C", str(project_root), "log", "--oneline", "--since=7 days ago"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        git_log = git_log_result.stdout.strip() or "(no commits in the last 7 days)"
    except Exception:
        git_log = "(could not retrieve git log)"

    # Build compact issue list for the prompt
    compact_issues = []
    for issue in issues_for_prompt:
        compact_issues.append({
            "id": issue.get("id", ""),
            "title": issue.get("title", ""),
            "description": (issue.get("description", "") or "")[:500],
            "created_at": issue.get("created_at", ""),
        })

    issues_json = json.dumps(compact_issues, indent=2)

    prompt = (
        prompt_template
        .replace("{{DATE}}", date_str)
        .replace("{{ISSUE_COUNT}}", str(len(unresolved)))
        .replace("{{ISSUES_JSON}}", issues_json)
        .replace("{{GIT_LOG}}", git_log)
    )

    session_title = f"issues-investigation {date_str}"
    print(f"[issues-checker] Starting opencode investigation for {len(unresolved)} unresolved issue(s)...")

    returncode, share_url = run_opencode_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(project_root),
        log_prefix="[issues-checker]",
        agent="plan",
        timeout=900,
    )

    if share_url:
        print(f"OPENCODE_URL:{share_url}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <check-issues>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command == "check-issues":
        check_issues()
    else:
        print(f"[issues-checker] Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
