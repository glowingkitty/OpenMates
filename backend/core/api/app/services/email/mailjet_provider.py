"""
Mailjet email provider implementation.

Mailjet is an email service provider (fallback option).
API Documentation: https://dev.mailjet.com/email/guides/send-api-v31/
"""

import logging
import json
import aiohttp
from typing import Dict, Any, Optional
from urllib.parse import quote

from backend.core.api.app.services.email.base_provider import BaseEmailProvider

logger = logging.getLogger(__name__)


class MailjetProvider(BaseEmailProvider):
    """
    Mailjet email provider implementation.
    
    Mailjet API v3.1 endpoint: https://api.mailjet.com/v3.1/send
    Authentication: Basic Auth with API key and secret
    """
    
    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize Mailjet provider.
        
        Args:
            api_key: Mailjet API key
            api_secret: Mailjet API secret
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_url = "https://api.mailjet.com/v3.1/send"
        # Contact lookup uses v3 REST, GDPR deletion uses v4 endpoint
        self.contact_lookup_base_url = "https://api.mailjet.com/v3/REST/contact"
        self.gdpr_delete_base_url = "https://api.mailjet.com/v4/contacts"
    
    def get_provider_name(self) -> str:
        """Get the provider name."""
        return "Mailjet"
    
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
        Send email via Mailjet API v3.1.
        
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
            # Prepare the email data for Mailjet API v3.1
            email_data = {
                "Messages": [
                    {
                        "From": {
                            "Name": sender_name,
                            "Email": sender_email
                        },
                        "To": [
                            {
                                "Email": recipient_email,
                                "Name": recipient_name or recipient_email
                            }
                        ],
                        "Subject": subject,
                        "HTMLPart": html_content,
                        "TextPart": plain_text_content,
                        "Headers": email_headers,
                        "Attachments": [
                            {
                                "ContentType": "application/pdf",  # Assuming PDF for now, might need adjustment
                                "Filename": att["filename"],
                                "Base64Content": att["content"]
                            } for att in attachments
                        ] if attachments else []
                    }
                ]
            }
            
            # Send the email via Mailjet API
            async with aiohttp.ClientSession() as session:
                auth = aiohttp.BasicAuth(self.api_key, self.api_secret)
                headers = {
                    "Content-Type": "application/json"
                }
                
                logger.debug(f"Sending email via Mailjet API to {self.api_url}")
                async with session.post(
                    self.api_url,
                    auth=auth,
                    headers=headers,
                    data=json.dumps(email_data)
                ) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        try:
                            response_data = json.loads(response_text)
                            logger.debug(f"Mailjet API response: {json.dumps(response_data)}")
                            
                            # Mailjet v3.1 API response structure: {'Messages': [{'Status': 'success', 'To': [...], 'Errors': [...]}]}
                            messages = response_data.get('Messages', [])
                            if not messages:
                                logger.error(f"Mailjet returned 200 but no Messages in response: {response_data}")
                                return False
                            
                            # Check each message for Status and Errors
                            has_errors = False
                            for msg in messages:
                                status = msg.get('Status', 'unknown')
                                if status != 'success':
                                    has_errors = True
                                    logger.error(f"Mailjet API message status is not 'success': Status={status}, Message: {msg}")
                                
                                errors = msg.get('Errors', [])
                                if errors:
                                    has_errors = True
                                    for error in errors:
                                        logger.error(f"Mailjet API error in message: {error.get('ErrorMessage', 'Unknown error')} (ErrorCode: {error.get('ErrorCode', 'unknown')})")
                            
                            if has_errors:
                                logger.error(f"Mailjet API returned errors or non-success status despite 200 HTTP status. Full response: {response_data}")
                                return False
                            
                            # Extract message ID
                            message_id = 'unknown'
                            message_uuid = 'unknown'
                            to_recipients = messages[0].get('To', [])
                            if to_recipients and isinstance(to_recipients, list) and len(to_recipients) > 0:
                                message_id = to_recipients[0].get('MessageID', 'unknown')
                                message_uuid = to_recipients[0].get('MessageUUID', 'unknown')
                            
                            if message_id == 'unknown':
                                logger.warning(f"Mailjet response structure unexpected - MessageID not found. Response: {response_data}")
                                logger.info(f"Email sent successfully (Message ID not found in expected format, but HTTP 200, Status=success, and no errors)")
                            else:
                                logger.info(f"Email sent successfully via Mailjet. Message ID: {message_id}, Message UUID: {message_uuid}")

                            return True
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse Mailjet JSON response: {e}. Response text: {response_text[:500]}")
                            return False
                    else:
                        logger.error(f"Failed to send email via Mailjet. Status: {response.status}, Response: {response_text[:1000]}")
                        # Try to parse error response for more details
                        try:
                            error_data = json.loads(response_text)
                            if 'Messages' in error_data:
                                for msg in error_data.get('Messages', []):
                                    for error in msg.get('Errors', []):
                                        logger.error(f"Mailjet API error: {error.get('ErrorMessage', 'Unknown error')} (ErrorCode: {error.get('ErrorCode', 'unknown')})")
                        except:
                            pass
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending email via Mailjet: {str(e)}", exc_info=True)
            return False
    
    def schedule_contact_cleanup(self, recipient_email: str) -> None:
        """
        Schedule a delayed Celery task to clean up Mailjet contact after email sending.
        
        Uses a 30-second delay to allow Mailjet time to fully process the contact creation
        before attempting deletion. This prevents timing issues where we try to delete
        a contact that hasn't been fully created yet.
        
        Args:
            recipient_email: Email address of the contact to clean up
        """
        try:
            # Import the task function directly
            from backend.core.api.app.tasks.email_tasks.mailjet_contact_cleanup_task import cleanup_mailjet_contact

            # Schedule task with 30-second delay using .delay()
            cleanup_mailjet_contact.apply_async(
                args=[recipient_email],
                countdown=30  # 30-second delay
            )
            logger.info(f"Scheduled delayed Mailjet contact cleanup for {recipient_email[:3]}*** in 30 seconds")
        except Exception as e:
            logger.warning(f"Failed to schedule Mailjet contact cleanup task (non-fatal): {e}")
    
    async def best_effort_delete_contact(
        self,
        session: aiohttp.ClientSession,
        auth: aiohttp.BasicAuth,
        recipient_email: str,
    ) -> None:
        """
        Best-effort removal of the recipient from Mailjet Contacts after a successful send.
        
        Notes:
        - This is best-effort and must not impact delivery success.
        - Mail providers can still keep addresses in delivery logs/suppression lists; this only targets Contacts.
        
        Args:
            session: aiohttp ClientSession
            auth: aiohttp BasicAuth for Mailjet API
            recipient_email: Email address to delete
        """
        try:
            encoded_recipient = quote(recipient_email, safe="")
            lookup_url = f"{self.contact_lookup_base_url}/{encoded_recipient}"

            async with session.get(lookup_url, auth=auth) as lookup_response:
                if lookup_response.status == 404:
                    logger.info("Mailjet contact cleanup: contact not found (non-fatal).")
                    return
                if lookup_response.status != 200:
                    body = await lookup_response.text()
                    logger.warning(
                        f"Mailjet contact lookup returned status {lookup_response.status} (non-fatal). "
                        f"Response: {body[:500]}"
                    )
                    return

                body = await lookup_response.text()
                try:
                    lookup_data = json.loads(body)
                except json.JSONDecodeError:
                    logger.warning(
                        "Mailjet contact lookup returned non-JSON body (non-fatal). "
                        f"Response: {body[:500]}"
                    )
                    return

                contact_id: Optional[Any] = None
                data = lookup_data.get("Data") or []
                if data and isinstance(data, list) and isinstance(data[0], dict):
                    contact_id = data[0].get("ID")

                if not contact_id:
                    logger.warning(
                        f"Mailjet contact lookup did not return a contact ID for {recipient_email} (non-fatal). "
                        f"Response: {str(lookup_data)[:500]}"
                    )
                    return

            delete_url = f"{self.gdpr_delete_base_url}/{contact_id}"
            async with session.delete(delete_url, auth=auth) as delete_response:
                # 200: anonymized, then removed after 30 days; 404: already missing; others warn.
                if delete_response.status in (200, 404):
                    logger.info("Mailjet contact cleanup attempted (non-fatal).")
                    return
                body = await delete_response.text()
                logger.warning(
                    f"Mailjet contact cleanup returned status {delete_response.status} (non-fatal). "
                    f"Response: {body[:500]}"
                )
        except Exception as e:
            logger.warning(f"Mailjet contact cleanup failed (non-fatal): {e}")

