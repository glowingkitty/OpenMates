#!/usr/bin/env python3
"""
Unified user activity timeline — combines backend logs, compliance events,
container logs, client console logs, and satellite server logs for a single user.

Produces a chronologically sorted timeline showing every action a user triggered
across all services, for debugging and issue investigation.

Architecture context: See docs/claude/inspection-scripts.md

Usage:
    # Dev server (default) — last 24 hours
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com

    # Last 2 hours only
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --since 120

    # Production logs (via Admin Debug API)
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --prod

    # Filter by category (auth, chat, sync, embed, usage, settings, client, error)
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --category auth,chat

    # Filter by level (warning = warning+error+critical)
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --level warning

    # Filter by chat
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --chat-id <chat_id>

    # Follow mode (poll every 5s)
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --follow

    # JSON output
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --json

    # Show raw log lines alongside parsed events
    docker exec api python /app/backend/scripts/inspect_user_logs.py user@example.com --verbose
"""

import asyncio
import argparse
import hashlib
import base64
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

import aiohttp

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')
sys.path.insert(0, '/app')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging — suppress everything except our output
logging.basicConfig(level=logging.WARNING, format='%(message)s')
script_logger = logging.getLogger('inspect_user_logs')
script_logger.setLevel(logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)

# ─── Constants ────────────────────────────────────────────────────────────────

LOKI_URL = "http://loki:3100"
DEFAULT_SINCE_MINUTES = 1440  # 24 hours
MAX_LOKI_ENTRIES = 5000
FOLLOW_POLL_INTERVAL_SECONDS = 5

UPLOAD_SERVER_LOG_URL = "https://upload.openmates.org/admin/logs"
PREVIEW_SERVER_LOG_URL = "https://preview.openmates.org/admin/logs"

# ANSI colour codes
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_GREEN = "\033[92m"
C_CYAN = "\033[96m"
C_BLUE = "\033[94m"
C_MAGENTA = "\033[95m"
C_GRAY = "\033[90m"

# Category → colour mapping
CATEGORY_COLORS = {
    "auth": C_GREEN,
    "chat": C_CYAN,
    "sync": C_BLUE,
    "embed": C_MAGENTA,
    "usage": C_YELLOW,
    "payment": C_YELLOW,
    "settings": C_BLUE,
    "client": C_GRAY,
    "error": C_RED,
    "other": C_DIM,
}

LEVEL_SEVERITY = {"debug": 0, "info": 1, "warn": 2, "warning": 2, "error": 3, "critical": 4}


# ─── Event pattern matching ──────────────────────────────────────────────────

