#!/usr/bin/env python3
"""
Script to generate admin tokens for granting server admin privileges.

This script should only be run via docker exec by the server administrator.
It creates a 30-second valid token that can be used to grant admin privileges
to a user account.

Usage:
    docker exec openmates-api python /app/backend/scripts/create_admin_token.py

The script will output a URL that can be shared with the user who should
become the server admin.
"""

import asyncio
import os
import sys
import logging
import argparse
from typing import Optional
from pathlib import Path

# Add the parent directory to Python path to import our modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Set up basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_frontend_url(args_url: Optional[str] = None) -> str:
    """
    Determine the best frontend URL to use.
    
    Order of priority:
    1. Command line argument --url
    2. FRONTEND_URL environment variable
    3. FRONTEND_URLS environment variable (comma-separated list)
    4. Default fallback (https://app.openmates.org)
    """
    # 1. Command line argument
    if args_url:
        return args_url.rstrip('/')

    # 2. FRONTEND_URL environment variable
    env_url = os.getenv("FRONTEND_URL")
    if env_url:
        return env_url.rstrip('/')

    # 3. FRONTEND_URLS environment variable
    env_urls = os.getenv("FRONTEND_URLS")
    if env_urls:
        urls = [u.strip().rstrip('/') for u in env_urls.split(',') if u.strip()]
        if urls:
            # Prioritize non-localhost and HTTPS
            priority_urls = []
            for u in urls:
                score = 0
                if u.startswith('https://'):
                    score += 2
                if 'localhost' not in u and '127.0.0.1' not in u:
                    score += 5
                priority_urls.append((score, u))
            
            # Sort by score descending
            priority_urls.sort(key=lambda x: x[0], reverse=True)
            return priority_urls[0][1]

    # 4. Default fallback
    return "https://app.openmates.org"

async def main():
    """Generate an admin token and display the URL."""
    parser = argparse.ArgumentParser(description="Generate admin token for OpenMates.")
    parser.add_argument("--url", help="Override the frontend URL (e.g., https://app.dev.openmates.org)")
    parser.add_argument("--duration", type=int, default=30, help="Token duration in seconds (default: 30)")
    args = parser.parse_args()

    try:
        print("\n🔐 OpenMates Admin Token Generator")
        print("=" * 50)
        print(f"This will create a {args.duration}-second valid token for granting admin privileges.\n")

        # Initialize services
        print("🔧 Initializing services...")

        # Initialize secrets manager
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()

        # Initialize encryption service
        encryption_service = EncryptionService(secrets_manager)

        # Initialize cache service
        cache_service = CacheService()

        # Initialize Directus service
        directus_service = DirectusService(cache_service, encryption_service)

        # Create admin token
        print("🎟️  Generating admin token...")
        admin_token = await directus_service.admin.create_admin_token(duration_seconds=args.duration)

        if not admin_token:
            print("❌ Failed to create admin token!")
            return 1

        # Determine frontend URL
        frontend_url = get_frontend_url(args.url)

        # Construct the admin URL
        admin_url = f"{frontend_url}/#settings/server/become-admin?token={admin_token}"

        print("✅ Admin token created successfully!")
        print(f"\n🔗 Admin URL (valid for {args.duration} seconds):")
        print("-" * 50)
        print(f"{admin_url}")
        print("-" * 50)
        print("\n📝 Instructions:")
        print("1. Copy the URL above")
        print("2. Send it to the user who should become server admin")
        print("3. They must open the URL while logged into their account")
        print(f"4. The token expires in {args.duration} seconds for security")
        print("\n⚠️  Security Notes:")
        print("- Only share this URL with trusted users")
        print("- The URL grants permanent admin privileges")
        print("- Admin privileges cannot be revoked through the UI")
        print(f"\n🕐 Token expires in {args.duration} seconds starting... NOW!")

        # Close services
        await directus_service.close()

        return 0

    except Exception as e:
        print(f"❌ Error generating admin token: {e}")
        logger.error(f"Error in create_admin_token script: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)