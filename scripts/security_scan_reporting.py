#!/usr/bin/env python3
"""Opt-in persistence bridge for deterministic security scanner observations.

The scanner helpers remain usable without a reporting ledger.  Persistence is
enabled only by a local marker so host deployments opt in deliberately.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

if __package__:
    from .security_reporting import ReportingStore, _utc_timestamp, read_reporting_config as _marker
else:
    from security_reporting import ReportingStore, _utc_timestamp, read_reporting_config as _marker


def reporting_directory(project_root: str | Path) -> Path:
    return Path(os.environ.get("SECURITY_REPORTING_DIR") or Path(project_root) / "logs" / "security-reporting")


def reporting_enabled(project_root: str | Path) -> Path | None:
    directory = reporting_directory(project_root)
    config = _marker(directory)
    enabled = config.get("collection_enabled") is True or config.get("enabled") is True
    return directory if enabled else None


def report_scan(*, project_root: str | Path, source: str, findings: list[dict[str, Any]], outcome: str,
                subject_commit: str, coverage: dict[str, Any] | None = None,
                inventory: dict[str, Any] | None = None, dry_run: bool = False,
                summary_only: bool = False) -> str | None:
    """Persist one completed scanner observation and request critical delivery.

    Failures are intentionally non-blocking: scanner remediation remains more
    important than reporting availability, while the warning exposes the gap.
    """
    if dry_run or summary_only:
        return None
    directory = reporting_enabled(project_root)
    if directory is None:
        return None
    coverage = dict(coverage or {})
    if os.environ.get("SECURITY_REPORTING_SLOT"):
        coverage["scheduled_slot"] = _utc_timestamp(os.environ["SECURITY_REPORTING_SLOT"])
    try:
        run_id = ReportingStore(directory / "reporting.sqlite3").record_run(
            source, findings, outcome, subject_commit, coverage=coverage, inventory=inventory
        )
    except Exception as error:
        print(f"[security-reporting] WARNING: persistence unavailable ({type(error).__name__})", file=sys.stderr)
        return None
    if not _marker(directory).get("enabled") or os.environ.get("SECURITY_REPORTING_COLLECTION_ONLY", "").lower() == "true":
        return run_id
    try:
        delivery = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("security_reporting_runner.py")), "critical"],
            cwd=project_root, env={**os.environ, "SECURITY_REPORTING_DIR": str(directory.resolve())}, capture_output=True, text=True, timeout=30, check=False,
        )
        if delivery.returncode != 0:
            raise RuntimeError("delivery_runner_failed")
    except Exception as error:
        print(f"[security-reporting] WARNING: critical delivery unavailable ({type(error).__name__})", file=sys.stderr)
        try:
            ReportingStore(directory / "reporting.sqlite3").record_run(
                "security_reporting_delivery", [], "incomplete", subject_commit,
                coverage={"expected_and_completed_stages": {"critical_delivery": [1, 0]}, "sanitized_failure_codes": ["critical_delivery_unavailable"]},
                inventory={"missing_required_data": ["critical_delivery_receipt"]},
            )
        except Exception as persistence_error:
            print(f"[security-reporting] WARNING: delivery failure could not persist ({type(persistence_error).__name__})", file=sys.stderr)
    return run_id


def ingest_snapshot(*, project_root: str | Path, source: str, path: Path, dry_run: bool = False) -> str | None:
    """Ingest dated normalized audit data; never interpret prose or start an audit.

    Producers may expose details.security_reporting in their nightly JSON.
    Legacy summaries remain explicitly unavailable, with their original date.
    """
    if source not in {"security_audit", "redteam"}:
        raise ValueError("snapshot source must be an audit or redteam")
    directory = reporting_enabled(project_root)
    if directory is None or dry_run:
        return None
    record = {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        observed_at = _utc_timestamp(record["ran_at"])
        details = record.get("details", {}).get("security_reporting", {})
        findings = details.get("findings")
        structured = isinstance(findings, list) and all(isinstance(item, dict) and item.get("vuln_id") and item.get("package") and item.get("ecosystem") for item in findings)
        outcome = details.get("outcome") if structured else "incomplete"
        if outcome not in {"findings", "no_new_findings", "incomplete", "failed", "skipped"}:
            outcome, structured = "incomplete", False
        commit = str(details.get("subject_commit") or "unknown")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print(f"[security-reporting] {source}: structured snapshot unavailable", file=sys.stderr)
        observed_at, findings, outcome, structured, commit = _utc_timestamp(), [], "incomplete", False, "unknown"
    # Never persist arbitrary source prose, links or transcripts.
    allowed = {"vuln_id", "aliases", "package", "ecosystem", "severity", "current_version", "state", "resolution_evidence", "remediation"}
    findings = [{key: item[key] for key in allowed if key in item} for item in findings] if structured else []
    payload = {"findings": findings, "observed_at": observed_at, "outcome": outcome, "commit": commit}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return ReportingStore(directory / "reporting.sqlite3").record_run(
        source, findings, outcome, commit, completed_at=observed_at,
        run_id=f"snapshot-{source}-{identity}",
        coverage={"expected_and_completed_stages": {"structured_snapshot": [1, int(structured)]}, "sanitized_failure_codes": [] if structured else ["structured_snapshot_unavailable"]},
        inventory={"structured": structured},
    )
