#!/usr/bin/env python3
"""
Script to fetch emails from an InboxKitten temporary email address.

This script:
1. Creates a new temporary email address (or uses an existing one)
2. Fetches emails sent to that address
3. Can poll for new emails at intervals
4. Outputs emails to JSON or text file

InboxKitten is a disposable email service useful for testing and temporary email needs.
Emails are typically stored for a limited time, so retrieve them promptly.

Prerequisites:
- Python package 'inboxkitten' installed: pip install inboxkitten

Usage:
    # Create new address with random username and fetch emails
    python scripts/fetch_inboxkitten_emails.py
    
    # Create new address with specific username
    python scripts/fetch_inboxkitten_emails.py --username test
    
    # Use existing address
    python scripts/fetch_inboxkitten_emails.py --email test@inboxkitten.com
    
    # Poll for new emails every 5 seconds for 60 seconds
    python scripts/fetch_inboxkitten_emails.py --email test@inboxkitten.com --poll --interval 5 --timeout 60
    
    # Save to specific file
    python scripts/fetch_inboxkitten_emails.py --email test@inboxkitten.com --output my_emails.json
"""

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import inboxkitten as ik
except ImportError:
    logger.error(
        "inboxkitten package not found. Install it with: pip install inboxkitten"
    )
    raise


def extract_username(email_address: str) -> str:
    """
    Extract username from InboxKitten email address.
    
    Args:
        email_address: Full email address (e.g., 'test@inboxkitten.com')
        
    Returns:
        Username part (e.g., 'test')
    """
    if '@' in email_address:
        return email_address.split('@')[0]
    # If no @, assume it's already just the username
    return email_address


def create_temp_email(username: Optional[str] = None) -> str:
    """
    Create a new temporary email address using InboxKitten.
    
    Args:
        username: Optional username for the email (if None, will be generated)
        
    Returns:
        Temporary email address string (e.g., 'test@inboxkitten.com')
        
    Raises:
        Exception: If email creation fails
    """
    try:
        if username is None:
            # Generate a random username
            import random
            import string
            username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        
        logger.info(f"Creating temporary email address with username: {username}")
        email_address = f"{username}@inboxkitten.com"
        logger.info(f"Temporary email address: {email_address}")
        return email_address
    except Exception as e:
        logger.error(f"Failed to create temporary email address: {e}", exc_info=True)
        raise


def fetch_emails(email_address: str) -> List[Dict]:
    """
    Fetch all emails for a given InboxKitten email address.
    
    Args:
        email_address: The InboxKitten email address to fetch emails for
        
    Returns:
        List of email dictionaries with keys: from, subject, text, index
    """
    emails = []
    
    try:
        # Extract username from email address
        username = extract_username(email_address)
        logger.info(f"Fetching emails for {email_address} (username: {username})...")
        
        # Create InboxKitten instance
        inbox = ik.InboxKitten(username)
        
        # Refresh to get latest emails
        inbox.refresh
        
        # Get subjects and senders lists
        subjects = inbox.subjects
        senders = inbox.senders
        
        if not subjects or len(subjects) == 0:
            logger.info("No emails found")
            return emails
        
        logger.info(f"Found {len(subjects)} email(s)")
        
        # Process each email by index
        for i in range(len(subjects)):
            try:
                # Get email text content
                try:
                    email_text = inbox.text(index=i)
                except ik.EmailNotFound:
                    logger.warning(f"Email at index {i} not found, skipping")
                    continue
                
                # Build email dictionary
                email_dict = {
                    "email_address": email_address,
                    "index": i,
                    "from": senders[i] if i < len(senders) else "Unknown",
                    "subject": subjects[i] if i < len(subjects) else "No Subject",
                    "text": email_text,
                    "body": email_text,  # Alias for consistency
                    "timestamp": datetime.now().isoformat()
                }
                
                emails.append(email_dict)
                
                logger.debug(
                    f"Email {i+1}/{len(subjects)}: From={email_dict['from']}, "
                    f"Subject={email_dict['subject'][:50]}..."
                )
                
            except Exception as e:
                logger.warning(f"Error processing email at index {i}: {e}", exc_info=True)
                continue
        
    except Exception as e:
        logger.error(f"Failed to fetch emails: {e}", exc_info=True)
    
    return emails


