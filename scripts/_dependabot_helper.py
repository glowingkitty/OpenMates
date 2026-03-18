#!/usr/bin/env python3
"""
scripts/_dependabot_helper.py

Python helper for check-dependabot-daily.sh.

Handles the complex dedup, state tracking, and opencode dispatch logic for
Dependabot security alerts. Called by the shell script via:

    python3 scripts/_dependabot_helper.py process-alerts

Environment variables (set by the shell script):
    ALERTS_JSON_B64         — base64-encoded JSON array of GitHub Dependabot alerts
    TRACKING_FILE_PATH      — absolute path to scripts/dependabot-processed.json
    PROJECT_ROOT            — absolute path to the repo root
    REDISPATCH_AFTER_DAYS   — number of days before re-dispatching an unresolved alert
    DRY_RUN                 — "true" to skip actual opencode invocation
    PROMPT_TEMPLATE_PATH    — absolute path to scripts/prompts/dependabot-analysis.md
    TODAY_DATE              — current date as YYYY-MM-DD

Tracking file format (scripts/dependabot-processed.json):
{
  "last_run": "2026-03-17T04:00:00Z",
  "processed": [
    {
      "ghsa_id": "GHSA-wfv2-pwc8-crg5",
      "severity": "critical",
      "package": "jspdf",
      "summary": "jsPDF has HTML Injection in New Window paths",
      "alert_numbers": [111, 112],
      "first_seen_at": "2026-03-17T04:00:00Z",
      "last_dispatched_at": "2026-03-17T04:00:00Z",
      "re_dispatch_count": 0,
      "resolved_via_commit": null
    }
  ]
}
"""

import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Severity levels to process (skip "low")
PROCESS_SEVERITIES = {"critical", "high", "medium"}

# Severity sort order for prompt grouping
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_tracking(tracking_file: str) -> dict:
    """Load the tracking file, returning an empty structure if it doesn't exist or is corrupt."""
    empty = {"last_run": _now_iso(), "processed": []}
    if not os.path.isfile(tracking_file):
        return empty
    try:
        with open(tracking_file) as f:
            data = json.load(f)
        if "processed" not in data:
            data["processed"] = []
        return data
    except Exception as e:
        print(f"[dependabot] WARNING: could not load tracking file: {e} — starting fresh.", file=sys.stderr)
        return empty


def _save_tracking(tracking_file: str, data: dict) -> None:
    """Save the tracking file atomically via a temp file."""
    tmp_path = tracking_file + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, tracking_file)
    print(f"[dependabot] Tracking file updated: {tracking_file}")


def _check_ghsa_in_git(ghsa_id: str, project_root: str) -> str | None:
    """
    Search git log for a commit message containing the GHSA ID.
    Returns the commit SHA if found, or None.
    """
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "log", "--all", "--oneline", f"--grep={ghsa_id}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if output:
            return output.splitlines()[0].split()[0]
        return None
    except Exception as e:
        print(f"[dependabot] WARNING: git log search failed for {ghsa_id}: {e}", file=sys.stderr)
        return None


def _deduplicate_by_ghsa(alerts: list[dict]) -> dict[str, dict]:
    """
    Deduplicate alerts by GHSA ID. Multiple alerts for the same GHSA
    (e.g. same vuln in frontend and backend manifests) are merged into one entry.

    Returns a dict: ghsa_id -> merged alert dict.
    """
    merged: dict[str, dict] = {}
    for alert in alerts:
        sa = alert.get("security_advisory", {}) or {}
        sv = alert.get("security_vulnerability", {}) or {}
        dep = alert.get("dependency", {}) or {}
        pkg = dep.get("package", {}) or {}

        ghsa_id = sa.get("ghsa_id", "")
        if not ghsa_id:
            # Skip alerts without a GHSA ID — can't deduplicate or track them
            continue

        severity = (sa.get("severity") or sv.get("severity") or "unknown").lower()
        if severity not in PROCESS_SEVERITIES:
            continue

        alert_number = alert.get("number", 0)
        package_name = pkg.get("name", "unknown")
        ecosystem = pkg.get("ecosystem", "")
        summary = sa.get("summary", "")
        cve_id = sa.get("cve_id") or ""
        fixed_in = sv.get("first_patched_version", {}) or {}
        fixed_version = fixed_in.get("identifier", "") if isinstance(fixed_in, dict) else ""

        # Find which manifest files are affected
        manifest = dep.get("manifest_path", "")

        if ghsa_id not in merged:
            merged[ghsa_id] = {
                "ghsa_id": ghsa_id,
                "severity": severity,
                "package": package_name,
                "ecosystem": ecosystem,
                "summary": summary,
                "cve_id": cve_id,
                "fixed_version": fixed_version,
                "alert_numbers": [alert_number],
                "manifest_paths": [manifest] if manifest else [],
            }
        else:
            # Merge additional alert numbers and manifest paths
            if alert_number not in merged[ghsa_id]["alert_numbers"]:
                merged[ghsa_id]["alert_numbers"].append(alert_number)
            if manifest and manifest not in merged[ghsa_id]["manifest_paths"]:
                merged[ghsa_id]["manifest_paths"].append(manifest)

    return merged


