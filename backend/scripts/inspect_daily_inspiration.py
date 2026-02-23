#!/usr/bin/env python3
"""
Script to inspect daily inspiration state for a specific user.

This script provides a full debug view of the daily inspiration system for one user,
covering all layers of the architecture:

  1. Cache state (Redis):
     - Topic suggestions (personalization input)
     - Paid-request tracking (eligibility + language)
     - View tracking (how many viewed → how many to generate tomorrow)
     - Pending delivery cache (inspirations waiting for offline user)
     - First-run flag (prevents duplicate first-run generation)

  2. Directus state (persistent storage):
     - All stored user_daily_inspirations records for the user
     - Sorted by generated_at DESC (newest first)

The user is identified by their plain-text user ID (UUID). The script hashes it
internally before querying Directus (SHA-256), matching the storage convention in
user_daily_inspiration_methods.py.

Usage:
    docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id>
    docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --json
    docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --no-directus
    docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --no-cache
    docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py --list-active

Options:
    --json              Output as JSON instead of formatted text
    --no-directus       Skip Directus fetch (cache state only — faster)
    --no-cache          Skip Redis cache fetch (Directus state only)
    --list-active       List all users that currently have a paid-request tracking key
                        (i.e. all users eligible for the next daily generation run)
"""

import asyncio
import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# Add the /app directory to the Python path so backend imports resolve
sys.path.insert(0, '/app')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

# ── Logging configuration ────────────────────────────────────────────────────
# Only show warnings and errors from third-party libraries; our script logs at INFO.
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
script_logger = logging.getLogger('inspect_daily_inspiration')
script_logger.setLevel(logging.INFO)

for noisy_logger in ('httpx', 'httpcore', 'backend'):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# ── Cache key constants (must match cache_inspiration_mixin.py) ──────────────
# These are duplicated here so the script remains self-contained and runnable
# even if the mixin's implementation changes.
_KEY_TOPICS = "daily_inspiration_topics:{user_id}"
_KEY_PAID_REQUEST = "daily_inspiration_last_paid_request:{user_id}"
_KEY_VIEWS = "daily_inspiration_views:{user_id}"
_KEY_PENDING = "daily_inspiration_pending:{user_id}"
_KEY_FIRST_RUN = "daily_inspiration_first_run_done:{user_id}"

# Directus collection for per-user stored inspirations
_DIRECTUS_COLLECTION = "user_daily_inspirations"


# ── Utility helpers ──────────────────────────────────────────────────────────

