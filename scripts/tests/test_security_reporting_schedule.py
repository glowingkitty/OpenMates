#!/usr/bin/env python3
"""Isolated contracts for safe security reporting systemd scheduling.

All mutating systemctl calls are injected and unit files live in temporary
directories. Receipt and source-evidence checks prove cutover readiness
without activating any host scheduler or sending operator notifications.
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
    spec = importlib.util.spec_from_file_location("security_reporting_schedule", ROOT / "scripts" / "security_reporting_schedule.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# contract-test: infrastructure
def test_install_writes_exactly_one_digest_and_one_retry_timer_without_enabling(tmp_path):
    schedule = load_module()
    commands = []

    result = schedule.install(unit_directory=tmp_path / "units", reporting_directory=tmp_path / "reporting", runner=lambda command: commands.append(command) or 0)

    assert result["installed"] is True
    assert commands == [["systemctl", "--user", "daemon-reload"]]
    digest_timer = (tmp_path / "units" / "security-reporting-digest.timer").read_text(encoding="utf-8")
    digest_service = (tmp_path / "units" / "security-reporting-digest.service").read_text(encoding="utf-8")
    retry_timer = (tmp_path / "units" / "security-reporting-retry.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 08:30:00 UTC" in digest_timer
    assert "OnUnitActiveSec=15min" in retry_timer
    assert "WorkingDirectory=" in digest_service
    assert "Environment=PROJECT_ROOT=" in digest_service
    marker = json.loads((tmp_path / "reporting" / "enabled.json").read_text(encoding="utf-8"))
    assert marker == {"timer_installed": True}


# contract-test: infrastructure
def test_failed_daemon_reload_does_not_mark_installation(tmp_path):
    schedule = load_module()

    try:
        schedule.install(unit_directory=tmp_path / "units", reporting_directory=tmp_path / "reporting", runner=lambda _command: 1)
    except RuntimeError as error:
        assert "daemon-reload" in str(error)
    else:
        raise AssertionError("daemon reload failure must stop installation")
    assert not (tmp_path / "reporting" / "enabled.json").exists()


# contract-test: infrastructure
def test_enable_requires_accepted_current_data_receipt_and_installed_units(tmp_path):
    schedule = load_module()
    reporting = tmp_path / "reporting"
    reporting.mkdir()
    (reporting / "enabled.json").write_text(json.dumps({"test_receipt": "accepted", "current_data": True, "configured_destination": "container"}), encoding="utf-8")

    try:
        schedule.enable(unit_directory=tmp_path / "units", reporting_directory=reporting, runner=lambda _command: 0)
    except RuntimeError as error:
        assert "timer installation" in str(error)
    else:
        raise AssertionError("enable must fail before installation")

    schedule.install(unit_directory=tmp_path / "units", reporting_directory=reporting, runner=lambda _command: 0)
    # Isolated transport acceptance must write a real ledger row and outbox payload.
    from security_report_delivery import SendResult
    from verify_security_reporting import send_test
    from security_reporting import ReportingStore
    from datetime import datetime, timezone
    store = ReportingStore(reporting / "reporting.sqlite3")
    store.record_run("dependabot", [], "no_new_findings", "abc")
    send_test(directory=reporting, now=datetime.now(timezone.utc).isoformat(), sender=lambda _request: SendResult.accepted("isolated-test"))
    commands = []
    result = schedule.enable(unit_directory=tmp_path / "units", reporting_directory=reporting, runner=lambda command: commands.append(command) or 0)

    assert result["enabled"] is True
    assert commands == [["systemctl", "--user", "enable", "--now", "security-reporting-digest.timer", "security-reporting-retry.timer"]]
    marker = json.loads((reporting / "enabled.json").read_text(encoding="utf-8"))
    assert marker["enabled"] is True
    assert marker["generic_email_suppression"] is True
    assert marker["configured_destination"] == "container"


# contract-test: infrastructure
def test_status_and_disable_do_not_touch_unrelated_cron(tmp_path):
    schedule = load_module()
    reporting = tmp_path / "reporting"
    reporting.mkdir()
    (reporting / "enabled.json").write_text(json.dumps({"enabled": True, "timer_installed": True}), encoding="utf-8")
    commands = []

    assert schedule.status(unit_directory=tmp_path / "units", reporting_directory=reporting)["enabled"] is True
    schedule.disable(reporting_directory=reporting, runner=lambda command: commands.append(command) or 0)

    assert commands == [["systemctl", "--user", "disable", "--now", "security-reporting-digest.timer", "security-reporting-retry.timer"]]
    marker = json.loads((reporting / "enabled.json").read_text(encoding="utf-8"))
    assert marker["enabled"] is False
    assert marker["generic_email_suppression"] is False


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_marker_claim_alone_is_not_an_accepted_receipt(tmp_path):
    schedule = load_module()
    (tmp_path / "enabled.json").write_text(json.dumps({"test_receipt":"accepted", "current_data":True, "test_notification_id":"fake", "test_payload_hash":"fake", "test_accepted_at":"2026-09-07T10:00:00Z"}))
    assert schedule.status(unit_directory=tmp_path / "units", reporting_directory=tmp_path)["receipt_accepted"] is False


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_cutover_rejects_inactive_runtime_even_if_marker_claims_enabled(tmp_path, monkeypatch):
    import verify_security_reporting as verifier
    (tmp_path / "enabled.json").write_text(json.dumps({"enabled":True,"configured_destination":"container","test_notification_id":"test","test_payload_hash":"hash","test_accepted_at":"date","generic_suppression_verified":True,"scanner_adapter_verified":True}))
    monkeypatch.setattr(verifier, "status", lambda **kw: {"receipt_accepted":True,"installed":True,"enabled":True})
    result = verifier.check_cutover(tmp_path, timer_probe=lambda unit: False)
    assert result["cutover_ready"] is False
    assert any(check["id"] == "runtime_timers_active" and not check["passed"] for check in result["checks"])


# Reporting coverage: security-reporting.delivery.durable-observable
# contract-test: infrastructure
def test_adapter_evidence_is_invalidated_when_source_changes(tmp_path):
    import verify_security_reporting as verifier
    source = tmp_path / "adapter.py"
    source.write_text("version = 1")
    (tmp_path / "adapter-verification.json").write_text(json.dumps({"status":"passed","source_hashes":{str(source):verifier._hash(source)}}))
    assert verifier.adapter_evidence_valid(tmp_path, files=[source])
    source.write_text("version = 2")
    assert not verifier.adapter_evidence_valid(tmp_path, files=[source])
