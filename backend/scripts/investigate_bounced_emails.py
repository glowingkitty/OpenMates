#!/usr/bin/env python3
"""
Script to investigate bounced transactional emails from Brevo.

This script fetches bounced email events from Brevo's API to help investigate
why emails are bouncing (currently ~0.98% bounce rate).

Bounce types:
- HARD_BOUNCE: Permanent delivery failures (invalid email address, domain doesn't exist)
- SOFT_BOUNCE: Temporary failures (mailbox full, server temporarily unavailable)

Usage:
    # Run inside the API container
    docker exec -it api python /app/backend/scripts/investigate_bounced_emails.py
    
    # With options
    docker exec -it api python /app/backend/scripts/investigate_bounced_emails.py --days 7
    docker exec -it api python /app/backend/scripts/investigate_bounced_emails.py --days 30 --export bounces.csv
    docker exec -it api python /app/backend/scripts/investigate_bounced_emails.py --email user@example.com
"""

import asyncio
import argparse
import logging
import sys
import csv
from datetime import datetime
from typing import Dict, Any

# Add the backend directory to the Python path
sys.path.insert(0, '/app/backend')

from backend.core.api.app.services.email.brevo_provider import BrevoProvider
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def anonymize_email(email: str) -> str:
    """
    Anonymize an email address by showing only the first 2 characters
    of the local part and the full domain.
    
    Examples:
        - j-e-2015@eeb.de → j-***@eeb.de
        - günterschmidt@me.com → gü***@me.com
        - a@test.com → a***@test.com
    """
    if not email or "@" not in email:
        return email or "Unknown"
    
    local_part, domain = email.rsplit("@", 1)
    
    # Show first 2 characters of local part (or all if shorter)
    if len(local_part) <= 2:
        masked_local = local_part + "***"
    else:
        masked_local = local_part[:2] + "***"
    
    return f"{masked_local}@{domain}"


def format_timestamp(ts) -> str:
    """
    Convert timestamp to readable date string.
    
    Handles both Unix timestamps (int) and ISO date strings from Brevo API.
    Brevo API returns dates in ISO format like "2023-10-27T10:00:00Z" or "2023-10-27".
    """
    try:
        if ts is None:
            return "Unknown"
        
        # Handle ISO date string format from Brevo API (e.g., "2023-10-27T10:00:00Z")
        if isinstance(ts, str):
            # Try ISO format with time
            if "T" in ts:
                # Remove 'Z' suffix if present and parse
                ts_clean = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
                try:
                    dt = datetime.fromisoformat(ts_clean)
                    return dt.strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    # Try without timezone
                    dt = datetime.fromisoformat(ts.split("+")[0].replace("Z", ""))
                    return dt.strftime('%Y-%m-%d %H:%M:%S')
            else:
                # Just a date string (YYYY-MM-DD)
                return ts
        
        # Handle Unix timestamp (int)
        if isinstance(ts, (int, float)) and ts > 0:
            return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        
        return "Unknown"
    except (ValueError, TypeError):
        return f"Unknown ({ts})"


