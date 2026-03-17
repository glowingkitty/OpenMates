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
    - Issues are stored in Directus and exposed via GET /admin/debug/issues
    - The admin debug API requires ADMIN_API_KEY (Bearer token)
    - Git commit messages are expected to reference issue IDs (e.g. "fix: ... (issue abc123)")
    - opencode is invoked with --share to produce a shareable analysis session URL
    - The session URL is logged to stdout for the calling shell script

Env vars (read from .env if not in environment):
    ADMIN_API_KEY           — Bearer token for the admin debug API
    INTERNAL_API_URL        — base URL for the internal API (default: http://localhost:8000)
    INTERNAL_API_SHARED_TOKEN — auth token for internal email dispatch

Not intended to be called directly by users; use nightly-issues-check.sh instead.
"""

import json
import os
import subprocess
import sys
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Maximum number of issues to include in a single opencode session
MAX_ISSUES_IN_PROMPT = 15

# How far back to look for open issues (hours)
ISSUES_LOOKBACK_HOURS = 24

# API endpoint path for listing issues
ISSUES_API_PATH = "/admin/debug/issues"

# Default production API URL (used when running against prod)
DEFAULT_API_URL = "http://localhost:8000"


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
                env_vars[key.strip()] = value.strip()
    return env_vars


def _fetch_open_issues(api_url: str, admin_api_key: str) -> list[dict]:
    """
    Fetch open (unprocessed) issues from the admin debug API.

    Returns a list of issue dicts with at least: id, title, description, created_at.
    Filters to issues created in the last ISSUES_LOOKBACK_HOURS hours.
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=ISSUES_LOOKBACK_HOURS)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = api_url.rstrip("/") + ISSUES_API_PATH + f"?include_processed=false&limit=100"

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {admin_api_key}")
    req.add_header("Accept", "application/json")

    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
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

    admin_api_key = os.environ.get("ADMIN_API_KEY") or dot_env.get("ADMIN_API_KEY", "")
    if not admin_api_key:
        print("[issues-checker] ERROR: ADMIN_API_KEY not set — cannot fetch issues.", file=sys.stderr)
        sys.exit(1)

    api_url = os.environ.get("INTERNAL_API_URL") or dot_env.get("INTERNAL_API_URL", DEFAULT_API_URL)

    # Fetch open issues from the past 24h
    issues = _fetch_open_issues(api_url, admin_api_key)

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
    cmd = [
        "opencode", "run",
        "--share",
        "--model", "anthropic/claude-sonnet-4-6",
        "--title", session_title,
        "--dir", str(project_root),
        prompt,
    ]

    print(f"[issues-checker] Starting opencode investigation for {len(unresolved)} unresolved issue(s)...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute max
        )

        combined_output = result.stdout + result.stderr

        share_url = None
        for line in combined_output.splitlines():
            line_stripped = line.strip()
            if "opencode.ai/s/" in line_stripped:
                for token in line_stripped.split():
                    if "opencode.ai/s/" in token:
                        share_url = token.lstrip("Shared:").strip()
                        break
            if share_url:
                break

        if share_url:
            print(f"[issues-checker] opencode session: {share_url}")
            print(f"OPENCODE_URL:{share_url}")
        else:
            print(
                "[issues-checker] WARNING: opencode ran but no share URL found in output.",
                file=sys.stderr,
            )

        if result.returncode != 0:
            print(
                f"[issues-checker] WARNING: opencode exited with code {result.returncode}",
                file=sys.stderr,
            )

    except subprocess.TimeoutExpired:
        print("[issues-checker] WARNING: opencode investigation timed out after 15 minutes", file=sys.stderr)
    except FileNotFoundError:
        print("[issues-checker] ERROR: opencode binary not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[issues-checker] ERROR: opencode failed: {e}", file=sys.stderr)
        sys.exit(1)


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
