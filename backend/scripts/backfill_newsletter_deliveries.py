#!/usr/bin/env python3
"""
Backfill newsletter_deliveries in Directus from Brevo transactional email events.

Use this when a newsletter was sent before the newsletter_deliveries collection
existed, or when the send script crashed before writing all delivery records.

Approach:
  1. Pull all Brevo events (delivered + hardBounces) for the given slug's subjects.
  2. Decrypt every newsletter subscriber's email from Directus.
  3. Match plaintext Brevo emails -> subscriber IDs.
  4. Write newsletter_deliveries records (idempotent — skips existing rows).

Usage:
    # Dry run (shows what would be written, touches nothing):
    docker exec -it api python /app/backend/scripts/backfill_newsletter_deliveries.py \\
        --slug introducing-openmates-v09 --dry-run

    # Write to dev Directus:
    docker exec -it api python /app/backend/scripts/backfill_newsletter_deliveries.py \\
        --slug introducing-openmates-v09

    # Write to prod Directus (uses DIRECTUS_URL / DIRECTUS_TOKEN from Vault):
    docker exec -it api python /app/backend/scripts/backfill_newsletter_deliveries.py \\
        --slug introducing-openmates-v09 --production

    # Custom date window (default: manifest sent_at ±3 days, fallback: last 30 days):
    docker exec -it api python /app/backend/scripts/backfill_newsletter_deliveries.py \\
        --slug introducing-openmates-v09 --start 2026-04-18 --end 2026-04-20
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, "/app/backend")

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email.brevo_provider import BrevoProvider
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.secrets_manager import SecretsManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())

REPO_ROOT = Path("/app")
ISSUES_DIR = REPO_ROOT / "backend" / "newsletters" / "issues"

# Brevo returns up to 5000 events per call; newsletters rarely exceed that.
BREVO_LIMIT = 5000


def load_manifest(slug: str) -> dict[str, Any]:
    path = ISSUES_DIR / f"{slug}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _subjects_for_manifest(manifest: dict[str, Any]) -> set[str]:
    """Return all non-null subject values from the manifest."""
    subjects = manifest.get("subject") or {}
    return {v for v in subjects.values() if v}


def _date_window(
    manifest: dict[str, Any],
    start_override: str | None,
    end_override: str | None,
) -> tuple[datetime, datetime]:
    """Resolve the Brevo query date window."""
    if start_override and end_override:
        return (
            datetime.strptime(start_override, "%Y-%m-%d"),
            datetime.strptime(end_override, "%Y-%m-%d"),
        )

    # Try to anchor on manifest sent_at ±3 days
    sent_at = manifest.get("sent_at")
    if sent_at:
        try:
            if isinstance(sent_at, str):
                anchor = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
            else:
                anchor = datetime.fromtimestamp(float(sent_at), tz=timezone.utc)
            return anchor - timedelta(days=1), anchor + timedelta(days=2)
        except (ValueError, TypeError):
            pass

    # Fallback: last 30 days
    now = datetime.now(timezone.utc)
    return now - timedelta(days=30), now


async def fetch_brevo_events(
    brevo: BrevoProvider,
    subjects: set[str],
    start: datetime,
    end: datetime,
) -> tuple[dict[str, str], str]:
    """Return ({email: status}, earliest_sent_at_iso) for all newsletter events in the window.

    Status is "sent" for delivered emails and "failed" for hard bounces.
    Delivered takes precedence over failed for the same address.
    earliest_sent_at_iso falls back to now() if no delivered events are found.
    """
    email_status: dict[str, str] = {}
    earliest_ts: str | None = None

    for event_type, status in [("delivered", "sent"), ("hardBounces", "failed")]:
        result = await brevo.get_email_events(
            event_type=event_type,
            start_date=start,
            end_date=end,
            limit=BREVO_LIMIT,
        )
        if "error" in result:
            logger.error("Brevo %s query error: %s", event_type, result["error"])
            continue

        matched = [e for e in result["events"] if e.get("subject", "") in subjects]
        logger.info("Brevo %s: %d total, %d matched newsletter", event_type, result["count"], len(matched))

        for event in matched:
            email = (event.get("email") or "").lower().strip()
            if not email:
                continue
            # Delivered takes precedence over failed
            if email not in email_status or status == "sent":
                email_status[email] = status
            # Track earliest delivered timestamp for the sent_at field
            if status == "sent" and event.get("date"):
                ts = event["date"]
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts

    sent_at = earliest_ts or datetime.now(timezone.utc).isoformat()
    return email_status, sent_at


async def fetch_and_decrypt_subscribers(
    directus: DirectusService,
    encryption: EncryptionService,
) -> dict[str, dict[str, Any]]:
    """Return {plaintext_email: subscriber_row} for all confirmed subscribers.

    Decryption failures are skipped with a warning.
    """
    url = f"{directus.base_url}/items/newsletter_subscribers"
    params = {
        "fields": "id,encrypted_email_address,language,confirmed_at",
        "filter[confirmed_at][_nnull]": "true",
        "limit": "-1",
    }
    resp = await directus._make_api_request("GET", url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch subscribers: {resp.status_code} {resp.text[:300]}")

    rows = resp.json().get("data", [])
    logger.info("Fetched %d confirmed subscribers from Directus", len(rows))

    email_map: dict[str, dict[str, Any]] = {}
    failed_decrypt = 0
    for row in rows:
        try:
            plaintext = await encryption.decrypt_newsletter_email(
                row.get("encrypted_email_address", "")
            )
            if plaintext:
                email_map[plaintext.lower().strip()] = row
            else:
                failed_decrypt += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("Decrypt failed for subscriber %s: %s", row.get("id"), exc)
            failed_decrypt += 1

    if failed_decrypt:
        logger.warning("%d subscribers could not be decrypted (skipped)", failed_decrypt)

    logger.info("%d subscribers decrypted successfully", len(email_map))
    return email_map


async def fetch_existing_deliveries(slug: str, directus: DirectusService) -> set[str]:
    """Return subscriber_ids that already have a delivery record for this slug."""
    url = f"{directus.base_url}/items/newsletter_deliveries"
    params = {
        "fields": "subscriber_id",
        "filter[slug][_eq]": slug,
        "limit": "-1",
    }
    resp = await directus._make_api_request("GET", url, params=params)
    if resp.status_code in (403, 404):
        logger.warning("newsletter_deliveries not found — will create records from scratch")
        return set()
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch existing deliveries: {resp.status_code}")
    return {row["subscriber_id"] for row in resp.json().get("data", [])}


async def write_delivery(
    slug: str,
    subscriber_id: str,
    status: str,
    lang: str,
    sent_at: str,
    directus: DirectusService,
) -> bool:
    url = f"{directus.base_url}/items/newsletter_deliveries"
    payload = {
        "slug": slug,
        "subscriber_id": subscriber_id,
        "status": status,
        "lang": lang,
        "sent_at": sent_at,
    }
    resp = await directus._make_api_request("POST", url, json=payload)
    return resp.status_code in (200, 201)


async def run(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.slug)
    subjects = _subjects_for_manifest(manifest)
    if not subjects:
        logger.error("No subjects found in manifest — cannot match Brevo events")
        return 2

    logger.info("Subjects to match: %s", subjects)

    start, end = _date_window(manifest, args.start, args.end)
    logger.info("Brevo query window: %s → %s", start.date(), end.date())

    # Services
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    directus = DirectusService()
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    await encryption.initialize()

    brevo_api_key = await secrets_manager.get_secret(
        secret_path="kv/data/providers/brevo", secret_key="api_key"
    )
    if not brevo_api_key:
        logger.error("Brevo API key not found at kv/data/providers/brevo -> api_key")
        return 2
    brevo = BrevoProvider(api_key=brevo_api_key)

    # 1. Pull Brevo events
    brevo_events, earliest_sent_at = await fetch_brevo_events(brevo, subjects, start, end)
    if not brevo_events:
        logger.warning("No matching Brevo events found — check subjects and date window")
        return 0

    logger.info("Brevo events matched: %d total (%d sent, %d failed)",
                len(brevo_events),
                sum(1 for s in brevo_events.values() if s == "sent"),
                sum(1 for s in brevo_events.values() if s == "failed"))

    # 2. Decrypt subscribers
    subscriber_map = await fetch_and_decrypt_subscribers(directus, encryption)

    # 3. Match
    existing_ids = await fetch_existing_deliveries(args.slug, directus)
    logger.info("Already have %d delivery records for slug '%s'", len(existing_ids), args.slug)

    matched: list[dict[str, Any]] = []
    unmatched_emails: list[str] = []

    for email, status in brevo_events.items():
        sub = subscriber_map.get(email)
        if sub is None:
            unmatched_emails.append(email)
            continue
        if sub["id"] in existing_ids:
            logger.debug("Skipping %s — delivery record already exists", sub["id"])
            continue
        matched.append({
            "subscriber_id": sub["id"],
            "lang": sub.get("language", "en"),
            "status": status,
        })

    logger.info("To write: %d records  |  Already exists: %d  |  Unmatched: %d",
                len(matched), len(existing_ids), len(unmatched_emails))

    if unmatched_emails:
        logger.warning(
            "%d Brevo emails had no matching subscriber in Directus "
            "(test sends, admin previews, or deleted subscribers):",
            len(unmatched_emails),
        )
        for e in unmatched_emails:
            masked = e[:3] + "***@" + e.split("@")[1] if "@" in e else e
            logger.warning("  unmatched: %s", masked)

    if args.dry_run:
        print(f"\n[DRY RUN] Would write {len(matched)} delivery records for slug '{args.slug}'")
        for r in matched:
            print(f"  subscriber_id={r['subscriber_id']}  lang={r['lang']}  status={r['status']}")
        return 0

    if not matched:
        print("Nothing to write — all records already exist or no matches found.")
        return 0

    written = 0
    failed_writes = 0
    for record in matched:
        ok = await write_delivery(
            slug=args.slug,
            subscriber_id=record["subscriber_id"],
            status=record["status"],
            lang=record["lang"],
            sent_at=earliest_sent_at,
            directus=directus,
        )
        if ok:
            written += 1
        else:
            failed_writes += 1
            logger.warning("Failed to write record for subscriber %s", record["subscriber_id"])

    print(f"\n=== Backfill complete for '{args.slug}' ===")
    print(f"  Written:  {written}")
    print(f"  Failed:   {failed_writes}")
    print(f"  Skipped (already existed): {len(existing_ids)}")
    print(f"  Unmatched Brevo emails:    {len(unmatched_emails)}")

    await directus.close()
    await cache.close()
    await encryption.close()

    return 0 if failed_writes == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill newsletter_deliveries in Directus from Brevo event data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--slug", required=True, help="Newsletter slug (must match issues/<slug>.yml)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be written, touch nothing")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD (overrides auto-detect)")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD (overrides auto-detect)")
    parser.add_argument("--production", action="store_true", help="Target production Directus (uses prod secrets)")
    args = parser.parse_args()

    if args.production:
        os.environ.setdefault("SERVER_ENVIRONMENT", "production")

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.error("Fatal: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