def poll_for_emails(
    email_address: str,
    interval: int = 5,
    timeout: int = 60,
    initial_fetch: bool = True
) -> List[Dict]:
    """
    Poll for new emails at regular intervals until timeout.
    
    Args:
        email_address: The InboxKitten email address to poll
        interval: Seconds between polling attempts (default: 5)
        timeout: Maximum seconds to poll (default: 60)
        initial_fetch: Whether to fetch emails immediately (default: True)
        
    Returns:
        List of all emails found during polling period
    """
    all_emails = []
    seen_email_ids = set()
    start_time = time.time()
    elapsed = 0
    
    logger.info(
        f"Polling for emails every {interval} seconds for up to {timeout} seconds"
    )
    
    # Initial fetch
    if initial_fetch:
        logger.info("Performing initial email fetch...")
        initial_emails = fetch_emails(email_address)
        all_emails.extend(initial_emails)
        # Track seen emails by creating a unique ID from subject + from + index
        for email in initial_emails:
            email_id = f"{email.get('from', '')}_{email.get('subject', '')}_{email.get('index', '')}"
            seen_email_ids.add(email_id)
    
    # Poll for new emails
    while elapsed < timeout:
        time.sleep(interval)
        elapsed = time.time() - start_time
        
        logger.info(f"Polling for new emails... (elapsed: {elapsed:.1f}s)")
        
        try:
            new_emails = fetch_emails(email_address)
            
            # Filter out emails we've already seen
            new_count = 0
            for email in new_emails:
                email_id = f"{email.get('from', '')}_{email.get('subject', '')}_{email.get('index', '')}"
                if email_id not in seen_email_ids:
                    seen_email_ids.add(email_id)
                    all_emails.append(email)
                    new_count += 1
                    logger.info(
                        f"New email received: From={email.get('from', 'N/A')}, "
                        f"Subject={email.get('subject', 'N/A')[:50]}"
                    )
            
            if new_count > 0:
                logger.info(f"Found {new_count} new email(s)")
            else:
                logger.debug("No new emails")
                
        except Exception as e:
            logger.warning(f"Error during polling: {e}", exc_info=True)
            continue
    
    logger.info(f"Polling completed. Total emails collected: {len(all_emails)}")
    return all_emails


def save_emails(emails: List[Dict], output_path: Path, format_type: str = "json"):
    """
    Save emails to a file in the specified format.
    
    Args:
        emails: List of email dictionaries
        output_path: Path to output file
        format_type: Output format - "json" or "text"
    """
    if format_type == "json":
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(emails, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(emails)} emails to {output_path} (JSON format)")
    else:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("InboxKitten Email Fetch Results\n")
            f.write(f"{'='*80}\n")
            f.write(f"Total emails: {len(emails)}\n")
            f.write(f"Fetched at: {datetime.now().isoformat()}\n")
            f.write(f"{'='*80}\n\n")
            
            for i, email_data in enumerate(emails, 1):
                f.write(f"\n{'='*80}\n")
                f.write(f"Email {i}/{len(emails)}\n")
                f.write(f"{'='*80}\n")
                f.write(f"Email Address: {email_data.get('email_address', 'N/A')}\n")
                f.write(f"From: {email_data.get('from', 'N/A')}\n")
                f.write(f"Subject: {email_data.get('subject', 'N/A')}\n")
                f.write(f"Index: {email_data.get('index', 'N/A')}\n")
                f.write(f"Timestamp: {email_data.get('timestamp', 'N/A')}\n")
                f.write(f"\nContent:\n{email_data.get('text', email_data.get('body', 'N/A'))}\n")
                f.write("\n")
        
        logger.info(f"Saved {len(emails)} emails to {output_path} (text format)")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch emails from an InboxKitten temporary email address"
    )
    parser.add_argument(
        "--email",
        type=str,
        help="Existing InboxKitten email address (e.g., test@inboxkitten.com)"
    )
    parser.add_argument(
        "--username",
        type=str,
        help="Username for new InboxKitten email address (e.g., 'test' creates test@inboxkitten.com). If not provided, a random username will be generated."
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Poll for new emails at intervals instead of single fetch"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Seconds between polling attempts (default: 5, only used with --poll)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Maximum seconds to poll (default: 60, only used with --poll)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="inboxkitten_emails.json",
        help="Output file path (default: inboxkitten_emails.json)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format: json or text (default: json)"
    )
    parser.add_argument(
        "--no-initial-fetch",
        action="store_true",
        help="Skip initial fetch when polling (only used with --poll)"
    )
    
    args = parser.parse_args()
    
    # Get or create email address
    if args.email:
        email_address = args.email
        logger.info(f"Using provided email address: {email_address}")
    else:
        email_address = create_temp_email(username=args.username)
        logger.info(f"Created new email address: {email_address}")
        print(f"\n{'='*80}")
        print(f"Your temporary email address: {email_address}")
        print(f"{'='*80}\n")
    
    # Fetch emails
    if args.poll:
        emails = poll_for_emails(
            email_address=email_address,
            interval=args.interval,
            timeout=args.timeout,
            initial_fetch=not args.no_initial_fetch
        )
    else:
        emails = fetch_emails(email_address)
    
    logger.info(f"Fetched {len(emails)} email(s)")
    
    # Save output
    if emails:
        output_path = Path(args.output)
        save_emails(emails, output_path, args.format)
        
        # Print summary
        total_text_length = sum(len(e.get("text", e.get("body", ""))) for e in emails)
        logger.info(f"Total text extracted: {total_text_length:,} characters")
        
        # Print email summary to console
        print(f"\n{'='*80}")
        print("Email Summary")
        print(f"{'='*80}")
        print(f"Email Address: {email_address}")
        print(f"Total Emails: {len(emails)}")
        print("\nEmails:")
        for i, email_data in enumerate(emails, 1):
            print(f"  {i}. From: {email_data.get('from', 'N/A')}")
            print(f"     Subject: {email_data.get('subject', 'N/A')[:60]}")
            print(f"     Index: {email_data.get('index', 'N/A')}")
        print(f"{'='*80}\n")
    else:
        logger.info("No emails to save")
        print(f"\nNo emails found for {email_address}\n")


if __name__ == "__main__":
    main()

