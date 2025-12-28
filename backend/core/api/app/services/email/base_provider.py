"""
Base abstract class for email providers.

All email providers (Brevo, Mailjet, etc.) should inherit from this class
and implement the required methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseEmailProvider(ABC):
    """
    Abstract base class for email providers.
    
    All email providers must implement the send_email method.
    """
    
    @abstractmethod
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
        Send an email via the provider's API.
        
        Args:
            sender_name: Sender's name
            sender_email: Sender's email address
            recipient_email: Recipient's email address
            recipient_name: Recipient's name
            subject: Email subject line
            html_content: HTML email content
            plain_text_content: Plain text email content
            email_headers: Dictionary of email headers
            attachments: Optional list of attachments (dicts with 'filename', 'content' base64 encoded)
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Get the name of the email provider.
        
        Returns:
            Provider name (e.g., "Brevo", "Mailjet")
        """
        pass

