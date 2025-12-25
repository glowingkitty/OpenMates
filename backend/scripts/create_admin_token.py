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

async def main():
    """Generate an admin token and display the URL."""
    try:
        print("\n🔐 OpenMates Admin Token Generator")
        print("=" * 50)
        print("This will create a 30-second valid token for granting admin privileges.\n")

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
        admin_token = await directus_service.admin.create_admin_token(duration_seconds=30)

        if not admin_token:
            print("❌ Failed to create admin token!")
            return 1

        # Get frontend URL from environment
        frontend_url = os.getenv("FRONTEND_URL", "https://app.openmates.org")

        # Construct the admin URL
        admin_url = f"{frontend_url}/settings/server/become-admin?token={admin_token}"

        print("✅ Admin token created successfully!")
        print("\n🔗 Admin URL (valid for 30 seconds):")
        print("-" * 50)
        print(f"{admin_url}")
        print("-" * 50)
        print("\n📝 Instructions:")
        print("1. Copy the URL above")
        print("2. Send it to the user who should become server admin")
        print("3. They must open the URL while logged into their account")
        print("4. The token expires in 30 seconds for security")
        print("\n⚠️  Security Notes:")
        print("- Only share this URL with trusted users")
        print("- The URL grants permanent admin privileges")
        print("- Admin privileges cannot be revoked through the UI")
        print("\n🕐 Token expires in 30 seconds starting... NOW!")

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