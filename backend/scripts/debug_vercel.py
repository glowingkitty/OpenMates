#!/usr/bin/env python3
"""
Vercel deployment log inspector for debug.py.

Fetches build logs for the latest (or a specified) Vercel deployment of the
web app via the Vercel REST API. Works for ERROR deployments where the CLI
`vercel logs` command returns nothing.

Architecture context: See docs/claude/debugging.md
Tests: None (inspection script, not production code)

USAGE (via debug.py):
  debug.py vercel                  # latest deployment — errors/warnings only
  debug.py vercel --all            # latest deployment — full build log
  debug.py vercel --url <url|id>   # specific deployment
  debug.py vercel --n 3            # check last N deployments
  debug.py vercel --max-events 8000  # increase pagination limit (default: 5000)

USAGE (standalone, outside Docker):
  python3 backend/scripts/debug_vercel.py [options]

Reads VERCEL_TOKEN from environment or project root .env file.
Team/project IDs are read from frontend/apps/web_app/.vercel/project.json.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

# ── Path bootstrap ────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ── ANSI colours ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

def _ok(msg: str) -> str:   return _c(GREEN,  f"✓ {msg}")
def _warn(msg: str) -> str: return _c(YELLOW, f"⚠ {msg}")
def _err(msg: str) -> str:  return _c(RED,    f"✗ {msg}")
def _hdr(msg: str) -> str:  return f"\n{BOLD}{CYAN}{'─'*4} {msg} {'─'*(50-len(msg))}{RESET}"


# ═════════════════════════════════════════════════════════════════════════════
#  Config helpers
# ═════════════════════════════════════════════════════════════════════════════

def _project_root() -> Path:
    """Walk up from script dir to find the repo root (contains .env)."""
    here = _SCRIPT_DIR
    for _ in range(6):
        if (here / ".env").exists():
            return here
        here = here.parent
    return _SCRIPT_DIR


def _load_env_file(root: Path) -> dict:
    """Parse KEY=VALUE pairs from .env (no dependency on python-dotenv)."""
    env_path = root / ".env"
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


def _get_token() -> str:
    """Return VERCEL_TOKEN from environment or .env file."""
    token = os.environ.get("VERCEL_TOKEN", "")
    if token:
        return token
    root = _project_root()
    env_vars = _load_env_file(root)
    token = env_vars.get("VERCEL_TOKEN", "")
    if not token:
        print(_err("VERCEL_TOKEN not found in environment or .env file."), file=sys.stderr)
        print("  Set it in .env:  VERCEL_TOKEN=\"vcp_...\"", file=sys.stderr)
        sys.exit(1)
    return token


def _get_project_config() -> dict:
    """Read team_id and project_id from the web app's .vercel/project.json."""
    root = _project_root()
    project_json = root / "frontend" / "apps" / "web_app" / ".vercel" / "project.json"
    if not project_json.exists():
        return {}
    try:
        return json.loads(project_json.read_text())
    except Exception:
        return {}


# ═════════════════════════════════════════════════════════════════════════════
#  Vercel API helpers
# ═════════════════════════════════════════════════════════════════════════════

VERCEL_API = "https://api.vercel.com"


