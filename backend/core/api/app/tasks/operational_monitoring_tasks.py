"""
Scheduled operational monitoring digest collection and delivery.

The task gathers aggregate 24-hour data, renders one compact PNG, delivers each
configured channel independently, and writes redacted delivery receipts. It
never reads user content and never evaluates cloud billing in self-host mode.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.operational_monitoring import (
    build_operational_discord_summary,
    build_operational_snapshot,
    collect_active_alerts,
    collect_activity_and_transactions,
    collect_billing_readiness,
    collect_provider_health,
    collect_resource_series,
    create_delivery_receipt,
    deliver_with_retries,
    render_operational_report_png,
    report_subject,
    resolve_operations_discord_destination,
    resolve_operational_environment,
    snapshot_sha256,
    summarize_delivery_state,
)
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.secrets_manager import SecretsManager


logger = logging.getLogger(__name__)
REPORT_DIR = Path(os.getenv("OPENMATES_REPO_ROOT", "/app")) / "test-results" / "operational-monitoring"
RECEIPT_CACHE_KEY = "operational_monitoring:last_delivery"
RECEIPT_TTL_SECONDS = 8 * 24 * 60 * 60


def _environment() -> str:
    return resolve_operational_environment(
        os.getenv("OPENMATES_DEPLOYMENT_MODE", ""),
        os.getenv("SERVER_ENVIRONMENT", "development"),
    )


def _discord_destination(environment: str) -> dict:
    return resolve_operations_discord_destination(environment, os.environ)


async def _send_discord(webhook_url: str, content: str, png: bytes) -> bool:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            webhook_url,
            data={"payload_json": json.dumps({"content": content[:2000], "username": "OpenMates Operations"})},
            files={"files[0]": ("openmates-operational-report.png", png, "image/png")},
        )
    return 200 <= response.status_code < 300


async def generate_and_deliver_operational_report(
    *,
    environment: str | None = None,
    channels: set[str] | None = None,
    test: bool = False,
) -> dict:
    selected_environment = environment or _environment()
    selected_channels = channels or {"email", "discord"}
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    directus = DirectusService()
    cache = CacheService()
    secrets: SecretsManager | None = None
    secrets_ready = False
    try:
        resources, activity_result, alerts_result = await asyncio.gather(
            collect_resource_series(start=start, end=now),
            collect_activity_and_transactions(
                directus,
                cache_service=cache,
                environment=selected_environment,
                start=start,
                end=now,
            ),
            collect_active_alerts(),
            return_exceptions=True,
        )
        collection_issues = []
        resource_series = resources if isinstance(resources, dict) else {
            "cpu_percent": [], "memory_percent": [], "disk_used_percent": [], "disk_free_bytes": []
        }
        if isinstance(resources, Exception):
            logger.warning("Operational resource collection unavailable: %s", type(resources).__name__)
            collection_issues.append({
                "fingerprint": "ResourceMetricsUnavailable", "severity": "critical", "active": True,
                "count": 1, "last_seen": now.isoformat(),
            })
        if isinstance(activity_result, Exception):
            raise activity_result
        activity, processing, cloud = activity_result
        provider_health = None
        billing_readiness = None
        if selected_environment != "self_host":
            try:
                provider_health = await collect_provider_health(cache, now=now)
            except Exception as exc:
                logger.warning("Operational provider-health collection unavailable: %s", type(exc).__name__)
                provider_health = {
                    "status": "unavailable", "healthy_count": 0, "unavailable_names": [],
                    "skipped_names": [], "stale_names": [], "checked_at": now.isoformat(),
                }
                collection_issues.append({
                    "fingerprint": "ProviderHealthUnavailable", "severity": "warning", "active": True,
                    "count": 1, "last_seen": now.isoformat(),
                })
            try:
                billing_readiness = await collect_billing_readiness(cache, now=now)
            except Exception as exc:
                logger.warning("Operational billing-readiness collection unavailable: %s", type(exc).__name__)
                billing_readiness = {
                    "status": "unavailable", "eu_card": "unavailable", "managed": "unavailable",
                    "catalog_gaps": [], "missing_events": [], "checked_at": now.isoformat(),
                }
            if billing_readiness["status"] != "healthy":
                collection_issues.append({
                    "fingerprint": "BillingReadinessDegraded", "severity": "warning", "active": True,
                    "count": 1, "last_seen": now.isoformat(),
                })
        issues = alerts_result if isinstance(alerts_result, list) else []
        if isinstance(alerts_result, Exception):
            logger.warning("Operational alert collection unavailable: %s", type(alerts_result).__name__)
            collection_issues.append({
                "fingerprint": "AlertQueryUnavailable", "severity": "warning", "active": True,
                "count": 1, "last_seen": now.isoformat(),
            })
        snapshot = build_operational_snapshot(
            environment=selected_environment,
            window_start=start,
            window_end=now,
            resource_series=resource_series,
            activity_counts=activity,
            processing_transactions=processing,
            provider_health=provider_health,
            billing_readiness=billing_readiness,
            billing=cloud,
            telemetry_freshness={
                "resource_metrics": "fresh" if any(resource_series.values()) else "stale",
                "application_metrics": "fresh",
                "report_scheduler": "fresh",
            },
            issues=[*issues, *collection_issues],
        )
        png = render_operational_report_png(snapshot)
        report_hash = snapshot_sha256(snapshot)
        report_id = f"operational-{selected_environment}-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        subject = report_subject(selected_environment, test=test)
        receipts = []
        admin_email = os.getenv("OPENMATES_RUNTIME_HEALTH_EMAIL_TO") or os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL")

        if "email" in selected_channels:
            if not admin_email:
                receipts.append(create_delivery_receipt(
                    environment=selected_environment, report_id=report_id, report_sha256=report_hash,
                    channel="email", state="unavailable", attempt_count=0, occurred_at=now,
                    sanitized_failure_class="missing_admin_email",
                ))
            else:
                async def send_email_attempt() -> bool:
                    nonlocal secrets, secrets_ready
                    if secrets is None:
                        secrets = SecretsManager()
                    if not secrets_ready:
                        await secrets.initialize()
                        secrets_ready = True
                    email_service = EmailTemplateService(secrets)
                    return await email_service.send_email(
                        template="operational_monitoring_digest",
                        recipient_email=admin_email,
                        subject=subject,
                        context={
                            "environment_label": selected_environment.replace("_", " ").upper(),
                            "test_label": "TEST · " if test else "",
                            "window_start": snapshot["window_start"],
                            "window_end": snapshot["window_end"],
                            "activity": activity,
                            "processing": processing,
                            "provider_health": provider_health,
                            "billing_readiness": billing_readiness,
                            "cloud": cloud,
                            "issues": snapshot["prioritized_issues"],
                            "freshness": snapshot["telemetry_freshness"],
                        },
                        attachments=[{
                            "filename": "openmates-operational-report.png",
                            "content": base64.b64encode(png).decode("ascii"),
                            "contentId": "operational-report",
                            "inline": True,
                        }],
                    )
                accepted, attempts, failure_class = await deliver_with_retries(
                    send_email_attempt, failure_class="email_delivery_failed",
                )
                if not accepted:
                    logger.warning("Operational report email delivery exhausted retries")
                receipts.append(create_delivery_receipt(
                    environment=selected_environment, report_id=report_id, report_sha256=report_hash,
                    channel="email", state="accepted" if accepted else "failed", attempt_count=attempts,
                    occurred_at=now, sanitized_failure_class=failure_class,
                ))

        if "discord" in selected_channels:
            discord_destination = _discord_destination(selected_environment)
            webhook = discord_destination["url"]
            if not webhook:
                receipts.append(create_delivery_receipt(
                    environment=selected_environment, report_id=report_id, report_sha256=report_hash,
                    channel="discord", state="unavailable", attempt_count=0, occurred_at=now,
                    sanitized_failure_class="missing_discord_webhook",
                    destination_source=discord_destination["source"],
                    fallback_used=discord_destination["fallback_used"],
                ))
            else:
                accepted, attempts, failure_class = await deliver_with_retries(
                    lambda: _send_discord(
                        webhook,
                        build_operational_discord_summary(snapshot, test=test, report_id=report_id),
                        png,
                    ),
                    failure_class="discord_delivery_failed",
                )
                if not accepted:
                    logger.warning("Operational report Discord delivery exhausted retries")
                receipts.append(create_delivery_receipt(
                    environment=selected_environment, report_id=report_id, report_sha256=report_hash,
                    channel="discord", state="accepted" if accepted else "failed", attempt_count=attempts,
                    occurred_at=now, sanitized_failure_class=failure_class,
                    destination_source=discord_destination["source"],
                    fallback_used=discord_destination["fallback_used"],
                ))

        result = {
            "report_id": report_id,
            "report_sha256": report_hash,
            "environment": selected_environment,
            "delivery_state": summarize_delivery_state(receipts),
            "receipts": receipts,
            "snapshot": snapshot,
        }
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (REPORT_DIR / "latest.png").write_bytes(png)
        with (REPORT_DIR / f"receipts-{now.strftime('%Y-%m')}.jsonl").open("a", encoding="utf-8") as receipt_file:
            for receipt in receipts:
                receipt_file.write(json.dumps(receipt, separators=(",", ":")) + "\n")
        await cache.set(RECEIPT_CACHE_KEY, result, ttl=RECEIPT_TTL_SECONDS)
        return result
    finally:
        if secrets is not None:
            await secrets.aclose()
        await cache.close()
        await directus.close()


@app.task(name="operational_monitoring.send_digest", bind=True)
def send_operational_monitoring_digest(self, *, test: bool = False) -> dict:
    return asyncio.run(generate_and_deliver_operational_report(test=test))
