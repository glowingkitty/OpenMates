#!/usr/bin/env python3
"""
Script to inspect a specific embed from Directus.

This script provides deep embed inspection including:
1. Embed metadata from Directus
2. Embed encryption keys
3. Child embeds (if any)
4. Decrypted TOON content with field inventory (--decrypt flag)
5. Linkage verification (message, chat, parent/child consistency)
6. Redis cache status

Architecture context: See docs/architecture/embed-encryption.md
Tests: None (inspection script, not production code)

Usage:
    docker exec -it api python /app/backend/scripts/inspect_embed.py <embed_id>
    docker exec -it api python /app/backend/scripts/inspect_embed.py <embed_id> --decrypt
    docker exec -it api python /app/backend/scripts/inspect_embed.py <embed_id> --decrypt --check-links

Options:
    --json              Output as JSON instead of formatted text
    --decrypt           Decrypt and TOON-decode content (requires Vault access)
    --check-links       Verify message/chat/parent-child linkage integrity
"""

import asyncio
import argparse
import hashlib
import logging
import sys
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings and errors from libraries
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set our script logger to INFO level
script_logger = logging.getLogger('inspect_embed')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging from httpx and other libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)

# --- Constants ---
MAX_TOON_VALUE_DISPLAY_LEN = 120
MAX_CHILD_EMBEDS_DISPLAY = 10
MAX_TOON_FIELD_INVENTORY_ITEMS = 30


def format_timestamp(ts: Optional[int]) -> str:
    """
    Format a Unix timestamp to human-readable string.

    Args:
        ts: Unix timestamp in seconds or None

    Returns:
        Formatted datetime string or "N/A" if timestamp is None/invalid
    """
    if not ts:
        return "N/A"
    try:
        if isinstance(ts, int):
            dt = datetime.fromtimestamp(ts)
        else:
            # Try parsing as ISO format string
            dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def truncate_string(s: str, max_len: int = 50) -> str:
    """
    Truncate a string to max_len characters, adding ellipsis if truncated.

    Args:
        s: String to truncate
        max_len: Maximum length (default: 50)

    Returns:
        Truncated string with ellipsis if needed
    """
    if not s:
        return "N/A"
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


def _describe_toon_value(value: Any) -> str:
    """
    Produce a type+size description for a single TOON field value.
    Does NOT expose actual content — only structural info.

    Args:
        value: The decoded TOON field value

    Returns:
        String like "str(142)", "list(5)", "dict(3 keys)", "int", "bool", "null"
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"bool({value})"
    if isinstance(value, int):
        return f"int({value})"
    if isinstance(value, float):
        return f"float({value})"
    if isinstance(value, str):
        return f"str({len(value)})"
    if isinstance(value, list):
        return f"list({len(value)})"
    if isinstance(value, dict):
        return f"dict({len(value)} keys)"
    return f"{type(value).__name__}"


async def get_embed_by_id(directus_service: DirectusService, embed_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a specific embed by its embed_id from Directus.

    Args:
        directus_service: DirectusService instance
        embed_id: The embed ID to fetch

    Returns:
        Embed dictionary if found, None otherwise
    """
    script_logger.debug(f"Fetching embed with embed_id: {embed_id}")

    params = {
        'filter[embed_id][_eq]': embed_id,
        'fields': '*',  # Get all fields
        'limit': 1
    }

    try:
        response = await directus_service.get_items('embeds', params=params, no_cache=True)
        if response and isinstance(response, list) and len(response) > 0:
            return response[0]
        return None
    except Exception as e:
        script_logger.error(f"Error fetching embed: {e}")
        return None


