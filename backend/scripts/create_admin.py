#!/usr/bin/env python3
"""
Script to grant server administrator privileges to a user by email address.
This script directly updates the database and does not require an admin token.

Usage:
    docker exec -it api python /app/backend/scripts/create_admin.py <email_address>
"""

import asyncio
import argparse
import hashlib
import logging
import sys
import base64

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('create_admin')

def hash_email_sha256(email: str) -> str:
    """Hash email address using SHA-256 (base64) for Directus lookup."""
    email_bytes = email.strip().lower().encode('utf-8')
    hashed_email_buffer = hashlib.sha256(email_bytes).digest()
    return base64.b64encode(hashed_email_buffer).decode('utf-8')

async def main():
    parser = argparse.ArgumentParser(description='Grant admin privileges to a user by email')
    parser.add_argument('email', type=str, help='User email address')
    args = parser.parse_args()

    sm = SecretsManager()
    await sm.initialize()
    
    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    
    try:
        email = args.email
        hashed_email = hash_email_sha256(email)
        
        logger.info(f"Searching for user with email: {email} (hash: {hashed_email})")
        
        # Search for user in Directus
        # We search by hashed_email which is indexed for privacy-preserving lookup
        # We only need the user ID to grant admin privileges
        params = {
            'filter': '{"hashed_email": {"_eq": "' + hashed_email + '"}}',
            'fields': 'id',
            'limit': 1
        }
        
        url = f"{directus_service.base_url}/users"
        admin_token = await directus_service.ensure_auth_token(admin_required=True)
        headers = {
            "Authorization": f"Bearer {admin_token}",
            "Cache-Control": "no-store"
        }
        
        response = await directus_service._make_api_request("GET", url, params=params, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to query Directus users: {response.status_code} - {response.text}")
            return

        data = response.json().get("data", [])
        if not data:
            logger.error(f"User not found with email: {email}")
            return

        user = data[0]
        user_id = user.get('id')
        
        logger.info(f"Found user ID: {user_id}")
        
        # Grant admin privileges
        success = await directus_service.admin.make_user_admin(user_id)
        
        if success:
            logger.info(f"SUCCESS: User {email} is now a server administrator.")
            logger.info("User profile cache has been invalidated - the Server settings section will appear")
            logger.info("on the next authentication check (typically within a few seconds).")
        else:
            logger.error(f"FAILED to grant admin privileges to user {user_id}")
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await sm.aclose()
        await directus_service.close()

if __name__ == "__main__":
    asyncio.run(main())