# Each tuple: (regex_pattern, category, event_name)
# Order matters — first match wins.
EVENT_PATTERNS: List[Tuple[str, str, str]] = [
    # Auth
    (r"login.?success|Login successful|finalize_login_session", "auth", "login_success"),
    (r"login.?failed|Authentication failed|login_failed", "auth", "login_failed"),
    (r"User account created|signup.*success", "auth", "signup"),
    (r"Token.*refresh|token_refresh|Token expires soon|Token refreshed", "auth", "token_refresh"),
    (r"forced.?logout|Forced logout", "auth", "forced_logout"),
    (r"2FA.*verif|tfa.*success|2fa_verified|tfa_enabled", "auth", "2fa_event"),
    (r"Session valid for user", "auth", "session_valid"),
    (r"Re-auth triggered", "auth", "re_auth_triggered"),

    # Chat / message processing
    (r"\[PERF\] Message handler started", "chat", "message_received"),
    (r"\[PERF\] Vault key retrieval took", "chat", "vault_key_retrieved"),
    (r"\[PERF\] Message encryption took", "chat", "message_encrypted"),
    (r"\[PERF\] Cache save took", "chat", "message_cached"),
    (r"\[PERF\] Cache fetch for AI history", "chat", "ai_history_fetched"),
    (r"\[PERF\] Message history construction took", "chat", "history_constructed"),
    (r"\[PERF\] AI app call took|AI app ask skill executed", "chat", "ai_dispatched"),
    (r"\[PERF\] Message handler completed", "chat", "message_completed"),
    (r"\[PERF\] Message handler failed", "chat", "message_failed"),
    (r"Streaming response|AI response|stream_consumer.*finished", "chat", "ai_response"),
    (r"chat ownership|Rejecting message.*read-only", "chat", "ownership_rejected"),

    # Sync
    (r"warm_user_cache|Cache warm|TASK_ENTRY_SYNC_WRAPPER.*warm_user_cache", "sync", "cache_warm"),
    (r"PHASE1|Phase 1|phase_1_last_chat_ready", "sync", "phase1_sync"),
    (r"phase_2_last_20|Phase 2", "sync", "phase2_sync"),
    (r"phase_3_last_100|Phase 3|cache_primed", "sync", "phase3_sync"),
    (r"SYNC_CACHE_UPDATE|sync_cache_update", "sync", "sync_cache_update"),
    (r"WebSocket connection established for user_id", "sync", "ws_connect"),
    (r"WebSocket connection closed|WebSocket.*disconnect", "sync", "ws_disconnect"),
    (r"WebSocket.*error|ConnectionResetError", "sync", "ws_error"),

    # Embed
    (r"[Ee]mbed resolved|resolve_embed", "embed", "embed_resolved"),
    (r"embed.*expired|key expired", "embed", "embed_expired"),
    (r"embed.*created|store_embed", "embed", "embed_created"),
    (r"Code block extraction took", "embed", "code_embed_extracted"),

    # Usage / billing
    (r"[Cc]redits.*charged|Credits charged", "usage", "credits_charged"),
    (r"usage.*recorded", "usage", "usage_recorded"),
    (r"billing|invoice|payment|refund|Polar", "payment", "payment_event"),

    # Settings
    (r"[Ll]anguage.*changed|Updating language", "settings", "language_changed"),
    (r"profile.*updated|profile.*image", "settings", "profile_updated"),
    (r"passkey|api_key.*created|device.*record", "settings", "account_setting_changed"),

    # Errors — these are overridden by log level in classify_event()
]

_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), cat, evt) for p, cat, evt in EVENT_PATTERNS]


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class LogEvent:
    """A single parsed log event in the user activity timeline."""
    timestamp: str  # ISO-8601
    timestamp_ns: int  # nanoseconds since epoch (for sorting)
    category: str
    event_name: str
    source: str  # api, task-worker, app-ai, browser, upload, preview, compliance
    level: str  # debug, info, warn, error
    message: str  # Human-readable summary
    raw: str = ""  # Original log line (shown in --verbose mode)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─── User resolution ─────────────────────────────────────────────────────────

def hash_email_sha256(email: str) -> str:
    """Hash email using SHA-256 (base64) for Directus lookup."""
    return base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()


def hash_user_id(user_id: str) -> str:
    """Hash user ID using SHA-256 (hex) for related item lookup."""
    return hashlib.sha256(user_id.encode()).hexdigest()


async def resolve_user(email: str) -> Optional[Dict[str, Any]]:
    """Resolve email → user_id, chat_ids, is_admin, etc."""
    sm = SecretsManager()
    await sm.initialize()

    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)

    try:
        # Look up user
        hashed_email = hash_email_sha256(email)
        url = f"{directus_service.base_url}/users"
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        headers = {"Authorization": f"Bearer {admin_token}"}
        params = {
            'filter[hashed_email][_eq]': hashed_email,
            'fields': 'id,status,is_admin,vault_key_id,account_id',
            'limit': 1,
        }
        resp = await directus_service._make_api_request("GET", url, params=params, headers=headers)
        if resp.status_code != 200:
            return None
        users = resp.json().get("data", [])
        if not users:
            return None

        user = users[0]
        user_id = user["id"]
        h_uid = hash_user_id(user_id)

        # Get chat IDs for this user (for cross-referencing in container logs)
        chat_params = {
            'filter[hashed_user_id][_eq]': h_uid,
            'sort': '-updated_at',
            'limit': 50,
            'fields': 'id',
        }
        chats_resp = await directus_service.get_items('chats', params=chat_params, no_cache=True)
        chat_ids = [c['id'] for c in (chats_resp or []) if c.get('id')]

        # Check admin status from server_admins collection
        is_admin = await directus_service.admin.is_user_admin(user_id)

        # Try to get admin username from Directus (for client console log queries)
        admin_username = None
        if is_admin:
            # Admin username is stored in the account_id field or we can derive from email
            # For Loki client logs, user_email label is the admin username (email prefix)
            admin_username = email.split("@")[0] if "@" in email else email

        return {
            "user_id": user_id,
            "email": email,
            "is_admin": is_admin,
            "admin_username": admin_username,
            "chat_ids": chat_ids,
            "vault_key_id": user.get("vault_key_id"),
            "status": user.get("status"),
        }
    except Exception as e:
        script_logger.error(f"Failed to resolve user: {e}")
        return None
    finally:
        await sm.aclose()
        await directus_service.close()


