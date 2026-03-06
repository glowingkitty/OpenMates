#!/usr/bin/env python3
"""
Script to inspect newsletter subscription data.

Shows:
- Total confirmed subscribers count
- Pending (unconfirmed) subscriptions in cache
- Ignored email count
- Full subscriber list with decrypted emails (optional)
- Subscription timeline (daily/monthly breakdown)

Usage:
    # Summary only (counts)
    docker exec api python /app/backend/scripts/debug.py newsletter

    # Show all subscribers with decrypted emails
    docker exec api python /app/backend/scripts/debug.py newsletter --show-emails

    # Show pending (unconfirmed) subscriptions from cache
    docker exec api python /app/backend/scripts/debug.py newsletter --show-pending

    # Show everything
    docker exec api python /app/backend/scripts/debug.py newsletter --show-emails --show-pending

    # JSON output
    docker exec api python /app/backend/scripts/debug.py newsletter --json

    # Show subscription timeline (monthly breakdown)
    docker exec api python /app/backend/scripts/debug.py newsletter --timeline
"""

import asyncio
import argparse
import sys
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict

# Add the backend directory to the Python path — must happen before backend imports
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

# Shared inspection utilities — replaces duplicated helpers
from debug_utils import (
    configure_script_logging,
    format_timestamp,
    censor_email,
)

script_logger = configure_script_logging('debug_newsletter')


async def get_confirmed_subscribers(
    directus_service: DirectusService,
) -> List[Dict[str, Any]]:
    """Fetch all confirmed newsletter subscribers from Directus."""
    collection_name = "newsletter_subscribers"
    url = f"{directus_service.base_url}/items/{collection_name}"
    params = {
        "fields": "id,encrypted_email_address,hashed_email,confirmed_at,subscribed_at,language,darkmode",
        "filter[confirmed_at][_nnull]": "true",
        "sort": "-confirmed_at",
        "limit": -1,  # Get all
    }

    response = await directus_service._make_api_request("GET", url, params=params)
    if response.status_code == 200:
        data = response.json()
        return data.get("data", [])
    return []


async def get_all_subscriber_records(
    directus_service: DirectusService,
) -> List[Dict[str, Any]]:
    """Fetch ALL newsletter subscriber records (including any without confirmed_at, if they exist)."""
    collection_name = "newsletter_subscribers"
    url = f"{directus_service.base_url}/items/{collection_name}"
    params = {
        "fields": "id,encrypted_email_address,hashed_email,confirmed_at,subscribed_at,language,darkmode,unsubscribe_token,user_registration_status",
        "sort": "-subscribed_at",
        "limit": -1,
        "meta": "total_count,filter_count",
    }

    response = await directus_service._make_api_request("GET", url, params=params)
    if response.status_code == 200:
        data = response.json()
        meta = data.get("meta", {})
        return data.get("data", []), meta
    return [], {}


async def get_ignored_emails_count(directus_service: DirectusService) -> int:
    """Get count of ignored/blocked emails."""
    url = f"{directus_service.base_url}/items/ignored_emails"
    params = {
        "limit": 1,
        "meta": "total_count",
    }

    response = await directus_service._make_api_request("GET", url, params=params)
    if response.status_code == 200:
        data = response.json()
        meta = data.get("meta", {})
        return int(meta.get("total_count", 0))
    return 0


async def get_pending_subscriptions(cache_service: CacheService) -> List[Dict[str, Any]]:
    """
    Scan cache for pending (unconfirmed) newsletter subscriptions.
    These are stored with key pattern: newsletter_subscribe:{token}
    They expire after 30 minutes.
    """
    pending = []
    try:
        # Use get_keys_by_pattern to find all newsletter subscription keys
        keys = await cache_service.get_keys_by_pattern("newsletter_subscribe:*")
        for key in keys:
            data = await cache_service.get(key)
            if data:
                # Extract token from key
                token = key.replace("newsletter_subscribe:", "")
                entry = {
                    "token": token[:8] + "...",
                    "email": data.get("email", "unknown"),
                    "language": data.get("language", "en"),
                    "darkmode": data.get("darkmode", False),
                    "created_at": data.get("created_at", "unknown"),
                }
                # Get TTL via raw redis client
                try:
                    client = await cache_service.client
                    if client:
                        ttl_val = await client.ttl(key)
                        if ttl_val and ttl_val > 0:
                            entry["expires_in_minutes"] = round(ttl_val / 60, 1)
                except Exception:
                    pass
                pending.append(entry)
    except Exception as e:
        script_logger.warning(f"Could not scan cache for pending subscriptions: {e}")
    return pending


async def decrypt_email(encryption_service: EncryptionService, encrypted_email: str) -> Optional[str]:
    """Decrypt a newsletter email address."""
    if not encrypted_email:
        return None
    try:
        return await encryption_service.decrypt_newsletter_email(encrypted_email)
    except Exception as e:
        script_logger.warning(f"Failed to decrypt email: {e}")
        return None


