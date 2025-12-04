#!/usr/bin/env python3
"""
Script to delete users who do not have any chats created.

This script:
1. Fetches all users from Directus
2. For each user, hashes their user_id and checks if they have any chats
3. Collects users without chats
4. Asks for user confirmation before deletion
5. Deletes the identified users

The script must be run inside the Docker container (api service) to have access
to the necessary environment variables and services.

Usage:
    docker exec -it api python /app/backend/scripts/delete_users_without_chats.py
"""

import asyncio
import hashlib
import logging
import os
import sys
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


async def get_all_users(directus_service: DirectusService) -> List[Dict[str, Any]]:
    """
    Fetch all users from Directus using the /users endpoint.
    
    Returns a list of user dictionaries, each containing at least an 'id' field.
    """
    logger.info("Fetching all users from Directus...")
    
    # Ensure we have admin token for accessing users
    await directus_service.ensure_auth_token(admin_required=True)
    if not directus_service.admin_token:
        logger.error("Failed to get admin token for fetching users")
        return []
    
    all_users = []
    limit = 100  # Fetch in batches
    offset = 0
    
    while True:
        # Query users using the /users endpoint directly
        url = f"{directus_service.base_url}/users"
        params = {
            'fields': 'id,is_admin',
            'limit': limit,
            'offset': offset
        }
        
        try:
            # Use _make_api_request which will use admin token
            response = await directus_service._make_api_request("GET", url, params=params)
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch users: {response.status_code} - {response.text}")
                break
            
            data = response.json()
            users_batch = data.get("data", [])
            
            if not users_batch or len(users_batch) == 0:
                break
            
            all_users.extend(users_batch)
            logger.info(f"Fetched {len(users_batch)} users (total so far: {len(all_users)})")
            
            # If we got fewer than the limit, we've reached the end
            if len(users_batch) < limit:
                break
            
            offset += limit
            
        except Exception as e:
            logger.error(f"Error fetching users batch at offset {offset}: {e}", exc_info=True)
            break
    
    logger.info(f"Total users fetched: {len(all_users)}")
    return all_users


async def user_has_chats(directus_service: DirectusService, user_id: str) -> bool:
    """
    Check if a user has any chats by querying the chats collection with hashed_user_id.
    
    Args:
        directus_service: The DirectusService instance
        user_id: The user's ID to check
        
    Returns:
        True if the user has at least one chat, False otherwise
    """
    try:
        # Hash the user_id using SHA-256 (same method used throughout the codebase)
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Query chats collection for this hashed_user_id
        params = {
            'filter[hashed_user_id][_eq]': hashed_user_id,
            'fields': 'id',  # We only need to know if any exist
            'limit': 1  # We only need to check existence
        }
        
        chats = await directus_service.get_items('chats', params=params, no_cache=True)
        
        has_chats = len(chats) > 0
        return has_chats
        
    except Exception as e:
        logger.error(f"Error checking chats for user {user_id}: {e}", exc_info=True)
        # If we can't check, assume they have chats to be safe (don't delete)
        return True


async def find_users_without_chats(directus_service: DirectusService) -> List[Dict[str, Any]]:
    """
    Find all users who do not have any chats.
    
    Returns a list of user dictionaries for users without chats.
    """
    logger.info("Finding users without chats...")
    
    all_users = await get_all_users(directus_service)
    users_without_chats = []
    
    total_users = len(all_users)
    processed = 0
    
    for user in all_users:
        user_id = user.get('id')
        is_admin = user.get('is_admin', False)
        
        if not user_id:
            logger.warning(f"Skipping user with no ID: {user}")
            continue
        
        # Skip admin users - we don't want to delete admins
        if is_admin:
            logger.debug(f"Skipping admin user: {user_id[:8]}...")
            processed += 1
            continue
        
        processed += 1
        logger.info(f"Checking user {user_id[:8]}... ({processed}/{total_users})")
        
        # Check if user has any chats
        has_chats = await user_has_chats(directus_service, user_id)
        
        if not has_chats:
            logger.info(f"User {user_id[:8]}... has no chats - marked for deletion")
            users_without_chats.append(user)
        else:
            logger.debug(f"User {user_id[:8]}... has chats - keeping")
    
    logger.info(f"Found {len(users_without_chats)} users without chats out of {total_users} total users")
    return users_without_chats


