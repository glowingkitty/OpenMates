"""
Stripe revenue check — sums all EUR charge balance transactions.

Used to verify the EU VAT OSS threshold status (9,900 EUR safety limit).
The VAT threshold resets each calendar year; pass --all-time to query
all transactions regardless of date.

Usage (inside the api container):
    python /app/backend/scripts/stripe_revenue_check.py
    python /app/backend/scripts/stripe_revenue_check.py --all-time
"""
import sys
sys.path.insert(0, '/app')

import asyncio
import argparse
import stripe
from datetime import datetime, timezone
from backend.core.api.app.utils.secrets_manager import SecretsManager

EU_REVENUE_THRESHOLD_EUR_CENTS = 990_000  # 9,900 EUR safety limit


async def main(all_time: bool = False):
    sm = SecretsManager()
    await sm.initialize()
    api_key = await sm.get_secret("kv/data/providers/stripe", "sandbox_secret_key")
    env = "SANDBOX"
    if not api_key:
        api_key = await sm.get_secret("kv/data/providers/stripe", "production_secret_key")
        env = "PRODUCTION"

    if not api_key:
        print("ERROR: No Stripe API key found in Vault")
        return

    stripe.api_key = api_key
    print(f"\n=== STRIPE EUR REVENUE CHECK ({env}) ===\n")

    params: dict = {"type": "charge", "currency": "eur", "limit": 100}

    if not all_time:
        now = datetime.now(timezone.utc)
        jan1 = int(datetime(now.year, 1, 1, tzinfo=timezone.utc).timestamp())
        params["created"] = {"gte": jan1}
        print(f"Period: {now.year}-01-01 → now")
    else:
        print("Period: all time")

    total_cents = 0
    count = 0

    for txn in stripe.BalanceTransaction.list(**params).auto_paging_iter():
        total_cents += txn.amount
        count += 1

    total_eur = total_cents / 100
    threshold_eur = EU_REVENUE_THRESHOLD_EUR_CENTS / 100
    remaining = max(0, threshold_eur - total_eur)
    pct = (total_eur / threshold_eur * 100) if threshold_eur > 0 else 0

    print(f"Transactions counted : {count}")
    print(f"Total revenue        : EUR {total_eur:,.2f}")
    print(f"Safety threshold     : EUR {threshold_eur:,.2f}")
    print(f"Threshold used       : {pct:.1f}%")
    print(f"Remaining headroom   : EUR {remaining:,.2f}")

    if total_eur >= threshold_eur:
        print("\n⛔  THRESHOLD EXCEEDED — EU payments should be blocked")
    elif total_eur >= threshold_eur * 0.9:
        print("\n⚠️   >90% of threshold used — action needed soon")
    else:
        print("\n✅  Below threshold — EU payments OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check Stripe EUR revenue against EU VAT threshold")
    parser.add_argument("--all-time", action="store_true", help="Query all transactions, not just current year")
    args = parser.parse_args()
    asyncio.run(main(all_time=args.all_time))
