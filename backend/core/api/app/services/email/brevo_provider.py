"""
Brevo (formerly Sendinblue) email provider implementation.

Brevo is an EU-based email service provider with GDPR compliance.
API Documentation: https://developers.brevo.com/reference/sendtransacemail

This module provides:
- Email sending via Brevo API v3
- Email event tracking (bounces, deliveries, etc.) via /smtp/logs endpoint
"""

import logging
import json
import aiohttp
import os
from datetime import datetime
from typing import Dict, Any, Optional, List

from backend.core.api.app.services.email.base_provider import BaseEmailProvider

logger = logging.getLogger(__name__)

# Brevo email event types that can be queried via /smtp/statistics/events endpoint
# See: https://developers.brevo.com/reference/getemaileventreport-1
# Note: These are the exact values accepted by the Brevo API (case-sensitive)
BREVO_EVENT_TYPES = {
    "bounces",       # All bounces (hard + soft)
    "hardBounces",   # Permanent delivery failure (e.g., invalid email address)
    "softBounces",   # Temporary failure (e.g., mailbox full, server temporarily unavailable)
    "delivered",     # Email was delivered
    "spam",          # Email marked as spam
    "requests",      # Email requests sent
    "opened",        # Email was opened
    "clicks",        # Link in email was clicked
    "invalid",       # Invalid email address format
    "deferred",      # Email delivery deferred
    "blocked",       # Email was blocked
    "unsubscribed",  # Recipient unsubscribed
    "error",         # Error occurred
    "loadedByProxy", # Loaded by proxy (e.g., Apple Mail Privacy Protection)
}

# Brevo supported file extensions for email attachments
# Based on common email attachment support and Brevo API documentation
# Note: Brevo explicitly rejects .yml files, so we convert them to .txt
BREVO_SUPPORTED_EXTENSIONS = {
    # Documents
    '.pdf', '.txt', '.doc', '.docx', '.rtf',
    # Images
    '.jpg', '.jpeg', '.png', '.gif', '.bmp',
    # Archives
    '.zip',
    # Spreadsheets
    '.xls', '.xlsx', '.csv',
}

# File extensions that should be converted to .txt (text-based formats)
TEXT_FORMATS_TO_CONVERT = {'.yml', '.yaml', '.json', '.xml', '.log'}