def _build_alert_summary(alerts_to_dispatch: list[dict]) -> str:
    """
    Build the alert summary section for the opencode prompt.
    Groups alerts by severity: CRITICAL, HIGH, MEDIUM.
    """
    by_severity: dict[str, list] = {"critical": [], "high": [], "medium": []}

    for alert in alerts_to_dispatch:
        sev = alert["severity"].lower()
        if sev in by_severity:
            by_severity[sev].append(alert)

    lines = []
    for sev in ("critical", "high", "medium"):
        if not by_severity[sev]:
            continue
        lines.append(f"\n{sev.upper()}:")
        for a in by_severity[sev]:
            ghsa = a["ghsa_id"]
            pkg = a["package"]
            summary = a["summary"]
            cve = f" ({a['cve_id']})" if a.get("cve_id") else ""
            fixed = f"\n  Fix: upgrade to >= {a['fixed_version']}" if a.get("fixed_version") else "\n  Fix: upgrade to latest patched version (check GitHub advisory for details)"
            manifests = a.get("manifest_paths", [])
            manifest_str = "\n  Affected files: " + ", ".join(manifests) if manifests else ""
            re_dispatch = a.get("re_dispatch_count", 0)
            re_dispatch_note = f"\n  NOTE: Previously dispatched {re_dispatch} time(s) — still unresolved." if re_dispatch > 0 else ""

            lines.append(f"- [{ghsa}] {pkg} — {summary}{cve}{fixed}{manifest_str}{re_dispatch_note}")

    return "\n".join(lines)


