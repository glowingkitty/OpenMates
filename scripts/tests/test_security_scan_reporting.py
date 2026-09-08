"""Contracts for opt-in scanner persistence and critical delivery.

Temporary state and isolated environment variables protect operator data.
A subprocess guard forbids OpenCode launches even when a regression removes
a collection-mode early return. No test may invoke a real agent or send mail.
"""

# contract-test-file: infrastructure
from __future__ import annotations

import json
from pathlib import Path
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import security_scan_reporting as reporting


@pytest.fixture(autouse=True)
def isolated_reporting_environment(monkeypatch):
    """Never inherit operator state or launch OpenCode from offline regressions."""
    for name in ("SECURITY_REPORTING_DIR", "SECURITY_REPORTING_COLLECTION_ONLY", "SECURITY_REPORTING_SLOT", "CRON_SESSION_EMAILS_DISABLED", "DRY_RUN", "SUMMARY_ONLY"):
        monkeypatch.delenv(name, raising=False)
    original_popen = subprocess.Popen

    def guarded_popen(command, *args, **kwargs):
        executable = command[0] if isinstance(command, (list, tuple)) else command.split()[0]
        if Path(executable).name == "opencode":
            raise AssertionError("OpenCode subprocesses are forbidden in reporting tests")
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded_popen)


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_reporting_is_disabled_without_an_explicit_enabled_marker(tmp_path: Path) -> None:
    assert reporting.report_scan(
        project_root=tmp_path,
        source="eu_vulns",
        findings=[],
        outcome="no_new_findings",
        subject_commit="abc",
    ) is None
    assert not (tmp_path / "logs" / "security-reporting").exists()


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_enabled_reporting_uses_configured_directory_and_preserves_all_findings(tmp_path: Path, monkeypatch) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "enabled.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    monkeypatch.setenv("SECURITY_REPORTING_DIR", str(report_dir))

    run_id = reporting.report_scan(
        project_root=tmp_path,
        source="eu_vulns",
        findings=[{"vuln_id": "GHSA-low", "package": "lib", "ecosystem": "npm", "severity": "low"}],
        outcome="findings",
        subject_commit="abc",
        coverage={"expected_and_completed_stages": {"osv": [2, 1]}, "sanitized_failure_codes": ["osv_batch_failed"]},
        inventory={"expected_queries": 2, "completed_queries": 1, "missing_required_data": []},
    )

    assert run_id
    snapshot = reporting.ReportingStore(report_dir / "reporting.sqlite3").snapshot()
    assert snapshot["run_counts"]["findings"] == 1
    assert snapshot["finding_counts"]["by_severity"]["low"] == 1


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_dry_and_summary_modes_never_write_even_when_enabled(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "enabled.json").write_text('{"enabled":true}', encoding="utf-8")

    assert reporting.report_scan(project_root=tmp_path, source="dependabot", findings=[], outcome="no_new_findings", subject_commit="abc", dry_run=True) is None
    assert reporting.report_scan(project_root=tmp_path, source="dependabot", findings=[], outcome="no_new_findings", subject_commit="abc", summary_only=True) is None
    assert not (report_dir / "reporting.sqlite3").exists()


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_critical_delivery_runs_after_a_successful_persist(monkeypatch, tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "enabled.json").write_text('{"enabled":true}', encoding="utf-8")
    monkeypatch.setenv("SECURITY_REPORTING_DIR", str(report_dir))
    calls = []
    monkeypatch.setattr(reporting.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))

    reporting.report_scan(project_root=tmp_path, source="dependabot", findings=[], outcome="no_new_findings", subject_commit="abc")

    assert calls
    assert Path(calls[0][0][1]).name == "security_reporting_runner.py"
    assert calls[0][0][2] == "critical"


