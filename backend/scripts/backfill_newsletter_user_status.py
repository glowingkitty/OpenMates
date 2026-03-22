#!/usr/bin/env python3
"""
One-time backfill script: populate newsletter_subscribers.user_registration_status
by cross-referencing directus_users.hashed_email.

Both tables store hashed_email as SHA-256(email_bytes).base64encode() — identical algorithm —
so no decryption is needed. We do a pure in-memory set intersection.

Status values:
  not_signed_up     — subscriber hashed_email has no match in directus_users
  signup_incomplete — match found, but directus_users.signup_completed = False
  signup_complete   — match found, and signup_completed = True

Usage:
    # Dry run (shows what WOULD be updated, writes nothing)
    docker exec api python /app/backend/scripts/backfill_newsletter_user_status.py

    # Apply updates (writes to Directus)
    docker exec api python /app/backend/scripts/backfill_newsletter_user_status.py --apply

    # Target production via admin debug CLI (run from dev server):
    docker exec api python /app/backend/scripts/admin_debug_cli.py newsletter-backfill
    (Note: the admin_debug_cli does not yet expose this; run directly on production via SSH+docker exec)
"""

import asyncio
import argparse
import logging
import sys
from typing import Dict, Any

# Add the app to the Python path
sys.path.insert(0, '/app')

from backend.core.api.app.services.directus.directus import DirectusService

# Configure logging — suppress noisy library output
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
script_logger = logging.getLogger('backfill_newsletter')
script_logger.setLevel(logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)


