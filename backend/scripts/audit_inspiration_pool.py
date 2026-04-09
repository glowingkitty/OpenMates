#!/usr/bin/env python3
"""
Audit script for daily inspiration pool and defaults — detects content policy violations.

Uses the shared content_filter module with word-boundary regex matching.
No LLM calls — pure deterministic keyword check. Fast, free, and reliable.

Usage:
    # Dry run — report violations (default)
    docker exec api python /app/backend/scripts/audit_inspiration_pool.py

    # Include defaults table
    docker exec api python /app/backend/scripts/audit_inspiration_pool.py --include-defaults

    # JSON output
    docker exec api python /app/backend/scripts/audit_inspiration_pool.py --json

    # Delete violations (asks for confirmation)
    docker exec api python /app/backend/scripts/audit_inspiration_pool.py --delete
"""

import asyncio
import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, '/app')

from backend.apps.ai.daily_inspiration.content_filter import check_entry
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger("audit_inspiration_pool")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _format_entry_summary(entry: Dict[str, Any]) -> str:
    """Format a pool entry as a concise summary."""
    lang = entry.get("language", "?")
    title = entry.get("title", "")[:50]
    video_title = entry.get("video_title", "")[:60]
    channel = entry.get("video_channel_name", "")[:30]
    return f"[{lang}] \"{title}\" — video: \"{video_title}\" (ch: {channel})"


def print_text_report(
    all_results: List[Dict[str, Any]],
    table_name: str,
) -> Tuple[int, int]:
    """Print a formatted text report. Returns (pass_count, reject_count)."""
    rejects = [r for r in all_results if r["verdict"] == "REJECT"]
    passes = [r for r in all_results if r["verdict"] == "PASS"]

    print(f"\n{'=' * 80}")
    print(f"  AUDIT REPORT: {table_name}")
    print(f"{'=' * 80}")
    print(f"  Total entries:  {len(all_results)}")
    print(f"  PASS:           {len(passes)}")
    print(f"  REJECT:         {len(rejects)}")
    print(f"{'=' * 80}")

    if rejects:
        print(f"\n{'─' * 80}")
        print("  VIOLATIONS FOUND")
        print(f"{'─' * 80}")
        for r in rejects:
            entry = r.get("entry", {})
            print(f"\n  ID: {r['entry_id']}")
            print(f"  {_format_entry_summary(entry)}")
            for cat, keywords in r.get("violations", {}).items():
                print(f"  [{cat.upper()}] matched: {', '.join(keywords[:5])}")
            yt_id = entry.get("youtube_id", "")
            if yt_id:
                print(f"  YouTube: https://youtube.com/watch?v={yt_id}")

    if passes and not rejects:
        print("\n  All entries passed.")
    elif passes:
        print(f"\n{'─' * 80}")
        print(f"  PASSED ({len(passes)} entries)")
        print(f"{'─' * 80}")
        for r in passes:
            entry = r.get("entry", {})
            print(f"  OK {_format_entry_summary(entry)}")

    print()
    return len(passes), len(rejects)


