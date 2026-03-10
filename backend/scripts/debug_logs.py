#!/usr/bin/env python3
"""
Unified log inspection tool — user activity timeline, browser console logs,
and satellite server log/update/status management.

Combines backend logs, compliance events, container logs, client console logs,
and satellite server logs.  Supports multiple modes:

  1. User timeline (default):  Per-user activity log across all services.
  2. Browser console logs:     Search admin browser console logs in OpenObserve.
  3. Satellite server logs:    Fetch Docker logs from upload/preview servers.
  4. Satellite server update:  Trigger git-pull + rebuild on upload/preview.
  5. Satellite server status:  Poll last update status on upload/preview.

Architecture context: See docs/claude/inspection-scripts.md

Usage — User Timeline Mode (requires email):
    docker exec api python /app/backend/scripts/debug_logs.py <email>
    docker exec api python /app/backend/scripts/debug_logs.py <email> --since 120
    docker exec api python /app/backend/scripts/debug_logs.py <email> --prod
    docker exec api python /app/backend/scripts/debug_logs.py <email> --category auth,chat
    docker exec api python /app/backend/scripts/debug_logs.py <email> --level warning
    docker exec api python /app/backend/scripts/debug_logs.py <email> --chat-id <chat_id>
    docker exec api python /app/backend/scripts/debug_logs.py <email> --follow
    docker exec api python /app/backend/scripts/debug_logs.py <email> --json
    docker exec api python /app/backend/scripts/debug_logs.py <email> --verbose

Usage — Browser Console Log Mode (no email required):
    docker exec api python /app/backend/scripts/debug_logs.py --browser
    docker exec api python /app/backend/scripts/debug_logs.py --browser --since 10
    docker exec api python /app/backend/scripts/debug_logs.py --browser --level error
    docker exec api python /app/backend/scripts/debug_logs.py --browser --user jan41139
    docker exec api python /app/backend/scripts/debug_logs.py --browser --search "decrypt"
    docker exec api python /app/backend/scripts/debug_logs.py --browser --limit 100
    docker exec api python /app/backend/scripts/debug_logs.py --browser --follow
    docker exec api python /app/backend/scripts/debug_logs.py --browser --json
    docker exec api python /app/backend/scripts/debug_logs.py --browser --prod

Usage — OpenObserve Summary Mode (no email required):
    docker exec api python /app/backend/scripts/debug_logs.py --o2 --preset web-app-health --since 60
    docker exec api python /app/backend/scripts/debug_logs.py --o2 --preset web-search-failures --since 1440
    docker exec api python /app/backend/scripts/debug_logs.py --o2 --preset api-failed-requests --since 1440
    docker exec api python /app/backend/scripts/debug_logs.py --o2 --sql "SELECT level, COUNT(*) as c FROM \"default\" GROUP BY level"

Usage — Satellite Server Logs:
    docker exec api python /app/backend/scripts/debug_logs.py --upload-logs
    docker exec api python /app/backend/scripts/debug_logs.py --upload-logs --services app-uploads,clamav --since 30
    docker exec api python /app/backend/scripts/debug_logs.py --preview-logs
    docker exec api python /app/backend/scripts/debug_logs.py --preview-logs --since 30 --search "ERROR"

Usage — Satellite Server Update (git pull + rebuild + restart):
    docker exec api python /app/backend/scripts/debug_logs.py --upload-update
    docker exec api python /app/backend/scripts/debug_logs.py --preview-update

Usage — Satellite Server Status (poll last update result):
    docker exec api python /app/backend/scripts/debug_logs.py --upload-status
    docker exec api python /app/backend/scripts/debug_logs.py --preview-status
"""

import asyncio
import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
import httpx

# Add the backend directory to the Python path — must happen before backend imports
sys.path.insert(0, '/app/backend')
sys.path.insert(0, '/app')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Shared inspection utilities — replaces duplicated helpers
from debug_utils import (
    configure_script_logging,
    hash_email_sha256,
    hash_user_id,
    get_api_key_from_vault,
    C_RESET,
    C_BOLD,
    C_DIM,
    C_RED,
    C_YELLOW,
    C_GREEN,
    C_CYAN,
    C_BLUE,
    C_MAGENTA,
    C_GRAY,
)

script_logger = configure_script_logging(
    'debug_logs', fmt='%(message)s', extra_suppress=['aiohttp']
)

# ─── Constants ────────────────────────────────────────────────────────────────

OPENOBSERVE_URL = "http://openobserve:5080"
OPENOBSERVE_ORG = "default"
DEFAULT_SINCE_MINUTES = 1440  # 24 hours
MAX_LOKI_ENTRIES = 5000
FOLLOW_POLL_INTERVAL_SECONDS = 5

UPLOAD_SERVER_LOG_URL = "https://upload.openmates.org/admin/logs"
PREVIEW_SERVER_LOG_URL = "https://preview.openmates.org/admin/logs"

# Satellite server update endpoints — trigger git pull + rebuild + restart.
# Served by the admin-sidecar container on each satellite VM.
UPLOAD_SERVER_UPDATE_URL = "https://upload.openmates.org/admin/update"
PREVIEW_SERVER_UPDATE_URL = "https://preview.openmates.org/admin/update"
UPLOAD_SERVER_STATUS_URL = "https://upload.openmates.org/admin/update/status"
PREVIEW_SERVER_STATUS_URL = "https://preview.openmates.org/admin/update/status"

# Default settings for browser log mode
BROWSER_LOG_DEFAULT_SINCE_MINUTES = 30
BROWSER_LOG_DEFAULT_LIMIT = 200
O2_DEFAULT_SINCE_MINUTES = 60
O2_DEFAULT_MAX_ROWS = 200
O2_PRESETS = (
    "web-app-health",
    "web-search-failures",
    "api-failed-requests",
    "top-warnings-errors",
)


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
    (r"login_known_device", "auth", "login_known_device"),
    (r"login_new_device", "auth", "login_new_device"),
    (r"User account created|signup.*success", "auth", "signup"),
    (r"token_refresh_success|Token refreshed successfully", "auth", "token_refresh_success"),
    (r"token_refresh_failed|Failed to refresh token", "auth", "token_refresh_failed"),
    (r"Token.*refresh|token_refresh|Token expires soon|Token refreshed", "auth", "token_refresh"),
    (r"forced.?logout|Forced logout", "auth", "forced_logout"),
    (r'"logout_all"', "auth", "logout_all"),
    (r'"logout"', "auth", "logout"),
    (r"session_expired", "auth", "session_expired"),
    (r"2FA.*verif|tfa.*success|2fa_verified|tfa_enabled", "auth", "2fa_event"),
    (r"Session valid for user", "auth", "session_valid"),
    (r"Re-auth triggered", "auth", "re_auth_triggered"),
    (r"ws_auth_success", "auth", "ws_auth_success"),
    (r"ws_auth_failed", "auth", "ws_auth_failed"),

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
            # For OpenObserve client logs, user_email field is the admin username (email prefix)
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
    """Convert a nanosecond timestamp → (ISO string, ns int)."""
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


