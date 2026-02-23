#!/usr/bin/env python3
"""
Manually trigger the creation of 3 daily inspirations for a user and verify the full
generation → pending-cache → Directus persistence pipeline.

This script simulates exactly what happens when the daily Celery job finds a user who
viewed 3 inspirations the previous day:
  1. Sets up the paid-request eligibility key in Redis (so state is realistic)
  2. Calls generate_and_deliver_inspirations_for_user() — the same function used by
     the real daily job and the first-run trigger
  3. Reads the newly-written pending-delivery cache and prints all generated inspirations
     in full detail (phrase, category, YouTube ID, full video URL, thumbnail, etc.)
  4. Prints next-step instructions for verifying the WebSocket delivery → client
     POST → Directus persistence flow

WHY THIS EXISTS:
- The real daily job runs at 06:00 UTC and requires users to have viewed inspirations
  the previous day — hard to trigger manually.
- This script bypasses all eligibility checks and forces immediate generation, letting
  you test the full pipeline at any time without waiting for the scheduler.

NOTE:
- This performs REAL API calls (Brave video search + Mistral LLM). It consumes real
  quota. Do not run in tight loops.
- Pending inspirations are NOT delivered to the client by this script. They sit in Redis
  waiting for the next login (WebSocket delivery hook in websockets.py). Log in as the
  user after running this script to trigger delivery and test the client-side persistence.

Usage:
    docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py <email>
    docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com
    docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --language de
    docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --count 1
    docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --reset-first-run
    docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --no-setup
    docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --json

Options:
    --language <code>   Language for generation (default: en). Controls LLM phrase language
                        and Brave video search locale (e.g. de, es, fr, it, pt, nl).
    --count <n>         Number of inspirations to generate: 1, 2, or 3 (default: 3).
    --reset-first-run   Clear the first-run flag before generating, so the first-run
                        path can be re-tested (daily_inspiration_first_run_done:{user_id}).
    --no-setup          Skip writing the paid_request eligibility key. Use this if you
                        want to test with existing cache state exactly as-is.
    --json              Output report as JSON instead of formatted text.
"""

import asyncio
import argparse
import base64
import hashlib
import json
import logging
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# Add the /app directory to the Python path so backend imports resolve inside Docker
sys.path.insert(0, '/app')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# ── Logging configuration ────────────────────────────────────────────────────
# Show only warnings from third-party libraries; script logs at INFO.
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
script_logger = logging.getLogger('trigger_daily_inspiration')
script_logger.setLevel(logging.INFO)

for _noisy in ('httpx', 'httpcore', 'backend'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ── Cache key constants (must match daily_inspiration_tasks.py / cache_inspiration_mixin.py) ──
_KEY_PAID_REQUEST = "daily_inspiration_last_paid_request:{user_id}"
_KEY_PENDING = "daily_inspiration_pending:{user_id}"
_KEY_FIRST_RUN = "daily_inspiration_first_run_done:{user_id}"
_FIRST_RUN_FLAG_TTL = 7 * 86400  # 7 days
_PAID_REQUEST_TTL = 48 * 3600    # 48 hours


# ── Utility helpers ──────────────────────────────────────────────────────────

def _hash_email(email: str) -> str:
    """
    SHA-256 hash of a normalised email address, base64-encoded.
    Matches the lookup convention used in inspect_user.py and the API's auth flow.
    """
    email_bytes = email.strip().lower().encode('utf-8')
    return base64.b64encode(hashlib.sha256(email_bytes).digest()).decode('utf-8')


def _fmt_ts(ts: Optional[int]) -> str:
    """Format a Unix timestamp as a human-readable string, or return 'N/A'."""
    if not ts:
        return "N/A"
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _fmt_views(n: Optional[int]) -> str:
    """Format a view count as a readable number string, e.g. '1,234,567'."""
    if n is None:
        return "unknown"
    return f"{n:,}"


def _fmt_duration(seconds: Optional[int]) -> str:
    """Format duration seconds as 'm:ss' or 'unknown'."""
    if seconds is None:
        return "unknown"
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins}m{secs:02d}s"


def _fmt_ttl(ttl_seconds: int) -> str:
    """Format a Redis TTL in seconds as 'Xh Ym'."""
    if ttl_seconds == -2:
        return "key not found"
    if ttl_seconds == -1:
        return "no expiry"
    hours, rem = divmod(ttl_seconds, 3600)
    mins = rem // 60
    return f"{hours}h {mins}m"