def _api_get(path: str, token: str, params: Optional[dict] = None) -> Any:
    """GET a Vercel REST API endpoint; raise on HTTP error."""
    resp = httpx.get(
        f"{VERCEL_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _list_deployments(token: str, team_id: str, project_id: str, limit: int = 10) -> list[dict]:
    """Return recent deployments for the project, newest first."""
    data = _api_get(
        "/v6/deployments",
        token,
        params={
            "teamId": team_id,
            "projectId": project_id,
            "limit": limit,
        },
    )
    return data.get("deployments", [])


def _fetch_build_logs(
    token: str,
    id_or_url: str,
    team_id: str,
    max_events: int = 5000,
) -> list[dict]:
    """
    Fetch all build log events for a deployment via the v3 events API.

    The Vercel events API caps responses at ~500 events per request.
    This function automatically paginates using the ``since`` parameter
    (timestamp of the last event) until no new events are returned or
    ``max_events`` is reached.

    Returns a list of event objects — each has at minimum:
      text (str), type (stdout|stderr|delimiter), created (int ms epoch)
    """
    all_events: list[dict] = []
    since_ts: Optional[int] = None
    page_cap = 450  # Conservative threshold — Vercel typically caps at ~467

    for _ in range(20):  # Safety cap: max 20 pagination rounds
        params: dict = {
            "builds": 1,
            "limit": -1,
            "teamId": team_id,
        }
        if since_ts is not None:
            params["since"] = since_ts

        data = _api_get(
            f"/v3/deployments/{id_or_url}/events",
            token,
            params=params,
        )

        if not isinstance(data, list) or not data:
            break

        all_events.extend(data)

        # If we got fewer events than the per-page cap, we have everything
        if len(data) < page_cap:
            break

        # Paginate: use the last event's timestamp as the ``since`` cursor
        last_created = data[-1].get("created")
        if last_created is None or last_created == since_ts:
            break  # No progress — avoid infinite loop
        since_ts = last_created

        if len(all_events) >= max_events:
            break

    return all_events[:max_events]


# ═════════════════════════════════════════════════════════════════════════════
#  Formatting helpers
# ═════════════════════════════════════════════════════════════════════════════

_STATUS_COLOUR = {
    "READY":    GREEN,
    "ERROR":    RED,
    "BUILDING": YELLOW,
    "CANCELED": DIM,
    "QUEUED":   DIM,
}

_ERROR_PREFIXES = (
    "error",
    "err ",
    "✗",
    "✘",
    "failed",
    "failure",
    "exception",
    "traceback",
    "exit code",
    "elifecycle",
    "command failed",
    " error:",
    "typeerror",
    "syntaxerror",
    "referenceerror",
    "cannot find",
    "module not found",
    "could not resolve",
    "404",
    "✖",
)

_WARNING_PREFIXES = (
    "warn",
    "⚠",
    "warning",
    "deprecated",
)


def _classify_line(text: str) -> str:
    """Return 'error', 'warn', or 'info' for a log line."""
    low = text.lower()
    if any(low.startswith(p) or f" {p}" in low for p in _ERROR_PREFIXES):
        return "error"
    if any(low.startswith(p) or f" {p}" in low for p in _WARNING_PREFIXES):
        return "warn"
    return "info"


def _format_status(state: str) -> str:
    colour = _STATUS_COLOUR.get(state, RESET)
    return f"{colour}{state}{RESET}"


def _print_deployment_header(dep: dict) -> None:
    uid    = dep.get("uid", dep.get("id", "?"))
    url    = dep.get("url", "")
    state  = dep.get("state", dep.get("readyState", "?"))
    branch = dep.get("meta", {}).get("githubCommitRef", "?")
    sha    = dep.get("meta", {}).get("githubCommitSha", "")[:8]
    msg    = dep.get("meta", {}).get("githubCommitMessage", "")
    print(_hdr("DEPLOYMENT"))
    print(f"  ID      : {BOLD}{uid}{RESET}")
    if url:
        print(f"  URL     : https://{url}")
    print(f"  Status  : {_format_status(state)}")
    print(f"  Branch  : {branch}  {DIM}{sha}{RESET}")
    if msg:
        first_line = msg.splitlines()[0][:80]
        print(f"  Commit  : {first_line}")


def _print_logs(events: list[dict], show_all: bool) -> None:
    """Print build log events, colouring errors/warnings."""
    printed = 0
    for ev in events:
        text = ev.get("text", "").rstrip()
        if not text:
            continue

        kind = _classify_line(text)

        if not show_all and kind == "info":
            continue  # skip routine info lines unless --all

        if kind == "error":
            print(_c(RED, text))
        elif kind == "warn":
            print(_c(YELLOW, text))
        else:
            print(text)

        printed += 1

    if printed == 0 and not show_all:
        print(_ok("No errors or warnings found in build log."))
        print(DIM + "  Run with --all to see full output." + RESET)


# ═════════════════════════════════════════════════════════════════════════════
#  Core logic
# ═════════════════════════════════════════════════════════════════════════════

def inspect_deployment(
    token: str,
    team_id: str,
    project_id: str,
    id_or_url: Optional[str],
    show_all: bool,
    num_deployments: int,
    max_events: int = 5000,
) -> None:
    """
    Fetch and print build logs for one or more deployments.

    If id_or_url is given, inspect that specific deployment.
    Otherwise list recent deployments and inspect the latest `num_deployments`.
    Automatically paginates past the Vercel events API per-page cap (~467).
    """
    if id_or_url:
        # Specific deployment requested
        events = _fetch_build_logs(token, id_or_url, team_id, max_events=max_events)
        print(_hdr("BUILD LOG"))
        _print_logs(events, show_all)
        return

    # Fetch the list and iterate
    deployments = _list_deployments(token, team_id, project_id, limit=max(num_deployments, 5))
    if not deployments:
        print(_warn("No deployments found."))
        return

    targets = deployments[:num_deployments]

    for dep in targets:
        _print_deployment_header(dep)
        uid = dep.get("uid", dep.get("id", ""))
        if not uid:
            print(_warn("  Could not determine deployment ID, skipping logs."))
            continue

        events = _fetch_build_logs(token, uid, team_id, max_events=max_events)
        if not events:
            print(_warn("  No build log events returned by API."))
        else:
            print(_hdr("BUILD LOG"))
            _print_logs(events, show_all)

        print()


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="debug.py vercel",
        description="Fetch Vercel build logs for the web app (works for ERROR deployments).",
    )
    parser.add_argument(
        "--url",
        metavar="URL_OR_ID",
        help="Inspect a specific deployment URL or ID instead of the latest.",
    )
    parser.add_argument(
        "--all",
        dest="show_all",
        action="store_true",
        help="Print full build log (default: errors and warnings only).",
    )
    parser.add_argument(
        "--n",
        dest="num_deployments",
        type=int,
        default=1,
        metavar="N",
        help="Check the last N deployments (default: 1).",
    )
    parser.add_argument(
        "--max-events",
        dest="max_events",
        type=int,
        default=5000,
        metavar="N",
        help="Maximum build log events to fetch across pagination (default: 5000). "
        "Increase if build logs appear truncated.",
    )
    args = parser.parse_args()

    token = _get_token()
    cfg   = _get_project_config()

    team_id    = cfg.get("orgId", "")
    project_id = cfg.get("projectId", "")

    if not team_id or not project_id:
        print(_warn("Could not read team/project IDs from .vercel/project.json."))
        print("  Expected at: frontend/apps/web_app/.vercel/project.json")
        sys.exit(1)

    print(_hdr("VERCEL DEPLOYMENT LOGS"))
    print(f"  Project : {cfg.get('projectName', project_id)}")
    print(f"  Team    : {team_id}")
    if args.show_all:
        print("  Mode    : full log")
    else:
        print(f"  Mode    : errors + warnings only  {DIM}(--all for full){RESET}")
    print()

    try:
        inspect_deployment(
            token=token,
            team_id=team_id,
            project_id=project_id,
            id_or_url=args.url,
            show_all=args.show_all,
            num_deployments=args.num_deployments,
            max_events=args.max_events,
        )
    except httpx.HTTPStatusError as exc:
        print(_err(f"Vercel API error {exc.response.status_code}: {exc.response.text}"))
        sys.exit(1)
    except httpx.RequestError as exc:
        print(_err(f"Network error: {exc}"))
        sys.exit(1)


if __name__ == "__main__":
    main()
