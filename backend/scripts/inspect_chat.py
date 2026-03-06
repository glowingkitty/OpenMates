#!/usr/bin/env python3
"""
Script to inspect chat data including metadata, messages, embeds, embed keys, usage entries, and cache status.

This script provides deep chat inspection including:
1. Chat metadata from Directus
2. Messages with optional per-message embed content summaries (--decrypt)
3. Embeds with encryption key completeness
4. Embed encryption keys (chat-type vs master-type)
5. Usage entries (credit usage)
6. Redis cache status
7. Encryption health dashboard (--decrypt)
8. Client-side AES decryption of messages/embeds (--share-url or --share-key)

Embed Keys Architecture:
- key_type='chat': AES(embed_key, chat_key) - for shared chat access
- key_type='master': AES(embed_key, master_key) - for owner cross-chat access

Architecture context: See docs/architecture/embed-encryption.md
Tests: None (inspection script, not production code)

Usage (local — inside Docker container):
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id>
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --decrypt
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --share-url "https://app.openmates.org/share/chat/<id>#key=<blob>"
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --share-key "<base64-key-blob>"

Usage (production — fetch from prod API, decrypt locally):
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --production
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --production --share-url "<url>#key=<blob>"
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --production --json
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id> --dev  # hit dev API instead of prod

Options:
    --messages-limit N    Limit number of messages to display (default: 20)
    --embeds-limit N      Limit number of embeds to display (default: 20)
    --usage-limit N       Limit number of usage entries to display (default: 20)
    --json                Output as JSON instead of formatted text
    --no-cache            Skip cache checks (faster if Redis is down)
    --decrypt             Decrypt embeds via Vault (server-side encryption only, local mode only)
    --share-url URL       Share URL with #key= fragment for client-side AES decryption
    --share-key BLOB      Raw base64 key blob (the part after #key= in the share URL)
    --share-password PWD  Password for password-protected share links
    --production          Fetch data from the production Admin Debug API (requires Vault API key)
    --dev                 With --production, use the dev API instead of prod
"""

import asyncio
import argparse
import hashlib
import json
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the backend directory to the Python path — must happen before backend imports
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

# Import share key crypto utilities for client-side AES decryption
from share_key_crypto import (
    parse_share_url,
    decrypt_share_key_blob,
    decrypt_client_aes_content,
)

# Shared inspection utilities — replaces duplicated helpers
from debug_utils import (
    configure_script_logging,
    format_timestamp,
    truncate_string,
    collect_timestamp_issues,
    get_api_key_from_vault,
    make_prod_api_request,
    resolve_vault_key_id,
    decrypt_and_decode_toon,
    describe_toon_value,
    PROD_API_URL,
    DEV_API_URL,
)

script_logger = configure_script_logging('inspect_chat')

# --- Constants (script-specific) ---
MAX_EMBED_SUMMARY_QUERY_LEN = 50
MAX_EMBED_SUMMARY_DISPLAY = 5
MAX_HEALTH_ISSUES_TO_SHOW = 10


async def fetch_chat_from_production_api(
    chat_id: str,
    messages_limit: int = 20,
    embeds_limit: int = 20,
    usage_limit: int = 20,
    use_dev: bool = False,
) -> Dict[str, Any]:
    """Fetch chat data from the production (or dev) Admin Debug API.
    
    This calls GET /v1/admin/debug/inspect/chat/{chat_id} and returns the
    response body. The API returns chat metadata, messages, embeds, usage,
    and cache info in a single request.
    
    Args:
        chat_id: The chat ID (UUID) to inspect.
        messages_limit: Max messages to return from the API.
        embeds_limit: Max embeds to return from the API.
        usage_limit: Max usage entries to return from the API.
        use_dev: If True, hit the dev API instead of production.
    
    Returns:
        The full JSON response dict from the API.
    
    Raises:
        SystemExit: On authentication failure, 404, or connection error.
    """
    api_key = await get_api_key_from_vault()
    base_url = DEV_API_URL if use_dev else PROD_API_URL
    
    script_logger.info(
        f"Fetching chat from {'dev' if use_dev else 'production'} API: "
        f"{base_url}/inspect/chat/{chat_id}"
    )
    
    return await make_prod_api_request(
        f"inspect/chat/{chat_id}",
        api_key,
        base_url,
        params={
            "messages_limit": messages_limit,
            "embeds_limit": embeds_limit,
            "usage_limit": usage_limit,
            "include_cache": True,
        },
        entity_label=f"Chat {chat_id}",
    )


def map_production_chat_response(api_response: Dict[str, Any]) -> Dict[str, Any]:
    """Map the production Admin Debug API response to the local data format.
    
    The production API returns a nested structure; this function extracts and
    maps it to match what the local Directus fetchers return, so the same
    formatter functions can consume the data.
    
    Args:
        api_response: The full JSON response from the production API.
    
    Returns:
        Dictionary with keys matching local data structures:
        - chat_metadata: Dict or None
        - messages: List[Dict]
        - embeds: List[Dict]
        - embed_keys_by_embed: Dict[str, Dict[str, int]]  (always empty for prod)
        - usage_entries: List[Dict]
        - cache_info: Dict
    """
    data = api_response.get("data", {})
    
    # Chat metadata — the API returns it directly as a dict
    chat_metadata = data.get("chat_metadata")
    
    # Messages — nested under data.messages.items
    messages_data = data.get("messages", {})
    messages = messages_data.get("items", [])
    
    # Embeds — nested under data.embeds.items
    embeds_data = data.get("embeds", {})
    embeds = embeds_data.get("items", [])
    
    # Usage entries — nested under data.usage.items
    usage_data = data.get("usage", {})
    usage_entries = usage_data.get("items", [])
    
    # Embed keys — the chat API does NOT return embed_keys, so we return
    # an empty dict. The formatter will show "N/A" for embed key analysis.
    embed_keys_by_embed: Dict[str, Dict[str, int]] = {}
    
    # Cache info — map the production API's simplified cache structure
    # to the format expected by the formatters.
    prod_cache = data.get("cache", {})
    cache_info: Dict[str, Any] = {
        "discovered_user_id": prod_cache.get("discovered_user_id"),
        "chat_versions": prod_cache.get("chat_versions"),
        "raw_keys": {},
    }
    
    # Include found_keys from the API so the formatter can show them
    found_keys = prod_cache.get("found_keys", [])
    if found_keys:
        cache_info["found_keys_count"] = len(found_keys)
        for key in found_keys:
            # Derive a short label from the key suffix
            parts = key.rsplit(":", 1)
            label = parts[-1] if parts else key
            cache_info["raw_keys"][label] = key
    
    # Propagate any cache error
    cache_error = prod_cache.get("error")
    if cache_error:
        cache_info["error"] = cache_error
    
    return {
        "chat_metadata": chat_metadata,
        "messages": messages,
        "embeds": embeds,
        "embed_keys_by_embed": embed_keys_by_embed,
        "usage_entries": usage_entries,
        "cache_info": cache_info,
    }


