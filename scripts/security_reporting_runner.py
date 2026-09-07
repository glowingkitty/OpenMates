#!/usr/bin/env python3
"""Run deterministic security digest, critical alert, and retry delivery.

This host process never reads recipient configuration or credentials.  It keeps
the rendered payload private and delegates recipient resolution and transport to
the existing API container sender.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from security_digest import render_security_report, safe_advisory_link
from security_report_delivery import (
    container_email_sender,
    deliver_notification,
    stable_notification_id,
    payload_hash,
)
from security_reporting import ReportingStore, read_reporting_config as _marker


DESTINATION_SENTINEL = "configured_destination"


def reporting_directory() -> Path:
    return Path(os.environ.get("SECURITY_REPORTING_DIR") or Path(os.environ.get("PROJECT_ROOT", ".")) / "logs" / "security-reporting")


def _store(directory: Path, *, dry_run: bool) -> ReportingStore:
    return ReportingStore(directory / "reporting.sqlite3", dry_run=dry_run)


def _timestamp(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("now must include a timezone")
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def latest_digest_end(now: str | None = None) -> str:
    current = _timestamp(now)
    cutoff = datetime.combine(current.date(), time(8, 30), tzinfo=timezone.utc)
    if current < cutoff:
        cutoff -= timedelta(days=1)
    return cutoff.isoformat().replace("+00:00", "Z")


def _report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Adapt the stable store snapshot directly to the shared email renderer."""
    return {key: snapshot[key] for key in ("environment", "window_start", "window_end", "subject_commit", "coverage", "sources", "new", "open", "resolved", "history")}


def _bounded(value: object, limit: int = 160) -> str:
    return " ".join(str(value or "unknown").split())[:limit] or "unknown"


def _subject_text(value: object, limit: int = 160) -> str:
    return _bounded(value, limit).replace("<", "").replace(">", "")


def render_digest(report: dict[str, Any]) -> dict[str, str]:
    """Attach collector health and remediation detail to the deployed safe renderer.

    Preserve the delivery slice's escaping and complete severity totals. Only
    allowlisted operational fields enter this bounded appendix.
    """
    rendered = render_security_report(report)
    history = report.get("history") or {}
    lines = [f"History: {_bounded(history.get('status', 'unavailable'))}"]
    if history.get("enabled_at"):
        lines.append(f"Collection began: {_bounded(history['enabled_at'])}; earlier history was not observed")
    for source, coverage in sorted((report.get("coverage") or {}).items()):
        if coverage.get("schedule_status"):
            lines.append(f"{_bounded(source)} monitoring: {_bounded(coverage['schedule_status'])}")
        for code in coverage.get("failure_codes", [])[:10]:
            lines.append(f"{_bounded(source)} failure: {_bounded(code)}")
    details = [item for group in ("new", "open", "resolved") for item in report.get(group, [])]
    for item in details[:20]:
        remediation = item.get("remediation") or {}
        status = remediation.get("status", "not recorded")
        versions = ", ".join(str(value) for value in item.get("current_versions", []))
        lines.append(f"{_bounded(item.get('package'))}: versions {_bounded(versions)}; remediation {_bounded(status)}")
    rendered["text"] += "\n\nCollection and remediation details:\n" + "\n".join(lines)
    appendix = "<h2>Collection and remediation details</h2><ul>" + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>"
    rendered["html"] = rendered["html"].replace("</body>", appendix + "</body>")
    return rendered


def _critical_payload(incident: dict[str, Any], environment: str) -> dict[str, str]:
    package = _bounded(incident.get("package"))
    ecosystem, version = _bounded(incident.get("ecosystem")), _bounded(incident.get("current_versions") or incident.get("version"))
    advisory = _bounded((incident.get("aliases") or [incident.get("advisory") or "unknown"])[0])
    opened_at = _bounded(incident.get("opened_at"))
    subject = f"[Security] CRITICAL alert: {_subject_text(package)} ({_subject_text(environment, 80)})"
    link = safe_advisory_link(advisory)
    advisory_html = f'<a href="{escape(link, quote=True)}">{escape(advisory)}</a>' if link else escape(advisory)
    text = f"Critical security incident\nEnvironment: {_bounded(environment)}\nPackage: {package}\nEcosystem: {ecosystem}\nVersion: {version}\nAdvisory: {advisory}\nOpened: {opened_at} UTC"
    html = f"<!doctype html><html><body><h1>Critical security alert</h1><p>Environment: {escape(_bounded(environment))}<br>Package: {escape(package)}<br>Ecosystem: {escape(ecosystem)}<br>Version: {escape(version)}<br>Advisory: {advisory_html}<br>Opened: {escape(opened_at)} UTC</p></body></html>"
    return {"subject": subject, "text": text, "html": html}


