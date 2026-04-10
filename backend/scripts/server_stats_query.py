#!/usr/bin/env python3
"""
scripts/server_stats_query.py

Queries server stats from Directus and Redis for the daily meeting health report.
Runs inside Docker via: docker exec api python3 /app/backend/scripts/server_stats_query.py

Supports --prod flag to query production stats via the Admin Debug API endpoint
(/v1/admin/debug/server-stats) instead of local Directus.

Outputs structured text to stdout with sections:
  - Revenue — Lifetime (total EUR, paying customers, monthly cohort)
  - Revenue — last 14 days (sparkline trend)
  - User Growth (registrations, signups, total users)
  - Engagement (messages, chats, page loads, unique visits)
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
    """Dev stats: short one-line mini summary (dev is not the focus — use --prod for the full report)."""
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
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        items = await directus.get_items(
            "server_stats_global_daily",
            {"filter": {"date": {"_eq": yesterday_str}}, "limit": 1},
            admin_required=True,
        )
        s = items[0] if items else None
    except Exception as e:
        return f"[DEV] stats query failed: {e}"

    if not s:
        return f"[DEV] no stats for {yesterday_str}"

    total_users = s.get("total_regular_users", "?")
    msgs = _int(s.get("messages_sent"))
    embeds = _int(s.get("embeds_created"))
    chats = _int(s.get("chats_created"))
    purchases = _int(s.get("purchase_count"))
    income = _int(s.get("income_eur_cents")) / 100.0
    return (
        f"[DEV] {yesterday_str}: {total_users} users • "
        f"{msgs} msgs / {chats} chats / {embeds} embeds • "
        f"{purchases} purchases, €{income:.2f}"
    )


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


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list) -> str:
    """Render a unicode sparkline from a list of numbers. Zero → space."""
    if not values:
        return ""
    mx = max(values) if values else 0
    if mx == 0:
        return " " * len(values)
    out = []
    for v in values:
        if v <= 0:
            out.append(" ")
        else:
            idx = min(len(_SPARK_CHARS) - 1, int(round(v / mx * (len(_SPARK_CHARS) - 1))))
            out.append(_SPARK_CHARS[idx])
    return "".join(out)


def _print_prod_stats_text(sections: dict, date: str) -> None:
    """Format production stats response with vertical sparklines and 14-day trends."""
    lines = [f"[Production Server Stats — {date}]", ""]

    # ── Lifetime Revenue (lead section — most important metric) ─────────
    lr = sections.get("lifetime_revenue", {})
    inv = sections.get("invoices") or {}
    if "error" not in lr and lr:
        total_eur = lr.get("total_eur", 0)
        total_purchases = lr.get("total_purchases", 0)
        lifetime_buyers = (inv or {}).get("lifetime_unique_buyers", 0)
        total_users = (sections.get("user_growth") or {}).get("total_users")
        pct = ""
        if isinstance(total_users, int) and total_users > 0:
            pct = f" ({lifetime_buyers * 100 / total_users:.1f}% of users)"

        lines.append("**Revenue — Lifetime**")
        lines.append(f"- Total revenue: EUR {total_eur:,.2f}")
        lines.append(f"- Total purchases: {total_purchases:,}")
        lines.append(f"- Paying customers: {lifetime_buyers}{pct}")
        if total_purchases > 0:
            lines.append(f"- Avg per purchase: EUR {total_eur / total_purchases:.2f}")
        if inv and "error" not in inv:
            lines.append(
                f"- Invoices: {inv.get('total_invoices', 0)} total "
                f"({inv.get('paid_invoices', 0)} paid, "
                f"{inv.get('refunded_or_chargeback', 0)} refunded/chargeback)"
            )
        rev = sections.get("revenue") or {}
        lines.append(
            f"- Subscriptions: {rev.get('active_subscriptions', '?')} active"
        )

        # Monthly cohort table
        monthly = lr.get("monthly_trend") or []
        if monthly:
            lines.append("")
            lines.append("**Revenue — Monthly Breakdown**")
            lines.append("  Month     | Revenue     | Purchases | New Buyers | Users")
            lines.append("  ----------|-------------|-----------|------------|------")
            income_vals = [m.get("income_eur", 0) for m in monthly]
            for m in monthly:
                inc = m.get("income_eur", 0)
                pur = m.get("purchases", 0)
                nb = m.get("new_paying_users", 0)
                tu = m.get("total_users", 0)
                lines.append(
                    f"  {m.get('month', '?'):10s}| EUR {inc:>7.2f} | {pur:>9d} | {nb:>10d} | {tu:>5,}"
                )
            lines.append(f"  Revenue   {_sparkline(income_vals)}")
        lines.append("")

    # ── Revenue — last 14 days ──────────────────────────────────────────
    rev = sections.get("revenue", {})
    rev_trend = (rev or {}).get("trend_14d") or []
    if "error" not in rev and rev_trend:
        income_vals = [d.get("income_eur", 0) for d in rev_trend]
        buyer_vals = [d.get("unique_buyers", 0) for d in rev_trend]
        purchase_vals = [d.get("purchases", 0) for d in rev_trend]
        total_income = sum(income_vals)
        total_purchases_14d = sum(purchase_vals)
        avg_per_purchase = (total_income / total_purchases_14d) if total_purchases_14d else 0.0

        lines.append(f"**Revenue — last {len(rev_trend)} days**")
        lines.append(
            f"  Income €  {_sparkline(income_vals)}   sum=€{total_income:.2f}  "
            f"avg/purchase=€{avg_per_purchase:.2f}"
        )
        lines.append(
            f"  Buyers    {_sparkline(buyer_vals)}   "
            f"{total_purchases_14d} purchases across {len(rev_trend)} days"
        )
        lines.append("")
    elif "error" not in rev:
        lines.append("**Revenue (yesterday)**")
        income = rev.get("income_eur", 0)
        lines.append(f"- Income: EUR {income:.2f}" if isinstance(income, (int, float)) else f"- Income: EUR {income}")
        lines.append(f"- Credits sold: {rev.get('credits_sold', 0)} | used: {rev.get('credits_used', 0)}")
        lines.append(f"- Purchases: {rev.get('purchases', 0)}")
        lines.append("")

    # ── User Growth ─────────────────────────────────────────────────────
    ug = sections.get("user_growth", {})
    if "error" not in ug:
        lines.append("**User Growth**")
        lines.append(
            f"- Total users: {ug.get('total_users', '?'):,}"
            if isinstance(ug.get("total_users"), int)
            else f"- Total users: {ug.get('total_users', '?')}"
        )
        lines.append(
            f"- Yesterday: +{ug.get('new_registrations', 0)} registered, "
            f"+{ug.get('completed_signups', 0)} completed signups"
        )
        lines.append("")

    # ── Engagement — 14 day trend ───────────────────────────────────────
    eng = sections.get("engagement", {})
    totals = sections.get("totals") or {}
    trend = (eng or {}).get("trend_14d") or []
    if "error" not in eng and trend:
        msgs = [d.get("messages", 0) for d in trend]
        embeds = [d.get("embeds", 0) for d in trend]
        chats = [d.get("chats", 0) for d in trend]
        first_date = trend[0].get("date") if trend else "?"
        last_date = trend[-1].get("date") if trend else "?"
        lines.append(f"**Engagement — last {len(trend)} days ({first_date} → {last_date})**")
        lines.append(f"  Messages  {_sparkline(msgs)}   sum={sum(msgs):>6,}  max={max(msgs):,}/day")
        lines.append(f"  Embeds    {_sparkline(embeds)}   sum={sum(embeds):>6,}  max={max(embeds):,}/day")
        lines.append(f"  Chats     {_sparkline(chats)}   sum={sum(chats):>6,}  max={max(chats):,}/day")
        if totals:
            lines.append(
                f"- All-time totals: "
                f"{(totals.get('messages') or 0):,} messages • "
                f"{(totals.get('chats') or 0):,} chats • "
                f"{(totals.get('embeds') or 0):,} embeds"
            )
        lines.append("")
    elif "error" not in eng:
        lines.append("**Engagement (yesterday)**")
        lines.append(f"- Messages sent: {eng.get('messages_sent', 0)}")
        lines.append(f"- Chats created: {eng.get('chats_created', 0)}")
        lines.append(f"- Embeds created: {eng.get('embeds_created', 0)}")
        lines.append("")

    # ── AI Usage ────────────────────────────────────────────────────────
    ai = sections.get("ai_usage", {})
    if "error" not in ai:
        lines.append("**AI Usage (yesterday)**")
        lines.append(f"- Input tokens: {ai.get('input_tokens', 0):,}")
        lines.append(f"- Output tokens: {ai.get('output_tokens', 0):,}")
        lines.append("")

    # ── Web Analytics ───────────────────────────────────────────────────
    wa = sections.get("web_analytics", {})
    if "error" not in wa and wa:
        lines.append("**Web Analytics (yesterday)**")
        lines.append(f"- Page loads: {wa.get('page_loads', 0):,}")
        lines.append(f"- Unique visits: ~{wa.get('unique_visits', 0):,}")

    # ── Newsletter ──────────────────────────────────────────────────────
    nl = sections.get("newsletter", {})
    if "error" not in nl and nl:
        lines.append("")
        lines.append("**Newsletter**")
        lines.append(f"- Confirmed subscribers: {nl.get('confirmed_subscribers', 0):,}")

    # ── Data Health ─────────────────────────────────────────────────────
    dh = sections.get("data_health", {})
    if "error" not in dh and dh:
        lines.append("")
        lines.append("**Data Health**")
        lines.append(
            f"- daily_inspiration_defaults: "
            f"today={dh.get('daily_inspiration_today', '?')}, "
            f"total={dh.get('daily_inspiration_total', '?')}"
        )

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