class BrevoProvider(BaseEmailProvider):
    """
    Brevo email provider implementation.
    
    Brevo API v3 endpoint: https://api.brevo.com/v3/smtp/email
    Authentication: API key in header "api-key"
    """
    
    def __init__(self, api_key: str):
        """
        Initialize Brevo provider.
        
        Args:
            api_key: Brevo API key
        """
        self.api_key = api_key
        self.api_url = "https://api.brevo.com/v3/smtp/email"
    
    def get_provider_name(self) -> str:
        """Get the provider name."""
        return "Brevo"
    
    def _validate_and_convert_attachment(
        self, 
        attachment: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate and convert attachment file format for Brevo compatibility.
        
        Brevo API has restrictions on file formats. This method:
        1. Checks if the file extension is supported
        2. Converts text-based formats (.yml, .yaml, .json, .xml, .log) to .txt
        3. Filters out unsupported binary formats with a warning
        
        Args:
            attachment: Attachment dict with 'filename' and 'content' keys
            
        Returns:
            Processed attachment dict with converted filename if needed, or None if unsupported
        """
        filename = attachment.get('filename', '')
        if not filename:
            logger.warning("Attachment missing filename, skipping")
            return None
        
        # Extract file extension (case-insensitive)
        _, ext = os.path.splitext(filename)
        ext_lower = ext.lower()
        
        # Check if extension is directly supported
        if ext_lower in BREVO_SUPPORTED_EXTENSIONS:
            logger.debug(f"Attachment '{filename}' has supported extension: {ext_lower}")
            return attachment
        
        # Check if it's a text-based format we can convert to .txt
        if ext_lower in TEXT_FORMATS_TO_CONVERT:
            # Convert to .txt extension
            base_name, _ = os.path.splitext(filename)
            new_filename = f"{base_name}.txt"
            logger.warning(
                f"Converting attachment '{filename}' to '{new_filename}' "
                f"(Brevo does not support {ext_lower} format)"
            )
            return {
                'filename': new_filename,
                'content': attachment['content']  # Content is already base64 encoded
            }
        
        # Unsupported format - log warning and skip
        logger.error(
            f"Attachment '{filename}' has unsupported extension '{ext_lower}'. "
            f"Brevo does not support this file format. Skipping attachment."
        )
        return None
    
    def _process_attachments(
        self, 
        attachments: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Process and validate all attachments for Brevo compatibility.
        
        Args:
            attachments: List of attachment dicts with 'filename' and 'content' keys
            
        Returns:
            List of processed attachments that are compatible with Brevo
        """
        if not attachments:
            return []
        
        processed_attachments = []
        for att in attachments:
            processed = self._validate_and_convert_attachment(att)
            if processed:
                processed_attachments.append(processed)
        
        if len(processed_attachments) < len(attachments):
            skipped_count = len(attachments) - len(processed_attachments)
            logger.warning(
                f"Filtered out {skipped_count} unsupported attachment(s). "
                f"Sending {len(processed_attachments)} compatible attachment(s)."
            )
        
        return processed_attachments
    
    async def send_email(
        self,
        sender_name: str,
        sender_email: str,
        recipient_email: str,
        recipient_name: str,
        subject: str,
        html_content: str,
        plain_text_content: str,
        email_headers: Dict[str, Any],
        attachments: Optional[list],
    ) -> bool:
        """
        Send email via Brevo API v3.
        
        According to Brevo docs: https://developers.brevo.com/reference/sendtransacemail
        - Endpoint: POST https://api.brevo.com/v3/smtp/email
        - Auth: API key in header "api-key"
        - Request: {"sender": {...}, "to": [...], "subject": "...", "htmlContent": "...", "textContent": "...", "headers": {...}, "attachment": [...]}
        - Response: {"messageId": "..."} on success (201 status)
        
        Args:
            sender_name: Sender's name
            sender_email: Sender's email
            recipient_email: Recipient's email
            recipient_name: Recipient's name
            subject: Email subject
            html_content: HTML email content
            plain_text_content: Plain text email content
            email_headers: Email headers dict
            attachments: Optional list of attachments
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            # Prepare email data for Brevo API
            # Brevo API structure: https://developers.brevo.com/reference/sendtransacemail
            email_data = {
                "sender": {
                    "name": sender_name,
                    "email": sender_email
                },
                "to": [
                    {
                        "email": recipient_email,
                        "name": recipient_name or recipient_email
                    }
                ],
                "subject": subject,
                "htmlContent": html_content,
                "textContent": plain_text_content,
            }
            
            # Add headers if provided (Brevo supports custom headers)
            if email_headers:
                email_data["headers"] = email_headers
            
            # Process and validate attachments for Brevo compatibility
            # Brevo attachment format: [{"name": "filename.pdf", "content": "base64content"}]
            # Brevo has restrictions on file formats - we validate and convert unsupported formats
            if attachments:
                processed_attachments = self._process_attachments(attachments)
                if processed_attachments:
                    email_data["attachment"] = [
                        {
                            "name": att["filename"],
                            "content": att["content"]  # Already base64 encoded
                        } for att in processed_attachments
                    ]
                else:
                    logger.warning(
                        "All attachments were filtered out due to unsupported formats. "
                        "Sending email without attachments."
                    )
            
            # Send the email via Brevo API
            async with aiohttp.ClientSession() as session:
                headers = {
                    "accept": "application/json",
                    "api-key": self.api_key,
                    "content-type": "application/json"
                }
                
                logger.debug(f"Sending email via Brevo API to {self.api_url}")
                async with session.post(
                    self.api_url,
                    headers=headers,
                    data=json.dumps(email_data)
                ) as response:
                    response_text = await response.text()
                    
                    # Brevo returns 201 on success, 400 on error
                    if response.status == 201:
                        try:
                            response_data = json.loads(response_text)
                            logger.debug(f"Brevo API response: {json.dumps(response_data)}")
                            
                            # Brevo success response: {"messageId": "..."}
                            message_id = response_data.get('messageId', 'unknown')
                            
                            if message_id == 'unknown':
                                logger.warning(f"Brevo response structure unexpected - messageId not found. Response: {response_data}")
                                logger.info("Email sent successfully (messageId not found in expected format, but HTTP 201)")
                            else:
                                logger.info(f"Email sent successfully via Brevo. Message ID: {message_id}")
                            
                            return True
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse Brevo JSON response: {e}. Response text: {response_text[:500]}")
                            return False
                    else:
                        logger.error(f"Failed to send email via Brevo. Status: {response.status}, Response: {response_text[:1000]}")
                        # Try to parse error response for more details
                        try:
                            error_data = json.loads(response_text)
                            error_message = error_data.get('message', 'Unknown error')
                            error_code = error_data.get('code', 'unknown')
                            logger.error(f"Brevo API error: {error_message} (Code: {error_code})")
                        except Exception:
                            pass
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending email via Brevo: {str(e)}", exc_info=True)
            return False

    async def get_email_events(
        self,
        event_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        days: Optional[int] = None,
        email: Optional[str] = None,
        limit: int = 2500,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Retrieve transactional email events from Brevo.
        
        Brevo API endpoint: GET /smtp/statistics/events
        Docs: https://developers.brevo.com/reference/getemaileventreport-1
        
        This is useful for investigating:
        - Bounced emails (hardBounces, softBounces)
        - Blocked emails
        - Spam reports
        - Delivery status
        
        Args:
            event_type: Filter by event type. Valid values: bounces, hardBounces, softBounces,
                       delivered, spam, requests, opened, clicks, invalid, deferred, blocked, 
                       unsubscribed, error, loadedByProxy
            start_date: Start of date range (datetime object) - uses YYYY-MM-DD format
            end_date: End of date range (datetime object) - uses YYYY-MM-DD format
            days: Alternative to date range - get events from last N days (max 90)
            email: Filter by specific email address
            limit: Number of results to return (default 2500, max 5000)
            offset: Pagination offset (default 0)
            
        Returns:
            Dict containing:
            - events: List of email event objects with email, date, messageId, event, etc.
            - count: Total number of events matching the query
            - error: Error message if request failed (only present on error)
        """
        try:
            # Build query parameters
            # Brevo API has max limit of 5000, default 2500
            params = {
                "limit": min(limit, 5000),
                "offset": offset
            }
            
            # Add event type filter if specified
            if event_type:
                # Validate event type (case-sensitive, use exact values)
                if event_type not in BREVO_EVENT_TYPES:
                    logger.warning(
                        f"Invalid event type '{event_type}'. "
                        f"Valid types: {', '.join(sorted(BREVO_EVENT_TYPES))}"
                    )
                    return {
                        "events": [],
                        "count": 0,
                        "error": f"Invalid event type. Valid types: {', '.join(sorted(BREVO_EVENT_TYPES))}"
                    }
                params["event"] = event_type
            
            # Handle date filtering
            # Note: Cannot use 'days' parameter together with startDate/endDate
            # Brevo API expects dates in YYYY-MM-DD format for this endpoint
            if days is not None:
                if start_date is not None or end_date is not None:
                    logger.warning(
                        "Cannot use 'days' parameter together with start_date/end_date. "
                        "Using 'days' parameter."
                    )
                if days > 90:
                    logger.warning(f"Days parameter {days} exceeds max of 90. Using 90.")
                    days = 90
                params["days"] = days
            else:
                # Use start_date and end_date if provided (format: YYYY-MM-DD)
                if start_date:
                    params["startDate"] = start_date.strftime("%Y-%m-%d")
                if end_date:
                    params["endDate"] = end_date.strftime("%Y-%m-%d")
            
            # Add email filter if specified
            if email:
                params["email"] = email
            
            # Make the API request to /smtp/statistics/events
            # Docs: https://developers.brevo.com/reference/getemaileventreport-1
            events_url = "https://api.brevo.com/v3/smtp/statistics/events"
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    "accept": "application/json",
                    "api-key": self.api_key
                }
                
                logger.debug(f"Fetching email events from Brevo: {events_url} with params: {params}")
                
                async with session.get(
                    events_url,
                    headers=headers,
                    params=params
                ) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            response_data = json.loads(response_text)
                            events = response_data.get("events", [])
                            
                            logger.info(
                                f"Retrieved {len(events)} email events from Brevo "
                                f"(event_type={event_type}, days={days})"
                            )
                            
                            return {
                                "events": events,
                                "count": len(events)
                            }
                        except json.JSONDecodeError as e:
                            logger.error(
                                f"Failed to parse Brevo email events response: {e}. "
                                f"Response text: {response_text[:500]}"
                            )
                            return {
                                "events": [],
                                "count": 0,
                                "error": f"Failed to parse response: {str(e)}"
                            }
                    else:
                        # Handle error response
                        error_message = f"Failed to fetch email events. Status: {response.status}"
                        try:
                            error_data = json.loads(response_text)
                            api_error = error_data.get('message', response_text[:500])
                            error_message = f"{error_message}, Error: {api_error}"
                        except Exception:
                            error_message = f"{error_message}, Response: {response_text[:500]}"
                        
                        logger.error(error_message)
                        return {
                            "events": [],
                            "count": 0,
                            "error": error_message
                        }
                        
        except Exception as e:
            logger.error(f"Error fetching email events from Brevo: {str(e)}", exc_info=True)
            return {
                "events": [],
                "count": 0,
                "error": str(e)
            }

    async def get_bounced_emails(
        self,
        days: int = 30,
        include_soft_bounces: bool = True,
        email: Optional[str] = None,
        limit: int = 500
    ) -> Dict[str, Any]:
        """
        Retrieve bounced email events from Brevo.
        
        This is a convenience method that fetches both hard and soft bounces
        and combines them into a single report for investigation.
        
        Hard bounces = permanent delivery failures (invalid email, domain doesn't exist)
        Soft bounces = temporary failures (mailbox full, server temporarily unavailable)
        
        Args:
            days: Number of days to look back (max 90, default 30)
            include_soft_bounces: Whether to include soft bounces (default True)
            email: Filter by specific email address (optional)
            limit: Maximum number of results per bounce type (default 500)
            
        Returns:
            Dict containing:
            - hard_bounces: List of hard bounce events with email, reason, date, etc.
            - soft_bounces: List of soft bounce events (if include_soft_bounces=True)
            - total_hard_bounces: Count of hard bounces
            - total_soft_bounces: Count of soft bounces
            - summary: Summary statistics by bounce reason
            - error: Error message if request failed (only present on error)
        """
        logger.info(
            f"Fetching bounced emails from Brevo "
            f"(days={days}, include_soft_bounces={include_soft_bounces}, email={email})"
        )
        
        result = {
            "hard_bounces": [],
            "soft_bounces": [],
            "total_hard_bounces": 0,
            "total_soft_bounces": 0,
            "summary": {
                "by_reason": {},
                "by_domain": {}
            }
        }
        
        # Fetch hard bounces
        # Using "hardBounces" as per Brevo API event type values
        hard_bounce_result = await self.get_email_events(
            event_type="hardBounces",
            days=days,
            email=email,
            limit=limit
        )
        
        if "error" in hard_bounce_result:
            logger.error(f"Error fetching hard bounces: {hard_bounce_result['error']}")
            result["error"] = hard_bounce_result["error"]
        else:
            result["hard_bounces"] = hard_bounce_result["events"]
            result["total_hard_bounces"] = hard_bounce_result["count"]
        
        # Fetch soft bounces if requested
        # Using "softBounces" as per Brevo API event type values
        if include_soft_bounces:
            soft_bounce_result = await self.get_email_events(
                event_type="softBounces",
                days=days,
                email=email,
                limit=limit
            )
            
            if "error" in soft_bounce_result:
                logger.error(f"Error fetching soft bounces: {soft_bounce_result['error']}")
                if "error" not in result:
                    result["error"] = soft_bounce_result["error"]
            else:
                result["soft_bounces"] = soft_bounce_result["events"]
                result["total_soft_bounces"] = soft_bounce_result["count"]
        
        # Generate summary statistics
        all_bounces = result["hard_bounces"] + result["soft_bounces"]
        
        # Group by reason
        for bounce in all_bounces:
            reason = bounce.get("reason", "Unknown")
            # Truncate long reasons for summary
            if len(reason) > 100:
                reason = reason[:100] + "..."
            
            if reason not in result["summary"]["by_reason"]:
                result["summary"]["by_reason"][reason] = 0
            result["summary"]["by_reason"][reason] += 1
            
            # Group by domain
            email_addr = bounce.get("email", "")
            if "@" in email_addr:
                domain = email_addr.split("@")[1].lower()
                if domain not in result["summary"]["by_domain"]:
                    result["summary"]["by_domain"][domain] = 0
                result["summary"]["by_domain"][domain] += 1
        
        # Sort summary by count (descending)
        result["summary"]["by_reason"] = dict(
            sorted(
                result["summary"]["by_reason"].items(), 
                key=lambda x: x[1], 
                reverse=True
            )
        )
        result["summary"]["by_domain"] = dict(
            sorted(
                result["summary"]["by_domain"].items(), 
                key=lambda x: x[1], 
                reverse=True
            )
        )
        
        logger.info(
            f"Bounced email report: "
            f"{result['total_hard_bounces']} hard bounces, "
            f"{result['total_soft_bounces']} soft bounces"
        )
        
        return result

