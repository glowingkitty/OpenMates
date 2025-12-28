"""
Brevo (formerly Sendinblue) email provider implementation.

Brevo is an EU-based email service provider with GDPR compliance.
API Documentation: https://developers.brevo.com/reference/sendtransacemail
"""

import logging
import json
import aiohttp
import os
from typing import Dict, Any, Optional, List

from backend.core.api.app.services.email.base_provider import BaseEmailProvider

logger = logging.getLogger(__name__)

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

