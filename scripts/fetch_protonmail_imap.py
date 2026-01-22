#!/usr/bin/env python3
"""
Script to fetch emails from ProtonMail via IMAP (using ProtonMail Bridge).

This script:
1. Connects to ProtonMail via IMAP (requires ProtonMail Bridge running)
2. Searches for emails matching criteria (subject, sender, date range)
3. Extracts email text content
4. Outputs to JSON or text file for LLM processing

Prerequisites:
- ProtonMail paid account (required for Bridge)
- ProtonMail Bridge installed and running
- IMAP credentials from Bridge (usually localhost:1143)

Usage:
    python scripts/fetch_protonmail_imap.py --imap-host localhost --imap-port 1143 --username your@email.com
    python scripts/fetch_protonmail_imap.py --imap-host localhost --imap-port 1143 --username your@email.com --search-subject "support"
    python scripts/fetch_protonmail_imap.py --imap-host localhost --imap-port 1143 --username your@email.com --folder "Support" --output support_emails.json
"""

import argparse
import email
import imaplib
import json
import logging
import getpass
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import Dict, List, Optional
from email.utils import parsedate_to_datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def decode_mime_header(header_value: Optional[str]) -> str:
    """Decode MIME-encoded email headers."""
    if not header_value:
        return ""
    
    try:
        decoded_parts = decode_header(header_value)
        decoded_string = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                if encoding:
                    decoded_string += part.decode(encoding)
                else:
                    decoded_string += part.decode('utf-8', errors='ignore')
            else:
                decoded_string += part
        return decoded_string
    except Exception as e:
        logger.warning(f"Failed to decode header '{header_value}': {e}")
        return str(header_value)


def extract_email_text(msg: email.message.Message) -> str:
    """Extract plain text from an email message."""
    text_content = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if "attachment" in content_disposition:
                continue
            
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        text_content = payload.decode(charset, errors='ignore')
                        break
                except Exception as e:
                    logger.warning(f"Failed to decode text/plain part: {e}")
            
            elif content_type == "text/html" and not text_content:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        html_content = payload.decode(charset, errors='ignore')
                        import re
                        text_content = re.sub(r'<[^>]+>', '', html_content)
                        text_content = re.sub(r'\s+', ' ', text_content).strip()
                except Exception as e:
                    logger.warning(f"Failed to decode text/html part: {e}")
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                text_content = payload.decode(charset, errors='ignore')
        except Exception as e:
            logger.warning(f"Failed to decode single part message: {e}")
    
    return text_content.strip()


