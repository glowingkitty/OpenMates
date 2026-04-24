"""
Stripe product audit and management script.

Commands:
  (no args)              — Read-only audit: list all products, compare against expected
  create-global-products — Create non-EU (global/Managed Payments) products and prices
  --sandbox              — Force sandbox API key (default: auto-detect)
  --production           — Force production API key

Usage (from project root, run inside the api container or with Vault access):
    docker exec api python /app/backend/scripts/stripe_audit.py
    docker exec api python /app/backend/scripts/stripe_audit.py create-global-products
    docker exec api python /app/backend/scripts/stripe_audit.py create-global-products --production
"""
import sys
sys.path.insert(0, '/app')

import stripe
import asyncio
import argparse
from backend.core.api.app.utils.secrets_manager import SecretsManager

# EU (regular Stripe) tiers — EUR only, Adaptive Pricing handles other currencies
EU_PRICING_TIERS = [
    {"credits": 1000,   "price": {"eur": 2}},
    {"credits": 10000,  "price": {"eur": 10},  "monthly_auto_top_up_extra_credits": 500},
    {"credits": 21000,  "price": {"eur": 20},  "monthly_auto_top_up_extra_credits": 1000},
    {"credits": 54000,  "price": {"eur": 50},  "monthly_auto_top_up_extra_credits": 3000},
    {"credits": 110000, "price": {"eur": 100}, "bank_transfer_only": True},
]

# Global (non-EU, Managed Payments) tiers — EUR only, higher prices to cover tax
GLOBAL_PRICING_TIERS = [
    {"credits": 1000,  "price_global": {"eur": 2.50}},
    {"credits": 10000, "price_global": {"eur": 13},  "monthly_auto_top_up_extra_credits": 500},
    {"credits": 21000, "price_global": {"eur": 25},  "monthly_auto_top_up_extra_credits": 1000},
    {"credits": 54000, "price_global": {"eur": 60},  "monthly_auto_top_up_extra_credits": 3000},
]


def _credits_label(n: int) -> str:
    """Format credit count with dot-thousands separator (European style)."""
    return f"{n:,}".replace(",", ".")


def get_expected_eu_product_names() -> set:
    names = set()
    for tier in EU_PRICING_TIERS:
        names.add(_credits_label(tier["credits"]) + " credits")
    for tier in EU_PRICING_TIERS:
        if "monthly_auto_top_up_extra_credits" in tier:
            total = tier["credits"] + tier["monthly_auto_top_up_extra_credits"]
            names.add(_credits_label(total) + " credits (monthly auto top-up)")
    names.add("Supporter Contribution")
    names.add("Monthly Supporter Contribution")
    return names


def get_expected_global_product_names() -> set:
    names = set()
    for tier in GLOBAL_PRICING_TIERS:
        names.add(_credits_label(tier["credits"]) + " credits (global)")
    for tier in GLOBAL_PRICING_TIERS:
        if "monthly_auto_top_up_extra_credits" in tier:
            total = tier["credits"] + tier["monthly_auto_top_up_extra_credits"]
            names.add(_credits_label(total) + " credits (monthly auto top-up, global)")
    return names


async def run_audit():
    sm = SecretsManager()
    await sm.initialize()
    api_key = await sm.get_secret("kv/data/providers/stripe", "sandbox_secret_key")
    env = "SANDBOX"
    if not api_key:
        api_key = await sm.get_secret("kv/data/providers/stripe", "production_secret_key")
        env = "PRODUCTION"

    if not api_key:
        print("ERROR: No Stripe API key found")
        return

    stripe.api_key = api_key
    print(f"\n=== STRIPE PRODUCT AUDIT ({env}) ===\n")

    eu_expected = get_expected_eu_product_names()
    global_expected = get_expected_global_product_names()
    all_expected = eu_expected | global_expected

    print(f"Expected EU products ({len(eu_expected)}):")
    for n in sorted(eu_expected):
        print(f"  - {n}")
    print()
    print(f"Expected global products ({len(global_expected)}):")
    for n in sorted(global_expected):
        print(f"  - {n}")
    print()

    all_active = stripe.Product.list(active=True, limit=100)
    all_inactive = stripe.Product.list(active=False, limit=100)

    print(f"Active products in Stripe: {len(all_active.data)}")
    print(f"Inactive products in Stripe: {len(all_inactive.data)}")
    print()

    expected_found = set()
    stale_products = []

    print("=== ACTIVE PRODUCTS ===")
    for p in sorted(all_active.data, key=lambda x: x.name):
        prices = stripe.Price.list(product=p.id, active=True, limit=100)
        price_summary = []
        for pr in prices.data:
            amt = pr.unit_amount / 100 if pr.currency != "jpy" else pr.unit_amount
            recurring = " (monthly)" if pr.recurring else ""
            price_summary.append(f"{pr.currency.upper()} {amt:.2f}{recurring}")

        is_expected = p.name in all_expected
        status = "✅ EXPECTED" if is_expected else "⚠️  UNEXPECTED"
        if is_expected:
            expected_found.add(p.name)
        else:
            stale_products.append(p)

        print(f"  {status} | {p.name}")
        print(f"    ID: {p.id} | Created: {p.created}")
        print(f"    Prices ({len(prices.data)}): {', '.join(price_summary) or 'none'}")
        meta = dict(p.metadata) if p.metadata else {}
        if meta:
            print(f"    Meta: {meta}")
        print()

    missing = all_expected - expected_found
    if missing:
        print("=== MISSING EXPECTED PRODUCTS ===")
        for n in sorted(missing):
            print(f"  ❌ MISSING: {n}")
        print()

    if all_inactive.data:
        print("=== INACTIVE PRODUCTS (archived) ===")
        for p in sorted(all_inactive.data, key=lambda x: x.name):
            prices_all = stripe.Price.list(product=p.id, active=False, limit=20)
            print(f"  🗄️  {p.name} (ID: {p.id}, {len(prices_all.data)} inactive prices)")
        print()

    print("=== SUMMARY ===")
    print(f"Expected products:   {len(all_expected)}")
    print(f"Found expected:      {len(expected_found)}")
    print(f"Missing:             {len(missing)}")
    print(f"Unexpected/stale:    {len(stale_products)}")
    if stale_products:
        print("\nStale products to consider archiving:")
        for p in stale_products:
            print(f"  - {p.name} (ID: {p.id})")


