#!/usr/bin/env python3
"""
Deterministically audit the operational-monitoring implementation contract.

The default audit checks required source, compose, alert, and self-host omission
guards. ``--privacy`` additionally checks that report models and templates keep
private fields out of operator artifacts and delivery receipts.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "backend/core/api/app/services/operational_monitoring.py"
TASK = ROOT / "backend/core/api/app/tasks/operational_monitoring_tasks.py"
CELERY_CONFIG = ROOT / "backend/core/api/app/tasks/celery_config.py"
ALERT_RULES = ROOT / "backend/core/monitoring/prometheus/alert_rules.yml"
ALERTMANAGER = ROOT / "backend/core/monitoring/alertmanager/alertmanager.yml"
PROMETHEUS = ROOT / "backend/core/monitoring/prometheus/prometheus.yml"
SOURCE_COMPOSE = ROOT / "backend/core/docker-compose.yml"
SELFHOST_COMPOSE = ROOT / "backend/core/docker-compose.selfhost.yml"
SELFHOST_TEMPLATE = ROOT / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml"
SERVER_HEALTH = ROOT / "frontend/packages/openmates-cli/src/serverHealth.ts"
SERVER = ROOT / "frontend/packages/openmates-cli/src/server.ts"
SERVER_PLANNING = ROOT / "frontend/packages/openmates-cli/src/serverPlanning.ts"
VERIFIER = ROOT / "scripts/verify_operational_monitoring.py"

FORBIDDEN_PRIVATE_FIELDS = {
    "user",
    "encrypted",
    "payment",
    "webhook",
    "email",
    "content",
    "stack",
    "destination",
    "token",
}


def _require_file(path: Path, failures: list[str]) -> str:
    if not path.exists():
        failures.append(f"missing required file: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def run_audit(*, privacy: bool) -> list[str]:
    failures: list[str] = []
    service = _require_file(SERVICE, failures)
    task = _require_file(TASK, failures)
    celery_config = _require_file(CELERY_CONFIG, failures)
    alert_rules = _require_file(ALERT_RULES, failures)
    alertmanager = _require_file(ALERTMANAGER, failures)
    prometheus = _require_file(PROMETHEUS, failures)
    source_compose = _require_file(SOURCE_COMPOSE, failures)
    selfhost_compose = _require_file(SELFHOST_COMPOSE, failures)
    selfhost_template = _require_file(SELFHOST_TEMPLATE, failures)
    server_health = _require_file(SERVER_HEALTH, failures)
    server = _require_file(SERVER, failures)
    server_planning = _require_file(SERVER_PLANNING, failures)
    verifier = _require_file(VERIFIER, failures)

    required_markers = {
        "service snapshot builder": (service, "build_operational_snapshot"),
        "service deterministic renderer": (service, "render_operational_report_png"),
        "scheduled digest task": (task, "send_operational_monitoring_digest"),
        "node scrape target": (prometheus, 'job_name: "node"'),
        "disk warning rule": (alert_rules, "HostDiskSpaceWarning"),
        "disk critical rule": (alert_rules, "HostDiskSpaceCritical"),
        "stale report rule": (alert_rules, "OperationalReportStale"),
        "absent report metric guard": (alert_rules, "unless on(environment) operational_report_last_success_timestamp_seconds"),
        "direct urgent receiver": (alertmanager, "discord_configs:"),
        "source node exporter": (source_compose, "node-exporter:"),
        "self-host node exporter": (selfhost_compose, "node-exporter:"),
        "published self-host node exporter": (selfhost_template, "node-exporter:"),
        "host report freshness": (server_health, "evaluateOperationalReportFreshness"),
        "self-host activation": (server_health, "planOperationalMonitoring"),
        "configured digest channels": (server_health, "--channel ${selectedChannels}"),
        "schedule-gated freshness state": (server, "if (operationalPlan.scheduleEnabled)"),
        "host delivery retries": (server_health, "for (let attempt = 1; attempt <= 3; attempt += 1)"),
        "host API-down incident": (server, 'failureClass: "critical_availability"'),
        "digest delivery retries": (service, "deliver_with_retries"),
        "official billing readiness inventory": (server_planning, "billing.stripe_account_read"),
        "real delivery verifier": (verifier, '"monitoring", "digest"'),
        "environment-specific self-host Discord": (service, "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_SELF_HOST"),
        "environment-specific production urgent Discord": (source_compose, "DISCORD_WEBHOOK_URGENT_PRODUCTION"),
        "environment-specific development urgent Discord": (source_compose, "DISCORD_WEBHOOK_URGENT_DEVELOPMENT"),
    }
    for label, (content, marker) in required_markers.items():
        if marker not in content:
            failures.append(f"missing {label}: {marker}")
    if "operational-monitoring-digest-daily" in celery_config:
        failures.append("operational digest must have exactly one scheduler; Celery Beat schedule is forbidden")

    combined_selfhost = "\n".join((selfhost_compose, selfhost_template, server_health))
    if "self_host" not in combined_selfhost:
        failures.append("self-host monitoring mode is not explicit")
    if "billing: not_applicable" in combined_selfhost.lower():
        failures.append("self-host monitoring must omit billing instead of rendering not_applicable")
    for label, compose in (
        ("source", source_compose),
        ("self-host", selfhost_compose),
        ("published self-host", selfhost_template),
    ):
        if "--store_container_labels=false" not in compose or "--whitelisted_container_labels=com.docker.compose.project" not in compose:
            failures.append(f"{label} cAdvisor must suppress labels except the compose project label")

    if privacy:
        for field in sorted(FORBIDDEN_PRIVATE_FIELDS):
            if f'"{field}"' not in service and f"'{field}'" not in service:
                failures.append(f"privacy denylist missing field: {field}")
        if "forbidden private field" not in service.lower():
            failures.append("service does not reject forbidden private fields")
        if "report_sha256" not in service or "sanitized_failure_class" not in service:
            failures.append("delivery receipt schema is missing redacted integrity fields")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--privacy", action="store_true")
    args = parser.parse_args()
    failures = run_audit(privacy=args.privacy)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: operational monitoring contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
