#!/usr/bin/env python3
"""
Script to test the new get_completed_signups_count() function.

This script compares:
- Total registered users (all accounts created)
- Completed signups (users who finished payment/signup flow)

Usage:
    docker exec -it api python /app/backend/scripts/test_completed_signups_count.py
"""

import asyncio
import logging
import sys
from datetime import datetime

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


async def get_total_users(directus_service: DirectusService) -> int:
    """Get total count of all registered users."""
    try:
        return await directus_service.get_total_users_count()
    except Exception as e:
        logger.error(f"Error getting total users count: {e}")
        return 0


async def get_completed_signups(directus_service: DirectusService) -> int:
    """Get count of users who completed signup and payment."""
    try:
        return await directus_service.get_completed_signups_count()
    except Exception as e:
        logger.error(f"Error getting completed signups count: {e}")
        return 0


def format_results(total_users: int, completed_signups: int) -> str:
    """Format the results for display."""
    lines = []
    lines.append(f"\n{'='*80}")
    lines.append(f"USER SIGNUP COUNT COMPARISON")
    lines.append(f"{'='*80}")
    lines.append(f"")
    lines.append(f"Total Registered Users:      {total_users:,}")
    lines.append(f"Completed Signups:            {completed_signups:,}")
    lines.append(f"")
    
    if total_users > 0:
        abandoned = total_users - completed_signups
        completion_rate = (completed_signups / total_users) * 100
        lines.append(f"Abandoned Signups:            {abandoned:,}")
        lines.append(f"Completion Rate:                {completion_rate:.1f}%")
        lines.append(f"")
    
    lines.append(f"{'='*80}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"{'='*80}")
    
    return "\n".join(lines)


async def main():
    """Main function that fetches and displays user counts."""
    logger.info("Starting completed signups count test...")
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    
    try:
        logger.info("Fetching user counts...")
        
        # Fetch both counts
        total_users = await get_total_users(directus_service)
        completed_signups = await get_completed_signups(directus_service)
        
        # Display results
        display = format_results(total_users, completed_signups)
        print(display)
        
        logger.info("Test complete.")
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise
    finally:
        # Clean up - close the DirectusService httpx client
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())

