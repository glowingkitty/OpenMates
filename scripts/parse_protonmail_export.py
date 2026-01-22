#!/usr/bin/env python3
"""
Script to parse ProtonMail exported EML files and extract text content.

This script:
1. Scans a directory of exported EML files
2. Extracts email metadata (subject, sender, date)
3. Extracts plain text content from emails
4. Optionally filters by criteria (subject keywords, sender, date range)
5. Outputs to JSON or text file for LLM processing

Usage:
    python scripts/parse_protonmail_export.py --export-dir /path/to/exported/emails
    python scripts/parse_protonmail_export.py --export-dir /path/to/exported/emails --filter-subject "support" --output support_emails.json
    python scripts/parse_protonmail_export.py --export-dir /path/to/exported/emails --output all_emails.txt --format text
"""

import argparse
import email
import json
import logging
from datetime import datetime
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
    """
    Decode MIME-encoded email headers (subject, from, etc.).
    
    Args:
        header_value: The header value to decode
        
    Returns:
        Decoded string
    """
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
    """
    Extract plain text from an email message.
    Tries to get plain text, falls back to HTML if needed.
    
    Args:
        msg: Email message object
        
    Returns:
        Extracted text content
    """
    text_content = ""
    
    # Try to get plain text first
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Skip attachments
            if "attachment" in content_disposition:
                continue
            
            # Get plain text
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        text_content = payload.decode(charset, errors='ignore')
                        break
                except Exception as e:
                    logger.warning(f"Failed to decode text/plain part: {e}")
            
            # Fallback to HTML if no plain text found
            elif content_type == "text/html" and not text_content:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        html_content = payload.decode(charset, errors='ignore')
                        # Simple HTML stripping (you might want to use BeautifulSoup for better results)
                        import re
                        text_content = re.sub(r'<[^>]+>', '', html_content)
                        text_content = re.sub(r'\s+', ' ', text_content).strip()
                except Exception as e:
                    logger.warning(f"Failed to decode text/html part: {e}")
    else:
        # Single part message
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                text_content = payload.decode(charset, errors='ignore')
        except Exception as e:
            logger.warning(f"Failed to decode single part message: {e}")
    
    return text_content.strip()


def parse_eml_file(eml_path: Path) -> Optional[Dict]:
    """
    Parse a single EML file and extract email data.
    
    Args:
        eml_path: Path to the EML file
        
    Returns:
        Dictionary with email data or None if parsing fails
    """
    try:
        with open(eml_path, 'rb') as f:
            msg = email.message_from_bytes(f.read())
        
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
        
        return {
            "file": str(eml_path.name),
            "subject": subject,
            "from": from_addr,
            "to": to_addr,
            "date": email_date.isoformat() if email_date else date_str,
            "text": text_content,
            "text_length": len(text_content)
        }
    except Exception as e:
        logger.error(f"Failed to parse {eml_path}: {e}", exc_info=True)
        return None


def filter_emails(
    emails: List[Dict],
    subject_keywords: Optional[List[str]] = None,
    sender_keywords: Optional[List[str]] = None,
    min_date: Optional[datetime] = None,
    max_date: Optional[datetime] = None
) -> List[Dict]:
    """
    Filter emails based on criteria.
    
    Args:
        emails: List of email dictionaries
        subject_keywords: Keywords to search in subject (case-insensitive)
        sender_keywords: Keywords to search in sender (case-insensitive)
        min_date: Minimum date filter
        max_date: Maximum date filter
        
    Returns:
        Filtered list of emails
    """
    filtered = emails
    
    if subject_keywords:
        filtered = [
            e for e in filtered
            if any(keyword.lower() in e.get("subject", "").lower() for keyword in subject_keywords)
        ]
    
    if sender_keywords:
        filtered = [
            e for e in filtered
            if any(keyword.lower() in e.get("from", "").lower() for keyword in sender_keywords)
        ]
    
    if min_date or max_date:
        filtered_with_dates = []
        for e in filtered:
            date_str = e.get("date", "")
            if date_str:
                try:
                    email_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    if min_date and email_date < min_date:
                        continue
                    if max_date and email_date > max_date:
                        continue
                    filtered_with_dates.append(e)
                except Exception:
                    # If date parsing fails, include the email anyway
                    filtered_with_dates.append(e)
        filtered = filtered_with_dates
    
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Parse ProtonMail exported EML files and extract text content"
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        required=True,
        help="Directory containing exported EML files"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="extracted_emails.json",
        help="Output file path (default: extracted_emails.json)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format: json or text (default: json)"
    )
    parser.add_argument(
        "--filter-subject",
        type=str,
        nargs="+",
        help="Filter emails by subject keywords (case-insensitive)"
    )
    parser.add_argument(
        "--filter-sender",
        type=str,
        nargs="+",
        help="Filter emails by sender keywords (case-insensitive)"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search for EML files recursively in subdirectories"
    )
    
    args = parser.parse_args()
    
    export_dir = Path(args.export_dir)
    if not export_dir.exists():
        logger.error(f"Export directory does not exist: {export_dir}")
        return
    
    # Find all EML files
    if args.recursive:
        eml_files = list(export_dir.rglob("*.eml"))
    else:
        eml_files = list(export_dir.glob("*.eml"))
    
    logger.info(f"Found {len(eml_files)} EML files to process")
    
    # Parse all emails
    emails = []
    for eml_file in eml_files:
        email_data = parse_eml_file(eml_file)
        if email_data:
            emails.append(email_data)
    
    logger.info(f"Successfully parsed {len(emails)} emails")
    
    # Apply filters
    if args.filter_subject or args.filter_sender:
        emails = filter_emails(
            emails,
            subject_keywords=args.filter_subject,
            sender_keywords=args.filter_sender
        )
        logger.info(f"After filtering: {len(emails)} emails")
    
    # Sort by date (newest first)
    emails.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    # Write output
    output_path = Path(args.output)
    if args.format == "json":
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(emails, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(emails)} emails to {output_path}")
    else:
        # Text format: one email per section
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



