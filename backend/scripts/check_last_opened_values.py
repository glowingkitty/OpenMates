#!/usr/bin/env python3
"""
Script to check the last_opened values for all users.

This helps verify the completed signups count filter is working correctly.

Usage:
    docker exec api python /app/backend/scripts/check_last_opened_values.py
"""

import asyncio
import logging
import sys
from collections import Counter

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Reduce log noise
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_all_users_last_opened(directus_service: DirectusService):
    """Get last_opened values for all users."""
    try:
        await directus_service.ensure_auth_token(admin_required=True)
        if not directus_service.admin_token:
            logger.error("Failed to get admin token")
            return []
        
        all_users = []
        limit = 100
        offset = 0
        
        while True:
            url = f"{directus_service.base_url}/users"
            params = {
                'fields': 'id,last_opened,is_admin',
                'limit': limit,
                'offset': offset
            }
            
            response = await directus_service._make_api_request("GET", url, params=params)
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch users: {response.status_code}")
                break
            
            data = response.json()
            users_batch = data.get("data", [])
            
            if not users_batch:
                break
            
            all_users.extend(users_batch)
            
            if len(users_batch) < limit:
                break
            
            offset += limit
        
        return all_users
    except Exception as e:
        logger.error(f"Error getting users: {e}", exc_info=True)
        return []


async def main():
    """Main function."""
    logger.info("Starting last_opened check...")
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    
    try:
        users = await get_all_users_last_opened(directus_service)
        
        print(f"\n{'='*80}")
        print(f"LAST_OPENED VALUES FOR ALL USERS")
        print(f"{'='*80}\n")
        
        # Count by last_opened value
        last_opened_counts = Counter()
        admin_count = 0
        regular_users = []
        
        for user in users:
            is_admin = user.get('is_admin', False)
            last_opened = user.get('last_opened')
            
            if is_admin:
                admin_count += 1
                continue
            
            last_opened_str = last_opened if last_opened else '(null)'
            last_opened_counts[last_opened_str] += 1
            regular_users.append({
                'id': user.get('id', '')[:8] + '...',
                'last_opened': last_opened_str
            })
        
        print(f"Total Users: {len(users)}")
        print(f"Admin Users: {admin_count}")
        print(f"Regular Users: {len(regular_users)}\n")
        print(f"{'='*80}")
        print(f"LAST_OPENED VALUE DISTRIBUTION")
        print(f"{'='*80}\n")
        
        for value, count in last_opened_counts.most_common():
            print(f"  {value:50} : {count:3} users")
        
        print(f"\n{'='*80}")
        print(f"COMPLETED SIGNUPS BREAKDOWN")
        print(f"{'='*80}\n")
        
        completed = sum(count for value, count in last_opened_counts.items() 
                       if value != '(null)' and value.startswith('/chat/'))
        in_signup = sum(count for value, count in last_opened_counts.items() 
                       if value != '(null)' and value.startswith('/signup/'))
        null_count = last_opened_counts.get('(null)', 0)
        other = len(regular_users) - completed - in_signup - null_count
        
        print(f"  Completed (starts with /chat/): {completed:3} users")
        print(f"  In Signup (starts with /signup/): {in_signup:3} users")
        print(f"  Null/Empty: {null_count:3} users")
        print(f"  Other values: {other:3} users")
        print(f"\n  Total Regular Users: {len(regular_users)}")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise
    finally:
        await directus_service.close()


if __name__ == "__main__":
    asyncio.run(main())

