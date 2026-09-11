#!/usr/bin/env python3
"""
Ingest retained security audit/red-team snapshots and manage historical findings.

run-audit and run-redteam use the deterministic digest adapter, including its
missing/stale snapshot checks; they never launch an AI review or live probe.
acknowledge, list-findings and reset retain the existing manual state interface.
DRY_RUN avoids report persistence; PROJECT_ROOT locates retained snapshots.
Automatic agent review was removed under TASK-7543; see
 docs/architecture/infrastructure/cronjobs.md and future workflow TASK-8338.
"""

import argparse

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Append scripts/ to path so we can import shared helpers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from security_scan_reporting import ingest_snapshot


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
    """Ingest the existing structured snapshot without starting an AI audit."""
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = os.environ.get("PROJECT_ROOT", "")
    if not project_root:
        print("[security] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)
    ingest_snapshot(project_root=project_root, source="security_audit",
                    path=Path(project_root) / "logs/nightly-reports/security-audit.json", dry_run=dry_run)


def run_redteam() -> None:
    """Ingest the existing structured snapshot without starting an AI audit."""
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = os.environ.get("PROJECT_ROOT", "")
    if not project_root:
        print("[redteam] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)
    ingest_snapshot(project_root=project_root, source="redteam",
                    path=Path(project_root) / "logs/nightly-reports/red-teaming.json", dry_run=dry_run)


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
