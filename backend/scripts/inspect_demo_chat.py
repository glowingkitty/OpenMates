#!/usr/bin/env python3
"""
Script to inspect demo chat data including metadata, translations, messages, embeds, and cache status.

This script:
1. Takes a demo ID (demo-1, demo-2, etc.) or UUID as argument
2. Fetches demo chat metadata from Directus
3. Fetches translations for the demo chat
4. Fetches all messages for the demo chat from Directus
5. Fetches all embeds for the demo chat from Directus
6. Checks Redis cache status for the demo chat

Usage:
    docker exec -it api python /app/backend/scripts/inspect_demo_chat.py demo-1
    docker exec -it api python /app/backend/scripts/inspect_demo_chat.py abc12345-6789-0123-4567-890123456789

Options:
    --lang LANG         Language to inspect (default: en)
    --messages-limit N  Limit number of messages to display (default: 20)
    --embeds-limit N    Limit number of embeds to display (default: 20)
    --json              Output as JSON instead of formatted text
    --no-cache          Skip cache checks (faster if Redis is down)
"""

import asyncio
import argparse
import logging
import sys
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

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
script_logger = logging.getLogger('inspect_demo_chat')
script_logger.setLevel(logging.INFO)

# Suppress verbose logging from httpx and other libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)


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


