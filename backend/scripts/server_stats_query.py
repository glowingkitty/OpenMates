#!/usr/bin/env python3
"""
scripts/_server_stats_query.py

Queries server stats from Directus and Redis for the daily meeting health report.
Runs inside Docker via: docker exec api python3 /app/scripts/_server_stats_query.py

Supports --prod flag to query production stats via the Admin Debug API endpoint
(/v1/admin/debug/server-stats) instead of local Directus.

Outputs structured text to stdout with sections:
  - User Growth (registrations, signups, total users)
  - Engagement (messages, chats, page loads, unique visits)
  - Revenue (income, credits, purchases, subscriptions)
  - AI Usage (input/output tokens)
  - Web Analytics (top countries, device split)
  - Data Health (daily_inspiration_defaults row count check)
"""

import asyncio
import json
import logging
import sys

sys.path.insert(0, "/app")

# Suppress noisy logs — we only want our stdout output
logging.basicConfig(level=logging.WARNING)
for _noisy in ("httpx", "httpcore", "backend", "uvicorn"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)


def _int(value, default: int = 0) -> int:
    """Safely convert a Directus value (may be str, None, or int) to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


async def query_stats() -> str:
    """Query Directus and Redis for server stats, return formatted text."""
    from datetime import datetime, timedelta, timezone

    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )

    today = datetime.now(timezone.utc)
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    lines = []

    # ── Server Stats (yesterday) ─────────────────────────────────────────────
    stats = None
    try:
        items = await directus.get_items(
            "server_stats_global_daily",
            {
                "filter": {"date": {"_eq": yesterday_str}},
                "limit": 1,
            },
            admin_required=True,
        )
        stats = items[0] if items else None
    except Exception as e:
        lines.append(f"[server_stats_global_daily query failed: {e}]")

    if stats:
        # User Growth
        total_users = stats.get("total_regular_users") or "?"
        new_reg = _int(stats.get("new_users_registered"))
        new_signup = _int(stats.get("new_users_finished_signup"))
        lines.append("**User Growth**")
        lines.append(f"- Total registered users: {total_users}")
        lines.append(f"- New registrations: {new_reg}")
        lines.append(f"- Completed signups: {new_signup}")
        lines.append("")

        # Engagement
        messages = _int(stats.get("messages_sent"))
        chats = _int(stats.get("chats_created"))
        embeds = _int(stats.get("embeds_created"))
        lines.append("**Engagement**")
        lines.append(f"- Messages sent: {messages}")
        lines.append(f"- Chats created: {chats}")
        lines.append(f"- Embeds created: {embeds}")

        # Revenue
        income_cents = _int(stats.get("income_eur_cents"))
        income_eur = income_cents / 100.0
        credits_sold = _int(stats.get("credits_sold"))
        credits_used = _int(stats.get("credits_used"))
        purchases = _int(stats.get("purchase_count"))
        active_subs = stats.get("active_subscriptions") or "?"
        liability = stats.get("liability_total") or "?"
        sub_new = _int(stats.get("subscription_creations"))
        sub_cancel = _int(stats.get("subscription_cancellations"))
        lines.append("")
        lines.append("**Revenue**")
        lines.append(f"- Income: EUR {income_eur:.2f}")
        lines.append(f"- Credits sold: {credits_sold} | used: {credits_used}")
        lines.append(f"- Purchases: {purchases}")
        lines.append(f"- Subscriptions: {active_subs} active (+{sub_new}/-{sub_cancel})")
        lines.append(f"- Credit liability: {liability}")

        # AI Usage
        input_tokens = _int(stats.get("total_input_tokens"))
        output_tokens = _int(stats.get("total_output_tokens"))
        lines.append("")
        lines.append("**AI Usage**")
        lines.append(f"- Input tokens: {input_tokens:,}")
        lines.append(f"- Output tokens: {output_tokens:,}")
    else:
        lines.append(f"(No server stats found for {yesterday_str})")

    # ── Newsletter Subscribers ───────────────────────────────────────────────
    lines.append("")
    lines.append("**Newsletter**")
    try:
        collection_url = f"{directus.base_url}/items/newsletter_subscribers"
        params = {
            "limit": 1,
            "meta": "filter_count",
            "filter[confirmed_at][_nnull]": "true",
        }
        resp = await directus._make_api_request("GET", collection_url, params=params)
        if resp.status_code == 200:
            nl_count = _int(resp.json().get("meta", {}).get("filter_count"))
        else:
            nl_count = 0
        lines.append(f"- Confirmed subscribers: {nl_count:,}")
    except Exception as e:
        lines.append(f"- Confirmed subscribers: ERROR — {e}")

    # ── Web Analytics (yesterday) ────────────────────────────────────────────
    lines.append("")
    try:
        wa_items = await directus.get_items(
            "web_analytics_daily",
            {
                "filter": {"date": {"_eq": yesterday_str}},
                "limit": 1,
            },
            admin_required=True,
        )
        wa = wa_items[0] if wa_items else None
    except Exception as e:
        wa = None
        lines.append(f"[web_analytics_daily query failed: {e}]")

    if wa:
        page_loads = wa.get("page_loads") or 0
        unique_visits = wa.get("unique_visits_approx") or 0

        # Append to Engagement section
        lines.append("**Web Analytics**")
        lines.append(f"- Page loads: {page_loads:,}")
        lines.append(f"- Unique visits: ~{unique_visits:,}")

        # Top countries
        countries_raw = wa.get("countries")
        if countries_raw:
            if isinstance(countries_raw, str):
                try:
                    countries = json.loads(countries_raw)
                except (json.JSONDecodeError, TypeError):
                    countries = {}
            else:
                countries = countries_raw
            if countries:
                top3 = sorted(countries.items(), key=lambda x: x[1], reverse=True)[:3]
                lines.append(f"- Top countries: {', '.join(f'{c} ({n})' for c, n in top3)}")

        # Device split
        devices_raw = wa.get("devices")
        if devices_raw:
            if isinstance(devices_raw, str):
                try:
                    devices = json.loads(devices_raw)
                except (json.JSONDecodeError, TypeError):
                    devices = {}
            else:
                devices = devices_raw
            if devices:
                parts = [f"{k}: {v}" for k, v in sorted(devices.items(), key=lambda x: x[1], reverse=True)]
                lines.append(f"- Devices: {', '.join(parts)}")
    else:
        lines.append(f"(No web analytics found for {yesterday_str})")

    # ── Data Health: daily_inspiration_defaults ──────────────────────────────
    lines.append("")
    lines.append("**Data Health**")
    try:
        # Count today's defaults
        today_items = await directus.get_items(
            "daily_inspiration_defaults",
            {
                "filter": {"date": {"_eq": today_str}},
                "fields": ["id"],
                "limit": 100,
            },
            admin_required=True,
        )
        today_count = len(today_items) if today_items else 0

        # Count all defaults (check for stale accumulation)
        all_items = await directus.get_items(
            "daily_inspiration_defaults",
            {
                "fields": ["id"],
                "limit": 500,
            },
            admin_required=True,
        )
        total_count = len(all_items) if all_items else 0

        # Expected: 20 languages × 3 entries = 60 for today, ~120 total (today + yesterday)
        status = "OK"
        flags = []
        if today_count < 60:
            flags.append(f"today has {today_count}/60 expected")
        if total_count > 200:
            flags.append(f"stale accumulation: {total_count} total rows (expected ≤120)")

        if flags:
            status = "WARNING — " + "; ".join(flags)

        lines.append(f"- daily_inspiration_defaults: {status}")
        lines.append(f"  (today: {today_count} rows, total: {total_count} rows)")
    except Exception as e:
        lines.append(f"- daily_inspiration_defaults: ERROR — {e}")

    return "\n".join(lines)


async def _query_prod_stats(as_json: bool = False) -> None:
    """Query production server stats via Admin Debug API.

    Uses the same vault-based API key and prod endpoint pattern as debug_logs.py.
    """
    import aiohttp

    sys.path.insert(0, "/app/backend/scripts")
    from debug_utils import get_api_key_from_vault

    # Same constant as debug_logs.py — production Admin Debug API base URL
    PROD_API_BASE = "https://api.openmates.org/v1/admin/debug"

    api_key = await get_api_key_from_vault()
    if not api_key:
        print("Cannot query production: no admin API key in Vault", file=sys.stderr)
        sys.exit(1)

    url = f"{PROD_API_BASE}/server-stats"
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = aiohttp.ClientTimeout(total=60)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"Admin API error {resp.status}: {text[:300]}", file=sys.stderr)
                    sys.exit(1)
                data = await resp.json()
    except Exception as e:
        print(f"Failed to reach production Admin Debug API: {e}", file=sys.stderr)
        sys.exit(1)

    if as_json:
        print(json.dumps(data, indent=2))
        return

    _print_prod_stats_text(data.get("sections", {}), data.get("date", "?"))


def _print_prod_stats_text(sections: dict, date: str) -> None:
    """Format production stats response as readable markdown text."""
    lines = [f"[Production Server Stats — {date}]", ""]

    ug = sections.get("user_growth", {})
    if "error" not in ug:
        lines.append("**User Growth**")
        lines.append(f"- Total registered users: {ug.get('total_users', '?')}")
        lines.append(f"- New registrations: {ug.get('new_registrations', 0)}")
        lines.append(f"- Completed signups: {ug.get('completed_signups', 0)}")
        lines.append("")

    eng = sections.get("engagement", {})
    if "error" not in eng:
        lines.append("**Engagement**")
        lines.append(f"- Messages sent: {eng.get('messages_sent', 0)}")
        lines.append(f"- Chats created: {eng.get('chats_created', 0)}")
        lines.append(f"- Embeds created: {eng.get('embeds_created', 0)}")
        lines.append("")

    rev = sections.get("revenue", {})
    if "error" not in rev:
        lines.append("**Revenue**")
        income = rev.get("income_eur", 0)
        lines.append(f"- Income: EUR {income:.2f}" if isinstance(income, (int, float)) else f"- Income: EUR {income}")
        lines.append(f"- Credits sold: {rev.get('credits_sold', 0)} | used: {rev.get('credits_used', 0)}")
        lines.append(f"- Purchases: {rev.get('purchases', 0)}")
        lines.append(
            f"- Subscriptions: {rev.get('active_subscriptions', '?')} active "
            f"(+{rev.get('subscription_creations', 0)}/-{rev.get('subscription_cancellations', 0)})"
        )
        lines.append("")

    ai = sections.get("ai_usage", {})
    if "error" not in ai:
        lines.append("**AI Usage**")
        lines.append(f"- Input tokens: {ai.get('input_tokens', 0):,}")
        lines.append(f"- Output tokens: {ai.get('output_tokens', 0):,}")
        lines.append("")

    wa = sections.get("web_analytics", {})
    if "error" not in wa:
        lines.append("**Web Analytics**")
        lines.append(f"- Page loads: {wa.get('page_loads', 0):,}")
        lines.append(f"- Unique visits: ~{wa.get('unique_visits', 0):,}")

    nl = sections.get("newsletter", {})
    if "error" not in nl and nl:
        lines.append("")
        lines.append("**Newsletter**")
        lines.append(f"- Confirmed subscribers: {nl.get('confirmed_subscribers', 0):,}")

    dh = sections.get("data_health", {})
    if "error" not in dh and dh:
        lines.append("")
        lines.append("**Data Health**")
        lines.append(f"- daily_inspiration_defaults: today={dh.get('daily_inspiration_today', '?')}, total={dh.get('daily_inspiration_total', '?')}")

    print("\n".join(lines))


def main() -> None:
    """Entry point with --prod and --json flags."""
    import argparse

    parser = argparse.ArgumentParser(description="Query server stats from Directus")
    parser.add_argument("--prod", action="store_true",
                        help="Query production via Admin Debug API instead of local Directus")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output raw JSON (prod mode only)")
    args = parser.parse_args()

    if args.prod:
        asyncio.run(_query_prod_stats(as_json=args.as_json))
    else:
        result = asyncio.run(query_stats())
        print(result)


if __name__ == "__main__":
    main()
