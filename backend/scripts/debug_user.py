#!/usr/bin/env python3
"""
Script to inspect user data including metadata, decrypted fields, counts of related items,
recent activities, cache status, and daily inspiration state.

Usage (local — queries local Directus + Redis on dev server):
    docker exec -it api python /app/backend/scripts/debug.py user <email_address>
    docker exec -it api python /app/backend/scripts/debug.py user user@example.com

Usage (production — fetch from prod API):
    docker exec -it api python /app/backend/scripts/debug.py user <email> --production
    docker exec -it api python /app/backend/scripts/debug.py user <email> --production --json
    docker exec -it api python /app/backend/scripts/debug.py user <email> --dev  # hit dev API instead of prod

Options:
    --json              Output as JSON instead of formatted text
    --no-cache          Skip cache checks (faster if Redis is down)
    --recent-limit N    Limit number of recent activities to display (default: 5)
    --production        Fetch data from the production Admin Debug API (requires Vault API key)
    --dev               With --production, use the dev API instead of prod

Tests: None (inspection script, not production code)
"""

import asyncio
import time
import aiohttp
import argparse
import json
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the backend directory to the Python path — must happen before backend imports
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Shared inspection utilities — replaces duplicated helpers
from debug_utils import (
    configure_script_logging,
    format_timestamp,
    get_api_key_from_vault,
    get_base_url,
    hash_email_sha256,
    hash_user_id,
    make_prod_api_request,
)

script_logger = configure_script_logging('debug_user')


async def decrypt_fields(encryption_service: EncryptionService, data: Dict[str, Any], vault_key_id: str) -> Dict[str, Any]:
    """Decrypt all fields starting with encrypted_ in a dictionary."""
    decrypted_data = {}
    if not vault_key_id:
        return decrypted_data

    # Collect all encryption fields
    encrypted_fields = [k for k in data.keys() if k.startswith('encrypted_') and data[k]]
    
    if not encrypted_fields:
        return decrypted_data

    # Decrypt in parallel
    tasks = []
    vault_fields = []
    for field in encrypted_fields:
        val = data[field]
        if isinstance(val, str) and val.startswith('vault:'):
            tasks.append(encryption_service.decrypt_with_user_key(val, vault_key_id))
            vault_fields.append(field)
    
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for field, result in zip(vault_fields, results):
            if isinstance(result, Exception):
                decrypted_data[field.replace('encrypted_', 'decrypted_')] = f"[DECRYPTION FAILED: {str(result)}]"
            else:
                decrypted_data[field.replace('encrypted_', 'decrypted_')] = result
            
    return decrypted_data


