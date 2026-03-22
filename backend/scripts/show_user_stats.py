#!/usr/bin/env python3
"""
Script to display user statistics and database health information.

This script shows:
- Total user count
- Recent signups (last 24 hours, 7 days, 30 days)
- Admin user count
- Active users (last 24 hours, 7 days, 30 days)

Usage:
    docker exec -it api python /app/backend/scripts/show_user_stats.py
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta

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


async def get_user_count(directus_service: DirectusService) -> int:
    """Get total user count."""
    try:
        return await directus_service.get_total_users_count()
    except Exception as e:
        logger.error(f"Error getting user count: {e}")
        return 0


async def get_admin_count(directus_service: DirectusService) -> int:
    """Get count of admin users."""
    try:
        await directus_service.ensure_auth_token(admin_required=True)
        if not directus_service.admin_token:
            return 0
        
        url = f"{directus_service.base_url}/users"
        params = {
            'filter[is_admin][_eq]': 'true',
            'limit': 1,
            'meta': 'filter_count'
        }
        
        response = await directus_service._make_api_request("GET", url, params=params)
        if response.status_code == 200:
            data = response.json()
            meta = data.get("meta", {})
            return int(meta.get("filter_count", 0))
        return 0
    except Exception as e:
        logger.error(f"Error getting admin count: {e}")
        return 0


async def get_recent_signups(directus_service: DirectusService, days: int) -> int:
    """Get count of users created in the last N days."""
    try:
        await directus_service.ensure_auth_token(admin_required=True)
        if not directus_service.admin_token:
            return 0
        
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        url = f"{directus_service.base_url}/users"
        params = {
            'filter[date_created][_gte]': cutoff_date,  # Directus uses 'date_created' for user creation
            'limit': 1,
            'meta': 'filter_count'
        }
        
        response = await directus_service._make_api_request("GET", url, params=params)
        if response.status_code == 200:
            data = response.json()
            meta = data.get("meta", {})
            return int(meta.get("filter_count", 0))
        return 0
    except Exception as e:
        logger.error(f"Error getting recent signups: {e}")
        return 0


async def get_active_users(directus_service: DirectusService, days: int) -> int:
    """Get count of users active in the last N days."""
    try:
        cutoff_timestamp = int((datetime.now() - timedelta(days=days)).timestamp())
        return await directus_service.get_active_users_since(cutoff_timestamp)
    except Exception as e:
        logger.error(f"Error getting active users: {e}")
        return 0


def format_stats_display(stats: dict) -> str:
    """Format statistics for display."""
    lines = []
    lines.append(f"\n{'='*80}")
    lines.append(f"USER STATISTICS")
    lines.append(f"{'='*80}")
    lines.append(f"")
    lines.append(f"Total Users:           {stats['total_users']:,}")
    lines.append(f"Admin Users:           {stats['admin_count']:,}")
    lines.append(f"Regular Users:         {stats['total_users'] - stats['admin_count']:,}")
    lines.append(f"")
    lines.append(f"{'='*80}")
    lines.append(f"RECENT SIGNUPS")
    lines.append(f"{'='*80}")
    lines.append(f"Last 24 hours:         {stats['signups_24h']:,}")
    lines.append(f"Last 7 days:           {stats['signups_7d']:,}")
    lines.append(f"Last 30 days:          {stats['signups_30d']:,}")
    lines.append(f"")
    lines.append(f"{'='*80}")
    lines.append(f"ACTIVE USERS")
    lines.append(f"{'='*80}")
    lines.append(f"Last 24 hours:         {stats['active_24h']:,}")
    lines.append(f"Last 7 days:           {stats['active_7d']:,}")
    lines.append(f"Last 30 days:          {stats['active_30d']:,}")
    lines.append(f"")
    lines.append(f"{'='*80}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"{'='*80}")
    
    return "\n".join(lines)


async def main():
    """Main function that fetches and displays user statistics."""
    logger.info("Starting user statistics script...")
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    
    try:
        logger.info("Fetching user statistics...")
        
        # Fetch all statistics
        total_users = await get_user_count(directus_service)
        admin_count = await get_admin_count(directus_service)
        signups_24h = await get_recent_signups(directus_service, 1)
        signups_7d = await get_recent_signups(directus_service, 7)
        signups_30d = await get_recent_signups(directus_service, 30)
        active_24h = await get_active_users(directus_service, 1)
        active_7d = await get_active_users(directus_service, 7)
        active_30d = await get_active_users(directus_service, 30)
        
        stats = {
            'total_users': total_users,
            'admin_count': admin_count,
            'signups_24h': signups_24h,
            'signups_7d': signups_7d,
            'signups_30d': signups_30d,
            'active_24h': active_24h,
            'active_7d': active_7d,
            'active_30d': active_30d
        }
        
        # Display statistics
        display = format_stats_display(stats)
        print(display)
        
        logger.info("Statistics display complete.")
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise
    finally:
        # Clean up - close the DirectusService httpx client
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())