async def get_embed_keys_by_embed_id(directus_service: DirectusService, embed_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all embed_keys for a specific embed from Directus.

    Args:
        directus_service: DirectusService instance
        embed_id: The embed ID

    Returns:
        List of embed_key dictionaries
    """
    script_logger.debug(f"Fetching embed keys for embed_id: {embed_id}")

    # Hash the embed_id to query embed_keys (embed_keys use hashed_embed_id)
    hashed_embed_id = hashlib.sha256(embed_id.encode()).hexdigest()

    params = {
        'filter[hashed_embed_id][_eq]': hashed_embed_id,
        'fields': '*',  # Get all fields
    }

    try:
        response = await directus_service.get_items('embed_keys', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching embed keys: {e}")
        return []


async def get_child_embeds(directus_service: DirectusService, embed_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Fetch child embeds by their embed_ids.

    Args:
        directus_service: DirectusService instance
        embed_ids: List of child embed IDs

    Returns:
        List of child embed dictionaries
    """
    if not embed_ids:
        return []

    child_embeds = []
    for child_id in embed_ids:
        child = await get_embed_by_id(directus_service, child_id)
        if child:
            child_embeds.append(child)

    return child_embeds


async def resolve_vault_key_id(
    directus_service: DirectusService,
    hashed_user_id: str
) -> Optional[str]:
    """
    Resolve a hashed_user_id to a vault_key_id via the user_passkeys lookup.

    This is a two-step process:
    1. hashed_user_id -> user_id (via user_passkeys table)
    2. user_id -> vault_key_id (via Directus users API)

    Args:
        directus_service: DirectusService instance
        hashed_user_id: SHA256 hash of the user_id

    Returns:
        vault_key_id string or None if not resolvable
    """
    try:
        # Step 1: hashed_user_id -> user_id
        user_id = await directus_service.get_user_id_from_hashed_user_id(hashed_user_id)
        if not user_id:
            script_logger.debug("Could not resolve hashed_user_id to user_id")
            return None

        # Step 2: user_id -> vault_key_id
        user_data = await directus_service.get_user_fields_direct(user_id, ["vault_key_id"])
        if user_data:
            return user_data.get("vault_key_id")
        return None
    except Exception as e:
        script_logger.debug(f"Error resolving vault_key_id: {e}")
        return None


async def decrypt_and_decode_toon(
    encryption_service: EncryptionService,
    encrypted_content: str,
    vault_key_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Decrypt Vault-encrypted content and TOON-decode it.

    Args:
        encryption_service: EncryptionService instance
        encrypted_content: The Vault-encrypted ciphertext
        vault_key_id: The user's Vault transit key ID

    Returns:
        Tuple of (decoded_dict, error_message). On success error_message is None.
    """
    try:
        plaintext = await encryption_service.decrypt_with_user_key(encrypted_content, vault_key_id)
        if not plaintext:
            return None, "Decryption returned None (key mismatch or empty content)"
    except Exception as e:
        return None, f"Decryption failed: {e}"

    try:
        from toon_format import decode
        decoded = decode(plaintext)
        if isinstance(decoded, dict):
            return decoded, None
        return None, f"TOON decoded to {type(decoded).__name__}, expected dict"
    except Exception as e:
        # Might be JSON instead of TOON (legacy embeds)
        try:
            decoded = json.loads(plaintext)
            if isinstance(decoded, dict):
                return decoded, None
            return None, f"JSON decoded to {type(decoded).__name__}, expected dict"
        except Exception:
            return None, f"TOON decode failed: {e}"


async def check_embed_cache(
    cache_service: CacheService,
    embed_id: str
) -> Dict[str, Any]:
    """
    Check Redis cache status for an embed.

    Args:
        cache_service: CacheService instance
        embed_id: The embed ID

    Returns:
        Dictionary with cache status information
    """
    cache_info: Dict[str, Any] = {
        'cached': False,
        'cache_key': f"embed:{embed_id}",
        'has_encrypted_content': False,
        'has_type': False,
        'ttl': None,
    }

    try:
        client = await cache_service.client
        if not client:
            cache_info['error'] = "Redis client not available"
            return cache_info

        cache_key = f"embed:{embed_id}"
        raw = await client.get(cache_key)
        if raw:
            cache_info['cached'] = True
            ttl = await client.ttl(cache_key)
            cache_info['ttl'] = ttl if ttl > 0 else None
            try:
                data = json.loads(raw)
                cache_info['has_encrypted_content'] = bool(data.get('encrypted_content'))
                cache_info['has_type'] = bool(data.get('encrypted_type'))
                cache_info['cached_fields'] = list(data.keys())
            except Exception:
                cache_info['parse_error'] = "Could not parse cached JSON"
    except Exception as e:
        cache_info['error'] = str(e)

    return cache_info


async def check_message_linkage(
    directus_service: DirectusService,
    hashed_message_id: Optional[str]
) -> Dict[str, Any]:
    """
    Verify the embed's hashed_message_id points to an existing message.

    Args:
        directus_service: DirectusService instance
        hashed_message_id: The SHA256 hash of the message_id (from embed record)

    Returns:
        Dictionary with linkage check results
    """
    result: Dict[str, Any] = {
        'has_message_link': bool(hashed_message_id),
        'message_exists': False,
        'message_role': None,
        'message_created_at': None,
    }

    if not hashed_message_id:
        return result

    try:
        params = {
            'filter[hashed_message_id][_eq]': hashed_message_id,
            'fields': 'id,role,created_at',
            'limit': 1
        }
        messages = await directus_service.get_items('messages', params=params, no_cache=True)
        if messages and isinstance(messages, list) and len(messages) > 0:
            result['message_exists'] = True
            result['message_role'] = messages[0].get('role')
            result['message_created_at'] = format_timestamp(messages[0].get('created_at'))
    except Exception as e:
        result['error'] = str(e)

    return result


async def check_chat_linkage(
    cache_service: CacheService,
    embed_id: str,
    hashed_chat_id: Optional[str]
) -> Dict[str, Any]:
    """
    Verify the embed appears in the chat's embed_ids cache set.

    Args:
        cache_service: CacheService instance
        embed_id: The embed ID to look for
        hashed_chat_id: The SHA256 hash of the chat_id

    Returns:
        Dictionary with chat linkage results
    """
    result: Dict[str, Any] = {
        'has_chat_link': bool(hashed_chat_id),
        'in_chat_embed_set': None,  # None = could not check
    }

    if not hashed_chat_id:
        return result

    try:
        client = await cache_service.client
        if not client:
            result['error'] = "Redis client not available"
            return result

        # We need the un-hashed chat_id to check the cache set, but we only have the hash.
        # The cache set key uses the raw chat_id: chat:{chat_id}:embed_ids
        # We can't reverse the hash, so we scan for matching sets instead.
        # This is a best-effort check — we scan for embed_id membership across all chat embed sets.
        cursor = 0
        found_in_set = False
        while True:
            cursor, keys = await client.scan(cursor, match="chat:*:embed_ids", count=100)
            for key in keys:
                is_member = await client.sismember(key, embed_id)
                if is_member:
                    found_in_set = True
                    result['in_chat_embed_set'] = True
                    result['cache_set_key'] = key.decode('utf-8')
                    break
            if found_in_set or cursor == 0:
                break

        if not found_in_set:
            result['in_chat_embed_set'] = False
    except Exception as e:
        result['error'] = str(e)

    return result


def format_toon_field_inventory(decoded: Dict[str, Any]) -> List[str]:
    """
    Build a human-readable field inventory from decoded TOON content.
    Shows field names, types, and sizes without exposing actual values
    (except for key metadata fields like app_id, skill_id, status).

    Args:
        decoded: The decoded TOON dictionary

    Returns:
        List of formatted lines
    """
    lines = []

    # Key metadata fields — show actual values for these
    key_fields = ['app_id', 'skill_id', 'status', 'type', 'query', 'provider',
                  'result_count', 'language', 'filename', 'title']
    shown_keys = set()

    lines.append("  Key Metadata:")
    for field in key_fields:
        if field in decoded:
            val = decoded[field]
            if isinstance(val, str) and len(val) > MAX_TOON_VALUE_DISPLAY_LEN:
                val = val[:MAX_TOON_VALUE_DISPLAY_LEN - 3] + "..."
            lines.append(f"    {field:25} = {val}")
            shown_keys.add(field)

    # Anomaly checks
    anomalies = []
    status = decoded.get('status')
    if status and status != 'finished' and status != 'activated':
        anomalies.append(f"status=\"{status}\" (expected \"finished\")")

    embed_ids = decoded.get('embed_ids')
    result_count = decoded.get('result_count')
    if embed_ids and isinstance(embed_ids, list) and result_count is not None:
        try:
            if int(result_count) != len(embed_ids):
                anomalies.append(
                    f"result_count={result_count} but embed_ids has {len(embed_ids)} entries"
                )
        except (ValueError, TypeError):
            pass

    # S3-backed embed check: flag presence of encryption keys without showing values
    s3_fields = ['aes_key', 'aes_nonce', 'vault_wrapped_aes_key', 's3_base_url']
    has_s3 = any(f in decoded for f in s3_fields)
    if has_s3:
        lines.append("")
        lines.append("  S3-Backed Embed:")
        for f in s3_fields:
            present = "present" if f in decoded else "MISSING"
            lines.append(f"    {f:25} = {present}")
        # Check files metadata
        if 'files' in decoded:
            files = decoded['files']
            if isinstance(files, dict):
                lines.append(f"    {'files':25} = dict({len(files)} formats: {', '.join(files.keys())})")
            else:
                lines.append(f"    {'files':25} = {_describe_toon_value(files)}")
            shown_keys.add('files')
        for f in s3_fields:
            shown_keys.add(f)

    # Full field inventory — type+size only
    remaining = {k: v for k, v in decoded.items() if k not in shown_keys}
    if remaining:
        lines.append("")
        lines.append(f"  All Fields ({len(decoded)} total):")
        count = 0
        for field, value in sorted(remaining.items()):
            if count >= MAX_TOON_FIELD_INVENTORY_ITEMS:
                lines.append(f"    ... and {len(remaining) - count} more fields")
                break
            lines.append(f"    {field:25} : {_describe_toon_value(value)}")
            count += 1

    if anomalies:
        lines.append("")
        lines.append("  ⚠️  Anomalies Detected:")
        for a in anomalies:
            lines.append(f"    • {a}")

    return lines


def format_output_text(
    embed_id: str,
    embed: Optional[Dict[str, Any]],
    embed_keys: List[Dict[str, Any]],
    child_embeds: List[Dict[str, Any]],
    decrypted_content: Optional[Dict[str, Any]] = None,
    decrypted_type: Optional[str] = None,
    decrypt_error: Optional[str] = None,
    cache_info: Optional[Dict[str, Any]] = None,
    linkage: Optional[Dict[str, Any]] = None,
    child_decoded: Optional[List[Optional[Dict[str, Any]]]] = None,
) -> str:
    """
    Format the embed inspection as human-readable text.

    Args:
        embed_id: The embed ID
        embed: Embed data from Directus
        embed_keys: List of embed_keys for this embed
        child_embeds: List of child embeds (if any)
        decrypted_content: Decoded TOON dict (if --decrypt was used)
        decrypted_type: Decrypted type string (if --decrypt was used)
        decrypt_error: Error message if decryption failed
        cache_info: Redis cache status (if checked)
        linkage: Linkage verification results (if --check-links was used)
        child_decoded: List of decoded TOON dicts for child embeds (if --decrypt)

    Returns:
        Formatted string for display
    """
    lines = []

    # Header
    lines.append("")
    lines.append("=" * 100)
    lines.append("EMBED INSPECTION REPORT")
    lines.append("=" * 100)
    lines.append(f"Embed ID: {embed_id}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)

    # ===================== EMBED DATA =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("EMBED DATA (from Directus)")
    lines.append("-" * 100)

    if not embed:
        lines.append("❌ Embed NOT FOUND in Directus")
    else:
        # Core metadata
        lines.append(f"  Directus ID:                 {embed.get('id', 'N/A')}")
        lines.append(f"  Embed ID:                    {embed.get('embed_id', 'N/A')}")
        lines.append(f"  Status:                      {embed.get('status', 'N/A')}")
        lines.append(f"  Created At:                  {format_timestamp(embed.get('created_at'))}")
        lines.append(f"  Updated At:                  {format_timestamp(embed.get('updated_at'))}")
        lines.append("")

        # Hashed IDs
        lines.append(f"  Hashed Chat ID:              {truncate_string(embed.get('hashed_chat_id', 'N/A'), 20)}...")
        lines.append(f"  Hashed Message ID:           {truncate_string(embed.get('hashed_message_id', 'N/A'), 20)}...")
        lines.append(f"  Hashed Task ID:              {truncate_string(embed.get('hashed_task_id', 'N/A'), 20)}...")
        lines.append(f"  Hashed User ID:              {truncate_string(embed.get('hashed_user_id', 'N/A'), 20)}...")
        lines.append("")

        # Relationships
        lines.append(f"  Parent Embed ID:             {embed.get('parent_embed_id', 'N/A')}")
        child_ids = embed.get('embed_ids')
        if child_ids and isinstance(child_ids, list):
            lines.append(f"  Child Embed IDs:             {len(child_ids)} child(ren)")
            for cid in child_ids[:5]:
                lines.append(f"    - {cid}")
            if len(child_ids) > 5:
                lines.append(f"    ... and {len(child_ids) - 5} more")
        else:
            lines.append("  Child Embed IDs:             None")
        lines.append("")

        # Versioning & metadata
        lines.append(f"  Version Number:              {embed.get('version_number', 'N/A')}")
        lines.append(f"  File Path:                   {embed.get('file_path', 'N/A')}")
        lines.append(f"  Content Hash:                {truncate_string(embed.get('content_hash', 'N/A'), 20)}...")
        lines.append(f"  Text Length (chars):         {embed.get('text_length_chars', 'N/A')}")
        lines.append("")

        # Sharing status
        lines.append(f"  Is Private:                  {embed.get('is_private', 'N/A')}")
        lines.append(f"  Is Shared:                   {embed.get('is_shared', 'N/A')}")
        lines.append("")

        # Encrypted fields
        encrypted_content = embed.get('encrypted_content')
        encrypted_type_raw = embed.get('encrypted_type')
        encrypted_preview = embed.get('encrypted_text_preview')

        lines.append("  Encrypted Fields:")
        lines.append(f"    {'✓' if encrypted_content else '✗'} encrypted_content:       {len(encrypted_content) if encrypted_content else 0} chars")
        if encrypted_content and not decrypted_content:
            lines.append(f"      Preview: {truncate_string(encrypted_content, 80)}")
        lines.append(f"    {'✓' if encrypted_type_raw else '✗'} encrypted_type:          {len(encrypted_type_raw) if encrypted_type_raw else 0} chars")
        if decrypted_type:
            lines.append(f"      Decrypted Type: {decrypted_type}")
        elif encrypted_type_raw:
            lines.append(f"      Value: {encrypted_type_raw}")
        lines.append(f"    {'✓' if encrypted_preview else '✗'} encrypted_text_preview:  {len(encrypted_preview) if encrypted_preview else 0} chars")
        if encrypted_preview and not decrypted_content:
            lines.append(f"      Preview: {truncate_string(encrypted_preview, 80)}")

        # Show all raw fields for debugging
        lines.append("")
        lines.append("  All Fields (raw):")
        for key, value in sorted(embed.items()):
            if key.startswith('encrypted_'):
                # Show length only for encrypted fields
                val_str = f"[{len(value)} chars]" if value else "null"
            elif isinstance(value, str) and len(value) > 60:
                val_str = truncate_string(value, 60)
            else:
                val_str = str(value) if value is not None else "null"
            lines.append(f"    {key}: {val_str}")

    # ===================== DECRYPTED CONTENT =====================
    if decrypted_content is not None or decrypt_error is not None:
        lines.append("")
        lines.append("-" * 100)
        lines.append("DECRYPTED TOON CONTENT")
        lines.append("-" * 100)

        if decrypt_error:
            lines.append(f"  ❌ {decrypt_error}")
        elif decrypted_content:
            lines.append(f"  ✅ Successfully decrypted and decoded ({len(decrypted_content)} fields)")
            lines.append("")
            lines.extend(format_toon_field_inventory(decrypted_content))

    # ===================== EMBED KEYS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"EMBED KEYS (from Directus) - Total: {len(embed_keys)}")
    lines.append("-" * 100)

    if not embed_keys:
        parent_embed_id = embed.get('parent_embed_id') if embed else None
        if parent_embed_id:
            lines.append(f"  No own keys — inherits from parent embed ({parent_embed_id})")
        else:
            lines.append("  ❌ No embed keys found (root embed without keys!)")
    else:
        has_master = False
        has_chat = False
        for i, key in enumerate(embed_keys, 1):
            key_type = key.get('key_type', 'unknown')
            hashed_chat_id = key.get('hashed_chat_id')
            created_at = format_timestamp(key.get('created_at'))
            encrypted_key = key.get('encrypted_embed_key', '')

            if key_type == 'master':
                has_master = True
            if key_type == 'chat':
                has_chat = True

            type_emoji = {"master": "🔑", "chat": "💬"}.get(key_type, "❓")

            lines.append(f"  {i}. {type_emoji} [{key_type:6}] Created: {created_at}")
            lines.append(f"     Hashed Embed ID: {truncate_string(key.get('hashed_embed_id', 'N/A'), 20)}...")
            if hashed_chat_id:
                lines.append(f"     Hashed Chat ID:  {truncate_string(hashed_chat_id, 20)}...")
            lines.append(f"     Hashed User ID:  {truncate_string(key.get('hashed_user_id', 'N/A'), 20)}...")
            lines.append(f"     Encrypted Key:   [{len(encrypted_key)} chars]")

        # Key completeness summary
        lines.append("")
        lines.append("  Key Completeness:")
        lines.append(f"    Master key: {'✅ present' if has_master else '❌ MISSING'}")
        lines.append(f"    Chat key:   {'✅ present' if has_chat else '⚠️  missing (required for shared chat access)'}")

    # ===================== CACHE STATUS =====================
    if cache_info is not None:
        lines.append("")
        lines.append("-" * 100)
        lines.append("REDIS CACHE STATUS")
        lines.append("-" * 100)

        if cache_info.get('error'):
            lines.append(f"  ⚠️  {cache_info['error']}")
        elif cache_info.get('cached'):
            lines.append(f"  ✅ Cached at key: {cache_info['cache_key']}")
            if cache_info.get('ttl'):
                ttl_mins = cache_info['ttl'] // 60
                lines.append(f"     TTL: {cache_info['ttl']}s ({ttl_mins}min)")
            lines.append(f"     Has encrypted_content: {'✓' if cache_info.get('has_encrypted_content') else '✗'}")
            lines.append(f"     Has encrypted_type: {'✓' if cache_info.get('has_type') else '✗'}")
            if cache_info.get('cached_fields'):
                lines.append(f"     Cached fields: {', '.join(cache_info['cached_fields'])}")
        else:
            lines.append(f"  ❌ NOT CACHED (key: {cache_info['cache_key']})")

    # ===================== LINKAGE CHECKS =====================
    if linkage is not None:
        lines.append("")
        lines.append("-" * 100)
        lines.append("LINKAGE VERIFICATION")
        lines.append("-" * 100)

        msg = linkage.get('message', {})
        chat = linkage.get('chat', {})
        parent_child = linkage.get('parent_child', {})

        # Message linkage
        if msg.get('has_message_link'):
            if msg.get('message_exists'):
                lines.append(f"  ✅ Message: exists (role={msg.get('message_role')}, created={msg.get('message_created_at')})")
            else:
                lines.append("  ❌ Message: hashed_message_id set but message NOT FOUND (orphaned embed?)")
        else:
            lines.append("  ⚠️  Message: no hashed_message_id set")

        # Chat embed set linkage
        if chat.get('has_chat_link'):
            if chat.get('in_chat_embed_set') is True:
                lines.append(f"  ✅ Chat embed set: found in {chat.get('cache_set_key', 'N/A')}")
            elif chat.get('in_chat_embed_set') is False:
                lines.append("  ❌ Chat embed set: NOT found in any chat:*:embed_ids set")
            else:
                lines.append("  ⚠️  Chat embed set: could not verify (Redis unavailable?)")
        else:
            lines.append("  ⚠️  Chat: no hashed_chat_id set")

        # Parent-child consistency
        if parent_child.get('is_parent'):
            expected = parent_child.get('expected_children', 0)
            found = parent_child.get('found_children', 0)
            missing = parent_child.get('missing_children', [])
            if expected == found:
                lines.append(f"  ✅ Children: all {expected} child embeds exist in Directus")
            else:
                lines.append(f"  ❌ Children: {found}/{expected} exist — missing: {', '.join(missing[:5])}")
        if parent_child.get('is_child'):
            if parent_child.get('parent_exists'):
                if parent_child.get('listed_in_parent'):
                    lines.append("  ✅ Parent: exists and lists this embed as a child")
                else:
                    lines.append("  ❌ Parent: exists but does NOT list this embed in embed_ids")
            else:
                lines.append("  ❌ Parent: parent_embed_id set but parent NOT FOUND")

    # ===================== CHILD EMBEDS =====================
    if child_embeds:
        lines.append("")
        lines.append("-" * 100)
        lines.append(f"CHILD EMBEDS (from Directus) - Total: {len(child_embeds)}")
        lines.append("-" * 100)

        display_children = child_embeds[:MAX_CHILD_EMBEDS_DISPLAY]
        for i, child in enumerate(display_children, 1):
            status = child.get('status', 'unknown')
            created_at = format_timestamp(child.get('created_at'))
            encrypted_content_child = child.get('encrypted_content')
            encrypted_type_child = child.get('encrypted_type')

            status_emoji = {"processing": "⏳", "finished": "✅", "error": "❌"}.get(status, "❓")

            lines.append(f"  {i}. {status_emoji} [{status:10}] {created_at}")
            lines.append(f"     Embed ID: {child.get('embed_id', 'N/A')}")

            # Show decrypted child info if available
            cd_item = child_decoded[i - 1] if (child_decoded and i - 1 < len(child_decoded)) else None
            if cd_item is not None:
                child_type = cd_item.get('type', decrypted_type or 'N/A')
                child_title = cd_item.get('title', cd_item.get('name', 'N/A'))
                child_url = cd_item.get('url', 'N/A')
                lines.append(f"     Type: {child_type}  Title: {truncate_string(str(child_title), 60)}")
                if child_url and child_url != 'N/A':
                    lines.append(f"     URL: {truncate_string(str(child_url), 80)}")
                # Show field inventory summary
                cd_keys = sorted(cd_item.keys())
                fields_summary = ', '.join(cd_keys[:10])
                if len(cd_keys) > 10:
                    fields_summary += f" (+{len(cd_keys) - 10} more)"
                lines.append(f"     Fields: {fields_summary}")
            else:
                lines.append(f"     Type: [{len(encrypted_type_child) if encrypted_type_child else 0} chars]  Content: [{len(encrypted_content_child) if encrypted_content_child else 0} chars]")

        if len(child_embeds) > MAX_CHILD_EMBEDS_DISPLAY:
            lines.append(f"\n  ... and {len(child_embeds) - MAX_CHILD_EMBEDS_DISPLAY} more child embed(s)")

    lines.append("")
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    lines.append("")

    return "\n".join(lines)


def format_output_json(
    embed_id: str,
    embed: Optional[Dict[str, Any]],
    embed_keys: List[Dict[str, Any]],
    child_embeds: List[Dict[str, Any]],
    decrypted_content: Optional[Dict[str, Any]] = None,
    decrypted_type: Optional[str] = None,
    decrypt_error: Optional[str] = None,
    cache_info: Optional[Dict[str, Any]] = None,
    linkage: Optional[Dict[str, Any]] = None,
    child_decoded: Optional[List[Optional[Dict[str, Any]]]] = None,
) -> str:
    """
    Format the embed inspection as JSON.

    Args:
        embed_id: The embed ID
        embed: Embed data from Directus
        embed_keys: List of embed_keys for this embed
        child_embeds: List of child embeds (if any)
        decrypted_content: Decoded TOON dict (if --decrypt)
        decrypted_type: Decrypted type string (if --decrypt)
        decrypt_error: Error if decryption failed
        cache_info: Redis cache status
        linkage: Linkage verification results
        child_decoded: Decoded TOON dicts for child embeds

    Returns:
        JSON string
    """
    output: Dict[str, Any] = {
        'embed_id': embed_id,
        'generated_at': datetime.now().isoformat(),
        'embed': embed,
        'embed_keys': {
            'count': len(embed_keys),
            'items': embed_keys
        },
        'child_embeds': {
            'count': len(child_embeds),
            'items': child_embeds
        }
    }

    if decrypted_content is not None or decrypt_error is not None:
        decrypted_info: Dict[str, Any] = {
            'success': decrypted_content is not None,
            'type': decrypted_type,
            'field_inventory': None,
            'key_metadata': None,
            'error': decrypt_error,
        }
        if decrypted_content:
            decrypted_info['field_inventory'] = {
                k: _describe_toon_value(v) for k, v in decrypted_content.items()
            }
            meta_keys = ['app_id', 'skill_id', 'status', 'type', 'query', 'provider',
                         'result_count', 'language', 'filename', 'title']
            decrypted_info['key_metadata'] = {
                k: decrypted_content[k] for k in meta_keys
                if k in decrypted_content
            }
        output['decrypted'] = decrypted_info

    if child_decoded:
        decoded_list = []
        for cd in child_decoded:
            if cd:
                decoded_list.append({
                    'field_inventory': {k: _describe_toon_value(v) for k, v in cd.items()},
                    'key_metadata': {
                        k: cd[k] for k in ['type', 'title', 'name', 'url']
                        if k in cd
                    }
                })
            else:
                decoded_list.append(None)
        output['child_embeds']['decoded'] = decoded_list

    if cache_info is not None:
        output['cache'] = cache_info

    if linkage is not None:
        output['linkage'] = linkage

    return json.dumps(output, indent=2, default=str)


async def main():
    """Main function that inspects an embed."""
    parser = argparse.ArgumentParser(
        description='Inspect embed data from Directus'
    )
    parser.add_argument(
        'embed_id',
        type=str,
        help='Embed ID to inspect'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of formatted text'
    )
    parser.add_argument(
        '--decrypt',
        action='store_true',
        help='Decrypt and TOON-decode embed content (requires Vault access and user lookup)'
    )
    parser.add_argument(
        '--check-links',
        action='store_true',
        help='Verify message, chat, and parent-child linkage integrity'
    )

    args = parser.parse_args()

    script_logger.info(f"Inspecting embed: {args.embed_id}")

    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )

    try:
        # 1. Fetch embed data
        embed = await get_embed_by_id(directus_service, args.embed_id)

        # 2. Fetch embed keys
        embed_keys = await get_embed_keys_by_embed_id(directus_service, args.embed_id)

        # 3. Fetch child embeds if any
        child_embed_ids = embed.get('embed_ids', []) if embed else []
        child_embeds = await get_child_embeds(directus_service, child_embed_ids)

        # 4. Decrypt content if requested
        decrypted_content = None
        decrypted_type = None
        decrypt_error = None
        child_decoded: Optional[List[Optional[Dict[str, Any]]]] = None

        if args.decrypt and embed:
            hashed_user_id = embed.get('hashed_user_id')
            if hashed_user_id:
                vault_key_id = await resolve_vault_key_id(directus_service, hashed_user_id)
                if vault_key_id:
                    # Decrypt main embed content
                    encrypted_content = embed.get('encrypted_content')
                    if encrypted_content:
                        decrypted_content, decrypt_error = await decrypt_and_decode_toon(
                            encryption_service, encrypted_content, vault_key_id
                        )

                    # Decrypt type field
                    encrypted_type_field = embed.get('encrypted_type')
                    if encrypted_type_field:
                        try:
                            decrypted_type = await encryption_service.decrypt_with_user_key(
                                encrypted_type_field, vault_key_id
                            )
                        except Exception as e:
                            script_logger.debug(f"Could not decrypt type: {e}")

                    # Decrypt child embed content
                    if child_embeds:
                        child_decoded = []
                        for child in child_embeds:
                            child_enc = child.get('encrypted_content')
                            if child_enc:
                                cd, _ = await decrypt_and_decode_toon(
                                    encryption_service, child_enc, vault_key_id
                                )
                                child_decoded.append(cd)
                            else:
                                child_decoded.append(None)
                else:
                    decrypt_error = (
                        "Could not resolve vault_key_id from hashed_user_id "
                        "(user may not have passkeys registered)"
                    )
            else:
                decrypt_error = "Embed has no hashed_user_id — cannot determine encryption key"

        # 5. Check Redis cache status (always, as it's cheap)
        cache_info = await check_embed_cache(cache_service, args.embed_id)

        # 6. Check linkage if requested
        linkage = None
        if args.check_links and embed:
            linkage = {}

            # Message linkage
            linkage['message'] = await check_message_linkage(
                directus_service, embed.get('hashed_message_id')
            )

            # Chat embed set linkage
            linkage['chat'] = await check_chat_linkage(
                cache_service, args.embed_id, embed.get('hashed_chat_id')
            )

            # Parent-child consistency
            parent_child: Dict[str, Any] = {
                'is_parent': False,
                'is_child': False,
            }

            # Check as parent
            if child_embed_ids:
                parent_child['is_parent'] = True
                parent_child['expected_children'] = len(child_embed_ids)
                parent_child['found_children'] = len(child_embeds)
                found_ids = {c.get('embed_id') for c in child_embeds}
                parent_child['missing_children'] = [
                    cid for cid in child_embed_ids if cid not in found_ids
                ]

            # Check as child
            parent_embed_id = embed.get('parent_embed_id')
            if parent_embed_id:
                parent_child['is_child'] = True
                parent = await get_embed_by_id(directus_service, parent_embed_id)
                parent_child['parent_exists'] = parent is not None
                if parent:
                    parent_ids = parent.get('embed_ids', []) or []
                    parent_child['listed_in_parent'] = args.embed_id in parent_ids

            linkage['parent_child'] = parent_child

        # 7. Format and output results
        if args.json:
            output = format_output_json(
                args.embed_id, embed, embed_keys, child_embeds,
                decrypted_content, decrypted_type, decrypt_error,
                cache_info, linkage, child_decoded,
            )
        else:
            output = format_output_text(
                args.embed_id, embed, embed_keys, child_embeds,
                decrypted_content, decrypted_type, decrypt_error,
                cache_info, linkage, child_decoded,
            )

        print(output)

    except Exception as e:
        script_logger.error(f"Error during inspection: {e}", exc_info=True)
        raise
    finally:
        # Clean up
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())