def build_timeline(subscribers: List[Dict[str, Any]]) -> Dict[str, int]:
    """Build a monthly subscription timeline from subscriber data."""
    monthly = defaultdict(int)
    for sub in subscribers:
        confirmed_at = sub.get("confirmed_at") or sub.get("subscribed_at")
        if confirmed_at:
            try:
                ts = confirmed_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts)
                month_key = dt.strftime("%Y-%m")
                monthly[month_key] += 1
            except Exception:
                pass
    return dict(sorted(monthly.items()))


async def run_inspection(args: argparse.Namespace) -> None:
    """Main inspection logic."""
    output_json = args.json
    show_emails = args.show_emails
    show_pending = args.show_pending
    show_timeline = args.timeline

    # Initialize services
    directus_service = DirectusService()
    cache_service = CacheService()
    encryption_service = None

    if show_emails:
        encryption_service = EncryptionService(cache_service=cache_service)
        await encryption_service.initialize()

    # Collect all data
    result: Dict[str, Any] = {}

    # 1. Fetch all subscriber records + meta
    subscribers, meta = await get_all_subscriber_records(directus_service)
    total_records = int(meta.get("total_count", len(subscribers)))
    confirmed_count = sum(1 for s in subscribers if s.get("confirmed_at"))
    unconfirmed_count = total_records - confirmed_count

    result["summary"] = {
        "total_records_in_directus": total_records,
        "confirmed_subscribers": confirmed_count,
        "unconfirmed_records": unconfirmed_count,
    }

    # 2. Ignored emails count
    ignored_count = await get_ignored_emails_count(directus_service)
    result["summary"]["ignored_blocked_emails"] = ignored_count

    # 3. Language breakdown and registration status
    lang_breakdown: Dict[str, int] = defaultdict(int)
    darkmode_count = 0
    reg_status_counts: Dict[str, int] = {
        "not_signed_up": 0,
        "signup_incomplete": 0,
        "signup_complete": 0,
        "unknown": 0,
    }
    for sub in subscribers:
        lang = sub.get("language", "unknown")
        lang_breakdown[lang] += 1
        if sub.get("darkmode"):
            darkmode_count += 1
        reg_status = sub.get("user_registration_status")
        if reg_status in reg_status_counts:
            reg_status_counts[reg_status] += 1
        else:
            reg_status_counts["unknown"] += 1
    result["summary"]["language_breakdown"] = dict(sorted(lang_breakdown.items(), key=lambda x: -x[1]))
    result["summary"]["darkmode_subscribers"] = darkmode_count
    result["summary"]["registration_status"] = reg_status_counts

    # 4. Pending subscriptions from cache
    if show_pending:
        pending = await get_pending_subscriptions(cache_service)
        result["pending_in_cache"] = {
            "count": len(pending),
            "entries": pending,
        }

    # 5. Subscriber list with decrypted emails
    if show_emails and encryption_service:
        subscriber_list = []
        for sub in subscribers:
            encrypted = sub.get("encrypted_email_address", "")
            email = await decrypt_email(encryption_service, encrypted)
            subscriber_list.append({
                "id": sub.get("id"),
                "email": email or "[decrypt failed]",
                "email_masked": censor_email(email) if email else "[decrypt failed]",
                "confirmed_at": format_timestamp(sub.get("confirmed_at")),
                "subscribed_at": format_timestamp(sub.get("subscribed_at")),
                "language": sub.get("language", "unknown"),
                "darkmode": sub.get("darkmode", False),
                "has_unsubscribe_token": bool(sub.get("unsubscribe_token")),
            })
        result["subscribers"] = subscriber_list

    # 6. Timeline
    if show_timeline:
        result["timeline_monthly"] = build_timeline(subscribers)

    # Output
    if output_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_formatted(result, show_emails, show_pending, show_timeline)

    # Cleanup
    try:
        await directus_service.close()
        await cache_service.close()
        if encryption_service:
            await encryption_service.close()
    except Exception:
        pass