def _hash_user_id(user_id: str) -> str:
    """SHA-256 hash of a user ID (matches user_daily_inspiration_methods.py)."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def _fmt_ts(ts: Optional[int]) -> str:
    """Format a Unix timestamp as a human-readable string, or return 'N/A'."""
    if not ts:
        return "N/A"
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _trunc(s: Optional[str], max_len: int = 50) -> str:
    """Truncate a string to max_len characters, appending '...' if shortened."""
    if not s:
        return "N/A"
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


# ── Cache layer fetchers ─────────────────────────────────────────────────────

async def fetch_cache_state(cache_service: CacheService, user_id: str) -> Dict[str, Any]:
    """
    Fetch all daily-inspiration cache entries for a user.

    Returns a dict with keys:
        topics        — raw value from daily_inspiration_topics:{user_id}
        paid_request  — raw value from daily_inspiration_last_paid_request:{user_id}
        views         — raw value from daily_inspiration_views:{user_id}
        pending       — raw value from daily_inspiration_pending:{user_id}
        first_run     — raw value (TTL check) from daily_inspiration_first_run_done:{user_id}
        ttls          — dict mapping each key-name to its remaining TTL in seconds
    """
    client = await cache_service.client
    if not client:
        script_logger.error("Redis client is not available — cannot fetch cache state")
        return {}

    keys = {
        "topics": _KEY_TOPICS.format(user_id=user_id),
        "paid_request": _KEY_PAID_REQUEST.format(user_id=user_id),
        "views": _KEY_VIEWS.format(user_id=user_id),
        "pending": _KEY_PENDING.format(user_id=user_id),
        "first_run": _KEY_FIRST_RUN.format(user_id=user_id),
    }

    result: Dict[str, Any] = {}
    ttls: Dict[str, int] = {}

    for name, key in keys.items():
        try:
            raw = await client.get(key)
            ttl = await client.ttl(key)
            if raw and isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            result[name] = raw  # raw JSON string or None
            ttls[name] = ttl    # -1 = no TTL, -2 = key does not exist
        except Exception as e:
            script_logger.error(f"Error fetching cache key '{key}': {e}", exc_info=True)
            result[name] = None
            ttls[name] = -2

    result["ttls"] = ttls
    return result


async def list_active_users(cache_service: CacheService) -> List[Dict[str, Any]]:
    """
    Scan Redis for all daily_inspiration_last_paid_request:* keys.

    Returns a list of dicts with:
        user_id_prefix  — first 8 chars of user_id (for privacy)
        full_key        — the raw Redis key
        language        — stored language code
        last_paid_ts    — Unix timestamp of last paid request
        last_paid_at    — human-readable datetime
        ttl_seconds     — remaining TTL on the key
    """
    client = await cache_service.client
    if not client:
        script_logger.error("Redis client is not available — cannot list active users")
        return []

    pattern = "daily_inspiration_last_paid_request:*"
    try:
        raw_keys = await client.keys(pattern)
    except Exception as e:
        script_logger.error(f"Error scanning Redis keys with pattern '{pattern}': {e}", exc_info=True)
        return []

    active: List[Dict[str, Any]] = []
    for key in raw_keys:
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        user_id = key.split(":", 1)[1] if ":" in key else key

        try:
            raw_val = await client.get(key)
            ttl = await client.ttl(key)
        except Exception as e:
            script_logger.error(f"Error fetching key '{key}': {e}", exc_info=True)
            continue

        data: Dict[str, Any] = {}
        if raw_val:
            if isinstance(raw_val, bytes):
                raw_val = raw_val.decode("utf-8")
            try:
                data = json.loads(raw_val)
            except Exception:
                pass

        ts = data.get("last_paid_request_timestamp")
        active.append({
            "user_id_prefix": user_id[:8] + "..." if len(user_id) > 8 else user_id,
            "full_key": key,
            "language": data.get("language", "?"),
            "last_paid_ts": ts,
            "last_paid_at": _fmt_ts(ts),
            "ttl_seconds": ttl,
        })

    # Sort by last_paid_ts DESC (most recently active first)
    active.sort(key=lambda x: x.get("last_paid_ts") or 0, reverse=True)
    return active


# ── Directus layer fetchers ──────────────────────────────────────────────────

async def fetch_directus_inspirations(
    directus_service: DirectusService,
    user_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Fetch user_daily_inspirations records for a user from Directus.

    Queries by hashed_user_id (SHA-256 of user_id), sorted newest first.
    Returns up to `limit` records (default 20).

    Args:
        directus_service: Initialised DirectusService instance
        user_id: Plain-text user UUID
        limit: Maximum number of records to return

    Returns:
        List of raw Directus record dicts
    """
    hashed_user_id = _hash_user_id(user_id)
    script_logger.debug(
        f"Querying Directus for hashed_user_id={hashed_user_id[:16]}... "
        f"(limit={limit})"
    )

    params = {
        "filter[hashed_user_id][_eq]": hashed_user_id,
        "fields": (
            "id,daily_inspiration_id,embed_id,"
            "encrypted_phrase,encrypted_assistant_response,encrypted_title,"
            "encrypted_category,encrypted_icon,encrypted_video_metadata,"
            "is_opened,opened_chat_id,generated_at,content_type,"
            "created_at,updated_at"
        ),
        "sort": "-generated_at",
        "limit": limit,
    }

    try:
        response = await directus_service.get_items(
            _DIRECTUS_COLLECTION,
            params=params,
            no_cache=True,
        )
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching inspirations from Directus: {e}", exc_info=True)
        return []


# ── Text formatter ───────────────────────────────────────────────────────────