async def audit_table(
    directus: DirectusService,
    collection: str,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Fetch all entries from a Directus collection and check them."""
    logger.info(f"Fetching entries from {collection}...")

    sort_key = "-generated_at" if collection == "daily_inspiration_pool" else "-date"
    items = await directus.get_items(
        collection,
        {"sort": [sort_key], "limit": limit},
        admin_required=True,
    )

    if not items:
        logger.info(f"  No entries found in {collection}")
        return []

    logger.info(f"  Found {len(items)} entries — checking keywords...")
    return [check_entry(entry) for entry in items]


async def delete_violations(
    directus: DirectusService,
    results: List[Dict[str, Any]],
    collection: str,
) -> int:
    """Delete rejected entries. Returns count deleted."""
    rejects = [r for r in results if r["verdict"] == "REJECT"]
    deleted = 0
    for r in rejects:
        entry_id = r["entry_id"]
        try:
            success = await directus.delete_item(collection, entry_id)
            if success:
                deleted += 1
                logger.info(f"  Deleted {collection}/{entry_id}")
            else:
                logger.error(f"  Failed to delete {collection}/{entry_id}")
        except Exception as e:
            logger.error(f"  Exception deleting {collection}/{entry_id}: {e}")
    return deleted


async def _query_prod_audit(include_defaults: bool, as_json: bool) -> None:
    """Query the production inspiration audit via the Admin Debug API.

    Mirrors the --prod pattern used in server_stats_query.py.
    """
    import aiohttp

    sys.path.insert(0, "/app/backend/scripts")
    from debug_utils import get_api_key_from_vault

    PROD_API_BASE = "https://api.openmates.org/v1/admin/debug"

    api_key = await get_api_key_from_vault()
    if not api_key:
        print("Cannot query production: no admin API key in Vault", file=sys.stderr)
        sys.exit(1)

    url = f"{PROD_API_BASE}/inspiration-audit"
    params = {"include_defaults": "true" if include_defaults else "false"}
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = aiohttp.ClientTimeout(total=60)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"Admin API error {resp.status}: {text[:300]}", file=sys.stderr)
                    sys.exit(1)
                data = await resp.json()
    except Exception as e:
        print(f"Failed to reach production Admin Debug API: {e}", file=sys.stderr)
        sys.exit(1)

    sections = data.get("sections", {})
    pool_section = sections.get("pool", {}) or {}
    defaults_section = sections.get("defaults", {}) or {}
    pool_results = pool_section.get("results") or []
    defaults_results = defaults_section.get("results") or []

    if as_json:
        output: Dict[str, Any] = {}
        if "error" not in pool_section:
            output["pool"] = {
                "total": pool_section.get("total", len(pool_results)),
                "pass": pool_section.get("pass", 0),
                "reject": pool_section.get("reject", 0),
                "results": pool_results,
            }
        else:
            output["pool"] = pool_section
        if include_defaults:
            if "error" not in defaults_section:
                output["defaults"] = {
                    "total": defaults_section.get("total", len(defaults_results)),
                    "pass": defaults_section.get("pass", 0),
                    "reject": defaults_section.get("reject", 0),
                    "results": defaults_results,
                }
            else:
                output["defaults"] = defaults_section
        print(json.dumps(output, indent=2, default=str))
        return

    print_text_report(pool_results, "daily_inspiration_pool (PROD)")
    if include_defaults and defaults_results:
        print_text_report(defaults_results, "daily_inspiration_defaults (PROD)")


async def main() -> None:
    """Parse CLI arguments and run the audit."""
    parser = argparse.ArgumentParser(
        description="Audit daily inspiration pool for content policy violations",
    )
    parser.add_argument("--include-defaults", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Query production via Admin Debug API instead of local Directus",
    )

    args = parser.parse_args()

    if args.prod:
        if args.delete:
            print("--delete is not supported over --prod (safety: no remote deletes)", file=sys.stderr)
            sys.exit(2)
        await _query_prod_audit(include_defaults=args.include_defaults, as_json=args.json)
        return

    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )

    try:
        pool_results = await audit_table(directus_service, "daily_inspiration_pool")
        defaults_results: List[Dict[str, Any]] = []
        if args.include_defaults:
            defaults_results = await audit_table(directus_service, "daily_inspiration_defaults")

        if args.json:
            output: Dict[str, Any] = {
                "pool": {
                    "total": len(pool_results),
                    "pass": len([r for r in pool_results if r["verdict"] == "PASS"]),
                    "reject": len([r for r in pool_results if r["verdict"] == "REJECT"]),
                    "results": pool_results,
                },
            }
            if defaults_results:
                output["defaults"] = {
                    "total": len(defaults_results),
                    "pass": len([r for r in defaults_results if r["verdict"] == "PASS"]),
                    "reject": len([r for r in defaults_results if r["verdict"] == "REJECT"]),
                    "results": defaults_results,
                }
            print(json.dumps(output, indent=2, default=str))
        else:
            print_text_report(pool_results, "daily_inspiration_pool")
            if defaults_results:
                print_text_report(defaults_results, "daily_inspiration_defaults")

        if args.delete:
            pool_rejects = [r for r in pool_results if r["verdict"] == "REJECT"]
            defaults_rejects = [r for r in defaults_results if r["verdict"] == "REJECT"]
            total = len(pool_rejects) + len(defaults_rejects)
            if total == 0:
                print("\nNo violations to delete.")
            else:
                print(f"\nAbout to delete {total} entries:")
                print(f"  Pool: {len(pool_rejects)}, Defaults: {len(defaults_rejects)}")
                confirm = input("\nType 'yes' to confirm: ")
                if confirm.strip().lower() == "yes":
                    p = await delete_violations(directus_service, pool_results, "daily_inspiration_pool")
                    d = 0
                    if defaults_rejects:
                        d = await delete_violations(directus_service, defaults_results, "daily_inspiration_defaults")
                    print(f"\nDeleted: {p} pool + {d} defaults = {p + d} total")
                else:
                    print("Cancelled.")

    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=True)
        raise
    finally:
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())
