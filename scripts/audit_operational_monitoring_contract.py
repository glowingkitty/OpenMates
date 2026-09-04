#!/usr/bin/env python3
"""
Deterministically audit the operational-monitoring implementation contract.

The default audit checks required source, compose, alert, and self-host omission
guards. ``--privacy`` additionally checks that report models and templates keep
private fields out of operator artifacts and delivery receipts.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "backend/core/api/app/services/operational_monitoring.py"
TASK = ROOT / "backend/core/api/app/tasks/operational_monitoring_tasks.py"
EMAIL_TEMPLATE = ROOT / "backend/core/api/templates/email/operational_monitoring_digest.mjml"
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
PAYMENTS = ROOT / "backend/core/api/app/routes/payments.py"
APPROVE_BANK_TRANSFER = ROOT / "backend/scripts/approve_bank_transfer.py"
PURCHASE_SETTLEMENT_SCHEMA = ROOT / "backend/core/directus/schemas/credit_purchase_settlements.yml"
PURCHASE_SETTLEMENT_SERVICE = ROOT / "backend/core/api/app/services/purchase_settlement_ledger.py"
PAYMENT_READINESS = ROOT / "backend/core/api/app/services/payment_readiness.py"
DEGRADED_REPORT = ROOT / "backend/core/api/app/services/degraded_services_report.py"
STRIPE_AUDIT = ROOT / "scripts/stripe_audit.py"

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
    email_template = _require_file(EMAIL_TEMPLATE, failures)
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
    payments = _require_file(PAYMENTS, failures)
    approve_bank_transfer = _require_file(APPROVE_BANK_TRANSFER, failures)
    purchase_settlement_schema = _require_file(PURCHASE_SETTLEMENT_SCHEMA, failures)
    purchase_settlement_service = _require_file(PURCHASE_SETTLEMENT_SERVICE, failures)
    payment_readiness = _require_file(PAYMENT_READINESS, failures)
    degraded_report = _require_file(DEGRADED_REPORT, failures)
    stripe_audit = _require_file(STRIPE_AUDIT, failures)

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
        "bounded alert drill route": (alertmanager, 'drill: "true"'),
        "isolated alert drill grouping": (alertmanager, 'group_by: ["alertname", "severity", "drill_id"]'),
        "development-only alert drill routing": (alertmanager, "environment: development"),
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
        "dev-only reversible drill verifier": (verifier, 'parser.error("controlled drills are dev-only")'),
        "verified development drill runtime": (verifier, "controlled drills require a verified development API runtime"),
        "retrying drill restoration": (verifier, "for attempt in range(3)"),
        "correlated drill webhook receipt": (verifier, "_api_webhook_receipt_observed"),
        "environment-specific self-host Discord": (service, "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_SELF_HOST"),
        "environment-specific production urgent Discord": (source_compose, "DISCORD_WEBHOOK_URGENT_PRODUCTION"),
        "environment-specific development urgent Discord": (source_compose, "DISCORD_WEBHOOK_URGENT_DEVELOPMENT"),
        "development urgent Discord canonical destination": (source_compose, "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_DEVELOPMENT"),
        "development urgent Discord nightly fallback": (source_compose, "DISCORD_WEBHOOK_DEV_NIGHTLY"),
        "development urgent Discord smoke fallback": (source_compose, "DISCORD_WEBHOOK_DEV_SMOKE"),
        "production urgent Discord canonical destination": (source_compose, "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_PRODUCTION"),
        "production urgent Discord smoke fallback": (source_compose, "DISCORD_WEBHOOK_PROD_SMOKE"),
        "SVG conditional purchase label": (service, "purchase_window_label"),
        "Discord conditional purchase label": (service, "purchase_window_label"),
        "task uses shared Discord summary": (task, "build_operational_discord_summary"),
        "email conditional purchase label": (email_template, "purchase_window_label"),
        "explicit recovery-job scope": (service, "AI response recovery jobs"),
        "durable purchase settlement source": (service, "_purchase_ledger_totals"),
        "hashed purchase settlement identity": (purchase_settlement_schema, "settlement_key_hash"),
        "deterministic purchase settlement identity hash": (purchase_settlement_service, "hashlib.sha256"),
        "non-mutating Stripe readiness": (payment_readiness, "collect_stripe_readiness"),
        "independent EU and Managed readiness": (payment_readiness, "managed_payments"),
        "required Stripe event inventory": (payment_readiness, "REQUIRED_STRIPE_EVENTS"),
        "scheduled Stripe readiness collection": (_require_file(ROOT / "backend/core/api/app/tasks/health_check_tasks.py", failures), "collect_stripe_readiness"),
        "Stripe v2 destination inventory": (payment_readiness, "v2.core.event_destinations.list"),
        "payment worker readiness": (_require_file(ROOT / "backend/core/api/app/tasks/health_check_tasks.py", failures), "_stripe_payment_workers_healthy"),
        "provider inventory cadence TTL": (_require_file(ROOT / "backend/core/api/app/tasks/health_check_tasks.py", failures), "PROVIDER_HEALTH_INVENTORY_KEY, json.dumps(sorted(providers)), ex=PROVIDER_HEALTH_CHECK_CACHE_TTL"),
        "digest payment readiness collection": (task, "collect_billing_readiness"),
        "email payment readiness rendering": (email_template, "billing_readiness"),
        "Discord fallback receipt visibility": (task, "fallback_used=discord_destination"),
        "provider freshness summary": (service, "summarize_provider_health"),
        "canonical operations Discord resolver": (service, "resolve_operations_discord_destination"),
        "degraded report shared destination resolver": (degraded_report, "resolve_operations_discord_destination"),
        "redacted Stripe health audit": (stripe_audit, "--health"),
    }
    for label, (content, marker) in required_markers.items():
        if marker not in content:
            failures.append(f"missing {label}: {marker}")
    stripe_event_pattern = r'["\']((?:payment_intent|checkout\.session|charge|refund|invoice|customer\.subscription)\.[a-z_]+)["\']'
    handled_stripe_events = set(re.findall(stripe_event_pattern, payments))
    required_stripe_events = set(re.findall(stripe_event_pattern, payment_readiness))
    if handled_stripe_events - required_stripe_events:
        failures.append(
            "Stripe readiness omits backend-handled events: "
            + ", ".join(sorted(handled_stripe_events - required_stripe_events))
        )
    if required_stripe_events - handled_stripe_events:
        failures.append(
            "Stripe readiness requires events without backend handlers: "
            + ", ".join(sorted(required_stripe_events - handled_stripe_events))
        )
    forbidden_readiness_mutations = tuple(
        f"{resource}.{method}("
        for resource in ("Account", "Product", "Price", "WebhookEndpoint", "PaymentIntent", "Charge", "Refund", "Session")
        for method in ("create", "update", "delete", "cancel", "expire", "refund", "confirm")
    )
    if any(token in payment_readiness for token in forbidden_readiness_mutations):
        failures.append("payment readiness service must not expose Stripe mutation calls")
    for variable in (
        "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_PRODUCTION",
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION",
        "DISCORD_WEBHOOK_PROD_SMOKE",
        "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_DEVELOPMENT",
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_DEVELOPMENT",
        "DISCORD_WEBHOOK_DEV_NIGHTLY",
        "DISCORD_WEBHOOK_DEV_SMOKE",
        "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_SELF_HOST",
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_SELF_HOST",
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL",
    ):
        if variable not in service or variable not in server:
            failures.append(f"Python/CLI Discord resolver parity missing variable: {variable}")
    if "destinationSource: receipt.destination_source" not in server or "fallbackUsed: receipt.fallback_used" not in server:
        failures.append("CLI operational receipts must preserve Discord fallback visibility")
    if "operational-monitoring-digest-daily" in celery_config:
        failures.append("operational digest must have exactly one scheduler; Celery Beat schedule is forbidden")
    for path, source in ((PAYMENTS, payments), (APPROVE_BANK_TRANSFER, approve_bank_transfer)):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "increment_stat" or not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value in {"credits_sold", "purchase_count"}:
                failures.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} must use atomic record_credit_purchase"
                )
    if payments.count(".record_credit_purchase(") != 6:
        failures.append("payments route must update daily purchase analytics in exactly six settlement paths")
    if approve_bank_transfer.count(".record_credit_purchase(") != 2:
        failures.append("bank-transfer approval script must update daily purchase analytics in exactly two settlement paths")
    if payments.count("begin_purchase_settlement(") != 7 or payments.count("complete_purchase_settlement(") != 8:
        failures.append("payments route must ledger seven purchase branches and both Apple replay completion paths")
    if approve_bank_transfer.count("begin_purchase_settlement(") != 2 or approve_bank_transfer.count("complete_purchase_settlement(") != 2:
        failures.append("bank-transfer approval script must ledger exactly two purchase settlement paths")
    subscription_block = payments.partition('# Handle subscription events')[2].partition('event_type == "customer.subscription.deleted"')[0]
    subscription_order = (
        subscription_block.find('get_user_by_id(user_id)'),
        subscription_block.find('vault_key_id ='),
        subscription_block.find('begin_purchase_settlement('),
        subscription_block.find('update_user('),
    )
    if -1 in subscription_order or subscription_order != tuple(sorted(subscription_order)):
        failures.append("subscription settlement must validate cache/key before ledger begin and mutate credits afterward")
    if "cancel_purchase_settlement" in subscription_block or 'status_code=500' not in subscription_block:
        failures.append("failed subscription credit mutations must leave the pending ledger row for reconciliation")
    if 'existing_state == "reserved"' not in payments or "get_purchase_settlement(" not in payments:
        failures.append("Apple replays must block reserved fulfillment and reconcile an existing pending settlement")
    if "replayed_completed_settlement" not in payments or "directus_update_success or replayed_completed_settlement" not in payments:
        failures.append("completed payment replays must preserve completed cache state without rewriting credits")
    if "hmac.new" in purchase_settlement_service or "PURCHASE_SETTLEMENT_IDENTITY_SECRET" in purchase_settlement_service:
        failures.append("purchase settlement identities must use deterministic SHA-256 without extra runtime secrets")
    redemption_block = payments.partition("# Update Global Stats for Gift Card")[2].partition("# 9. Record redemption")[0]
    if 'increment_stat("credits_sold"' in redemption_block:
        failures.append("gift-card redemption must not record a second credit sale")

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