def fetch_emails_imap(
    imap_host: str,
    imap_port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    search_subject: Optional[str] = None,
    search_sender: Optional[str] = None,
    days_back: Optional[int] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Fetch emails from IMAP server.
    
    Args:
        imap_host: IMAP server hostname
        imap_port: IMAP server port
        username: Email username
        password: Email password
        folder: Mailbox folder to search (default: INBOX)
        search_subject: Search for emails with this keyword in subject
        search_sender: Search for emails from this sender
        days_back: Only fetch emails from last N days
        limit: Maximum number of emails to fetch
        
    Returns:
        List of email dictionaries
    """
    emails = []
    
    try:
        # Connect to IMAP server
        logger.info(f"Connecting to {imap_host}:{imap_port}")
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        
        # Login
        logger.info(f"Logging in as {username}")
        mail.login(username, password)
        
        # Select folder
        logger.info(f"Selecting folder: {folder}")
        status, messages = mail.select(folder)
        if status != "OK":
            logger.error(f"Failed to select folder {folder}")
            return emails
        
        # Build search criteria
        search_criteria = ["ALL"]
        
        if search_subject:
            search_criteria.append(f'SUBJECT "{search_subject}"')
        
        if search_sender:
            search_criteria.append(f'FROM "{search_sender}"')
        
        if days_back:
            since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
            search_criteria.append(f'SINCE {since_date}')
        
        search_query = " ".join(search_criteria)
        logger.info(f"Search query: {search_query}")
        
        # Search for emails
        status, message_ids = mail.search(None, search_query)
        if status != "OK":
            logger.error("Failed to search emails")
            return emails
        
        message_id_list = message_ids[0].split()
        total_messages = len(message_id_list)
        logger.info(f"Found {total_messages} emails")
        
        # Limit results if specified
        if limit and total_messages > limit:
            message_id_list = message_id_list[-limit:]  # Get most recent N emails
            logger.info(f"Limiting to {limit} most recent emails")
        
        # Fetch emails
        for i, msg_id in enumerate(message_id_list, 1):
            try:
                logger.info(f"Fetching email {i}/{len(message_id_list)}")
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                
                if status != "OK":
                    logger.warning(f"Failed to fetch email {msg_id}")
                    continue
                
                # Parse email
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Extract headers
                subject = decode_mime_header(msg.get("Subject", ""))
                from_addr = decode_mime_header(msg.get("From", ""))
                to_addr = decode_mime_header(msg.get("To", ""))
                date_str = msg.get("Date", "")
                
                # Parse date
                email_date = None
                if date_str:
                    try:
                        email_date = parsedate_to_datetime(date_str)
                    except Exception as e:
                        logger.warning(f"Failed to parse date '{date_str}': {e}")
                
                # Extract text content
                text_content = extract_email_text(msg)
                
                emails.append({
                    "message_id": msg_id.decode(),
                    "subject": subject,
                    "from": from_addr,
                    "to": to_addr,
                    "date": email_date.isoformat() if email_date else date_str,
                    "text": text_content,
                    "text_length": len(text_content)
                })
                
            except Exception as e:
                logger.error(f"Error processing email {msg_id}: {e}", exc_info=True)
                continue
        
        # Close connection
        mail.close()
        mail.logout()
        
    except Exception as e:
        logger.error(f"IMAP error: {e}", exc_info=True)
    
    return emails


def main():
    parser = argparse.ArgumentParser(
        description="Fetch emails from ProtonMail via IMAP (requires ProtonMail Bridge)"
    )
    parser.add_argument(
        "--imap-host",
        type=str,
        default="localhost",
        help="IMAP server hostname (default: localhost for Bridge)"
    )
    parser.add_argument(
        "--imap-port",
        type=int,
        default=1143,
        help="IMAP server port (default: 1143 for Bridge)"
    )
    parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="Email username"
    )
    parser.add_argument(
        "--password",
        type=str,
        help="Email password (will prompt if not provided)"
    )
    parser.add_argument(
        "--folder",
        type=str,
        default="INBOX",
        help="Mailbox folder to search (default: INBOX)"
    )
    parser.add_argument(
        "--search-subject",
        type=str,
        help="Search for emails with this keyword in subject"
    )
    parser.add_argument(
        "--search-sender",
        type=str,
        help="Search for emails from this sender"
    )
    parser.add_argument(
        "--days-back",
        type=int,
        help="Only fetch emails from last N days"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of emails to fetch"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="fetched_emails.json",
        help="Output file path (default: fetched_emails.json)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format: json or text (default: json)"
    )
    
    args = parser.parse_args()
    
    # Get password if not provided
    password = args.password or getpass.getpass("Enter email password: ")
    
    # Fetch emails
    emails = fetch_emails_imap(
        imap_host=args.imap_host,
        imap_port=args.imap_port,
        username=args.username,
        password=password,
        folder=args.folder,
        search_subject=args.search_subject,
        search_sender=args.search_sender,
        days_back=args.days_back,
        limit=args.limit
    )
    
    logger.info(f"Fetched {len(emails)} emails")
    
    # Sort by date (newest first)
    emails.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    # Write output
    output_path = Path(args.output)
    if args.format == "json":
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(emails, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(emails)} emails to {output_path}")
    else:
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, email_data in enumerate(emails, 1):
                f.write(f"\n{'='*80}\n")
                f.write(f"Email {i}/{len(emails)}\n")
                f.write(f"{'='*80}\n")
                f.write(f"Subject: {email_data.get('subject', 'N/A')}\n")
                f.write(f"From: {email_data.get('from', 'N/A')}\n")
                f.write(f"Date: {email_data.get('date', 'N/A')}\n")
                f.write(f"\nContent:\n{email_data.get('text', 'N/A')}\n")
                f.write("\n")
        logger.info(f"Saved {len(emails)} emails to {output_path}")
    
    # Print summary
    total_text_length = sum(e.get("text_length", 0) for e in emails)
    logger.info(f"Total text extracted: {total_text_length:,} characters")


if __name__ == "__main__":
    main()



