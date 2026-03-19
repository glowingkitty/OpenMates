#!/usr/bin/env python3
"""
scripts/_deploy_checker_helper.py

Python helper for check-deploy-status.sh.

Checks every 2 minutes (via cron) whether a git commit was made in the last
5 minutes on the local dev branch. If so, polls the Vercel API for the latest
deployment status. If the deployment has ERRORed and hasn't been dispatched yet,
runs an opencode build-mode session to investigate and fix the failure.

Architecture context: docs/architecture/cronjobs.md
Tests: None (cron helper, not production code)

State file: scripts/.deploy-checker-state.json
{
  "last_checked_at": "2026-03-19T10:00:00Z",
  "dispatched_deploy_ids": ["dpl_abc123", "dpl_def456"]
}

Called by check-deploy-status.sh:
    python3 scripts/_deploy_checker_helper.py run

Environment variables (sourced from .env by the shell script):
    VERCEL_TOKEN   — required; Vercel personal/team access token
    DRY_RUN        — "true" to skip actual opencode invocation
"""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

# Add backend/scripts to sys.path so we can import debug_vercel helpers
_BACKEND_SCRIPTS = _PROJECT_ROOT / "backend" / "scripts"
if str(_BACKEND_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SCRIPTS))

# Add scripts/ itself to sys.path for _opencode_utils
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import httpx  # noqa: E402
from _opencode_utils import run_opencode_session  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────────

STATE_FILE = _SCRIPT_DIR / ".deploy-checker-state.json"
PROMPT_TEMPLATE = _SCRIPT_DIR / "prompts" / "vercel-build-fix.md"
LOG_PREFIX = "[deploy-checker]"

# How far back to look for local commits (seconds)
COMMIT_LOOKBACK_SECONDS = 5 * 60  # 5 minutes

# Vercel branch to watch
TARGET_BRANCH = "dev"

VERCEL_API = "https://api.vercel.com"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}", flush=True)


def _load_state() -> dict:
    empty: dict = {
        "last_checked_at": None,
        "dispatched_deploy_ids": [],
    }
    if not STATE_FILE.exists():
        return empty
    try:
        data = json.loads(STATE_FILE.read_text())
        for k, v in empty.items():
            data.setdefault(k, v)
        return data
    except Exception as exc:
        _log(f"WARNING: could not load state file ({exc}) — starting fresh.")
        return empty


def _save_state(state: dict) -> None:
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, str(STATE_FILE))
    _log(f"State saved: {STATE_FILE}")


def _load_env_file() -> dict:
    """Parse KEY=VALUE pairs from .env (no python-dotenv dependency)."""
    env_path = _PROJECT_ROOT / ".env"
    result: dict = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def _get_vercel_token() -> str:
    token = os.environ.get("VERCEL_TOKEN", "")
    if token:
        return token
    env_vars = _load_env_file()
    token = env_vars.get("VERCEL_TOKEN", "")
    if not token:
        _log("ERROR: VERCEL_TOKEN not found in environment or .env file.")
        sys.exit(1)
    return token


def _get_vercel_project_config() -> dict:
    """Read orgId and projectId from frontend/apps/web_app/.vercel/project.json."""
    project_json = _PROJECT_ROOT / "frontend" / "apps" / "web_app" / ".vercel" / "project.json"
    if not project_json.exists():
        _log(f"ERROR: Vercel project.json not found at {project_json}")
        sys.exit(1)
    try:
        return json.loads(project_json.read_text())
    except Exception as exc:
        _log(f"ERROR: could not parse Vercel project.json: {exc}")
        sys.exit(1)


