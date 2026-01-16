#!/usr/bin/env python3
"""
Script to inspect user data including metadata, decrypted fields, counts of related items,
recent activities, and cache status.

Usage:
    docker exec -it api python /app/backend/scripts/inspect_user.py <email_address>
    docker exec -it api python /app/backend/scripts/inspect_user.py user@example.com

Options:
    --json              Output as JSON instead of formatted text
    --no-cache          Skip cache checks (faster if Redis is down)
    --recent-limit N    Limit number of recent activities to display (default: 5)
"""

import asyncio
import argparse
import hashlib
import logging
import sys
import json
import base64
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set our script logger to INFO level
script_logger = logging.getLogger('inspect_user')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)


def format_timestamp(ts: Any, relative: bool = False) -> str:
    """Format a timestamp to human-readable string (absolute or relative)."""
    if not ts:
        return "N/A"
    try:
        if isinstance(ts, (int, float, str)):
            try:
                if isinstance(ts, str):
                    # Try parsing as float/int first if it's a string timestamp
                    ts_val = float(ts)
                else:
                    ts_val = ts
                
                # Handle potential scale issues (some fields seem to have truncated timestamps)
                if 1000000 < ts_val < 10000000:
                    return f"{ts_val} (Raw)"
                
                dt = datetime.fromtimestamp(ts_val)
            except ValueError:
                # Try parsing as ISO format string
                dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        else:
            return str(ts)

        if relative:
            now = datetime.now()
            diff = now - dt
            seconds = diff.total_seconds()
            
            if seconds < 0:
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            if seconds < 60:
                return "Just now"
            if seconds < 3600:
                return f"{int(seconds // 60)} minutes ago"
            if seconds < 86400:
                return f"{int(seconds // 3600)} hours ago"
            # Fall through to absolute for > 24 hours
            
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def truncate_string(s: str, max_len: int = 50) -> str:
    """Truncate a string to max_len characters."""
    if not s:
        return "N/A"
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


def hash_email_sha256(email: str) -> str:
    """Hash email address using SHA-256 (base64) for Directus lookup."""
    email_bytes = email.strip().lower().encode('utf-8')
    hashed_email_buffer = hashlib.sha256(email_bytes).digest()
    return base64.b64encode(hashed_email_buffer).decode('utf-8')


def hash_user_id(user_id: str) -> str:
    """Hash user ID using SHA-256 (hex) for related item lookup."""
    return hashlib.sha256(user_id.encode()).hexdigest()


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
                return data[0]
        
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


def format_output_text(
    email: str,
    user_data: Optional[Dict[str, Any]],
    decrypted_fields: Dict[str, Any],
    counts: Dict[str, int],
    activities: Dict[str, List[Dict[str, Any]]],
    cache_info: Dict[str, Any]
) -> str:
    """Format results as text."""
    lines = []
    lines.append("=" * 100)
    lines.append("USER INSPECTION REPORT")
    lines.append("=" * 100)
    lines.append(f"Email: {email}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    lines.append(f"  Is Admin:          {user_data.get('is_admin', False)}")
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
            
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description='Inspect user data')
    parser.add_argument('email', type=str, help='User email address')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--no-cache', action='store_true', help='Skip cache checks')
    parser.add_argument('--recent-limit', type=int, default=5, help='Limit recent activities')
    
    args = parser.parse_args()
    
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
            
        # 6. Output results
        if args.json:
            output = {
                "email": args.email,
                "user_metadata": user_data,
                "decrypted_fields": decrypted,
                "item_counts": counts,
                "recent_activities": activities,
                "cache_status": cache_info
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            output = format_output_text(args.email, user_data, decrypted, counts, activities, cache_info)
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