# ─── OpenObserve querying ────────────────────────────────────────────────────

async def query_openobserve(
    stream: str,
    sql: str,
    since_minutes: int,
    limit: int = MAX_LOKI_ENTRIES,
    start_us: Optional[int] = None,
) -> List[LogEvent]:
    """Query OpenObserve via SQL search API and return parsed LogEvent list.

    OpenObserve SQL search: POST /api/{org}/{stream}/_search
    Body: {"query": {"sql": "...", "start_time": <µs>, "end_time": <µs>}}
    """
    if start_us is None:
        start_us = int((time.time() - since_minutes * 60) * 1_000_000)
    hits = await _query_openobserve_sql_hits(
        sql=sql,
        since_minutes=since_minutes,
        max_rows=limit,
        start_us=start_us,
    )

    events: List[LogEvent] = []
    for hit in hits:
        ts_us_val = hit.get("_timestamp", 0)
        # OpenObserve returns microseconds; convert to nanoseconds for internal consistency
        ts_ns = int(ts_us_val) * 1000
        ts_str = datetime.fromtimestamp(ts_us_val / 1_000_000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        message = hit.get("log", hit.get("message", "")).strip()
        level = hit.get("level", extract_level_from_message(message))

        # Determine source from stream metadata
        stream_source = hit.get("container", hit.get("service", "unknown"))
        job = hit.get("job", "")
        if job == "client-console":
            stream_source = "browser"
        elif job == "compliance-logs":
            stream_source = "compliance"

        category, event_name = classify_event(message, level, stream_source)

        display_msg = message
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
            raw=message,
        ))

    return events