def print_formatted(
    result: Dict[str, Any],
    show_emails: bool,
    show_pending: bool,
    show_timeline: bool,
) -> None:
    """Print human-readable formatted output."""
    summary = result.get("summary", {})

    print()
    print("=" * 60)
    print("  NEWSLETTER SUBSCRIBERS REPORT")
    print("=" * 60)
    print()

    # Summary
    confirmed = summary.get('confirmed_subscribers', 0)
    print("  SUMMARY")
    print("  " + "-" * 40)
    print(f"  Confirmed subscribers:    {confirmed}")
    print(f"  Unconfirmed records:      {summary.get('unconfirmed_records', 0)}")
    print(f"  Total Directus records:   {summary.get('total_records_in_directus', 0)}")
    print(f"  Blocked/ignored emails:   {summary.get('ignored_blocked_emails', 0)}")
    print(f"  Darkmode preference:      {summary.get('darkmode_subscribers', 0)}")
    print()

    # Registration status breakdown
    reg_status = summary.get("registration_status", {})
    not_signed_up = reg_status.get("not_signed_up", 0)
    signup_incomplete = reg_status.get("signup_incomplete", 0)
    signup_complete = reg_status.get("signup_complete", 0)
    unknown = reg_status.get("unknown", 0)
    total_known = not_signed_up + signup_incomplete + signup_complete

    print("  REGISTRATION STATUS")
    print("  " + "-" * 40)
    if total_known > 0 or unknown == 0:
        def pct(n: int) -> str:
            base = confirmed if confirmed > 0 else 1
            return f"{n / base * 100:.0f}%"
        print(f"  Not signed up:            {not_signed_up:>4}  ({pct(not_signed_up)})")
        print(f"  Signup incomplete:        {signup_incomplete:>4}  ({pct(signup_incomplete)})")
        print(f"  Fully signed up:          {signup_complete:>4}  ({pct(signup_complete)})")
        if unknown > 0:
            print(f"  Status unknown (pre-backfill): {unknown:>4}")
    else:
        print("  No status data yet — run the backfill script first.")
        print("  docker exec api python /app/backend/scripts/backfill_newsletter_user_status.py")
    print()

    # Language breakdown
    lang_breakdown = summary.get("language_breakdown", {})
    if lang_breakdown:
        print("  LANGUAGE BREAKDOWN")
        print("  " + "-" * 40)
        for lang, count in lang_breakdown.items():
            print(f"    {lang:10s}  {count}")
        print()

    # Pending subscriptions
    if show_pending:
        pending = result.get("pending_in_cache", {})
        pending_count = pending.get("count", 0)
        print("  PENDING (UNCONFIRMED) IN CACHE")
        print("  " + "-" * 40)
        print(f"  Count: {pending_count}")
        if pending_count > 0:
            print()
            for entry in pending.get("entries", []):
                email = entry.get("email", "unknown")
                masked = censor_email(email)
                expires = entry.get("expires_in_minutes", "?")
                created = entry.get("created_at", "unknown")
                print(f"    {masked:30s}  lang={entry.get('language', '?'):5s}  expires in {expires} min  (requested: {created})")
        else:
            print("  No pending subscriptions in cache.")
            print("  (Pending entries expire after 30 minutes)")
        print()

    # Subscriber list
    if show_emails:
        subscribers = result.get("subscribers", [])
        print("  SUBSCRIBERS (DECRYPTED)")
        print("  " + "-" * 40)
        if subscribers:
            for i, sub in enumerate(subscribers, 1):
                email = sub.get("email", "[unknown]")
                confirmed = sub.get("confirmed_at", "N/A")
                subscribed = sub.get("subscribed_at", "N/A")
                lang = sub.get("language", "?")
                dark = "dark" if sub.get("darkmode") else "light"
                has_unsub = "yes" if sub.get("has_unsubscribe_token") else "NO"
                reg_status = sub.get("user_registration_status") or "unknown"
                print(f"    {i}. {email}")
                print(f"       Confirmed:    {confirmed}")
                print(f"       Subscribed:   {subscribed}")
                print(f"       Language:     {lang}")
                print(f"       Theme:        {dark}")
                print(f"       Unsub token:  {has_unsub}")
                print(f"       Reg status:   {reg_status}")
                print()
        else:
            print("  No subscribers found.")
        print()

    # Timeline
    if show_timeline:
        timeline = result.get("timeline_monthly", {})
        print("  SUBSCRIPTION TIMELINE (MONTHLY)")
        print("  " + "-" * 40)
        if timeline:
            for month, count in timeline.items():
                bar = "#" * count
                print(f"    {month}  {count:3d}  {bar}")
        else:
            print("  No subscription data available.")
        print()

    print("=" * 60)
    print()


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Inspect newsletter subscription data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Summary counts
  docker exec api python /app/backend/scripts/debug.py newsletter

  # Show all subscribers with decrypted emails
  docker exec api python /app/backend/scripts/debug.py newsletter --show-emails

  # Show pending (unconfirmed) subscriptions from cache
  docker exec api python /app/backend/scripts/debug.py newsletter --show-pending

  # Show monthly subscription timeline
  docker exec api python /app/backend/scripts/debug.py newsletter --timeline

  # Show everything
  docker exec api python /app/backend/scripts/debug.py newsletter --show-emails --show-pending --timeline

  # JSON output
  docker exec api python /app/backend/scripts/debug.py newsletter --json
        """,
    )

    parser.add_argument(
        "--show-emails",
        action="store_true",
        help="Decrypt and display subscriber email addresses",
    )
    parser.add_argument(
        "--show-pending",
        action="store_true",
        help="Show pending (unconfirmed) subscriptions from cache",
    )
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="Show monthly subscription timeline",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text",
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_inspection(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        script_logger.error(f"Script failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