# ─── Event classification ────────────────────────────────────────────────────

def classify_event(message: str, level: str, source: str) -> Tuple[str, str]:
    """Classify a log message into (category, event_name)."""
    # Error-level logs are always category="error" regardless of content
    if level in ("error", "critical"):
        # Still try to find a more specific event name
        for pattern, _cat, evt in _COMPILED_PATTERNS:
            if pattern.search(message):
                return "error", evt
        return "error", "error"

    # Warning-level: check for known patterns first
    for pattern, cat, evt in _COMPILED_PATTERNS:
        if pattern.search(message):
            return cat, evt

    return "other", "other"


def parse_timestamp_ns(ns_str: str) -> Tuple[str, int]:
    """Convert Loki nanosecond timestamp → (ISO string, ns int)."""
    ns = int(ns_str)
    ts_seconds = ns / 1_000_000_000
    dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S"), ns


def extract_level_from_message(message: str) -> str:
    """Try to extract log level from a raw log message."""
    upper = message[:200].upper()
    if "ERROR" in upper or "CRITICAL" in upper:
        return "error"
    if "WARNING" in upper or "WARN " in upper:
        return "warning"
    if "DEBUG" in upper:
        return "debug"
    return "info"


# ─── Loki querying ───────────────────────────────────────────────────────────

async def query_loki(
    query: str,
    since_minutes: int,
    limit: int = MAX_LOKI_ENTRIES,
    start_ns: Optional[int] = None,
) -> List[LogEvent]:
    """Query Loki and return parsed LogEvent list."""
    if start_ns:
        start_param = str(start_ns)
    else:
        start_seconds = time.time() - (since_minutes * 60)
        start_param = str(int(start_seconds * 1_000_000_000))

    end_param = str(int(time.time() * 1_000_000_000))

    params = {
        "query": query,
        "limit": str(limit),
        "start": start_param,
        "end": end_param,
        "direction": "forward",
    }

    events: List[LogEvent] = []
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    script_logger.warning(f"Loki query failed ({resp.status}): {error_text[:200]}")
                    return events
                data = await resp.json()
    except aiohttp.ClientError as e:
        script_logger.warning(f"Cannot connect to Loki: {e}")
        return events

    results = data.get("data", {}).get("result", [])
    for stream in results:
        labels = stream.get("stream", {})
        stream_level = labels.get("level", "info")
        stream_source = labels.get("container", labels.get("service", "unknown"))
        # For client console logs, source is "browser"
        if labels.get("job") == "client-console":
            stream_source = "browser"
        # For compliance logs, source is "compliance"
        if labels.get("job") == "compliance-logs":
            stream_source = "compliance"

        for value in stream.get("values", []):
            ts_ns_str, message = value[0], value[1]
            ts_str, ts_ns = parse_timestamp_ns(ts_ns_str)

            # Determine level
            level = stream_level or extract_level_from_message(message)

            # Classify
            category, event_name = classify_event(message, level, stream_source)

            # Truncate message for display
            display_msg = message.strip()
            if len(display_msg) > 300:
                display_msg = display_msg[:297] + "..."

            events.append(LogEvent(
                timestamp=ts_str,
                timestamp_ns=ts_ns,
                category=category,
                event_name=event_name,
                source=stream_source,
                level=level,
                message=display_msg,
                raw=message.strip(),
            ))

    return events


