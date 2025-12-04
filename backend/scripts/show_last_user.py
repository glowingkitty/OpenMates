#!/usr/bin/env python3
"""
Script to display information about the most recently signed up user.

This script:
1. Fetches the most recently created user from Directus
2. Decrypts server-side decryptable fields (username, credits, etc.)
3. Displays user information in a readable format

The script must be run inside the Docker container (api service) to have access
to the necessary environment variables and services.

Usage:
    docker exec -it api python /app/backend/scripts/show_last_user.py
    docker exec -it api python /app/backend/scripts/show_last_user.py --count 5  # Show last 5 users
"""

import asyncio
import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

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


async def get_recent_users(directus_service: DirectusService, count: int = 1) -> List[Dict[str, Any]]:
    """
    Fetch the most recently created users from Directus.
    
    Args:
        directus_service: The DirectusService instance
        count: Number of recent users to fetch (default: 1)
        
    Returns:
        List of user dictionaries sorted by creation date (newest first)
    """
    logger.info(f"Fetching {count} most recent users from Directus...")
    
    # Ensure we have admin token for accessing users
    await directus_service.ensure_auth_token(admin_required=True)
    if not directus_service.admin_token:
        logger.error("Failed to get admin token for fetching users")
        return []
    
    url = f"{directus_service.base_url}/users"
    params = {
        'fields': '*',  # Get all fields
        'limit': count,
        'sort': '-date_created'  # Sort by creation date descending (newest first)
        # Note: Directus uses 'date_created' for user creation timestamp
    }
    
    try:
        response = await directus_service._make_api_request("GET", url, params=params)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch users: {response.status_code} - {response.text}")
            return []
        
        data = response.json()
        users = data.get("data", [])
        
        logger.info(f"Fetched {len(users)} user(s)")
        return users
        
    except Exception as e:
        logger.error(f"Error fetching users: {e}", exc_info=True)
        return []