# ── User lookup ──────────────────────────────────────────────────────────────

async def resolve_user_by_email(
    directus_service: DirectusService,
    email: str,
) -> Optional[Dict[str, Any]]:
    """
    Look up a Directus user record by email address.

    Hashes the email (SHA-256, base64) before querying — matches the storage convention
    used throughout the API and scripts (e.g. inspect_user.py).

    Returns the raw Directus user dict (including 'id'), or None if not found.
    """
    hashed_email = _hash_email(email)
    params = {
        'filter[hashed_email][_eq]': hashed_email,
        'fields': 'id,status,language',
        'limit': 1,
    }
    try:
        url = f"{directus_service.base_url}/users"
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = await directus_service._make_api_request("GET", url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data:
                return data[0]
        script_logger.warning(
            f"User not found for email (hashed: {hashed_email[:16]}..., status: {response.status_code})"
        )
        return None
    except Exception as e:
        script_logger.error(f"Error looking up user by email: {e}", exc_info=True)
        return None


# ── Pre-generation setup ─────────────────────────────────────────────────────

async def setup_eligibility_key(
    cache_service: CacheService,
    user_id: str,
    language: str,
) -> bool:
    """
    Write the paid-request tracking key so the user appears eligible in Redis.

    This mirrors what billing_service.py does after a real paid request. Writing it here
    puts the system in a realistic state even when the user hasn't recently made a paid
    request — important for testing the full pipeline.

    Returns True on success, False on error.
    """
    client = await cache_service.client
    if not client:
        script_logger.error("Redis client unavailable — cannot write eligibility key")
        return False

    key = _KEY_PAID_REQUEST.format(user_id=user_id)
    payload = json.dumps({
        "last_paid_request_timestamp": int(time.time()),
        "language": language or "en",
    })
    try:
        await client.set(key, payload, ex=_PAID_REQUEST_TTL)
        return True
    except Exception as e:
        script_logger.error(f"Failed to write eligibility key: {e}", exc_info=True)
        return False


async def clear_first_run_flag(cache_service: CacheService, user_id: str) -> bool:
    """
    Delete the first-run guard flag so the first-run path can be re-triggered.

    Only called when --reset-first-run is passed. Useful to re-test the first-run
    code path (trigger_first_run_inspirations in daily_inspiration_tasks.py) without
    creating a new user account.

    Returns True on success (including key not existing), False on error.
    """
    client = await cache_service.client
    if not client:
        script_logger.error("Redis client unavailable — cannot clear first-run flag")
        return False

    key = _KEY_FIRST_RUN.format(user_id=user_id)
    try:
        await client.delete(key)
        return True
    except Exception as e:
        script_logger.error(f"Failed to clear first-run flag: {e}", exc_info=True)
        return False


# ── Post-generation read-back ────────────────────────────────────────────────

async def read_pending_cache(
    cache_service: CacheService,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Read the pending inspirations from Redis after generation.

    Returns the full parsed JSON payload from daily_inspiration_pending:{user_id},
    or None if the key is absent.
    """
    client = await cache_service.client
    if not client:
        return None

    key = _KEY_PENDING.format(user_id=user_id)
    try:
        raw = await client.get(key)
        ttl = await client.ttl(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        payload = json.loads(raw)
        payload['_ttl_seconds'] = ttl
        return payload
    except Exception as e:
        script_logger.error(f"Failed to read pending cache: {e}", exc_info=True)
        return None


async def read_cache_key_ttl(cache_service: CacheService, key: str) -> int:
    """Return the TTL in seconds for a Redis key, or -2 if the key does not exist."""
    client = await cache_service.client
    if not client:
        return -2
    try:
        return await client.ttl(key)
    except Exception:
        return -2


# ── Output formatters ────────────────────────────────────────────────────────

def _build_video_url(youtube_id: str) -> str:
    """Build the full YouTube watch URL from a video ID."""
    return f"https://www.youtube.com/watch?v={youtube_id}"


# Banner UI strings (English — from daily_inspiration.yml i18n source)
_BANNER_LABEL = "Daily inspiration"
_BANNER_CTA = "Click to start chat"

# Human-readable labels for each category slug (mirrors categoryUtils.ts + mate names)
_CATEGORY_LABELS: Dict[str, str] = {
    "software_development":     "Software Development",
    "business_development":     "Business Development",
    "medical_health":           "Medical & Health",
    "openmates_official":       "OpenMates Official",
    "maker_prototyping":        "Maker & Prototyping",
    "marketing_sales":          "Marketing & Sales",
    "finance":                  "Finance",
    "design":                   "Design",
    "electrical_engineering":   "Electrical Engineering",
    "movies_tv":                "Movies & TV",
    "history":                  "History",
    "science":                  "Science",
    "life_coach_psychology":    "Life Coach & Psychology",
    "cooking_food":             "Cooking & Food",
    "activism":                 "Activism",
    "general_knowledge":        "General Knowledge",
}


def _category_label(category: str) -> str:
    """Return the human-readable mate/assistant name for a category slug."""
    return _CATEGORY_LABELS.get(category, category)


def _build_assistant_response(phrase: str, youtube_id: str, video_url: str) -> str:
    """
    Reconstruct the full first assistant message as it will appear in the chat.

    This exactly mirrors what handleStartChatFromInspiration() builds client-side
    (ActiveChat.svelte:3914): the phrase followed by an embed reference JSON block.
    The embed_id shown here is a placeholder — the real UUID is generated by the
    client at chat-creation time — but the structure is identical.

    Format:
        <phrase>

        ```json
        {
          "type": "video",
          "embed_id": "<client-generated-uuid>",
          "url": "<video_url>"
        }
        ```
    """
    embed_reference = (
        '```json\n'
        '{\n'
        '  "type": "video",\n'
        '  "embed_id": "<client-generated-uuid>",\n'
        f'  "url": "{video_url}"\n'
        '}\n'
        '```'
    )
    return f"{phrase}\n\n{embed_reference}"


def _format_report_text(
    email: str,
    user_id: str,
    count: int,
    language: str,
    setup_done: bool,
    reset_first_run: bool,
    generation_succeeded: bool,
    generation_error: Optional[str],
    pending_payload: Optional[Dict[str, Any]],
    paid_req_ttl: int,
    first_run_ttl: int,
    run_started_at: datetime,
) -> str:
    """
    Build the human-readable trigger report.

    Args:
        email: Plain-text email address (display only — never logged elsewhere)
        user_id: Resolved user UUID
        count: Number of inspirations requested
        language: Language code used for generation
        setup_done: Whether the paid-request eligibility key was written
        reset_first_run: Whether the first-run flag was cleared before generating
        generation_succeeded: Whether generate_and_deliver_inspirations_for_user() returned True
        generation_error: Error message if generation failed, else None
        pending_payload: Parsed pending-cache JSON, or None if not found / generation failed
        paid_req_ttl: TTL of the paid_request key after generation
        first_run_ttl: TTL of the first_run flag after generation
        run_started_at: datetime when the script started running
    """
    lines: List[str] = []
    W = 100

    lines.append("")
    lines.append("=" * W)
    lines.append("DAILY INSPIRATION — MANUAL TRIGGER")
    lines.append("=" * W)
    lines.append(f"Email:        {email}")
    lines.append(f"User ID:      {user_id}")
    lines.append(f"Count:        {count}")
    lines.append(f"Language:     {language}")
    lines.append(f"Triggered at: {run_started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * W)

    # ── Setup steps ──
    lines.append("")
    lines.append("-" * W)
    lines.append("SETUP")
    lines.append("-" * W)
    lines.append(
        f"  Eligibility key written:  {'YES' if setup_done else 'SKIPPED (--no-setup)'}  "
        f"  (daily_inspiration_last_paid_request:{user_id[:8]}...)"
    )
    lines.append(
        f"  First-run flag cleared:   {'YES' if reset_first_run else 'NO (pass --reset-first-run to clear it)'}"
    )

    # ── Generation result ──
    lines.append("")
    lines.append("-" * W)
    lines.append("GENERATION")
    lines.append("-" * W)
    if generation_succeeded:
        lines.append("  Result:  SUCCESS")
    else:
        lines.append("  Result:  FAILED")
        if generation_error:
            lines.append(f"  Error:   {generation_error}")
        lines.append("")
        lines.append("  Check logs with:")
        lines.append("    docker compose logs --tail=50 app-ai-worker")
        return "\n".join(lines)

    # ── Generated inspirations ──
    lines.append("")
    lines.append("-" * W)

    if not pending_payload:
        lines.append("GENERATED INSPIRATIONS — (pending cache not found after generation)")
        lines.append("  This should not happen. Check app-ai-worker logs.")
    else:
        inspirations = pending_payload.get("inspirations", [])
        generated_ts = pending_payload.get("generated_at")
        lines.append(
            f"GENERATED INSPIRATIONS ({len(inspirations)})  "
            f"— generated at {_fmt_ts(generated_ts)}"
        )
        lines.append("-" * W)

        for i, insp in enumerate(inspirations, 1):
            # The pending cache stores plaintext inspiration dicts (DailyInspiration.model_dump())
            inspiration_id = insp.get("inspiration_id", "?")
            phrase = insp.get("phrase", "?")
            category = insp.get("category", "?")
            content_type = insp.get("content_type", "video")
            insp_generated_at = insp.get("generated_at")

            video = insp.get("video") or {}
            youtube_id = video.get("youtube_id", "")
            title = video.get("title", "?")
            channel = video.get("channel_name") or "unknown"
            view_count = video.get("view_count")
            duration_seconds = video.get("duration_seconds")
            thumbnail_url = video.get("thumbnail_url") or (
                f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg" if youtube_id else "N/A"
            )
            published_at = video.get("published_at") or "unknown"

            video_url = _build_video_url(youtube_id) if youtube_id else "N/A"
            assistant_response = _build_assistant_response(phrase, youtube_id, video_url) if youtube_id else phrase

            lines.append("")
            lines.append(f"  {i}. [{content_type}] [{category}]  generated={_fmt_ts(insp_generated_at)}")
            lines.append(f"     Inspiration ID:  {inspiration_id}")
            lines.append("")
            lines.append(f"     Banner label:    {_BANNER_LABEL}")
            lines.append(f"     Phrase:          \"{phrase}\"")
            lines.append(f"     CTA text:        {_BANNER_CTA}")
            lines.append(f"     Mate/Assistant:  {_category_label(category)}  (category: {category})")
            lines.append("")
            lines.append(f"     YouTube ID:      {youtube_id}")
            lines.append(f"     Video URL:       {video_url}")
            lines.append(f"     Title:           {title}")
            lines.append(f"     Channel:         {channel}")
            lines.append(f"     Views:           {_fmt_views(view_count)}")
            lines.append(f"     Duration:        {_fmt_duration(duration_seconds)}")
            lines.append(f"     Published:       {published_at}")
            lines.append(f"     Thumbnail URL:   {thumbnail_url}")
            lines.append("")
            lines.append("     Full assistant response (shown in chat when user clicks banner):")
            for resp_line in assistant_response.splitlines():
                lines.append(f"       {resp_line}")

    # ── Cache state summary ──
    lines.append("")
    lines.append("-" * W)
    lines.append("CACHE STATE AFTER GENERATION")
    lines.append("-" * W)
    pending_ttl = (pending_payload or {}).get('_ttl_seconds', -2)
    lines.append(
        f"  Pending cache:     "
        f"{len((pending_payload or {}).get('inspirations', []))} inspiration(s) stored  "
        f"(TTL: {_fmt_ttl(pending_ttl)})"
    )
    lines.append(
        f"  Paid-request key:  TTL {_fmt_ttl(paid_req_ttl)}"
        f"  (daily_inspiration_last_paid_request:{user_id[:8]}...)"
    )
    lines.append(
        f"  First-run flag:    TTL {_fmt_ttl(first_run_ttl)}"
        f"  (daily_inspiration_first_run_done:{user_id[:8]}...)"
    )
    lines.append(
        "  Views key:         cleared  (reset for next generation cycle)"
    )

    # ── Next steps ──
    lines.append("")
    lines.append("-" * W)
    lines.append("NEXT STEPS — verify WebSocket delivery and Directus persistence")
    lines.append("-" * W)
    lines.append("  1. Log in as this user in the browser (or refresh an existing session).")
    lines.append("     The WebSocket login handler (websockets.py) will pick up the pending")
    lines.append("     inspirations and deliver them via 'daily_inspiration' WS event.")
    lines.append("")
    lines.append("  2. The client will:")
    lines.append("     a) Display the inspirations in the carousel")
    lines.append("     b) POST each to  POST /v1/daily-inspirations  (persists to Directus)")
    lines.append("     c) Send a 'daily_inspiration_received' ACK (clears the pending cache)")
    lines.append("")
    lines.append("  3. Verify persistence in Directus and full state with:")
    lines.append(f"     docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py {user_id}")

    lines.append("")
    lines.append("=" * W)
    lines.append("END OF REPORT")
    lines.append("=" * W)
    lines.append("")

    return "\n".join(lines)


def _format_report_json(
    email: str,
    user_id: str,
    count: int,
    language: str,
    setup_done: bool,
    reset_first_run: bool,
    generation_succeeded: bool,
    generation_error: Optional[str],
    pending_payload: Optional[Dict[str, Any]],
    paid_req_ttl: int,
    first_run_ttl: int,
    run_started_at: datetime,
) -> str:
    """Produce the JSON equivalent of the trigger report."""
    inspirations_out: List[Dict[str, Any]] = []

    if pending_payload:
        for insp in pending_payload.get("inspirations", []):
            video = insp.get("video") or {}
            youtube_id = video.get("youtube_id", "")
            video_url = _build_video_url(youtube_id) if youtube_id else None
            phrase = insp.get("phrase", "")
            category = insp.get("category", "")
            inspirations_out.append({
                "inspiration_id": insp.get("inspiration_id"),
                "banner_label": _BANNER_LABEL,
                "phrase": phrase,
                "cta_text": _BANNER_CTA,
                "mate_assistant": _category_label(category),
                "category": category,
                "content_type": insp.get("content_type"),
                "generated_at": insp.get("generated_at"),
                "assistant_response": _build_assistant_response(phrase, youtube_id, video_url or "") if youtube_id else phrase,
                "video": {
                    "youtube_id": youtube_id,
                    "video_url": video_url,
                    "title": video.get("title"),
                    "channel_name": video.get("channel_name"),
                    "view_count": video.get("view_count"),
                    "duration_seconds": video.get("duration_seconds"),
                    "published_at": video.get("published_at"),
                    "thumbnail_url": video.get("thumbnail_url"),
                },
            })

    output = {
        "triggered_at": run_started_at.isoformat(),
        "email_prefix": email[:3] + "***" if len(email) > 3 else "***",
        "user_id": user_id,
        "count_requested": count,
        "language": language,
        "setup": {
            "eligibility_key_written": setup_done,
            "first_run_flag_cleared": reset_first_run,
        },
        "generation": {
            "succeeded": generation_succeeded,
            "error": generation_error,
        },
        "inspirations": inspirations_out,
        "cache_after": {
            "pending_count": len(inspirations_out),
            "pending_ttl_seconds": (pending_payload or {}).get('_ttl_seconds', -2),
            "paid_request_ttl_seconds": paid_req_ttl,
            "first_run_ttl_seconds": first_run_ttl,
        },
    }
    return json.dumps(output, indent=2, default=str)


# ── Main entry point ─────────────────────────────────────────────────────────

async def main() -> None:
    """
    Parse CLI arguments, resolve the user, set up cache state, generate inspirations,
    and print a detailed report.
    """
    parser = argparse.ArgumentParser(
        description="Manually trigger daily inspiration generation for a user",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com\n"
            "  docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --language de\n"
            "  docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --count 1\n"
            "  docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --reset-first-run\n"
            "  docker exec -it api python /app/backend/scripts/trigger_daily_inspiration.py user@example.com --json\n"
            "\n"
            "After running, log in as the user to trigger WebSocket delivery, then run:\n"
            "  docker exec -it api python /app/backend/scripts/inspect_daily_inspiration.py <user_id>\n"
        ),
    )
    parser.add_argument(
        "email",
        type=str,
        help="Email address of the user to generate inspirations for",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="en",
        metavar="CODE",
        help=(
            "Language code for generation (default: en). Controls the LLM phrase language "
            "and Brave video search locale. Examples: de, es, fr, it, pt, nl, pl, ru, ja."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="Number of inspirations to generate: 1, 2, or 3 (default: 3)",
    )
    parser.add_argument(
        "--reset-first-run",
        action="store_true",
        help=(
            "Clear the daily_inspiration_first_run_done:{user_id} flag before generating. "
            "Use this to re-test the first-run code path."
        ),
    )
    parser.add_argument(
        "--no-setup",
        action="store_true",
        help=(
            "Skip writing the paid_request eligibility key. "
            "Useful when you want to test with the exact existing cache state."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON instead of formatted text",
    )

    args = parser.parse_args()
    run_started_at = datetime.now()

    # ── Initialise services ──────────────────────────────────────────────────
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )
    secrets_manager = SecretsManager(cache_service=cache_service)

    # Track state for the final report
    generation_succeeded = False
    generation_error: Optional[str] = None
    setup_done = False
    reset_first_run_done = False
    pending_payload: Optional[Dict[str, Any]] = None
    paid_req_ttl = -2
    first_run_ttl = -2
    user_id: Optional[str] = None

    try:
        # ── Step 1: Initialise SecretsManager (Vault connection) ─────────────
        script_logger.info("Initialising SecretsManager (Vault connection)...")
        try:
            await secrets_manager.initialize()
            script_logger.info("SecretsManager initialised")
        except Exception as e:
            print(f"ERROR: Failed to initialise SecretsManager: {e}", file=sys.stderr)
            sys.exit(1)

        # ── Step 2: Resolve user by email ────────────────────────────────────
        script_logger.info(f"Looking up user by email (length: {len(args.email)})...")
        user_record = await resolve_user_by_email(directus_service, args.email)
        if not user_record:
            print(
                f"ERROR: No user found for email '{args.email}'. "
                "Check the address and ensure the account exists in Directus.",
                file=sys.stderr,
            )
            sys.exit(1)

        user_id = user_record.get("id")
        if not user_id:
            print("ERROR: User record is missing 'id' field.", file=sys.stderr)
            sys.exit(1)

        # Use the user's stored language as the default if --language was not explicitly set
        # (args.language defaults to "en", so if the user set it explicitly we always honour it)
        effective_language = args.language

        script_logger.info(
            f"Resolved user {user_id[:8]}... (language: {effective_language}, count: {args.count})"
        )

        # ── Step 3: Optional — clear first-run flag ──────────────────────────
        if args.reset_first_run:
            script_logger.info("Clearing first-run flag...")
            ok = await clear_first_run_flag(cache_service, user_id)
            if ok:
                reset_first_run_done = True
                script_logger.info("First-run flag cleared")
            else:
                script_logger.warning("Failed to clear first-run flag — continuing anyway")

        # ── Step 4: Optional — write eligibility key ─────────────────────────
        if not args.no_setup:
            script_logger.info("Writing paid-request eligibility key...")
            ok = await setup_eligibility_key(cache_service, user_id, effective_language)
            if ok:
                setup_done = True
                script_logger.info("Eligibility key written")
            else:
                script_logger.warning("Failed to write eligibility key — continuing anyway")
        else:
            script_logger.info("Skipping eligibility key setup (--no-setup)")

        # ── Step 5: Generate and deliver inspirations ────────────────────────
        from backend.core.api.app.tasks.daily_inspiration_tasks import (
            generate_and_deliver_inspirations_for_user,
        )

        script_logger.info(
            f"Generating {args.count} inspiration(s) for user {user_id[:8]}... "
            f"(language: {effective_language}) — this may take 15-30 seconds..."
        )
        try:
            generation_succeeded = await generate_and_deliver_inspirations_for_user(
                user_id=user_id,
                count=args.count,
                cache_service=cache_service,
                secrets_manager=secrets_manager,
                task_id="trigger_daily_inspiration_script",
                is_online=False,    # Always use pending cache (same as the daily job)
                task_instance=None,
                language=effective_language,
            )
        except Exception as e:
            generation_error = str(e)
            script_logger.error(f"Generation raised an exception: {e}", exc_info=True)
            generation_succeeded = False

        # ── Step 6: Read back the pending cache ──────────────────────────────
        if generation_succeeded:
            pending_payload = await read_pending_cache(cache_service, user_id)

        # ── Step 7: Read TTLs for the cache state summary ────────────────────
        client = await cache_service.client
        if client:
            try:
                paid_req_ttl = await client.ttl(_KEY_PAID_REQUEST.format(user_id=user_id))
                first_run_ttl = await client.ttl(_KEY_FIRST_RUN.format(user_id=user_id))
            except Exception:
                pass  # TTLs are informational — don't abort on error

    finally:
        # Always close the Directus HTTP session, even on error
        try:
            await directus_service.close()
        except Exception:
            pass

    # ── Step 8: Print report ─────────────────────────────────────────────────
    if user_id is None:
        # Should not reach here (sys.exit above) but guard just in case
        print("ERROR: User resolution failed before generating a report.", file=sys.stderr)
        sys.exit(1)

    report_kwargs = dict(
        email=args.email,
        user_id=user_id,
        count=args.count,
        language=effective_language,
        setup_done=setup_done,
        reset_first_run=reset_first_run_done,
        generation_succeeded=generation_succeeded,
        generation_error=generation_error,
        pending_payload=pending_payload,
        paid_req_ttl=paid_req_ttl,
        first_run_ttl=first_run_ttl,
        run_started_at=run_started_at,
    )

    if args.json:
        print(_format_report_json(**report_kwargs))
    else:
        print(_format_report_text(**report_kwargs))


if __name__ == "__main__":
    asyncio.run(main())