async def query_satellite_logs(
    url: str,
    search: str,
    since_minutes: int,
    server_name: str,
) -> List[LogEvent]:
    """Query a satellite server's /admin/logs endpoint for user-specific logs."""
    try:
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        vault_path = "kv/data/providers/upload_server" if "upload" in server_name else "kv/data/providers/preview_server"
        sm = SecretsManager()
        await sm.initialize()

        # Temporarily suppress ALL logging during Vault key fetch — satellite keys may
        # not be configured and that's expected. SecretsManager and httpx print noisy
        # tracebacks via the root logger that we can't selectively suppress.
        root_logger = logging.getLogger()
        prev_root_level = root_logger.level
        root_logger.setLevel(logging.CRITICAL + 10)
        try:
            api_key = await sm.get_secret(vault_path, "admin_log_api_key")
        finally:
            root_logger.setLevel(prev_root_level)
            await sm.aclose()

        if not api_key:
            script_logger.debug(f"No API key for {server_name} — skipping satellite logs")
            return []

        params = {"lines": 500, "since_minutes": since_minutes, "search": search}
        headers = {"X-Admin-Log-Key": api_key}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    script_logger.debug(f"{server_name} returned {resp.status}")
                    return []
                text = await resp.text()

        events: List[LogEvent] = []
        for line in text.strip().split("\n"):
            if not line.strip():
                continue
            level = extract_level_from_message(line)
            category, event_name = classify_event(line, level, server_name)

            # Try to extract timestamp from log line
            ts_match = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
            if ts_match:
                ts_str = ts_match.group(1).replace("T", " ")
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    ts_ns = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000)
                except ValueError:
                    ts_ns = int(time.time() * 1_000_000_000)
            else:
                ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                ts_ns = int(time.time() * 1_000_000_000)

            display_msg = line.strip()
            if len(display_msg) > 300:
                display_msg = display_msg[:297] + "..."

            events.append(LogEvent(
                timestamp=ts_str,
                timestamp_ns=ts_ns,
                category=category,
                event_name=event_name,
                source=server_name,
                level=level,
                message=display_msg,
                raw=line.strip(),
            ))

        return events

    except Exception as e:
        script_logger.debug(f"Failed to fetch {server_name} logs: {e}")
        return []


# ─── Main log aggregation ────────────────────────────────────────────────────

def loki_escape(s: str) -> str:
    """Escape a string for use inside a Loki regex filter |~ "...".
    UUIDs and hex strings only need hyphen-safe treatment.
    Loki uses RE2 syntax inside double-quoted strings where backslash
    escapes like \\- are invalid. Hyphens are literal in RE2 outside
    character classes, so no escaping is needed for UUID-like strings.
    """
    # For UUIDs/hex, no special chars need escaping.
    # For safety, escape only truly special regex chars (not hyphens).
    return re.sub(r'([.+*?^${}()\[\]\\|])', r'\\\1', s)


def build_chat_id_regex(chat_ids: List[str], max_ids: int = 20) -> str:
    """Build a Loki regex alternation for a list of chat IDs."""
    if not chat_ids:
        return ""
    # Limit to avoid overly long regex
    ids = chat_ids[:max_ids]
    return "|".join(loki_escape(cid) for cid in ids)


