#!/usr/bin/env python3
"""
Admin Helper Script: Delete User Account by Email

This script allows administrators to delete a user account by providing
their email address. It performs the same deletion process as when a
user manually deletes their account via the Settings > Account > Delete Account UI.

Security:
- The email is hashed using the same Vault HMAC process used in the application
- User lookup is done by hashed_email (never stores/logs plaintext email)
- Requires explicit confirmation before deletion
- Supports dry-run mode to preview what would happen

Usage:
    # Must be run from within a Docker container that has access to backend services
    # (Vault, Directus, Redis, Celery)
    
    # Interactive mode (prompts for confirmation):
    python scripts/delete_user_account.py --email user@example.com
    
    # Dry-run mode (preview without actually deleting):
    python scripts/delete_user_account.py --email user@example.com --dry-run
    
    # Skip confirmation (for scripted use - USE WITH CAUTION):
    python scripts/delete_user_account.py --email user@example.com --yes
    
    # With custom deletion reason (for compliance logging):
    python scripts/delete_user_account.py --email user@example.com --reason "Policy violation"
    
Running from Docker:
    # Option 1: Execute in running backend container
    docker compose exec backend python scripts/delete_user_account.py --email user@example.com
    
    # Option 2: Run as a one-off container
    docker compose run --rm backend python scripts/delete_user_account.py --email user@example.com
"""

import argparse
import asyncio
import logging
import sys
import os

# Add backend to path for imports when running as script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def initialize_services():
    """
    Initialize the required services for user deletion.
    
    Returns:
        Tuple of (cache_service, encryption_service, directus_service)
    """
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService
    
    logger.info("Initializing services...")
    
    # Initialize services in the correct order
    cache_service = CacheService()
    # Ensure cache client is ready
    await cache_service.client
    logger.debug("CacheService initialized")
    
    encryption_service = EncryptionService(cache_service=cache_service)
    logger.debug("EncryptionService initialized")
    
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service
    )
    logger.debug("DirectusService initialized")
    
    logger.info("All services initialized successfully")
    return cache_service, encryption_service, directus_service


async def lookup_user_by_email(
    email: str,
    encryption_service,
    directus_service
) -> dict | None:
    """
    Look up a user by their email address.
    
    The email is hashed using Vault HMAC before lookup to match
    how users are stored in the database (privacy-preserving).
    
    Args:
        email: The plaintext email address to look up
        encryption_service: EncryptionService instance for hashing
        directus_service: DirectusService instance for database queries
        
    Returns:
        User data dict if found, None otherwise
    """
    # Hash the email using Vault HMAC (same process as user registration/login)
    logger.info(f"Hashing email for lookup (email length: {len(email)})")
    hashed_email = await encryption_service.hash_email(email)
    
    if not hashed_email:
        logger.error("Failed to hash email - check Vault connectivity")
        return None
    
    # Only log first 8 chars of hash for debugging (privacy)
    logger.debug(f"Email hashed successfully (hash prefix: {hashed_email[:8]}...)")
    
    # Look up user by hashed email
    success, user_data, message = await directus_service.get_user_by_hashed_email(hashed_email)
    
    if not success or not user_data:
        logger.warning(f"User not found: {message}")
        return None
    
    logger.info(f"User found: ID={user_data.get('id')}")
    return user_data


async def get_user_preview_info(user_id: str, directus_service) -> dict:
    """
    Get preview information about what will happen during deletion.
    
    This mirrors the preview shown in the UI at Settings > Account > Delete Account.
    
    Args:
        user_id: The user's ID
        directus_service: DirectusService instance
        
    Returns:
        Dict with preview information
    """
    preview = {
        'user_id': user_id,
        'has_passkeys': False,
        'passkey_count': 0,
        'has_api_keys': False,
        'api_key_count': 0,
        'chat_count': 0,
    }
    
    try:
        # Count passkeys
        passkeys = await directus_service.get_user_passkeys_by_user_id(user_id)
        preview['passkey_count'] = len(passkeys) if passkeys else 0
        preview['has_passkeys'] = preview['passkey_count'] > 0
    except Exception as e:
        logger.warning(f"Could not fetch passkey count: {e}")
    
    try:
        # Count API keys
        api_keys = await directus_service.get_user_api_keys_by_user_id(user_id)
        preview['api_key_count'] = len(api_keys) if api_keys else 0
        preview['has_api_keys'] = preview['api_key_count'] > 0
    except Exception as e:
        logger.warning(f"Could not fetch API key count: {e}")
    
    try:
        # Count chats (using hashed_user_id as chats table uses this field for privacy)
        import hashlib
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        chats = await directus_service.get_items(
            "chats",
            params={"filter": {"hashed_user_id": {"_eq": hashed_user_id}}, "limit": 1000}
        )
        preview['chat_count'] = len(chats) if chats else 0
    except Exception as e:
        logger.warning(f"Could not fetch chat count: {e}")
    
    return preview


