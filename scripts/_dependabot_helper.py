#!/usr/bin/env python3
"""
Collect Dependabot observations for the deterministic security ledger.

The process-alerts command normalizes all fetched alerts and preserves coverage
and incomplete-data reporting. DRY_RUN and SUMMARY_ONLY do not persist reports.
Legacy tracking utilities remain for existing records. Automatic agent
remediation and redispatch were removed under TASK-7543; TASK-8338 owns future
workflow requirements. See docs/architecture/infrastructure/cronjobs.md.
"""

import json
import os
import re
import subprocess

try:
    from .audit_frontend_dependency_pins import collect_package_versions
    from ._nightly_report import write_nightly_report
    from .security_scan_reporting import report_scan
except ImportError:
    from audit_frontend_dependency_pins import collect_package_versions
    from _nightly_report import write_nightly_report
    from security_scan_reporting import report_scan
import sys
from datetime import datetime, timedelta, timezone


# Severity levels to process (skip "low")
PROCESS_SEVERITIES = {"critical", "high", "medium"}

# Severity sort order for prompt grouping
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
SEMVER_PREFIX_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_commit(project_root: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", project_root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


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
    """Save the tracking file atomically via a temp file.

    Prunes resolved entries older than 72 hours to prevent unbounded growth.
    """
    PRUNE_HOURS = 72
    cutoff = datetime.now(timezone.utc) - timedelta(hours=PRUNE_HOURS)
    original_count = len(data.get("processed", []))

    pruned = []
    for entry in data.get("processed", []):
        # Keep unresolved entries (still need tracking)
        if not entry.get("resolved_via_commit"):
            pruned.append(entry)
            continue
        # Keep resolved entries newer than cutoff
        first_seen = entry.get("first_seen_at", "")
        try:
            seen_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
            if seen_dt >= cutoff:
                pruned.append(entry)
        except (ValueError, TypeError):
            pruned.append(entry)  # Keep if date is unparseable

    data["processed"] = pruned
    removed = original_count - len(pruned)
    if removed > 0:
        print(f"[dependabot] Pruned {removed} resolved entries older than {PRUNE_HOURS}h")

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
    except Exception as error:
        print(
            f"[dependabot] WARNING: git log search failed for {ghsa_id}: {error}",
            file=sys.stderr,
        )
        return None


def _semver_prefix(version: str) -> tuple[int, int, int] | None:
    match = SEMVER_PREFIX_RE.match(version.split("(", 1)[0])
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _alert_is_fixed_in_project(alert: dict, project_root: str) -> bool:
    """Return whether every resolved dev npm version meets the advisory floor."""
    if alert.get("ecosystem", "").lower() != "npm":
        return False
    package = alert.get("package", "")
    fixed_version = _semver_prefix(alert.get("fixed_version", ""))
    lockfile = os.path.join(project_root, "pnpm-lock.yaml")
    if not package or fixed_version is None or not os.path.isfile(lockfile):
        return False

    try:
        with open(lockfile, encoding="utf-8") as file:
            versions = collect_package_versions(file.read()).get(package, set())
    except OSError as error:
        print(f"[dependabot] WARNING: could not inspect dev lockfile: {error}", file=sys.stderr)
        return False

    parsed_versions = [_semver_prefix(version) for version in versions]
    return bool(parsed_versions) and all(
        version is not None and version >= fixed_version for version in parsed_versions
    )


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


def _reportable_alerts(alerts: list[dict]) -> tuple[list[dict], list[str]]:
    """Normalize all alert records before remediation filtering loses context."""
    findings, missing = [], []
    if not isinstance(alerts, list):
        return [], ["dependabot_payload_not_array"]
    for index, alert in enumerate(alerts):
        if not isinstance(alert, dict) or any(not isinstance(alert.get(key) or {}, dict) for key in ("security_advisory", "security_vulnerability", "dependency")):
            missing.append(f"alert_{index}_malformed")
            continue
        if not isinstance((alert.get("dependency") or {}).get("package") or {}, dict):
            missing.append(f"alert_{index}_package_malformed")
            continue
        advisory = alert.get("security_advisory") or {}
        vulnerability = alert.get("security_vulnerability") or {}
        package = (alert.get("dependency") or {}).get("package") or {}
        ghsa_id = advisory.get("ghsa_id")
        name, ecosystem = package.get("name"), package.get("ecosystem")
        for key, value in (("ghsa_id", ghsa_id), ("package", name), ("ecosystem", ecosystem)):
            if not value:
                missing.append(f"alert_{index}_missing_{key}")
        severity = advisory.get("severity") or vulnerability.get("severity") or "unknown"
        if severity not in {"critical", "high", "medium", "low"}:
            missing.append(f"alert_{index}_severity_unavailable")
        findings.append({
            "vuln_id": ghsa_id, "aliases": [value for value in [advisory.get("cve_id")] if value],
            "severity": str(advisory.get("severity") or vulnerability.get("severity") or "unknown").lower(),
            "package": name or "unknown", "ecosystem": ecosystem or "unknown",
            "current_version": "unknown",
            "affected_version_range": vulnerability.get("vulnerable_version_range"),
            "remediation": {"dependabot_alert_numbers": [alert.get("number")]},
        })
    return findings, missing


def _build_alert_summary(alerts_to_dispatch: list[dict]) -> str:
    """
    Build the alert summary section for the claude prompt.
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
        # Empty first entry starts without leading newline; subsequent sections get one blank line separator
        prefix = "" if not lines else "\n"
        lines.append(f"{prefix}{sev.upper()}:")
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
    Collect Dependabot observations through the retained deterministic ledger adapter.
    """
    # Read env vars set by the shell script
    alerts_json_file = os.environ.get("ALERTS_JSON_FILE", "")
    tracking_file = os.environ.get("TRACKING_FILE_PATH", "")
    project_root = os.environ.get("PROJECT_ROOT", "")
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    summary_only = os.environ.get("SUMMARY_ONLY", "false").lower() == "true"

    if not tracking_file:
        print("[dependabot] ERROR: TRACKING_FILE_PATH not set.", file=sys.stderr)
        sys.exit(1)

    if not alerts_json_file:
        print("[dependabot] ERROR: ALERTS_JSON_FILE not set.", file=sys.stderr)
        sys.exit(1)

    # Read and parse alerts from temp file
    try:
        with open(alerts_json_file) as f:
            raw_alerts: list[dict] = json.load(f)
    except Exception as e:
        print(f"[dependabot] ERROR: Failed to decode/parse alerts: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[dependabot] Processing {len(raw_alerts)} raw alert(s)...")

    all_findings, missing = _reportable_alerts(raw_alerts)
    report_scan(
        project_root=project_root or os.getcwd(), source="dependabot", findings=all_findings,
        outcome="incomplete" if missing else ("findings" if all_findings else "no_new_findings"),
        subject_commit=_current_commit(project_root or os.getcwd()),
        coverage={"expected_and_completed_stages": {"dependabot_alert_payload": [1, 1]}, "sanitized_failure_codes": []},
        inventory={"raw_alerts": len(raw_alerts), "missing_required_data": missing},
        dry_run=dry_run, summary_only=summary_only,
    )

    if missing or summary_only or os.environ.get("SECURITY_REPORTING_COLLECTION_ONLY", "").lower() == "true":
        print(json.dumps({"source": "dependabot", "total_findings": len(all_findings), "missing_required_data": missing}))
        return

    # The deterministic collection/ledger path is the complete scan. Legacy
    # agent remediation and redispatch are retired (TASK-7543/TASK-8338).
    if dry_run:
        print("[dependabot] DRY RUN — no reporting state persisted.")
    print(json.dumps({"source": "dependabot", "total_findings": len(all_findings), "missing_required_data": missing}))


def _write_dependabot_report(
    tracking: dict,
    status: str,
    summary: str,
    dispatched: list[dict] | None = None,
) -> None:
    """Write a dependabot nightly report with security disclosure info."""
    processed = tracking.get("processed", [])
    severity_counts: dict[str, int] = {}
    unresolved = 0
    for item in processed:
        sev = item.get("severity", "unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        if not item.get("resolved_via_commit"):
            unresolved += 1

    details = {
        "total_tracked": len(processed),
        "unresolved": unresolved,
        "by_severity": severity_counts,
        "last_run": tracking.get("last_run", "unknown"),
    }

    # Security disclosure: include package update details for dispatched alerts
    security_disclosure = None
    if dispatched:
        packages_updated = []
        for alert in dispatched:
            packages_updated.append({
                "name": alert.get("package", "unknown"),
                "ghsa_id": alert.get("ghsa_id", "unknown"),
                "severity": alert.get("severity", "unknown"),
                "summary": alert.get("summary", ""),
                "used_in_project": True,  # Dependabot only alerts on used packages
                "user_risk": (
                    "high" if alert.get("severity") in ("critical", "high")
                    else "low"
                ),
            })
        security_disclosure = {
            "packages_updated": packages_updated,
            "risk_summary": (
                f"{len(dispatched)} package vulnerability alert(s) dispatched for fix. "
                f"Severity breakdown: {severity_counts}."
            ),
        }

    write_nightly_report(
        job="dependabot",
        status=status,
        summary=summary,
        details=details,
        security_disclosure=security_disclosure,
    )


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
