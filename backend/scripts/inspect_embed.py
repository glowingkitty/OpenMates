#!/usr/bin/env python3
"""
Script to inspect a specific embed from Directus.

This script:
1. Takes an embed_id as argument
2. Fetches the embed data from Directus
3. Fetches all embed_keys for the embed
4. Fetches child embeds (if any)

Usage:
    docker exec -it api python /app/backend/scripts/inspect_embed.py <embed_id>
    docker exec -it api python /app/backend/scripts/inspect_embed.py abc12345-6789-0123-4567-890123456789

Options:
    --json              Output as JSON instead of formatted text
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
script_logger = logging.getLogger('inspect_embed')
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


def format_output_text(
    embed_id: str,
    embed: Optional[Dict[str, Any]],
    embed_keys: List[Dict[str, Any]],
    child_embeds: List[Dict[str, Any]]
) -> str:
    """
    Format the embed inspection as human-readable text.
    
    Args:
        embed_id: The embed ID
        embed: Embed data from Directus
        embed_keys: List of embed_keys for this embed
        child_embeds: List of child embeds (if any)
        
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
            lines.append(f"  Child Embed IDs:             None")
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
        encrypted_type = embed.get('encrypted_type')
        encrypted_preview = embed.get('encrypted_text_preview')
        
        lines.append("  Encrypted Fields:")
        lines.append(f"    ✓ encrypted_content:       {len(encrypted_content) if encrypted_content else 0} chars")
        if encrypted_content:
            lines.append(f"      Preview: {truncate_string(encrypted_content, 80)}")
        lines.append(f"    ✓ encrypted_type:          {len(encrypted_type) if encrypted_type else 0} chars")
        if encrypted_type:
            lines.append(f"      Value: {encrypted_type}")
        lines.append(f"    ✓ encrypted_text_preview:  {len(encrypted_preview) if encrypted_preview else 0} chars")
        if encrypted_preview:
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
    
    # ===================== EMBED KEYS =====================
    lines.append("")
    lines.append("-" * 100)
    lines.append(f"EMBED KEYS (from Directus) - Total: {len(embed_keys)}")
    lines.append("-" * 100)
    
    if not embed_keys:
        lines.append("  No embed keys found for this embed.")
    else:
        for i, key in enumerate(embed_keys, 1):
            key_type = key.get('key_type', 'unknown')
            hashed_chat_id = key.get('hashed_chat_id')
            created_at = format_timestamp(key.get('created_at'))
            encrypted_key = key.get('encrypted_embed_key', '')
            
            type_emoji = {"master": "🔑", "chat": "💬"}.get(key_type, "❓")
            
            lines.append(f"  {i}. {type_emoji} [{key_type:6}] Created: {created_at}")
            lines.append(f"     Hashed Embed ID: {truncate_string(key.get('hashed_embed_id', 'N/A'), 20)}...")
            if hashed_chat_id:
                lines.append(f"     Hashed Chat ID:  {truncate_string(hashed_chat_id, 20)}...")
            lines.append(f"     Hashed User ID:  {truncate_string(key.get('hashed_user_id', 'N/A'), 20)}...")
            lines.append(f"     Encrypted Key:   [{len(encrypted_key)} chars]")
    
    # ===================== CHILD EMBEDS =====================
    if child_embeds:
        lines.append("")
        lines.append("-" * 100)
        lines.append(f"CHILD EMBEDS (from Directus) - Total: {len(child_embeds)}")
        lines.append("-" * 100)
        
        for i, child in enumerate(child_embeds, 1):
            status = child.get('status', 'unknown')
            created_at = format_timestamp(child.get('created_at'))
            encrypted_content = child.get('encrypted_content')
            encrypted_type = child.get('encrypted_type')
            
            status_emoji = {"processing": "⏳", "finished": "✅", "error": "❌"}.get(status, "❓")
            
            lines.append(f"  {i}. {status_emoji} [{status:10}] {created_at}")
            lines.append(f"     Embed ID: {child.get('embed_id', 'N/A')}")
            lines.append(f"     Type: [{len(encrypted_type) if encrypted_type else 0} chars]  Content: [{len(encrypted_content) if encrypted_content else 0} chars]")
    
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
    child_embeds: List[Dict[str, Any]]
) -> str:
    """
    Format the embed inspection as JSON.
    
    Args:
        embed_id: The embed ID
        embed: Embed data from Directus
        embed_keys: List of embed_keys for this embed
        child_embeds: List of child embeds (if any)
        
    Returns:
        JSON string
    """
    output = {
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
        
        # 4. Format and output results
        if args.json:
            output = format_output_json(args.embed_id, embed, embed_keys, child_embeds)
        else:
            output = format_output_text(args.embed_id, embed, embed_keys, child_embeds)
        
        print(output)
        
    except Exception as e:
        script_logger.error(f"Error during inspection: {e}", exc_info=True)
        raise
    finally:
        # Clean up
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())