def trigger_deletion_task(
    user_id: str,
    deletion_type: str,
    reason: str,
    refund_invoices: bool
) -> str:
    """
    Trigger the Celery task for account deletion.
    
    This is the same task triggered by the UI when a user deletes their account.
    
    Args:
        user_id: The user's ID to delete
        deletion_type: Type of deletion (admin_action, policy_violation, etc.)
        reason: Reason for deletion (for compliance logging)
        refund_invoices: Whether to auto-refund eligible purchases
        
    Returns:
        The Celery task ID
    """
    from backend.core.api.app.tasks.celery_config import app as celery_app
    
    # Send the task to the same queue used by the UI
    task_result = celery_app.send_task(
        name="delete_user_account",
        kwargs={
            "user_id": user_id,
            "deletion_type": deletion_type,
            "reason": reason,
            "ip_address": "admin_script",  # Indicates deletion via admin script
            "device_fingerprint": "admin_cli",
            "refund_invoices": refund_invoices
        },
        queue="user_init"  # Same queue as user-initiated deletions
    )
    
    logger.info(f"Deletion task triggered: task_id={task_result.id}")
    return task_result.id


def print_preview(user_data: dict, preview: dict):
    """
    Print a preview of what will be deleted.
    
    Args:
        user_data: User data from Directus
        preview: Preview information
    """
    print("\n" + "=" * 60)
    print("ACCOUNT DELETION PREVIEW")
    print("=" * 60)
    print(f"\nUser ID: {user_data.get('id')}")
    print(f"Username: {user_data.get('username', 'N/A')}")
    print(f"Created: {user_data.get('date_created', 'N/A')}")
    
    print("\n" + "-" * 60)
    print("DATA TO BE DELETED:")
    print("-" * 60)
    print(f"  • Passkeys: {preview.get('passkey_count', 0)}")
    print(f"  • API Keys: {preview.get('api_key_count', 0)}")
    print(f"  • Chats: {preview.get('chat_count', 0)}")
    print("  • All messages, embeddings, and associated data")
    print("  • All sessions and authentication tokens")
    print("  • User profile and settings")
    
    print("\n" + "-" * 60)
    print("REFUND POLICY:")
    print("-" * 60)
    print("  • All unused credits will be refunded")
    print("  • Credits from gift card redemptions are NOT refunded")
    
    print("\n" + "=" * 60)


async def main():
    """
    Main entry point for the script.
    """
    parser = argparse.ArgumentParser(
        description="Delete a user account by email address",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Preview deletion (dry-run):
    python scripts/delete_user_account.py --email user@example.com --dry-run
    
    # Delete with confirmation:
    python scripts/delete_user_account.py --email user@example.com
    
    # Delete without confirmation (scripted use):
    python scripts/delete_user_account.py --email user@example.com --yes
    
    # Delete for policy violation:
    python scripts/delete_user_account.py --email user@example.com --reason "Terms of service violation"
        """
    )
    
    parser.add_argument(
        "--email",
        required=True,
        help="Email address of the user to delete"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without actually deleting"
    )
    
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt (use with caution)"
    )
    
    parser.add_argument(
        "--reason",
        default="Admin-initiated account deletion",
        help="Reason for deletion (for compliance logging)"
    )
    
    parser.add_argument(
        "--deletion-type",
        default="admin_action",
        choices=["admin_action", "policy_violation", "user_requested"],
        help="Type of deletion (default: admin_action)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging"
    )
    
    args = parser.parse_args()
    
    # Set logging level based on verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Validate email format (basic check)
    email = args.email.strip().lower()
    if '@' not in email or '.' not in email:
        logger.error("Invalid email format")
        sys.exit(1)
    
    print("\n🔍 Looking up user by email...")
    
    # Initialize services
    try:
        cache_service, encryption_service, directus_service = await initialize_services()
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        logger.error("Make sure you're running this script inside a Docker container with access to Vault, Directus, and Redis")
        sys.exit(1)
    
    try:
        # Look up user by email
        user_data = await lookup_user_by_email(email, encryption_service, directus_service)
        
        if not user_data:
            print(f"\n❌ No user found with email: {email}")
            print("   The email might be misspelled or the user may not exist.")
            sys.exit(1)
        
        user_id = user_data.get('id')
        print(f"✅ User found: {user_id}")
        
        # Get preview information
        preview = await get_user_preview_info(user_id, directus_service)
        
        # Print preview
        print_preview(user_data, preview)
        
        # Handle dry-run mode
        if args.dry_run:
            print("\n🔎 DRY-RUN MODE: No changes were made")
            print("   Remove --dry-run flag to actually delete the account")
            sys.exit(0)
        
        # Confirmation prompt
        if not args.yes:
            print("\n⚠️  WARNING: This action is IRREVERSIBLE!")
            print("   All user data will be permanently deleted.")
            confirm = input("\nType 'DELETE' to confirm deletion: ")
            
            if confirm != "DELETE":
                print("\n❌ Deletion cancelled")
                sys.exit(0)
        
        # Trigger deletion
        print("\n🗑️  Triggering account deletion...")
        print(f"   Deletion type: {args.deletion_type}")
        print(f"   Reason: {args.reason}")
        
        task_id = trigger_deletion_task(
            user_id=user_id,
            deletion_type=args.deletion_type,
            reason=args.reason,
            refund_invoices=True  # Always refund eligible purchases
        )
        
        print("\n✅ Account deletion initiated!")
        print(f"   Task ID: {task_id}")
        print(f"   User ID: {user_id}")
        print("\n📋 The deletion task is now running in the background.")
        print("   Check task worker logs for progress:")
        print("   docker compose logs -f task-worker | grep DELETE_ACCOUNT")
        
    except Exception as e:
        logger.error(f"Error during deletion process: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Clean up services
        try:
            await directus_service.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())