def format_bounce_report(bounce_data: Dict[str, Any]) -> str:
    """
    Format bounce data into a readable report.
    
    Args:
        bounce_data: Dict from BrevoProvider.get_bounced_emails()
        
    Returns:
        Formatted string report
    """
    lines = []
    lines.append("")
    lines.append("=" * 100)
    lines.append("BREVO BOUNCED EMAIL INVESTIGATION REPORT")
    lines.append("=" * 100)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    
    # Summary section
    lines.append("-" * 100)
    lines.append("SUMMARY")
    lines.append("-" * 100)
    total_bounces = bounce_data["total_hard_bounces"] + bounce_data["total_soft_bounces"]
    lines.append(f"Total Bounces:      {total_bounces:,}")
    lines.append(f"  Hard Bounces:     {bounce_data['total_hard_bounces']:,}")
    lines.append(f"  Soft Bounces:     {bounce_data['total_soft_bounces']:,}")
    lines.append("")
    
    # Error check
    if "error" in bounce_data:
        lines.append(f"⚠️  WARNING: {bounce_data['error']}")
        lines.append("")
    
    # Bounce reasons section
    if bounce_data["summary"]["by_reason"]:
        lines.append("-" * 100)
        lines.append("BOUNCES BY REASON (Top 20)")
        lines.append("-" * 100)
        for i, (reason, count) in enumerate(bounce_data["summary"]["by_reason"].items()):
            if i >= 20:
                remaining = len(bounce_data["summary"]["by_reason"]) - 20
                lines.append(f"  ... and {remaining} more reasons")
                break
            lines.append(f"  [{count:4d}] {reason}")
        lines.append("")
    
    # Bounces by domain section
    if bounce_data["summary"]["by_domain"]:
        lines.append("-" * 100)
        lines.append("BOUNCES BY EMAIL DOMAIN (Top 20)")
        lines.append("-" * 100)
        for i, (domain, count) in enumerate(bounce_data["summary"]["by_domain"].items()):
            if i >= 20:
                remaining = len(bounce_data["summary"]["by_domain"]) - 20
                lines.append(f"  ... and {remaining} more domains")
                break
            lines.append(f"  [{count:4d}] {domain}")
        lines.append("")
    
    # Detailed hard bounces section (show first 50)
    if bounce_data["hard_bounces"]:
        lines.append("-" * 100)
        lines.append("HARD BOUNCE DETAILS (First 50)")
        lines.append("-" * 100)
        lines.append(f"{'Email':<40} {'Date':<20} {'Reason'}")
        lines.append("-" * 100)
        
        for i, bounce in enumerate(bounce_data["hard_bounces"][:50]):
            # Anonymize email for privacy (show first 2 chars + domain)
            email = anonymize_email(bounce.get("email", "Unknown"))[:38]
            # Brevo API uses "date" field, not "eventTime"
            event_time = format_timestamp(bounce.get("date"))
            reason = bounce.get("reason", "Unknown")[:60]
            lines.append(f"{email:<40} {event_time:<20} {reason}")
        
        if len(bounce_data["hard_bounces"]) > 50:
            remaining = len(bounce_data["hard_bounces"]) - 50
            lines.append(f"  ... and {remaining} more hard bounces")
        lines.append("")
    
    # Detailed soft bounces section (show first 30)
    if bounce_data["soft_bounces"]:
        lines.append("-" * 100)
        lines.append("SOFT BOUNCE DETAILS (First 30)")
        lines.append("-" * 100)
        lines.append(f"{'Email':<40} {'Date':<20} {'Reason'}")
        lines.append("-" * 100)
        
        for i, bounce in enumerate(bounce_data["soft_bounces"][:30]):
            # Anonymize email for privacy (show first 2 chars + domain)
            email = anonymize_email(bounce.get("email", "Unknown"))[:38]
            # Brevo API uses "date" field, not "eventTime"
            event_time = format_timestamp(bounce.get("date"))
            reason = bounce.get("reason", "Unknown")[:60]
            lines.append(f"{email:<40} {event_time:<20} {reason}")
        
        if len(bounce_data["soft_bounces"]) > 30:
            remaining = len(bounce_data["soft_bounces"]) - 30
            lines.append(f"  ... and {remaining} more soft bounces")
        lines.append("")
    
    # Recommendations section
    lines.append("-" * 100)
    lines.append("INVESTIGATION RECOMMENDATIONS")
    lines.append("-" * 100)
    lines.append("")
    lines.append("For HARD BOUNCES (permanent failures):")
    lines.append("  - Invalid email addresses: User may have mistyped during signup")
    lines.append("  - Domain doesn't exist: Email domain is invalid or decommissioned")
    lines.append("  - Mailbox doesn't exist: User no longer exists at that domain")
    lines.append("  → Consider: Remove these emails from future sends")
    lines.append("")
    lines.append("For SOFT BOUNCES (temporary failures):")
    lines.append("  - Mailbox full: User hasn't cleared their inbox")
    lines.append("  - Server temporarily unavailable: Retry may succeed")
    lines.append("  - Rate limited: Receiving server is throttling")
    lines.append("  → Consider: Brevo typically retries soft bounces automatically")
    lines.append("")
    lines.append("=" * 100)
    
    return "\n".join(lines)


