#!/usr/bin/env python3
"""Verify security reporting readiness and render private review artifacts.

Default status and proof rendering never send. Explicit --send-test performs
one approved labeled test, retaining its immutable payload and durable receipt.
Collection initialization records monitoring policy without changing schedulers.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys

from security_report_delivery import payload_hash, stable_notification_id
from security_reporting_runner import render_digest, accepted_test_receipt, _outbox_payload, _critical_payload, _deliver, _marker, _report, _store, latest_digest_end, reporting_directory
from security_reporting_schedule import UNITS, status


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_proof(fixtures: Path, output: Path) -> dict[str, object]:
    """Render only committed synthetic fixtures and bind the output with hashes."""
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    artifacts = []
    for fixture in sorted(fixtures.glob("*.json")):
        report = json.loads(fixture.read_text(encoding="utf-8"))
        rendered = _critical_payload(report["incident"], report.get("environment", "development")) if report.get("kind") == "critical" else render_digest(report)
        html = output / f"{fixture.stem}.html"
        mime = output / f"{fixture.stem}.eml"
        html.write_text(rendered["html"], encoding="utf-8")
        message = EmailMessage()
        message["Subject"] = rendered["subject"]
        message["To"] = "operator@example.invalid"
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(rendered["text"])
        message.add_alternative(rendered["html"], subtype="html")
        mime.write_bytes(message.as_bytes())
        artifacts.extend({"file": path.name, "sha256": _hash(path)} for path in (html, mime))
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps({"synthetic": True, "artifacts": artifacts}, indent=2, sort_keys=True), encoding="utf-8")
    return {"synthetic": True, "manifest": str(manifest), "artifacts": artifacts}


def _write_marker(directory: Path, marker: dict[str, object]) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".enabled-", suffix=".json")
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(json.dumps(marker, sort_keys=True))
    os.chmod(temporary, 0o600)
    Path(temporary).replace(directory / "enabled.json")


def prepare_test(*, directory: Path, now: str | None = None) -> dict[str, object]:
    """Freeze one current-data payload per UTC reporting day without sending."""
    cutoff = latest_digest_end(now)
    notification_id = stable_notification_id("test", "development", cutoff)
    existing = directory / "outbox" / f"{notification_id}.json"
    if existing.is_file():
        payload = json.loads(existing.read_text(encoding="utf-8"))["payload"]
    else:
        snapshot = _store(directory, dry_run=True).snapshot(now)
        if not snapshot.get("runs"):
            return {"state": "unavailable", "reason": "current_scan_history_required"}
        payload = render_digest(_report(snapshot))
        payload["subject"] = f"[Security TEST] {payload['subject']}"
        payload = _outbox_payload(directory, notification_id, payload, dry_run=False, kind="test", window_end=cutoff)
    return {"state": "prepared", "notification_id": notification_id, "payload_hash": payload_hash(payload), "window_end": cutoff, "payload": payload}


def send_test(*, directory: Path | None = None, now: str | None = None, sender=None) -> dict[str, object]:
    """Send only the frozen labeled current-data test; replay cannot alter its hash."""
    directory = directory or reporting_directory()
    prepared = prepare_test(directory=directory, now=now)
    if prepared["state"] != "prepared":
        return prepared
    payload = prepared.pop("payload")
    notification_id = prepared["notification_id"]
    state = _deliver(directory, notification_id, payload, dry_run=False, sender=sender, kind="test", window_end=prepared["window_end"])
    result = {**prepared, "state": state}
    if state == "accepted":
        marker = _marker(directory)
        if marker.get("test_notification_id") != notification_id:
            marker["test_accepted_at"] = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        marker.update({"test_receipt": "accepted", "current_data": True, "configured_destination": "container",
                       "test_notification_id": notification_id, "test_payload_hash": result["payload_hash"]})
        _write_marker(directory, marker)
    return result


def initialize_collection(directory: Path, *, now: str | None = None) -> dict[str, object]:
    """Initialize private collection with all scheduled monitoring held disabled."""
    from security_reporting import REPORT_SOURCES
    moment = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    store = _store(directory, dry_run=False)
    marker = _marker(directory)
    if not marker.get("collection_enabled"):
        for source in REPORT_SOURCES:
            store.set_schedule(source, enabled=False, effective_at=moment)
        marker.update({"collection_enabled": True, "collection_started_at": moment})
        _write_marker(directory, marker)
    return {"state": "collection_ready", "delivery_enabled": marker.get("enabled") is True, "schedulers_changed": False}


ADAPTER_FILES = tuple(Path(__file__).parent / name for name in (
    "_dependabot_helper.py", "_eu_vuln_helper.py", "_security_helper.py", "_opencode_utils.py",
    "security_scan_reporting.py", "security_reporting_runner.py", "security_reporting.py",
    "tests/test_security_scan_reporting.py",
))


def adapter_evidence_valid(directory: Path, *, files=None) -> bool:
    """Require passing offline adapter checks against the exact current sources."""
    try:
        evidence = json.loads((directory / "adapter-verification.json").read_text(encoding="utf-8"))
        expected = {str(path): _hash(path) for path in (ADAPTER_FILES if files is None else files)}
        return evidence.get("status") == "passed" and evidence.get("source_hashes") == expected
    except (OSError, ValueError, AttributeError):
        return False


def verify_adapters(directory: Path) -> dict[str, object]:
    """Run isolated no-agent/no-network scanner and notification policy regressions."""
    command = [sys.executable, "-m", "pytest", str(Path(__file__).parent / "tests/test_security_scan_reporting.py"), "-q", "--color=no"]
    before = {str(path): _hash(path) for path in ADAPTER_FILES}
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    after = {str(path): _hash(path) for path in ADAPTER_FILES}
    evidence = {"status": "passed" if result.returncode == 0 and before == after else "failed",
                "source_hashes": after, "command": command, "timestamp": datetime.now(timezone.utc).isoformat()}
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "adapter-verification.json"
    path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    # Test output is isolated synthetic evidence, never scanner data.
    (directory / "adapter-verification.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    return evidence


def _timer_active(unit: str) -> bool:
    result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit], capture_output=True, timeout=10, check=False)
    return result.returncode == 0


def check_cutover(directory: Path | None = None, *, timer_probe=None) -> dict[str, object]:
    directory = directory or reporting_directory()
    marker = _marker(directory)
    schedule = status(reporting_directory=directory)
    receipt_bound = bool(marker.get("test_notification_id") and marker.get("test_payload_hash") and marker.get("test_accepted_at"))
    checks = [
        {"id": "accepted_current_data_receipt", "passed": schedule["receipt_accepted"] and receipt_bound and accepted_test_receipt(directory)},
        {"id": "exact_reporting_timer_units", "passed": schedule["installed"]},
        {"id": "timers_enabled_after_receipt", "passed": schedule["enabled"]},
        {"id": "runtime_timers_active", "passed": all((timer_probe or _timer_active)(unit) for unit in UNITS)},
        {"id": "container_destination_configured", "passed": marker.get("configured_destination") == "container"},
        {"id": "generic_suppression_verified", "passed": adapter_evidence_valid(directory)},
        {"id": "scanner_adapter_verified", "passed": adapter_evidence_valid(directory)},
    ]
    return {"checks": checks, "cutover_ready": all(check["passed"] for check in checks)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("dev", "production"), default="dev")
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--prepare-test", action="store_true")
    parser.add_argument("--initialize-collection", action="store_true")
    parser.add_argument("--verify-adapters", action="store_true")
    parser.add_argument("--check-cutover", action="store_true")
    parser.add_argument("--render-proof", action="store_true")
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.env == "production":
        print(json.dumps({"state": "refused", "reason": "production verification is outside the development-host scope"}))
        return 2
    if args.render_proof:
        if not args.fixtures or not args.output:
            parser.error("--render-proof requires --fixtures and --output")
        print(json.dumps(render_proof(args.fixtures, args.output), sort_keys=True))
        return 0
    if args.verify_adapters:
        result = verify_adapters(reporting_directory())
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "passed" else 2
    if args.initialize_collection:
        print(json.dumps(initialize_collection(reporting_directory()), sort_keys=True))
        return 0
    if args.prepare_test:
        if not args.output:
            parser.error("--prepare-test requires private --output directory")
        prepared = prepare_test(directory=reporting_directory())
        if prepared["state"] == "prepared":
            args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
            payload = prepared.pop("payload")
            for extension, content in (("html", payload["html"]), ("txt", payload["text"])):
                path = args.output / f"security-test.{extension}"
                path.write_text(content, encoding="utf-8")
                path.chmod(0o600)
        print(json.dumps(prepared, sort_keys=True))
        return 0 if prepared["state"] == "prepared" else 2
    if args.send_test:
        result = send_test()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["state"] == "accepted" else 2
    if args.check_cutover:
        result = check_cutover()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["cutover_ready"] else 2
    print(json.dumps(status(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