async def gather_all_events(
    user_info: Dict[str, Any],
    since_minutes: int,
    chat_id_filter: Optional[str] = None,
) -> List[LogEvent]:
    """Fire all Loki queries in parallel and merge results."""
    user_id = user_info["user_id"]
    chat_ids = user_info["chat_ids"]
    is_admin = user_info["is_admin"]
    admin_username = user_info.get("admin_username")

    # Build search patterns
    # user_id is the primary match; also match on first 6 chars (legacy truncated format)
    user_id_short = user_id[:6]
    user_id_regex = f"{loki_escape(user_id)}|{loki_escape(user_id_short)}"

    if chat_id_filter:
        chat_ids = [chat_id_filter]

    chat_regex = build_chat_id_regex(chat_ids)
    combined_regex = user_id_regex
    if chat_regex:
        combined_regex = f"{user_id_regex}|{chat_regex}"

    # Build queries
    queries: List[Tuple[str, str]] = []  # (query, description)

    # 1. Compliance logs (user_id is a Loki label — fast!)
    queries.append((
        f'{{job="compliance-logs", user_id="{user_id}"}}',
        "compliance",
    ))

    # 2. API application logs (search message body)
    queries.append((
        f'{{job="api-logs"}} |~ "{user_id_regex}"',
        "api-logs",
    ))

    # 3. Container logs — targeted per service for performance
    targeted_services = [
        ("api", "api"),
        ("task-worker", "task-worker"),
        ("task-scheduler", "task-scheduler"),
    ]
    for service, desc in targeted_services:
        queries.append((
            f'{{job="container-logs", container="{service}"}} |~ "{combined_regex}"',
            desc,
        ))

    # 4. App containers (match on chat IDs primarily since apps don't log user_id directly)
    if chat_regex:
        queries.append((
            f'{{job="container-logs", container=~"app-.*"}} |~ "{combined_regex}"',
            "app-containers",
        ))

    # 5. Client console logs (admin only)
    if is_admin and admin_username:
        queries.append((
            f'{{job="client-console", user_email="{admin_username}"}}',
            "client-console",
        ))

    # Fire all Loki queries in parallel
    tasks = [query_loki(q, since_minutes) for q, _ in queries]

    # Also query satellite servers in parallel
    satellite_search = user_id
    if chat_id_filter:
        satellite_search = chat_id_filter

    tasks.append(query_satellite_logs(UPLOAD_SERVER_LOG_URL, satellite_search, since_minutes, "upload"))
    tasks.append(query_satellite_logs(PREVIEW_SERVER_LOG_URL, satellite_search, since_minutes, "preview"))

    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge
    all_events: List[LogEvent] = []
    query_descs = [desc for _, desc in queries] + ["upload", "preview"]

    for i, result in enumerate(all_results):
        desc = query_descs[i] if i < len(query_descs) else f"query-{i}"
        if isinstance(result, Exception):
            script_logger.warning(f"Query '{desc}' failed: {result}")
            continue
        if result:
            all_events.extend(result)

    # Sort by timestamp
    all_events.sort(key=lambda e: e.timestamp_ns)

    # Deduplicate — same timestamp + same message = duplicate
    seen = set()
    unique: List[LogEvent] = []
    for evt in all_events:
        key = (evt.timestamp_ns, evt.message[:100])
        if key not in seen:
            seen.add(key)
            unique.append(evt)

    return unique


# ─── Filtering ────────────────────────────────────────────────────────────────

def filter_events(
    events: List[LogEvent],
    categories: Optional[List[str]] = None,
    min_level: Optional[str] = None,
) -> List[LogEvent]:
    """Filter events by category and/or minimum level."""
    filtered = events

    if categories:
        cat_set = set(categories)
        filtered = [e for e in filtered if e.category in cat_set]

    if min_level:
        min_sev = LEVEL_SEVERITY.get(min_level, 0)
        filtered = [e for e in filtered if LEVEL_SEVERITY.get(e.level, 0) >= min_sev]

    return filtered


# ─── Output formatting ───────────────────────────────────────────────────────