async def fetch_all_subscribers(directus: DirectusService) -> list[Dict[str, Any]]:
    """Fetch all newsletter_subscribers records (id + hashed_email + current status)."""
    url = f"{directus.base_url}/items/newsletter_subscribers"
    resp = await directus._make_api_request(
        "GET",
        url,
        params={
            "fields": "id,hashed_email,user_registration_status",
            "limit": -1,
            "sort": "subscribed_at",
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch newsletter_subscribers: HTTP {resp.status_code} — {resp.text}")
    return resp.json().get("data", [])


async def fetch_all_users(directus: DirectusService) -> Dict[str, bool]:
    """
    Fetch all directus_users records as a dict of {hashed_email: signup_completed}.
    Uses pagination to handle large user tables.
    """
    url = f"{directus.base_url}/users"
    page = 1
    limit = 500
    result: Dict[str, bool] = {}

    while True:
        resp = await directus._make_api_request(
            "GET",
            url,
            params={
                "fields": "hashed_email,signup_completed",
                "limit": limit,
                "page": page,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch users (page {page}): HTTP {resp.status_code} — {resp.text}")

        data = resp.json().get("data", [])
        if not data:
            break

        for user in data:
            h = user.get("hashed_email")
            if h:
                result[h] = bool(user.get("signup_completed", False))

        if len(data) < limit:
            # Last page
            break
        page += 1

    return result


def determine_status(hashed_email: str, users_map: Dict[str, bool]) -> str:
    """
    Return the correct user_registration_status for a newsletter subscriber.

    Args:
        hashed_email: SHA-256/base64 hash of the subscriber's email
        users_map: {hashed_email: signup_completed} for all registered users

    Returns:
        "not_signed_up" | "signup_incomplete" | "signup_complete"
    """
    if hashed_email not in users_map:
        return "not_signed_up"
    return "signup_complete" if users_map[hashed_email] else "signup_incomplete"


async def patch_subscriber_status(
    directus: DirectusService,
    subscriber_id: str,
    status: str,
) -> bool:
    """PATCH a single newsletter_subscribers record with the new status."""
    url = f"{directus.base_url}/items/newsletter_subscribers/{subscriber_id}"
    resp = await directus._make_api_request(
        "PATCH",
        url,
        json={"user_registration_status": status},
    )
    return resp.status_code < 400


async def run(apply: bool) -> None:
    """Main backfill logic."""
    directus = DirectusService()

    try:
        script_logger.info("Fetching newsletter subscribers...")
        subscribers = await fetch_all_subscribers(directus)
        script_logger.info(f"Found {len(subscribers)} subscriber records")

        script_logger.info("Fetching registered users...")
        users_map = await fetch_all_users(directus)
        script_logger.info(f"Found {len(users_map)} user records")

        # --- Calculate what each subscriber's status should be ---
        counts: Dict[str, int] = {"not_signed_up": 0, "signup_incomplete": 0, "signup_complete": 0}
        updates_needed: list[tuple[str, str, str, str | None]] = []  # (id, hashed_email, new_status, old_status)

        for sub in subscribers:
            sub_id = sub.get("id", "")
            hashed_email = sub.get("hashed_email", "")
            current_status = sub.get("user_registration_status")

            if not hashed_email:
                script_logger.warning(f"Subscriber {sub_id} has no hashed_email — skipping")
                continue

            new_status = determine_status(hashed_email, users_map)
            counts[new_status] += 1

            if current_status != new_status:
                updates_needed.append((sub_id, hashed_email, new_status, current_status))

        # --- Summary ---
        print()
        print("=" * 60)
        print("  NEWSLETTER USER REGISTRATION BACKFILL")
        print("=" * 60)
        print()
        print(f"  Total subscribers:    {len(subscribers)}")
        print(f"  Registered users:     {len(users_map)}")
        print()
        print("  COMPUTED STATUS BREAKDOWN")
        print("  " + "-" * 40)
        print(f"  not_signed_up:        {counts['not_signed_up']}")
        print(f"  signup_incomplete:    {counts['signup_incomplete']}")
        print(f"  signup_complete:      {counts['signup_complete']}")
        print()
        print(f"  Records to update:    {len(updates_needed)}")
        already_correct = len(subscribers) - len(updates_needed)
        print(f"  Already correct:      {already_correct}")
        print()

        if not updates_needed:
            print("  Nothing to update — all records are already correct.")
            print("=" * 60)
            return

        # Show first 20 pending changes
        preview_limit = 20
        print("  PENDING CHANGES (first 20)")
        print("  " + "-" * 40)
        for sub_id, hashed_email, new_status, old_status in updates_needed[:preview_limit]:
            old_label = old_status or "null"
            print(f"  {sub_id[:8]}...  {old_label:20s} → {new_status}")
        if len(updates_needed) > preview_limit:
            print(f"  ... and {len(updates_needed) - preview_limit} more")
        print()

        if not apply:
            print("  DRY RUN — no changes written.")
            print("  Re-run with --apply to commit these updates.")
            print("=" * 60)
            return

        # --- Apply updates ---
        print("  APPLYING UPDATES...")
        print("  " + "-" * 40)
        success_count = 0
        fail_count = 0

        for sub_id, hashed_email, new_status, old_status in updates_needed:
            ok = await patch_subscriber_status(directus, sub_id, new_status)
            if ok:
                success_count += 1
            else:
                fail_count += 1
                script_logger.error(f"Failed to update subscriber {sub_id} to status '{new_status}'")

        print(f"  Updated:  {success_count}")
        print(f"  Failed:   {fail_count}")
        print()
        print("=" * 60)

        if fail_count > 0:
            sys.exit(1)

    finally:
        try:
            await directus.close()
        except Exception:
            pass


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill newsletter_subscribers.user_registration_status from directus_users",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (default — shows changes, writes nothing)
  docker exec api python /app/backend/scripts/backfill_newsletter_user_status.py

  # Apply updates
  docker exec api python /app/backend/scripts/backfill_newsletter_user_status.py --apply
        """,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write updates to Directus (default is dry-run)",
    )
    args = parser.parse_args()

    if not args.apply:
        print("\n[DRY RUN MODE] Pass --apply to write changes.\n")

    try:
        asyncio.run(run(apply=args.apply))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        script_logger.error(f"Backfill failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