def process_alerts() -> None:
    """
    Main entry point: process Dependabot alerts, update tracking, run opencode if needed.
    """
    # Read env vars set by the shell script
    alerts_json_b64 = os.environ.get("ALERTS_JSON_B64", "")
    tracking_file = os.environ.get("TRACKING_FILE_PATH", "")
    project_root = os.environ.get("PROJECT_ROOT", "")
    redispatch_days = int(os.environ.get("REDISPATCH_AFTER_DAYS", "7"))
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE_PATH", "")
    today_date = os.environ.get("TODAY_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    if not tracking_file:
        print("[dependabot] ERROR: TRACKING_FILE_PATH not set.", file=sys.stderr)
        sys.exit(1)

    if not alerts_json_b64:
        print("[dependabot] ERROR: ALERTS_JSON_B64 not set.", file=sys.stderr)
        sys.exit(1)

    # Decode and parse alerts
    try:
        alerts_json = base64.b64decode(alerts_json_b64).decode("utf-8")
        raw_alerts: list[dict] = json.loads(alerts_json)
    except Exception as e:
        print(f"[dependabot] ERROR: Failed to decode/parse alerts: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[dependabot] Processing {len(raw_alerts)} raw alert(s)...")

    # Step 1: Deduplicate by GHSA ID and filter by severity
    deduplicated = _deduplicate_by_ghsa(raw_alerts)
    print(
        f"[dependabot] After dedup + severity filter: {len(deduplicated)} unique GHSA ID(s) "
        f"(critical/high/medium only, low skipped)"
    )

    if not deduplicated:
        print("[dependabot] No processable alerts after filtering — done.")
        return

    # Step 2: Load tracking state
    tracking = _load_tracking(tracking_file)
    processed_map: dict[str, dict] = {e["ghsa_id"]: e for e in tracking.get("processed", [])}

    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Step 3: For each GHSA, determine action
    to_dispatch: list[dict] = []
    skip_count = 0
    resolve_count = 0

    for ghsa_id, alert in deduplicated.items():
        # Check if resolved in git
        commit_sha = _check_ghsa_in_git(ghsa_id, project_root)
        if commit_sha:
            print(f"[dependabot] {ghsa_id} resolved via commit {commit_sha} — marking resolved.")
            # Update or create tracking entry
            if ghsa_id in processed_map:
                processed_map[ghsa_id]["resolved_via_commit"] = commit_sha
            else:
                processed_map[ghsa_id] = {
                    "ghsa_id": ghsa_id,
                    "severity": alert["severity"],
                    "package": alert["package"],
                    "summary": alert["summary"],
                    "alert_numbers": alert["alert_numbers"],
                    "first_seen_at": now_iso,
                    "last_dispatched_at": None,
                    "re_dispatch_count": 0,
                    "resolved_via_commit": commit_sha,
                }
            resolve_count += 1
            continue

        # Not resolved — check tracking state
        existing = processed_map.get(ghsa_id)

        if existing is None:
            # Never seen before → dispatch now
            print(f"[dependabot] {ghsa_id} [{alert['severity']}] {alert['package']} — NEW, will dispatch.")
            dispatch_entry = {**alert, "re_dispatch_count": 0}
            to_dispatch.append(dispatch_entry)
            processed_map[ghsa_id] = {
                "ghsa_id": ghsa_id,
                "severity": alert["severity"],
                "package": alert["package"],
                "summary": alert["summary"],
                "alert_numbers": alert["alert_numbers"],
                "first_seen_at": now_iso,
                "last_dispatched_at": now_iso,  # Will be set after dispatch
                "re_dispatch_count": 0,
                "resolved_via_commit": None,
            }
        else:
            # Previously seen — check if within grace period
            last_dispatched_str = existing.get("last_dispatched_at")
            if not last_dispatched_str:
                # Was tracked but never dispatched (shouldn't normally happen)
                print(f"[dependabot] {ghsa_id} [{alert['severity']}] — tracked but never dispatched, dispatching now.")
                dispatch_entry = {**alert, "re_dispatch_count": 0}
                to_dispatch.append(dispatch_entry)
                existing["last_dispatched_at"] = now_iso
            else:
                try:
                    last_dispatched = datetime.fromisoformat(last_dispatched_str.replace("Z", "+00:00"))
                    days_since = (now - last_dispatched).days
                except ValueError:
                    days_since = redispatch_days + 1  # Force re-dispatch if date is unparseable

                if days_since >= redispatch_days:
                    re_count = existing.get("re_dispatch_count", 0) + 1
                    print(
                        f"[dependabot] {ghsa_id} [{alert['severity']}] — "
                        f"still unresolved after {days_since} days, RE-DISPATCHING (count={re_count})."
                    )
                    dispatch_entry = {**alert, "re_dispatch_count": re_count}
                    to_dispatch.append(dispatch_entry)
                    existing["re_dispatch_count"] = re_count
                    existing["last_dispatched_at"] = now_iso
                else:
                    remaining = redispatch_days - days_since
                    print(
                        f"[dependabot] {ghsa_id} [{alert['severity']}] — "
                        f"within {redispatch_days}-day grace period ({remaining} day(s) remaining), skipping."
                    )
                    skip_count += 1

    print(
        f"[dependabot] Dispatch summary: {len(to_dispatch)} to dispatch, "
        f"{skip_count} skipped (grace period), {resolve_count} resolved in git."
    )

    # Update tracking before dispatch (so state is saved even if opencode fails)
    tracking["last_run"] = now_iso
    tracking["processed"] = list(processed_map.values())
    _save_tracking(tracking_file, tracking)

    if not to_dispatch:
        print("[dependabot] Nothing to dispatch — done.")
        return

    # Sort by severity for the prompt
    to_dispatch.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"].lower(), 99))

    # Step 4: Build the prompt
    if not prompt_template_path or not os.path.isfile(prompt_template_path):
        print(f"[dependabot] ERROR: Prompt template not found at {prompt_template_path}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_template_path) as f:
        prompt_template = f.read()

    alert_summary = _build_alert_summary(to_dispatch)
    prompt = (
        prompt_template
        .replace("{{DATE}}", today_date)
        .replace("{{ALERT_SUMMARY}}", alert_summary)
    )

    # Step 5: Run opencode
    if dry_run:
        print("[dependabot] DRY RUN — would run opencode with the following prompt:")
        print("-" * 60)
        print(prompt[:2000])
        print("-" * 60)
        return

    session_title = f"security: dependabot {today_date}"
    cmd = [
        "opencode", "run",
        "--attach", "http://localhost:4096",
        "--share",
        "--model", "anthropic/claude-sonnet-4-6",
        "--title", session_title,
        "--dir", project_root,
        prompt,
    ]

    print(f"[dependabot] Starting opencode session for {len(to_dispatch)} alert(s)...")

    # Cron runs with a minimal PATH that excludes ~/.npm-global/bin where opencode lives.
    run_env = os.environ.copy()
    run_env["PATH"] = "/home/superdev/.npm-global/bin:" + run_env.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minutes max for security fixes
            env=run_env,
        )

        combined = (result.stdout + result.stderr).strip()

        # Extract and log the share URL
        share_url = None
        for line in (result.stdout + result.stderr).splitlines():
            for token in line.split():
                if "opncd.ai/share/" in token:
                    share_url = token.strip()
                    break
            if share_url:
                break

        if share_url:
            print(f"[dependabot] opencode session: {share_url}")
        else:
            print("[dependabot] WARNING: no share URL found in opencode output.", file=sys.stderr)

        if result.returncode != 0:
            print(
                f"[dependabot] WARNING: opencode exited with code {result.returncode}",
                file=sys.stderr,
            )
            if result.stderr.strip():
                print(f"[dependabot] opencode stderr: {result.stderr[:1000]}", file=sys.stderr)
        else:
            print("[dependabot] opencode session completed successfully.")

        if combined:
            print(f"[dependabot] opencode output (first 500 chars): {combined[:500]}")

    except subprocess.TimeoutExpired:
        print("[dependabot] WARNING: opencode timed out after 30 minutes.", file=sys.stderr)
    except FileNotFoundError:
        print("[dependabot] ERROR: opencode binary not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[dependabot] ERROR: opencode failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <process-alerts>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command == "process-alerts":
        process_alerts()
    else:
        print(f"[dependabot] Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