async def create_global_products(force_env: str | None = None):
    sm = SecretsManager()
    await sm.initialize()

    if force_env == "production":
        api_key = await sm.get_secret("kv/data/providers/stripe", "production_secret_key")
        env = "PRODUCTION"
    elif force_env == "sandbox":
        api_key = await sm.get_secret("kv/data/providers/stripe", "sandbox_secret_key")
        env = "SANDBOX"
    else:
        api_key = await sm.get_secret("kv/data/providers/stripe", "sandbox_secret_key")
        env = "SANDBOX"
        if not api_key:
            api_key = await sm.get_secret("kv/data/providers/stripe", "production_secret_key")
            env = "PRODUCTION"

    if not api_key:
        print("ERROR: No Stripe API key found")
        return

    stripe.api_key = api_key
    print(f"\n=== CREATE GLOBAL PRODUCTS ({env}) ===\n")
    print("These products use Stripe Managed Payments (Checkout Sessions).")
    print("Tax is included in the listed EUR price; Stripe remits VAT automatically.\n")

    # Fetch existing products to avoid duplicates
    existing = {p.name: p for p in stripe.Product.list(active=True, limit=100).auto_paging_iter()}

    created_count = 0

    for tier in GLOBAL_PRICING_TIERS:
        credits = tier["credits"]
        eur_cents = int(round(tier["price_global"]["eur"] * 100))
        product_name = _credits_label(credits) + " credits (global)"

        # One-time purchase product
        if product_name not in existing:
            product = stripe.Product.create(
                name=product_name,
                metadata={"credits": str(credits), "pricing_type": "global"},
            )
            stripe.Price.create(
                product=product.id,
                unit_amount=eur_cents,
                currency="eur",
                tax_behavior="inclusive",  # Tax included in price (Stripe setting for EUR)
                metadata={"credits": str(credits), "pricing_type": "global"},
            )
            print(f"  ✅ Created: {product_name} — EUR {eur_cents / 100:.2f} (one-time)")
            created_count += 1
        else:
            print(f"  ⏭️  Exists:  {product_name}")

        # Monthly subscription product (tiers with bonus credits only)
        if "monthly_auto_top_up_extra_credits" in tier:
            bonus = tier["monthly_auto_top_up_extra_credits"]
            total_credits = credits + bonus
            sub_name = _credits_label(total_credits) + " credits (monthly auto top-up, global)"

            if sub_name not in existing:
                sub_product = stripe.Product.create(
                    name=sub_name,
                    metadata={
                        "credits": str(credits),
                        "bonus_credits": str(bonus),
                        "pricing_type": "global",
                    },
                )
                stripe.Price.create(
                    product=sub_product.id,
                    unit_amount=eur_cents,
                    currency="eur",
                    tax_behavior="inclusive",
                    recurring={"interval": "month"},
                    metadata={"credits": str(credits), "pricing_type": "global"},
                )
                print(f"  ✅ Created: {sub_name} — EUR {eur_cents / 100:.2f}/month")
                created_count += 1
            else:
                print(f"  ⏭️  Exists:  {sub_name}")

    print(f"\nDone — {created_count} new products created in {env}.")
    if created_count > 0:
        print("Run the audit (no args) to verify all products are present.")


async def main():
    parser = argparse.ArgumentParser(description="Stripe product audit and management")
    parser.add_argument("command", nargs="?", default="audit",
                        choices=["audit", "create-global-products"],
                        help="Command to run (default: audit)")
    parser.add_argument("--sandbox", action="store_true", help="Force sandbox environment")
    parser.add_argument("--production", action="store_true", help="Force production environment")
    args = parser.parse_args()

    force_env = None
    if args.production:
        force_env = "production"
    elif args.sandbox:
        force_env = "sandbox"

    if args.command == "create-global-products":
        await create_global_products(force_env=force_env)
    else:
        await run_audit()


asyncio.run(main())
