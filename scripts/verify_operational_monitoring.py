#!/usr/bin/env python3
"""
Run the real packaged CLI operational-report delivery path against Docker.

The verifier builds the local CLI, requests an explicitly labeled test report,
checks independent channel receipts, and stores only redacted evidence. It does
not inspect secrets or treat process exit alone as proof of delivery.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
EVIDENCE_DIR = ROOT / "test-results" / "operational-monitoring"
TARGET_ENVIRONMENTS = {"dev": "development", "self-host": "self_host", "prod": "production"}
VALID_CHANNELS = {"email", "discord"}
DRILL_DEFINITIONS = {
    "api-down": {
        "alertname": "APIDown",
        "severity": "critical",
        "summary": "[DEV DRILL] API unavailable",
        "description": "Synthetic dev drill; the API was not stopped.",
        "integrations": {"discord", "webhook"},
    },
    "stale-report": {
        "alertname": "OperationalReportStale",
        "severity": "critical",
        "summary": "[DEV DRILL] Operational report stale",
        "description": "Synthetic dev drill; report state was not changed.",
        "integrations": {"discord", "webhook"},
    },
    "disk-warning": {
        "alertname": "HostDiskSpaceWarning",
        "severity": "warning",
        "summary": "[DEV DRILL] Host disk warning",
        "description": "Synthetic dev drill; disk usage was not changed.",
        "integrations": {"webhook"},
    },
}
ALERTMANAGER_URL = "http://localhost:9093"
DRILL_TIMEOUT_SECONDS = 30
DRILL_ACTIVE_SECONDS = 120


def _parse_output(stdout: str) -> dict:
    decoder = json.JSONDecoder()
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("command") == "monitoring digest":
            return value
    raise ValueError("CLI did not return a structured operational-report result")


def _receipts_accepted(result: dict, *, channels: set[str], environment: str, returncode: int) -> bool:
    receipts = result.get("receipts") or []
    return (
        result.get("deliveryState") == "accepted"
        and {receipt.get("channel") for receipt in receipts} == channels
        and all(receipt.get("environment") == environment for receipt in receipts)
        and all(receipt.get("state") == "accepted" for receipt in receipts)
        and returncode == 0
    )


def _build_drill_alert(drill: str, drill_id: str, *, resolved: bool, now: datetime | None = None) -> dict:
    definition = DRILL_DEFINITIONS[drill]
    current = now or datetime.now(timezone.utc)
    starts_at = current - timedelta(seconds=DRILL_ACTIVE_SECONDS) if resolved else current
    ends_at = current if resolved else current + timedelta(seconds=DRILL_ACTIVE_SECONDS)
    return {
        "labels": {
            "alertname": definition["alertname"],
            "severity": definition["severity"],
            "environment": "development",
            "drill": "true",
            "drill_id": drill_id,
        },
        "annotations": {
            "summary": definition["summary"],
            "description": definition["description"],
        },
        "startsAt": starts_at.isoformat(),
        "endsAt": ends_at.isoformat(),
        "generatorURL": "openmates://operational-monitoring/dev-drill",
    }


def _active_drill_count(alerts: list[dict], drill_id: str) -> int:
    return sum(
        alert.get("labels", {}).get("drill") == "true"
        and alert.get("labels", {}).get("drill_id") == drill_id
        and alert.get("status", {}).get("state") == "active"
        for alert in alerts
    )


def _drill_receivers(groups: list[dict], drill_id: str) -> set[str]:
    return {
        group.get("receiver", {}).get("name")
        for group in groups
        if any(alert.get("labels", {}).get("drill_id") == drill_id for alert in group.get("alerts", []))
        and group.get("receiver", {}).get("name")
    }


def _is_development_environment(value: str) -> bool:
    return value.strip().lower() in {"dev", "development"}


def _metric_value(metrics: str, metric: str, integration: str) -> float:
    pattern = rf'^{re.escape(metric)}\{{[^}}]*integration="{re.escape(integration)}"[^}}]*\}}\s+([0-9.eE+-]+)$'
    match = re.search(pattern, metrics, re.MULTILINE)
    return float(match.group(1)) if match else 0


def _alertmanager_request(path: str, *, payload: list[dict] | None = None) -> str:
    command = ["docker", "exec", "alertmanager", "wget", "-qO-"]
    if payload is not None:
        command.extend(["--header", "Content-Type: application/json", "--post-data", json.dumps(payload)])
    command.append(f"{ALERTMANAGER_URL}{path}")
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=15)
    if completed.returncode != 0:
        raise RuntimeError(f"Alertmanager request failed for {path}")
    return completed.stdout


def _wait_for(description: str, predicate, *, timeout: int = DRILL_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {description}")


def _notification_counters(integrations: set[str]) -> dict[str, dict[str, float]]:
    metrics = _alertmanager_request("/metrics")
    return {
        integration: {
            "requests": _metric_value(metrics, "alertmanager_notification_requests_total", integration),
            "completed": _metric_value(metrics, "alertmanager_notification_latency_seconds_count", integration),
            "failed": _metric_value(metrics, "alertmanager_notification_requests_failed_total", integration),
        }
        for integration in integrations
    }


def _delivery_delta_accepted(
    before: dict[str, dict[str, float]], after: dict[str, dict[str, float]],
) -> bool:
    return all(
        after[integration]["requests"] == counters["requests"] + 1
        and after[integration]["completed"] == counters["completed"] + 1
        and after[integration]["failed"] == counters["failed"]
        for integration, counters in before.items()
    )


def _delivery_samples_accepted(
    before: dict[str, dict[str, float]], samples: list[dict[str, dict[str, float]]],
) -> bool:
    return len(samples) >= 2 and all(_delivery_delta_accepted(before, sample) for sample in samples)


def _active_alerts() -> list[dict]:
    return json.loads(_alertmanager_request("/api/v2/alerts"))


def _has_foreign_active_alerts(drill_id: str) -> bool:
    return any(
        alert.get("status", {}).get("state") == "active"
        and alert.get("labels", {}).get("drill_id") != drill_id
        for alert in _active_alerts()
    )


def _wait_for_notification_delivery(
    description: str, before: dict[str, dict[str, float]], drill_id: str,
) -> None:
    deadline = time.monotonic() + DRILL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _has_foreign_active_alerts(drill_id):
            raise RuntimeError("A non-drill alert became active; receiver evidence is not isolated")
        first = _notification_counters(set(before))
        if _delivery_delta_accepted(before, first):
            time.sleep(2)
            if _has_foreign_active_alerts(drill_id):
                raise RuntimeError("A non-drill alert became active; receiver evidence is not isolated")
            second = _notification_counters(set(before))
            if _delivery_samples_accepted(before, [first, second]):
                return
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {description}")


def _webhook_log_has_receipt(log: str, drill_id: str, status: str) -> bool:
    return any(f"status={status}" in line and drill_id in line for line in log.splitlines())


def _api_webhook_receipt_observed(drill_id: str, status: str, since: datetime) -> bool:
    completed = subprocess.run(
        ["docker", "logs", "--since", since.isoformat(), "api"],
        cwd=ROOT, text=True, capture_output=True, check=False, timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError("Could not inspect the redacted API webhook receipt log")
    return _webhook_log_has_receipt(f"{completed.stdout}\n{completed.stderr}", drill_id, status)


def _restore_drill(drill: str, drill_id: str) -> None:
    restored_by_post = False
    for attempt in range(3):
        try:
            _alertmanager_request("/api/v2/alerts", payload=[_build_drill_alert(drill, drill_id, resolved=True)])
            restored_by_post = True
            break
        except (RuntimeError, subprocess.TimeoutExpired):
            if attempt < 2:
                time.sleep(1)
    timeout = DRILL_TIMEOUT_SECONDS if restored_by_post else DRILL_ACTIVE_SECONDS + DRILL_TIMEOUT_SECONDS
    _wait_for(
        f"{drill} restoration",
        lambda: _active_drill_count(_active_alerts(), drill_id) == 0,
        timeout=timeout,
    )


def _run_drill(drill: str, run_id: str) -> dict:
    definition = DRILL_DEFINITIONS[drill]
    drill_id = f"{run_id}-{drill}"
    integrations = definition["integrations"]
    expected_receivers = {"api-webhook", "urgent-discord"} if definition["severity"] == "critical" else {"api-webhook"}
    firing_counters = _notification_counters(integrations)
    firing_alert = _build_drill_alert(drill, drill_id, resolved=False)
    started_at = datetime.now(timezone.utc)
    failure: Exception | None = None
    recovery_counters: dict[str, dict[str, float]] | None = None
    try:
        _alertmanager_request("/api/v2/alerts", payload=[firing_alert])
        _alertmanager_request("/api/v2/alerts", payload=[firing_alert])
        _wait_for(
            f"one deduplicated {drill} alert",
            lambda: _active_drill_count(_active_alerts(), drill_id) == 1,
        )
        _wait_for(
            f"{drill} receiver routing",
            lambda: _drill_receivers(
                json.loads(_alertmanager_request("/api/v2/alerts/groups")), drill_id,
            ) == expected_receivers,
        )
        _wait_for_notification_delivery(f"{drill} firing notifications", firing_counters, drill_id)
        _wait_for(
            f"{drill} correlated webhook receipt",
            lambda: _api_webhook_receipt_observed(drill_id, "firing", started_at),
        )
        recovery_counters = _notification_counters(integrations)
    except Exception as error:
        failure = error
    finally:
        try:
            _restore_drill(drill, drill_id)
        except Exception as cleanup_error:
            if failure:
                raise RuntimeError(f"{drill} failed and automatic restoration could not be confirmed") from cleanup_error
            raise
    if failure:
        raise failure
    if recovery_counters is None:
        raise RuntimeError(f"{drill} firing evidence was incomplete")
    _wait_for_notification_delivery(f"{drill} recovery notifications", recovery_counters, drill_id)
    _wait_for(
        f"{drill} correlated recovery receipt",
        lambda: _api_webhook_receipt_observed(drill_id, "resolved", started_at),
    )
    return {
        "drill": drill,
        "alertname": definition["alertname"],
        "deduplicated_active_count": 1,
        "firing_delivery": "accepted",
        "restored": True,
        "recovery_delivery": "accepted",
        "integrations": sorted(integrations),
        "receivers": sorted(expected_receivers),
        "correlated_webhook_receipts": ["firing", "resolved"],
    }


def _run_drills(drills: list[str], evidence_dir: Path) -> int:
    environment_check = subprocess.run(
        [
            "docker", "exec", "api", "python", "-c",
            "import os; print(os.getenv('SERVER_ENVIRONMENT', ''))",
        ],
        cwd=ROOT, text=True, capture_output=True, check=False, timeout=15,
    )
    if environment_check.returncode != 0 or not _is_development_environment(environment_check.stdout):
        raise RuntimeError("controlled drills require a verified development API runtime")
    if any(alert.get("status", {}).get("state") == "active" for alert in _active_alerts()):
        raise RuntimeError("controlled drills require Alertmanager to have no pre-existing active alerts")
    status = json.loads(_alertmanager_request("/api/v2/status"))
    rendered_config = status.get("config", {}).get("original", "")
    if not re.search(r'drill:\s*["\u0027]?true["\u0027]?', rendered_config) or "drill_id" not in rendered_config:
        raise RuntimeError("Alertmanager is not running the bounded dev drill routes")
    run_id = f"drill-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    results = [_run_drill(drill, run_id) for drill in drills]
    evidence = {
        "target": "dev",
        "environment": "development",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "accepted": True,
        "drills": results,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"drill-dev-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {evidence_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=sorted(TARGET_ENVIRONMENTS), required=True)
    parser.add_argument("--window-hours", type=int, choices=[24], default=24)
    parser.add_argument("--send", default="email,discord")
    parser.add_argument("--role", choices=["core", "upload", "preview"], default="core")
    parser.add_argument("--path", type=Path, default=ROOT)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--drill")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()

    if args.target == "prod" and not args.allow_production:
        parser.error("production delivery requires --allow-production after explicit rollout approval")
    channels = {item.strip() for item in args.send.split(",") if item.strip()}
    if not channels or channels - VALID_CHANNELS:
        parser.error("--send must contain email, discord, or both")
    if args.drill:
        drills = [item.strip() for item in args.drill.split(",") if item.strip()]
        invalid_drills = set(drills) - set(DRILL_DEFINITIONS)
        if invalid_drills:
            parser.error(f"unsupported drills: {', '.join(sorted(invalid_drills))}")
        if args.target != "dev":
            parser.error("controlled drills are dev-only")
        if not args.restore:
            parser.error("controlled drills require --restore")
        return _run_drills(drills, args.evidence_dir)

    if not args.skip_build:
        subprocess.run(["npm", "run", "build"], cwd=CLI_DIR, check=True)
    command = [
        "node", str(CLI_DIR / "dist" / "cli.js"), "server", "monitoring", "digest",
        "--path", str(args.path.resolve()), "--role", args.role,
        "--channel", ",".join(sorted(channels)), "--test", "--json",
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    try:
        result = _parse_output(completed.stdout)
    except ValueError as error:
        print(f"FAIL: {error}")
        return 1

    expected_environment = TARGET_ENVIRONMENTS[args.target]
    receipts = result.get("receipts") or []
    accepted = _receipts_accepted(
        result, channels=channels, environment=expected_environment, returncode=completed.returncode,
    )
    evidence = {
        "target": args.target,
        "environment": expected_environment,
        "window_hours": args.window_hours,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "accepted": accepted,
        "report_id": result.get("reportId"),
        "report_sha256": result.get("reportSha256"),
        "receipts": receipts,
    }
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = args.evidence_dir / f"verification-{args.target}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if accepted else 'FAIL'}: {evidence_path}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
