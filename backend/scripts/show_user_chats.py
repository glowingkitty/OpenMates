#!/usr/bin/env python3
"""
Script to display chat information for a specific user.

This script:
1. Takes a user ID as argument
2. Hashes the user ID and queries for their chats
3. Displays chat count and basic chat information

Usage:
    docker exec -it api python /app/backend/scripts/show_user_chats.py <user_id>
    docker exec -it api python /app/backend/scripts/show_user_chats.py abc12345-6789-0123-4567-890123456789
"""

import asyncio
import argparse
import hashlib
import logging
import sys
from datetime import datetime
from typing import Dict, Any, List

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_user_chats(directus_service: DirectusService, user_id: str) -> List[Dict[str, Any]]:
    """
    Get all chats for a user by hashing their user_id and querying the chats collection.
    
    Args:
        directus_service: The DirectusService instance
        user_id: The user's ID
        
    Returns:
        List of chat dictionaries
    """
    try:
        # Hash the user_id using SHA-256 (same method used throughout the codebase)
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        logger.info(f"Querying chats for user {user_id[:8]}... (hashed: {hashed_user_id[:16]}...)")
        
        # Query chats collection for this hashed_user_id
        params = {
            'filter[hashed_user_id][_eq]': hashed_user_id,
            'fields': 'id,created_at,updated_at,last_message_timestamp,unread_count',
            'sort': '-updated_at',  # Most recently updated first
            'limit': 1000  # Get up to 1000 chats
        }
        
        chats = await directus_service.get_items('chats', params=params, no_cache=True)
        
        logger.info(f"Found {len(chats)} chat(s) for user {user_id[:8]}...")
        return chats
        
    except Exception as e:
        logger.error(f"Error getting chats for user {user_id}: {e}", exc_info=True)
        return []


def format_chats_display(user_id: str, chats: List[Dict[str, Any]]) -> str:
    """
    Format chat information for display.
    
    Args:
        user_id: The user's ID
        chats: List of chat dictionaries
        
    Returns:
        Formatted string for display
    """
    lines = []
    lines.append(f"\n{'='*80}")
    lines.append(f"CHAT INFORMATION FOR USER")
    lines.append(f"{'='*80}")
    lines.append(f"User ID: {user_id}")
    lines.append(f"Total Chats: {len(chats)}")
    lines.append(f"{'='*80}")
    
    if not chats:
        lines.append(f"\nNo chats found for this user.")
        lines.append(f"{'='*80}")
        return "\n".join(lines)
    
    # Show summary statistics
    total_unread = sum(chat.get('unread_count', 0) for chat in chats)
    lines.append(f"Total Unread Messages: {total_unread}")
    lines.append(f"")
    
    # Show recent chats (last 10)
    lines.append(f"Recent Chats (showing up to 10 most recent):")
    lines.append(f"")
    
    for i, chat in enumerate(chats[:10], 1):
        chat_id = chat.get('id', 'unknown')
        created_at = chat.get('created_at')
        updated_at = chat.get('updated_at')
        last_message = chat.get('last_message_timestamp')
        unread = chat.get('unread_count', 0)
        
        # Format timestamps
        def format_timestamp(ts):
            if not ts:
                return "N/A"
            try:
                if isinstance(ts, int):
                    dt = datetime.fromtimestamp(ts)
                else:
                    dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                return str(ts)
        
        lines.append(f"  {i}. Chat ID: {chat_id[:8]}...{chat_id[-4:]}")
        lines.append(f"     Created:    {format_timestamp(created_at)}")
        lines.append(f"     Updated:    {format_timestamp(updated_at)}")
        lines.append(f"     Last Msg:   {format_timestamp(last_message)}")
        lines.append(f"     Unread:     {unread}")
        lines.append(f"")
    
    if len(chats) > 10:
        lines.append(f"  ... and {len(chats) - 10} more chat(s)")
        lines.append(f"")
    
    lines.append(f"{'='*80}")
    
    return "\n".join(lines)


async def main():
    """Main function that displays chat information for a user."""
    parser = argparse.ArgumentParser(description='Display chat information for a specific user')
    parser.add_argument(
        'user_id',
        type=str,
        help='User ID to query chats for'
    )
    args = parser.parse_args()
    
    logger.info("Starting user chats display script...")
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    
    try:
        # Get user chats
        chats = await get_user_chats(directus_service, args.user_id)
        
        # Display chat information
        display = format_chats_display(args.user_id, chats)
        print(display)
        
        logger.info("Display complete.")
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise
    finally:
        # Clean up - close the DirectusService httpx client
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())