def format_timeline(
    events: List[LogEvent],
    user_info: Dict[str, Any],
    since_minutes: int,
    verbose: bool = False,
) -> str:
    """Format events as a human-readable timeline."""
    lines: List[str] = []
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=since_minutes)

    # Header
    lines.append("=" * 100)
    lines.append(f"{C_BOLD}USER ACTIVITY LOG{C_RESET}")
    lines.append("=" * 100)
    lines.append(f"  User:        {user_info['email']}")
    lines.append(f"  User ID:     {user_info['user_id']}")
    admin_str = "Yes (client console logs included)" if user_info["is_admin"] else "No"
    lines.append(f"  Admin:       {admin_str}")
    lines.append(f"  Time range:  {start_time.strftime('%Y-%m-%d %H:%M:%S')} → {now.strftime('%Y-%m-%d %H:%M:%S')} UTC ({since_minutes // 60}h {since_minutes % 60}m)")
    lines.append(f"  Chat IDs:    {len(user_info['chat_ids'])} chats found (used for cross-referencing)")
    lines.append("=" * 100)
    lines.append("")

    if not events:
        lines.append(f"  {C_DIM}No events found for this user in the specified time range.{C_RESET}")
        lines.append("")
        lines.append("=" * 100)
        return "\n".join(lines)

    lines.append(f"  Found {C_BOLD}{len(events)}{C_RESET} events from {_count_sources(events)} source(s)")
    lines.append("")
    lines.append("-" * 100)
    lines.append(f" {C_BOLD}TIMELINE{C_RESET}")
    lines.append("-" * 100)
    lines.append("")

    # Group events with blank lines between time gaps > 60s
    prev_ns = 0
    for evt in events:
        gap = (evt.timestamp_ns - prev_ns) / 1_000_000_000 if prev_ns else 0
        if gap > 60 and prev_ns > 0:
            lines.append("")

        cat_color = CATEGORY_COLORS.get(evt.category, C_DIM)
        level_indicator = ""
        if evt.level in ("error", "critical"):
            level_indicator = f" {C_RED}!!{C_RESET}"
        elif evt.level in ("warning", "warn"):
            level_indicator = f" {C_YELLOW}!{C_RESET}"

        cat_label = f"{cat_color}{evt.category.upper():8s}{C_RESET}"
        source_label = f"{C_DIM}[{evt.source}]{C_RESET}"

        lines.append(
            f" {C_DIM}{evt.timestamp}{C_RESET}  "
            f"{cat_label} {source_label:30s} "
            f"{evt.message}{level_indicator}"
        )

        if verbose and evt.raw and evt.raw != evt.message:
            # Show raw log (indented, dimmed)
            raw_truncated = evt.raw[:500]
            lines.append(f"   {C_DIM}RAW: {raw_truncated}{C_RESET}")

        prev_ns = evt.timestamp_ns

    # Summary
    lines.append("")
    lines.append("-" * 100)
    lines.append(f" {C_BOLD}SUMMARY{C_RESET}")
    lines.append("-" * 100)

    by_cat = _count_by_field(events, "category")
    by_source = _count_by_field(events, "source")
    error_count = sum(1 for e in events if e.level in ("error", "critical"))
    warn_count = sum(1 for e in events if e.level in ("warning", "warn"))

    cat_parts = [f"{k}: {v}" for k, v in sorted(by_cat.items(), key=lambda x: -x[1])]
    src_parts = [f"{k}: {v}" for k, v in sorted(by_source.items(), key=lambda x: -x[1])]

    lines.append(f"  Events by category:   {' | '.join(cat_parts)}")
    lines.append(f"  Events by source:     {' | '.join(src_parts)}")
    lines.append(f"  Errors/Warnings:      {error_count} error(s), {warn_count} warning(s)")
    lines.append("")
    lines.append("=" * 100)

    return "\n".join(lines)


def format_json(
    events: List[LogEvent],
    user_info: Dict[str, Any],
    since_minutes: int,
) -> str:
    """Format events as JSON."""
    by_cat = _count_by_field(events, "category")
    by_source = _count_by_field(events, "source")
    error_count = sum(1 for e in events if e.level in ("error", "critical"))
    warn_count = sum(1 for e in events if e.level in ("warning", "warn"))

    output = {
        "user": {
            "email": user_info["email"],
            "user_id": user_info["user_id"],
            "is_admin": user_info["is_admin"],
            "chat_ids_count": len(user_info["chat_ids"]),
        },
        "query": {
            "since_minutes": since_minutes,
        },
        "summary": {
            "total_events": len(events),
            "by_category": by_cat,
            "by_source": by_source,
            "errors": error_count,
            "warnings": warn_count,
        },
        "events": [asdict(e) for e in events],
    }
    return json.dumps(output, indent=2, default=str)


def _count_sources(events: List[LogEvent]) -> int:
    return len(set(e.source for e in events))