async def get_user_data(directus_service: DirectusService, email: str) -> Optional[Dict[str, Any]]:
    """Fetch user data from Directus."""
    hashed_email = hash_email_sha256(email)
    script_logger.debug(f"Fetching user data for email: {email} (hash: {hashed_email})")
    
    params = {
        'filter[hashed_email][_eq]': hashed_email,
        'fields': '*',
        'limit': 1
    }
    
    try:
        # Directus system users are accessed via /users endpoint, not /items/directus_users
        url = f"{directus_service.base_url}/users"
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        response = await directus_service._make_api_request("GET", url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data:
                user_record = data[0]
                
                # Check server_admins collection for formal admin record
                user_id = user_record.get('id')
                if user_id:
                    is_server_admin = await directus_service.admin.is_user_admin(user_id)
                    user_record['is_server_admin_record_exists'] = is_server_admin
                
                return user_record
        
        script_logger.warning(f"User not found in Directus: {email} (Status: {response.status_code})")
        return None
    except Exception as e:
        script_logger.error(f"Error fetching user metadata: {e}")
        return None


async def get_related_counts(directus_service: DirectusService, user_id: str) -> Dict[str, int]:
    """Get counts of related items for a user."""
    h_uid = hash_user_id(user_id)
    counts = {}
    
    # Define collections and their filter fields
    collections = [
        ('chats', 'hashed_user_id', h_uid),
        ('embeds', 'hashed_user_id', h_uid),
        ('usage', 'user_id_hash', h_uid),
        ('invoices', 'user_id_hash', h_uid),
        ('api_keys', 'user_id', user_id),
        ('user_passkeys', 'user_id', user_id),
        ('redeemed_gift_cards', 'user_id_hash', h_uid),
        ('gift_cards', 'purchaser_user_id_hash', h_uid)
    ]
    
    async def get_count(coll, field, val):
        params = {
            f'filter[{field}][_eq]': val,
            'limit': 1,
            'meta': 'filter_count'
        }
        try:
            # Need to use _make_api_request directly to get meta
            url = f"{directus_service.base_url}/items/{coll}"
            admin_token = await directus_service.ensure_auth_token(admin_required=True)
            headers = {"Authorization": f"Bearer {admin_token}"}
            resp = await directus_service._make_api_request("GET", url, params=params, headers=headers)
            if resp.status_code == 200:
                return resp.json().get('meta', {}).get('filter_count', 0)
            return 0
        except Exception as e:
            script_logger.error(f"Error getting count for {coll}: {e}")
            return 0

    results = await asyncio.gather(*[get_count(c, f, v) for c, f, v in collections])
    for (coll, _, _), count in zip(collections, results):
        counts[coll] = count
        
    return counts


async def get_recent_activities(directus_service: DirectusService, user_id: str, limit: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    """Get recent activities for a user."""
    h_uid = hash_user_id(user_id)
    activities = {}
    
    # Recent chats
    params_chats = {
        'filter[hashed_user_id][_eq]': h_uid,
        'sort': '-updated_at',
        'limit': limit,
        'fields': 'id,created_at,updated_at'
    }
    
    # Recent embeds
    params_embeds = {
        'filter[hashed_user_id][_eq]': h_uid,
        'sort': '-created_at',
        'limit': limit,
        'fields': 'id,embed_id,created_at,status'
    }
    
    # Recent usage
    params_usage = {
        'filter[user_id_hash][_eq]': h_uid,
        'sort': '-created_at',
        'limit': limit,
        'fields': 'id,created_at,app_id,skill_id,encrypted_credits_costs_total,chat_id'
    }
    
    # Recent invoices
    params_invoices = {
        'filter[user_id_hash][_eq]': h_uid,
        'sort': '-date',
        'limit': limit,
        'fields': 'id,date,order_id,encrypted_amount'
    }

    try:
        results = await asyncio.gather(
            directus_service.get_items('chats', params=params_chats, no_cache=True),
            directus_service.get_items('embeds', params=params_embeds, no_cache=True),
            directus_service.get_items('usage', params=params_usage, no_cache=True, admin_required=True),
            directus_service.get_items('invoices', params=params_invoices, no_cache=True, admin_required=True)
        )
        activities['chats'] = results[0] or []
        activities['embeds'] = results[1] or []
        activities['usage'] = results[2] or []
        activities['invoices'] = results[3] or []
    except Exception as e:
        script_logger.error(f"Error fetching recent activities: {e}")
        
    return activities


async def check_user_cache(cache_service: CacheService, user_id: str) -> Dict[str, Any]:
    """Check Redis cache status for a user."""
    cache_info = {
        'primed': False,
        'chat_ids_versions_count': 0,
        'active_chats_lru': [],
        'keys_found': []
    }
    
    try:
        client = await cache_service.client
        if not client:
            return cache_info
            
        # Check primed flag
        primed_key = f"user:{user_id}:cache_status:primed_flag"
        cache_info['primed'] = bool(await client.get(primed_key))
        
        # Check chat_ids_versions (Sorted Set)
        cv_key = f"user:{user_id}:chat_ids_versions"
        cache_info['chat_ids_versions_count'] = await client.zcard(cv_key)
        
        # Check active_chats_lru (List)
        lru_key = f"user:{user_id}:active_chats_lru"
        lru_data = await client.lrange(lru_key, 0, -1)
        if lru_data:
            cache_info['active_chats_lru'] = [d.decode('utf-8') for d in lru_data]
            
        # Scan for other user keys
        pattern = f"user:{user_id}:*"
        cursor = 0
        found_keys = []
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=100)
            for k in keys:
                found_keys.append(k.decode('utf-8'))
            if cursor == 0:
                break
        
        cache_info['keys_found'] = sorted(list(set(found_keys)))
                
        return cache_info
    except Exception as e:
        script_logger.error(f"Error checking user cache: {e}")
        return cache_info


async def get_daily_inspirations(
    directus_service: DirectusService,
    user_id: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Fetch stored user_daily_inspirations records for a user from Directus.

    Queries by SHA-256 hashed user_id (matching user_daily_inspiration_methods.py),
    sorted newest first. Returns up to `limit` records.

    Args:
        directus_service: Initialised DirectusService instance
        user_id: Plain-text user UUID
        limit: Maximum number of records to return (default: 10)

    Returns:
        List of raw Directus record dicts, empty list on error or not found
    """
    hashed_user_id = hash_user_id(user_id)
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
            "user_daily_inspirations",
            params=params,
            no_cache=True,
        )
        return response if response and isinstance(response, list) else []
    except Exception as e:
        script_logger.error(f"Error fetching daily inspirations from Directus: {e}")
        return []


async def get_daily_inspiration_cache(
    cache_service: CacheService,
    user_id: str,
) -> Dict[str, Any]:
    """
    Fetch the daily inspiration cache summary for a user.

    Reads the four daily inspiration Redis keys for this user and returns a
    structured summary suitable for display in the user inspection report.

    Keys checked (TTL for each is also returned):
        daily_inspiration_last_paid_request:{user_id}  — eligibility tracking
        daily_inspiration_views:{user_id}               — view count tracking
        daily_inspiration_pending:{user_id}             — pending offline delivery
        daily_inspiration_first_run_done:{user_id}      — first-run guard flag

    Args:
        cache_service: CacheService instance
        user_id: Plain-text user UUID

    Returns:
        Dict with parsed values for each key; all fields default to None/0 on error
    """
    summary: Dict[str, Any] = {
        "eligible": False,
        "language": None,
        "last_paid_ts": None,
        "view_count": 0,
        "viewed_ids": [],
        "pending_count": 0,
        "pending_generated_at": None,
        "first_run_done": False,
        "ttls": {},
        "error": None,
    }

    try:
        client = await cache_service.client
        if not client:
            summary["error"] = "Redis client not available"
            return summary

        keys = {
            "paid_request": f"daily_inspiration_last_paid_request:{user_id}",
            "views":        f"daily_inspiration_views:{user_id}",
            "pending":      f"daily_inspiration_pending:{user_id}",
            "first_run":    f"daily_inspiration_first_run_done:{user_id}",
        }

        # Fetch all values + TTLs in parallel
        raw_values: Dict[str, Any] = {}
        ttls: Dict[str, int] = {}
        for name, key in keys.items():
            try:
                raw = await client.get(key)
                ttl = await client.ttl(key)
                if raw and isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                raw_values[name] = raw
                ttls[name] = ttl
            except Exception as e:
                script_logger.error(f"Error reading cache key '{key}': {e}")
                raw_values[name] = None
                ttls[name] = -2

        summary["ttls"] = ttls

        # Parse paid_request
        paid_raw = raw_values.get("paid_request")
        if paid_raw:
            try:
                paid_data = json.loads(paid_raw)
                summary["eligible"] = True
                summary["language"] = paid_data.get("language", "?")
                summary["last_paid_ts"] = paid_data.get("last_paid_request_timestamp")
            except Exception:
                pass

        # Parse views
        views_raw = raw_values.get("views")
        if views_raw:
            try:
                view_data = json.loads(views_raw)
                viewed_ids = view_data.get("viewed_inspiration_ids", [])
                summary["view_count"] = len(viewed_ids)
                summary["viewed_ids"] = viewed_ids
            except Exception:
                pass

        # Parse pending
        pending_raw = raw_values.get("pending")
        if pending_raw:
            try:
                pending_data = json.loads(pending_raw)
                summary["pending_count"] = len(pending_data.get("inspirations", []))
                summary["pending_generated_at"] = pending_data.get("generated_at")
            except Exception:
                pass

        # First-run flag
        summary["first_run_done"] = raw_values.get("first_run") is not None

    except Exception as e:
        script_logger.error(f"Error fetching daily inspiration cache for user {user_id[:8]}...: {e}", exc_info=True)
        summary["error"] = str(e)

    return summary


LOKI_URL = "http://loki:3100"
AUTH_EVENT_TYPES = [
    "login_known_device", "login_new_device", "login_success_recovery_key",
    "login_success_backup_code", "login_failed",
    "logout", "logout_all",
    "token_refresh_success", "token_refresh_failed",
    "session_expired",
    "ws_auth_success", "ws_auth_failed",
]


async def get_session_history(user_id: str, since_hours: int = 24) -> List[Dict[str, Any]]:
    """
    Query Loki compliance logs for auth events related to a specific user.
    Returns a list of auth event dicts sorted by timestamp (newest first).
    """
    events: List[Dict[str, Any]] = []
    start_ns = str(int((time.time() - since_hours * 3600) * 1_000_000_000))
    end_ns = str(int(time.time() * 1_000_000_000))

    # Query compliance logs for this user_id
    query = f'{{job="compliance-logs"}} |~ "{user_id[:12]}"'
    params = {
        "query": query,
        "limit": "500",
        "start": start_ns,
        "end": end_ns,
        "direction": "backward",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params) as resp:
                if resp.status != 200:
                    script_logger.warning(f"Loki query failed ({resp.status})")
                    return events
                data = await resp.json()
    except Exception as e:
        script_logger.warning(f"Cannot connect to Loki for session history: {e}")
        return events

    results = data.get("data", {}).get("result", [])
    for stream in results:
        for value in stream.get("values", []):
            _, message = value[0], value[1]
            try:
                parsed = json.loads(message)
            except (json.JSONDecodeError, TypeError):
                continue

            # Filter to auth events only
            event_type = parsed.get("event_type", "")
            if event_type not in AUTH_EVENT_TYPES:
                continue

            # Verify user_id matches (the regex may have matched a substring)
            if parsed.get("user_id") != user_id and parsed.get("user_id") != "anonymous":
                continue

            events.append({
                "timestamp": parsed.get("timestamp", ""),
                "event_type": event_type,
                "status": parsed.get("status", ""),
                "device_fingerprint": parsed.get("device_fingerprint", ""),
                "location": parsed.get("location", ""),
                "details": parsed.get("details", {}),
            })

    return events


def format_output_text(
    email: str,
    user_data: Optional[Dict[str, Any]],
    decrypted_fields: Dict[str, Any],
    counts: Dict[str, int],
    activities: Dict[str, List[Dict[str, Any]]],
    cache_info: Dict[str, Any],
    daily_inspirations: Optional[List[Dict[str, Any]]] = None,
    daily_inspiration_cache: Optional[Dict[str, Any]] = None,
    source_label: Optional[str] = None,
    session_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Format results as text."""
    lines = []
    lines.append("=" * 100)
    title = "USER INSPECTION REPORT"
    if source_label:
        title += f"  [{source_label.upper()} SERVER]"
    lines.append(title)
    lines.append("=" * 100)
    lines.append(f"Email: {email}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if source_label:
        lines.append(f"Source: {source_label} Admin Debug API")
        lines.append("Note: Vault decryption and daily inspirations are not available remotely")
    lines.append("=" * 100)
    
    if not user_data:
        lines.append(f"❌ User with email {email} NOT FOUND in Directus.")
        return "\n".join(lines)
        
    # User Metadata
    lines.append("-" * 100)
    lines.append("USER METADATA (Directus)")
    lines.append("-" * 100)
    lines.append(f"  ID:                {user_data.get('id')}")
    lines.append(f"  Account ID:        {user_data.get('account_id', 'N/A')}")
    lines.append(f"  Status:            {user_data.get('status', 'N/A')}")
    
    is_admin_flag = user_data.get('is_admin', False)
    is_server_admin_record = user_data.get('is_server_admin_record_exists', False)
    admin_status = f"{is_admin_flag} (Flag) | {is_server_admin_record} (Server Admin Record)"
    lines.append(f"  Is Admin:          {admin_status}")
    
    lines.append(f"  Signup Completed:  {user_data.get('signup_completed', False)}")
    lines.append(f"  Last Online:       {format_timestamp(user_data.get('last_online_timestamp'), relative=True)}")
    lines.append(f"  Last Opened:       {user_data.get('last_opened', 'N/A')}")
    lines.append(f"  Vault Key ID:      {user_data.get('vault_key_id', 'N/A')}")
    lines.append(f"  Vault Key Ver:     {user_data.get('vault_key_version', 'N/A')}")
    lines.append("")
    
    # Decrypted Fields
    lines.append("-" * 100)
    lines.append("DECRYPTED FIELDS (from Vault)")
    lines.append("-" * 100)
    for k, v in decrypted_fields.items():
        name = k.replace('decrypted_', '').replace('_', ' ').title()
        val = v
        if k == 'decrypted_tfa_secret' and v and isinstance(v, str):
            val = v[:4] + "*" * (len(v) - 4) if len(v) > 4 else "****"
        lines.append(f"  {name:20}: {val}")
    lines.append("")
    
    # Counts
    lines.append("-" * 100)
    lines.append("ITEM COUNTS (from Directus)")
    lines.append("-" * 100)
    for coll, count in counts.items():
        lines.append(f"  {coll.replace('_', ' ').title():20}: {count}")
    lines.append("")
    
    # Recent Activities
    lines.append("-" * 100)
    lines.append("RECENT ACTIVITIES (from Directus)")
    lines.append("-" * 100)
    
    lines.append("  Recent Chats:")
    if not activities.get('chats'):
        lines.append("    None")
    for chat in activities['chats']:
        lines.append(f"    - {format_timestamp(chat.get('updated_at'))} | Chat ID: {chat.get('id')}")
    
    lines.append("\n  Recent Embeds:")
    if not activities.get('embeds'):
        lines.append("    None")
    for e in activities['embeds']:
        lines.append(f"    - {format_timestamp(e.get('created_at'))} | Embed ID: {e.get('embed_id')} | Status: {e.get('status')} | Directus ID: {e.get('id')}")

    lines.append("\n  Recent Usage:")
    if not activities.get('usage'):
        lines.append("    None")
    for u in activities['usage']:
        chat_id = u.get('chat_id')
        if chat_id and chat_id.startswith('openai-'):
            chat_info = " | [REST API CALL]"
        elif chat_id:
            chat_info = f" | Chat ID: {chat_id}"
        else:
            chat_info = ""
        lines.append(f"    - {format_timestamp(u.get('created_at'))} | {u.get('app_id')}.{u.get('skill_id'):10} | Usage ID: {u.get('id')}{chat_info}")
        
    lines.append("\n  Recent Invoices:")
    if not activities.get('invoices'):
        lines.append("    None")
    for inv in activities['invoices']:
        lines.append(f"    - {format_timestamp(inv.get('date'))} | Order ID: {inv.get('order_id', 'N/A'):20} | Invoice ID: {inv.get('id')}")
    lines.append("")
    
    # Cache Status
    lines.append("-" * 100)
    lines.append("CACHE STATUS (Redis)")
    lines.append("-" * 100)
    lines.append(f"  Primed:            {cache_info.get('primed', False)}")
    lines.append(f"  Chat List Count:   {cache_info.get('chat_ids_versions_count', 0)}")
    lines.append(f"  Active LRU:        {', '.join(cache_info.get('active_chats_lru', [])) or 'Empty'}")
    lines.append(f"  Total Keys Found:  {len(cache_info.get('keys_found', []))}")
    if cache_info.get('keys_found'):
        lines.append("  Sample Keys:")
        for k in cache_info['keys_found'][:5]:
            lines.append(f"    - {k}")
        if len(cache_info['keys_found']) > 5:
            lines.append(f"    ... and {len(cache_info['keys_found']) - 5} more")

    # Daily Inspiration — cache summary
    lines.append("")
    lines.append("-" * 100)
    lines.append("DAILY INSPIRATION — Cache Summary (Redis)")
    lines.append("-" * 100)
    if daily_inspiration_cache is None:
        lines.append("  [Skipped — pass --no-cache to omit, or check Redis availability]")
    elif daily_inspiration_cache.get("error"):
        lines.append(f"  [Error: {daily_inspiration_cache['error']}]")
    else:
        dic = daily_inspiration_cache
        ttls = dic.get("ttls", {})

        def _ttl(name: str) -> str:
            t = ttls.get(name, -2)
            if t == -2:
                return "key not found"
            if t == -1:
                return "no expiry"
            h, rem = divmod(t, 3600)
            return f"{h}h {rem // 60}m"

        eligible_icon = "✅" if dic["eligible"] else "⬜"
        first_run_icon = "✅" if dic["first_run_done"] else "⬜"

        lines.append(f"  {eligible_icon} Eligible for daily generation: {dic['eligible']}")
        if dic["eligible"]:
            lines.append(f"     Language:            {dic['language']}")
            lines.append(f"     Last paid request:   {format_timestamp(dic['last_paid_ts'])}  (TTL: {_ttl('paid_request')})")
        lines.append(f"  Views tracked:             {dic['view_count']}  (→ {dic['view_count']} new inspiration(s) tomorrow)  TTL: {_ttl('views')}")
        lines.append(f"  Pending (offline):         {dic['pending_count']} inspiration(s) awaiting delivery  TTL: {_ttl('pending')}")
        if dic["pending_count"] > 0:
            lines.append(f"     Generated at:        {format_timestamp(dic['pending_generated_at'])}")
        lines.append(f"  {first_run_icon} First-run done:            {dic['first_run_done']}  TTL: {_ttl('first_run')}")

    # Daily Inspiration — Directus records
    lines.append("")
    lines.append("-" * 100)
    if daily_inspirations is None:
        lines.append("DAILY INSPIRATION — Stored Records (Directus)  [Skipped]")
        lines.append("-" * 100)
    else:
        lines.append(f"DAILY INSPIRATION — Stored Records (Directus)  [{len(daily_inspirations)} record(s)]")
        lines.append("-" * 100)
        if not daily_inspirations:
            lines.append("  No records found in user_daily_inspirations for this user.")
        else:
            for i, rec in enumerate(daily_inspirations, 1):
                inspiration_id = rec.get("daily_inspiration_id", "N/A")
                embed_id = rec.get("embed_id") or "—"
                opened_chat = rec.get("opened_chat_id") or "—"
                is_opened = rec.get("is_opened", False)
                content_type = rec.get("content_type", "?")
                generated_at = rec.get("generated_at")

                # Show which encrypted fields are populated (sizes)
                enc = {
                    "phrase":             rec.get("encrypted_phrase"),
                    "assistant_response": rec.get("encrypted_assistant_response"),
                    "title":              rec.get("encrypted_title"),
                    "category":           rec.get("encrypted_category"),
                    "icon":               rec.get("encrypted_icon"),
                    "video_metadata":     rec.get("encrypted_video_metadata"),
                }
                enc_summary = "  ".join(
                    f"{name}=[{len(v)} chars]" if v else f"{name}=—"
                    for name, v in enc.items()
                )

                opened_icon = "✅" if is_opened else "⬜"
                lines.append(
                    f"  {i}. {opened_icon} [{content_type}]  "
                    f"generated={format_timestamp(generated_at)}"
                )
                lines.append(f"     ID:           {inspiration_id}")
                lines.append(f"     embed_id:     {embed_id}   opened_chat: {opened_chat}")
                lines.append(f"     Encrypted:    {enc_summary}")

    # Session History — Auth events from compliance logs (Loki)
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"SESSION HISTORY — Auth Events (Last 24h)  [{len(session_history) if session_history else 0} event(s)]")
    lines.append("-" * 100)
    if session_history is None:
        lines.append("  [Skipped — Loki query not available in this context]")
    elif not session_history:
        lines.append("  No auth events found in the last 24 hours.")
    else:
        for evt in session_history:
            ts = evt.get("timestamp", "?")
            etype = evt.get("event_type", "?")
            status = evt.get("status", "?")
            device_fp = evt.get("device_fingerprint", "")
            details = evt.get("details", {})
            detail_str = ""
            if isinstance(details, dict):
                # Show non-empty detail fields
                detail_parts = [f"{k}={v}" for k, v in details.items() if v]
                if detail_parts:
                    detail_str = f"  ({', '.join(detail_parts)})"
            fp_short = f"  device={device_fp[:8]}..." if device_fp and device_fp not in ("unknown", "session", "all_devices", "") else ""
            status_icon = "\u2705" if status == "success" else "\u274c"
            lines.append(f"  {status_icon} {ts}  {etype:<25}  {status}{fp_short}{detail_str}")

    lines.append("")
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    
    return "\n".join(lines)


async def fetch_user_from_production_api(
    email: str,
    *,
    recent_limit: int = 5,
    include_cache: bool = True,
    use_dev: bool = False,
) -> Dict[str, Any]:
    """Fetch user data from the production (or dev) Admin Debug API.

    Queries the /inspect/user/{email} endpoint on the remote server.

    Args:
        email: User email address to look up.
        recent_limit: Max recent activities to return (default: 5).
        include_cache: Whether to include cache status (default: True).
        use_dev: If True, hit the dev API instead of production.

    Returns:
        The API response data dict.

    Raises:
        SystemExit: On auth failures, connection errors, or timeouts.
    """
    api_key = await get_api_key_from_vault()
    base_url = get_base_url(use_dev=use_dev)
    source_label = "dev" if use_dev else "production"

    script_logger.info(
        f"Fetching user from {source_label} API: "
        f"{base_url}/inspect/user/{email}"
    )

    import urllib.parse
    encoded_email = urllib.parse.quote(email, safe="")

    result = await make_prod_api_request(
        f"inspect/user/{encoded_email}",
        api_key,
        base_url,
        params={"recent_limit": recent_limit, "include_cache": include_cache},
        entity_label="User",
    )

    if result is None:
        print(f"User with email {email} not found on {source_label} server.")
        sys.exit(1)

    return result


def map_production_user_response(api_response: Dict[str, Any]) -> Dict[str, Any]:
    """Map the production Admin Debug API response to the local data format.

    The production API returns a nested structure; this function extracts and
    remaps fields so the same formatter function can be used for both local
    and remote data.

    Args:
        api_response: The full JSON response from the production API.

    Returns:
        Dict with keys: user_data, counts, recent_chats, cache_info.
    """
    data = api_response.get("data", {})

    user_metadata = data.get("user_metadata", {})
    item_counts = data.get("item_counts", {})
    recent_chats = data.get("recent_chats", [])
    cache_info_raw = data.get("cache", {})

    # Map cache info to the format expected by format_output_text
    cache_info = {
        "primed": cache_info_raw.get("primed", False),
        "chat_ids_versions_count": cache_info_raw.get("chat_ids_versions_count", 0),
        "active_chats_lru": [],
        "keys_found": cache_info_raw.get("sample_keys", []),
    }

    # Build activities dict from recent_chats (the API only returns chats)
    activities = {
        "chats": recent_chats,
        "embeds": [],
        "usage": [],
        "invoices": [],
    }

    return {
        "user_data": user_metadata,
        "counts": item_counts,
        "activities": activities,
        "cache_info": cache_info,
    }


async def main():
    parser = argparse.ArgumentParser(description='Inspect user data')
    parser.add_argument('email', type=str, help='User email address')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--no-cache', action='store_true', help='Skip cache checks')
    parser.add_argument('--recent-limit', type=int, default=5, help='Limit recent activities')
    parser.add_argument(
        '--production',
        action='store_true',
        help='Fetch data from the production Admin Debug API instead of local Directus'
    )
    parser.add_argument(
        '--dev',
        action='store_true',
        help='When used with --production, hit the dev API instead of prod'
    )
    
    args = parser.parse_args()

    # --- Validate flag combinations ---
    is_remote = args.production or args.dev

    if args.dev and not args.production:
        # --dev implies --production (it selects which remote API to hit)
        is_remote = True
    
    if is_remote:
        # ---- PRODUCTION / DEV API MODE ----
        # Fetch all data in a single API call, then map to local format.
        # Vault decryption and daily inspirations are NOT available remotely.
        source_label = "dev" if args.dev else "production"
        script_logger.info(f"Using {source_label} Admin Debug API")

        try:
            api_response = await fetch_user_from_production_api(
                args.email,
                recent_limit=args.recent_limit,
                include_cache=not args.no_cache,
                use_dev=args.dev,
            )

            mapped = map_production_user_response(api_response)
            user_data = mapped["user_data"]
            counts = mapped["counts"]
            activities = mapped["activities"]
            cache_info = mapped["cache_info"]

            # Vault decryption is not available in production mode
            decrypted: Dict[str, Any] = {}
            # Daily inspirations are not returned by the API
            daily_inspirations: Optional[List[Dict[str, Any]]] = None
            daily_inspiration_cache: Optional[Dict[str, Any]] = None

            if args.json:
                output = {
                    "source": source_label,
                    "email": args.email,
                    "user_metadata": user_data,
                    "decrypted_fields": decrypted,
                    "item_counts": counts,
                    "recent_activities": activities,
                    "cache_status": cache_info,
                    "daily_inspirations": None,
                }
                print(json.dumps(output, indent=2, default=str))
            else:
                output = format_output_text(
                    args.email, user_data, decrypted, counts, activities, cache_info,
                    daily_inspirations=daily_inspirations,
                    daily_inspiration_cache=daily_inspiration_cache,
                    source_label=source_label,
                )
                print(output)

        except SystemExit:
            raise
        except Exception as e:
            script_logger.error(f"Error during {source_label} inspection: {e}", exc_info=True)
            if args.json:
                print(json.dumps({"error": str(e)}))
            else:
                print(f"❌ Error: {str(e)}")
        return

    # ---- LOCAL MODE (default) ----
    sm = SecretsManager()
    await sm.initialize()
    
    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    
    try:
        # 1. Fetch user metadata
        user_data = await get_user_data(directus_service, args.email)
        
        if not user_data:
            if args.json:
                print(json.dumps({"error": "User not found", "email": args.email}))
            else:
                print(f"❌ User with email {args.email} NOT FOUND in Directus.")
            return

        user_id = user_data.get('id')
        vault_key_id = user_data.get('vault_key_id')
        
        # 2. Decrypt fields
        decrypted = {}
        if vault_key_id:
            decrypted = await decrypt_fields(encryption_service, user_data, vault_key_id)
            
        # 3. Get related counts
        counts = await get_related_counts(directus_service, user_id)

        # 4. Get recent activities
        activities = await get_recent_activities(directus_service, user_id, limit=args.recent_limit)

        # 5. Check cache
        cache_info = {}
        if not args.no_cache:
            cache_info = await check_user_cache(cache_service, user_id)

        # 6. Fetch daily inspirations (Directus records + cache summary)
        daily_inspirations_list: Optional[List[Dict[str, Any]]] = await get_daily_inspirations(
            directus_service, user_id
        )
        daily_inspiration_cache_data: Optional[Dict[str, Any]] = None
        if not args.no_cache:
            daily_inspiration_cache_data = await get_daily_inspiration_cache(cache_service, user_id)

        # Add stored inspiration count to the counts dict
        counts["user_daily_inspirations"] = len(daily_inspirations_list) if daily_inspirations_list else 0

        # 7b. Fetch session history from Loki compliance logs
        session_history = await get_session_history(user_id)

        # 8. Output results
        if args.json:
            output = {
                "email": args.email,
                "user_metadata": user_data,
                "decrypted_fields": decrypted,
                "item_counts": counts,
                "recent_activities": activities,
                "cache_status": cache_info,
                "daily_inspirations": {
                    "records": daily_inspirations_list,
                    "count": len(daily_inspirations_list) if daily_inspirations_list else 0,
                    "cache": daily_inspiration_cache_data,
                },
                "session_history": session_history,
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            output = format_output_text(
                args.email, user_data, decrypted, counts, activities, cache_info,
                daily_inspirations=daily_inspirations_list,
                daily_inspiration_cache=daily_inspiration_cache_data,
                session_history=session_history,
            )
            print(output)
            
    except Exception as e:
        script_logger.error(f"Error during inspection: {e}", exc_info=True)
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"❌ Error: {str(e)}")
    finally:
        await sm.aclose()
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())