def export_to_csv(
    bounce_data: Dict[str, Any], 
    filepath: str,
    include_soft_bounces: bool = True
) -> None:
    """
    Export bounce data to CSV file for further analysis.
    
    Args:
        bounce_data: Dict from BrevoProvider.get_bounced_emails()
        filepath: Path to write CSV file
        include_soft_bounces: Whether to include soft bounces
    """
    all_bounces = []
    
    # Add hard bounces with type indicator
    for bounce in bounce_data["hard_bounces"]:
        bounce_copy = bounce.copy()
        bounce_copy["bounce_type"] = "HARD"
        # Brevo API uses "date" field
        bounce_copy["event_time_formatted"] = format_timestamp(bounce.get("date"))
        # Anonymize email for privacy
        bounce_copy["email"] = anonymize_email(bounce.get("email", ""))
        all_bounces.append(bounce_copy)
    
    # Add soft bounces with type indicator
    if include_soft_bounces:
        for bounce in bounce_data["soft_bounces"]:
            bounce_copy = bounce.copy()
            bounce_copy["bounce_type"] = "SOFT"
            # Brevo API uses "date" field
            bounce_copy["event_time_formatted"] = format_timestamp(bounce.get("date"))
            # Anonymize email for privacy
            bounce_copy["email"] = anonymize_email(bounce.get("email", ""))
            all_bounces.append(bounce_copy)
    
    if not all_bounces:
        logger.warning("No bounces to export")
        return
    
    # Define CSV columns (based on Brevo API response fields)
    # See: https://developers.brevo.com/reference/getemaileventreport-1
    fieldnames = [
        "bounce_type",
        "email",
        "event_time_formatted",
        "date",
        "event",
        "reason",
        "messageId",
        "templateId",
        "tags"
    ]
    
    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_bounces)
    
    logger.info(f"Exported {len(all_bounces)} bounces to {filepath}")


async def main():
    """Main function to fetch and display bounced email report."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Investigate bounced transactional emails from Brevo"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to look back (max 90, default 30)"
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Filter by specific email address"
    )
    parser.add_argument(
        "--no-soft-bounces",
        action="store_true",
        help="Exclude soft bounces from report"
    )
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="Export bounces to CSV file (e.g., --export bounces.csv)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of results per bounce type (default 500)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only show summary, not detailed bounce list"
    )
    
    args = parser.parse_args()
    
    # Validate days parameter
    if args.days > 90:
        logger.warning(f"Days parameter {args.days} exceeds max of 90. Using 90.")
        args.days = 90
    
    logger.info(f"Starting bounced email investigation (last {args.days} days)...")
    
    # Initialize secrets manager to get Brevo API key
    secrets_manager = SecretsManager()
    
    try:
        # Initialize secrets manager (authenticates with Vault)
        logger.info("Initializing secrets manager...")
        await secrets_manager.initialize()
        
        # Get Brevo API key from secrets
        brevo_api_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/brevo",
            secret_key="api_key"
        )
        
        if not brevo_api_key:
            logger.error(
                "Brevo API key not found in secrets. "
                "Expected at: kv/data/providers/brevo -> api_key"
            )
            print("\n❌ ERROR: Brevo API key not configured. Cannot fetch bounce data.")
            return
        
        # Initialize Brevo provider
        brevo = BrevoProvider(api_key=brevo_api_key)
        
        # Fetch bounced emails
        logger.info("Fetching bounced emails from Brevo API...")
        bounce_data = await brevo.get_bounced_emails(
            days=args.days,
            include_soft_bounces=not args.no_soft_bounces,
            email=args.email,
            limit=args.limit
        )
        
        # Check for errors
        if "error" in bounce_data and bounce_data["total_hard_bounces"] == 0:
            logger.error(f"Failed to fetch bounce data: {bounce_data['error']}")
            print(f"\n❌ ERROR: {bounce_data['error']}")
            return
        
        # Format and display report
        if args.quiet:
            # Just show summary
            total = bounce_data["total_hard_bounces"] + bounce_data["total_soft_bounces"]
            print(f"\nBounce Summary (last {args.days} days):")
            print(f"  Total: {total}")
            print(f"  Hard Bounces: {bounce_data['total_hard_bounces']}")
            print(f"  Soft Bounces: {bounce_data['total_soft_bounces']}")
        else:
            report = format_bounce_report(bounce_data)
            print(report)
        
        # Export to CSV if requested
        if args.export:
            export_to_csv(
                bounce_data, 
                args.export,
                include_soft_bounces=not args.no_soft_bounces
            )
            print(f"\n✅ Exported bounce data to: {args.export}")
        
        logger.info("Bounce investigation complete.")
        
    except Exception as e:
        logger.error(f"Fatal error in bounce investigation: {e}", exc_info=True)
        print(f"\n❌ ERROR: {str(e)}")
        raise
    finally:
        # Clean up secrets manager
        await secrets_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

