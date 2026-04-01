#!/usr/bin/env python3
"""
scripts/_nightly_report.py

Shared utility for nightly cron jobs to write standardized summary reports.
Each job calls write_nightly_report() at the end of its run; the daily meeting
helper auto-discovers all reports from logs/nightly-reports/.

Report format (JSON):
    {
        "job": "dependabot",
        "ran_at": "2026-03-31T04:30:00Z",
        "status": "ok" | "warning" | "error" | "skipped",
        "summary": "1-2 sentence human-readable summary",
        "details": { ... job-specific structured data ... },
        "security_disclosure": { ... only for security/dependabot jobs ... }
    }

The security_disclosure field (when present) includes:
    - packages_updated: [{name, from_version, to_version, cve, used_in_project, user_risk}]
    - risk_summary: human-readable risk assessment for users

Auto-cleanup: reports older than 7 days are pruned on each write.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_DIR = PROJECT_ROOT / "logs" / "nightly-reports"

# Reports older than this are deleted on each write
REPORT_RETENTION_DAYS = 7


def write_nightly_report(
    job: str,
    status: str,
    summary: str,
    details: dict | None = None,
    security_disclosure: dict | None = None,
) -> Path:
    """Write a standardized nightly report JSON file.

    Args:
        job: Short identifier for the cron job (e.g. "dependabot", "docker-cleanup").
        status: One of "ok", "warning", "error", "skipped".
        summary: 1-2 sentence human-readable summary of the run.
        details: Job-specific structured data (optional).
        security_disclosure: Security-relevant info for user disclosure (optional).

    Returns:
        Path to the written report file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _prune_old_reports()

    now = datetime.now(timezone.utc)
    report = {
        "job": job,
        "ran_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "summary": summary,
    }
    if details:
        report["details"] = details
    if security_disclosure:
        report["security_disclosure"] = security_disclosure

    # Filename: {job}.json (latest wins — one report per job type)
    report_path = REPORTS_DIR / f"{job}.json"
    tmp_path = report_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, report_path)

    print(f"[nightly-report] Wrote {report_path} ({status})")
    return report_path


def read_all_reports() -> dict[str, dict]:
    """Read all nightly report JSON files from the reports directory.

    Returns:
        Dict mapping job name to the parsed report dict.
        Reports older than REPORT_RETENTION_DAYS are excluded.
    """
    reports = {}
    if not REPORTS_DIR.is_dir():
        return reports

    cutoff = datetime.now(timezone.utc) - timedelta(days=REPORT_RETENTION_DAYS)

    for path in sorted(REPORTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            ran_at = datetime.strptime(data["ran_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if ran_at >= cutoff:
                reports[data.get("job", path.stem)] = data
        except Exception as e:
            print(f"[nightly-report] WARNING: failed to read {path}: {e}")

    return reports


def _prune_old_reports() -> None:
    """Delete report files older than REPORT_RETENTION_DAYS."""
    if not REPORTS_DIR.is_dir():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=REPORT_RETENTION_DAYS)
    for path in REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            ran_at = datetime.strptime(data["ran_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if ran_at < cutoff:
                path.unlink()
                print(f"[nightly-report] Pruned old report: {path.name}")
        except Exception:
            pass
