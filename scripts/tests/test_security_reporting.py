"""Contracts for the durable, deterministic security reporting ledger.

The store is host-local and receives only structured scanner observations.
These tests use temporary SQLite databases and never contact scanners or email.
They cover canonical lifecycle, truthful coverage, and critical incidents.
"""

# contract-test-file: infrastructure
from __future__ import annotations

import sys
from pathlib import Path
import os
import sqlite3
import stat

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_reporting import ReportingStore


def finding(**overrides):
    value = {
        "package": "sample-lib",
        "ecosystem": "pypi",
        "current_version": "1.0.0",
        "vuln_id": "GHSA-example",
        "aliases": ["CVE-example"],
        "severity": "high",
    }
    value.update(overrides)
    return value


# Reporting coverage: security-reporting.findings.canonical-lifecycle
# contract-test: infrastructure
def test_aliases_merge_only_for_the_same_environment_ecosystem_and_package(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3", environment="development")
    store.record_run(
        "dependabot", [finding()], "findings", "commit-a", completed_at="2026-09-05T10:00:00Z"
    )
    store.record_run(
        "eu_vulns",
        [finding(vuln_id="CVE-example", aliases=["GHSA-example"], current_version="1.0.1")],
        "findings",
        "commit-b",
        completed_at="2026-09-05T11:00:00Z",
    )
    store.record_run(
        "eu_vulns",
        [finding(package="other-lib", vuln_id="CVE-example", aliases=["GHSA-example"])],
        "findings",
        "commit-c",
        completed_at="2026-09-05T11:30:00Z",
    )

    snapshot = store.snapshot("2026-09-06T00:00:00Z")
    assert snapshot["finding_counts"]["open"] == 2
    merged = next(item for item in snapshot["findings"] if item["package"] == "sample-lib")
    assert merged["aliases"] == ["CVE-EXAMPLE", "GHSA-EXAMPLE"]
    assert merged["sources"] == ["dependabot", "eu_vulns"]
    assert merged["current_versions"] == ["1.0.0", "1.0.1"]


# Reporting coverage: security-reporting.findings.canonical-lifecycle,security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_resolution_requires_positive_verification_and_remediation_is_durable(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3")
    store.record_run("dependabot", [finding(remediation={"status": "dispatched"})], "findings", "a", "2026-09-05T10:00:00Z")
    store.record_run("dependabot", [finding(state="resolved")], "no_new_findings", "b", "2026-09-05T11:00:00Z")
    assert store.snapshot()["finding_counts"]["open"] == 1

    store.record_run(
        "dependabot",
        [finding(state="resolved", resolution_evidence=resolution("c", "2026-09-05T12:35:00Z"))],
        "no_new_findings",
        "c",
        completed_at="2026-09-05T12:35:00Z",
    )
    resolved = store.snapshot("2026-09-06T00:00:00Z")["findings"][0]
    assert resolved["state"] == "resolved"
    assert resolved["remediation"] == {"status": "dispatched"}
    assert resolved["resolution_evidence"]["subject_commit"] == "c"


# Reporting coverage: security-reporting.alerts.new-critical-only
# contract-test: infrastructure
def test_critical_escalation_is_deduplicated_and_verified_recurrence_opens_new_incident(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3", enabled_at="2026-09-05T00:00:00Z")
    store.record_run("dependabot", [finding(severity="high")], "findings", "a")
    store.record_run("eu_vulns", [finding(severity="critical")], "findings", "b")
    first = store.pending_critical()
    assert len(first) == 1
    assert store.mark_critical_notified(first[0]["incident_id"])
    store.record_run("dependabot", [finding(severity="critical")], "findings", "c")
    assert store.pending_critical() == []

    store.record_run(
        "dependabot",
        [finding(state="resolved", resolution_evidence=resolution("d"))],
        "no_new_findings",
        "d",
    )
    store.record_run("dependabot", [finding(severity="critical")], "findings", "e")
    recurrence = store.pending_critical()
    assert len(recurrence) == 1
    assert recurrence[0]["incident_id"] != first[0]["incident_id"]


# Reporting coverage: security-reporting.coverage.no-false-clean,security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_run_history_and_snapshot_keep_unknowns_and_truthful_coverage(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3", enabled_at="2026-09-05T00:00:00Z")
    store.record_run(
        "eu_vulns",
        [finding(severity=None)],
        "incomplete",
        "a",
        completed_at="2026-09-05T10:00:00Z",
        coverage={"expected_and_completed_stages": {"osv": [3, 2]}, "sanitized_failure_codes": ["batch_failed"]},
    )
    store.record_run(
        "eu_vulns", [], "failed", "b", completed_at="2026-09-05T11:00:00Z",
        coverage={"expected_and_completed_stages": {"osv": [3, 0]}, "sanitized_failure_codes": ["network"]},
    )

    snapshot = store.snapshot("2026-09-06T00:00:00Z")
    assert snapshot["run_counts"] == {"failed": 1, "incomplete": 1}
    assert snapshot["coverage"]["eu_vulns"]["expected"] == 24
    assert snapshot["coverage"]["eu_vulns"]["completed"] == 0
    assert snapshot["finding_counts"]["by_severity"]["unknown"] == 1
    assert len(snapshot["runs"]) == 2


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_dry_run_never_creates_or_mutates_a_database(tmp_path):
    database = tmp_path / "reporting.sqlite3"
    store = ReportingStore(database, dry_run=True)
    store.record_run("dependabot", [finding(severity="critical")], "findings", "a")
    assert not database.exists()
    assert store.pending_critical() == []


def resolution(subject_commit, verified_at="2026-09-05T12:35:00Z"):
    return {
        "type": "current_inventory",
        "complete": True,
        "all_instances_outside_affected_ranges": True,
        "subject_commit": subject_commit,
        "verified_at": verified_at,
    }


# Reporting coverage: security-reporting.findings.canonical-lifecycle
# contract-test: infrastructure
def test_missing_advisory_identifiers_never_merge_and_unverified_resolution_stays_open(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3")
    store.record_run("dependabot", [finding(vuln_id=None, aliases=[], current_version="1.0.0")], "findings", "a")
    store.record_run("dependabot", [finding(vuln_id=None, aliases=[], current_version="2.0.0")], "findings", "b")
    assert store.snapshot()["finding_counts"]["open"] == 2

    verified_store = ReportingStore(tmp_path / "verified.sqlite3")
    verified_store.record_run("dependabot", [finding()], "findings", "a")
    verified_store.record_run(
        "dependabot", [finding(state="resolved", resolution_evidence={"verified": True})], "no_new_findings", "c"
    )

    snapshot = verified_store.snapshot()
    assert snapshot["finding_counts"]["open"] == 1
    assert snapshot["findings"][0]["state"] == "open"


# Reporting coverage: security-reporting.findings.canonical-lifecycle
# contract-test: infrastructure
def test_alias_bridge_preserves_earliest_first_seen_and_latest_last_seen(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3")
    store.record_run("dependabot", [finding(vuln_id="GHSA-a", aliases=[])], "findings", "a", "2026-09-05T10:00:00Z")
    store.record_run("eu_vulns", [finding(vuln_id="CVE-a", aliases=[])], "findings", "b", "2026-09-05T11:00:00Z")
    store.record_run("dependabot", [finding(vuln_id="GHSA-a", aliases=["CVE-a"])], "findings", "c", "2026-09-05T09:00:00Z")

    merged = store.snapshot("2026-09-06T00:00:00Z")["findings"]
    assert len(merged) == 1
    assert merged[0]["first_seen_at"] == "2026-09-05T09:00:00Z"
    assert merged[0]["last_seen_at"] == "2026-09-05T11:00:00Z"


# Reporting coverage: security-reporting.findings.canonical-lifecycle
# contract-test: infrastructure
def test_duplicate_aliases_in_one_run_coalesce_to_one_observation(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3")
    store.record_run(
        "dependabot",
        [finding(vuln_id="GHSA-a", aliases=["CVE-a"]), finding(vuln_id="CVE-a", aliases=["GHSA-a"])],
        "findings",
        "a",
    )
    snapshot = store.snapshot()
    assert snapshot["finding_counts"]["open"] == 1
    assert snapshot["findings"][0]["sources"] == ["dependabot"]


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_private_permissions_and_schema_version_are_checked_before_use(tmp_path):
    database = tmp_path / "private" / "reporting.sqlite3"
    ReportingStore(database)
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700

    os.chmod(database, 0o644)
    with pytest.raises(PermissionError):
        ReportingStore(database)

    os.chmod(database, 0o600)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE schema_version SET version=999")
    with pytest.raises(ValueError, match="schema version"):
        ReportingStore(database)


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_pruning_keeps_open_and_pending_critical_history(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3")
    store.record_run("dependabot", [finding(vuln_id="GHSA-resolved", aliases=[])], "findings", "a", "2026-07-01T10:00:00Z")
    store.record_run(
        "dependabot", [finding(vuln_id="GHSA-resolved", aliases=[], state="resolved", resolution_evidence=resolution("b", "2026-07-02T10:00:00Z"))],
        "no_new_findings", "b", "2026-07-02T10:00:00Z",
    )
    store.record_run("dependabot", [finding(vuln_id="GHSA-open", aliases=[], severity="critical")], "findings", "c", "2026-07-01T11:00:00Z")
    store.record_run("security_audit", [], "no_new_findings", "audit", "2026-07-03T02:30:00Z", inventory={"structured": True})

    assert store.prune_completed_history("2026-09-05T00:00:00Z") == 2
    assert store.pending_critical()[0]["finding_id"]
    assert len(store.snapshot("2026-07-02T11:00:00Z")["runs"]) == 1
    assert store.snapshot("2026-09-05T00:00:00Z")["sources"]["security_audit"]["status"] == "stale"


# Reporting coverage: security-reporting.findings.canonical-lifecycle,security-reporting.digest.actionable-content
# contract-test: infrastructure
def test_snapshot_is_historical_and_renderer_ready_with_same_window_resolution(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3", enabled_at="2026-09-04T00:00:00Z")
    store.record_run("dependabot", [finding(vuln_id="GHSA-prior", aliases=[])], "findings", "prior", "2026-09-04T10:30:00Z")
    store.record_run("dependabot", [finding(vuln_id="GHSA-day", aliases=[])], "findings", "new", "2026-09-05T10:30:00Z")
    store.record_run(
        "dependabot", [finding(vuln_id="GHSA-day", aliases=[], state="resolved", resolution_evidence=resolution("fixed", "2026-09-05T12:30:00Z"))],
        "no_new_findings", "fixed", "2026-09-05T12:30:00Z",
    )
    # This later recurrence must not affect the historical 2026-09-05 report.
    store.record_run("dependabot", [finding(vuln_id="GHSA-day", aliases=[], severity="critical")], "findings", "future", "2026-09-06T10:30:00Z")

    report = store.snapshot("2026-09-06T00:00:00Z")
    assert report["subject_commit"] == "fixed"
    assert [item["advisory"] for item in report["new"]] == ["GHSA-DAY"]
    assert [item["advisory"] for item in report["resolved"]] == ["GHSA-DAY"]
    assert [item["advisory"] for item in report["open"]] == ["GHSA-PRIOR"]
    assert report["new"][0].keys() >= {"advisory", "package", "severity", "current_versions", "remediation"}
    assert report["history"]["status"] == "complete"


# Reporting coverage: security-reporting.coverage.no-false-clean,security-reporting.digest.actionable-content
# contract-test: infrastructure
def test_snapshot_uses_scheduled_slots_and_includes_latest_structured_audit_freshness(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3", enabled_at="2026-09-05T00:00:00Z")
    slot = "2026-09-05T10:30:00Z"
    store.record_run("dependabot", [], "failed", "failed", "2026-09-05T10:31:00Z", coverage={"scheduled_slot": slot})
    store.record_run("dependabot", [], "no_new_findings", "retry", "2026-09-05T10:40:00Z", coverage={"scheduled_slot": slot})
    store.record_run("security_audit", [], "no_new_findings", "audit", "2026-09-02T02:30:00Z", inventory={"structured": True})

    report = store.snapshot("2026-09-06T00:00:00Z")
    assert report["coverage"]["dependabot"] == {"expected": 24, "completed": 1, "missing": 23, "failure_codes": []}
    assert report["coverage"]["eu_vulns"]["expected"] == 24
    assert report["sources"]["security_audit"] == {"status": "available", "observed_at": "2026-09-02T02:30:00Z"}
    assert report["sources"]["redteam"]["status"] == "unavailable"


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_duplicate_run_id_is_idempotent_only_for_identical_payload(tmp_path):
    store = ReportingStore(tmp_path / "reporting.sqlite3")
    store.record_run("dependabot", [], "no_new_findings", "a", "2026-09-05T10:30:00Z", run_id="run-1")
    assert store.record_run("dependabot", [], "no_new_findings", "a", "2026-09-05T10:30:00Z", run_id="run-1") == "run-1"
    with pytest.raises(ValueError, match="payload conflict"):
        store.record_run("dependabot", [], "failed", "a", "2026-09-05T10:30:00Z", run_id="run-1")


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_slots_include_partial_first_hour_and_only_one_audit_slot():
    assert ReportingStore._scheduled_slots("dependabot", "2026-09-05T10:15:00Z", "2026-09-05T11:00:00Z") == ["2026-09-05T10:30:00Z"]
    assert ReportingStore._scheduled_slots("security_audit", "2026-09-04T00:00:00Z", "2026-09-05T00:00:00Z") == ["2026-09-04T02:30:00Z"]


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_paused_schedule_has_no_expected_slots_and_reports_pause(tmp_path):
    store = ReportingStore(tmp_path / "state.sqlite3", enabled_at="2026-09-05T00:00:00Z")
    store.set_schedule("dependabot", enabled=False, effective_at="2026-09-05T12:00:00Z")
    result = store.snapshot("2026-09-06T00:00:00Z")["coverage"]["dependabot"]
    assert result["expected"] == 12
    assert result["schedule_status"] == "disabled"


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_read_only_snapshot_does_not_chmod_parent(tmp_path):
    directory = tmp_path / "state"
    store = ReportingStore(directory / "state.sqlite3")
    directory.chmod(0o750)
    ReportingStore(store.path, read_only=True).snapshot()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o750


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_unscheduled_failed_scan_remains_visible_while_monitoring_is_paused(tmp_path):
    store = ReportingStore(tmp_path / "state.sqlite3", enabled_at="2026-09-05T00:00:00Z")
    store.set_schedule("eu_vulns", enabled=False, effective_at="2026-09-05T00:00:00Z")
    store.record_run("eu_vulns", [], "failed", "abc", "2026-09-05T10:36:00Z", coverage={"sanitized_failure_codes":["osv_batch_failed"]})
    coverage = store.snapshot("2026-09-06T00:00:00Z")["coverage"]["eu_vulns"]
    assert coverage["expected"] == 0
    assert coverage["failure_codes"] == ["osv_batch_failed"]


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_old_dependency_scan_is_stale_not_current_coverage(tmp_path):
    store = ReportingStore(tmp_path / "state.sqlite3")
    store.record_run("dependabot", [], "no_new_findings", "abc", "2026-09-05T10:30:00Z")
    assert store.snapshot("2026-09-06T00:00:00Z")["sources"]["dependabot"]["status"] == "stale"