def _count_by_field(events: List[LogEvent], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in events:
        val = getattr(e, field)
        counts[val] = counts.get(val, 0) + 1
    return counts


# ─── Follow mode ──────────────────────────────────────────────────────────────

async def follow_mode(
    user_info: Dict[str, Any],
    since_minutes: int,
    categories: Optional[List[str]],
    min_level: Optional[str],
    chat_id_filter: Optional[str],
    as_json: bool,
    verbose: bool,
):
    """Continuously poll for new events."""
    print(f"{C_BOLD}Following user activity log for {user_info['email']}{C_RESET}")
    print(f"{C_DIM}Press Ctrl+C to stop{C_RESET}")
    print()

    # Initial fetch
    events = await gather_all_events(user_info, since_minutes, chat_id_filter)
    events = filter_events(events, categories, min_level)

    if events:
        if as_json:
            print(format_json(events, user_info, since_minutes))
        else:
            print(format_timeline(events, user_info, since_minutes, verbose))

    latest_ns = max((e.timestamp_ns for e in events), default=0)

    while True:
        await asyncio.sleep(FOLLOW_POLL_INTERVAL_SECONDS)

        # Fetch only new events (since latest seen + 1ns)
        new_events = await gather_all_events(user_info, since_minutes, chat_id_filter)
        new_events = [e for e in new_events if e.timestamp_ns > latest_ns]
        new_events = filter_events(new_events, categories, min_level)

        if new_events:
            for evt in new_events:
                cat_color = CATEGORY_COLORS.get(evt.category, C_DIM)
                cat_label = f"{cat_color}{evt.category.upper():8s}{C_RESET}"
                source_label = f"{C_DIM}[{evt.source}]{C_RESET}"
                print(
                    f" {C_DIM}{evt.timestamp}{C_RESET}  "
                    f"{cat_label} {source_label:30s} {evt.message}"
                )
            latest_ns = max(e.timestamp_ns for e in new_events)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Unified user activity timeline — combine all log sources for a single user"
    )
    parser.add_argument("email", help="User email address")
    parser.add_argument("--since", type=int, default=DEFAULT_SINCE_MINUTES,
                        help=f"Minutes to look back (default: {DEFAULT_SINCE_MINUTES})")
    parser.add_argument("--category", type=str, default=None,
                        help="Filter by category (comma-separated: auth,chat,sync,embed,usage,settings,client,error)")
    parser.add_argument("--level", type=str, default=None,
                        choices=["debug", "info", "warning", "error"],
                        help="Minimum log level to show")
    parser.add_argument("--chat-id", type=str, default=None,
                        help="Filter by specific chat ID")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output as JSON")
    parser.add_argument("--verbose", action="store_true",
                        help="Show raw log lines alongside parsed events")
    parser.add_argument("--follow", action="store_true",
                        help="Poll for new events every 5s (Ctrl+C to stop)")
    parser.add_argument("--prod", action="store_true",
                        help="Query production server (via Admin Debug API) instead of dev")
    args = parser.parse_args()

    # Production mode note
    if args.prod:
        print(f"{C_YELLOW}Production mode: Loki queries will go through the Admin Debug API.{C_RESET}")
        print(f"{C_YELLOW}Note: For production, use the Admin Debug CLI directly for now:{C_RESET}")
        print(f"{C_DIM}  docker exec api python /app/backend/scripts/admin_debug_cli.py logs --search '<user_id>' --since {args.since}{C_RESET}")
        print()
        # Production mode will be implemented by routing Loki queries through the admin API
        # For now, we exit with instructions
        print("Production log aggregation is not yet implemented. Use the Admin Debug CLI.")
        return

    # Resolve user
    print(f"{C_DIM}Resolving user {args.email}...{C_RESET}", end="", flush=True)
    user_info = await resolve_user(args.email)
    if not user_info:
        print(f"\n{C_RED}User not found: {args.email}{C_RESET}")
        return
    print(f" {C_GREEN}found{C_RESET} (user_id={user_info['user_id'][:12]}..., {len(user_info['chat_ids'])} chats)")

    # Parse categories
    categories = None
    if args.category:
        categories = [c.strip() for c in args.category.split(",")]

    # Follow mode
    if args.follow:
        try:
            await follow_mode(
                user_info, args.since, categories, args.level,
                args.chat_id, args.as_json, args.verbose,
            )
        except KeyboardInterrupt:
            print(f"\n{C_DIM}Stopped.{C_RESET}")
        return

    # One-shot query
    print(f"{C_DIM}Querying logs (last {args.since} min)...{C_RESET}", flush=True)
    t0 = time.time()
    events = await gather_all_events(user_info, args.since, args.chat_id)
    events = filter_events(events, categories, args.level)
    elapsed = time.time() - t0
    print(f"{C_DIM}Done in {elapsed:.1f}s — {len(events)} events found{C_RESET}")
    print()

    if args.as_json:
        print(format_json(events, user_info, args.since))
    else:
        print(format_timeline(events, user_info, args.since, args.verbose))


if __name__ == "__main__":
    asyncio.run(main())
