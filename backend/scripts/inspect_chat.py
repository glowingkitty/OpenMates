#!/usr/bin/env python3
"""
Script to inspect chat data including metadata, messages, embeds, and cache status.

This script:
1. Takes a chat ID as argument
2. Fetches chat metadata from Directus
3. Fetches all messages for the chat from Directus
4. Fetches all embeds for the chat from Directus
5. Checks Redis cache status for the chat and its components

Usage:
    docker exec -it api python /app/backend/scripts/inspect_chat.py <chat_id>
    docker exec -it api python /app/backend/scripts/inspect_chat.py abc12345-6789-0123-4567-890123456789

Options:
    --messages-limit N  Limit number of messages to display (default: 20)
    --embeds-limit N    Limit number of embeds to display (default: 20)
    --json              Output as JSON instead of formatted text
    --no-cache          Skip cache checks (faster if Redis is down)
"""

import asyncio
import argparse
import hashlib
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
script_logger = logging.getLogger('inspect_chat')
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


async def check_cache_status(cache_service: CacheService, chat_id: str, hashed_user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Check Redis cache status for a chat and its components.
    
    Args:
        cache_service: CacheService instance
        chat_id: The chat ID
        hashed_user_id: Optional hashed user ID (if known from chat metadata)
        
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
        'raw_keys': {}
    }
    
    try:
        client = await cache_service.client
        if not client:
            script_logger.warning("Redis client not available for cache checks")
            return cache_info
        
        # 1. Check chat versions (requires hashed_user_id)
        if hashed_user_id:
            # Check chat versions hash
            versions_key = f"user:{hashed_user_id}:chat:{chat_id}:versions"
            versions_data = await client.hgetall(versions_key)
            if versions_data:
                cache_info['chat_versions'] = {
                    k.decode('utf-8'): v.decode('utf-8') for k, v in versions_data.items()
                }
                cache_info['raw_keys']['versions'] = versions_key
            
            # Check list item data hash
            list_item_key = f"user:{hashed_user_id}:chat:{chat_id}:list_item_data"
            list_item_data = await client.hgetall(list_item_key)
            if list_item_data:
                cache_info['list_item_data'] = {
                    k.decode('utf-8'): truncate_string(v.decode('utf-8'), 100) for k, v in list_item_data.items()
                }
                cache_info['raw_keys']['list_item_data'] = list_item_key
            
            # Check AI messages cache (vault-encrypted, for AI inference)
            ai_messages_key = f"user:{hashed_user_id}:chat:{chat_id}:messages:ai"
            ai_messages_count = await client.llen(ai_messages_key)
            if ai_messages_count > 0:
                cache_info['ai_messages_count'] = ai_messages_count
                cache_info['raw_keys']['ai_messages'] = ai_messages_key
            
            # Check sync messages cache (client-encrypted, for sync)
            sync_messages_key = f"user:{hashed_user_id}:chat:{chat_id}:messages:sync"
            sync_messages_count = await client.llen(sync_messages_key)
            if sync_messages_count > 0:
                cache_info['sync_messages_count'] = sync_messages_count
                cache_info['raw_keys']['sync_messages'] = sync_messages_key
            
            # Check draft cache
            draft_key = f"user:{hashed_user_id}:chat:{chat_id}:draft"
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
    cache_info: Dict[str, Any],
    messages_limit: int,
    embeds_limit: int
) -> str:
    """
    Format the inspection results as human-readable text.
    
    Args:
        chat_id: The chat ID
        chat_metadata: Chat metadata from Directus
        messages: List of messages from Directus
        embeds: List of embeds from Directus
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
    lines.append("CHAT INSPECTION REPORT")
    lines.append("=" * 100)
    lines.append(f"Chat ID: {chat_id}")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)
    
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
            
            # Show if model name is present (for assistant messages)
            if msg.get('encrypted_model_name'):
                lines.append("       Model: ✓ (encrypted)")
        
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
        
        if len(embeds) > embeds_limit:
            lines.append(f"\n  ... and {len(embeds) - embeds_limit} more embed(s)")
    
    # ===================== CACHE STATUS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append("CACHE STATUS (from Redis)")
    lines.append("-" * 100)
    
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
    cache_info: Dict[str, Any]
) -> str:
    """
    Format the inspection results as JSON.
    
    Args:
        chat_id: The chat ID
        chat_metadata: Chat metadata from Directus
        messages: List of messages from Directus
        embeds: List of embeds from Directus
        cache_info: Cache status information
        
    Returns:
        JSON string
    """
    output = {
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
        'cache': cache_info
    }
    
    return json.dumps(output, indent=2, default=str)


async def main():
    """Main function that inspects a chat."""
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
    
    script_logger.info(f"Inspecting chat: {args.chat_id}")
    
    # Initialize services
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
            limit=args.messages_limit + 100 if not args.json else 10000  # Get more for count
        )
        
        # 3. Fetch embeds
        embeds = await get_chat_embeds(
            directus_service, 
            args.chat_id,
            limit=args.embeds_limit + 100 if not args.json else 10000  # Get more for count
        )
        
        # 4. Check cache status (if not skipped)
        cache_info = {}
        if not args.no_cache:
            hashed_user_id = chat_metadata.get('hashed_user_id') if chat_metadata else None
            cache_info = await check_cache_status(cache_service, args.chat_id, hashed_user_id)
        
        # 5. Format and output results
        if args.json:
            output = format_output_json(args.chat_id, chat_metadata, messages, embeds, cache_info)
        else:
            output = format_output_text(
                args.chat_id,
                chat_metadata,
                messages,
                embeds,
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