def _api_get(path: str, token: str, params: dict | None = None) -> dict | list:
    resp = httpx.get(
        f"{VERCEL_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_build_log_text(token: str, deploy_id: str, team_id: str, max_events: int = 5000) -> str:
    """
    Fetch Vercel build log events for a deployment and return them as a single
    text block (errors and warnings only — same filter as debug.py vercel).
    Paginates past the ~467-event per-page cap.
    """
    all_events: list[dict] = []
    since_ts: int | None = None
    page_cap = 450

    for _ in range(20):
        params: dict = {"builds": 1, "limit": -1, "teamId": team_id}
        if since_ts is not None:
            params["since"] = since_ts

        data = _api_get(f"/v3/deployments/{deploy_id}/events", token, params)
        if not isinstance(data, list) or not data:
            break
        all_events.extend(data)
        if len(data) < page_cap:
            break
        last_created = data[-1].get("created")
        if last_created is None or last_created == since_ts:
            break
        since_ts = last_created
        if len(all_events) >= max_events:
            break

    all_events = all_events[:max_events]

    # Filter to errors and warnings (same logic as debug_vercel.py)
    _error_prefixes = (
        "error", "err ", "failed", "failure", "exception", "traceback",
        "exit code", "elifecycle", "command failed", " error:", "typeerror",
        "syntaxerror", "referenceerror", "cannot find", "module not found",
        "could not resolve", "✗", "✘", "✖", "404",
    )
    _warn_prefixes = ("warn", "⚠", "warning", "deprecated")

    lines: list[str] = []
    for ev in all_events:
        text = ev.get("text", "").rstrip()
        if not text:
            continue
        low = text.lower()
        is_error = any(low.startswith(p) or f" {p}" in low for p in _error_prefixes)
        is_warn = any(low.startswith(p) or f" {p}" in low for p in _warn_prefixes)
        if is_error or is_warn:
            lines.append(text)

    if not lines:
        lines.append("(No errors or warnings found in build log — check full log manually.)")

    return "\n".join(lines)


# ── Core checks ────────────────────────────────────────────────────────────────

def _has_recent_local_commit() -> bool:
    """Return True if there is at least one local git commit in the last 5 minutes."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=COMMIT_LOOKBACK_SECONDS)
    # git log with --after uses local repo history (no fetch needed)
    since_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = subprocess.run(
        ["git", "-C", str(_PROJECT_ROOT), "log", f"--after={since_str}", "--oneline", "-1"],
        capture_output=True,
        text=True,
    )
    has_commit = bool(result.stdout.strip())
    if has_commit:
        _log(f"Recent local commit found (since {since_str}): {result.stdout.strip()[:80]}")
    else:
        _log(f"No local commits in the last {COMMIT_LOOKBACK_SECONDS // 60} minutes — skipping.")
    return has_commit


def _get_latest_dev_deployment(token: str, team_id: str, project_id: str) -> dict | None:
    """
    Return the most recent Vercel deployment for the TARGET_BRANCH, or None.
    We fetch the last 10 and find the first one matching the branch.
    """
    try:
        data = _api_get(
            "/v6/deployments",
            token,
            params={"teamId": team_id, "projectId": project_id, "limit": 10},
        )
    except httpx.HTTPStatusError as exc:
        _log(f"ERROR: Vercel API returned {exc.response.status_code}: {exc.response.text[:200]}")
        return None
    except httpx.RequestError as exc:
        _log(f"ERROR: Network error querying Vercel API: {exc}")
        return None

    deployments = data.get("deployments", []) if isinstance(data, dict) else []
    for dep in deployments:
        branch = dep.get("meta", {}).get("githubCommitRef", "")
        if branch == TARGET_BRANCH:
            return dep
    return None


def _build_prompt(dep: dict, build_log: str) -> str:
    """Fill in the prompt template with deployment context."""
    template = PROMPT_TEMPLATE.read_text()

    meta = dep.get("meta", {})
    deploy_id = dep.get("uid", dep.get("id", "unknown"))
    deploy_url = dep.get("url", "")
    git_sha = meta.get("githubCommitSha", "")[:9]
    commit_msg = meta.get("githubCommitMessage", "(no message)").splitlines()[0][:100]
    commit_author = meta.get("githubCommitAuthorName", meta.get("githubCommitAuthorLogin", "unknown"))

    return (
        template
        .replace("{{DATE}}", _now_iso())
        .replace("{{DEPLOY_ID}}", deploy_id)
        .replace("{{DEPLOY_URL}}", f"https://{deploy_url}" if deploy_url else deploy_id)
        .replace("{{GIT_SHA}}", git_sha)
        .replace("{{GIT_BRANCH}}", TARGET_BRANCH)
        .replace("{{COMMIT_MESSAGE}}", commit_msg)
        .replace("{{COMMIT_AUTHOR}}", commit_author)
        .replace("{{BUILD_LOG}}", build_log)
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def run() -> None:
    _log(f"Starting deploy checker at {_now_iso()}")

    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if dry_run:
        _log("DRY RUN mode — opencode will not be invoked.")

    # Step 1: Any local commit in the last 5 minutes? (skip if --force)
    force = os.environ.get("DEPLOY_CHECKER_FORCE", "false").lower() == "true"
    if force:
        _log("--force: bypassing recent-commit guard.")
    elif not _has_recent_local_commit():
        return

    # Step 2: Query Vercel for the latest dev deployment
    token = _get_vercel_token()
    cfg = _get_vercel_project_config()
    team_id = cfg.get("orgId", "")
    project_id = cfg.get("projectId", "")

    if not team_id or not project_id:
        _log("ERROR: Could not read team/project IDs from .vercel/project.json")
        sys.exit(1)

    dep = _get_latest_dev_deployment(token, team_id, project_id)
    if dep is None:
        _log(f"No deployments found for branch '{TARGET_BRANCH}' — skipping.")
        return

    deploy_id = dep.get("uid", dep.get("id", ""))
    state_val = dep.get("state", dep.get("readyState", "?"))
    meta = dep.get("meta", {})
    git_sha = meta.get("githubCommitSha", "")[:9]
    commit_msg = meta.get("githubCommitMessage", "").splitlines()[0][:80]

    _log(f"Latest {TARGET_BRANCH} deployment: {deploy_id} | status={state_val} | sha={git_sha} | msg={commit_msg!r}")

    # Step 3: Is it a failure we haven't dispatched yet?
    if state_val not in ("ERROR", "CANCELED"):
        _log(f"Deployment status is '{state_val}' — nothing to do (only act on ERROR/CANCELED).")
        return

    state = _load_state()
    state["last_checked_at"] = _now_iso()

    if deploy_id in state["dispatched_deploy_ids"]:
        _log(f"Deployment {deploy_id} already dispatched — skipping to avoid duplicate.")
        _save_state(state)
        return

    # Step 4: Fetch the build log and build the opencode prompt
    _log(f"Fetching build log for {deploy_id}...")
    build_log = _fetch_build_log_text(token, deploy_id, team_id)
    _log(f"Build log: {len(build_log)} chars, {build_log.count(chr(10))+1} lines")

    prompt = _build_prompt(dep, build_log)

    session_title = f"fix: Vercel build failure {deploy_id[:16]} ({git_sha})"

    _log(f"Dispatching opencode build session: {session_title!r}")

    # Step 5: Mark as dispatched BEFORE running opencode (so a timeout doesn't cause a re-dispatch)
    state["dispatched_deploy_ids"].append(deploy_id)
    # Keep the list bounded — only the last 50 deploy IDs
    state["dispatched_deploy_ids"] = state["dispatched_deploy_ids"][-50:]
    _save_state(state)

    if dry_run:
        _log("DRY RUN: would dispatch opencode with the following prompt (truncated to 500 chars):")
        print(prompt[:500])
        return

    # Step 6: Invoke opencode in build mode
    returncode, share_url = run_opencode_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(_PROJECT_ROOT),
        log_prefix=LOG_PREFIX,
        agent=None,   # None = build mode (default)
        timeout=1800, # 30 minutes
    )

    if returncode == 0:
        _log("opencode session completed successfully.")
    else:
        _log(f"WARNING: opencode exited with code {returncode}.")

    if share_url:
        _log(f"Session share URL: {share_url}")
    else:
        _log("No share URL found in opencode output.")

    _log(f"Deploy checker complete at {_now_iso()}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "run":
        print(f"Usage: {sys.argv[0]} run [--dry-run]")
        sys.exit(1)
    run()