async def decrypt_user_fields(directus_service: DirectusService, user_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decrypt server-side decryptable fields for a user.
    
    Args:
        directus_service: The DirectusService instance
        user_data: Raw user data from Directus
        
    Returns:
        Dictionary with decrypted fields added
    """
    vault_key_id = user_data.get("vault_key_id")
    if not vault_key_id:
        logger.warning(f"User {user_data.get('id', 'unknown')} has no vault_key_id - cannot decrypt fields")
        return user_data
    
    # Fields that can be decrypted server-side
    fields_to_decrypt = [
        ("username", "encrypted_username"),
        ("credits", "encrypted_credit_balance"),
        ("profile_image_url", "encrypted_profileimage_url"),
        ("tfa_app_name", "encrypted_tfa_app_name"),
        ("gifted_credits_for_signup", "encrypted_gifted_credits_for_signup"),
        ("invoice_counter", "encrypted_invoice_counter")
    ]
    
    decrypted_data = user_data.copy()
    
    for field_name, encrypted_field_name in fields_to_decrypt:
        encrypted_value = user_data.get(encrypted_field_name)
        if encrypted_value:
            try:
                decrypted_value = await directus_service.encryption_service.decrypt_with_user_key(
                    encrypted_value, vault_key_id
                )
                
                if decrypted_value:
                    # Convert numeric fields to integers
                    if field_name in ["credits", "gifted_credits_for_signup", "invoice_counter"]:
                        try:
                            decrypted_data[field_name] = int(decrypted_value)
                        except (ValueError, TypeError):
                            logger.warning(f"Could not convert {field_name} to int: {decrypted_value}")
                            decrypted_data[field_name] = decrypted_value
                    else:
                        decrypted_data[field_name] = decrypted_value
                else:
                    decrypted_data[field_name] = None
            except Exception as e:
                logger.warning(f"Failed to decrypt {field_name}: {e}")
                decrypted_data[field_name] = f"<decryption_error: {str(e)[:50]}>"
        else:
            decrypted_data[field_name] = None
    
    return decrypted_data


def format_user_display(user_data: Dict[str, Any], index: int = 0) -> str:
    """
    Format user data for display in a readable format.
    
    Args:
        user_data: User data dictionary (with decrypted fields)
        index: User index (for multiple users)
        
    Returns:
        Formatted string for display
    """
    user_id = user_data.get("id", "unknown")
    username = user_data.get("username", "<not set>")
    is_admin = user_data.get("is_admin", False)
    
    # Format dates
    # Directus uses 'date_created' for creation timestamp, fallback to 'created_at' if not available
    date_created = user_data.get("date_created") or user_data.get("created_at")
    last_access = user_data.get("last_access")
    
    date_created_str = "N/A"
    if date_created:
        try:
            dt = datetime.fromisoformat(date_created.replace('Z', '+00:00'))
            date_created_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            date_created_str = str(date_created)
    
    last_access_str = "Never"
    if last_access:
        try:
            dt = datetime.fromisoformat(last_access.replace('Z', '+00:00'))
            last_access_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            last_access_str = str(last_access)
    
    # Build display string
    lines = []
    if index > 0:
        lines.append(f"\n{'='*80}")
        lines.append(f"USER #{index + 1}")
        lines.append(f"{'='*80}")
    else:
        lines.append(f"\n{'='*80}")
        lines.append(f"MOST RECENT USER")
        lines.append(f"{'='*80}")
    
    lines.append(f"User ID:        {user_id}")
    lines.append(f"Username:       {username}")
    lines.append(f"Admin:          {is_admin}")
    lines.append(f"Status:         {user_data.get('status', 'N/A')}")
    lines.append(f"Role:           {user_data.get('role', 'N/A')}")
    lines.append(f"")
    lines.append(f"Created:        {date_created_str}")
    lines.append(f"Last Access:    {last_access_str}")
    lines.append(f"Last Online:    {user_data.get('last_online_timestamp', 'N/A')}")
    lines.append(f"")
    lines.append(f"Credits:        {user_data.get('credits', 0)}")
    lines.append(f"Gifted Credits: {user_data.get('gifted_credits_for_signup', 0)}")
    lines.append(f"Invoice Counter: {user_data.get('invoice_counter', 0)}")
    lines.append(f"")
    lines.append(f"Language:       {user_data.get('language', 'en')}")
    lines.append(f"Dark Mode:      {user_data.get('darkmode', False)}")
    lines.append(f"2FA Enabled:    {bool(user_data.get('encrypted_tfa_secret'))}")
    if user_data.get('tfa_app_name'):
        lines.append(f"2FA App:        {user_data.get('tfa_app_name')}")
    lines.append(f"")
    lines.append(f"Account ID:     {user_data.get('account_id', 'N/A')}")
    lines.append(f"Vault Key ID:   {user_data.get('vault_key_id', 'N/A')}")
    lines.append(f"Vault Key Ver:  {user_data.get('vault_key_version', 'N/A')}")
    lines.append(f"")
    
    # Subscription info
    if user_data.get('stripe_customer_id') or user_data.get('stripe_subscription_id'):
        lines.append(f"Subscription:")
        lines.append(f"  Customer ID:  {user_data.get('stripe_customer_id', 'N/A')}")
        lines.append(f"  Subscription: {user_data.get('stripe_subscription_id', 'N/A')}")
        lines.append(f"  Status:       {user_data.get('subscription_status', 'N/A')}")
        lines.append(f"  Credits:      {user_data.get('subscription_credits', 'N/A')}")
        lines.append(f"  Currency:     {user_data.get('subscription_currency', 'N/A')}")
        lines.append(f"  Next Billing: {user_data.get('next_billing_date', 'N/A')}")
        lines.append(f"")
    
    # Auto top-up info
    if user_data.get('auto_topup_low_balance_enabled'):
        lines.append(f"Auto Top-up:")
        lines.append(f"  Enabled:      {user_data.get('auto_topup_low_balance_enabled', False)}")
        lines.append(f"  Threshold:    {user_data.get('auto_topup_low_balance_threshold', 'N/A')}")
        lines.append(f"  Amount:       {user_data.get('auto_topup_low_balance_amount', 'N/A')}")
        lines.append(f"  Currency:     {user_data.get('auto_topup_low_balance_currency', 'N/A')}")
        lines.append(f"")
    
    # Profile image
    if user_data.get('profile_image_url'):
        lines.append(f"Profile Image:  {user_data.get('profile_image_url')}")
        lines.append(f"")
    
    # Last opened
    if user_data.get('last_opened'):
        lines.append(f"Last Opened:    {user_data.get('last_opened')}")
        lines.append(f"")
    
    # Lookup hashes count
    lookup_hashes = user_data.get('lookup_hashes', [])
    if lookup_hashes:
        lines.append(f"Lookup Hashes:  {len(lookup_hashes)} authentication method(s)")
    
    # Connected devices
    connected_devices = user_data.get('connected_devices', [])
    if connected_devices:
        lines.append(f"Devices:        {len(connected_devices)} device(s) connected")
    
    lines.append(f"{'='*80}")
    
    return "\n".join(lines)


async def main():
    """
    Main function that fetches and displays the most recent user(s).
    """
    parser = argparse.ArgumentParser(description='Display information about the most recently signed up user(s)')
    parser.add_argument(
        '--count',
        type=int,
        default=1,
        help='Number of recent users to display (default: 1)'
    )
    args = parser.parse_args()
    
    logger.info("Starting user display script...")
    
    # Initialize services
    cache_service = CacheService()
    encryption_service = EncryptionService()
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    
    try:
        # Fetch recent users
        users = await get_recent_users(directus_service, count=args.count)
        
        if not users:
            logger.info("No users found.")
            return
        
        # Process and display each user
        for index, user in enumerate(users):
            logger.info(f"Processing user {index + 1}/{len(users)}...")
            
            # Decrypt user fields
            user_with_decrypted = await decrypt_user_fields(directus_service, user)
            
            # Display user information
            display = format_user_display(user_with_decrypted, index=index)
            print(display)
        
        logger.info("Display complete.")
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise
    finally:
        # Clean up - close the DirectusService httpx client
        await directus_service.close()


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())

