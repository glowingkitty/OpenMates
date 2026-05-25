#!/usr/bin/env python3
"""
Create an admin-controlled referral campaign budget.

Cloud admins use this script to enable referral rewards without hardcoding a
global budget in application code. Self-hosted deployments can leave referral
campaigns absent, which keeps the frontend referral section hidden.
"""

import argparse
import asyncio
import base64
import hashlib
from datetime import datetime, timezone

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService


def _hash_email(email: str) -> str:
    normalized = email.strip().lower().encode("utf-8")
    return base64.b64encode(hashlib.sha256(normalized).digest()).decode("utf-8")


def _hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


async def _find_user_by_email(directus: DirectusService, email: str) -> dict | None:
    rows = await directus.get_items(
        "users",
        {
            "filter": {"hashed_email": {"_eq": _hash_email(email)}},
            "fields": "id,hashed_email",
            "limit": 1,
        },
        admin_required=True,
    )
    return rows[0] if rows else None


async def _reset_referral_usage(directus: DirectusService, user_id: str) -> None:
    user_hash = _hash_user_id(user_id)
    deleted_rewards = await directus.delete_items(
        "referral_rewards",
        {"recipient_user_id_hash": {"_eq": user_hash}},
        admin_required=True,
    )
    deleted_referred = await directus.delete_items(
        "referral_attributions",
        {"referred_user_id_hash": {"_eq": user_hash}},
        admin_required=True,
    )
    deleted_referrer = await directus.delete_items(
        "referral_attributions",
        {"referrer_user_id_hash": {"_eq": user_hash}},
        admin_required=True,
    )
    profiles = await directus.get_items(
        "referral_profiles",
        {"filter": {"user_id_hash": {"_eq": user_hash}}, "limit": 1},
        admin_required=True,
    )
    if profiles:
        await directus.update_item(
            "referral_profiles",
            profiles[0]["id"],
            {"successful_referrals_count": 0, "disabled_at": None},
            admin_required=True,
        )
    print(
        "Reset referral usage for user "
        f"{user_id}: deleted_rewards={deleted_rewards}, "
        f"deleted_referred_attributions={deleted_referred}, "
        f"deleted_referrer_attributions={deleted_referrer}"
    )


async def _ensure_campaign(directus: DirectusService, args: argparse.Namespace) -> dict:
    existing = await directus.get_items(
        "referral_campaigns",
        {"filter": {"name": {"_eq": args.name}}, "sort": "-created_at", "limit": 1},
        admin_required=True,
    )
    payload = {
        "is_active": True,
        "cloud_only": True,
        "credits_per_referrer": args.referrer_credits,
        "credits_per_referred_user": args.referred_credits,
        "max_total_credits": args.budget,
        "max_successful_referrals_per_user": args.max_per_user,
        "min_purchase_amount_cents": args.min_purchase_cents,
        "attribution_expires_days": args.expires_days,
        "notes": args.notes,
    }
    if existing:
        updated = await directus.update_item(
            "referral_campaigns",
            existing[0]["id"],
            payload,
            admin_required=True,
        )
        if not updated:
            raise SystemExit(f"Failed to update referral campaign {existing[0]['id']}")
        print(f"Updated referral campaign {existing[0]['id']} with budget {args.budget} credits")
        return updated

    success, created = await directus.create_item(
        "referral_campaigns",
        {
            "name": args.name,
            "credits_awarded": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        },
        admin_required=True,
    )
    if not success:
        raise SystemExit(f"Failed to create referral campaign: {created}")
    print(f"Created referral campaign {created.get('id')} with budget {args.budget} credits")
    return created


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create a referral campaign budget")
    parser.add_argument("--name", required=True, help="Admin-facing campaign name")
    parser.add_argument("--budget", type=int, default=60000, help="Maximum total promotional credits")
    parser.add_argument("--referrer-credits", type=int, default=2000)
    parser.add_argument("--referred-credits", type=int, default=2000)
    parser.add_argument("--max-per-user", type=int, default=10)
    parser.add_argument("--min-purchase-cents", type=int, default=1000)
    parser.add_argument("--expires-days", type=int, default=7)
    parser.add_argument("--ensure", action="store_true", help="Update an existing campaign with this name instead of creating a duplicate")
    parser.add_argument("--reset-user-id", help="Reset referral attributions/rewards for a Directus user id")
    parser.add_argument("--reset-user-email", help="Reset referral attributions/rewards for a user looked up by email hash")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    cache = CacheService()
    directus = DirectusService(cache, EncryptionService())
    try:
        if args.ensure:
            await _ensure_campaign(directus, args)
        else:
            success, created = await directus.create_item(
                "referral_campaigns",
                {
                    "name": args.name,
                    "is_active": True,
                    "cloud_only": True,
                    "credits_per_referrer": args.referrer_credits,
                    "credits_per_referred_user": args.referred_credits,
                    "max_total_credits": args.budget,
                    "credits_awarded": 0,
                    "max_successful_referrals_per_user": args.max_per_user,
                    "min_purchase_amount_cents": args.min_purchase_cents,
                    "attribution_expires_days": args.expires_days,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "notes": args.notes,
                },
                admin_required=True,
            )
            if not success:
                raise SystemExit(f"Failed to create referral campaign: {created}")
            print(f"Created referral campaign {created.get('id')} with budget {args.budget} credits")

        reset_user_id = args.reset_user_id
        if args.reset_user_email:
            user = await _find_user_by_email(directus, args.reset_user_email)
            if not user:
                raise SystemExit("Could not find reset user by email hash")
            reset_user_id = user["id"]
        if reset_user_id:
            await _reset_referral_usage(directus, reset_user_id)
    finally:
        await directus.close()
        await cache.close()


if __name__ == "__main__":
    asyncio.run(main())