# Reporting coverage: security-reporting.processing.deterministic
# contract-test: infrastructure
def test_collection_only_records_without_transport_or_agent_launch(tmp_path, monkeypatch):
    directory = tmp_path / "reports"
    directory.mkdir()
    (directory / "enabled.json").write_text('{"collection_enabled":true,"enabled":false}')
    monkeypatch.setenv("SECURITY_REPORTING_DIR", str(directory))
    monkeypatch.setattr(reporting.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch transport")))
    run_id = reporting.report_scan(project_root=tmp_path, source="dependabot", findings=[], outcome="no_new_findings", subject_commit="abc")
    assert run_id
    assert reporting.ReportingStore(directory / "reporting.sqlite3").snapshot()["run_counts"]["no_new_findings"] == 1


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_explicit_original_slot_survives_retry(tmp_path, monkeypatch):
    directory = tmp_path / "reports"
    directory.mkdir()
    (directory / "enabled.json").write_text('{"collection_enabled":true}')
    monkeypatch.setenv("SECURITY_REPORTING_DIR", str(directory))
    monkeypatch.setenv("SECURITY_REPORTING_SLOT", "2026-09-07T10:30:00Z")
    reporting.report_scan(project_root=tmp_path, source="dependabot", findings=[], outcome="no_new_findings", subject_commit="abc")
    runs = reporting.ReportingStore(directory / "reporting.sqlite3").snapshot()["runs"]
    assert runs[0]["coverage"]["scheduled_slot"] == "2026-09-07T10:30:00Z"


# Reporting coverage: security-reporting.processing.deterministic
# contract-test: infrastructure
def test_collection_only_dependabot_never_changes_remediation_state(tmp_path, monkeypatch):
    from scripts import _dependabot_helper as helper
    alerts = tmp_path / "alerts.json"
    alerts.write_text('[{"number":1,"security_advisory":{"ghsa_id":"GHSA-aaaa-bbbb-cccc","severity":"critical"},"dependency":{"package":{"name":"demo","ecosystem":"npm"}},"security_vulnerability":{}}]')
    monkeypatch.setenv("SECURITY_REPORTING_COLLECTION_ONLY", "true")
    monkeypatch.setenv("ALERTS_JSON_FILE", str(alerts))
    monkeypatch.setenv("TRACKING_FILE_PATH", str(tmp_path / "tracking.json"))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    calls = []
    monkeypatch.setattr(helper, "report_scan", lambda **kw: calls.append(kw))
    monkeypatch.setattr(helper, "_load_tracking", lambda *a: (_ for _ in ()).throw(AssertionError("remediation state accessed")))
    helper.process_alerts()
    assert len(calls) == 1
    assert not (tmp_path / "tracking.json").exists()


# Reporting coverage: security-reporting.notifications.daily-not-per-scan
# contract-test: infrastructure


# Reporting coverage: security-reporting.processing.deterministic
# contract-test: infrastructure
def test_collection_only_eu_clean_scan_does_not_write_remediation(tmp_path, monkeypatch):
    from scripts import _eu_vuln_helper as helper
    monkeypatch.setenv("SECURITY_REPORTING_COLLECTION_ONLY", "true")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TRACKING_FILE_PATH", str(tmp_path / "tracking.json"))
    monkeypatch.setattr(helper, "_collect_all_dependencies", lambda root: [{"name":"demo","version":"1","ecosystem":"npm"}])
    monkeypatch.setattr(helper, "_query_osv_batch", lambda deps: ([], {"expected_and_completed_stages":{"osv_queries":[1,1]},"sanitized_failure_codes":[]}))
    monkeypatch.setattr(helper, "report_scan", lambda **kw: "isolated-run")
    helper.check_vulns()
    assert not (tmp_path / "tracking.json").exists()


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_structured_snapshot_ingestion_is_dated_idempotent_and_no_send(tmp_path, monkeypatch):
    directory = tmp_path / "reports"
    directory.mkdir()
    (directory / "enabled.json").write_text('{"collection_enabled":true}')
    monkeypatch.setenv("SECURITY_REPORTING_DIR", str(directory))
    snapshot = tmp_path / "audit.json"
    snapshot.write_text(json.dumps({"ran_at":"2026-09-06T02:30:00Z", "details":{"security_reporting":{"subject_commit":"abc", "outcome":"findings", "findings":[{"vuln_id":"AUDIT-1","ecosystem":"repository","package":"backend","severity":"high"}]}}}))
    for _ in range(2):
        reporting.ingest_snapshot(project_root=tmp_path, source="security_audit", path=snapshot)
    result = reporting.ReportingStore(directory / "reporting.sqlite3").snapshot("2026-09-07T00:00:00Z")
    assert result["run_counts"]["findings"] == 1
    assert result["sources"]["security_audit"]["observed_at"] == "2026-09-06T02:30:00Z"
    assert result["finding_counts"]["open"] == 1


# Reporting coverage: security-reporting.processing.deterministic
# contract-test: infrastructure
def test_audit_collection_mode_never_invokes_agent_or_changes_state(tmp_path, monkeypatch):
    from scripts import _security_helper as helper
    monkeypatch.setenv("SECURITY_REPORTING_COLLECTION_ONLY", "true")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(helper, "_load_state", lambda *a: (_ for _ in ()).throw(AssertionError("audit state accessed")))
    helper.run_audit()
    helper.run_redteam()


# Reporting coverage: security-reporting.processing.deterministic
# contract-test: infrastructure


# Reporting coverage: security-reporting.coverage.no-false-clean
# contract-test: infrastructure
def test_malformed_dependabot_record_preserves_other_confirmed_findings():
    from scripts import _dependabot_helper as helper
    good = {"security_advisory":{"ghsa_id":"GHSA-aaaa-bbbb-cccc","severity":"high"},"dependency":{"package":{"name":"demo","ecosystem":"npm"}}}
    findings, missing = helper._reportable_alerts([good, None, {"security_advisory":"broken"}])
    assert findings[0]["vuln_id"] == "GHSA-aaaa-bbbb-cccc"
    assert missing
