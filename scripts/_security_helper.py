#!/usr/bin/env python3
"""
scripts/_security_helper.py

Python helper for security-audit.sh and red-teaming.sh.

Manages security audit state, deduplication of findings, and the acknowledge
workflow. Runs claude sessions for both the code-based security audit and
the external red team probe.

Commands:
    run-audit       Run the security-focused code audit (top 5 issues)
    run-redteam     Run the external red team probe (20 min cap, plan mode)
    acknowledge     Mark a finding as acknowledged (won't report again)
    list-findings   List all known findings and their status
    reset           Clear all state (for fresh start)

State files (.claude/ — gitignored):
    .claude/security-audit-state.json      — finding state, file hashes, run history
    .claude/security-acknowledged.json     — manually acknowledged risks

Environment variables (set by shell wrappers):
    DRY_RUN             — "true" to skip claude, print prompt only
    PROJECT_ROOT        — absolute path to repo root
    TODAY_DATE          — current date as YYYY-MM-DD
    PROMPT_TEMPLATE_PATH — path to the relevant prompt template
    JOB_TYPE            — "audit" or "redteam"

Not intended to be called directly; use security-audit.sh or red-teaming.sh.
For acknowledge/list-findings/reset, call directly:
    python3 scripts/_security_helper.py acknowledge --id "finding-001" --reason "Accepted risk"
    python3 scripts/_security_helper.py list-findings
    python3 scripts/_security_helper.py reset
"""

import argparse

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Append scripts/ to path so we can import _claude_utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _claude_utils import run_claude_session


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Security-relevant file patterns (for change detection)
SECURITY_RELEVANT_PATTERNS = [
    "backend/core/api/",
    "backend/apps/",
    "backend/shared/",
    "backend/core/workers/",
    "frontend/apps/web_app/src/routes/",
    "frontend/apps/web_app/src/lib/",
    "frontend/packages/ui/src/",
    "docker-compose",
    "Dockerfile",
    ".env.example",
    "nginx",
    "Caddyfile",
    "vercel.json",
]

# Max age (days) before forcing a full sweep regardless of changes
FULL_SWEEP_MAX_AGE_DAYS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_dir(project_root: str) -> Path:
    """Return .claude/ directory, creating it if needed."""
    d = Path(project_root) / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(project_root: str) -> Path:
    return _state_dir(project_root) / "security-audit-state.json"


def _acknowledged_path(project_root: str) -> Path:
    return _state_dir(project_root) / "security-acknowledged.json"


def _load_json(path: Path, default: dict | list) -> dict | list:
    if not path.is_file():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"[security] WARNING: could not load {path}: {e}", file=sys.stderr)
        return default


def _save_json(path: Path, data: dict | list) -> None:
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _load_state(project_root: str) -> dict:
    default = {
        "last_audit_date": None,
        "last_audit_sha": None,
        "last_audit_session_id": None,
        "last_redteam_date": None,
        "last_redteam_sha": None,
        "last_redteam_session_id": None,
        "last_full_sweep_date": None,
        "findings": {},
        "run_history": [],
    }
    data = _load_json(_state_path(project_root), default)
    for k, v in default.items():
        data.setdefault(k, v)
    return data


def _save_state(project_root: str, data: dict) -> None:
    _save_json(_state_path(project_root), data)
    print(f"[security] State file updated: {_state_path(project_root)}")


def _load_acknowledged(project_root: str) -> dict:
    """Load acknowledged findings. Format: {"finding-id": {"reason": "...", "date": "..."}}"""
    return _load_json(_acknowledged_path(project_root), {})


def _save_acknowledged(project_root: str, data: dict) -> None:
    _save_json(_acknowledged_path(project_root), data)


