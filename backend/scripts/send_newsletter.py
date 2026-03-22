#!/usr/bin/env python3
"""
Script to send newsletter emails to all confirmed newsletter subscribers.

This script:
1. Fetches all confirmed newsletter subscribers from Directus
2. Decrypts their email addresses
3. Checks if emails are in the ignored list (skips if ignored)
4. Sends newsletter emails to each subscriber using the specified template
5. Provides progress feedback and error handling

The script must be run inside the Docker container (api service) to have access
to the necessary environment variables and services.

Usage:
    docker exec -it api python /app/backend/scripts/send_newsletter.py
    docker exec -it api python /app/backend/scripts/send_newsletter.py --template newsletter
    docker exec -it api python /app/backend/scripts/send_newsletter.py --template newsletter --dry-run
    docker exec -it api python /app/backend/scripts/send_newsletter.py --template newsletter --limit 10
"""

import asyncio
import argparse
import logging
import sys
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.newsletter_utils import check_ignored_email

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_all_newsletter_subscribers(
    directus_service: DirectusService,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Fetch all newsletter subscribers from Directus.
    
    All entries in the newsletter_subscribers collection have already confirmed
    their subscription (they are only added after confirmation).
    
    Args:
        directus_service: The DirectusService instance
        limit: Optional limit on number of subscribers to fetch (for testing)
        
    Returns:
        List of subscriber dictionaries
    """
    logger.info("Fetching newsletter subscribers from Directus...")
    
    collection_name = "newsletter_subscribers"
    url = f"{directus_service.base_url}/items/{collection_name}"
    
    # All entries in newsletter_subscribers are confirmed (only added after confirmation)
    params = {
        "fields": "*,id,encrypted_email_address,hashed_email,language,darkmode,unsubscribe_token,confirmed_at,subscribed_at",
        "sort": "subscribed_at"  # Sort by subscription date
    }
    
    # Add limit if specified (useful for testing)
    if limit:
        params["limit"] = limit
        logger.info(f"Limiting to {limit} subscribers for testing")
    
    try:
        response = await directus_service._make_api_request("GET", url, params=params)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch newsletter subscribers: {response.status_code} - {response.text}")
            return []
        
        data = response.json()
        subscribers = data.get("data", [])
        
        logger.info(f"Fetched {len(subscribers)} newsletter subscriber(s)")
        return subscribers
        
    except Exception as e:
        logger.error(f"Error fetching newsletter subscribers: {str(e)}", exc_info=True)
        return []


async def decrypt_subscriber_email(
    encryption_service: EncryptionService,
    encrypted_email: str
) -> Optional[str]:
    """
    Decrypt a subscriber's email address.
    
    Args:
        encryption_service: The EncryptionService instance
        encrypted_email: Encrypted email address from Directus
        
    Returns:
        Decrypted email address or None if decryption fails
    """
    if not encrypted_email:
        logger.warning("No encrypted email provided")
        return None
    
    try:
        decrypted_email = await encryption_service.decrypt_newsletter_email(encrypted_email)
        return decrypted_email
    except Exception as e:
        logger.error(f"Error decrypting email: {str(e)}", exc_info=True)
        return None


async def build_unsubscribe_url(
    subscriber: Dict[str, Any],
    base_url: str
) -> Optional[str]:
    """
    Build the unsubscribe URL for a subscriber.
    
    Args:
        subscriber: Subscriber dictionary containing unsubscribe_token
        base_url: Base URL for the frontend application
        
    Returns:
        Unsubscribe URL or None if token is missing
    """
    unsubscribe_token = subscriber.get("unsubscribe_token")
    if not unsubscribe_token:
        logger.warning(f"Subscriber {subscriber.get('id', 'unknown')} has no unsubscribe token")
        return None
    
    # Build unsubscribe URL using settings deep link format
    # Format: {base_url}/#settings/newsletter/unsubscribe/{token}
    unsubscribe_url = f"{base_url}/#settings/newsletter/unsubscribe/{unsubscribe_token}"
    return unsubscribe_url


async def send_newsletter_to_subscriber(
    email_template_service: EmailTemplateService,
    subscriber: Dict[str, Any],
    email: str,
    template_name: str,
    context: Dict[str, Any],
    dry_run: bool = False
) -> bool:
    """
    Send newsletter email to a single subscriber.
    
    Args:
        email_template_service: The EmailTemplateService instance
        subscriber: Subscriber dictionary
        email: Decrypted email address
        template_name: Name of the email template to use
        context: Context variables for the template
        dry_run: If True, only log what would be sent without actually sending
        
    Returns:
        True if email was sent successfully (or dry-run), False otherwise
    """
    language = subscriber.get("language", "en")
    hashed_email = subscriber.get("hashed_email", "")
    
    # Log subscriber info (masked for privacy)
    masked_email = f"{email[:2]}***" if len(email) > 2 else "***"
    logger.info(f"Processing subscriber: {masked_email} (language: {language})")
    
    if dry_run:
        logger.info(f"[DRY RUN] Would send newsletter to {masked_email} using template '{template_name}'")
        logger.info(f"[DRY RUN] Context: {list(context.keys())}")
        return True
    
    try:
        # Send the newsletter email
        success = await email_template_service.send_email(
            template=template_name,
            recipient_email=email,
            context=context,
            lang=language
        )
        
        if success:
            logger.info(f"Successfully sent newsletter to {masked_email}")
            return True
        else:
            logger.error(f"Failed to send newsletter to {masked_email}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending newsletter to {masked_email}: {str(e)}", exc_info=True)
        return False


async def send_newsletter_to_all(
    template_name: str = "newsletter",
    dry_run: bool = False,
    limit: Optional[int] = None
) -> None:
    """
    Main function to send newsletter emails to all confirmed subscribers.
    
    Args:
        template_name: Name of the email template to use (default: "newsletter")
        dry_run: If True, only simulate sending without actually sending emails
        limit: Optional limit on number of subscribers to process (for testing)
    """
    logger.info("=" * 80)
    logger.info("Newsletter Sending Script")
    logger.info("=" * 80)
    
    if dry_run:
        logger.info("DRY RUN MODE - No emails will be sent")
    
    logger.info(f"Template: {template_name}")
    if limit:
        logger.info(f"Limit: {limit} subscribers")
    
    # Initialize services
    logger.info("Initializing services...")
    try:
        # Initialize SecretsManager for email service
        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
        
        # Initialize services
        directus_service = DirectusService()
        cache_service = CacheService()
        encryption_service = EncryptionService(cache_service=cache_service)
        await encryption_service.initialize()
        email_template_service = EmailTemplateService(secrets_manager=secrets_manager)
        
        logger.info("Services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {str(e)}", exc_info=True)
        sys.exit(1)
    
    # Get base URL for unsubscribe links from shared config
    from backend.core.api.app.services.email.config_loader import load_shared_urls
    shared_urls = load_shared_urls()
    
    # Determine environment (development or production)
    is_dev = os.getenv("ENVIRONMENT", "production").lower() in ("development", "dev", "test") or \
             "localhost" in os.getenv("WEBAPP_URL", "").lower()
    env_name = "development" if is_dev else "production"
    
    # Get webapp URL from shared config
    base_url = shared_urls.get('urls', {}).get('base', {}).get('webapp', {}).get(env_name)
    
    # Fallback to environment variable or default
    if not base_url:
        base_url = os.getenv("WEBAPP_URL", "https://openmates.org" if not is_dev else "http://localhost:5173")
    
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    logger.info(f"Base URL: {base_url}")
    
    # Validate template exists (try to render it with empty context)
    if not dry_run:
        try:
            logger.info(f"Validating template '{template_name}'...")
            test_context = {"unsubscribe_url": base_url, "darkmode": False}
            email_template_service.render_template(template_name, test_context, "en")
            logger.info(f"Template '{template_name}' validated successfully")
        except Exception as e:
            logger.error(f"Template '{template_name}' validation failed: {str(e)}")
            logger.error("Please ensure the template exists in /backend/core/api/templates/email/")
            sys.exit(1)
    
    # Fetch all subscribers
    subscribers = await get_all_newsletter_subscribers(directus_service, limit=limit)
    
    if not subscribers:
        logger.warning("No newsletter subscribers found")
        return
    
    logger.info(f"Found {len(subscribers)} confirmed subscriber(s) to process")
    
    # Statistics
    stats = {
        "total": len(subscribers),
        "sent": 0,
        "failed": 0,
        "skipped_ignored": 0,
        "skipped_decrypt_failed": 0
    }
    
    # Process each subscriber
    logger.info("=" * 80)
    logger.info("Processing subscribers...")
    logger.info("=" * 80)
    
    for index, subscriber in enumerate(subscribers, 1):
        subscriber_id = subscriber.get("id", "unknown")
        hashed_email = subscriber.get("hashed_email", "")
        encrypted_email = subscriber.get("encrypted_email_address", "")
        
        logger.info(f"\n[{index}/{stats['total']}] Processing subscriber {subscriber_id}")
        
        # Check if email is in ignored list
        if hashed_email:
            is_ignored = await check_ignored_email(hashed_email, directus_service)
            if is_ignored:
                logger.info(f"Subscriber {subscriber_id} is in ignored list, skipping")
                stats["skipped_ignored"] += 1
                continue
        
        # Decrypt email
        email = await decrypt_subscriber_email(encryption_service, encrypted_email)
        if not email:
            logger.error(f"Failed to decrypt email for subscriber {subscriber_id}")
            stats["skipped_decrypt_failed"] += 1
            continue
        
        # Build unsubscribe URL
        unsubscribe_url = await build_unsubscribe_url(subscriber, base_url)
        
        # Get subscriber's darkmode preference (default to False if not set)
        darkmode = subscriber.get("darkmode", False)
        
        # Prepare email context
        # Add any custom context variables here that your newsletter template needs
        context = {
            "unsubscribe_url": unsubscribe_url,
            "darkmode": darkmode,  # Use subscriber's stored darkmode preference
            # Add any additional context variables your newsletter template requires
            # For example:
            # "newsletter_title": "Monthly Update",
            # "newsletter_content": "...",
            # etc.
        }
        
        # Send newsletter email
        success = await send_newsletter_to_subscriber(
            email_template_service=email_template_service,
            subscriber=subscriber,
            email=email,
            template_name=template_name,
            context=context,
            dry_run=dry_run
        )
        
        if success:
            stats["sent"] += 1
        else:
            stats["failed"] += 1
        
        # Small delay to avoid overwhelming the email service
        if not dry_run and index < stats["total"]:
            await asyncio.sleep(0.5)  # 500ms delay between emails
    
    # Print summary
    logger.info("=" * 80)
    logger.info("Newsletter Sending Summary")
    logger.info("=" * 80)
    logger.info(f"Total subscribers: {stats['total']}")
    logger.info(f"Successfully sent: {stats['sent']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Skipped (ignored): {stats['skipped_ignored']}")
    logger.info(f"Skipped (decrypt failed): {stats['skipped_decrypt_failed']}")
    logger.info("=" * 80)
    
    # Cleanup
    try:
        await directus_service.close()
        await cache_service.close()
        await encryption_service.close()
    except Exception as e:
        logger.warning(f"Error during cleanup: {str(e)}")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Send newsletter emails to all confirmed newsletter subscribers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send newsletter to all subscribers using default template
  docker exec -it api python /app/backend/scripts/send_newsletter.py
  
  # Send newsletter using specific template
  docker exec -it api python /app/backend/scripts/send_newsletter.py --template newsletter-monthly
  
  # Dry run (test without sending emails)
  docker exec -it api python /app/backend/scripts/send_newsletter.py --dry-run
  
  # Test with limited number of subscribers
  docker exec -it api python /app/backend/scripts/send_newsletter.py --limit 5
        """
    )
    
    parser.add_argument(
        "--template",
        type=str,
        default="newsletter",
        help="Name of the email template to use (default: 'newsletter')"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate sending without actually sending emails"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of subscribers to process (useful for testing)"
    )
    
    args = parser.parse_args()
    
    # Run the async function
    try:
        asyncio.run(send_newsletter_to_all(
            template_name=args.template,
            dry_run=args.dry_run,
            limit=args.limit
        ))
    except KeyboardInterrupt:
        logger.info("\nScript interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Script failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