def build_version_consistency_check(
    chat_metadata: Optional[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    cache_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Build version mismatch details for health + report sections."""
    actual_message_count = len(messages)
    directus_messages_v = chat_metadata.get('messages_v') if chat_metadata else None
    cache_messages_v = None

    if cache_info.get('chat_versions'):
        try:
            cache_messages_v = int(cache_info['chat_versions'].get('messages_v', 0))
        except (ValueError, TypeError):
            cache_messages_v = None

    issues: List[str] = []

    if directus_messages_v is not None and directus_messages_v != actual_message_count:
        issues.append(
            f"Directus messages_v ({directus_messages_v}) != actual message count ({actual_message_count})"
        )

    if cache_messages_v is not None and cache_messages_v != actual_message_count:
        issues.append(
            f"Cache messages_v ({cache_messages_v}) != actual message count ({actual_message_count})"
        )

    if directus_messages_v is not None and cache_messages_v is not None:
        if directus_messages_v != cache_messages_v:
            issues.append(
                f"Directus messages_v ({directus_messages_v}) != cache messages_v ({cache_messages_v})"
            )

    return {
        'actual_message_count': actual_message_count,
        'directus_messages_v': directus_messages_v,
        'cache_messages_v': cache_messages_v,
        'issues': issues,
        'is_consistent': len(issues) == 0,
    }


def build_chat_health_summary(
    chat_metadata: Optional[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    embeds: List[Dict[str, Any]],
    usage_entries: List[Dict[str, Any]],
    cache_info: Dict[str, Any],
    encryption_health: Optional[Dict[str, Any]],
    share_key_error: Optional[str],
) -> Dict[str, Any]:
    """Build top-level health summary for chat inspection output."""
    issues: List[str] = []
    warnings: List[str] = []

    version_check = build_version_consistency_check(chat_metadata, messages, cache_info)
    issues.extend(version_check['issues'])

    if not chat_metadata:
        issues.append("Chat metadata is missing in Directus")
    else:
        collect_timestamp_issues('chat.created_at', chat_metadata.get('created_at'), issues)
        collect_timestamp_issues('chat.updated_at', chat_metadata.get('updated_at'), issues)
        collect_timestamp_issues(
            'chat.last_message_timestamp',
            chat_metadata.get('last_message_timestamp'),
            issues,
        )
        collect_timestamp_issues(
            'chat.last_edited_overall_timestamp',
            chat_metadata.get('last_edited_overall_timestamp'),
            issues,
        )

    messages_missing_content = 0
    for msg in messages:
        collect_timestamp_issues('message.created_at', msg.get('created_at'), issues)
        role = msg.get('role')
        if role in {'assistant', 'user'} and not msg.get('encrypted_content'):
            messages_missing_content += 1

    if messages_missing_content > 0:
        issues.append(f"{messages_missing_content} user/assistant message(s) missing encrypted_content")

    embeds_in_error = 0
    finished_missing_content = 0
    for embed in embeds:
        collect_timestamp_issues('embed.created_at', embed.get('created_at'), issues)
        collect_timestamp_issues('embed.updated_at', embed.get('updated_at'), issues)
        status = str(embed.get('status', '')).lower()
        if status == 'error':
            embeds_in_error += 1
        if status == 'finished' and not embed.get('encrypted_content'):
            finished_missing_content += 1

    if embeds_in_error > 0:
        warnings.append(f"{embeds_in_error} embed(s) currently in error status")
    if finished_missing_content > 0:
        issues.append(f"{finished_missing_content} finished embed(s) missing encrypted_content")

    for usage in usage_entries:
        collect_timestamp_issues('usage.created_at', usage.get('created_at'), issues)

    if cache_info.get('error'):
        warnings.append(f"cache check failed: {cache_info.get('error')}")

    if share_key_error:
        issues.append(f"share key error: {share_key_error}")

    if encryption_health:
        for anomaly in encryption_health.get('anomalies', []):
            issues.append(f"encryption anomaly: {anomaly}")

    return {
        'status': 'healthy' if not issues else 'issues_detected',
        'is_healthy': len(issues) == 0,
        'issues': issues,
        'warnings': warnings,
        'version_check': version_check,
        'counts': {
            'messages': len(messages),
            'embeds': len(embeds),
            'usage_entries': len(usage_entries),
        },
    }


async def get_chat_metadata(directus_service: DirectusService, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch chat metadata from Directus.
    
    Args:
        directus_service: DirectusService instance
        chat_id: The chat ID (UUID format)
        
    Returns:
        Chat metadata dictionary or None if not found
    """
    script_logger.debug(f"Fetching chat metadata for chat_id: {chat_id}")
    
    # Query all chat fields
    params = {
        'filter[id][_eq]': chat_id,
        'fields': '*',  # Get all fields
        'limit': 1
    }
    
    try:
        response = await directus_service.get_items('chats', params=params, no_cache=True)
        if response and isinstance(response, list) and len(response) > 0:
            return response[0]
        else:
            script_logger.warning(f"Chat not found in Directus: {chat_id}")
            return None
    except Exception as e:
        script_logger.error(f"Error fetching chat metadata: {e}")
        return None


async def get_chat_messages(directus_service: DirectusService, chat_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch all messages for a chat from Directus.
    
    Args:
        directus_service: DirectusService instance
        chat_id: The chat ID
        limit: Maximum number of messages to fetch
        
    Returns:
        List of message dictionaries, sorted by created_at ascending
    """
    script_logger.debug(f"Fetching messages for chat_id: {chat_id}")
    
    params = {
        'filter[chat_id][_eq]': chat_id,
        'fields': '*',  # Get all fields
        'sort': 'created_at',  # Oldest first
        'limit': limit
    }
    
    try:
        response = await directus_service.get_items('messages', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching messages: {e}")
        return []


async def get_chat_embeds(directus_service: DirectusService, chat_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch all embeds for a chat from Directus using hashed_chat_id.
    
    Args:
        directus_service: DirectusService instance
        chat_id: The chat ID
        limit: Maximum number of embeds to fetch
        
    Returns:
        List of embed dictionaries, sorted by created_at descending
    """
    script_logger.debug(f"Fetching embeds for chat_id: {chat_id}")
    
    # Hash the chat_id to query embeds (embeds use hashed_chat_id for privacy)
    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
    
    params = {
        'filter[hashed_chat_id][_eq]': hashed_chat_id,
        'fields': '*',  # Get all fields
        'sort': '-created_at',  # Newest first
        'limit': limit
    }
    
    try:
        response = await directus_service.get_items('embeds', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching embeds: {e}")
        return []


async def get_embed_keys_for_chat(directus_service: DirectusService, chat_id: str) -> Dict[str, Dict[str, int]]:
    """
    Fetch all embed_keys entries for a chat from Directus and organize by embed.
    
    The embed_keys collection stores wrapped encryption keys for embeds:
    - key_type='chat': AES(embed_key, chat_key) for shared chat access
    - key_type='master': AES(embed_key, master_key) for owner cross-chat access
    
    Args:
        directus_service: DirectusService instance
        chat_id: The chat ID
        
    Returns:
        Dictionary mapping hashed_embed_id -> {'chat': count, 'master': count}
    """
    script_logger.debug(f"Fetching embed_keys for chat_id: {chat_id}")
    
    # Hash the chat_id to query embed_keys
    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
    
    # Result structure: hashed_embed_id -> {key_type -> count}
    embed_keys_by_embed: Dict[str, Dict[str, int]] = {}
    
    # First, fetch all 'chat' type keys for this chat
    chat_key_params = {
        'filter[hashed_chat_id][_eq]': hashed_chat_id,
        'filter[key_type][_eq]': 'chat',
        'fields': 'id,hashed_embed_id,key_type,encrypted_embed_key',
        'limit': -1
    }
    
    try:
        chat_keys_response = await directus_service.get_items('embed_keys', params=chat_key_params, no_cache=True)
        if chat_keys_response and isinstance(chat_keys_response, list):
            script_logger.debug(f"Found {len(chat_keys_response)} 'chat' type embed_keys")
            
            # Collect hashed_embed_ids for master key lookup
            hashed_embed_ids = set()
            
            for key_entry in chat_keys_response:
                hashed_embed_id = key_entry.get('hashed_embed_id')
                if hashed_embed_id:
                    hashed_embed_ids.add(hashed_embed_id)
                    if hashed_embed_id not in embed_keys_by_embed:
                        embed_keys_by_embed[hashed_embed_id] = {'chat': 0, 'master': 0}
                    embed_keys_by_embed[hashed_embed_id]['chat'] += 1
            
            # Now fetch master keys for these embeds
            if hashed_embed_ids:
                master_key_params = {
                    'filter[hashed_embed_id][_in]': ','.join(hashed_embed_ids),
                    'filter[key_type][_eq]': 'master',
                    'fields': 'id,hashed_embed_id,key_type,encrypted_embed_key',
                    'limit': -1
                }
                
                master_keys_response = await directus_service.get_items('embed_keys', params=master_key_params, no_cache=True)
                if master_keys_response and isinstance(master_keys_response, list):
                    script_logger.debug(f"Found {len(master_keys_response)} 'master' type embed_keys")
                    
                    for key_entry in master_keys_response:
                        hashed_embed_id = key_entry.get('hashed_embed_id')
                        if hashed_embed_id:
                            if hashed_embed_id not in embed_keys_by_embed:
                                embed_keys_by_embed[hashed_embed_id] = {'chat': 0, 'master': 0}
                            embed_keys_by_embed[hashed_embed_id]['master'] += 1
        
        return embed_keys_by_embed
        
    except Exception as e:
        script_logger.error(f"Error fetching embed_keys: {e}")
        return {}


async def get_chat_usage_entries(directus_service: DirectusService, chat_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch all usage entries for a chat from Directus.
    
    Usage entries are stored with chat_id in cleartext for easy client-side matching.
    This function queries usage entries by chat_id to show credit usage for a specific chat.
    
    Args:
        directus_service: DirectusService instance
        chat_id: The chat ID
        limit: Maximum number of usage entries to fetch
        
    Returns:
        List of usage entry dictionaries, sorted by created_at descending (newest first)
    """
    script_logger.debug(f"Fetching usage entries for chat_id: {chat_id}")
    
    params = {
        'filter[chat_id][_eq]': chat_id,
        'fields': '*',  # Get all fields
        'sort': '-created_at',  # Newest first
        'limit': limit
    }
    
    try:
        response = await directus_service.get_items('usage', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching usage entries: {e}")
        return []


def build_embed_summary_line(
    embed_id: str,
    decoded: Optional[Dict[str, Any]],
    embed_raw: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build a one-line summary for an embed, suitable for per-message display.

    Format: embed-<short_id>: <type> [<app_id>.<skill_id>] status=<status> results=<N> query="<q>"

    Args:
        embed_id: The embed ID
        decoded: Decoded TOON dict (None if decryption failed or not attempted)
        embed_raw: Raw embed record from Directus (used as fallback for status)

    Returns:
        One-line summary string
    """
    short_id = embed_id[:8] if embed_id else "unknown"

    if decoded:
        embed_type = decoded.get('type', 'unknown')
        app_id = decoded.get('app_id', '')
        skill_id = decoded.get('skill_id', '')
        status = decoded.get('status', embed_raw.get('status', 'N/A') if embed_raw else 'N/A')
        query = decoded.get('query', '')
        result_count = decoded.get('result_count')
        embed_ids = decoded.get('embed_ids')

        parts = [f"embed-{short_id}: {embed_type}"]

        if app_id or skill_id:
            parts.append(f"[{app_id}.{skill_id}]")

        parts.append(f"status={status}")

        if result_count is not None:
            parts.append(f"results={result_count}")
        elif embed_ids and isinstance(embed_ids, list):
            parts.append(f"children={len(embed_ids)}")

        if query:
            truncated_query = query[:MAX_EMBED_SUMMARY_QUERY_LEN]
            if len(query) > MAX_EMBED_SUMMARY_QUERY_LEN:
                truncated_query += "..."
            parts.append(f'query="{truncated_query}"')

        return " ".join(parts)
    else:
        # Fallback: use raw embed data
        status = embed_raw.get('status', 'N/A') if embed_raw else 'N/A'
        has_content = bool(embed_raw.get('encrypted_content')) if embed_raw else False
        return f"embed-{short_id}: (encrypted, not decoded) status={status} content={'present' if has_content else 'missing'}"


async def decrypt_chat_embeds(
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    embeds: List[Dict[str, Any]],
    vault_key_id: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Decrypt and TOON-decode all embeds for a chat, returning a mapping by embed_id.

    Args:
        directus_service: DirectusService instance
        encryption_service: EncryptionService instance
        embeds: List of embed records from Directus
        vault_key_id: The user's Vault transit key ID

    Returns:
        Dictionary mapping embed_id -> decoded_dict (or None if decryption failed)
    """
    decoded_by_id: Dict[str, Optional[Dict[str, Any]]] = {}

    for embed in embeds:
        embed_id = embed.get('embed_id', '')
        encrypted_content = embed.get('encrypted_content')
        if encrypted_content and embed_id:
            decoded, error = await decrypt_and_decode_toon(
                encryption_service, encrypted_content, vault_key_id
            )
            if error:
                script_logger.debug(f"Failed to decode embed {embed_id[:8]}: {error}")
            decoded_by_id[embed_id] = decoded
        elif embed_id:
            decoded_by_id[embed_id] = None

    return decoded_by_id


def build_encryption_health(
    chat_metadata: Optional[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    embeds: List[Dict[str, Any]],
    embed_keys_by_embed: Dict[str, Dict[str, int]],
    vault_key_id: Optional[str]
) -> Dict[str, Any]:
    """
    Build an encryption health dashboard for the chat.

    Checks:
    - Chat key presence (encrypted_chat_key)
    - Title/summary/tags encryption status
    - Per-message encrypted_content completeness
    - Embed key completeness (master vs chat keys)
    - Vault key info

    Args:
        chat_metadata: Chat metadata from Directus
        messages: List of messages from Directus
        embeds: List of embeds from Directus
        embed_keys_by_embed: Dict mapping hashed_embed_id -> {'chat': count, 'master': count}
        vault_key_id: The user's vault_key_id (or None if unresolvable)

    Returns:
        Dictionary with encryption health metrics and anomalies
    """
    health: Dict[str, Any] = {
        'vault_key': {
            'present': vault_key_id is not None,
            'key_id': vault_key_id[:12] + '...' if vault_key_id else None,
        },
        'chat_key': {
            'present': False,
            'encrypted_chat_key_len': 0,
        },
        'encrypted_fields': {},
        'messages': {
            'total': len(messages),
            'with_encrypted_content': 0,
            'without_encrypted_content': 0,
            'missing_content_ids': [],
        },
        'embeds': {
            'total': len(embeds),
            'parent_count': 0,
            'child_count': 0,
            'parents_with_master_key': 0,
            'parents_with_chat_key': 0,
            'parents_missing_all_keys': 0,
            'missing_key_embed_ids': [],
        },
        'anomalies': [],
    }

    if chat_metadata:
        chat_key_val = chat_metadata.get('encrypted_chat_key')
        health['chat_key']['present'] = bool(chat_key_val)
        health['chat_key']['encrypted_chat_key_len'] = len(chat_key_val) if chat_key_val else 0

        # Check encrypted fields
        field_checks = [
            ('encrypted_title', 'title'),
            ('encrypted_chat_summary', 'summary'),
            ('encrypted_chat_tags', 'tags'),
            ('encrypted_icon', 'icon'),
            ('encrypted_category', 'category'),
        ]
        for field_key, label in field_checks:
            val = chat_metadata.get(field_key)
            health['encrypted_fields'][label] = {
                'present': bool(val),
                'length': len(val) if val else 0,
            }

        if not chat_key_val:
            health['anomalies'].append("Chat key (encrypted_chat_key) is MISSING — embeds cannot be decrypted via chat key path")

    # Message completeness
    max_missing_ids_to_track = 10
    for msg in messages:
        if msg.get('encrypted_content'):
            health['messages']['with_encrypted_content'] += 1
        else:
            health['messages']['without_encrypted_content'] += 1
            if len(health['messages']['missing_content_ids']) < max_missing_ids_to_track:
                msg_id = msg.get('id', 'unknown')
                health['messages']['missing_content_ids'].append(str(msg_id)[:12])

    if health['messages']['without_encrypted_content'] > 0:
        health['anomalies'].append(
            f"{health['messages']['without_encrypted_content']} message(s) missing encrypted_content"
        )

    # Embed key completeness
    for embed in embeds:
        embed_id = embed.get('embed_id', '')
        parent_embed_id = embed.get('parent_embed_id')
        if parent_embed_id:
            health['embeds']['child_count'] += 1
            continue  # Child embeds inherit keys from parent

        health['embeds']['parent_count'] += 1
        hashed_embed_id = hashlib.sha256(embed_id.encode()).hexdigest() if embed_id else None

        if hashed_embed_id and hashed_embed_id in embed_keys_by_embed:
            key_info = embed_keys_by_embed[hashed_embed_id]
            if key_info.get('master', 0) > 0:
                health['embeds']['parents_with_master_key'] += 1
            if key_info.get('chat', 0) > 0:
                health['embeds']['parents_with_chat_key'] += 1
        else:
            health['embeds']['parents_missing_all_keys'] += 1
            health['embeds']['missing_key_embed_ids'].append(embed_id[:12] if embed_id else 'unknown')

    if health['embeds']['parents_missing_all_keys'] > 0:
        health['anomalies'].append(
            f"{health['embeds']['parents_missing_all_keys']} parent embed(s) missing ALL encryption keys"
        )

    parents_missing_master = health['embeds']['parent_count'] - health['embeds']['parents_with_master_key']
    if parents_missing_master > 0:
        health['anomalies'].append(
            f"{parents_missing_master} parent embed(s) missing master key (owner cross-chat access broken)"
        )

    parents_missing_chat = health['embeds']['parent_count'] - health['embeds']['parents_with_chat_key']
    if parents_missing_chat > 0:
        health['anomalies'].append(
            f"{parents_missing_chat} parent embed(s) missing chat key (shared access broken)"
        )

    return health


async def check_cache_status(cache_service: CacheService, chat_id: str) -> Dict[str, Any]:
    """
    Check Redis cache status for a chat and its components.
    
    Uses Redis SCAN to find cache keys by pattern since we don't know the user_id.
    Cache keys use the UNHASHED user_id (UUID), not hashed_user_id from Directus.
    The cache key format is: user:{user_id}:chat:{chat_id}:...
    
    Args:
        cache_service: CacheService instance
        chat_id: The chat ID
        
    Returns:
        Dictionary with cache status information
    """
    cache_info = {
        'chat_versions': None,
        'list_item_data': None,
        'ai_messages_count': None,
        'sync_messages_count': None,
        'embed_ids': None,
        'active_ai_task': None,
        'queued_messages_count': None,
        'raw_keys': {},
        'discovered_user_id': None  # Will be populated if we find cache keys
    }
    
    try:
        client = await cache_service.client
        if not client:
            script_logger.warning("Redis client not available for cache checks")
            return cache_info
        
        # 1. Use SCAN to find user-specific cache keys for this chat
        # Pattern: user:*:chat:{chat_id}:* to find any user's cache for this chat
        # This discovers the user_id from the cache key itself
        
        async def scan_for_pattern(pattern: str) -> List[str]:
            """Scan Redis for keys matching pattern."""
            keys = []
            cursor = 0
            while True:
                cursor, batch = await client.scan(cursor, match=pattern, count=100)
                keys.extend([k.decode('utf-8') for k in batch])
                if cursor == 0:
                    break
            return keys
        
        # Find all user-specific keys for this chat
        pattern = f"user:*:chat:{chat_id}:*"
        found_keys = await scan_for_pattern(pattern)
        
        # Extract user_id from found keys and check each type
        user_id = None
        for key in found_keys:
            # Extract user_id from key: user:{user_id}:chat:{chat_id}:...
            parts = key.split(':')
            if len(parts) >= 5 and parts[0] == 'user' and parts[2] == 'chat' and parts[3] == chat_id:
                user_id = parts[1]
                cache_info['discovered_user_id'] = user_id
                break
        
        if user_id:
            # Check chat versions hash
            versions_key = f"user:{user_id}:chat:{chat_id}:versions"
            versions_data = await client.hgetall(versions_key)
            if versions_data:
                cache_info['chat_versions'] = {
                    k.decode('utf-8'): v.decode('utf-8') for k, v in versions_data.items()
                }
                cache_info['raw_keys']['versions'] = versions_key
            
            # Check list item data hash
            list_item_key = f"user:{user_id}:chat:{chat_id}:list_item_data"
            list_item_data = await client.hgetall(list_item_key)
            if list_item_data:
                cache_info['list_item_data'] = {
                    k.decode('utf-8'): truncate_string(v.decode('utf-8'), 100) for k, v in list_item_data.items()
                }
                cache_info['raw_keys']['list_item_data'] = list_item_key
            
            # Check AI messages cache (vault-encrypted, for AI inference)
            ai_messages_key = f"user:{user_id}:chat:{chat_id}:messages:ai"
            ai_messages_count = await client.llen(ai_messages_key)
            if ai_messages_count > 0:
                cache_info['ai_messages_count'] = ai_messages_count
                cache_info['raw_keys']['ai_messages'] = ai_messages_key
            
            # Check sync messages cache (client-encrypted, for sync)
            sync_messages_key = f"user:{user_id}:chat:{chat_id}:messages:sync"
            sync_messages_count = await client.llen(sync_messages_key)
            if sync_messages_count > 0:
                cache_info['sync_messages_count'] = sync_messages_count
                cache_info['raw_keys']['sync_messages'] = sync_messages_key
            
            # Check draft cache
            draft_key = f"user:{user_id}:chat:{chat_id}:draft"
            draft_data = await client.hgetall(draft_key)
            if draft_data:
                cache_info['draft'] = {
                    k.decode('utf-8'): truncate_string(v.decode('utf-8'), 100) for k, v in draft_data.items()
                }
                cache_info['raw_keys']['draft'] = draft_key
        
        # 2. Check embed IDs for this chat (not user-specific)
        embed_ids_key = f"chat:{chat_id}:embed_ids"
        embed_ids = await client.smembers(embed_ids_key)
        if embed_ids:
            cache_info['embed_ids'] = [eid.decode('utf-8') for eid in embed_ids]
            cache_info['raw_keys']['embed_ids'] = embed_ids_key
        
        # 3. Check active AI task marker
        active_task_key = f"chat:{chat_id}:active_ai_task"
        active_task = await client.get(active_task_key)
        if active_task:
            cache_info['active_ai_task'] = active_task.decode('utf-8')
            cache_info['raw_keys']['active_ai_task'] = active_task_key
        
        # 4. Check message queue
        queue_key = f"chat:{chat_id}:message_queue"
        queue_count = await client.llen(queue_key)
        if queue_count > 0:
            cache_info['queued_messages_count'] = queue_count
            cache_info['raw_keys']['message_queue'] = queue_key
        
        return cache_info
    
    except Exception as e:
        script_logger.error(f"Error checking cache status: {e}")
        return cache_info


def format_output_text(
    chat_id: str,
    chat_metadata: Optional[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    embeds: List[Dict[str, Any]],
    embed_keys_by_embed: Dict[str, Dict[str, int]],
    usage_entries: List[Dict[str, Any]],
    cache_info: Dict[str, Any],
    messages_limit: int,
    embeds_limit: int,
    usage_limit: int,
    decoded_embeds: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    encryption_health: Optional[Dict[str, Any]] = None,
    decrypted_messages: Optional[Dict[str, str]] = None,
    share_key_error: Optional[str] = None,
) -> str:
    """
    Format the inspection results as human-readable text.
    
    Args:
        chat_id: The chat ID
        chat_metadata: Chat metadata from Directus
        messages: List of messages from Directus
        embeds: List of embeds from Directus
        embed_keys_by_embed: Dict mapping hashed_embed_id -> {'chat': count, 'master': count}
        usage_entries: List of usage entries from Directus
        cache_info: Cache status information
        messages_limit: Limit for messages display
        embeds_limit: Limit for embeds display
        usage_limit: Limit for usage entries display
        decoded_embeds: Dict mapping embed_id -> decoded TOON dict (if --decrypt was used)
        encryption_health: Encryption health dashboard data (if --decrypt was used)
        decrypted_messages: Dict mapping message_id -> plaintext (if share key was used)
        share_key_error: Error message if share key decryption failed
        
    Returns:
        Formatted string for display
    """
    lines = []
    
    # Header
    lines.append("")
    lines.append("=" * 100)
    lines.append("CHAT INSPECTION REPORT")
    lines.append("=" * 100)
    lines.append(f"Chat ID: {chat_id}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if decrypted_messages is not None:
        lines.append("🔓 CLIENT-SIDE DECRYPTION: Active (share key provided)")
    if share_key_error:
        lines.append(f"❌ SHARE KEY ERROR: {share_key_error}")
    lines.append("=" * 100)

    # ===================== HEALTH CHECK SUMMARY =====================
    health_summary = build_chat_health_summary(
        chat_metadata=chat_metadata,
        messages=messages,
        embeds=embeds,
        usage_entries=usage_entries,
        cache_info=cache_info,
        encryption_health=encryption_health,
        share_key_error=share_key_error,
    )

    version_check = health_summary['version_check']
    status_line = "🟢 HEALTH CHECK: HEALTHY" if health_summary['is_healthy'] else "🔴 HEALTH CHECK: ISSUES DETECTED"
    lines.append(status_line)
    lines.append(
        f"   messages={health_summary['counts']['messages']} embeds={health_summary['counts']['embeds']} "
        f"usage={health_summary['counts']['usage_entries']}"
    )

    if health_summary['issues']:
        lines.append("   Issues:")
        for issue in health_summary['issues'][:MAX_HEALTH_ISSUES_TO_SHOW]:
            lines.append(f"    - {issue}")
        remaining_issues = len(health_summary['issues']) - MAX_HEALTH_ISSUES_TO_SHOW
        if remaining_issues > 0:
            lines.append(f"    - ... and {remaining_issues} more issue(s)")

    if health_summary['warnings']:
        lines.append("   Warnings:")
        for warning in health_summary['warnings'][:MAX_HEALTH_ISSUES_TO_SHOW]:
            lines.append(f"    - {warning}")
    lines.append("=" * 100)
    
    # ===================== VERSION CONSISTENCY CHECK =====================
    # Check for version mismatches between message count, Directus, and cache
    actual_message_count = version_check['actual_message_count']
    directus_messages_v = version_check['directus_messages_v']
    cache_messages_v = version_check['cache_messages_v']
    version_issues = version_check['issues']

    if version_issues:
        lines.append("")
        lines.append("🚨" + "=" * 96 + "🚨")
        lines.append("🚨  VERSION CONSISTENCY ISSUES DETECTED!")
        lines.append("🚨" + "=" * 96 + "🚨")
        lines.append("")
        lines.append(f"  📊 Actual Messages in Directus: {actual_message_count}")
        lines.append(f"  📝 messages_v in Directus:      {directus_messages_v if directus_messages_v is not None else 'N/A'}")
        lines.append(f"  💾 messages_v in Cache:         {cache_messages_v if cache_messages_v is not None else 'NOT CACHED'}")
        lines.append("")
        lines.append("  ❌ ISSUES:")
        for issue in version_issues:
            lines.append(f"     • {issue}")
        lines.append("")
        lines.append("  ℹ️  EXPECTED: messages_v should equal the actual message count.")
        lines.append("     This mismatch may indicate double-counting bugs in version tracking.")
        lines.append("🚨" + "=" * 96 + "🚨")
    else:
        # Show version consistency status (all good)
        lines.append("")
        lines.append("-" * 100)
        lines.append("VERSION CONSISTENCY CHECK")
        lines.append("-" * 100)
        lines.append("  ✅ All versions consistent:")
        lines.append(f"     • Actual Messages: {actual_message_count}")
        lines.append(f"     • Directus messages_v: {directus_messages_v if directus_messages_v is not None else 'N/A'}")
        lines.append(f"     • Cache messages_v: {cache_messages_v if cache_messages_v is not None else 'NOT CACHED'}")
    
    # ===================== CHAT METADATA =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("CHAT METADATA (from Directus)")
    lines.append("-" * 100)
    
    if not chat_metadata:
        lines.append("❌ Chat NOT FOUND in Directus")
    else:
        # Core metadata
        lines.append(f"  Hashed User ID:              {truncate_string(chat_metadata.get('hashed_user_id', 'N/A'), 20)}...")
        lines.append(f"  Created At:                  {format_timestamp(chat_metadata.get('created_at'))}")
        lines.append(f"  Updated At:                  {format_timestamp(chat_metadata.get('updated_at'))}")
        lines.append(f"  Last Message Timestamp:      {format_timestamp(chat_metadata.get('last_message_timestamp'))}")
        lines.append(f"  Last Edited Overall TS:      {format_timestamp(chat_metadata.get('last_edited_overall_timestamp'))}")
        lines.append("")
        
        # Version tracking
        lines.append(f"  Messages Version (messages_v): {chat_metadata.get('messages_v', 'N/A')}")
        lines.append(f"  Title Version (title_v):       {chat_metadata.get('title_v', 'N/A')}")
        lines.append(f"  Unread Count:                  {chat_metadata.get('unread_count', 0)}")
        lines.append(f"  Pinned:                        {chat_metadata.get('pinned', False)}")
        lines.append("")
        
        # Sharing status
        lines.append(f"  Is Private:                  {chat_metadata.get('is_private', 'N/A')}")
        lines.append(f"  Is Shared:                   {chat_metadata.get('is_shared', 'N/A')}")
        lines.append(f"  Shared Timestamp:            {format_timestamp(chat_metadata.get('shared_timestamp'))}")
        shared_users = chat_metadata.get('shared_with_user_hashes')
        if shared_users:
            lines.append(f"  Shared With Users:           {len(shared_users)} user(s)")
        lines.append("")
        
        # Encrypted fields (show presence only)
        encrypted_fields = [
            ('encrypted_title', 'Title'),
            ('encrypted_chat_key', 'Chat Key'),
            ('encrypted_chat_summary', 'Summary'),
            ('encrypted_chat_tags', 'Tags'),
            ('encrypted_icon', 'Icon'),
            ('encrypted_category', 'Category'),
            ('encrypted_active_focus_id', 'Active Focus'),
            ('encrypted_follow_up_request_suggestions', 'Follow-up Suggestions'),
            ('encrypted_top_recommended_apps_for_chat', 'Recommended Apps'),
        ]
        
        lines.append("  Encrypted Fields Present:")
        for field_key, field_name in encrypted_fields:
            value = chat_metadata.get(field_key)
            has_value = "✓" if value else "✗"
            size_info = f" ({len(value)} chars)" if value else ""
            lines.append(f"    {has_value} {field_name}{size_info}")
    
    # ===================== MESSAGES =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"MESSAGES (from Directus) - Total: {len(messages)}")
    lines.append("-" * 100)
    
    if not messages:
        lines.append("  No messages found for this chat.")
    else:
        # Show summary
        roles_count = {}
        for msg in messages:
            role = msg.get('role', 'unknown')
            roles_count[role] = roles_count.get(role, 0) + 1
        
        lines.append(f"  Role Distribution: {roles_count}")
        lines.append("")
        
        # Show message list (limited)
        display_messages = messages[:messages_limit]
        lines.append(f"  Showing {len(display_messages)} of {len(messages)} messages:")
        lines.append("")
        
        for i, msg in enumerate(display_messages, 1):
            msg_id = msg.get('id', 'N/A')
            client_msg_id = msg.get('client_message_id', 'N/A')
            role = msg.get('role', 'unknown')
            created_at = format_timestamp(msg.get('created_at'))
            has_content = "✓" if msg.get('encrypted_content') else "✗"
            content_len = len(msg.get('encrypted_content', '')) if msg.get('encrypted_content') else 0
            
            # Role indicator
            role_emoji = {"user": "👤", "assistant": "🤖", "system": "⚙️"}.get(role, "❓")
            
            lines.append(f"  {i:3}. {role_emoji} [{role:9}] {created_at}")
            lines.append(f"       ID: {msg_id[:8]}...  Client ID: {truncate_string(client_msg_id, 25)}")
            lines.append(f"       Content: {has_content} ({content_len} chars encrypted)")
            
            # Show decrypted plaintext if share key was used
            if decrypted_messages is not None:
                msg_id_str = str(msg.get('id', ''))
                plaintext = decrypted_messages.get(msg_id_str)
                if plaintext and not plaintext.startswith('[DECRYPT ERROR:'):
                    lines.append("       🔓 Decrypted Content:")
                    # Show full plaintext, indented and wrapped
                    for pt_line in plaintext.split('\n'):
                        lines.append(f"          {pt_line}")
                elif plaintext:
                    lines.append(f"       ❌ {plaintext}")
            
            # Show if model name is present (for assistant messages)
            if msg.get('encrypted_model_name'):
                lines.append("       Model: ✓ (encrypted)")
            
            # Show per-message embed summaries (improvement B)
            if decoded_embeds is not None:
                # Find embeds for this message by hashed_message_id
                msg_id_raw = msg.get('id', '')
                hashed_msg_id = hashlib.sha256(str(msg_id_raw).encode()).hexdigest() if msg_id_raw else None
                
                if hashed_msg_id:
                    msg_embeds = [
                        e for e in embeds
                        if e.get('hashed_message_id') == hashed_msg_id
                    ]
                    if msg_embeds:
                        lines.append(f"       Embeds ({len(msg_embeds)}):")
                        for me in msg_embeds[:MAX_EMBED_SUMMARY_DISPLAY]:
                            me_id = me.get('embed_id', '')
                            me_decoded = decoded_embeds.get(me_id)
                            summary = build_embed_summary_line(me_id, me_decoded, me)
                            lines.append(f"         • {summary}")
                        if len(msg_embeds) > MAX_EMBED_SUMMARY_DISPLAY:
                            lines.append(f"         ... and {len(msg_embeds) - MAX_EMBED_SUMMARY_DISPLAY} more embed(s)")
        
        if len(messages) > messages_limit:
            lines.append(f"\n  ... and {len(messages) - messages_limit} more message(s)")
    
    # ===================== EMBEDS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"EMBEDS (from Directus) - Total: {len(embeds)}")
    lines.append("-" * 100)
    
    if not embeds:
        lines.append("  No embeds found for this chat.")
    else:
        # Show summary by status
        status_count = {}
        for embed in embeds:
            status = embed.get('status', 'unknown')
            status_count[status] = status_count.get(status, 0) + 1
        
        lines.append(f"  Status Distribution: {status_count}")
        
        # Show encryption keys summary
        # Count embeds with their own keys vs child embeds (which inherit from parent)
        total_chat_keys = sum(k.get('chat', 0) for k in embed_keys_by_embed.values())
        total_master_keys = sum(k.get('master', 0) for k in embed_keys_by_embed.values())
        embeds_with_keys = len(embed_keys_by_embed)
        
        # Child embeds inherit keys from their parent, so they don't need their own keys
        child_embeds_count = sum(1 for e in embeds if e.get('parent_embed_id'))
        parent_embeds_count = len(embeds) - child_embeds_count
        
        # Only parent/root embeds should have their own keys - child embeds inherit
        truly_missing_keys = parent_embeds_count - embeds_with_keys
        
        lines.append(f"  Encryption Keys: {total_chat_keys} chat-type, {total_master_keys} master-type")
        lines.append(f"  Parent/root embeds: {parent_embeds_count} (with keys: {embeds_with_keys})")
        lines.append(f"  Child embeds: {child_embeds_count} (inherit keys from parent)")
        if truly_missing_keys > 0:
            lines.append(f"  ⚠️  Truly missing keys: {truly_missing_keys} parent embed(s) without keys")
        else:
            lines.append("  ✅ All parent embeds have encryption keys")
        lines.append("")
        
        # Show embed list (limited)
        display_embeds = embeds[:embeds_limit]
        lines.append(f"  Showing {len(display_embeds)} of {len(embeds)} embeds:")
        lines.append("")
        
        for i, embed in enumerate(display_embeds, 1):
            embed_id = embed.get('embed_id', 'N/A')
            directus_id = embed.get('id', 'N/A')
            status = embed.get('status', 'unknown')
            created_at = format_timestamp(embed.get('created_at'))
            updated_at = format_timestamp(embed.get('updated_at'))
            has_content = "✓" if embed.get('encrypted_content') else "✗"
            content_len = len(embed.get('encrypted_content', '')) if embed.get('encrypted_content') else 0
            has_type = "✓" if embed.get('encrypted_type') else "✗"
            
            # Status indicator
            status_emoji = {"processing": "⏳", "finished": "✅", "error": "❌"}.get(status, "❓")
            
            lines.append(f"  {i:3}. {status_emoji} [{status:10}] {created_at}")
            lines.append(f"       Embed ID: {embed_id}")
            lines.append(f"       Directus ID: {directus_id}")
            lines.append(f"       Type: {has_type}  Content: {has_content} ({content_len} chars)")
            lines.append(f"       Updated: {updated_at}")
            
            # Show additional info
            if embed.get('parent_embed_id'):
                lines.append(f"       Parent: {embed.get('parent_embed_id')}")
            if embed.get('version_number'):
                lines.append(f"       Version: {embed.get('version_number')}")
            if embed.get('embed_ids'):
                lines.append(f"       Child Embeds: {len(embed.get('embed_ids', []))} item(s)")
            
            # Show encryption keys for this embed
            # Need to hash embed_id to lookup in embed_keys_by_embed
            hashed_embed_id = hashlib.sha256(embed_id.encode()).hexdigest() if embed_id and embed_id != 'N/A' else None
            parent_embed_id = embed.get('parent_embed_id')
            
            if hashed_embed_id and hashed_embed_id in embed_keys_by_embed:
                # This embed has its own encryption keys
                key_info = embed_keys_by_embed[hashed_embed_id]
                chat_keys = key_info.get('chat', 0)
                master_keys = key_info.get('master', 0)
                total_keys = chat_keys + master_keys
                
                # Build key status display
                key_parts = []
                if chat_keys > 0:
                    key_parts.append(f"{chat_keys} chat")
                if master_keys > 0:
                    key_parts.append(f"{master_keys} master")
                
                key_display = ', '.join(key_parts) if key_parts else "none"
                lines.append(f"       🔑 Encryption Keys: {total_keys} total ({key_display})")
            elif parent_embed_id:
                # Child embeds inherit encryption keys from their parent - this is expected
                lines.append(f"       🔑 Encryption Keys: ✅ Inherits from parent ({parent_embed_id[:8]}...)")
            else:
                # Root/parent embed without keys - this is a problem
                lines.append("       🔑 Encryption Keys: ❌ MISSING (parent embed has no keys in embed_keys collection)")
        
        if len(embeds) > embeds_limit:
            lines.append(f"\n  ... and {len(embeds) - embeds_limit} more embed(s)")
    
    # ===================== USAGE ENTRIES =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"USAGE ENTRIES (from Directus) - Total: {len(usage_entries)}")
    lines.append("-" * 100)
    
    if not usage_entries:
        lines.append("  No usage entries found for this chat.")
    else:
        # Show summary by app_id and skill_id
        app_skill_count = {}
        for entry in usage_entries:
            app_id = entry.get('app_id', 'unknown')
            skill_id = entry.get('skill_id', 'unknown')
            key = f"{app_id}.{skill_id}"
            app_skill_count[key] = app_skill_count.get(key, 0) + 1
        
        lines.append(f"  App.Skill Distribution: {app_skill_count}")
        lines.append("")
        
        # Show usage entry list (limited)
        display_usage = usage_entries[:usage_limit]
        lines.append(f"  Showing {len(display_usage)} of {len(usage_entries)} usage entries:")
        lines.append("")
        
        for i, entry in enumerate(display_usage, 1):
            usage_id = entry.get('id', 'N/A')
            app_id = entry.get('app_id', 'N/A')
            skill_id = entry.get('skill_id', 'N/A')
            source = entry.get('source', 'N/A')
            message_id = entry.get('message_id', 'N/A')
            created_at = format_timestamp(entry.get('created_at'))
            
            # Encrypted fields presence
            has_model = "✓" if entry.get('encrypted_model_used') else "✗"
            has_credits = "✓" if entry.get('encrypted_credits_costs_total') else "✗"
            has_input_tokens = "✓" if entry.get('encrypted_input_tokens') else "✗"
            has_output_tokens = "✓" if entry.get('encrypted_output_tokens') else "✗"
            
            # Source indicator
            source_emoji = {"chat": "💬", "api_key": "🔑", "direct": "📡"}.get(source, "❓")
            
            lines.append(f"  {i:3}. {source_emoji} [{app_id}.{skill_id:12}] {created_at}")
            lines.append(f"       Usage ID: {usage_id[:8]}...")
            lines.append(f"       Message ID: {truncate_string(message_id, 40)}")
            lines.append(f"       Source: {source}")
            lines.append(f"       Encrypted: Model={has_model}  Credits={has_credits}  Input={has_input_tokens}  Output={has_output_tokens}")
        
        if len(usage_entries) > usage_limit:
            lines.append(f"\n  ... and {len(usage_entries) - usage_limit} more usage entry(ies)")
    
    # ===================== ENCRYPTION HEALTH (improvement G) =====================
    if encryption_health is not None:
        lines.append("")
        lines.append("-" * 100)
        lines.append("ENCRYPTION HEALTH DASHBOARD")
        lines.append("-" * 100)
        
        # Vault key
        vk = encryption_health.get('vault_key', {})
        if vk.get('present'):
            lines.append(f"  ✅ Vault Key: {vk.get('key_id', 'N/A')}")
        else:
            lines.append("  ❌ Vault Key: NOT RESOLVABLE (user may not have passkeys)")
        
        # Chat key
        ck = encryption_health.get('chat_key', {})
        if ck.get('present'):
            lines.append(f"  ✅ Chat Key: present ({ck.get('encrypted_chat_key_len', 0)} chars)")
        else:
            lines.append("  ❌ Chat Key: MISSING")
        
        # Encrypted fields
        ef = encryption_health.get('encrypted_fields', {})
        lines.append("")
        lines.append("  Chat Encrypted Fields:")
        for label, info in ef.items():
            marker = "✓" if info.get('present') else "✗"
            size = f" ({info.get('length', 0)} chars)" if info.get('present') else ""
            lines.append(f"    {marker} {label}{size}")
        
        # Messages
        msg_health = encryption_health.get('messages', {})
        total_msgs = msg_health.get('total', 0)
        with_content = msg_health.get('with_encrypted_content', 0)
        without_content = msg_health.get('without_encrypted_content', 0)
        lines.append("")
        lines.append(f"  Messages: {with_content}/{total_msgs} have encrypted_content")
        if without_content > 0:
            missing_ids = msg_health.get('missing_content_ids', [])
            lines.append(f"  ⚠️  {without_content} message(s) missing encrypted_content")
            if missing_ids:
                lines.append(f"     Missing IDs: {', '.join(missing_ids[:5])}")
                if len(missing_ids) > 5:
                    lines.append(f"     ... and {len(missing_ids) - 5} more")
        
        # Embeds
        emb_health = encryption_health.get('embeds', {})
        parent_count = emb_health.get('parent_count', 0)
        child_count = emb_health.get('child_count', 0)
        with_master = emb_health.get('parents_with_master_key', 0)
        with_chat = emb_health.get('parents_with_chat_key', 0)
        missing_all = emb_health.get('parents_missing_all_keys', 0)
        lines.append("")
        lines.append(f"  Embed Keys: {parent_count} parent embeds, {child_count} child embeds (inherit)")
        lines.append(f"    Master keys: {with_master}/{parent_count}")
        lines.append(f"    Chat keys:   {with_chat}/{parent_count}")
        if missing_all > 0:
            missing_ids = emb_health.get('missing_key_embed_ids', [])
            lines.append(f"    ❌ {missing_all} parent(s) missing ALL keys: {', '.join(missing_ids[:5])}")
        
        # Anomalies
        anomalies = encryption_health.get('anomalies', [])
        if anomalies:
            lines.append("")
            lines.append("  ⚠️  Anomalies:")
            for a in anomalies:
                lines.append(f"    • {a}")
        else:
            lines.append("")
            lines.append("  ✅ No encryption anomalies detected")
    
    # ===================== CACHE STATUS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("CACHE STATUS (from Redis)")
    lines.append("-" * 100)
    
    # Show discovered user_id if found
    if cache_info.get('discovered_user_id'):
        lines.append(f"  🔍 Discovered User ID: {cache_info['discovered_user_id']}")
        lines.append("")
    
    # Chat versions
    if cache_info.get('chat_versions'):
        lines.append("  ✅ Chat Versions Cached:")
        for k, v in cache_info['chat_versions'].items():
            lines.append(f"     {k}: {v}")
        lines.append(f"     Key: {cache_info['raw_keys'].get('versions', 'N/A')}")
    else:
        lines.append("  ❌ Chat Versions: NOT CACHED")
    
    lines.append("")
    
    # List item data
    if cache_info.get('list_item_data'):
        lines.append("  ✅ List Item Data Cached:")
        for k, v in cache_info['list_item_data'].items():
            lines.append(f"     {k}: {v}")
        lines.append(f"     Key: {cache_info['raw_keys'].get('list_item_data', 'N/A')}")
    else:
        lines.append("  ❌ List Item Data: NOT CACHED")
    
    lines.append("")
    
    # AI Messages
    if cache_info.get('ai_messages_count') is not None and cache_info['ai_messages_count'] > 0:
        lines.append(f"  ✅ AI Messages Cached: {cache_info['ai_messages_count']} message(s)")
        lines.append(f"     Key: {cache_info['raw_keys'].get('ai_messages', 'N/A')}")
    else:
        lines.append("  ❌ AI Messages: NOT CACHED")
    
    lines.append("")
    
    # Sync Messages
    if cache_info.get('sync_messages_count') is not None and cache_info['sync_messages_count'] > 0:
        lines.append(f"  ✅ Sync Messages Cached: {cache_info['sync_messages_count']} message(s)")
        lines.append(f"     Key: {cache_info['raw_keys'].get('sync_messages', 'N/A')}")
    else:
        lines.append("  ❌ Sync Messages: NOT CACHED")
    
    lines.append("")
    
    # Draft
    if cache_info.get('draft'):
        lines.append("  ✅ Draft Cached:")
        for k, v in cache_info['draft'].items():
            lines.append(f"     {k}: {v}")
        lines.append(f"     Key: {cache_info['raw_keys'].get('draft', 'N/A')}")
    else:
        lines.append("  ❌ Draft: NOT CACHED")
    
    lines.append("")
    
    # Embed IDs
    if cache_info.get('embed_ids'):
        lines.append(f"  ✅ Embed IDs Indexed: {len(cache_info['embed_ids'])} embed(s)")
        lines.append(f"     Key: {cache_info['raw_keys'].get('embed_ids', 'N/A')}")
        for eid in cache_info['embed_ids'][:5]:
            lines.append(f"     - {eid}")
        if len(cache_info['embed_ids']) > 5:
            lines.append(f"     ... and {len(cache_info['embed_ids']) - 5} more")
    else:
        lines.append("  ❌ Embed IDs: NOT INDEXED")
    
    lines.append("")
    
    # Active AI Task
    if cache_info.get('active_ai_task'):
        lines.append(f"  ⚠️  Active AI Task: {cache_info['active_ai_task']}")
        lines.append(f"     Key: {cache_info['raw_keys'].get('active_ai_task', 'N/A')}")
    else:
        lines.append("  ❌ Active AI Task: None")
    
    # Queued Messages
    if cache_info.get('queued_messages_count') is not None and cache_info['queued_messages_count'] > 0:
        lines.append(f"  ⚠️  Queued Messages: {cache_info['queued_messages_count']}")
        lines.append(f"     Key: {cache_info['raw_keys'].get('message_queue', 'N/A')}")
    
    lines.append("")
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    lines.append("")
    
    return "\n".join(lines)


def format_output_json(
    chat_id: str,
    chat_metadata: Optional[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    embeds: List[Dict[str, Any]],
    embed_keys_by_embed: Dict[str, Dict[str, int]],
    usage_entries: List[Dict[str, Any]],
    cache_info: Dict[str, Any],
    decoded_embeds: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    encryption_health: Optional[Dict[str, Any]] = None,
    decrypted_messages: Optional[Dict[str, str]] = None,
    share_key_error: Optional[str] = None,
) -> str:
    """
    Format the inspection results as JSON.
    
    Args:
        chat_id: The chat ID
        chat_metadata: Chat metadata from Directus
        messages: List of messages from Directus
        embeds: List of embeds from Directus
        embed_keys_by_embed: Dict mapping hashed_embed_id -> {'chat': count, 'master': count}
        usage_entries: List of usage entries from Directus
        cache_info: Cache status information
        decoded_embeds: Dict mapping embed_id -> decoded TOON dict (if --decrypt)
        encryption_health: Encryption health dashboard data (if --decrypt)
        decrypted_messages: Dict mapping message_id -> plaintext (if share key was used)
        share_key_error: Error message if share key decryption failed
        
    Returns:
        JSON string
    """
    health_summary = build_chat_health_summary(
        chat_metadata=chat_metadata,
        messages=messages,
        embeds=embeds,
        usage_entries=usage_entries,
        cache_info=cache_info,
        encryption_health=encryption_health,
        share_key_error=share_key_error,
    )

    # Calculate embed key stats
    total_chat_keys = sum(k.get('chat', 0) for k in embed_keys_by_embed.values())
    total_master_keys = sum(k.get('master', 0) for k in embed_keys_by_embed.values())
    
    output: Dict[str, Any] = {
        'chat_id': chat_id,
        'generated_at': datetime.now().isoformat(),
        'chat_metadata': chat_metadata,
        'messages': {
            'count': len(messages),
            'items': messages
        },
        'embeds': {
            'count': len(embeds),
            'items': embeds
        },
        'embed_keys': {
            'embeds_with_keys': len(embed_keys_by_embed),
            'total_chat_keys': total_chat_keys,
            'total_master_keys': total_master_keys,
            'by_hashed_embed_id': embed_keys_by_embed
        },
        'usage': {
            'count': len(usage_entries),
            'items': usage_entries
        },
        'cache': cache_info,
        'health_check': health_summary,
    }
    
    # Add decoded embed summaries if available (improvement B)
    if decoded_embeds is not None:
        embed_summaries = {}
        for embed_id, decoded in decoded_embeds.items():
            if decoded:
                embed_summaries[embed_id] = {
                    'field_inventory': {k: describe_toon_value(v) for k, v in decoded.items()},
                    'key_metadata': {
                        k: decoded[k] for k in ['app_id', 'skill_id', 'status', 'type',
                                                  'query', 'provider', 'result_count']
                        if k in decoded
                    },
                    'summary': build_embed_summary_line(embed_id, decoded),
                }
            else:
                embed_summaries[embed_id] = None
        output['decoded_embeds'] = embed_summaries
    
    # Add encryption health if available (improvement G)
    if encryption_health is not None:
        output['encryption_health'] = encryption_health
    
    # Add client-side decrypted messages if available
    if decrypted_messages is not None:
        output['decrypted_messages'] = decrypted_messages
    if share_key_error:
        output['share_key_error'] = share_key_error
    
    return json.dumps(output, indent=2, default=str)


async def main():
    """Main function that inspects a chat.
    
    Supports two data sources:
    - Local mode (default): queries Directus and Redis directly inside the Docker container
    - Production mode (--production): fetches data from the remote Admin Debug API,
      then optionally decrypts with --share-url/--share-key (client-side AES only)
    """
    parser = argparse.ArgumentParser(
        description='Inspect chat data including metadata, messages, embeds, and cache status'
    )
    parser.add_argument(
        'chat_id',
        type=str,
        help='Chat ID (UUID format) to inspect'
    )
    parser.add_argument(
        '--messages-limit',
        type=int,
        default=20,
        help='Limit number of messages to display (default: 20)'
    )
    parser.add_argument(
        '--embeds-limit',
        type=int,
        default=20,
        help='Limit number of embeds to display (default: 20)'
    )
    parser.add_argument(
        '--usage-limit',
        type=int,
        default=20,
        help='Limit number of usage entries to display (default: 20)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of formatted text'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Skip cache checks (faster if Redis is unavailable)'
    )
    parser.add_argument(
        '--decrypt',
        action='store_true',
        help='Decrypt embeds via Vault (server-side encryption only)'
    )
    parser.add_argument(
        '--share-url',
        type=str,
        default=None,
        help='Share URL with #key= fragment for client-side AES decryption of messages and embeds'
    )
    parser.add_argument(
        '--share-key',
        type=str,
        default=None,
        help='Raw base64 key blob (the part after #key= in the share URL)'
    )
    parser.add_argument(
        '--share-password',
        type=str,
        default=None,
        help='Password for password-protected share links'
    )
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
    
    if is_remote and args.decrypt:
        print(
            "Error: --decrypt (Vault server-side decryption) is not available in production mode.\n"
            "  Vault is not accessible from the dev server.\n"
            "  Use --share-url or --share-key for client-side AES decryption instead.",
            file=sys.stderr,
        )
        sys.exit(1)
    
    if is_remote and args.no_cache:
        # --no-cache is meaningless in production mode (we can't access prod Redis directly,
        # but the API returns cache info for us). Just ignore silently.
        pass
    
    script_logger.info(f"Inspecting chat: {args.chat_id}")
    
    if is_remote:
        # ---- PRODUCTION / DEV API MODE ----
        # Fetch all data in a single API call, then map to local format
        source_label = "dev" if args.dev else "production"
        script_logger.info(f"Using {source_label} Admin Debug API")
        
        api_response = await fetch_chat_from_production_api(
            args.chat_id,
            messages_limit=args.messages_limit,
            embeds_limit=args.embeds_limit,
            usage_limit=args.usage_limit,
            use_dev=args.dev,
        )
        
        mapped = map_production_chat_response(api_response)
        chat_metadata = mapped["chat_metadata"]
        messages = mapped["messages"]
        embeds = mapped["embeds"]
        embed_keys_by_embed = mapped["embed_keys_by_embed"]
        usage_entries = mapped["usage_entries"]
        cache_info = mapped["cache_info"]
        
        # Vault decryption is not available in production mode
        decoded_embeds: Optional[Dict[str, Optional[Dict[str, Any]]]] = None
        encryption_health: Optional[Dict[str, Any]] = None
        
        # Client-side AES decryption via share key (--share-url or --share-key)
        decrypted_messages: Optional[Dict[str, str]] = None
        share_key_error: Optional[str] = None
        
        if args.share_url or args.share_key:
            chat_key_bytes: Optional[bytes] = None
            
            if args.share_url:
                entity_type, entity_id, key_blob = parse_share_url(args.share_url)
                if entity_type == 'chat' and entity_id and key_blob:
                    if entity_id != args.chat_id:
                        share_key_error = (
                            f"Share URL chat ID ({entity_id}) does not match "
                            f"inspected chat ID ({args.chat_id})"
                        )
                    else:
                        chat_key_bytes, share_key_error = decrypt_share_key_blob(
                            entity_id, key_blob,
                            key_field_name='chat_encryption_key',
                            password=args.share_password,
                        )
                else:
                    share_key_error = (
                        "Could not parse share URL. Expected format: "
                        "https://<domain>/share/chat/<chatId>#key=<blob>"
                    )
            elif args.share_key:
                chat_key_bytes, share_key_error = decrypt_share_key_blob(
                    args.chat_id, args.share_key,
                    key_field_name='chat_encryption_key',
                    password=args.share_password,
                )
            
            if chat_key_bytes and not share_key_error:
                script_logger.info("Share key decrypted successfully, decrypting messages...")
                decrypted_messages = {}
                decrypt_ok = 0
                decrypt_fail = 0
                
                for msg in messages:
                    msg_id = str(msg.get('id', ''))
                    encrypted_content = msg.get('encrypted_content')
                    if encrypted_content and msg_id:
                        plaintext, err = decrypt_client_aes_content(
                            encrypted_content, chat_key_bytes
                        )
                        if plaintext:
                            decrypted_messages[msg_id] = plaintext
                            decrypt_ok += 1
                        else:
                            decrypted_messages[msg_id] = f"[DECRYPT ERROR: {err}]"
                            decrypt_fail += 1
                
                script_logger.info(
                    f"Decrypted {decrypt_ok} messages "
                    f"({decrypt_fail} failed) out of {len(messages)} total"
                )
                
                # Also decrypt embed content with the chat key
                if embeds:
                    decoded_embeds = decoded_embeds or {}
                for embed in embeds:
                    embed_id = embed.get('embed_id', '')
                    enc_content = embed.get('encrypted_content')
                    if enc_content and embed_id:
                        plaintext, err = decrypt_client_aes_content(
                            enc_content, chat_key_bytes
                        )
                        if plaintext:
                            try:
                                from toon_format import decode as toon_decode
                                decoded = toon_decode(plaintext)
                                if isinstance(decoded, dict):
                                    decoded_embeds[embed_id] = decoded  # type: ignore[index]
                                    continue
                            except Exception:
                                pass
                            try:
                                decoded = json.loads(plaintext)
                                if isinstance(decoded, dict):
                                    decoded_embeds[embed_id] = decoded  # type: ignore[index]
                                    continue
                            except Exception:
                                pass
                            decoded_embeds[embed_id] = {'_raw_plaintext': plaintext}  # type: ignore[index]
                        else:
                            script_logger.debug(
                                f"Could not decrypt embed {embed_id[:8]} with chat key: {err}"
                            )
            elif share_key_error:
                script_logger.error(f"Share key error: {share_key_error}")
        
        # Format and output results
        if args.json:
            output = format_output_json(
                args.chat_id, chat_metadata, messages, embeds,
                embed_keys_by_embed, usage_entries, cache_info,
                decoded_embeds, encryption_health,
                decrypted_messages, share_key_error,
            )
        else:
            output = format_output_text(
                args.chat_id,
                chat_metadata,
                messages,
                embeds,
                embed_keys_by_embed,
                usage_entries,
                cache_info,
                args.messages_limit,
                args.embeds_limit,
                args.usage_limit,
                decoded_embeds,
                encryption_health,
                decrypted_messages,
                share_key_error,
            )
        
        print(output)
    
    else:
        # ---- LOCAL MODE (default) ----
        # Initialize services for direct Directus/Redis access
        cache_service = CacheService()
        encryption_service = EncryptionService()
        directus_service = DirectusService(
            cache_service=cache_service,
            encryption_service=encryption_service
        )
        
        try:
            # 1. Fetch chat metadata
            chat_metadata = await get_chat_metadata(directus_service, args.chat_id)
            
            # 2. Fetch messages
            messages = await get_chat_messages(
                directus_service, 
                args.chat_id, 
                limit=args.messages_limit + 100 if not args.json else 10000
            )
            
            # 3. Fetch embeds
            embeds = await get_chat_embeds(
                directus_service, 
                args.chat_id,
                limit=args.embeds_limit + 100 if not args.json else 10000
            )
            
            # 4. Fetch embed encryption keys (from embed_keys collection)
            embed_keys_by_embed = await get_embed_keys_for_chat(directus_service, args.chat_id)
            
            # 5. Fetch usage entries
            usage_entries = await get_chat_usage_entries(
                directus_service,
                args.chat_id,
                limit=args.usage_limit + 100 if not args.json else 10000
            )
            
            # 6. Check cache status (if not skipped)
            cache_info = {}
            if not args.no_cache:
                cache_info = await check_cache_status(cache_service, args.chat_id)
            
            # 7. Decrypt embed content and build encryption health (if --decrypt)
            decoded_embeds: Optional[Dict[str, Optional[Dict[str, Any]]]] = None  # type: ignore[no-redef]
            encryption_health: Optional[Dict[str, Any]] = None  # type: ignore[no-redef]
            vault_key_id: Optional[str] = None
            
            if args.decrypt and chat_metadata:
                hashed_user_id = chat_metadata.get('hashed_user_id')
                if hashed_user_id:
                    vault_key_id = await resolve_vault_key_id(directus_service, hashed_user_id)
                    if vault_key_id:
                        script_logger.info(f"Resolved vault_key_id: {vault_key_id[:12]}...")
                        decoded_embeds = await decrypt_chat_embeds(
                            directus_service, encryption_service, embeds, vault_key_id
                        )
                        decode_success = sum(1 for v in decoded_embeds.values() if v is not None)
                        script_logger.info(
                            f"Decoded {decode_success}/{len(decoded_embeds)} embeds"
                        )
                    else:
                        script_logger.warning(
                            "Could not resolve vault_key_id — "
                            "user may not have passkeys registered"
                        )
                        decoded_embeds = {}
                else:
                    script_logger.warning("Chat has no hashed_user_id — cannot decrypt")
                    decoded_embeds = {}
            
            if args.decrypt:
                encryption_health = build_encryption_health(
                    chat_metadata, messages, embeds, embed_keys_by_embed, vault_key_id
                )
            
            # 8. Client-side AES decryption via share key (--share-url or --share-key)
            decrypted_messages: Optional[Dict[str, str]] = None  # type: ignore[no-redef]
            share_key_error: Optional[str] = None  # type: ignore[no-redef]
            
            if args.share_url or args.share_key:
                chat_key_bytes: Optional[bytes] = None
                
                if args.share_url:
                    entity_type, entity_id, key_blob = parse_share_url(args.share_url)
                    if entity_type == 'chat' and entity_id and key_blob:
                        if entity_id != args.chat_id:
                            share_key_error = (
                                f"Share URL chat ID ({entity_id}) does not match "
                                f"inspected chat ID ({args.chat_id})"
                            )
                        else:
                            chat_key_bytes, share_key_error = decrypt_share_key_blob(
                                entity_id, key_blob,
                                key_field_name='chat_encryption_key',
                                password=args.share_password,
                            )
                    else:
                        share_key_error = (
                            "Could not parse share URL. Expected format: "
                            "https://<domain>/share/chat/<chatId>#key=<blob>"
                        )
                elif args.share_key:
                    chat_key_bytes, share_key_error = decrypt_share_key_blob(
                        args.chat_id, args.share_key,
                        key_field_name='chat_encryption_key',
                        password=args.share_password,
                    )
                
                if chat_key_bytes and not share_key_error:
                    script_logger.info("Share key decrypted successfully, decrypting messages...")
                    decrypted_messages = {}
                    decrypt_ok = 0
                    decrypt_fail = 0
                    
                    for msg in messages:
                        msg_id = str(msg.get('id', ''))
                        encrypted_content = msg.get('encrypted_content')
                        if encrypted_content and msg_id:
                            plaintext, err = decrypt_client_aes_content(
                                encrypted_content, chat_key_bytes
                            )
                            if plaintext:
                                decrypted_messages[msg_id] = plaintext
                                decrypt_ok += 1
                            else:
                                decrypted_messages[msg_id] = f"[DECRYPT ERROR: {err}]"
                                decrypt_fail += 1
                    
                    script_logger.info(
                        f"Decrypted {decrypt_ok} messages "
                        f"({decrypt_fail} failed) out of {len(messages)} total"
                    )
                    
                    # Also decrypt embed content with the chat key
                    if embeds and decoded_embeds is None:
                        decoded_embeds = {}
                    for embed in embeds:
                        embed_id = embed.get('embed_id', '')
                        enc_content = embed.get('encrypted_content')
                        if enc_content and embed_id:
                            plaintext, err = decrypt_client_aes_content(
                                enc_content, chat_key_bytes
                            )
                            if plaintext:
                                try:
                                    from toon_format import decode as toon_decode
                                    decoded = toon_decode(plaintext)
                                    if isinstance(decoded, dict):
                                        decoded_embeds[embed_id] = decoded  # type: ignore[index]
                                        continue
                                except Exception:
                                    pass
                                try:
                                    decoded = json.loads(plaintext)
                                    if isinstance(decoded, dict):
                                        decoded_embeds[embed_id] = decoded  # type: ignore[index]
                                        continue
                                except Exception:
                                    pass
                                decoded_embeds[embed_id] = {'_raw_plaintext': plaintext}  # type: ignore[index]
                            else:
                                script_logger.debug(
                                    f"Could not decrypt embed {embed_id[:8]} with chat key: {err}"
                                )
                elif share_key_error:
                    script_logger.error(f"Share key error: {share_key_error}")
            
            # 9. Format and output results
            if args.json:
                output = format_output_json(
                    args.chat_id, chat_metadata, messages, embeds,
                    embed_keys_by_embed, usage_entries, cache_info,
                    decoded_embeds, encryption_health,
                    decrypted_messages, share_key_error,
                )
            else:
                output = format_output_text(
                    args.chat_id,
                    chat_metadata,
                    messages,
                    embeds,
                    embed_keys_by_embed,
                    usage_entries,
                    cache_info,
                    args.messages_limit,
                    args.embeds_limit,
                    args.usage_limit,
                    decoded_embeds,
                    encryption_health,
                    decrypted_messages,
                    share_key_error,
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
