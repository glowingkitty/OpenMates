#!/usr/bin/env python3
"""Isolated contracts for the host-local security reporting runner.

Tests use temporary ledgers and injected transports, never live email.
They cover immutable payloads, readiness, critical failures and synthetic
production artifacts; see docs/architecture/infrastructure/security-reporting.md.
"""

# contract-test-file: infrastructure
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def load_module():
    spec = importlib.util.spec_from_file_location("security_reporting_runner", ROOT / "scripts" / "security_reporting_runner.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_security_reporting", ROOT / "scripts" / "verify_security_reporting.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def marker(directory: Path, **values):
    directory.mkdir()
    (directory / "enabled.json").write_text(json.dumps({"enabled": True, "configured_destination": "container", **values}), encoding="utf-8")


def snapshot():
    return {
        "environment": "development", "window_start": "2026-09-05T08:30:00Z", "window_end": "2026-09-06T08:30:00Z",
        "runs": [{"source": "eu_vulns", "subject_commit": "abc123", "completed_at": "2026-09-06T08:00:00Z", "outcome": "findings", "coverage": {}}],
        "coverage": {"eu_vulns": {"expected": 24, "completed": 24}},
        "findings": [{"finding_id": "f1", "package": "demo", "severity": "critical", "state": "open", "aliases": ["CVE-2026-0001"], "first_seen_at": "2026-09-05T09:00:00Z", "last_seen_at": "2026-09-06T08:00:00Z", "sources": ["eu_vulns"]}],
        "new": [], "open": [], "resolved": [], "sources": {}, "subject_commit": "abc123", "history": {"status": "complete"},
    }


# contract-test: infrastructure
def test_digest_uses_latest_0830_window_and_persists_immutable_payload(tmp_path, monkeypatch):
    runner = load_module()
    directory = tmp_path / "reporting"
    marker(directory)
    monkeypatch.setattr(runner, "_store", lambda *_args, **_kwargs: type("Store", (), {"snapshot": lambda *_args: snapshot()})())
    calls = []
    monkeypatch.setattr(runner, "deliver_notification", lambda **kwargs: calls.append(kwargs) or type("Result", (), {"state": "accepted"})())

    result = runner.run("digest", directory=directory, now="2026-09-06T10:00:00Z")

    assert result["state"] == "accepted"
    assert result["window_end"] == "2026-09-06T08:30:00Z"
    assert len(calls) == 1
    payload_path = directory / "outbox" / f"{result['notification_id']}.json"
    assert json.loads(payload_path.read_text(encoding="utf-8"))["payload"] == calls[0]["payload"]
    assert calls[0]["recipient"] == "configured_destination"


# contract-test: infrastructure
def test_critical_renders_distinct_alert_and_marks_only_accepted_incidents(tmp_path, monkeypatch):
    runner = load_module()
    directory = tmp_path / "reporting"
    marker(directory)
    store = type("Store", (), {"pending_critical": lambda *_args: [{"incident_id": "i1", "package": "demo", "severity": "critical", "opened_at": "2026-09-06T08:00:00Z"}], "snapshot": lambda *_args: {"findings": []}, "mark_critical_notified": lambda *_args: True})()
    monkeypatch.setattr(runner, "_store", lambda *_args, **_kwargs: store)
    sent = []
    monkeypatch.setattr(runner, "deliver_notification", lambda **kwargs: sent.append(kwargs) or type("Result", (), {"state": "accepted"})())

    result = runner.run("critical", directory=directory)

    assert result["count"] == 1
    assert "CRITICAL alert" in sent[0]["payload"]["subject"]
    assert "digest" not in sent[0]["payload"]["subject"].lower()


# contract-test: infrastructure
def test_critical_marks_only_provider_accepted_and_bounds_safe_details(tmp_path, monkeypatch):
    runner = load_module()
    directory = tmp_path / "reporting"
    marker(directory)
    marks = []
    incident = {"incident_id": "i1", "package": "<demo>", "ecosystem": "pypi", "version": "1.2.3", "aliases": ["CVE-2026-0001"], "opened_at": "2026-09-06T08:00:00Z"}
    store = type("Store", (), {"environment": "development", "pending_critical": lambda *_args: [incident], "snapshot": lambda *_args: {"findings": []}, "mark_critical_notified": lambda *_args: marks.append("i1")})()
    monkeypatch.setattr(runner, "_store", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(runner, "deliver_notification", lambda **_kwargs: type("Result", (), {"state": "queued"})())

    runner.run("critical", directory=directory)

    assert marks == []
    payload = runner._critical_payload(incident, "development")
    assert "<demo>" not in payload["html"]
    assert "CVE-2026-0001" in payload["html"]
    assert "<demo>" not in payload["subject"]


# contract-test: infrastructure
def test_dry_run_does_not_create_outbox_or_delivery_state(tmp_path, monkeypatch):
    runner = load_module()
    directory = tmp_path / "reporting"
    marker(directory)
    monkeypatch.setattr(runner, "_store", lambda *_args, **_kwargs: type("Store", (), {"snapshot": lambda *_args: snapshot()})())
    monkeypatch.setattr(runner, "deliver_notification", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not send")))

    result = runner.run("digest", directory=directory, dry_run=True, now="2026-09-06T10:00:00Z")

    assert result["state"] == "dry_run"
    assert not (directory / "outbox").exists()


# contract-test: infrastructure
def test_retry_reuses_private_outbox_payload_without_rebuilding(tmp_path, monkeypatch):
    runner = load_module()
    directory = tmp_path / "reporting"
    marker(directory)
    outbox = directory / "outbox"
    outbox.mkdir()
    (outbox / "notification.json").write_text(json.dumps({"notification_id": "notification", "payload": {"subject": "saved", "text": "saved", "html": "<p>saved</p>"}}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "deliver_notification", lambda **kwargs: calls.append(kwargs) or type("Result", (), {"state": "accepted"})())

    result = runner.run("retry", directory=directory)

    assert result["state"] == "complete"
    assert result["accepted"] == 1
    assert calls[0]["payload"]["subject"] == "saved"


# contract-test: infrastructure
def test_retry_skips_accepted_and_never_reports_failed_as_complete(tmp_path, monkeypatch):
    runner = load_module()
    directory = tmp_path / "reporting"
    marker(directory)
    outbox = directory / "outbox"
    outbox.mkdir()
    for name in ("accepted", "failed"):
        (outbox / f"{name}.json").write_text(json.dumps({"notification_id": name, "payload": {"subject": name, "text": name, "html": name}}), encoding="utf-8")
    monkeypatch.setattr(runner, "_receipt_state", lambda _directory, notification_id: notification_id)
    monkeypatch.setattr(runner, "deliver_notification", lambda **_kwargs: type("Result", (), {"state": "failed"})())

    result = runner.run("retry", directory=directory)

    assert result["state"] == "failed"
    assert result["accepted"] == 0
    assert result["failed"] == 1


# contract-test: infrastructure
def test_send_test_persists_accepted_current_data_receipt_without_enabled_marker(tmp_path, monkeypatch):
    verifier = load_verifier()
    directory = tmp_path / "reporting"
    fake_store = type("Store", (), {"snapshot": lambda *_args: snapshot()})()
    monkeypatch.setattr(verifier, "_store", lambda *_args, **_kwargs: fake_store)
    monkeypatch.setattr(verifier, "_deliver", lambda *_args, **_kwargs: "accepted")

    result = verifier.send_test(directory=directory, now="2026-09-06T10:00:00Z", sender=object())

    marker_data = json.loads((directory / "enabled.json").read_text(encoding="utf-8"))
    assert result["state"] == "accepted"
    assert marker_data.get("enabled") is not True
    assert marker_data["configured_destination"] == "container"
    assert marker_data["test_payload_hash"] == result["payload_hash"]


# contract-test: infrastructure
def test_render_proof_writes_real_mime_for_incomplete_and_critical_fixtures(tmp_path):
    verifier = load_verifier()

    result = verifier.render_proof(ROOT / "scripts/tests/fixtures/security-reporting", tmp_path / "proof")

    assert result["synthetic"] is True
    assert (tmp_path / "proof" / "digest-incomplete.eml").read_bytes().startswith(b"Subject:")
    assert b"Critical security alert" in (tmp_path / "proof" / "critical-alert.eml").read_bytes()


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_empty_history_cannot_authorize_current_data_test(tmp_path):
    verifier = load_verifier()
    calls = []
    result = verifier.send_test(directory=tmp_path, sender=lambda request: calls.append(request))
    assert result["state"] == "unavailable"
    assert calls == []
    assert not (tmp_path / "enabled.json").exists()


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_prepared_test_replay_preserves_original_payload_hash(tmp_path):
    verifier = load_verifier()
    from security_reporting import ReportingStore
    from security_report_delivery import SendResult
    store = ReportingStore(tmp_path / "reporting.sqlite3")
    store.record_run("dependabot", [], "no_new_findings", "abc")
    calls = []
    def sender(request):
        calls.append(request)
        return SendResult.accepted("isolated-test")
    first = verifier.send_test(directory=tmp_path, sender=sender)
    store.record_run("dependabot", [], "failed", "def")
    second = verifier.send_test(directory=tmp_path, sender=sender)
    assert first["payload_hash"] == second["payload_hash"]
    assert len(calls) == 1
    assert verifier.accepted_test_receipt(tmp_path)


# Reporting coverage: security-reporting.digest.actionable-content
# contract-test: infrastructure
def test_digest_exposes_partial_history_paused_scans_and_failure_codes():
    runner = load_module()
    report = snapshot()
    report["history"] = {"status":"partial", "enabled_at":"2026-09-06T08:00:00Z"}
    report["coverage"] = {"eu_vulns":{"expected":0,"completed":0,"missing":0,"schedule_status":"disabled","failure_codes":["osv_batch_failed"]}}
    report["open"] = [{"severity":"high","package":"demo","advisory":"CVE-2026-1234","current_versions":["1.0"],"remediation":{"status":"pending"}}]
    rendered = runner.render_digest(report)
    for text in ("partial", "disabled", "osv_batch_failed", "pending", "1.0"):
        assert text in rendered["text"]
        assert text in rendered["html"]


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_critical_transport_failure_is_not_reported_complete(tmp_path, monkeypatch):
    runner = load_module()
    directory = tmp_path / "reporting"
    marker(directory)
    store = type("Store", (), {"pending_critical": lambda *_args: [{"incident_id":"one","finding_id":"one"}], "snapshot": lambda *_args: {"findings":[]}})()
    monkeypatch.setattr(runner, "_store", lambda *a, **kw: store)
    monkeypatch.setattr(runner, "_deliver", lambda *a, **kw: "failed")
    assert runner.run("critical", directory=directory)["state"] == "failed"