def _format_text(
    user_id: str,
    cache_state: Optional[Dict[str, Any]],
    directus_records: Optional[List[Dict[str, Any]]],
) -> str:
    """
    Build a human-readable inspection report for a user's daily inspiration state.

    Args:
        user_id: Plain-text user UUID (used for display only)
        cache_state: Dict returned by fetch_cache_state(), or None if skipped
        directus_records: List returned by fetch_directus_inspirations(), or None if skipped

    Returns:
        Formatted multi-line string ready for print()
    """
    lines: List[str] = []

    # ── Header ──
    lines.append("")
    lines.append("=" * 100)
    lines.append("DAILY INSPIRATION INSPECTION REPORT")
    lines.append("=" * 100)
    lines.append(f"User ID:      {user_id}")
    lines.append(f"Hashed ID:    {_hash_user_id(user_id)[:32]}...")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Cache state
    # ─────────────────────────────────────────────────────────────────────────
    if cache_state is None:
        lines.append("")
        lines.append("[Cache inspection skipped (--no-cache)]")
    else:
        ttls = cache_state.get("ttls", {})

        def _ttl_str(name: str) -> str:
            """Format TTL for display."""
            t = ttls.get(name, -2)
            if t == -2:
                return "key not found"
            if t == -1:
                return "no expiry"
            hours, rem = divmod(t, 3600)
            mins = rem // 60
            return f"{hours}h {mins}m remaining"

        # ── 1a. Paid-request tracking (eligibility) ──
        lines.append("")
        lines.append("-" * 100)
        lines.append("CACHE — Paid Request Tracking  (key: daily_inspiration_last_paid_request:{user_id})")
        lines.append("-" * 100)

        paid_raw = cache_state.get("paid_request")
        if not paid_raw:
            lines.append("  NOT SET  — user is not eligible for daily generation (no recent paid request)")
        else:
            try:
                paid_data = json.loads(paid_raw)
                ts = paid_data.get("last_paid_request_timestamp")
                lang = paid_data.get("language", "?")
                lines.append(f"  Last paid request:  {_fmt_ts(ts)}  (ts={ts})")
                lines.append(f"  Language:           {lang}")
                lines.append(f"  TTL:                {_ttl_str('paid_request')}")
            except Exception:
                lines.append(f"  [Raw, failed to parse] {_trunc(paid_raw, 80)}")

        # ── 1b. View tracking ──
        lines.append("")
        lines.append("-" * 100)
        lines.append("CACHE — View Tracking  (key: daily_inspiration_views:{user_id})")
        lines.append("-" * 100)

        views_raw = cache_state.get("views")
        if not views_raw:
            lines.append("  NOT SET  — no views tracked (0 inspirations generated tomorrow)")
        else:
            try:
                view_data = json.loads(views_raw)
                viewed_ids = view_data.get("viewed_inspiration_ids", [])
                last_viewed_ts = view_data.get("last_viewed_timestamp")
                lines.append(f"  Viewed count:       {len(viewed_ids)}  (→ {len(viewed_ids)} new inspiration(s) generated tomorrow)")
                lines.append(f"  Last viewed:        {_fmt_ts(last_viewed_ts)}")
                lines.append(f"  TTL:                {_ttl_str('views')}")
                if viewed_ids:
                    lines.append("  Viewed IDs:")
                    for vid in viewed_ids:
                        lines.append(f"    - {vid}")
            except Exception:
                lines.append(f"  [Raw, failed to parse] {_trunc(views_raw, 80)}")

        # ── 1c. Pending delivery cache ──
        lines.append("")
        lines.append("-" * 100)
        lines.append("CACHE — Pending Delivery  (key: daily_inspiration_pending:{user_id})")
        lines.append("-" * 100)

        pending_raw = cache_state.get("pending")
        if not pending_raw:
            lines.append("  NOT SET  — no pending inspirations (user was online at generation time, or none generated yet)")
        else:
            try:
                pending_data = json.loads(pending_raw)
                pending_list = pending_data.get("inspirations", [])
                generated_at = pending_data.get("generated_at")
                lines.append(f"  Pending count:      {len(pending_list)}  (waiting for user to log in)")
                lines.append(f"  Generated at:       {_fmt_ts(generated_at)}")
                lines.append(f"  TTL:                {_ttl_str('pending')}")
                for i, item in enumerate(pending_list, 1):
                    insp_id = item.get("inspiration_id", "?")
                    key_ver = item.get("key_version", "?")
                    enc_len = len(item.get("encrypted_data", "")) if item.get("encrypted_data") else 0
                    lines.append(f"  {i}. inspiration_id={insp_id}  key_version={key_ver}  encrypted_data=[{enc_len} chars]")
            except Exception:
                lines.append(f"  [Raw, failed to parse] {_trunc(pending_raw, 120)}")

        # ── 1d. Topic suggestions ──
        lines.append("")
        lines.append("-" * 100)
        lines.append("CACHE — Topic Suggestions  (key: daily_inspiration_topics:{user_id})")
        lines.append("-" * 100)

        topics_raw = cache_state.get("topics")
        if not topics_raw:
            lines.append("  NOT SET  — no topic suggestions (generation will use generic topics)")
        else:
            try:
                batches = json.loads(topics_raw)
                # Flatten all suggestion strings
                all_suggestions: List[str] = []
                seen: set = set()
                for batch in reversed(batches):
                    for s in batch.get("suggestions", []):
                        if s and s not in seen:
                            all_suggestions.append(s)
                            seen.add(s)
                lines.append(f"  Total batches:      {len(batches)}")
                lines.append(f"  Unique suggestions: {len(all_suggestions)}")
                lines.append(f"  TTL:                {_ttl_str('topics')}")
                lines.append("  Recent suggestions (newest first):")
                for s in all_suggestions[:10]:
                    lines.append(f"    - {s}")
                if len(all_suggestions) > 10:
                    lines.append(f"    ... and {len(all_suggestions) - 10} more")
            except Exception:
                lines.append(f"  [Raw, failed to parse] {_trunc(topics_raw, 120)}")

        # ── 1e. First-run flag ──
        lines.append("")
        lines.append("-" * 100)
        lines.append("CACHE — First-Run Flag  (key: daily_inspiration_first_run_done:{user_id})")
        lines.append("-" * 100)

        first_run_raw = cache_state.get("first_run")
        if not first_run_raw:
            lines.append("  NOT SET  — first-run inspirations have NOT been generated yet (will trigger on next paid request)")
        else:
            lines.append(f"  SET      — first-run inspirations were already generated  (TTL: {_ttl_str('first_run')})")
            lines.append(f"  Value:   {_trunc(str(first_run_raw), 80)}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2 — Directus records
    # ─────────────────────────────────────────────────────────────────────────
    if directus_records is None:
        lines.append("")
        lines.append("[Directus inspection skipped (--no-directus)]")
    else:
        lines.append("")
        lines.append("-" * 100)
        lines.append(f"DIRECTUS — Stored Inspirations (user_daily_inspirations) — {len(directus_records)} record(s)")
        lines.append("-" * 100)

        if not directus_records:
            lines.append("  No records found in Directus for this user.")
        else:
            for i, rec in enumerate(directus_records, 1):
                inspiration_id = rec.get("daily_inspiration_id", "N/A")
                embed_id = rec.get("embed_id") or "—"
                opened_chat = rec.get("opened_chat_id") or "—"
                is_opened = rec.get("is_opened", False)
                content_type = rec.get("content_type", "?")
                generated_at = rec.get("generated_at")
                created_at = rec.get("created_at")
                updated_at = rec.get("updated_at")

                opened_emoji = "✅" if is_opened else "⬜"

                # Encrypted field sizes
                enc_fields = {
                    "phrase":               rec.get("encrypted_phrase"),
                    "assistant_response":   rec.get("encrypted_assistant_response"),
                    "title":                rec.get("encrypted_title"),
                    "category":             rec.get("encrypted_category"),
                    "icon":                 rec.get("encrypted_icon"),
                    "video_metadata":       rec.get("encrypted_video_metadata"),
                }

                lines.append("")
                lines.append(f"  {i}. {opened_emoji} [{content_type}]  generated={_fmt_ts(generated_at)}")
                lines.append(f"     daily_inspiration_id: {inspiration_id}")
                lines.append(f"     embed_id:             {embed_id}")
                lines.append(f"     is_opened:            {is_opened}   opened_chat_id: {opened_chat}")
                lines.append(f"     created_at:           {_fmt_ts(created_at)}   updated_at: {_fmt_ts(updated_at)}")
                lines.append("     Encrypted fields:")
                for field_name, value in enc_fields.items():
                    size = len(value) if value else 0
                    present = "✓" if value else "✗"
                    lines.append(f"       {present} {field_name}: [{size} chars]")

    # ── Footer ──
    lines.append("")
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    lines.append("")

    return "\n".join(lines)


def _format_active_users_text(active_users: List[Dict[str, Any]]) -> str:
    """
    Format the list of active users (--list-active) as a human-readable table.

    Args:
        active_users: List returned by list_active_users()

    Returns:
        Formatted string for print()
    """
    lines: List[str] = []
    lines.append("")
    lines.append("=" * 100)
    lines.append("DAILY INSPIRATION — ACTIVE USERS (daily_inspiration_last_paid_request:*)")
    lines.append("=" * 100)
    lines.append(f"Total eligible users: {len(active_users)}")
    lines.append(f"Generated at:         {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)

    if not active_users:
        lines.append("  No active users found.")
    else:
        col_w = [16, 8, 22, 20]
        header = (
            f"  {'User ID (prefix)':<{col_w[0]}}  "
            f"{'Lang':<{col_w[1]}}  "
            f"{'Last Paid Request':<{col_w[2]}}  "
            f"{'TTL':<{col_w[3]}}"
        )
        lines.append(header)
        lines.append("  " + "-" * (sum(col_w) + 8))
        for user in active_users:
            ttl_s = user.get("ttl_seconds", -2)
            if ttl_s == -2:
                ttl_display = "expired"
            elif ttl_s == -1:
                ttl_display = "no expiry"
            else:
                hours, rem = divmod(ttl_s, 3600)
                ttl_display = f"{hours}h {rem // 60}m"

            row = (
                f"  {user['user_id_prefix']:<{col_w[0]}}  "
                f"{user['language']:<{col_w[1]}}  "
                f"{user['last_paid_at']:<{col_w[2]}}  "
                f"{ttl_display:<{col_w[3]}}"
            )
            lines.append(row)

    lines.append("")
    lines.append("=" * 100)
    lines.append("")
    return "\n".join(lines)


# ── JSON formatters ──────────────────────────────────────────────────────────

def _format_json(
    user_id: str,
    cache_state: Optional[Dict[str, Any]],
    directus_records: Optional[List[Dict[str, Any]]],
) -> str:
    """
    Produce a JSON inspection report for a user.

    The cache fields are parsed from their raw JSON strings for readability.
    Fields that cannot be parsed are left as raw strings.
    """
    def _try_parse(raw: Optional[str]) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    parsed_cache: Optional[Dict[str, Any]] = None
    if cache_state is not None:
        ttls = cache_state.get("ttls", {})
        parsed_cache = {
            "topics":        _try_parse(cache_state.get("topics")),
            "paid_request":  _try_parse(cache_state.get("paid_request")),
            "views":         _try_parse(cache_state.get("views")),
            "pending":       _try_parse(cache_state.get("pending")),
            "first_run":     _try_parse(cache_state.get("first_run")),
            "ttls":          ttls,
        }

    output = {
        "user_id": user_id,
        "hashed_user_id": _hash_user_id(user_id),
        "generated_at": datetime.now().isoformat(),
        "cache": parsed_cache,
        "directus": {
            "count": len(directus_records) if directus_records is not None else None,
            "records": directus_records,
        } if directus_records is not None else None,
    }
    return json.dumps(output, indent=2, default=str)


def _format_active_users_json(active_users: List[Dict[str, Any]]) -> str:
    """Produce a JSON list of active users."""
    output = {
        "generated_at": datetime.now().isoformat(),
        "total": len(active_users),
        "active_users": active_users,
    }
    return json.dumps(output, indent=2, default=str)


# ── Main entry point ─────────────────────────────────────────────────────────

async def main() -> None:
    """
    Parse CLI arguments and run the requested inspection mode.

    Two modes:
    - Default: inspect a specific user by user_id
    - --list-active: scan Redis for all users eligible for daily generation
    """
    parser = argparse.ArgumentParser(
        description="Inspect daily inspiration state for a user",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id>\n"
            "  docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --json\n"
            "  docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id> --no-directus\n"
            "  docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py --list-active\n"
        ),
    )
    parser.add_argument(
        "user_id",
        nargs="?",
        type=str,
        help="User UUID to inspect (required unless --list-active is used)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text",
    )
    parser.add_argument(
        "--no-directus",
        action="store_true",
        help="Skip Directus fetch; show cache state only (faster)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip Redis cache fetch; show Directus state only",
    )
    parser.add_argument(
        "--list-active",
        action="store_true",
        help="List all users currently eligible for daily generation (scans Redis)",
    )

    args = parser.parse_args()

    if not args.list_active and not args.user_id:
        parser.error("user_id is required unless --list-active is specified")

    # ── Initialise services ──
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )

    try:
        # ── Mode: list active users ──────────────────────────────────────────
        if args.list_active:
            active_users = await list_active_users(cache_service)
            if args.json:
                print(_format_active_users_json(active_users))
            else:
                print(_format_active_users_text(active_users))
            return

        # ── Mode: inspect single user ────────────────────────────────────────
        user_id: str = args.user_id

        # 1. Fetch cache state
        cache_state: Optional[Dict[str, Any]] = None
        if not args.no_cache:
            cache_state = await fetch_cache_state(cache_service, user_id)

        # 2. Fetch Directus records
        directus_records: Optional[List[Dict[str, Any]]] = None
        if not args.no_directus:
            directus_records = await fetch_directus_inspirations(directus_service, user_id)

        # 3. Format and print
        if args.json:
            print(_format_json(user_id, cache_state, directus_records))
        else:
            print(_format_text(user_id, cache_state, directus_records))

    except Exception as e:
        script_logger.error(f"Unexpected error during inspection: {e}", exc_info=True)
        raise
    finally:
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())