async def delete_users(directus_service: DirectusService, users: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Delete a list of users using the DirectusService delete_user method.
    
    Args:
        directus_service: The DirectusService instance
        users: List of user dictionaries to delete
        
    Returns:
        Dictionary with 'success' and 'failed' counts
    """
    results = {'success': 0, 'failed': 0}
    
    for user in users:
        user_id = user.get('id')
        if not user_id:
            logger.warning(f"Skipping user with no ID: {user}")
            results['failed'] += 1
            continue
        
        try:
            logger.info(f"Deleting user {user_id[:8]}...")
            
            # Use the delete_user method from DirectusService
            success = await directus_service.delete_user(
                user_id=user_id,
                deletion_type="admin_action",
                reason="User has no chats - cleanup script",
                details={"script": "delete_users_without_chats.py"}
            )
            
            if success:
                logger.info(f"Successfully deleted user {user_id[:8]}...")
                results['success'] += 1
            else:
                logger.error(f"Failed to delete user {user_id[:8]}...")
                results['failed'] += 1
                
        except Exception as e:
            logger.error(f"Exception while deleting user {user_id[:8]}...: {e}", exc_info=True)
            results['failed'] += 1
    
    return results


def confirm_deletion(users: List[Dict[str, Any]]) -> bool:
    """
    Ask the user for confirmation before deleting users.
    
    Args:
        users: List of users to be deleted
        
    Returns:
        True if user confirms, False otherwise
    """
    print("\n" + "="*80)
    print(f"WARNING: About to delete {len(users)} users who have no chats.")
    print("="*80)
    print("\nUsers to be deleted:")
    
    # Show first 10 user IDs (truncated for privacy)
    for i, user in enumerate(users[:10], 1):
        user_id = user.get('id', 'unknown')
        print(f"  {i}. {user_id[:8]}...{user_id[-4:]}")
    
    if len(users) > 10:
        print(f"  ... and {len(users) - 10} more users")
    
    print("\n" + "="*80)
    print("This action CANNOT be undone!")
    print("="*80)
    
    while True:
        response = input("\nDo you want to proceed with deletion? (yes/no): ").strip().lower()
        if response in ['yes', 'y']:
            return True
        elif response in ['no', 'n']:
            return False
        else:
            print("Please enter 'yes' or 'no'")


async def main():
    """
    Main function that orchestrates the user deletion process.
    """
    logger.info("Starting user deletion script...")
    
    # Initialize services
    # Note: These services need environment variables from .env file
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    
    try:
        # Find users without chats
        users_without_chats = await find_users_without_chats(directus_service)
        
        if len(users_without_chats) == 0:
            logger.info("No users found without chats. Nothing to delete.")
            return
        
        # Ask for confirmation
        if not confirm_deletion(users_without_chats):
            logger.info("Deletion cancelled by user.")
            return
        
        # Delete the users
        logger.info(f"Proceeding with deletion of {len(users_without_chats)} users...")
        results = await delete_users(directus_service, users_without_chats)
        
        # Print summary
        print("\n" + "="*80)
        print("DELETION SUMMARY")
        print("="*80)
        print(f"Successfully deleted: {results['success']} users")
        print(f"Failed to delete: {results['failed']} users")
        print("="*80)
        
        logger.info(f"Deletion complete. Success: {results['success']}, Failed: {results['failed']}")
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise
    finally:
        # Clean up - close the DirectusService httpx client
        await directus_service.close()


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())