async def _query_openobserve_sql_hits(
    sql: str,
    since_minutes: int,
    max_rows: int,
    start_us: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Execute OpenObserve SQL and return raw hits list."""
    import os

    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    if start_us is None:
        start_us = int((time.time() - since_minutes * 60) * 1_000_000)
    end_us = int(time.time() * 1_000_000)

    sql_text = sql.strip().rstrip(";")
    if " limit " not in sql_text.lower():
        sql_text = f"{sql_text} LIMIT {max_rows}"

    body = {"query": {"sql": sql_text, "start_time": start_us, "end_time": end_us}}
    urls = (
        f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/_search",
        f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/default/_search",
    )

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                async with session.post(url, json=body, auth=aiohttp.BasicAuth(email, password)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("hits", [])

                    error_text = await resp.text()
                    if resp.status == 404:
                        continue

                    script_logger.warning(
                        f"OpenObserve query failed ({resp.status}) at {url}: {error_text[:200]}"
                    )
                    return []
    except aiohttp.ClientError as exc:
        script_logger.warning(f"Cannot connect to OpenObserve: {exc}")
        return []

    script_logger.warning("OpenObserve query failed: no working _search endpoint found")
    return []


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

def sql_escape(s: str) -> str:
    """Escape a string for safe embedding in an OpenObserve SQL clause."""
    return s.replace("'", "''")  # escape single quotes for SQL\[\]\\|])', r'\\\1', s)


def build_chat_id_regex(chat_ids: List[str], max_ids: int = 20) -> str:
    """Build an OR pattern for a list of chat IDs (used in SQL LIKE queries)."""
    if not chat_ids:
        return ""
    # Limit to avoid overly long regex
    ids = chat_ids[:max_ids]
    return "|".join(sql_escape(cid) for cid in ids)


async def gather_all_events(
    user_info: Dict[str, Any],
    since_minutes: int,
    chat_id_filter: Optional[str] = None,
) -> List[LogEvent]:
    """Fire all OpenObserve SQL queries in parallel and merge results."""
    user_id = user_info["user_id"]
    chat_ids = user_info["chat_ids"]
    is_admin = user_info["is_admin"]
    admin_username = user_info.get("admin_username")

    # Build search patterns
    # user_id is the primary match; also match on first 6 chars (legacy truncated format)
    user_id_short = user_id[:6]
    user_id_regex = f"{sql_escape(user_id)}|{sql_escape(user_id_short)}"

    if chat_id_filter:
        chat_ids = [chat_id_filter]

    chat_regex = build_chat_id_regex(chat_ids)
    combined_regex = user_id_regex
    if chat_regex:
        combined_regex = f"{user_id_regex}|{chat_regex}"

    # Build queries
    queries: List[Tuple[str, str]] = []  # (query, description)

    # 1. Compliance logs — labelled stream
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

    # Fire all OpenObserve queries in parallel
    tasks = []
    for query_entry in queries:
        sql = query_entry[0]
        tasks.append(query_openobserve("default", sql, since_minutes))

    # Also query satellite servers in parallel
    satellite_search = user_id
    if chat_id_filter:
        satellite_search = chat_id_filter

    tasks.append(query_satellite_logs(UPLOAD_SERVER_LOG_URL, satellite_search, since_minutes, "upload"))
    tasks.append(query_satellite_logs(PREVIEW_SERVER_LOG_URL, satellite_search, since_minutes, "preview"))

    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge
    all_events: List[LogEvent] = []
    query_descs = [entry[1] for entry in queries] + ["upload", "preview"]

    for i, result in enumerate(all_results):
        desc = query_descs[i] if i < len(query_descs) else f"query-{i}"
        if isinstance(result, BaseException):
            script_logger.warning(f"Query '{desc}' failed: {result}")
            continue
        if isinstance(result, list) and result:
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


# ─── Production mode (Admin Debug API) ────────────────────────────────────────

# Admin Debug API base URL (production) — accessed from inside the Docker network
PROD_API_BASE = "https://api.openmates.org/v1/admin/debug"

# Services to query for user-specific logs — mirrors the OpenObserve queries in gather_all_events
PROD_LOG_SERVICES = ["api", "task-worker", "task-scheduler", "app-ai", "app-ai-worker",
                     "app-web", "app-web-worker", "app-events"]





async def _prod_api_request(
    endpoint: str,
    api_key: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make an authenticated GET request to the Admin Debug API."""
    url = f"{PROD_API_BASE}/{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                script_logger.error(f"Admin API error {resp.status}: {text[:300]}")
                return {}
            return await resp.json()


def _parse_raw_logs_to_events(raw_logs: str) -> List[LogEvent]:
    """Parse the raw log text returned by the Admin Debug /logs endpoint into LogEvent list."""
    events: List[LogEvent] = []
    for line in raw_logs.splitlines():
        line = line.strip()
        if not line or line.startswith("===") or line.startswith("---"):
            continue

        # Try to parse as JSON (structured log line)
        ts_str = ""
        ts_ns = 0
        level = "info"
        message = line
        source = "unknown"

        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                # Extract fields from JSON log
                ts_str = obj.get("timestamp", obj.get("asctime", ""))
                level = obj.get("levelname", obj.get("level", "info")).lower()
                message = obj.get("message", obj.get("msg", line))
                source = obj.get("container", obj.get("service", "api"))
                # Parse timestamp to nanoseconds for sorting
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        ts_ns = int(dt.timestamp() * 1_000_000_000)
                    except (ValueError, OSError):
                        ts_ns = 0
        except (json.JSONDecodeError, TypeError):
            # Not JSON — extract level from raw text
            level = extract_level_from_message(line)

        category, event_name = classify_event(message, level, source)

        display_msg = message.strip()
        if len(display_msg) > 300:
            display_msg = display_msg[:297] + "..."

        events.append(LogEvent(
            timestamp=ts_str or "unknown",
            timestamp_ns=ts_ns,
            category=category,
            event_name=event_name,
            source=source,
            level=level,
            message=display_msg,
            raw=message.strip(),
        ))

    return events


async def run_prod_mode(
    email: str,
    since_minutes: int,
    categories: Optional[List[str]] = None,
    level: Optional[str] = None,
    chat_id_filter: Optional[str] = None,
    as_json: bool = False,
    verbose: bool = False,
) -> None:
    """
    Production mode: query user logs via the Admin Debug API instead of local OpenObserve.

    Flow:
      1. Get admin API key from Vault
      2. Resolve user via /inspect/user/{email}
      3. Query /logs with search=<user_id> for each service group
      4. Parse, filter, and display the timeline
    """
    api_key = await get_api_key_from_vault()

    # Step 1: Resolve user via Admin Debug API
    print(f"{C_DIM}Resolving user via Admin Debug API...{C_RESET}", end="", flush=True)
    user_resp = await _prod_api_request(f"inspect/user/{email}", api_key)
    if not user_resp or not user_resp.get("success"):
        print(f"\n{C_RED}User not found or API error for: {email}{C_RESET}")
        return
    user_data = user_resp.get("data", {})
    user_id = user_data.get("user_id") or user_data.get("id", "")
    chat_ids = user_data.get("recent_chats", [])
    # Extract chat IDs from the recent_chats list (may be dicts with 'id' key)
    if chat_ids and isinstance(chat_ids[0], dict):
        chat_ids = [c.get("id", "") for c in chat_ids if c.get("id")]

    if not user_id:
        print(f"\n{C_RED}Could not resolve user_id for: {email}{C_RESET}")
        return

    print(f" {C_GREEN}found{C_RESET} (user_id={user_id[:12]}...)")

    # Step 2: Build search pattern — user_id and optionally chat IDs
    search_terms = [user_id]
    if chat_id_filter:
        search_terms = [chat_id_filter]
    elif chat_ids:
        search_terms.extend(chat_ids[:5])  # Limit to avoid huge regex

    search_pattern = "|".join(search_terms)

    # Step 3: Query logs from services via Admin Debug API
    since_minutes_clamped = min(since_minutes, 1440)  # API max is 24h
    services_str = ",".join(PROD_LOG_SERVICES)

    print(f"{C_DIM}Querying production logs (last {since_minutes_clamped} min, "
          f"services: {services_str})...{C_RESET}", flush=True)

    t0 = time.time()
    logs_resp = await _prod_api_request("logs", api_key, params={
        "services": services_str,
        "lines": 500,  # Max lines per service
        "since_minutes": since_minutes_clamped,
        "search": search_pattern,
    })

    raw_logs = logs_resp.get("logs", "")
    if not raw_logs:
        print(f"{C_YELLOW}No logs found for user in the given time window.{C_RESET}")
        return

    # Step 4: Parse raw logs into events
    events = _parse_raw_logs_to_events(raw_logs)

    # Build user_info dict for display functions (minimal, matching expected shape)
    user_info = {
        "user_id": user_id,
        "email": email,
        "is_admin": user_data.get("is_server_admin", False),
        "admin_username": None,
        "chat_ids": chat_ids,
        "status": user_data.get("status", "unknown"),
    }

    # Filter
    events = filter_events(events, categories, level)

    # Sort and dedup
    events.sort(key=lambda e: e.timestamp_ns)
    seen: set = set()
    unique: List[LogEvent] = []
    for evt in events:
        key = (evt.timestamp_ns, evt.message[:100])
        if key not in seen:
            seen.add(key)
            unique.append(evt)
    events = unique

    elapsed = time.time() - t0
    print(f"{C_DIM}Done in {elapsed:.1f}s — {len(events)} events found (via Admin Debug API){C_RESET}")
    print()

    if as_json:
        print(format_json(events, user_info, since_minutes))
    else:
        print(format_timeline(events, user_info, since_minutes, verbose))



# ─── Browser console log mode ────────────────────────────────────────────────
# Queries OpenObserve for admin browser console logs (stream: client-console).
# Does NOT require a user email — can search across ALL admins.

def _build_browser_log_query(
    level: Optional[str] = None,
    user: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """Build a LogQL query for browser console logs."""
    labels = ['job="client-console"']
    if level:
        labels.append(f'level="{level}"')
    if user:
        labels.append(f'user_email="{user}"')

    query = "{" + ", ".join(labels) + "}"

    if search:
        query += f' |= "{search}"'

    return query


def _print_browser_log_entry(timestamp_ns: str, message: str, level: str, user: str) -> None:
    """Print a single formatted browser console log entry."""
    ts = parse_timestamp_ns(timestamp_ns)[0]
    level_colors = {"error": C_RED, "warn": C_YELLOW, "info": C_GREEN, "debug": C_GRAY}
    level_color = level_colors.get(level, C_DIM)
    level_str = f"{level_color}{level.upper():5s}{C_RESET}"
    user_str = f"{C_DIM}[{user}]{C_RESET}"
    print(f"{C_DIM}{ts}{C_RESET} {level_str} {user_str} {message}")


async def _query_browser_logs_openobserve(
    since_minutes: int,
    limit: int,
    level: Optional[str],
    user: Optional[str],
    search: Optional[str],
    as_json: bool,
    start_us: Optional[int] = None,
) -> Optional[int]:
    """
    Query OpenObserve for client console logs (stream: client-console).

    Returns the latest timestamp (in nanoseconds) seen, or None if no results.
    Browser logs are pushed by the admin_client_logs route via OpenObservePushService
    using the OpenObserve Loki-compatible push endpoint.
    """
    import os
    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    where_clauses = ["1=1"]
    if level:
        where_clauses.append(f"level = '{sql_escape(level)}'")
    if user:
        where_clauses.append(f"user_email = '{sql_escape(user)}'")
    if search:
        where_clauses.append(f"(log LIKE '%{sql_escape(search)}%' OR message LIKE '%{sql_escape(search)}%')")

    where_sql = " AND ".join(where_clauses)
    sql = (
        f"SELECT _timestamp, log, message, level, user_email "
        f"FROM \"client-console\" "
        f"WHERE {where_sql} "
        f"ORDER BY _timestamp ASC LIMIT {limit}"
    )

    if start_us is None:
        start_us = int((time.time() - since_minutes * 60) * 1_000_000)
    end_us = int(time.time() * 1_000_000)

    url = f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/client-console/_search"
    body = {"query": {"sql": sql, "start_time": start_us, "end_time": end_us}}

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, json=body, auth=aiohttp.BasicAuth(email, password)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    script_logger.warning(f"OpenObserve query failed (HTTP {resp.status}): {error_text}")
                    return None
                data = await resp.json()
    except aiohttp.ClientError as e:
        script_logger.warning(f"Cannot connect to OpenObserve at {OPENOBSERVE_URL}: {e}")
        script_logger.warning("Make sure this script is running inside the API container (docker exec api ...)")
        return None

    if as_json:
        print(json.dumps(data, indent=2))
        latest_us = max((int(h.get("_timestamp", 0)) for h in data.get("hits", [])), default=None)
        return latest_us * 1000 if latest_us else None

    hits = data.get("hits", [])
    if not hits:
        return None

    for hit in hits:
        ts_us = hit.get("_timestamp", 0)
        ts_ns_str = str(int(ts_us) * 1000)
        message = hit.get("log", hit.get("message", ""))
        entry_level = hit.get("level", "info")
        entry_user = hit.get("user_email", "unknown")
        _print_browser_log_entry(ts_ns_str, message, entry_level, entry_user)

    return int(hits[-1].get("_timestamp", 0)) * 1000


async def _browser_log_follow_mode(
    since_minutes: int,
    limit: int,
    level: Optional[str],
    user: Optional[str],
    search: Optional[str],
    as_json: bool,
) -> None:
    """Continuously poll OpenObserve for new browser console log entries."""
    query = _build_browser_log_query(level, user, search)
    print(f"{C_BOLD}Following client logs: {query}{C_RESET}")
    print(f"{C_DIM}Press Ctrl+C to stop{C_RESET}")
    print()

    latest_ns = await _query_browser_logs_openobserve(since_minutes, limit, level, user, search, as_json)

    while True:
        await asyncio.sleep(FOLLOW_POLL_INTERVAL_SECONDS)
        start_from = (latest_ns + 1) if latest_ns else None
        if start_from is None:
            new_latest = await _query_browser_logs_openobserve(since_minutes, limit, level, user, search, as_json)
        else:
            new_latest = await _query_browser_logs_openobserve(
                since_minutes, limit, level, user, search, as_json, start_us=start_from
            )
        if new_latest:
            latest_ns = new_latest


async def run_browser_logs_mode(args) -> None:
    """
    Browser console log mode — query OpenObserve for admin browser console logs.

    Supports --prod to fall back to the Admin Debug API when local OpenObserve
    has no results (or when explicitly requested for production data).
    """
    since = getattr(args, 'since', BROWSER_LOG_DEFAULT_SINCE_MINUTES)
    limit = getattr(args, 'limit', BROWSER_LOG_DEFAULT_LIMIT)
    level = getattr(args, 'level', None)
    # In browser mode, --user is the admin username filter
    user_filter = getattr(args, 'user', None)
    search = getattr(args, 'search', None)
    as_json = getattr(args, 'as_json', False)
    use_prod = getattr(args, 'prod', False)

    if getattr(args, 'follow', False):
        try:
            await _browser_log_follow_mode(since, limit, level, user_filter, search, as_json)
        except KeyboardInterrupt:
            print(f"\n{C_DIM}Stopped.{C_RESET}")
        return

    query = _build_browser_log_query(level, user_filter, search)
    print(f"{C_DIM}Query: {query}  (last {since} min, limit {limit}){C_RESET}")
    print()

    latest_ns = await _query_browser_logs_openobserve(since, limit, level, user_filter, search, as_json)

    if latest_ns is None and not as_json:
        print(f"{C_DIM}No client console logs found for the given filters.{C_RESET}")
        if not use_prod:
            print(f"{C_DIM}Ensure an admin user has the app open in their browser.{C_RESET}")

        # If --prod is set and local OpenObserve had no results, try the Admin Debug API
        if use_prod:
            print(f"\n{C_YELLOW}Trying production via Admin Debug API...{C_RESET}")
            await _browser_logs_prod_fallback(since, limit, level, user_filter, search, as_json)


async def _browser_logs_prod_fallback(
    since_minutes: int,
    limit: int,
    level: Optional[str],
    user: Optional[str],
    search: Optional[str],
    as_json: bool,
) -> None:
    """Query browser console logs via the production Admin Debug API."""
    api_key = await get_api_key_from_vault()

    # Build search term — combine user and search filters
    search_parts = []
    if user:
        search_parts.append(user)
    if search:
        search_parts.append(search)
    search_pattern = "|".join(search_parts) if search_parts else "client-console"

    params = {
        "services": "promtail",  # Client console logs are forwarded via promtail
        "lines": limit,
        "since_minutes": min(since_minutes, 1440),
        "search": search_pattern,
    }

    resp = await _prod_api_request("logs", api_key, params=params)
    raw_logs = resp.get("logs", "")

    if not raw_logs:
        print(f"{C_DIM}No browser console logs found on production either.{C_RESET}")
        return

    if as_json:
        print(json.dumps(resp, indent=2))
    else:
        print(f"\n{C_BOLD}Production browser console logs:{C_RESET}")
        print(raw_logs)


# ─── Satellite server log management ─────────────────────────────────────────
# Fetches Docker logs from upload/preview servers via their admin-sidecar.

async def _get_satellite_log_key(vault_path: str, vault_key: str, server_name: str) -> str:
    """
    Fetch a satellite server's admin log API key from the core Vault.

    The key is stored under SECRET__{PROVIDER}__{KEY} convention and imported
    into Vault by vault-setup.

    Args:
        vault_path:  Vault KV path (e.g. "kv/data/providers/upload_server")
        vault_key:   Key within that path (e.g. "admin_log_api_key")
        server_name: Human-readable name for error messages (e.g. "upload server")

    Returns:
        The API key string.
    """
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()

    try:
        api_key = await secrets_manager.get_secret(vault_path, vault_key)
        if not api_key:
            print(
                f"Error: Admin log key for {server_name} not found in Vault at "
                f"{vault_path} (key: {vault_key})",
                file=sys.stderr,
            )
            print("", file=sys.stderr)
            print(f"To set up the {server_name} admin log key:", file=sys.stderr)
            print(
                '1. Generate a random secret: python3 -c "import secrets; print(secrets.token_hex(32))"',
                file=sys.stderr,
            )
            if "upload" in server_name:
                print(
                    "2. Add to core server .env: SECRET__UPLOAD_SERVER__ADMIN_LOG_API_KEY=<key>",
                    file=sys.stderr,
                )
                print("3. Add to upload VM's .env: ADMIN_LOG_API_KEY=<same-key>", file=sys.stderr)
            else:
                print(
                    "2. Add to core server .env: SECRET__PREVIEW_SERVER__ADMIN_LOG_API_KEY=<key>",
                    file=sys.stderr,
                )
                print("3. Add to preview VM's .env: ADMIN_LOG_API_KEY=<same-key>", file=sys.stderr)
            print("4. Restart vault-setup: docker compose ... restart vault-setup", file=sys.stderr)
            sys.exit(1)
        return api_key
    finally:
        await secrets_manager.aclose()


async def _fetch_satellite_logs(
    url: str,
    api_key: str,
    services: Optional[str],
    lines: int,
    since: int,
    search: Optional[str],
) -> str:
    """
    Call the /admin/logs endpoint on a satellite server (upload or preview).

    Args:
        url:      Full URL of the admin logs endpoint.
        api_key:  X-Admin-Log-Key secret.
        services: Comma-separated service names (or None for default).
        lines:    Number of log lines to return.
        since:    Time window in minutes.
        search:   Optional regex filter.

    Returns:
        Log output as plain text.
    """
    params: dict = {
        "lines": lines,
        "since_minutes": since,
    }
    if services:
        params["services"] = services
    if search:
        params["search"] = search

    headers = {"X-Admin-Log-Key": api_key}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, headers=headers, params=params)

        if response.status_code == 401:
            print("Error: Invalid admin log API key", file=sys.stderr)
            sys.exit(1)
        elif response.status_code == 503:
            print(
                "Error: Admin logs endpoint not configured on the server "
                "(ADMIN_LOG_API_KEY env var not set on the satellite VM)",
                file=sys.stderr,
            )
            sys.exit(1)
        elif response.status_code == 400:
            print(f"Error: {response.text}", file=sys.stderr)
            sys.exit(1)
        elif response.status_code != 200:
            print(f"Error: Server returned {response.status_code}", file=sys.stderr)
            print(response.text, file=sys.stderr)
            sys.exit(1)

        return response.text

    except httpx.ConnectError:
        print(f"Error: Could not connect to {url}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("Error: Request timed out (log fetch took > 60s)", file=sys.stderr)
        sys.exit(1)


async def run_upload_logs_mode(args) -> None:
    """Fetch logs from the upload server (upload.openmates.org)."""
    api_key = await _get_satellite_log_key(
        vault_path="kv/data/providers/upload_server",
        vault_key="admin_log_api_key",
        server_name="upload server",
    )

    output = await _fetch_satellite_logs(
        url=UPLOAD_SERVER_LOG_URL,
        api_key=api_key,
        services=getattr(args, 'services', None),
        lines=getattr(args, 'lines', 200),
        since=getattr(args, 'since', 60),
        search=getattr(args, 'search', None),
    )

    if getattr(args, 'as_json', False):
        print(json.dumps({"logs": output, "server": "upload"}))
    else:
        services_label = getattr(args, 'services', None) or "app-uploads"
        since_val = getattr(args, 'since', 60)
        print(f"=== Upload Server Logs [{services_label}] — last {since_val} min ===")
        search_val = getattr(args, 'search', None)
        if search_val:
            print(f"Search pattern: {search_val}")
        print()
        print(output)


async def run_preview_logs_mode(args) -> None:
    """Fetch logs from the preview server (preview.openmates.org)."""
    api_key = await _get_satellite_log_key(
        vault_path="kv/data/providers/preview_server",
        vault_key="admin_log_api_key",
        server_name="preview server",
    )

    output = await _fetch_satellite_logs(
        url=PREVIEW_SERVER_LOG_URL,
        api_key=api_key,
        services=getattr(args, 'services', None),
        lines=getattr(args, 'lines', 200),
        since=getattr(args, 'since', 60),
        search=getattr(args, 'search', None),
    )

    if getattr(args, 'as_json', False):
        print(json.dumps({"logs": output, "server": "preview"}))
    else:
        since_val = getattr(args, 'since', 60)
        print(f"=== Preview Server Logs — last {since_val} min ===")
        search_val = getattr(args, 'search', None)
        if search_val:
            print(f"Search pattern: {search_val}")
        print()
        print(output)


# ─── Satellite server update management ──────────────────────────────────────
# Triggers git pull + rebuild + restart on upload/preview servers.

async def _trigger_satellite_update(
    update_url: str,
    status_url: str,
    api_key: str,
    server_name: str,
    poll_timeout_s: int = 720,
) -> None:
    """
    Call the POST /admin/update endpoint on a satellite server (upload or preview),
    then poll GET /admin/update/status until the update completes or times out.

    Args:
        update_url:     Full URL of the /admin/update endpoint.
        status_url:     Full URL of the /admin/update/status endpoint.
        api_key:        X-Admin-Log-Key secret.
        server_name:    Human-readable name for error messages (e.g. "upload server").
        poll_timeout_s: Maximum seconds to wait for completion (default: 720 = 12 min).
    """
    import time as _time

    headers = {"X-Admin-Log-Key": api_key}

    # Step 1: trigger the update
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(update_url, headers=headers)

        if response.status_code == 401:
            print("Error: Invalid admin log API key", file=sys.stderr)
            sys.exit(1)
        elif response.status_code == 409:
            print(f"Note: An update is already in progress on the {server_name}.")
            print("Polling status until it completes...\n")
        elif response.status_code == 503:
            print(
                "Error: Admin update endpoint not configured on the server "
                "(ADMIN_LOG_API_KEY or SERVICE_UPDATE_TARGET not set on the satellite VM)",
                file=sys.stderr,
            )
            sys.exit(1)
        elif response.status_code == 404:
            print("Note: This sidecar does not support status polling (old version).")
            print("Update triggered. Check logs manually with *-logs command.")
            return
        elif response.status_code != 202:
            print(f"Error: Server returned {response.status_code}", file=sys.stderr)
            print(response.text, file=sys.stderr)
            sys.exit(1)
        else:
            try:
                data = response.json()
                print(data.get("message", "Update accepted (202). Polling for completion...\n"))
            except Exception:
                print("Update accepted (202). Polling for completion...\n")

    except httpx.ConnectError:
        print(f"Error: Could not connect to {update_url}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("Error: Request timed out", file=sys.stderr)
        sys.exit(1)

    # Step 2: poll /admin/update/status until done
    poll_interval_s = 10
    deadline = _time.monotonic() + poll_timeout_s
    dots = 0

    while _time.monotonic() < deadline:
        await asyncio.sleep(poll_interval_s)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                status_resp = await client.get(status_url, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException):
            dots += 1
            print(f"  [{dots * poll_interval_s}s] Waiting for server to come back...", flush=True)
            continue

        if status_resp.status_code == 404:
            print("\n  Server restarted with fresh sidecar (no update record — rebuild likely succeeded).")
            print("  Verify by checking logs: upload-logs --services admin-sidecar --since 5")
            return

        if status_resp.status_code not in (200, 404):
            dots += 1
            print(f"  [{dots * poll_interval_s}s] Status poll returned HTTP {status_resp.status_code} — retrying...")
            continue

        try:
            status_data = status_resp.json()
        except Exception:
            dots += 1
            print(f"  [{dots * poll_interval_s}s] Could not parse status response — retrying...")
            continue

        status = status_data.get("status", "unknown")

        if status == "in_progress":
            dots += 1
            print(f"  [{dots * poll_interval_s}s] Update in progress...", flush=True)
            continue

        _print_update_status(status_data, server_name)
        if status != "success":
            sys.exit(1)
        return

    print(
        f"\nError: Update did not complete within {poll_timeout_s}s. "
        "Check logs manually with *-logs --services admin-sidecar.",
        file=sys.stderr,
    )
    sys.exit(1)


def _print_update_status(data: dict, server_name: str) -> None:
    """Pretty-print a completed update status response."""
    status = data.get("status", "unknown")
    icon = "✓" if status == "success" else "✗"
    print(f"\n{icon} Update {status.upper()} on {server_name}")
    print(f"  Started:  {data.get('started_at', 'N/A')}")
    print(f"  Finished: {data.get('finished_at', 'N/A')}")
    print(f"  Duration: {data.get('duration_s', '?')}s")
    print(f"  Target:   {data.get('target', 'N/A')}")
    if data.get("extras"):
        print(f"  Extras:   {', '.join(data['extras'])}")
    steps = data.get("steps", [])
    if steps:
        print("\n  Steps:")
        for step in steps:
            step_icon = "✓" if step.get("success") else "✗"
            print(f"    {step_icon} {step.get('name')}  ({step.get('duration_s', '?')}s)")
            if not step.get("success") and step.get("output"):
                output_tail = step["output"][-600:].strip()
                if output_tail:
                    for line in output_tail.splitlines():
                        print(f"         {line}")
    if data.get("error"):
        print(f"\n  Error: {data['error']}")


async def _fetch_satellite_status(status_url: str, api_key: str, server_name: str) -> None:
    """Fetch and display the current/last update status from a satellite server."""
    headers = {"X-Admin-Log-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(status_url, headers=headers)
    except httpx.ConnectError:
        print(f"Error: Could not connect to {status_url}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("Error: Request timed out", file=sys.stderr)
        sys.exit(1)

    if response.status_code == 401:
        print("Error: Invalid admin log API key", file=sys.stderr)
        sys.exit(1)
    elif response.status_code == 404:
        try:
            data = response.json()
            if data.get("status") == "never_run":
                print(f"No update has run on {server_name} since the sidecar last started.")
                return
        except Exception:
            pass
        print("Error: Status endpoint returned 404 — sidecar may be an older version", file=sys.stderr)
        sys.exit(1)
    elif response.status_code != 200:
        print(f"Error: Server returned {response.status_code}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        sys.exit(1)

    try:
        data = response.json()
    except Exception:
        print("Error: Could not parse status response", file=sys.stderr)
        sys.exit(1)

    status = data.get("status", "unknown")
    if status == "in_progress":
        print(f"Update is currently IN PROGRESS on {server_name}.")
        print(f"  Target: {data.get('target', 'N/A')}")
        if data.get("extras"):
            print(f"  Extras: {', '.join(data['extras'])}")
        print("\nPoll again in a few seconds, or check sidecar logs:")
        print("  upload-logs --services admin-sidecar --since 5")
    else:
        _print_update_status(data, server_name)


async def run_upload_update_mode(args) -> None:
    """Trigger a full self-update of the upload server (git pull + rebuild + restart)."""
    api_key = await _get_satellite_log_key(
        vault_path="kv/data/providers/upload_server",
        vault_key="admin_log_api_key",
        server_name="upload server",
    )
    print("=== Triggering update on upload server ===\n")
    await _trigger_satellite_update(
        update_url=UPLOAD_SERVER_UPDATE_URL,
        status_url=UPLOAD_SERVER_STATUS_URL,
        api_key=api_key,
        server_name="upload server",
    )


async def run_preview_update_mode(args) -> None:
    """Trigger a full self-update of the preview server (git pull + rebuild + restart)."""
    api_key = await _get_satellite_log_key(
        vault_path="kv/data/providers/preview_server",
        vault_key="admin_log_api_key",
        server_name="preview server",
    )
    print("=== Triggering update on preview server ===\n")
    await _trigger_satellite_update(
        update_url=PREVIEW_SERVER_UPDATE_URL,
        status_url=PREVIEW_SERVER_STATUS_URL,
        api_key=api_key,
        server_name="preview server",
    )


async def run_upload_status_mode(args) -> None:
    """Poll the current/last update status on the upload server."""
    api_key = await _get_satellite_log_key(
        vault_path="kv/data/providers/upload_server",
        vault_key="admin_log_api_key",
        server_name="upload server",
    )
    print("=== Upload Server Update Status ===\n")
    await _fetch_satellite_status(
        status_url=UPLOAD_SERVER_STATUS_URL,
        api_key=api_key,
        server_name="upload server",
    )


async def run_preview_status_mode(args) -> None:
    """Poll the current/last update status on the preview server."""
    api_key = await _get_satellite_log_key(
        vault_path="kv/data/providers/preview_server",
        vault_key="admin_log_api_key",
        server_name="preview server",
    )
    print("=== Preview Server Update Status ===\n")
    await _fetch_satellite_status(
        status_url=PREVIEW_SERVER_STATUS_URL,
        api_key=api_key,
        server_name="preview server",
    )


# ─── OpenObserve summary mode (token-efficient) ─────────────────────────────

def _extract_structured_message(raw_message: str) -> str:
    """Extract the inner message from JSON-formatted log lines when available."""
    try:
        parsed = json.loads(raw_message)
        if isinstance(parsed, dict):
            return str(parsed.get("message", raw_message))
    except (json.JSONDecodeError, TypeError):
        pass
    return raw_message


def _normalize_path(path: str) -> str:
    """Normalize IDs in API paths for grouping."""
    normalized = re.sub(r"/[0-9a-fA-F-]{8,}", "/:id", path)
    normalized = re.sub(r"/\d+", "/:n", normalized)
    return normalized


def _print_compact_kv(title: str, rows: List[Tuple[str, int]], max_items: int = 8) -> None:
    """Print compact key/value ranking lines."""
    print(f"{C_BOLD}{title}:{C_RESET}")
    if not rows:
        print(f"  {C_DIM}(no data){C_RESET}")
        return
    for key, value in rows[:max_items]:
        print(f"  - {key}: {value}")


async def _o2_preset_web_app_health(args) -> None:
    level_hits = await _query_openobserve_sql_hits(
        sql=(
            'SELECT level, COUNT(*) as c FROM "default" '
            "WHERE service='app-web' GROUP BY level ORDER BY c DESC"
        ),
        since_minutes=args.since,
        max_rows=args.max_rows,
    )

    warn_hits = await _query_openobserve_sql_hits(
        sql=(
            'SELECT _timestamp, message FROM "default" '
            "WHERE service='app-web' AND (level='WARNING' OR level='ERROR') "
            "ORDER BY _timestamp DESC"
        ),
        since_minutes=args.since,
        max_rows=args.max_rows,
    )

    level_rows = [
        (str(hit.get("level", "UNKNOWN")).lower(), int(hit.get("c", 0)))
        for hit in level_hits
    ]

    issue_counter: Counter[str] = Counter()
    examples: Dict[str, str] = {}
    for hit in warn_hits:
        msg = _extract_structured_message(str(hit.get("message", "")))
        msg_lower = msg.lower()
        issue = "other"
        if "brave" in msg_lower and "429" in msg_lower:
            issue = "Brave API rate limiting"
        elif "translation key" in msg_lower and "web.search" in msg_lower:
            issue = "Missing web.search translation keys"
        elif "web.search completed with" in msg_lower and "error" in msg_lower:
            issue = "web.search partial failures"
        issue_counter[issue] += 1
        examples.setdefault(issue, msg[:180])

    print(f"{C_BOLD}OpenObserve preset: web-app-health{C_RESET}")
    print(f"{C_DIM}Time window: last {args.since} minutes{C_RESET}\n")
    _print_compact_kv("app-web level counts", level_rows)
    _print_compact_kv(
        "app-web warning/error categories",
        [(k, v) for k, v in issue_counter.most_common()],
    )

    if args.raw:
        print(f"\n{C_BOLD}Examples:{C_RESET}")
        for key, sample in examples.items():
            print(f"  - {key}: {sample}")


async def _o2_preset_web_search_failures(args) -> None:
    hits = await _query_openobserve_sql_hits(
        sql=(
            'SELECT _timestamp, level, message FROM "default" '
            "WHERE service='app-web' AND ("
            "message LIKE '%web.search%' OR message LIKE '%Brave%' OR message LIKE '%brave%') "
            "ORDER BY _timestamp DESC"
        ),
        since_minutes=args.since,
        max_rows=args.max_rows,
    )

    categories: Counter[str] = Counter()
    samples: Dict[str, str] = {}
    for hit in hits:
        msg = _extract_structured_message(str(hit.get("message", "")))
        msg_lower = msg.lower()
        key = "other"
        if "brave" in msg_lower and "429" in msg_lower:
            key = "Brave 429 rate limits"
        elif "translation key" in msg_lower:
            key = "Missing translations"
        elif "web.search" in msg_lower and "error" in msg_lower:
            key = "web.search errors"
        categories[key] += 1
        samples.setdefault(key, msg[:180])

    print(f"{C_BOLD}OpenObserve preset: web-search-failures{C_RESET}")
    print(f"{C_DIM}Time window: last {args.since} minutes{C_RESET}\n")
    _print_compact_kv("Failure categories", [(k, v) for k, v in categories.most_common()])

    if args.raw:
        print(f"\n{C_BOLD}Examples:{C_RESET}")
        for key, sample in samples.items():
            print(f"  - {key}: {sample}")


async def _o2_preset_api_failed_requests(args) -> None:
    hits = await _query_openobserve_sql_hits(
        sql=(
            'SELECT _timestamp, message FROM "default" '
            "WHERE service='api' AND level='WARNING' AND message LIKE '%Request failed:%' "
            "ORDER BY _timestamp DESC"
        ),
        since_minutes=args.since,
        max_rows=args.max_rows,
    )

    pattern = re.compile(r"Request failed: (GET|POST|PUT|PATCH|DELETE|OPTIONS) ([^ ]+) - (\d{3})")
    grouped: Counter[Tuple[str, str, str]] = Counter()
    for hit in hits:
        msg = _extract_structured_message(str(hit.get("message", "")))
        match = pattern.search(msg)
        if not match:
            continue
        method, path, status = match.groups()
        grouped[(method, _normalize_path(path), status)] += 1

    rows = [
        (f"{method} {path} -> {status}", count)
        for (method, path, status), count in grouped.most_common()
    ]

    print(f"{C_BOLD}OpenObserve preset: api-failed-requests{C_RESET}")
    print(f"{C_DIM}Time window: last {args.since} minutes{C_RESET}\n")
    _print_compact_kv("Top failing routes", rows)


async def _o2_preset_top_warnings_errors(args) -> None:
    hits = await _query_openobserve_sql_hits(
        sql=(
            'SELECT service, level, COUNT(*) as c FROM "default" '
            "WHERE level IN ('WARNING','ERROR','CRITICAL') "
            "GROUP BY service, level ORDER BY c DESC"
        ),
        since_minutes=args.since,
        max_rows=args.max_rows,
    )

    rows = []
    for hit in hits:
        service = str(hit.get("service") or "unknown")
        level = str(hit.get("level") or "unknown").lower()
        rows.append((f"{service} ({level})", int(hit.get("c", 0))))

    print(f"{C_BOLD}OpenObserve preset: top-warnings-errors{C_RESET}")
    print(f"{C_DIM}Time window: last {args.since} minutes{C_RESET}\n")
    _print_compact_kv("Top noisy services", rows)


async def _o2_custom_sql(args) -> None:
    hits = await _query_openobserve_sql_hits(
        sql=args.sql,
        since_minutes=args.since,
        max_rows=args.max_rows,
    )
    if args.as_json:
        print(json.dumps({"hits": hits}, indent=2, default=str))
        return

    print(f"{C_BOLD}OpenObserve custom SQL{C_RESET}")
    print(f"{C_DIM}Rows returned: {len(hits)}{C_RESET}")
    for hit in hits[: min(len(hits), args.max_rows)]:
        print(f"- {json.dumps(hit, default=str)[:240]}")


async def run_o2_logs_mode(args) -> None:
    """Run compact OpenObserve summaries and ad-hoc SQL queries."""
    if args.sql:
        await _o2_custom_sql(args)
        return

    if not args.preset:
        print(
            "Error: --preset or --sql is required in --o2 mode\n"
            f"Available presets: {', '.join(O2_PRESETS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.preset == "web-app-health":
        await _o2_preset_web_app_health(args)
        return
    if args.preset == "web-search-failures":
        await _o2_preset_web_search_failures(args)
        return
    if args.preset == "api-failed-requests":
        await _o2_preset_api_failed_requests(args)
        return
    if args.preset == "top-warnings-errors":
        await _o2_preset_top_warnings_errors(args)
        return


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Unified log tool — user timeline, browser console logs, satellite server management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Positional email — optional (not needed for --browser, satellite modes)
    parser.add_argument("email", nargs="?", default=None,
                        help="User email address (required for user timeline mode)")

    # Mode selectors
    parser.add_argument("--browser", action="store_true",
                        help="Browser console log mode — query admin browser logs (no email needed)")
    parser.add_argument("--o2", action="store_true",
                        help="Token-efficient OpenObserve summary mode (no email needed)")
    parser.add_argument("--upload-logs", action="store_true", dest="upload_logs",
                        help="Fetch Docker logs from the upload server")
    parser.add_argument("--preview-logs", action="store_true", dest="preview_logs",
                        help="Fetch Docker logs from the preview server")
    parser.add_argument("--upload-update", action="store_true", dest="upload_update",
                        help="Trigger git pull + rebuild on the upload server")
    parser.add_argument("--preview-update", action="store_true", dest="preview_update",
                        help="Trigger git pull + rebuild on the preview server")
    parser.add_argument("--upload-status", action="store_true", dest="upload_status",
                        help="Poll last update status on the upload server")
    parser.add_argument("--preview-status", action="store_true", dest="preview_status",
                        help="Poll last update status on the preview server")

    # Shared options
    parser.add_argument("--since", type=int, default=None,
                        help="Minutes to look back (default: 1440 for timeline, 30 for browser, 60 for satellite)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output as JSON")
    parser.add_argument("--follow", action="store_true",
                        help="Poll for new events every 5s (Ctrl+C to stop)")
    parser.add_argument("--prod", action="store_true",
                        help="Query production server (via Admin Debug API) instead of dev")

    # User timeline options
    parser.add_argument("--category", type=str, default=None,
                        help="Filter by category (comma-separated: auth,chat,sync,embed,usage,settings,client,error)")
    parser.add_argument("--level", type=str, default=None,
                        choices=["debug", "info", "warn", "warning", "error"],
                        help="Minimum log level to show")
    parser.add_argument("--chat-id", type=str, default=None,
                        help="Filter by specific chat ID")
    parser.add_argument("--verbose", action="store_true",
                        help="Show raw log lines alongside parsed events")

    # Browser log options
    parser.add_argument("--user", type=str, default=None,
                        help="Filter browser logs by admin username (browser mode only)")
    parser.add_argument("--search", type=str, default=None,
                        help="Search log message content (browser/satellite modes)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max log entries (default: 200 for browser, 200 for satellite)")

    # OpenObserve summary mode options
    parser.add_argument("--preset", type=str, choices=O2_PRESETS, default=None,
                        help="Preset for --o2 mode")
    parser.add_argument("--sql", type=str, default=None,
                        help="Custom OpenObserve SQL query for --o2 mode")
    parser.add_argument("--max-rows", type=int, default=O2_DEFAULT_MAX_ROWS,
                        help="Row cap for --o2 mode (default: 200)")
    parser.add_argument("--raw", action="store_true",
                        help="Include representative raw examples in --o2 mode")

    # Satellite log options
    parser.add_argument("--services", type=str, default=None,
                        help="Comma-separated service names (satellite log modes)")
    parser.add_argument("--lines", type=int, default=None,
                        help="Number of log lines (satellite modes, default: 200)")

    args = parser.parse_args()

    # ── Route to the correct mode ────────────────────────────────────────────

    # Satellite update/status modes (no log querying — just trigger/poll)
    if args.upload_update:
        await run_upload_update_mode(args)
        return
    if args.preview_update:
        await run_preview_update_mode(args)
        return
    if args.upload_status:
        await run_upload_status_mode(args)
        return
    if args.preview_status:
        await run_preview_status_mode(args)
        return

    # Satellite log modes
    if args.upload_logs:
        if args.since is None:
            args.since = 60
        if args.lines is None:
            args.lines = 200
        await run_upload_logs_mode(args)
        return
    if args.preview_logs:
        if args.since is None:
            args.since = 60
        if args.lines is None:
            args.lines = 200
        await run_preview_logs_mode(args)
        return

    # Browser console log mode
    if args.browser:
        if args.since is None:
            args.since = BROWSER_LOG_DEFAULT_SINCE_MINUTES
        if args.limit is None:
            args.limit = BROWSER_LOG_DEFAULT_LIMIT
        await run_browser_logs_mode(args)
        return

    # OpenObserve summary mode
    if args.o2:
        if args.since is None:
            args.since = O2_DEFAULT_SINCE_MINUTES
        await run_o2_logs_mode(args)
        return

    # ── User timeline mode (requires email) ──────────────────────────────────
    if not args.email:
        parser.error(
            "email is required for user timeline mode.\n"
            "Use --browser for browser console logs, --o2 for OpenObserve summaries, "
            "or --upload-logs / --preview-logs for satellite server logs."
        )

    if args.since is None:
        args.since = DEFAULT_SINCE_MINUTES

    # Production mode — route all queries through the Admin Debug API
    if args.prod:
        print(f"{C_YELLOW}Production mode: querying via Admin Debug API{C_RESET}")
        await run_prod_mode(
            email=args.email,
            since_minutes=args.since,
            categories=[c.strip() for c in args.category.split(",")] if args.category else None,
            level=args.level,
            chat_id_filter=args.chat_id,
            as_json=args.as_json,
            verbose=args.verbose,
        )
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