def _outbox_payload(directory: Path, notification_id: str, payload: dict[str, str], *, dry_run: bool, kind: str, window_end: str | None = None) -> dict[str, str]:
    path = directory / "outbox" / f"{notification_id}.json"
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        return stored["payload"]
    if dry_run:
        return payload
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps({"notification_id": notification_id, "payload": payload, "kind": kind, "window_end": window_end}, sort_keys=True, separators=(",", ":"))
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".outbox-", text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(encoded)
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
        else:
            os.unlink(temporary)
            return payload
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def _deliver(directory: Path, notification_id: str, payload: dict[str, str], *, dry_run: bool, sender: Any = None, kind: str = "critical", window_end: str | None = None) -> str:
    persisted = _outbox_payload(directory, notification_id, payload, dry_run=dry_run, kind=kind, window_end=window_end)
    if dry_run:
        return "dry_run"
    outcome = deliver_notification(ledger_path=directory / "delivery.sqlite3", notification_id=notification_id, payload=persisted,
                                   recipient=DESTINATION_SENTINEL, sender=sender or container_email_sender(), provider_supports_idempotency=False)
    return outcome.state


def _receipt_state(directory: Path, notification_id: str) -> str | None:
    path = directory / "delivery.sqlite3"
    if not path.exists():
        return None
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT state FROM delivery_receipts WHERE notification_id=?", (notification_id,)).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def accepted_test_receipt(directory: Path, *, now: str | None = None) -> bool:
    """Check a recent accepted test against the durable receipt and immutable payload.

    Marker assertions alone cannot authorize a live notification cutover.
    Neither queued nor unknown transport states are acceptance evidence.
    """
    marker = _marker(directory)
    notification_id = marker.get("test_notification_id")
    if not isinstance(notification_id, str) or not notification_id.startswith("security-report-") or "/" in notification_id:
        return False
    path = directory / "delivery.sqlite3"
    if not path.is_file():
        return False
    try:
        accepted_at = _timestamp(marker.get("test_accepted_at"))
        age = _timestamp(now) - accepted_at
        if not timedelta(0) <= age <= timedelta(hours=36):
            return False
        stored = json.loads((directory / "outbox" / f"{notification_id}.json").read_text(encoding="utf-8"))
        expected_id = stable_notification_id("test", "development", stored["window_end"])
        if stored["kind"] != "test" or expected_id != notification_id or not stored["payload"]["subject"].startswith("[Security TEST]"):
            return False
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT state, payload_hash FROM delivery_receipts WHERE notification_id=?", (notification_id,)).fetchone()
        finally:
            connection.close()
        return bool(row and row[0] == "accepted" and row[1] == marker.get("test_payload_hash") == payload_hash(stored["payload"]))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return False


def _retry_outbox(directory: Path, *, dry_run: bool) -> dict[str, int]:
    """Retry stored immutable payloads; never regenerate a changed report."""
    results = {"accepted": 0, "failed": 0, "unknown": 0, "unavailable": 0, "skipped": 0}
    for path in sorted((directory / "outbox").glob("*.json")):
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            notification_id, payload = stored["notification_id"], stored["payload"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            continue
        if _receipt_state(directory, str(notification_id)) in {"accepted", "queued"}:
            results["skipped"] += 1
            continue
        if stored.get("kind") == "digest" and stored.get("window_end") != latest_digest_end():
            results["skipped"] += 1
            continue
        state = _deliver(directory, str(notification_id), payload, dry_run=dry_run, kind=str(stored.get("kind") or "critical"), window_end=stored.get("window_end"))
        results[state if state in results else "unknown"] += 1
    return results


def run(command: str, *, directory: Path | None = None, dry_run: bool = False, now: str | None = None) -> dict[str, Any]:
    directory = directory or reporting_directory()
    marker = _marker(directory)
    if not marker.get("enabled"):
        return {"state": "disabled", "count": 0}
    if not marker.get("configured_destination"):
        return {"state": "unavailable", "reason": "container destination is not configured", "count": 0}
    if command == "retry":
        result = _retry_outbox(directory, dry_run=dry_run)
        state = "dry_run" if dry_run else ("failed" if result["failed"] else ("unknown" if result["unknown"] else ("unavailable" if result["unavailable"] else "complete")))
        return {"state": state, **result}
    store = _store(directory, dry_run=dry_run)
    if command == "digest":
        end = latest_digest_end(now)
        report = _report(store.snapshot(end))
        notification_id = stable_notification_id("digest", report["environment"], report["window_end"])
        state = _deliver(directory, notification_id, render_digest(report), dry_run=dry_run, kind="digest", window_end=report["window_end"])
        return {"state": state, "notification_id": notification_id, "window_end": end, "count": 1}
    if command == "critical":
        incidents = store.pending_critical()
        current = {item["finding_id"]: item for item in store.snapshot().get("findings", []) if isinstance(item, dict) and item.get("finding_id")}
        delivered = 0
        outcomes = []
        for incident in incidents:
            environment = getattr(store, "environment", "development")
            notification_id = stable_notification_id("critical", environment, incident["incident_id"])
            state = _deliver(directory, notification_id, _critical_payload({**current.get(incident.get("finding_id"), {}), **incident}, environment), dry_run=dry_run, kind="critical")
            outcomes.append(state)
            if state == "accepted":
                store.mark_critical_notified(incident["incident_id"])
            delivered += 1
        outcome = next((state for state in ("failed", "unknown", "unavailable", "queued") if state in outcomes), "complete")
        return {"state": "dry_run" if dry_run else outcome, "count": delivered}
    raise ValueError(f"unsupported command: {command}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("digest", "critical", "retry"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now")
    args = parser.parse_args()
    result = run(args.command, dry_run=args.dry_run, now=args.now)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["state"] in {"failed", "unknown", "unavailable"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