async def get_demo_chat_metadata(directus_service: DirectusService, demo_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch demo chat metadata from Directus.

    Args:
        directus_service: DirectusService instance
        demo_id: The demo ID (demo-1, demo-2, etc.) or UUID

    Returns:
        Demo chat metadata dictionary or None if not found
    """
    script_logger.debug(f"Fetching demo chat metadata for demo_id: {demo_id}")

    # Check if it's a UUID or display ID
    if demo_id.startswith("demo-"):
        # It's a display ID - need to fetch all published demos and find by index
        try:
            index = int(demo_id.split("-")[1]) - 1  # demo-1 -> index 0

            # Get published demos sorted by creation (same as list endpoint)
            params = {
                "filter": {
                    "status": {"_eq": "published"},
                    "is_active": {"_eq": True}
                },
                "sort": ["-created_at"],
                "fields": "*",  # Get all fields
                "limit": 100  # Get enough to cover all demos
            }

            response = await directus_service.get_items('demo_chats', params=params, no_cache=True)
            if response and isinstance(response, list) and len(response) > index:
                demo_metadata = response[index]
                script_logger.debug(f"Mapped display ID {demo_id} to UUID {demo_metadata.get('id')}")
                return demo_metadata
            else:
                script_logger.warning(f"No demo chat found at index {index} for display ID {demo_id}")
                return None
        except (ValueError, IndexError) as e:
            script_logger.error(f"Invalid demo ID format {demo_id}: {e}")
            return None
    else:
        # Assume it's a UUID
        params = {
            'filter[id][_eq]': demo_id,
            'fields': '*',  # Get all fields
            'limit': 1
        }

        try:
            response = await directus_service.get_items('demo_chats', params=params, no_cache=True)
            if response and isinstance(response, list) and len(response) > 0:
                return response[0]
            else:
                script_logger.warning(f"Demo chat not found in Directus: {demo_id}")
                return None
        except Exception as e:
            script_logger.error(f"Error fetching demo chat metadata: {e}")
            return None


async def get_demo_chat_translations(directus_service: DirectusService, demo_chat_uuid: str) -> List[Dict[str, Any]]:
    """
    Fetch all translations for a demo chat from Directus.

    Args:
        directus_service: DirectusService instance
        demo_chat_uuid: The demo chat UUID

    Returns:
        List of translation dictionaries
    """
    script_logger.debug(f"Fetching translations for demo_chat_uuid: {demo_chat_uuid}")

    params = {
        'filter[demo_chat_id][_eq]': demo_chat_uuid,
        'fields': '*',  # Get all fields
        'sort': 'language'  # Sort by language
    }

    try:
        response = await directus_service.get_items('demo_chat_translations', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching translations: {e}")
        return []


async def get_demo_messages(directus_service: DirectusService, demo_chat_uuid: str, language: str = "en", limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch messages for a demo chat from Directus, filtered by language.

    Args:
        directus_service: DirectusService instance
        demo_chat_uuid: The demo chat UUID
        language: Language code to filter by (e.g., 'en', 'de')
        limit: Maximum number of messages to fetch

    Returns:
        List of message dictionaries, sorted by original_created_at ascending
    """
    script_logger.debug(f"Fetching messages for demo_chat_uuid: {demo_chat_uuid}, language: {language}")

    params = {
        'filter': {
            'demo_chat_id': {'_eq': demo_chat_uuid},
            'language': {'_eq': language}
        },
        'fields': '*',  # Get all fields
        'sort': ['original_created_at'],  # Oldest first, by original timestamp
        'limit': limit
    }

    try:
        response = await directus_service.get_items('demo_messages', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching messages: {e}")
        return []


async def get_demo_messages_language_counts(directus_service: DirectusService, demo_chat_uuid: str) -> Dict[str, int]:
    """
    Get message counts per language for a demo chat.

    Args:
        directus_service: DirectusService instance
        demo_chat_uuid: The demo chat UUID

    Returns:
        Dictionary mapping language code to message count
    """
    script_logger.debug(f"Fetching message language counts for demo_chat_uuid: {demo_chat_uuid}")

    params = {
        'filter[demo_chat_id][_eq]': demo_chat_uuid,
        'fields': 'language',
        'limit': -1  # Get all
    }

    try:
        response = await directus_service.get_items('demo_messages', params=params, no_cache=True)
        if response and isinstance(response, list):
            counts: Dict[str, int] = {}
            for msg in response:
                lang = msg.get('language', 'unknown')
                counts[lang] = counts.get(lang, 0) + 1
            return counts
        return {}
    except Exception as e:
        script_logger.error(f"Error fetching message language counts: {e}")
        return {}


async def get_demo_embeds(directus_service: DirectusService, demo_chat_uuid: str, language: str = "en", limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch embeds for a demo chat from Directus.

    NOTE: Unlike messages, embeds are NOT translated - they are stored once with
    language="original". The language parameter is accepted for API consistency
    but is ignored since embeds don't get translated.

    Args:
        directus_service: DirectusService instance
        demo_chat_uuid: The demo chat UUID
        language: Language code (ignored - embeds always use "original")
        limit: Maximum number of embeds to fetch

    Returns:
        List of embed dictionaries, sorted by original_created_at descending
    """
    # Embeds are NOT translated - always fetch with language="original"
    script_logger.debug(f"Fetching embeds for demo_chat_uuid: {demo_chat_uuid} (embeds are not translated, using 'original')")

    params = {
        'filter': {
            'demo_chat_id': {'_eq': demo_chat_uuid},
            'language': {'_eq': 'original'}  # Embeds are stored only once with "original"
        },
        'fields': '*',  # Get all fields
        'sort': ['-original_created_at'],  # Newest first, by original timestamp
        'limit': limit
    }

    try:
        response = await directus_service.get_items('demo_embeds', params=params, no_cache=True)
        if response and isinstance(response, list):
            return response
        return []
    except Exception as e:
        script_logger.error(f"Error fetching embeds: {e}")
        return []


async def get_demo_embeds_language_counts(directus_service: DirectusService, demo_chat_uuid: str) -> Dict[str, int]:
    """
    Get embed counts per language for a demo chat.

    Args:
        directus_service: DirectusService instance
        demo_chat_uuid: The demo chat UUID

    Returns:
        Dictionary mapping language code to embed count
    """
    script_logger.debug(f"Fetching embed language counts for demo_chat_uuid: {demo_chat_uuid}")

    params = {
        'filter[demo_chat_id][_eq]': demo_chat_uuid,
        'fields': 'language',
        'limit': -1  # Get all
    }

    try:
        response = await directus_service.get_items('demo_embeds', params=params, no_cache=True)
        if response and isinstance(response, list):
            counts: Dict[str, int] = {}
            for embed in response:
                lang = embed.get('language', 'unknown')
                counts[lang] = counts.get(lang, 0) + 1
            return counts
        return {}
    except Exception as e:
        script_logger.error(f"Error fetching embed language counts: {e}")
        return {}


async def check_demo_cache_status(cache_service: CacheService, demo_id: str) -> Dict[str, Any]:
    """
    Check Redis cache status for a demo chat.

    Demo chats use different cache keys than regular chats:
    - public:demo_chat:data:{demo_id}:{language}
    - public:demo_chats:list:{language}
    - public:demo_chats:category:{category}:{language}

    Args:
        cache_service: CacheService instance
        demo_id: The demo ID (demo-1, demo-2, etc.) or UUID

    Returns:
        Dictionary with cache status information
    """
    cache_info = {
        'demo_chat_data': {},
        'demo_chats_list': {},
        'raw_keys': {}
    }

    try:
        client = await cache_service.client
        if not client:
            script_logger.warning("Redis client not available for cache checks")
            return cache_info

        # 1. Check demo chat data cache (language-specific)
        # This caches the full demo chat data for viewing
        languages = ['en', 'de', 'fr', 'es', 'it', 'pt', 'ja', 'ko', 'zh']
        for lang in languages:
            demo_data_key = f"public:demo_chat:data:{demo_id}:{lang}"
            demo_data = await client.get(demo_data_key)
            if demo_data:
                try:
                    parsed_data = json.loads(demo_data.decode('utf-8'))
                    cache_info['demo_chat_data'][lang] = {
                        'exists': True,
                        'content_hash': parsed_data.get('content_hash', 'N/A'),
                        'message_count': len(parsed_data.get('chat_data', {}).get('messages', [])),
                        'embed_count': len(parsed_data.get('chat_data', {}).get('embeds', []))
                    }
                except (json.JSONDecodeError, UnicodeDecodeError):
                    cache_info['demo_chat_data'][lang] = {'exists': True, 'parse_error': True}
                cache_info['raw_keys'][f'demo_data_{lang}'] = demo_data_key
            else:
                cache_info['demo_chat_data'][lang] = {'exists': False}

        # 2. Check demo chats list cache (language-specific)
        # This caches the list of all published demo chats
        for lang in languages:
            list_key = f"public:demo_chats:list:{lang}"
            list_data = await client.get(list_key)
            if list_data:
                try:
                    parsed_list = json.loads(list_data.decode('utf-8'))
                    demo_count = parsed_list.get('count', 0)
                    cache_info['demo_chats_list'][lang] = {
                        'exists': True,
                        'demo_count': demo_count
                    }
                except (json.JSONDecodeError, UnicodeDecodeError):
                    cache_info['demo_chats_list'][lang] = {'exists': True, 'parse_error': True}
                cache_info['raw_keys'][f'list_{lang}'] = list_key
            else:
                cache_info['demo_chats_list'][lang] = {'exists': False}

        return cache_info

    except Exception as e:
        script_logger.error(f"Error checking demo cache status: {e}")
        return cache_info


def format_output_text(
    demo_id: str,
    language: str,
    demo_metadata: Optional[Dict[str, Any]],
    translations: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    embeds: List[Dict[str, Any]],
    message_lang_counts: Dict[str, int],
    embed_lang_counts: Dict[str, int],
    cache_info: Dict[str, Any],
    messages_limit: int,
    embeds_limit: int
) -> str:
    """
    Format the inspection results as human-readable text.

    Args:
        demo_id: The demo ID
        language: The language code being inspected
        demo_metadata: Demo chat metadata from Directus
        translations: List of translations from Directus
        messages: List of messages from Directus (filtered by language)
        embeds: List of embeds from Directus (filtered by language)
        message_lang_counts: Message counts per language
        embed_lang_counts: Embed counts per language
        cache_info: Cache status information
        messages_limit: Limit for messages display
        embeds_limit: Limit for embeds display

    Returns:
        Formatted string for display
    """
    lines = []

    # Header
    lines.append("")
    lines.append("=" * 100)
    lines.append("DEMO CHAT INSPECTION REPORT")
    lines.append("=" * 100)
    lines.append(f"Demo ID: {demo_id}")
    lines.append(f"Language: {language.upper()}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)

    # ===================== DEMO METADATA =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("DEMO CHAT METADATA (from Directus)")
    lines.append("-" * 100)

    if not demo_metadata:
        lines.append("❌ Demo chat NOT FOUND in Directus")
    else:
        # Core metadata
        lines.append(f"  UUID:                  {demo_metadata.get('id', 'N/A')}")
        lines.append(f"  Demo ID:               {demo_id}")  # Show the input demo_id, not the db field
        lines.append(f"  Original Chat ID:      {demo_metadata.get('original_chat_id', 'N/A')}")
        lines.append(f"  Status:                {demo_metadata.get('status', 'N/A')}")
        lines.append(f"  Is Active:             {demo_metadata.get('is_active', 'N/A')}")
        lines.append(f"  Created At:            {format_timestamp(demo_metadata.get('created_at'))}")
        lines.append(f"  Updated At:            {format_timestamp(demo_metadata.get('updated_at'))}")
        lines.append("")

        # Admin approval
        approved_by = demo_metadata.get('approved_by_admin')
        approved_at = demo_metadata.get('approved_at')
        if approved_by:
            lines.append(f"  Approved By Admin:     {approved_by}")
            if approved_at:
                lines.append(f"  Approved At:           {format_timestamp(approved_at)}")
        else:
            lines.append("  Approved By Admin:     ❌ NOT APPROVED")
        lines.append("")

        # Encrypted fields (show presence only)
        encrypted_fields = [
            ('encrypted_category', 'Category'),
            ('encrypted_icon', 'Icon'),
        ]

        lines.append("  Encrypted Fields Present:")
        for field_key, field_name in encrypted_fields:
            value = demo_metadata.get(field_key)
            has_value = "✓" if value else "✗"
            size_info = f" ({len(value)} chars)" if value else ""
            lines.append(f"    {has_value} {field_name}{size_info}")
        lines.append("")

        # Content hash
        content_hash = demo_metadata.get('content_hash')
        if content_hash:
            lines.append(f"  Content Hash:          {content_hash}")
        else:
            lines.append("  Content Hash:          ❌ MISSING")

    # ===================== TRANSLATIONS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"TRANSLATIONS (from Directus) - Total: {len(translations)}")
    lines.append("-" * 100)

    if not translations:
        lines.append("  No translations found for this demo chat.")
    else:
        lines.append(f"  Available Languages: {', '.join(t.get('language', 'unknown') for t in translations)}")
        lines.append("")

        for translation in translations:
            lang = translation.get('language', 'unknown')
            lines.append(f"  Language: {lang.upper()}")
            lines.append(f"    Translation ID: {translation.get('id', 'N/A')}")

            # Encrypted fields presence
            encrypted_fields = [
                ('encrypted_title', 'Title'),
                ('encrypted_summary', 'Summary'),
                ('encrypted_follow_up_suggestions', 'Follow-up Suggestions'),
            ]

            lines.append("    Encrypted Fields Present:")
            for field_key, field_name in encrypted_fields:
                value = translation.get(field_key)
                has_value = "✓" if value else "✗"
                size_info = f" ({len(value)} chars)" if value else ""
                lines.append(f"      {has_value} {field_name}{size_info}")
            lines.append("")

    # ===================== MESSAGES =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"MESSAGES (from Directus) - Language: {language.upper()} - Total: {len(messages)}")
    lines.append("-" * 100)

    # Show language breakdown
    if message_lang_counts:
        total_all_langs = sum(message_lang_counts.values())
        langs_sorted = sorted(message_lang_counts.items())
        lines.append(f"  Language Breakdown (total {total_all_langs} across all languages):")
        lang_strs = [f"{lang}: {count}" for lang, count in langs_sorted]
        lines.append(f"    {', '.join(lang_strs)}")
        lines.append("")

    if not messages:
        lines.append(f"  No messages found for language '{language}'.")
    else:
        # Show summary
        roles_count = {}
        for msg in messages:
            role = msg.get('role', 'unknown')
            roles_count[role] = roles_count.get(role, 0) + 1

        lines.append(f"  Role Distribution ({language.upper()}): {roles_count}")
        lines.append("")

        # Show message list (limited)
        display_messages = messages[:messages_limit]
        lines.append(f"  Showing {len(display_messages)} of {len(messages)} messages:")
        lines.append("")

        for i, msg in enumerate(display_messages, 1):
            msg_id = msg.get('id', 'N/A')
            role = msg.get('role', 'unknown')
            original_created_at = format_timestamp(msg.get('original_created_at'))
            has_content = "✓" if msg.get('encrypted_content') else "✗"
            content_len = len(msg.get('encrypted_content', '')) if msg.get('encrypted_content') else 0

            # Role indicator
            role_emoji = {"user": "👤", "assistant": "🤖", "system": "⚙️"}.get(role, "❓")

            lines.append(f"  {i:3}. {role_emoji} [{role:9}] {original_created_at}")
            lines.append(f"       ID: {msg_id}")
            lines.append(f"       Content: {has_content} ({content_len} chars encrypted)")

            # Show additional encrypted fields
            if msg.get('encrypted_category'):
                lines.append("       Category: ✓ (encrypted)")
            if msg.get('encrypted_model_name'):
                lines.append("       Model Name: ✓ (encrypted)")

        if len(messages) > messages_limit:
            lines.append(f"\n  ... and {len(messages) - messages_limit} more message(s)")

    # ===================== EMBEDS =====================
    # NOTE: Embeds are NOT translated - always stored with language="original"
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"EMBEDS (from Directus) - NOT TRANSLATED - Total: {len(embeds)}")
    lines.append("-" * 100)

    # Show language breakdown (for diagnostics - should only have "original" after fix)
    if embed_lang_counts:
        total_all_langs = sum(embed_lang_counts.values())
        original_count = embed_lang_counts.get('original', 0)
        if total_all_langs > original_count:
            # There are duplicate embeds from before the fix
            lines.append(f"  ⚠️  WARNING: Found {total_all_langs} embeds across languages (expected only {original_count} 'original')")
            lines.append("     This indicates duplicate embeds from before the fix was applied.")
            langs_sorted = sorted(embed_lang_counts.items())
            lang_strs = [f"{lang}: {count}" for lang, count in langs_sorted]
            lines.append(f"     Breakdown: {', '.join(lang_strs)}")
        else:
            lines.append(f"  ✅ Embeds stored correctly: {original_count} with language='original'")
        lines.append("")

    if not embeds:
        lines.append("  No embeds found.")
    else:
        # Show summary by type
        type_count = {}
        for embed in embeds:
            embed_type = embed.get('type', 'unknown')
            type_count[embed_type] = type_count.get(embed_type, 0) + 1

        lines.append(f"  Type Distribution: {type_count}")
        lines.append("")

        # Show embed list (limited)
        display_embeds = embeds[:embeds_limit]
        lines.append(f"  Showing {len(display_embeds)} of {len(embeds)} embeds:")
        lines.append("")

        for i, embed in enumerate(display_embeds, 1):
            embed_id = embed.get('id', 'N/A')
            original_embed_id = embed.get('original_embed_id', 'N/A')
            embed_type = embed.get('type', 'unknown')
            original_created_at = format_timestamp(embed.get('original_created_at'))
            has_content = "✓" if embed.get('encrypted_content') else "✗"
            content_len = len(embed.get('encrypted_content', '')) if embed.get('encrypted_content') else 0

            # Type indicator
            type_emoji = {"text": "📄", "image": "🖼️", "code": "💻", "file": "📎"}.get(embed_type, "❓")

            lines.append(f"  {i:3}. {type_emoji} [{embed_type:6}] {original_created_at}")
            lines.append(f"       Directus ID: {embed_id}")
            lines.append(f"       Original Embed ID: {original_embed_id}")
            lines.append(f"       Content: {has_content} ({content_len} chars encrypted)")

        if len(embeds) > embeds_limit:
            lines.append(f"\n  ... and {len(embeds) - embeds_limit} more embed(s)")

    # ===================== CACHE STATUS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("CACHE STATUS (from Redis)")
    lines.append("-" * 100)

    # Demo chat data cache
    lines.append("  Demo Chat Data Cache:")
    demo_data_cache = cache_info.get('demo_chat_data', {})
    for lang, status in demo_data_cache.items():
        if status.get('exists'):
            if status.get('parse_error'):
                lines.append(f"    {lang.upper()}: ❌ EXISTS (parse error)")
            else:
                msg_count = status.get('message_count', 0)
                embed_count = status.get('embed_count', 0)
                content_hash = status.get('content_hash', 'N/A')
                lines.append(f"    {lang.upper()}: ✅ EXISTS ({msg_count} msgs, {embed_count} embeds, hash: {truncate_string(content_hash, 20)}...)")
        else:
            lines.append(f"    {lang.upper()}: ❌ NOT CACHED")

    lines.append("")

    # Demo chats list cache
    lines.append("  Demo Chats List Cache:")
    list_cache = cache_info.get('demo_chats_list', {})
    for lang, status in list_cache.items():
        if status.get('exists'):
            if status.get('parse_error'):
                lines.append(f"    {lang.upper()}: ❌ EXISTS (parse error)")
            else:
                demo_count = status.get('demo_count', 0)
                lines.append(f"    {lang.upper()}: ✅ EXISTS ({demo_count} demos)")
        else:
            lines.append(f"    {lang.upper()}: ❌ NOT CACHED")

    lines.append("")
    lines.append("=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    lines.append("")

    return "\n".join(lines)


def format_output_json(
    demo_id: str,
    language: str,
    demo_metadata: Optional[Dict[str, Any]],
    translations: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    embeds: List[Dict[str, Any]],
    message_lang_counts: Dict[str, int],
    embed_lang_counts: Dict[str, int],
    cache_info: Dict[str, Any]
) -> str:
    """
    Format the inspection results as JSON.

    Args:
        demo_id: The demo ID
        language: The language code being inspected
        demo_metadata: Demo chat metadata from Directus
        translations: List of translations from Directus
        messages: List of messages from Directus (filtered by language)
        embeds: List of embeds from Directus (filtered by language)
        message_lang_counts: Message counts per language
        embed_lang_counts: Embed counts per language
        cache_info: Cache status information

    Returns:
        JSON string
    """
    output = {
        'demo_id': demo_id,
        'language': language,
        'generated_at': datetime.now().isoformat(),
        'demo_metadata': demo_metadata,
        'translations': {
            'count': len(translations),
            'items': translations
        },
        'messages': {
            'language': language,
            'count': len(messages),
            'language_counts': message_lang_counts,
            'items': messages
        },
        'embeds': {
            'language': language,
            'count': len(embeds),
            'language_counts': embed_lang_counts,
            'items': embeds
        },
        'cache': cache_info
    }

    return json.dumps(output, indent=2, default=str)


async def main():
    """Main function that inspects a demo chat."""
    parser = argparse.ArgumentParser(
        description='Inspect demo chat data including metadata, translations, messages, embeds, and cache status'
    )
    parser.add_argument(
        'demo_id',
        type=str,
        help='Demo ID (demo-1, demo-2, etc.) or UUID to inspect'
    )
    parser.add_argument(
        '--lang',
        type=str,
        default='en',
        help='Language to inspect (default: en)'
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
        '--json',
        action='store_true',
        help='Output as JSON instead of formatted text'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Skip cache checks (faster if Redis is unavailable)'
    )

    args = parser.parse_args()

    script_logger.info(f"Inspecting demo chat: {args.demo_id} (language: {args.lang})")

    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )

    try:
        # 1. Fetch demo chat metadata
        demo_metadata = await get_demo_chat_metadata(directus_service, args.demo_id)

        # Get the UUID for subsequent queries
        demo_chat_uuid = None
        if demo_metadata:
            demo_chat_uuid = demo_metadata.get('id')
        elif not args.demo_id.startswith("demo-"):
            # If we didn't find it and input wasn't a display ID, assume it was a UUID
            demo_chat_uuid = args.demo_id

        if not demo_chat_uuid:
            script_logger.error(f"Could not determine UUID for demo chat: {args.demo_id}")
            return

        # 2. Fetch translations
        translations = await get_demo_chat_translations(directus_service, demo_chat_uuid)

        # 3. Fetch messages (filtered by language)
        messages = await get_demo_messages(
            directus_service,
            demo_chat_uuid,
            language=args.lang,
            limit=args.messages_limit + 100 if not args.json else 10000  # Get more for count
        )

        # 4. Fetch embeds (filtered by language)
        embeds = await get_demo_embeds(
            directus_service,
            demo_chat_uuid,
            language=args.lang,
            limit=args.embeds_limit + 100 if not args.json else 10000  # Get more for count
        )

        # 5. Fetch language breakdown counts
        message_lang_counts = await get_demo_messages_language_counts(directus_service, demo_chat_uuid)
        embed_lang_counts = await get_demo_embeds_language_counts(directus_service, demo_chat_uuid)

        # 6. Check cache status (if not skipped)
        cache_info = {}
        if not args.no_cache:
            cache_info = await check_demo_cache_status(cache_service, args.demo_id)

        # 7. Format and output results
        if args.json:
            output = format_output_json(
                args.demo_id,
                args.lang,
                demo_metadata,
                translations,
                messages,
                embeds,
                message_lang_counts,
                embed_lang_counts,
                cache_info
            )
        else:
            output = format_output_text(
                args.demo_id,
                args.lang,
                demo_metadata,
                translations,
                messages,
                embeds,
                message_lang_counts,
                embed_lang_counts,
                cache_info,
                args.messages_limit,
                args.embeds_limit
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