def _get_current_sha(project_root: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get_changed_files(project_root: str, since_sha: str | None) -> str:
    """Get files changed since a given SHA, filtered to security-relevant paths."""
    if not since_sha:
        # First run — show all recent changes (last 2 weeks)
        cmd = ["git", "-C", project_root, "log", "--name-only", "--pretty=format:", "--since=14 days ago"]
    else:
        cmd = ["git", "-C", project_root, "diff", "--name-only", since_sha, "HEAD"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        all_files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except Exception as e:
        print(f"[security] WARNING: git diff failed: {e}", file=sys.stderr)
        return "(could not retrieve changed files)"

    # Filter to security-relevant files
    relevant = []
    for f in sorted(set(all_files)):
        if any(f.startswith(p) or p in f for p in SECURITY_RELEVANT_PATTERNS):
            relevant.append(f)

    if not relevant:
        return "(no security-relevant files changed)"

    return "\n".join(relevant)


def _get_recent_commits(project_root: str, count: int = 30) -> str:
    """Get recent commit log for red team context."""
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "log", "--oneline", f"-{count}"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() or "(no recent commits)"
    except Exception:
        return "(could not retrieve git log)"


def _format_known_findings(findings: dict, exclude_ids: set) -> str:
    """Format known open findings for inclusion in prompt."""
    items = []
    for fid, f in sorted(findings.items()):
        if fid in exclude_ids:
            continue
        if f.get("status") == "fixed":
            continue
        severity = f.get("severity", "UNKNOWN")
        title = f.get("title", "Untitled")
        files = ", ".join(f.get("files", []))
        items.append(f"- [{severity}] {title} ({files}) [id: {fid}]")

    if not items:
        return "(none — this is the first audit or all previous findings are fixed)"
    return "\n".join(items)


def _format_acknowledged(acknowledged: dict) -> str:
    """Format acknowledged findings for inclusion in prompt."""
    if not acknowledged:
        return "(none)"
    items = []
    for fid, info in sorted(acknowledged.items()):
        reason = info.get("reason", "no reason given")
        items.append(f"- {fid}: {reason}")
    return "\n".join(items)


def _needs_full_sweep(state: dict) -> bool:
    """Check if a full sweep is needed (>30 days since last one)."""
    last = state.get("last_full_sweep_date")
    if not last:
        return True
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d")
        age = (datetime.now() - last_dt).days
        return age >= FULL_SWEEP_MAX_AGE_DAYS
    except Exception:
        return True


def _record_run(state: dict, job_type: str, sha: str, session_id: str | None) -> None:
    """Record a run in the state history (keep last 50)."""
    state["run_history"].append({
        "type": job_type,
        "date": _now_iso(),
        "sha": sha,
        "session_id": session_id,
    })
    state["run_history"] = state["run_history"][-50:]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def run_audit() -> None:
    """Run the security-focused code audit."""
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = os.environ.get("PROJECT_ROOT", "")
    today_date = os.environ.get("TODAY_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE_PATH", "")

    if not project_root:
        print("[security] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)

    state = _load_state(project_root)
    acknowledged = _load_acknowledged(project_root)
    current_sha = _get_current_sha(project_root)
    last_sha = state.get("last_audit_sha")
    last_date = state.get("last_audit_date") or "first run"

    # Check if there are relevant changes
    changed_files = _get_changed_files(project_root, last_sha)
    force_full = _needs_full_sweep(state)

    if "(no security-relevant files changed)" in changed_files and not force_full:
        print(f"[security] No security-relevant files changed since last audit ({last_date}). Skipping.")
        # Still update SHA so we don't re-check the same range
        state["last_audit_sha"] = current_sha
        state["last_audit_date"] = today_date
        _save_state(project_root, state)
        return

    if force_full:
        print(f"[security] Full sweep triggered (last full sweep: {state.get('last_full_sweep_date', 'never')})")
        changed_files = "(FULL SWEEP — reviewing all security-relevant code regardless of changes)"

    print(f"[security] Running security audit (HEAD {current_sha}, last audit: {last_date})")

    # Load prompt template
    if not prompt_template_path or not os.path.isfile(prompt_template_path):
        print(f"[security] ERROR: Prompt template not found: {prompt_template_path}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_template_path) as f:
        prompt_template = f.read()

    # Build prompt
    acknowledged_ids = set(acknowledged.keys())
    known_findings = _format_known_findings(state.get("findings", {}), acknowledged_ids)
    acknowledged_text = _format_acknowledged(acknowledged)

    prompt = (
        prompt_template
        .replace("{{DATE}}", today_date)
        .replace("{{GIT_SHA}}", current_sha)
        .replace("{{LAST_AUDIT_DATE}}", last_date)
        .replace("{{CHANGED_FILES}}", changed_files)
        .replace("{{KNOWN_FINDINGS}}", known_findings)
        .replace("{{ACKNOWLEDGED_FINDINGS}}", acknowledged_text)
    )

    if dry_run:
        print("[security] DRY RUN — would run claude with the following prompt:")
        print("-" * 60)
        print(prompt[:3000])
        print(f"... ({len(prompt)} chars total)")
        print("-" * 60)
        state["last_audit_date"] = today_date
        state["last_audit_sha"] = current_sha
        if force_full:
            state["last_full_sweep_date"] = today_date
        _save_state(project_root, state)
        return

    session_title = f"security-audit: top 5 issues {today_date}"
    print(f"[security] Starting claude security audit session (HEAD {current_sha})...")

    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=project_root,
        log_prefix="[security]",
        agent="plan",
        timeout=2700,  # 45 min max — no hard limit, but cap to be safe
    )

    # Update state
    state["last_audit_date"] = today_date
    state["last_audit_sha"] = current_sha
    state["last_audit_session_id"] = session_id
    if force_full:
        state["last_full_sweep_date"] = today_date
    _record_run(state, "audit", current_sha, session_id)
    _save_state(project_root, state)

    if returncode != 0:
        print(f"[security] WARNING: audit session exited with code {returncode}", file=sys.stderr)
        sys.exit(returncode)

    print("[security] Security audit complete.")


def run_redteam() -> None:
    """Run the external red team probe (20 min cap, plan mode)."""
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = os.environ.get("PROJECT_ROOT", "")
    today_date = os.environ.get("TODAY_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE_PATH", "")

    if not project_root:
        print("[redteam] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)

    state = _load_state(project_root)
    acknowledged = _load_acknowledged(project_root)
    current_sha = _get_current_sha(project_root)
    last_date = state.get("last_redteam_date") or "first run"

    recent_commits = _get_recent_commits(project_root, count=30)

    print(f"[redteam] Running red team probe (HEAD {current_sha}, last probe: {last_date})")

    # Load prompt template
    if not prompt_template_path or not os.path.isfile(prompt_template_path):
        print(f"[redteam] ERROR: Prompt template not found: {prompt_template_path}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_template_path) as f:
        prompt_template = f.read()

    # Build prompt
    acknowledged_ids = set(acknowledged.keys())
    known_findings = _format_known_findings(state.get("findings", {}), acknowledged_ids)
    acknowledged_text = _format_acknowledged(acknowledged)

    prompt = (
        prompt_template
        .replace("{{DATE}}", today_date)
        .replace("{{GIT_SHA}}", current_sha)
        .replace("{{LAST_AUDIT_DATE}}", last_date)
        .replace("{{KNOWN_FINDINGS}}", known_findings)
        .replace("{{ACKNOWLEDGED_FINDINGS}}", acknowledged_text)
        .replace("{{RECENT_COMMITS}}", recent_commits)
    )

    if dry_run:
        print("[redteam] DRY RUN — would run claude with the following prompt:")
        print("-" * 60)
        print(prompt[:3000])
        print(f"... ({len(prompt)} chars total)")
        print("-" * 60)
        state["last_redteam_date"] = today_date
        state["last_redteam_sha"] = current_sha
        _save_state(project_root, state)
        return

    session_title = f"redteam: external probe {today_date}"
    print(f"[redteam] Starting claude red team session (HEAD {current_sha})...")

    # 20 minute hard cap (1200 seconds) — plan mode only
    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=project_root,
        log_prefix="[redteam]",
        agent="plan",
        timeout=1200,
        allowed_tools=["Read", "Grep", "Glob", "Bash(curl *)"],
    )

    # Update state
    state["last_redteam_date"] = today_date
    state["last_redteam_sha"] = current_sha
    state["last_redteam_session_id"] = session_id
    _record_run(state, "redteam", current_sha, session_id)
    _save_state(project_root, state)

    if returncode != 0:
        # Timeout (exit 124) is expected for red team — not an error
        if returncode == 124:
            print("[redteam] Session reached 20-minute time limit (expected).")
        else:
            print(f"[redteam] WARNING: red team session exited with code {returncode}", file=sys.stderr)
            sys.exit(returncode)

    print("[redteam] Red team probe complete.")


def acknowledge_finding() -> None:
    """Mark a finding as acknowledged (accepted risk)."""
    parser = argparse.ArgumentParser(description="Acknowledge a security finding")
    parser.add_argument("command")  # consume the "acknowledge" positional
    parser.add_argument("--id", required=True, help="Finding ID to acknowledge")
    parser.add_argument("--reason", required=True, help="Reason for accepting the risk")
    args = parser.parse_args()

    project_root = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    acknowledged = _load_acknowledged(project_root)

    acknowledged[args.id] = {
        "reason": args.reason,
        "date": _now_iso(),
    }
    _save_acknowledged(project_root, acknowledged)
    print(f"[security] Acknowledged finding '{args.id}': {args.reason}")


def list_findings() -> None:
    """List all known findings and their status."""
    project_root = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    state = _load_state(project_root)
    acknowledged = _load_acknowledged(project_root)

    findings = state.get("findings", {})
    if not findings and not acknowledged:
        print("[security] No findings recorded yet.")
        return

    print("\n=== Open Findings ===")
    open_count = 0
    for fid, f in sorted(findings.items()):
        if f.get("status") == "fixed" or fid in acknowledged:
            continue
        open_count += 1
        severity = f.get("severity", "?")
        title = f.get("title", "Untitled")
        first_seen = f.get("first_seen", "?")
        files = ", ".join(f.get("files", []))
        print(f"  [{severity}] {fid}: {title}")
        print(f"         Files: {files}")
        print(f"         First seen: {first_seen}")
    if open_count == 0:
        print("  (none)")

    print("\n=== Acknowledged Findings ===")
    if not acknowledged:
        print("  (none)")
    else:
        for fid, info in sorted(acknowledged.items()):
            print(f"  {fid}: {info.get('reason', '?')} (since {info.get('date', '?')})")

    print("\n=== Run History (last 10) ===")
    for run in state.get("run_history", [])[-10:]:
        rtype = run.get("type", "?")
        rdate = run.get("date", "?")
        rsha = run.get("sha", "?")
        rurl = run.get("session_id", "")
        print(f"  [{rtype}] {rdate} (SHA {rsha}) {rurl or ''}")


def reset_state() -> None:
    """Clear all security state (fresh start)."""
    project_root = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    state_path = _state_path(project_root)
    ack_path = _acknowledged_path(project_root)

    for p in [state_path, ack_path]:
        if p.is_file():
            p.unlink()
            print(f"[security] Removed {p}")
        else:
            print(f"[security] {p} does not exist, nothing to remove.")
    print("[security] State reset complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <run-audit|run-redteam|acknowledge|list-findings|reset>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command == "run-audit":
        run_audit()
    elif command == "run-redteam":
        run_redteam()
    elif command == "acknowledge":
        acknowledge_finding()
    elif command == "list-findings":
        list_findings()
    elif command == "reset":
        reset_state()
    else:
        print(f"[security] Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
