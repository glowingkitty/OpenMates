#!/usr/bin/env python3
"""
Purpose: Backfill server-decryptable account contact emails from Brevo transactional history.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp
import yaml

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email_delivery_guard import build_delivery_id, build_delivery_key
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager


logging.basicConfig(level=logging.ERROR, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CONTACT_COLLECTION = "account_contact_emails"
DELIVERY_COLLECTION = "email_deliveries"
CONTACT_UUID_NAMESPACE = uuid.UUID("7f330c19-7aa0-5403-89ca-d97578fb8110")
DEFAULT_NEWSLETTER_SLUG = "introducing-openmates-v09"
NEWSLETTER_ISSUES_DIR = Path("/app/backend/newsletters/issues")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BREVO_URL = "https://api.brevo.com/v3/smtp/statistics/events"
BREVO_PAGE_LIMIT = 5000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill account contact emails from Brevo transactional event history.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  Preview Dec-Jan matches:\n"
            "    docker exec api python /app/backend/scripts/backfill_account_contact_emails.py --start-date 2025-12-20 --end-date 2026-01-31\n"
            "  Preview and include v0.10 newsletter recipient records:\n"
            "    docker exec api python /app/backend/scripts/backfill_account_contact_emails.py --start-date 2026-04-18 --end-date 2026-04-19 --newsletter-slug introducing-openmates-v09\n"
            "  Write first 10 contact records and newsletter records:\n"
            "    docker exec api python /app/backend/scripts/backfill_account_contact_emails.py --start-date 2025-12-20 --end-date 2026-04-19 --newsletter-slug introducing-openmates-v09 --write --max-records 10 --confirm"
        ),
    )
    today = date.today().isoformat()
    parser.add_argument("--start-date", default="2025-12-20", help="Start date, YYYY-MM-DD")
    parser.add_argument("--end-date", default=today, help="End date, YYYY-MM-DD")
    parser.add_argument("--newsletter-slug", default=None, help="Optional newsletter issue slug to backfill as delivered")
    parser.add_argument("--write", action="store_true", help="Actually create Directus rows. Default is dry-run.")
    parser.add_argument("--confirm", action="store_true", help="Required with --write")
    parser.add_argument("--max-records", type=int, default=None, help="Maximum new contact records to create")
    parser.add_argument("--max-emails", type=int, default=None, help="Maximum unique Brevo emails to inspect")
    parser.add_argument("--json", action="store_true", help="Print raw JSON summary")
    return parser.parse_args()


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def _date_chunks(start: date, end: date, max_days: int = 90) -> list[tuple[date, date]]:
    if end < start:
        raise SystemExit("--end-date must be on or after --start-date")
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    email = value.strip().lower()
    if not EMAIL_RE.match(email):
        return None
    return email


def _sha256_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _directus_hashed_email(email: str) -> str:
    """Match frontend cryptoService.hashEmail(): base64(SHA256(email))."""
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).digest()
    return base64.b64encode(digest).decode("utf-8")


def _contact_id(user_id: str) -> str:
    return str(uuid.uuid5(CONTACT_UUID_NAMESPACE, user_id))


def _event_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _load_newsletter_subjects(slug: str | None) -> set[str]:
    if not slug:
        return set()
    path = NEWSLETTER_ISSUES_DIR / f"{slug}.yml"
    if not path.exists():
        raise SystemExit(f"Newsletter issue not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    subject = data.get("subject") or {}
    return {value for value in subject.values() if value}


async def _fetch_brevo_events(api_key: str, start: date, end: date) -> list[dict[str, Any]]:
    headers = {"accept": "application/json", "api-key": api_key}
    events: list[dict[str, Any]] = []
    async with aiohttp.ClientSession() as session:
        for chunk_start, chunk_end in _date_chunks(start, end):
            for offset in range(0, 500000, BREVO_PAGE_LIMIT):
                params = {
                    "startDate": chunk_start.isoformat(),
                    "endDate": chunk_end.isoformat(),
                    "limit": BREVO_PAGE_LIMIT,
                    "offset": offset,
                    "sort": "asc",
                }
                async with session.get(BREVO_URL, headers=headers, params=params) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise RuntimeError(f"Brevo event query failed: HTTP {response.status} {text[:500]}")
                    data = json.loads(text)
                    page = data.get("events", [])
                    events.extend(page)
                    if len(page) < BREVO_PAGE_LIMIT:
                        break
    return events


def _collect_email_facts(
    events: list[dict[str, Any]],
    *,
    newsletter_subjects: set[str],
) -> tuple[dict[str, dict[str, Any]], set[str], dict[str, int]]:
    facts: dict[str, dict[str, Any]] = {}
    newsletter_emails: set[str] = set()
    by_event: dict[str, int] = {}
    for event in events:
        event_name = event.get("event") or "unknown"
        by_event[event_name] = by_event.get(event_name, 0) + 1
        email = _normalize_email(event.get("email"))
        if not email:
            continue
        event_at = _event_datetime(event.get("date"))
        current = facts.setdefault(email, {"events": set(), "last_seen_at": None})
        current["events"].add(event_name)
        if event_at and (not current["last_seen_at"] or event_at > current["last_seen_at"]):
            current["last_seen_at"] = event_at
        if newsletter_subjects and event.get("subject") in newsletter_subjects:
            newsletter_emails.add(email)
    return facts, newsletter_emails, by_event


async def _find_user_by_email_hash(directus: DirectusService, hashed_email: str) -> dict[str, Any] | None:
    users = await directus.get_items(
        "directus_users",
        params={
            "fields": "id,status,signup_completed,last_opened,language,darkmode,hashed_email",
            "filter": {"hashed_email": {"_eq": hashed_email}},
            "limit": 2,
        },
        admin_required=True,
    )
    return users[0] if users else None


async def _contact_exists(directus: DirectusService, user_id: str) -> bool:
    rows = await directus.get_items(
        CONTACT_COLLECTION,
        params={"fields": "id", "filter": {"user_id": {"_eq": user_id}}, "limit": 1},
        admin_required=True,
    )
    return bool(rows)


async def _newsletter_delivery_exists(directus: DirectusService, delivery_id: str) -> bool:
    rows = await directus.get_items(
        DELIVERY_COLLECTION,
        params={"fields": "id", "filter": {"id": {"_eq": delivery_id}}, "limit": 1},
        admin_required=True,
    )
    return bool(rows)


async def _create_contact(
    directus: DirectusService,
    encryption: EncryptionService,
    *,
    email: str,
    hashed_email: str,
    user: dict[str, Any],
    facts: dict[str, Any],
) -> bool:
    encrypted_email = await encryption.encrypt_account_contact_email(email)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": _contact_id(user["id"]),
        "user_id": user["id"],
        "hashed_email": hashed_email,
        "encrypted_email_address": encrypted_email,
        "purpose": "account_lifecycle",
        "source": "brevo_backfill",
        "verified_at": facts.get("last_seen_at"),
        "backfilled_at": now,
        "last_seen_brevo_at": facts.get("last_seen_at"),
        "metadata": {
            "brevo_events": sorted(facts.get("events") or []),
            "backfill_version": 1,
        },
    }
    success, _ = await directus.create_item(CONTACT_COLLECTION, payload, admin_required=True)
    return success


async def _create_newsletter_delivery(
    directus: DirectusService,
    *,
    slug: str,
    email: str,
    user: dict[str, Any],
    facts: dict[str, Any],
) -> bool:
    delivery_key = build_delivery_key(
        email_type="newsletter",
        campaign_key=slug,
        recipient_kind="directus_user",
        recipient_id=user["id"],
        stage="brevo_backfill",
    )
    delivery_id = build_delivery_id(delivery_key)
    if await _newsletter_delivery_exists(directus, delivery_id):
        return False
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": delivery_id,
        "delivery_key": delivery_key,
        "email_type": "newsletter",
        "campaign_key": slug,
        "recipient_kind": "directus_user",
        "recipient_id": user["id"],
        "recipient_hash": _sha256_email(email),
        "stage": "brevo_backfill",
        "status": "sent",
        "lang": user.get("language") or "en",
        "provider": "brevo",
        "processing_started_at": now,
        "sent_at": facts.get("last_seen_at") or now,
        "metadata": {
            "source": "brevo_backfill",
            "brevo_events": sorted(facts.get("events") or []),
            "backfilled_at": now,
        },
    }
    success, _ = await directus.create_item(DELIVERY_COLLECTION, payload, admin_required=True)
    return success


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.write and not args.confirm:
        raise SystemExit("Refusing to write without --confirm")
    if args.max_records is not None and args.max_records < 1:
        raise SystemExit("--max-records must be >= 1")
    if args.max_emails is not None and args.max_emails < 1:
        raise SystemExit("--max-emails must be >= 1")

    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    newsletter_subjects = _load_newsletter_subjects(args.newsletter_slug)

    secrets = SecretsManager()
    await secrets.initialize()
    api_key = await secrets.get_secret("kv/data/providers/brevo", "api_key")
    if not api_key:
        raise SystemExit("Brevo API key not found in Vault")

    events = await _fetch_brevo_events(api_key, start, end)
    email_facts, newsletter_emails, by_event = _collect_email_facts(events, newsletter_subjects=newsletter_subjects)
    emails = sorted(email_facts.keys())
    if args.max_emails is not None:
        emails = emails[: args.max_emails]

    cache = CacheService()
    encryption = EncryptionService(cache)
    await encryption.initialize()
    await encryption.ensure_keys_exist()
    directus = DirectusService(cache_service=cache, encryption_service=encryption)

    stats: dict[str, Any] = {
        "dry_run": not args.write,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "events_fetched": len(events),
        "events_by_type": by_event,
        "unique_brevo_emails": len(email_facts),
        "emails_inspected": len(emails),
        "matched_users": 0,
        "existing_contacts": 0,
        "contact_records_created": 0,
        "contact_records_would_create": 0,
        "unmatched_emails": 0,
        "newsletter_slug": args.newsletter_slug,
        "newsletter_brevo_emails": len(newsletter_emails),
        "newsletter_matched_users": 0,
        "newsletter_delivery_records_created": 0,
        "newsletter_delivery_records_would_create": 0,
        "newsletter_delivery_records_existing": 0,
        "stopped_by_limit": None,
    }

    try:
        for email in emails:
            facts = email_facts[email]
            hashed_email = _directus_hashed_email(email)
            user = await _find_user_by_email_hash(directus, hashed_email)
            if not user:
                stats["unmatched_emails"] += 1
                continue

            stats["matched_users"] += 1
            contact_exists = await _contact_exists(directus, user["id"])
            if contact_exists:
                stats["existing_contacts"] += 1
            else:
                if args.write:
                    if args.max_records is not None and stats["contact_records_created"] >= args.max_records:
                        stats["stopped_by_limit"] = "max_records"
                        break
                    if await _create_contact(directus, encryption, email=email, hashed_email=hashed_email, user=user, facts=facts):
                        stats["contact_records_created"] += 1
                else:
                    stats["contact_records_would_create"] += 1

            if args.newsletter_slug and email in newsletter_emails:
                stats["newsletter_matched_users"] += 1
                delivery_key = build_delivery_key(
                    email_type="newsletter",
                    campaign_key=args.newsletter_slug,
                    recipient_kind="directus_user",
                    recipient_id=user["id"],
                    stage="brevo_backfill",
                )
                delivery_id = build_delivery_id(delivery_key)
                if await _newsletter_delivery_exists(directus, delivery_id):
                    stats["newsletter_delivery_records_existing"] += 1
                elif args.write:
                    if await _create_newsletter_delivery(
                        directus,
                        slug=args.newsletter_slug,
                        email=email,
                        user=user,
                        facts=facts,
                    ):
                        stats["newsletter_delivery_records_created"] += 1
                else:
                    stats["newsletter_delivery_records_would_create"] += 1
    finally:
        await directus.close()

    return stats


def _format_summary(stats: dict[str, Any]) -> str:
    mode = "Preview" if stats["dry_run"] else "Write Run"
    lines = [f"Brevo Account Contact Backfill {mode}", ""]
    lines.append(f"Range: {stats['start_date']} to {stats['end_date']}")
    lines.append(f"Fetched {stats['events_fetched']} Brevo events across {stats['unique_brevo_emails']} unique recipient emails.")
    lines.append(f"Inspected {stats['emails_inspected']} unique recipient emails.")
    lines.append(f"Matched {stats['matched_users']} current Directus users.")
    lines.append(f"Skipped {stats['unmatched_emails']} emails that did not match a current user.")
    lines.append(f"Existing account contact records: {stats['existing_contacts']}")
    if stats["dry_run"]:
        lines.append(f"Would create {stats['contact_records_would_create']} account contact records.")
    else:
        lines.append(f"Created {stats['contact_records_created']} account contact records.")

    if stats.get("newsletter_slug"):
        lines.extend(["", f"Newsletter backfill: {stats['newsletter_slug']}"])
        lines.append(f"Brevo recipient emails with matching newsletter subject: {stats['newsletter_brevo_emails']}")
        lines.append(f"Matched newsletter recipients to {stats['newsletter_matched_users']} Directus users.")
        lines.append(f"Existing newsletter delivery records: {stats['newsletter_delivery_records_existing']}")
        if stats["dry_run"]:
            lines.append(f"Would create {stats['newsletter_delivery_records_would_create']} newsletter delivery records.")
        else:
            lines.append(f"Created {stats['newsletter_delivery_records_created']} newsletter delivery records.")

    if stats.get("stopped_by_limit"):
        lines.extend(["", f"Stopped early because {stats['stopped_by_limit']} was reached."])
    if stats["dry_run"]:
        lines.extend(["", "Nothing was written. Use --write --confirm to create records."])
    lines.append("Use --json for raw counters.")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    stats = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(stats, indent=2, sort_keys=True))
    else:
        print(_format_summary(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
